
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parents[2] / "chainpilot.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            );

            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL
            );
        """)
