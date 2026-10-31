
import json
import os
import uuid
from decimal import Decimal

from backend.database.connection import get_db
from backend.services.policy_engine import get_policy, rank_suppliers
from backend.services.procurement_service import (
    committed_cost,
    evaluate_procurement,
    record_log,
    utc_now,
)


REVIEWABLE = (
    "placed",
    "delayed",
    "pending_approval",
)


def auto_confirm_enabled():
    return os.getenv(
        "DEMO_AUTO_CONFIRM_CANCELLATION", "false"
    ).lower() in ("true", "1", "yes")


def find_replacement(db, order, policy):
    """
    Look for a full replacement using OTHER suppliers.

    No cancellation occurs here.
    This only checks whether switching is feasible.
    """
    needed = max(
        0,
        int(order["fulfillable_quantity"])
        - int(order["received_quantity"])
    )

    if needed == 0:
        return None

    candidates = [
        supplier
        for supplier in rank_suppliers(
            order["component"], needed, db
        )
        if supplier["id"] != order["supplier_id"]
    ]

    if not candidates:
        return None

    remaining = needed
    allocations = []
    total = Decimal("0")

    for supplier in candidates:
        if remaining == 0:
            break

        quantity = min(
            remaining,
            int(supplier["available"])
        )

        if quantity <= 0:
            continue

        allocations.append({
            "supplier": supplier["name"],
            "supplier_id": supplier["id"],
            "quantity": quantity,
            "unit_price": supplier["unit_price"],
            "delivery_days": supplier["delivery_days"],
        })

        remaining -= quantity
        total += (
            Decimal(str(supplier["unit_price"]))
            * quantity
        )

    # Don't cancel unless a complete replacement
    # is feasible.
    if remaining > 0:
        return None

    old_cost = (
        Decimal(str(order["unit_price"]))
        * needed
    )

    budget_after_cancellation = (
        Decimal(str(policy["max_budget"]))
        - committed_cost(db)
        + old_cost
    )

    if total > budget_after_cancellation:
        return None

    return {
        "quantity": needed,
        "total_cost": float(total),
        "old_cost": float(old_cost),
        "delivery_days": max(
            item["delivery_days"]
            for item in allocations
        ),
        "allocations": allocations,
    }


def confirm_cancellation_locked(
    db,
    order,
    initiated_by
):
    """
    Confirm cancellation within an existing
    write transaction.

    Never release reservations just because
    cancellation was requested.
    """
    if order["status"] not in (
        "cancellation_requested",
        "pending_approval"
    ):
        raise ValueError(
            "This order cannot be cancelled "
            "through the recovery workflow"
        )

    remaining = max(
        0,
        int(order["fulfillable_quantity"])
        - int(order["received_quantity"])
    )

    # Return reserved units to the original
    # supplier's available inventory.
    #
    # Pause the supplier after cancellation
    # to prevent immediately selecting the
    # same delayed supplier again.
    if order["status"] == "cancellation_requested":
        db.execute(
            """
            UPDATE suppliers
            SET available = available + ?,
                approved = 0
            WHERE id = ?
            """,
            (remaining, order["supplier_id"])
        )

    else:
        db.execute(
            """
            UPDATE suppliers
            SET available = available + ?
            WHERE id = ?
            """,
            (remaining, order["supplier_id"])
        )

    # Original order no longer commits
    # the unreceived quantity.
    db.execute(
        """
        UPDATE purchase_orders
        SET status = 'cancelled',
            fulfillable_quantity = received_quantity,
            updated_at = ?
        WHERE id = ?
        """,
        (utc_now(), order["id"])
    )

    record_log(
        db,
        "recovery_cancellation_confirmed",
        {
            "order_id": order["id"],
            "component": order["component"],
            "supplier_id": order["supplier_id"],
            "units_released": remaining,
            "initiated_by": initiated_by,
            "reason": (
                "Cancellation confirmed before shipment. "
                "Supplier reservation and outstanding "
                "purchasing commitment released."
            ),
        }
    )

    return remaining


def review_recovery(trigger, order_id=None):
    """
    Review an affected order, or all reviewable
    orders after a policy change.
    """
    decisions = []

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        policy = get_policy(db)

        if order_id is None:
            orders = db.execute(
                """
                SELECT po.*, s.name AS supplier
                FROM purchase_orders po
                JOIN suppliers s
                  ON s.id = po.supplier_id
                WHERE po.status IN (
                    'placed',
                    'delayed',
                    'pending_approval'
                )
                ORDER BY po.id
                """
            ).fetchall()

        else:
            orders = db.execute(
                """
                SELECT po.*, s.name AS supplier
                FROM purchase_orders po
                JOIN suppliers s
                  ON s.id = po.supplier_id
                WHERE po.id = ?
                """,
                (order_id,)
            ).fetchall()

        for order in orders:
            if order["status"] not in REVIEWABLE:
                continue

            if (
                trigger == "supplier_delay"
                and order["status"] != "delayed"
            ):
                continue

            outstanding = (
                int(order["fulfillable_quantity"])
                - int(order["received_quantity"])
            )

            if outstanding <= 0:
                continue

            old_days = int(
                order["expected_delivery_days"] or 999
            )

            speed_first = (
                policy["speed_weight"]
                > policy["cost_weight"]
                and policy["speed_weight"]
                > policy["reliability_weight"]
            )

            cost_first = (
                policy["cost_weight"]
                > policy["speed_weight"]
                and policy["cost_weight"]
                > policy["reliability_weight"]
            )

            plan = find_replacement(db, order, policy)

            decision = "keep_order"
            reason = (
                "No justified replacement was identified."
            )

            # COST FIRST or BALANCED:
            # preserve delayed commitment unless
            # an explicit policy rule justifies switching.
            if order["status"] == "delayed" and not speed_first:
                reason = (
                    f"The supplier's revised delivery is "
                    f"{old_days} days. Current policy "
                    "does not prioritize speed above "
                    "all other factors. ChainPilot "
                    "will keep the order and record "
                    "the delivery risk."
                )

            elif plan is None:
                reason = (
                    "No complete replacement is available "
                    "within supplier stock, delivery limits "
                    "and outstanding purchasing budget."
                )

            elif speed_first:
                new_days = plan["delivery_days"]

                if new_days < old_days:
                    decision = "request_cancellation"
                    reason = (
                        f"Delivery speed has highest priority. "
                        f"Alternative suppliers can deliver "
                        f"all {outstanding} units in "
                        f"{new_days} days instead of "
                        f"{old_days} days, within budget."
                    )

                else:
                    reason = (
                        "No eligible alternative "
                        "can deliver sooner."
                    )

            elif cost_first and trigger == "policy_changed":
                if (
                    plan["total_cost"]
                    <= plan["old_cost"] * 0.95
                ):
                    decision = "request_cancellation"
                    reason = (
                        "The updated cost-first policy "
                        "identified a complete alternative "
                        "with at least 5% savings."
                    )

                else:
                    reason = (
                        "Changing suppliers would not "
                        "save at least 5%."
                    )

            elif order["status"] == "delayed":
                reason = (
                    "ChainPilot is retaining the active "
                    "order and recording its delivery risk."
                )

            policy_name = (
                "Production First"
                if speed_first
                else "Budget First"
                if cost_first
                else "Balanced"
            )

            record = {
                "decision_id": uuid.uuid4().hex,
                "order_id": int(order["id"]),
                "supplier": order["supplier"],
                "component": order["component"],
                "outstanding_units": outstanding,
                "expected_delivery_days": old_days,
                "policy": policy_name,
                "trigger": trigger,
                "decision": decision,
                "reason": reason,
                "replacement": (
                    plan
                    if decision == "request_cancellation"
                    else None
                ),
                "status": (
                    "kept"
                    if decision == "keep_order"
                    else "awaiting_supplier_confirmation"
                ),
            }

            if decision == "request_cancellation":

                # An unapproved order can be
                # cancelled before being sent.
                if order["status"] == "pending_approval":
                    confirm_cancellation_locked(
                        db,
                        order,
                        "Unapproved order revised"
                    )
                    record["status"] = (
                        "cancelled_before_approval"
                    )

                else:
                    db.execute(
                        """
                        UPDATE purchase_orders
                        SET status = 'cancellation_requested',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (utc_now(), order["id"])
                    )

                    record_log(
                        db,
                        "recovery_cancellation_requested",
                        {
                            "order_id": order["id"],
                            "supplier": order["supplier"],
                            "component": order["component"],
                            "reason": reason,
                        }
                    )

                    # LOCAL DEMO ONLY:
                    # Simulates a supplier's confirmation.
                    if auto_confirm_enabled():
                        updated = db.execute(
                            """
                            SELECT *
                            FROM purchase_orders
                            WHERE id = ?
                            """,
                            (order["id"],)
                        ).fetchone()

                        confirm_cancellation_locked(
                            db,
                            updated,
                            "Simulated supplier confirmation"
                        )

                        record["status"] = (
                            "simulated_cancellation_confirmed"
                        )

            record_log(
                db,
                "recovery_decision",
                record
            )

            decisions.append(record)

    return decisions


def confirm_cancellation(order_id):
    """
    Manually simulate supplier confirmation.
    Called only by the controlled demo API.
    """
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        order = db.execute(
            """
            SELECT *
            FROM purchase_orders
            WHERE id = ?
            """,
            (order_id,)
        ).fetchone()

        if order is None:
            raise LookupError("Order not found")

        if order["status"] != "cancellation_requested":
            raise ValueError(
                "This order has no pending "
                "cancellation request"
            )

        released = confirm_cancellation_locked(
            db,
            order,
            "Simulated supplier confirmation"
        )

        record_log(
            db,
            "recovery_decision",
            {
                "order_id": order_id,
                "component": order["component"],
                "decision": "cancellation_confirmed",
                "status": "confirmed",
                "reason": (
                    f"The supplier confirmed cancellation; "
                    f"{released} units can now be re-sourced."
                ),
            }
        )

    return {
        "order_id": order_id,
        "cancelled": True,
        "units_released": released,
    }


def execute_replacements():
    """
    Run the EXISTING procurement engine only
    after cancellation has been committed.
    """
    result = evaluate_procurement()

    with get_db() as db:
        record_log(
            db,
            "recovery_replacement_evaluation",
            result
        )

    return result


def recent_recovery_decisions():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT *
            FROM agent_logs
            WHERE action = 'recovery_decision'
            ORDER BY id DESC
            LIMIT 80
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            **json.loads(row["details"]),
        }
        for row in rows
    ]
