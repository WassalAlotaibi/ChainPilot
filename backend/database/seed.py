
from backend.database.connection import get_db

DEFAULT_INVENTORY = [
    ("Motherboards", 300, 500),
    ("Batteries", 480, 500),
    ("RAM", 620, 500),
    ("Displays", 550, 500),
]

# Name, component, quantity, price SAR, days, reliability
DEFAULT_SUPPLIERS = [
    ("TechSource A", "Motherboards", 400, 40, 1, 92),
    ("ChipSupply B", "Motherboards", 500, 22.5, 3, 97),
    ("CoreParts C", "Motherboards", 350, 30, 2, 99),

    ("BatteryDirect", "Batteries", 200, 20, 2, 96),
    ("PowerWorks", "Batteries", 500, 25, 1, 94),

    ("MemoryWorks", "RAM", 400, 18, 2, 97),
    ("RapidRAM", "RAM", 350, 24, 1, 93),

    ("DisplaySource", "Displays", 400, 45, 2, 98),
    ("ScreenFast", "Displays", 250, 55, 1, 94),
]

DEFAULT_POLICY = (1, 70, 10, 20, 10000, 3, 5000)


def seed_database():
    with get_db() as db:

        for component, stock, demand in DEFAULT_INVENTORY:
            db.execute(
                """
                INSERT OR IGNORE INTO inventory(
                    component, stock, demand
                )
                VALUES (?, ?, ?)
                """,
                (component, stock, demand)
            )

        for name, component, available, price, days, reliability in DEFAULT_SUPPLIERS:
            exists = db.execute(
                """
                SELECT 1 FROM suppliers
                WHERE name=? AND component=?
                """,
                (name, component)
            ).fetchone()

            if not exists:
                db.execute(
                    """
                    INSERT INTO suppliers(
                        name, component, available,
                        unit_price, delivery_days, reliability
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name, component, available,
                        price, days, reliability
                    )
                )

        db.execute(
            """
            INSERT OR IGNORE INTO policies(
                id, speed_weight, cost_weight,
                reliability_weight, max_budget,
                max_delivery_days, approval_threshold
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            DEFAULT_POLICY
        )
