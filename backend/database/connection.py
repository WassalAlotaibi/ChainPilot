
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(
    os.getenv("CHAINPILOT_DB", str(ROOT / "chainpilot.db"))
)


@contextmanager
def get_db():
    db = sqlite3.connect(str(DB_PATH), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 15000")

    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component TEXT UNIQUE NOT NULL,
                stock INTEGER NOT NULL CHECK(stock >= 0),
                demand INTEGER NOT NULL CHECK(demand >= 0)
            );

            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                component TEXT NOT NULL,
                available INTEGER NOT NULL CHECK(available >= 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                delivery_days INTEGER NOT NULL CHECK(delivery_days >= 0),
                reliability REAL NOT NULL
                    CHECK(reliability BETWEEN 0 AND 100),
                approved INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS policies (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                speed_weight INTEGER NOT NULL,
                cost_weight INTEGER NOT NULL,
                reliability_weight INTEGER NOT NULL,
                max_budget REAL NOT NULL,
                max_delivery_days INTEGER NOT NULL,
                approval_threshold REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component TEXT NOT NULL,
                supplier_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                total_cost REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(supplier_id)
                    REFERENCES suppliers(id)
            );

            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS supplier_events (
                event_id TEXT PRIMARY KEY,
                order_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(order_id)
                    REFERENCES purchase_orders(id)
            );

            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id TEXT PRIMARY KEY,
                order_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                created_at TEXT NOT NULL,
                FOREIGN KEY(order_id)
                    REFERENCES purchase_orders(id)
            );

            CREATE INDEX IF NOT EXISTS idx_po_component_status
                ON purchase_orders(component, status);
        """)

        # Add fields to EXISTING orders without
        # deleting the original records.

        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(purchase_orders)"
            )
        }

        upgrading_existing_orders = (
            "fulfillable_quantity" not in columns
        )

        additions = {
            "fulfillable_quantity": "INTEGER",
            "received_quantity": "INTEGER NOT NULL DEFAULT 0",
            "unit_price": "REAL",
            "expected_delivery_days": "INTEGER",
            "supplier_note": "TEXT",
            "updated_at": "TEXT",
        }

        for column, definition in additions.items():
            if column not in columns:
                db.execute(
                    f"ALTER TABLE purchase_orders "
                    f"ADD COLUMN {column} {definition}"
                )

        # Existing purchase orders are assumed
        # unreceived unless the database already
        # has a receipt record.

        db.execute("""
            UPDATE purchase_orders
            SET fulfillable_quantity = quantity
            WHERE fulfillable_quantity IS NULL
        """)

        db.execute("""
            UPDATE purchase_orders
            SET unit_price =
                CASE WHEN quantity > 0
                    THEN total_cost * 1.0 / quantity
                    ELSE 0
                END
            WHERE unit_price IS NULL
        """)

        db.execute("""
            UPDATE purchase_orders
            SET expected_delivery_days = (
                SELECT delivery_days
                FROM suppliers
                WHERE suppliers.id =
                      purchase_orders.supplier_id
            )
            WHERE expected_delivery_days IS NULL
        """)

        db.execute("""
            UPDATE purchase_orders
            SET updated_at = created_at
            WHERE updated_at IS NULL
        """)

        # Old orders did not reserve supplier
        # stock. Reserve them exactly once during
        # migration to the new schema.

        if upgrading_existing_orders:
            db.execute("""
                UPDATE suppliers
                SET available = MAX(
                    0,
                    available - (
                        SELECT COALESCE(
                            SUM(po.quantity), 0
                        )
                        FROM purchase_orders po
                        WHERE po.supplier_id = suppliers.id
                          AND po.status IN (
                              'pending_approval',
                              'placed',
                              'delayed',
                              'shipped',
                              'awaiting_receipt',
                              'partially_received'
                          )
                    )
                )
            """)
