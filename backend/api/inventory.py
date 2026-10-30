
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException
)
from pydantic import BaseModel, Field

from backend.services.inventory_service import (
    get_inventory,
    get_shortages,
    update_inventory
)
from backend.agents.supply_agent import (
    trigger_agent_if_enabled
)


router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"]
)


class InventoryChange(BaseModel):
    stock: int = Field(ge=0)
    demand: int = Field(ge=0)


@router.get("/")
def list_inventory():
    return get_inventory()


@router.get("/shortages")
def list_shortages():
    return get_shortages()


@router.put("/{component}")
def set_inventory(
    component: str,
    data: InventoryChange,
    background_tasks: BackgroundTasks
):
    try:
        result = update_inventory(
            component,
            data.stock,
            data.demand
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        ) from exc

    triggered = trigger_agent_if_enabled(
        background_tasks,
        "AUTO_AGENT_ON_INVENTORY",
        f"Inventory changed for {component}"
    )

    return {
        **result,
        "agent_triggered": triggered
    }
