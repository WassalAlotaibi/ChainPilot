
import json
from datetime import datetime, timezone

from backend.database.connection import get_db
from backend.services.inventory_service import get_inventory
from backend.services.policy_engine import (
    get_policy,
    rank_suppliers
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def record_log(db, action, details):
    db.execute(
        """
        INSERT INTO agent_logs(timestamp, action, details)
        VALUES (?, ?, ?)
        """,
        (
            utc_now(),
            action,
            json.dumps(details, default=str)
        )
    )


def get_purchase_orders(db=None):
    if db is None:
        with get_db() as connection:
            return get_purchase_orders(connection)

    rows = db.execute("""
        SELECT
            po.*,
            s.name AS supplier,
            MAX(
                po.fulfillable_quantity -
                po.received_quantity,
                0
            ) AS outstanding_quantity
        FROM purchase_orders po
        JOIN suppliers s
          ON s.id = po.supplier_id
        ORDER BY po.id DESC
    """).fetchall()

    return [dict(row) for row in rows]


def evaluate_procurement():
    actions = []

    with get_db() as db:
        # Prevent concurrent evaluations from
        # creating orders for the same shortage.
        db.execute("BEGIN IMMEDIATE")

        policy = get_policy(db)

        for item in get_inventory(db):
            shortage = item["uncovered_shortage"]

            if shortage == 0:
                continue

            candidates = rank_suppliers(
                item["component"],
                shortage,
                db
            )

            if not candidates:
                action = {
                    "component": item["component"],
                    "shortage": shortage,
                    "action": "escalated",
                    "reason": (
                        "No eligible supplier satisfies "
                        "the current company policy"
                    )
                }

            else:
                best = candidates[0]

                status = (
                    "pending_approval"
                    if best["total_cost"]
                       > policy["approval_threshold"]
                    else "placed"
                )

                timestamp = utc_now()

                order = db.execute(
                    """
                    INSERT INTO purchase_orders (
                        component,
                        supplier_id,
                        quantity,
                        total_cost,
                        status,
                        created_at,
                        fulfillable_quantity,
                        received_quantity,
                        unit_price,
                        expected_delivery_days,
                        updated_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        item["component"],
                        best["id"],
                        shortage,
                        best["total_cost"],
                        status,
                        timestamp,
                        shortage,
                        0,
                        best["unit_price"],
                        best["delivery_days"],
                        timestamp
                    )
                )

                # Reserve fictional supplier stock.
                reserved = db.execute(
                    """
                    UPDATE suppliers
                    SET available = available - ?
                    WHERE id = ?
                      AND available >= ?
                    """,
                    (
                        shortage,
                        best["id"],
                        shortage
                    )
                )

                if reserved.rowcount != 1:
                    raise RuntimeError(
                        "Supplier availability changed. "
                        "Transaction rolled back."
                    )

                action = {
                    "component": item["component"],
                    "shortage": shortage,
                    "action": status,
                    "order_id": order.lastrowid,
                    "supplier": best["name"],
                    "total_cost": best["total_cost"],
                    "score": best["score"],
                    "reason": (
                        "Highest eligible "
                        "policy-weighted score"
                    )
                }

            actions.append(action)

            record_log(
                db,
                "procurement_evaluation",
                action
            )

        if not actions:
            record_log(
                db,
                "procurement_no_action",
                {
                    "reason": (
                        "All procurement needs are "
                        "covered by stock or "
                        "outstanding orders"
                    )
                }
            )

    return {"actions": actions}


def approve_purchase_order(order_id):
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

        if not order:
            raise LookupError("Order not found")

        if order["status"] != "pending_approval":
            raise ValueError(
                "Only pending orders can be approved"
            )

        db.execute(
            """
            UPDATE purchase_orders
            SET status = 'placed',
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), order_id)
        )

        record_log(
            db,
            "order_approved",
            {"order_id": order_id}
        )

    return {
        "order_id": order_id,
        "status": "placed"
    }


def receive_purchase_order(
    order_id,
    quantity,
    receipt_id
):
    """
    Confirm physical delivery.

    Each receipt_id can be applied only once.
    A supplier saying "delivered" does not
    automatically increase inventory.
    """
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        previous = db.execute(
            """
            SELECT *
            FROM receipts
            WHERE receipt_id = ?
            """,
            (receipt_id,)
        ).fetchone()

        if previous:
            if (
                previous["order_id"] != order_id
                or previous["quantity"] != quantity
            ):
                raise ValueError(
                    "Receipt ID already used "
                    "for a different receipt"
                )

            return {
                "order_id": order_id,
                "receipt_id": receipt_id,
                "quantity_added": 0,
                "already_processed": True
            }

        order = db.execute(
            """
            SELECT *
            FROM purchase_orders
            WHERE id = ?
            """,
            (order_id,)
        ).fetchone()

        if not order:
            raise LookupError("Order not found")

        allowed_statuses = (
            "placed",
            "delayed",
            "shipped",
            "awaiting_receipt",
            "partially_received",
        )

        if order["status"] not in allowed_statuses:
            raise ValueError(
                "Order is not eligible for receiving. "
                "Approve pending orders first."
            )

        remaining = (
            order["fulfillable_quantity"]
            - order["received_quantity"]
        )

        if quantity <= 0 or quantity > remaining:
            raise ValueError(
                f"Receipt quantity must be "
                f"between 1 and {remaining}"
            )

        # Apply the received quantity to
        # physical warehouse stock.
        updated = db.execute(
            """
            UPDATE inventory
            SET stock = stock + ?
            WHERE component = ?
            """,
            (quantity, order["component"])
        )

        if updated.rowcount != 1:
            raise RuntimeError(
                "Inventory component not found"
            )

        new_received = (
            order["received_quantity"]
            + quantity
        )

        new_status = (
            "received"
            if new_received
               == order["fulfillable_quantity"]
            else "partially_received"
        )

        db.execute(
            """
            UPDATE purchase_orders
            SET received_quantity = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_received,
                new_status,
                utc_now(),
                order_id
            )
        )

        db.execute(
            """
            INSERT INTO receipts(
                receipt_id,
                order_id,
                quantity,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                receipt_id,
                order_id,
                quantity,
                utc_now()
            )
        )

        result = {
            "order_id": order_id,
            "receipt_id": receipt_id,
            "status": new_status,
            "quantity_added": quantity,
            "total_received": new_received,
            "already_processed": False
        }

        record_log(
            db,
            "warehouse_receipt",
            result
        )

        return result
