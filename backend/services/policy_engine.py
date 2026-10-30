
from backend.database.connection import get_db


def get_policy(db=None):
    if db is None:
        with get_db() as connection:
            return get_policy(connection)

    row = db.execute(
        "SELECT * FROM policies WHERE id = 1"
    ).fetchone()

    if row is None:
        raise RuntimeError("Company policy is missing")

    return dict(row)


def rank_suppliers(component, quantity, db=None):
    if db is None:
        with get_db() as connection:
            return rank_suppliers(
                component, quantity, connection
            )

    if not isinstance(quantity, int) or quantity < 1:
        raise ValueError(
            "Quantity must be a positive integer"
        )

    policy = get_policy(db)

    rows = db.execute(
        """
        SELECT * FROM suppliers
        WHERE component = ?
          AND approved = 1
          AND available >= ?
          AND delivery_days <= ?
          AND unit_price * ? <= ?
        """,
        (
            component,
            quantity,
            policy["max_delivery_days"],
            quantity,
            policy["max_budget"]
        )
    ).fetchall()

    suppliers = [dict(row) for row in rows]

    if not suppliers:
        return []

    min_price = min(
        supplier["unit_price"]
        for supplier in suppliers
    )

    max_price = max(
        supplier["unit_price"]
        for supplier in suppliers
    )

    total_weight = (
        policy["speed_weight"]
        + policy["cost_weight"]
        + policy["reliability_weight"]
    )

    if total_weight <= 0:
        raise ValueError(
            "At least one policy weight must be positive"
        )

    for supplier in suppliers:
        speed_score = max(
            0,
            1 - (
                (supplier["delivery_days"] - 1)
                / max(1, policy["max_delivery_days"] - 1)
            )
        )

        cost_score = (
            (max_price - supplier["unit_price"])
            / (max_price - min_price)
            if max_price > min_price
            else 1
        )

        reliability_score = (
            supplier["reliability"] / 100
        )

        supplier["score"] = round(
            (
                policy["speed_weight"] * speed_score
                + policy["cost_weight"] * cost_score
                + policy["reliability_weight"]
                * reliability_score
            ) / total_weight,
            4
        )

        supplier["total_cost"] = round(
            supplier["unit_price"] * quantity,
            2
        )

    return sorted(
        suppliers,
        key=lambda supplier: (
            -supplier["score"],
            supplier["unit_price"]
        )
    )
