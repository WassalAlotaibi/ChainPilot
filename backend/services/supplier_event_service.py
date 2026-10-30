
import json

from backend.database.connection import get_db
from backend.services.policy_engine import get_policy
from backend.services.procurement_service import (
    record_log,
    utc_now
)


def apply_supplier_event(event):
    payload = json.dumps(
        event.model_dump(),
        sort_keys=True
    )

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        previous = db.execute(
            """
            SELECT *
            FROM supplier_events
            WHERE event_id=?
            """,
            (event.event_id,)
        ).fetchone()

        if previous:
            if previous["payload"] != payload:
                raise ValueError(
                    "Event ID reused with different content"
                )

            result = json.loads(previous["result"])

            return {
                **result,
                "duplicate_event": True
            }

        order = db.execute(
            """
            SELECT *
            FROM purchase_orders
            WHERE id=?
            """,
            (event.order_id,)
        ).fetchone()

        if order is None:
            raise LookupError("Order not found")

        if order["status"] in (
            "pending_approval",
            "cancelled",
            "received",
            "rejected"
        ):
            raise ValueError(
                "Order cannot accept supplier events "
                "in its current status"
            )

        changes = {
            "supplier_note": event.note,
            "updated_at": utc_now()
        }

        result = {
            "event_id": event.event_id,
            "order_id": event.order_id,
            "event_type": event.event_type,
            "duplicate_event": False,
            "requires_review": False,
            "message": ""
        }

        if event.event_type == "delayed":
            if event.expected_delivery_days is None:
                raise ValueError(
                    "New delivery days required"
                )

            changes.update(
                status="delayed",
                expected_delivery_days=event.expected_delivery_days
            )

            result["requires_review"] = (
                event.expected_delivery_days
                > get_policy(db)["max_delivery_days"]
            )

            result["message"] = (
                "Delay recorded; original order "
                "still covers unreceived quantity."
            )

        elif event.event_type == "cancelled":
            changes.update(
                status="cancelled",
                fulfillable_quantity=order["received_quantity"]
            )

            db.execute(
                """
                UPDATE suppliers
                SET approved=0
                WHERE id=?
                """,
                (order["supplier_id"],)
            )

            result["message"] = (
                "Cancelled; uncovered units may "
                "be sourced from another supplier."
            )

        elif event.event_type == "partial_fulfillment":
            confirmed = event.fulfillable_quantity

            if (
                confirmed is None
                or confirmed < order["received_quantity"]
                or confirmed > order["fulfillable_quantity"]
            ):
                raise ValueError(
                    "Fulfillable quantity must be between "
                    "received and original confirmed quantity"
                )

            if confirmed == 0:
                raise ValueError(
                    "Use cancelled when the supplier "
                    "cannot deliver any units"
                )

            if confirmed == order["fulfillable_quantity"]:
                result["message"] = (
                    "Quantity unchanged; "
                    "no replacement needed."
                )

            else:
                changes.update(
                    fulfillable_quantity=confirmed,
                    total_cost=round(
                        order["unit_price"] * confirmed,
                        2
                    )
                )

                if confirmed == order["received_quantity"]:
                    changes["status"] = "received"

                db.execute(
                    """
                    UPDATE suppliers
                    SET approved=0
                    WHERE id=?
                    """,
                    (order["supplier_id"],)
                )

                result["message"] = (
                    "Supplier quantity reduced; uncovered "
                    "units may be sourced elsewhere."
                )

        elif event.event_type == "shipped":
            changes["status"] = "shipped"
            result["message"] = (
                "Shipment reported. Inventory is unchanged."
            )

        elif event.event_type == "delivered":
            changes["status"] = "awaiting_receipt"
            result["message"] = (
                "Supplier reports delivery. "
                "Warehouse receipt still required."
            )

        else:
            raise ValueError("Unsupported supplier event")

        assignments = ",".join(
            f"{column}=?"
            for column in changes
        )

        db.execute(
            f"""
            UPDATE purchase_orders
            SET {assignments}
            WHERE id=?
            """,
            (*changes.values(), event.order_id)
        )

        db.execute(
            """
            INSERT INTO supplier_events(
                event_id,
                order_id,
                event_type,
                payload,
                result,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.order_id,
                event.event_type,
                payload,
                json.dumps(result),
                utc_now()
            )
        )

        record_log(
            db,
            "supplier_event",
            result
        )

        return result
