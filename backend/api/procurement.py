
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.procurement_service import (
    evaluate_procurement,
    get_purchase_orders,
    approve_purchase_order,
    receive_purchase_order
)


router = APIRouter(
    prefix="/procurement",
    tags=["Procurement"]
)


class ReceiptRequest(BaseModel):
    receipt_id: str = Field(
        min_length=6,
        max_length=128
    )
    quantity: int = Field(gt=0)


@router.post("/evaluate")
def evaluate():
    return evaluate_procurement()


@router.get("/orders")
def orders():
    return get_purchase_orders()


@router.post("/orders/{order_id}/approve")
def approve(order_id: int):
    try:
        return approve_purchase_order(order_id)

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc)
        ) from exc


@router.post("/orders/{order_id}/receive")
def receive(order_id: int, data: ReceiptRequest):
    try:
        return receive_purchase_order(
            order_id=order_id,
            quantity=data.quantity,
            receipt_id=data.receipt_id
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc)
        ) from exc
