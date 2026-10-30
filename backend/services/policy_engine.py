
from backend.database.connection import get_db


def get_policy(db=None):
    if db is None:
        with get_db() as conn:
            return get_policy(conn)

    row = db.execute(
        "SELECT * FROM policies WHERE id=1"
    ).fetchone()

    if row is None:
        raise RuntimeError("Company policy missing")

    return dict(row)


def rank_suppliers(component, quantity, db=None):
    """
    Rank eligible suppliers.

    A supplier may fulfill part of the requested
    quantity rather than the whole shortage.
    """
    if db is None:
        with get_db() as conn:
            return rank_suppliers(
                component, quantity, conn
            )

    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity < 1
    ):
        raise ValueError(
            "Quantity must be a positive integer"
        )

    p = get_policy(db)

    offers = [
        dict(row)
        for row in db.execute(
            """
            SELECT *
            FROM suppliers
            WHERE component=?
              AND approved=1
              AND available>0
              AND unit_price>0
              AND delivery_days<=?
            """,
            (component, p["max_delivery_days"])
        ).fetchall()
    ]

    if not offers:
        return []

    lo = min(s["unit_price"] for s in offers)
    hi = max(s["unit_price"] for s in offers)

    weight_sum = (
        p["speed_weight"]
        + p["cost_weight"]
        + p["reliability_weight"]
    )

    if weight_sum <= 0:
        raise ValueError(
            "Company policy requires positive weights"
        )

    for s in offers:
        speed = max(
            0.0,
            1 - (
                (s["delivery_days"] - 1)
                / max(1, p["max_delivery_days"] - 1)
            )
        )

        cost = (
            (hi - s["unit_price"]) / (hi - lo)
            if hi > lo else 1.0
        )

        reliability = s["reliability"] / 100

        s["score"] = round(
            (
                p["speed_weight"] * speed
                + p["cost_weight"] * cost
                + p["reliability_weight"] * reliability
            ) / weight_sum,
            4
        )

        s["allocatable_units"] = min(
            quantity,
            s["available"]
        )

        s["total_cost"] = round(
            s["unit_price"] * s["allocatable_units"],
            2
        )

    return sorted(
        offers,
        key=lambda s: (
            -s["score"],
            s["unit_price"],
            s["id"]
        )
    )
