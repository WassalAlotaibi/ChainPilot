
from backend.database.connection import get_db
# i useed fictional supplier data 

def seed_database():
    with get_db() as db:
        if not db.execute(
            "SELECT 1 FROM inventory LIMIT 1"
        ).fetchone():
            db.executemany(
                """
                INSERT INTO inventory (component, stock, demand)
                VALUES (?, ?, ?)
                """,
                [
                    ("Motherboards", 300, 500),
                    ("Batteries", 480, 500),
                    ("RAM", 620, 500),
                    ("Displays", 550, 500),
                ]
            )

        if not db.execute(
            "SELECT 1 FROM suppliers LIMIT 1"
        ).fetchone():
            db.executemany(
                """
                INSERT INTO suppliers (
                    name, component, available,
                    unit_price, delivery_days, reliability
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("TechSource A", "Motherboards", 400, 40, 1, 92),
                    ("ChipSupply B", "Motherboards", 500, 22.5, 3, 97),
                    ("CoreParts C", "Motherboards", 350, 30, 2, 99),
                    ("BatteryDirect", "Batteries", 200, 20, 2, 96),
                    ("PowerWorks", "Batteries", 500, 25, 1, 94),
                ]
            )

        db.execute(
            """
            INSERT OR IGNORE INTO policies (
                id, speed_weight, cost_weight,
                reliability_weight, max_budget,
                max_delivery_days, approval_threshold
            )
            VALUES (1, 70, 10, 20, 10000, 3, 5000)
            """
        )
