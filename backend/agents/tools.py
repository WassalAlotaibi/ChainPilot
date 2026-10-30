
from backend.services.inventory_service import (
    get_open_needs
)
from backend.services.policy_engine import (
    get_policy,
    rank_suppliers
)
from backend.services.procurement_service import (
    evaluate_procurement,
    get_purchase_orders
)


TOOLS = [
    {
        "name": "get_open_needs",
        "description": (
            "Inspect inventory, actual stock, "
            "incoming commitments, uncovered "
            "shortages, delayed orders and "
            "pending approvals."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
    },
    {
        "name": "get_policy",
        "description": (
            "Read the company's procurement "
            "budget, maximum delivery time, "
            "approval threshold and ranking weights."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
    },
    {
        "name": "get_purchase_orders",
        "description": (
            "Read existing orders, supplier "
            "statuses, fulfilled quantities, "
            "received quantities and delays."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
    },
    {
        "name": "rank_suppliers",
        "description": (
            "Rank eligible suppliers for a "
            "component and quantity using "
            "the company's current policy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string"
                },
                "quantity": {
                    "type": "integer",
                    "minimum": 1
                }
            },
            "required": [
                "component",
                "quantity"
            ],
            "additionalProperties": False
        }
    },
    {
        "name": "execute_procurement",
        "description": (
            "Request controlled procurement "
            "for uncovered shortages. The "
            "backend validates policy, "
            "supplier availability, approvals "
            "and duplicate-order prevention."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
    }
]


def invoke_tool(name, arguments):
    if name == "get_open_needs":
        return get_open_needs()

    if name == "get_policy":
        return get_policy()

    if name == "get_purchase_orders":
        return get_purchase_orders()

    if name == "rank_suppliers":
        quantity = int(
            arguments["quantity"]
        )

        if quantity <= 0:
            raise ValueError(
                "Quantity must be positive"
            )

        return rank_suppliers(
            str(arguments["component"]),
            quantity
        )

    if name == "execute_procurement":
        return evaluate_procurement()

    raise ValueError(
        f"Unknown agent tool: {name}"
    )
