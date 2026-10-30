
import json

from backend.database.connection import get_db
from backend.services.policy_engine import get_policy
from backend.services.procurement_service import (
    record_log,
    utc_now
)


def apply_supplier_event(event):
    payload = event.model_dump()
    canonical = json.dumps(
        payload,
        sort_keys=True
    )

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        previous = db.execute(
            """
            SELECT *
            FROM supplier_events
            WHERE event_id = ?
            """,
            (event.event_id,)
        ).fetchone()

        # Ignore duplicate notifications, but
        # reject reused IDs with changed content.
        if previous:
            if previous["payload"] != canonical:
                raise ValueError(
                    "Event ID reused with different data"
                )

            result = json.loads(previous["result"])
            result["duplicate_event"] = True
            return result

        order = db.execute(
            """
            SELECT *
            FROM purchase_orders
            WHERE id = ?
            """,
            (event.order_id,)
        ).fetchone()

        if not order:
            raise LookupError("Purchase order not found")

        invalid_statuses = (
            "pending_approval",
            "cancelled",
            "received",
            "rejected"
        )

        if order["status"] in invalid_statuses:
            raise ValueError(
                "Order cannot accept supplier updates "
                "in its current status"
            )

        updates = {
            "supplier_note": event.note or None,
            "updated_at": utc_now()
        }

        result = {
            "event_id": event.event_id,
            "order_id": event.order_id,
            "event_type": event.event_type,
            "duplicate_event": False,
            "message": "",
            "requires_review": False
        }

        # ----------------------------------
        # DELAY
        # ----------------------------------

        if event.event_type == "delayed":
            if event.expected_delivery_days is None:
                raise ValueError(
                    "expected_delivery_days is required"
                )

            updates["expected_delivery_days"] = (
                event.expected_delivery_days
            )
            updates["status"] = "delayed"

            policy = get_policy(db)

            result["requires_review"] = (
                event.expected_delivery_days
                > policy["max_delivery_days"]
            )

            result["message"] = (
                "Delay recorded. The existing order "
                "still covers its outstanding quantity. "
                "A replacement requires cancellation "
                "or an authorized change."
            )

        # ----------------------------------
        # CANCELLATION
        # ----------------------------------

        elif event.event_type == "cancelled":
            updates["status"] = "cancelled"

            # Previously received units stay
            # in inventory. Unreceived units
            # no longer cover procurement needs.
            updates["fulfillable_quantity"] = (
                order["received_quantity"]
            )

            # Pause supplier for future sourcing
            # until the manager reviews it.
            db.execute(
                """
                UPDATE suppliers
                SET approved = 0
                WHERE id = ?
                """,
                (order["supplier_id"],)
            )

            result["message"] = (
                "Order cancelled. Unreceived units "
                "are now uncovered. Supplier paused "
                "for new sourcing."
            )

        # ----------------------------------
        # PARTIAL FULFILLMENT
        # ----------------------------------

        elif event.event_type == "partial_fulfillment":
            confirmed = event.fulfillable_quantity

            if confirmed is None:
                raise ValueError(
                    "fulfillable_quantity is required"
                )

            if (
                confirmed < order["received_quantity"]
                or confirmed > order["fulfillable_quantity"]
            ):
                raise ValueError(
                    "Confirmed quantity must be between "
                    "already received and previously "
                    "fulfillable quantities"
                )

            if confirmed == 0:
                raise ValueError(
                    "Use a cancelled event when "
                    "the supplier cannot supply anything"
                )

            updates["fulfillable_quantity"] = confirmed
            updates["total_cost"] = round(
                order["unit_price"] * confirmed,
                2
            )

            # If the entire confirmed quantity
            # was already received, close the order.
            if confirmed == order["received_quantity"]:
                updates["status"] = "received"

            # Supplier cannot meet original order.
            db.execute(
                """
                UPDATE suppliers
                SET approved = 0
                WHERE id = ?
                """,
                (order["supplier_id"],)
            )

            result["message"] = (
                "Supplier can fulfill only part of "
                "the order. Remaining shortage can "
                "be sourced from another supplier."
            )

        # ----------------------------------
        # SHIPPED
        # ----------------------------------

        elif event.event_type == "shipped":
            updates["status"] = "shipped"

            result["message"] = (
                "Shipment recorded. Physical "
                "inventory remains unchanged."
            )

        # ----------------------------------
        # DELIVERED BY SUPPLIER
        # ----------------------------------

        elif event.event_type == "delivered":
            updates["status"] = "awaiting_receipt"

            result["message"] = (
                "Supplier reports delivery. "
                "Awaiting independent warehouse "
                "receipt confirmation."
            )

        else:
            raise ValueError(
                "Unsupported supplier event"
            )

        assignments = ", ".join(
            f"{column} = ?"
            for column in updates
        )

        db.execute(
            f"""
            UPDATE purchase_orders
            SET {assignments}
            WHERE id = ?
            """,
            (*updates.values(), event.order_id)
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
                canonical,
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
