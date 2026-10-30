
from fastapi import APIRouter
from backend.services.supplier_service import get_suppliers

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("/")
def list_suppliers(component: str | None = None):
    return get_suppliers(component)
