
import os
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException
)
from pydantic import BaseModel, Field

from backend.services.demo_service import (
    adjust_stock,
    set_production_target,
    reset_demo,
    load_scenario
)

from backend.agents.supply_agent import (
    trigger_agent_if_enabled
)


router = APIRouter(
    prefix="/demo",
    tags=["Interactive Demo"]
)


def require_demo_mode():
    enabled = os.getenv(
        "ENABLE_DEMO_CONTROLS",
        "false"
    ).strip().lower()

    if enabled not in ("true", "yes", "1"):
        raise HTTPException(
            403,
            "Demo controls disabled"
        )


class StockChange(BaseModel):
    action: Literal["consume", "add"]
    quantity: int = Field(gt=0)


class ProductionTarget(BaseModel):
    target: int = Field(ge=0)


class Scenario(BaseModel):
    name: Literal["battery_split"]


@router.post("/inventory/{component}/adjust")
def adjust(
    component: str,
    body: StockChange,
    tasks: BackgroundTasks
):
    require_demo_mode()

    try:
        result = adjust_stock(
            component,
            body.action,
            body.quantity
        )

    except LookupError as exc:
        raise HTTPException(
            404, str(exc)
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            409, str(exc)
        ) from exc

    result["agent_triggered"] = trigger_agent_if_enabled(
        tasks,
        "AUTO_AGENT_ON_INVENTORY",
        f"{body.action} {body.quantity} {component}"
    )

    return result


@router.post("/production-target")
def target(
    body: ProductionTarget,
    tasks: BackgroundTasks
):
    require_demo_mode()

    result = set_production_target(body.target)

    result["agent_triggered"] = trigger_agent_if_enabled(
        tasks,
        "AUTO_AGENT_ON_INVENTORY",
        f"Production target {body.target}"
    )

    return result


@router.post("/reset")
def reset():
    require_demo_mode()
    return reset_demo()


@router.post("/scenario")
def scenario(body: Scenario):
    require_demo_mode()
    return load_scenario(body.name)
