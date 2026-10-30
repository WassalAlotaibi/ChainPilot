
from backend.database.connection import get_db


def get_inventory():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM inventory ORDER BY id"
        ).fetchall()

        results = []

        for row in rows:
            item = dict(row)

            shortage = max(
                0,
                item["demand"] - item["stock"]
            )

            item["shortage"] = shortage
            item["status"] = (
                "SHORTAGE" if shortage > 0 else "SUFFICIENT"
            )

            results.append(item)

        return results


def get_shortages():
    inventory = get_inventory()

    return [
        item for item in inventory
        if item["shortage"] > 0
    ]
