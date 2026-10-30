
from backend.database.connection import get_db


def get_suppliers(component=None):
    with get_db() as db:
        if component:
            rows = db.execute(
                """
                SELECT * FROM suppliers
                WHERE component = ? AND approved = 1
                ORDER BY unit_price ASC
                """,
                (component,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM suppliers ORDER BY component, name"
            ).fetchall()

        return [dict(row) for row in rows]
