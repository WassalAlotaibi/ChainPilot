
from fastapi import APIRouter, HTTPException

from backend.services.procurement_service import (
    evaluate_procurement,
    get_purchase_orders,
    approve_purchase_order
)

router = APIRouter(
    prefix="/procurement",
    tags=["Procurement"]
)


@router.post("/evaluate")
def evaluate():
    return evaluate_procurement()


@router.get("/orders")
def orders():
    return get_purchase_orders()


@router.post("/orders/{order_id}/approve")
def approve(order_id: int):
    if not approve_purchase_order(order_id):
        raise HTTPException(
            404, "Pending order not found"
        )

    return {
        "order_id": order_id,
        "status": "placed"
    }
