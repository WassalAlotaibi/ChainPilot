
from backend.database.connection import get_db


ACTIVE_STATUSES = (
    "pending_approval",
    "placed",
    "delayed",
    "shipped",
    "awaiting_receipt",
    "partially_received",
)


def get_inventory(db=None):
    if db is None:
        with get_db() as connection:
            return get_inventory(connection)

    items = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM inventory ORDER BY id"
        )
    ]

    for item in items:
        orders = db.execute(
            """
            SELECT
                status,
                fulfillable_quantity,
                received_quantity
            FROM purchase_orders
            WHERE component = ?
              AND status IN (?, ?, ?, ?, ?, ?)
            """,
            (item["component"], *ACTIVE_STATUSES)
        ).fetchall()

        pending = 0
        committed = 0
        delayed = 0

        for order in orders:
            outstanding = max(
                0,
                order["fulfillable_quantity"]
                - order["received_quantity"]
            )

            if order["status"] == "pending_approval":
                pending += outstanding
            else:
                committed += outstanding

            if order["status"] == "delayed":
                delayed += outstanding

        item["pending_approval_quantity"] = pending
        item["committed_incoming"] = committed
        item["delayed_quantity"] = delayed
        item["ordered_or_pending"] = pending + committed

        item["physical_shortage"] = max(
            0,
            item["demand"] - item["stock"]
        )

        item["uncovered_shortage"] = max(
            0,
            item["demand"]
            - item["stock"]
            - pending
            - committed
        )

        # Maintain compatibility with old API.
        item["shortage"] = item["physical_shortage"]

        item["status"] = (
            "SHORTAGE"
            if item["physical_shortage"] > 0
            else "SUFFICIENT"
        )

    return items


def get_shortages():
    return [
        item for item in get_inventory()
        if item["physical_shortage"] > 0
    ]


def get_open_needs():
    return [
        {
            "component": item["component"],
            "stock": item["stock"],
            "demand": item["demand"],
            "ordered_or_pending": item["ordered_or_pending"],
            "uncovered_shortage": item["uncovered_shortage"],
            "pending_approval_quantity":
                item["pending_approval_quantity"],
            "delayed_quantity": item["delayed_quantity"],
        }
        for item in get_inventory()
    ]


def update_inventory(component, stock, demand):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        changed = db.execute(
            """
            UPDATE inventory
            SET stock = ?, demand = ?
            WHERE component = ?
            """,
            (stock, demand, component)
        )

        if changed.rowcount != 1:
            raise LookupError("Component not found")

    return {
        "component": component,
        "stock": stock,
        "demand": demand
    }
