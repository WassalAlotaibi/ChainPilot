
from fastapi import APIRouter
from backend.services.inventory_service import (
    get_inventory,
    get_shortages
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/")
def list_inventory():
    return get_inventory()


@router.get("/shortages")
def list_shortages():
    return get_shortages()
