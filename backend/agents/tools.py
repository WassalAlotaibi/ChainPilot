
from backend.database.connection import get_db
from backend.services.policy_engine import (
    get_policy, rank_suppliers
)
from backend.services.procurement_service import (
    evaluate_procurement, get_purchase_orders
)


def get_open_needs():
    """Calculate shortages not covered by existing orders."""
    with get_db() as db:
        rows = db.execute("""
            SELECT i.component, i.stock, i.demand,
                   COALESCE(SUM(
                       CASE WHEN p.status IN (
                           'placed', 'pending_approval'
                       ) THEN p.quantity ELSE 0 END
                   ), 0) AS ordered
            FROM inventory i
            LEFT JOIN purchase_orders p
              ON i.component = p.component
            GROUP BY i.id, i.component, i.stock, i.demand
        """).fetchall()

        return [
            {
                "component": r["component"],
                "stock": r["stock"],
                "demand": r["demand"],
                "ordered_or_pending": r["ordered"],
                "uncovered_shortage": max(
                    0, r["demand"] - r["stock"] - r["ordered"]
                )
            }
            for r in rows
        ]


TOOLS = [
    {
        "type": "function",
        "name": "get_open_needs",
        "description": "Inspect inventory and uncovered shortages.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "strict": True
    },
    {
        "type": "function",
        "name": "get_policy",
        "description": "Read current business purchasing policy.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "strict": True
    },
    {
        "type": "function",
        "name": "get_purchase_orders",
        "description": "Review existing procurement orders.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "strict": True
    },
    {
        "type": "function",
        "name": "rank_suppliers",
        "description": "Compare eligible suppliers using company policy.",
        "parameters": {
            "type": "object",
            "properties": {
                "component": {"type": "string"},
                "quantity": {
                    "type": "integer",
                    "minimum": 1
                }
            },
            "required": ["component", "quantity"],
            "additionalProperties": False
        },
        "strict": True
    },
    {
        "type": "function",
        "name": "execute_procurement",
        "description": (
            "Run the controlled procurement service. "
            "It independently checks shortages, policies, "
            "approvals, and existing orders."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "strict": True
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
        quantity = int(arguments["quantity"])
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        return rank_suppliers(arguments["component"], quantity)

    if name == "execute_procurement":
        return evaluate_procurement()

    raise ValueError(f"Unknown tool: {name}")
