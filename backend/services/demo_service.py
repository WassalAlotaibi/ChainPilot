
import json

from backend.database.connection import get_db
from backend.database.seed import (
    DEFAULT_INVENTORY,
    DEFAULT_SUPPLIERS,
    DEFAULT_POLICY
)
from backend.services.inventory_service import get_inventory
from backend.services.procurement_service import utc_now


def log(db, action, details):
    db.execute(
        """
        INSERT INTO agent_logs(
            timestamp, action, details
        )
        VALUES (?, ?, ?)
        """,
        (
            utc_now(),
            action,
            json.dumps(details)
        )
    )


def adjust_stock(component, action, quantity):
    if (
        action not in ("add", "consume")
        or not isinstance(quantity, int)
        or quantity <= 0
    ):
        raise ValueError(
            "Use add/consume with a positive integer"
        )

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        row = db.execute(
            """
            SELECT stock
            FROM inventory
            WHERE component=?
            """,
            (component,)
        ).fetchone()

        if row is None:
            raise LookupError("Component not found")

        previous = row["stock"]

        if action == "consume" and quantity > previous:
            raise ValueError(
                "Cannot consume more than available stock"
            )

        new_stock = (
            previous + quantity
            if action == "add"
            else previous - quantity
        )

        db.execute(
            """
            UPDATE inventory
            SET stock=?
            WHERE component=?
            """,
            (new_stock, component)
        )

        current = next(
            x for x in get_inventory(db)
            if x["component"] == component
        )

        result = {
            "component": component,
            "action": action,
            "quantity": quantity,
            "previous_stock": previous,
            "new_stock": new_stock,
            "uncovered_shortage": current["uncovered_shortage"]
        }

        log(db, "demo_stock_adjusted", result)

        return result


def set_production_target(target):
    if not isinstance(target, int) or target < 0:
        raise ValueError(
            "Target must be nonnegative"
        )

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        db.execute(
            "UPDATE inventory SET demand=?",
            (target,)
        )

        log(
            db,
            "demo_target_changed",
            {"target": target}
        )

        return {
            "target": target,
            "inventory": get_inventory(db)
        }


def _restore(db):
    """
    Restore fictional data inside the current
    transaction. This is a destructive reset.
    """
    for table in (
        "supplier_events",
        "receipts",
        "purchase_orders",
        "agent_logs",
        "inventory",
        "suppliers"
    ):
        db.execute(f"DELETE FROM {table}")

    db.executemany(
        """
        INSERT INTO inventory(
            component, stock, demand
        )
        VALUES (?, ?, ?)
        """,
        DEFAULT_INVENTORY
    )

    db.executemany(
        """
        INSERT INTO suppliers(
            name, component, available,
            unit_price, delivery_days, reliability
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        DEFAULT_SUPPLIERS
    )

    db.execute(
        """
        INSERT OR REPLACE INTO policies(
            id, speed_weight, cost_weight,
            reliability_weight, max_budget,
            max_delivery_days, approval_threshold
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        DEFAULT_POLICY
    )


def reset_demo():
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        _restore(db)

        log(
            db,
            "demo_reset",
            {"scenario": "default"}
        )

        return {
            "status": "reset",
            "inventory": get_inventory(db)
        }


def load_scenario(name):
    if name != "battery_split":
        raise ValueError("Unknown scenario")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        _restore(db)

        # Motherboards already sufficient.
        db.execute(
            """
            UPDATE inventory
            SET stock=500
            WHERE component='Motherboards'
            """
        )

        # 500 required - 200 available = 300 needed.
        db.execute(
            """
            UPDATE inventory
            SET stock=200
            WHERE component='Batteries'
            """
        )

        # Budget First makes BatteryDirect
        # the highest-ranked battery supplier.
        db.execute(
            """
            UPDATE policies
            SET speed_weight=15,
                cost_weight=75,
                reliability_weight=10
            WHERE id=1
            """
        )

        log(
            db,
            "demo_scenario_loaded",
            {"scenario": name}
        )

        return {
            "scenario": name,
            "message": (
                "300 batteries needed; "
                "Budget First policy selected"
            ),
            "inventory": get_inventory(db)
        }
