
"""Explain why factory demand remains unfulfilled."""

from decimal import Decimal

from backend.database.connection import get_db
from backend.services.inventory_service import get_inventory
from backend.services.policy_engine import get_policy
from backend.services.procurement_service import committed_cost


def get_supply_gaps(db=None):
    if db is None:
        with get_db() as conn:
            return get_supply_gaps(conn)

    policy = get_policy(db)

    budget = Decimal(str(policy["max_budget"]))
    used = committed_cost(db)

    remaining_budget = max(
        Decimal("0"),
        budget - used
    )

    gaps = []

    for item in get_inventory(db):
        needed = int(item["uncovered_shortage"])

        if needed <= 0:
            continue

        offers = [
            dict(row)
            for row in db.execute(
                """
                SELECT name, available, approved,
                       delivery_days, unit_price
                FROM suppliers
                WHERE component = ?
                """,
                (item["component"],)
            ).fetchall()
        ]

        all_stock = sum(
            max(0, int(s["available"]))
            for s in offers
        )

        approved = [
            s for s in offers
            if s["approved"] and s["unit_price"] > 0
        ]

        approved_stock = sum(
            max(0, int(s["available"]))
            for s in approved
        )

        eligible = [
            s for s in approved
            if s["available"] > 0
            and s["delivery_days"]
                <= policy["max_delivery_days"]
        ]

        eligible_stock = sum(
            int(s["available"])
            for s in eligible
        )

        reasons = []

        if all_stock == 0:
            status = "waiting_supplier_stock"
            reasons.append(
                "All listed suppliers are out of stock."
            )

        elif approved_stock == 0:
            status = "supplier_approval_required"
            reasons.append(
                "Stock exists, but no stocked supplier "
                "is approved for purchasing."
            )

        elif eligible_stock == 0:
            status = "delivery_policy_block"
            reasons.append(
                "Available approved suppliers cannot "
                "meet the delivery-days policy."
            )

        elif remaining_budget <= 0:
            status = "budget_exhausted"

        elif eligible_stock < needed:
            status = "partial_supplier_capacity"

        else:
            status = "ready_to_evaluate"

        if 0 < eligible_stock < needed:
            reasons.append(
                f"Eligible suppliers currently have "
                f"only {eligible_stock} units for "
                f"{needed} uncovered units."
            )

        if remaining_budget <= 0:
            reasons.append(
                "The outstanding purchasing budget "
                "is fully committed."
            )

        elif eligible:
            lowest_price = min(
                Decimal(str(s["unit_price"]))
                for s in eligible
            )

            if remaining_budget < lowest_price:
                reasons.append(
                    "Remaining budget cannot afford "
                    "one unit from an eligible supplier."
                )
                if status == "ready_to_evaluate":
                    status = "budget_limited"

            elif eligible_stock >= needed:
                # Minimum possible cost using currently
                # available eligible supplier quantities.
                left = needed
                minimum_cost = Decimal("0")

                for s in sorted(
                    eligible,
                    key=lambda x: x["unit_price"]
                ):
                    quantity = min(
                        left,
                        int(s["available"])
                    )

                    minimum_cost += (
                        Decimal(str(s["unit_price"]))
                        * quantity
                    )

                    left -= quantity

                    if left == 0:
                        break

                if remaining_budget < minimum_cost:
                    reasons.append(
                        "Remaining budget cannot cover "
                        "the whole shortage at available "
                        "supplier prices."
                    )

                    if status == "ready_to_evaluate":
                        status = "budget_limited"

        if not reasons:
            reasons.append(
                "Supplier and budget capacity are "
                "available. Run procurement evaluation."
            )

        gaps.append({
            "component": item["component"],
            "physical_stock": item["stock"],
            "demand": item["demand"],
            "already_ordered_or_pending":
                item["ordered_or_pending"],
            "unfulfilled_units": needed,
            "status": status,
            "reasons": reasons,
            "supplier_units_available": all_stock,
            "eligible_supplier_units": eligible_stock,
            "budget_remaining_sar": round(
                float(remaining_budget), 2
            )
        })

    return gaps
