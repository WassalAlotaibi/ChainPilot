
import json
from datetime import datetime, timezone

from backend.database.connection import get_db
from backend.services.policy_engine import rank_suppliers


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def evaluate_procurement():
    actions = []

    with get_db() as db:
        # Lock writes during shortage calculation and order creation.
        db.execute("BEGIN IMMEDIATE")

        inventory = db.execute(
            "SELECT * FROM inventory"
        ).fetchall()

        for item in inventory:
            component = item["component"]

            existing = db.execute(
                """
                SELECT COALESCE(SUM(quantity), 0)
                FROM purchase_orders
                WHERE component = ?
                  AND status IN ('placed', 'pending_approval')
                """,
                (component,)
            ).fetchone()[0]

            shortage = max(
                0,
                item["demand"] - item["stock"] - existing
            )

            if shortage == 0:
                continue

            candidates = rank_suppliers(component, shortage)

            if not candidates:
                action = {
                    "component": component,
                    "shortage": shortage,
                    "action": "escalated",
                    "reason": "No supplier satisfies company policy"
                }
            else:
                best = candidates[0]

                policy = db.execute(
                    "SELECT * FROM policies WHERE id = 1"
                ).fetchone()

                status = (
                    "pending_approval"
                    if best["total_cost"] > policy["approval_threshold"]
                    else "placed"
                )

                db.execute(
                    """
                    INSERT INTO purchase_orders (
                        component, supplier_id, quantity,
                        total_cost, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        component,
                        best["id"],
                        shortage,
                        best["total_cost"],
                        status,
                        utc_now()
                    )
                )

                action = {
                    "component": component,
                    "shortage": shortage,
                    "supplier": best["name"],
                    "score": best["score"],
                    "total_cost": best["total_cost"],
                    "action": status
                }

            db.execute(
                """
                INSERT INTO agent_logs (
                    timestamp, action, details
                )
                VALUES (?, ?, ?)
                """,
                (
                    utc_now(),
                    "procurement_evaluation",
                    json.dumps(action)
                )
            )

            actions.append(action)

    return {"actions": actions}


def get_purchase_orders():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT po.*, s.name AS supplier
            FROM purchase_orders po
            JOIN suppliers s ON s.id = po.supplier_id
            ORDER BY po.id DESC
            """
        ).fetchall()

        return [dict(row) for row in rows]


def approve_purchase_order(order_id):
    with get_db() as db:
        order = db.execute(
            """
            SELECT * FROM purchase_orders
            WHERE id = ? AND status = 'pending_approval'
            """,
            (order_id,)
        ).fetchone()

        if order is None:
            return False

        db.execute(
            """
            UPDATE purchase_orders
            SET status = 'placed'
            WHERE id = ?
            """,
            (order_id,)
        )

        return True
