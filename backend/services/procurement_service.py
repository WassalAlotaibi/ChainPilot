
"""ChainPilot procurement: split sourcing, approvals, receipts and clear blockers."""

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR

from backend.database.connection import get_db
from backend.services.inventory_service import get_inventory
from backend.services.policy_engine import get_policy, rank_suppliers

ACTIVE_STATUSES = (
    "pending_approval", "placed", "delayed", "shipped",
    "awaiting_receipt", "partially_received",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def record_log(db, action, details):
    db.execute(
        "INSERT INTO agent_logs(timestamp, action, details) VALUES (?, ?, ?)",
        (utc_now(), action, json.dumps(details, default=str)),
    )


def get_purchase_orders(db=None):
    if db is None:
        with get_db() as connection:
            return get_purchase_orders(connection)

    return [
        dict(row)
        for row in db.execute(
            """
            SELECT po.*, s.name AS supplier,
                   MAX(0, po.fulfillable_quantity - po.received_quantity)
                   AS outstanding_quantity
            FROM purchase_orders AS po
            JOIN suppliers AS s ON s.id = po.supplier_id
            ORDER BY po.id DESC
            """
        ).fetchall()
    ]


def committed_cost(db):
    """Current unreceived-order value, including pending approvals."""
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    result = db.execute(
        f"""
        SELECT COALESCE(SUM(
            MAX(0, fulfillable_quantity - received_quantity) * unit_price
        ), 0) AS total
        FROM purchase_orders
        WHERE status IN ({placeholders})
        """,
        ACTIVE_STATUSES,
    ).fetchone()
    return Decimal(str(result["total"]))


def _blocker(db, component, missing, budget_left, policy):
    """Explain the CURRENT reason why the remaining quantity isn't covered."""
    suppliers = [
        dict(row)
        for row in db.execute(
            """
            SELECT name, available, approved, unit_price, delivery_days
            FROM suppliers WHERE component = ?
            """,
            (component,),
        )
    ]

    in_stock = [s for s in suppliers if s["available"] > 0]
    approved = [
        s for s in in_stock if s["approved"] and s["unit_price"] > 0
    ]
    eligible = [
        s for s in approved
        if s["delivery_days"] <= policy["max_delivery_days"]
    ]
    eligible_units = sum(int(s["available"]) for s in eligible)
    reasons = []

    if not in_stock:
        status = "waiting_supplier_stock"
        reasons.append("All listed suppliers are out of stock.")
    elif not approved:
        status = "supplier_approval_required"
        reasons.append("Suppliers have stock, but none is approved for new orders.")
    elif not eligible:
        status = "delivery_policy_block"
        reasons.append("Available suppliers exceed the allowed delivery time.")
    elif budget_left <= 0:
        status = "budget_exhausted"
        reasons.append("The outstanding purchasing budget is fully committed.")
    else:
        cheapest = min(Decimal(str(s["unit_price"])) for s in eligible)
        if budget_left < cheapest:
            status = "budget_limited"
            reasons.append("The remaining budget cannot buy even one eligible unit.")
        elif eligible_units < missing:
            status = "partial_supplier_capacity"
            reasons.append(
                f"Eligible suppliers have only {eligible_units} units "
                f"for {missing} remaining units."
            )
        else:
            status = "budget_limited"
            reasons.append(
                "Available stock exists, but the remaining budget or "
                "policy-based allocation cannot cover the full requirement."
            )

    if eligible and eligible_units < missing and status != "partial_supplier_capacity":
        reasons.append(
            f"Eligible supplier stock is also limited to {eligible_units} units."
        )
    if budget_left <= 0 and status != "budget_exhausted":
        reasons.append("The purchasing budget also has no remaining capacity.")

    return {
        "status": status,
        "reason": " ".join(reasons),
        "supplier_units_available": sum(max(0, s["available"]) for s in suppliers),
        "eligible_supplier_units": eligible_units,
    }


def evaluate_procurement():
    """Atomically source uncovered shortages, splitting across suppliers."""
    actions = []

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        policy = get_policy(db)
        budget_left = max(
            Decimal("0"),
            Decimal(str(policy["max_budget"])) - committed_cost(db),
        )
        approval_threshold = Decimal(str(policy["approval_threshold"]))

        for item in get_inventory(db):
            needed = int(item["uncovered_shortage"])
            if needed <= 0:
                continue

            remaining = needed
            allocations = []
            suppliers = rank_suppliers(item["component"], needed, db)

            for supplier in suppliers:
                if remaining == 0:
                    break
                unit_price = Decimal(str(supplier["unit_price"]))
                if unit_price <= 0:
                    continue

                affordable = int(
                    (budget_left / unit_price).to_integral_value(
                        rounding=ROUND_FLOOR
                    )
                )
                quantity = min(
                    remaining, int(supplier["available"]), affordable
                )
                if quantity <= 0:
                    continue

                cost = unit_price * quantity
                allocations.append((supplier, quantity, cost))
                remaining -= quantity
                budget_left -= cost

            # Approval applies to the total split plan for this component.
            plan_cost = sum((cost for _, _, cost in allocations), Decimal("0"))
            order_status = (
                "pending_approval" if plan_cost > approval_threshold else "placed"
            )

            for supplier, quantity, cost in allocations:
                reservation = db.execute(
                    """
                    UPDATE suppliers SET available = available - ?
                    WHERE id = ? AND approved = 1 AND available >= ?
                    """,
                    (quantity, supplier["id"], quantity),
                )
                if reservation.rowcount != 1:
                    raise RuntimeError(
                        "Supplier availability changed; procurement rolled back."
                    )

                now = utc_now()
                order = db.execute(
                    """
                    INSERT INTO purchase_orders(
                        component, supplier_id, quantity, total_cost, status,
                        created_at, fulfillable_quantity, received_quantity,
                        unit_price, expected_delivery_days, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["component"], supplier["id"], quantity, float(cost),
                        order_status, now, quantity, 0, supplier["unit_price"],
                        supplier["delivery_days"], now,
                    ),
                )
                action = {
                    "action": order_status,
                    "order_id": order.lastrowid,
                    "component": item["component"],
                    "supplier": supplier["name"],
                    "quantity": quantity,
                    "total_cost": float(cost),
                    "score": supplier["score"],
                    "split_plan_cost": float(plan_cost),
                    "reason": "Selected by company policy; quantity limited by stock and budget.",
                }
                actions.append(action)
                record_log(db, "procurement_order", action)

            if remaining > 0:
                info = _blocker(
                    db, item["component"], remaining, budget_left, policy
                )
                escalation = {
                    "action": "escalated",
                    "component": item["component"],
                    "uncovered_quantity": remaining,
                    "status": info["status"],
                    "reason": info["reason"],
                    "supplier_units_available": info["supplier_units_available"],
                    "eligible_supplier_units": info["eligible_supplier_units"],
                }
                actions.append(escalation)
                record_log(db, "procurement_escalation", escalation)

        if not actions:
            record_log(
                db, "procurement_no_action",
                {"reason": "No uncovered need, or all needs covered by existing orders."},
            )

    return {"actions": actions}


def approve_purchase_order(order_id):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        order = db.execute(
            "SELECT * FROM purchase_orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise LookupError("Purchase order not found")
        if order["status"] != "pending_approval":
            raise ValueError("Only pending orders can be approved")

        db.execute(
            "UPDATE purchase_orders SET status = 'placed', updated_at = ? WHERE id = ?",
            (utc_now(), order_id),
        )
        record_log(db, "order_approved", {"order_id": order_id})

    return {"order_id": order_id, "status": "placed"}


def receive_purchase_order(order_id, quantity, receipt_id):
    """Warehouse-confirmed receipt; duplicate receipt IDs cannot add stock twice."""
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        old_receipt = db.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if old_receipt is not None:
            if (
                old_receipt["order_id"] != order_id
                or old_receipt["quantity"] != quantity
            ):
                raise ValueError("Receipt ID reused for a different delivery")
            return {
                "order_id": order_id,
                "receipt_id": receipt_id,
                "quantity_added": 0,
                "already_processed": True,
            }

        order = db.execute(
            "SELECT * FROM purchase_orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise LookupError("Purchase order not found")
        if order["status"] not in (
            "placed", "delayed", "shipped", "awaiting_receipt", "partially_received"
        ):
            raise ValueError("Order must be approved and active before receiving")

        remaining = order["fulfillable_quantity"] - order["received_quantity"]
        if quantity <= 0 or quantity > remaining:
            raise ValueError(f"Receipt must be between 1 and {remaining} units")

        changed = db.execute(
            "UPDATE inventory SET stock = stock + ? WHERE component = ?",
            (quantity, order["component"]),
        )
        if changed.rowcount != 1:
            raise RuntimeError("Inventory component missing")

        received = order["received_quantity"] + quantity
        status = (
            "received" if received == order["fulfillable_quantity"]
            else "partially_received"
        )
        db.execute(
            """
            UPDATE purchase_orders
            SET received_quantity = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (received, status, utc_now(), order_id),
        )
        db.execute(
            """
            INSERT INTO receipts(receipt_id, order_id, quantity, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (receipt_id, order_id, quantity, utc_now()),
        )
        result = {
            "order_id": order_id,
            "receipt_id": receipt_id,
            "status": status,
            "quantity_added": quantity,
            "total_received": received,
            "already_processed": False,
        }
        record_log(db, "warehouse_receipt", result)
        return result
