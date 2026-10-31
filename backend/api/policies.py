
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException
)
from pydantic import BaseModel, Field

from backend.database.connection import get_db
from backend.services.policy_engine import get_policy
from backend.services.recovery_service import (
    review_recovery,
    execute_replacements,
)
from backend.agents.supply_agent import (
    trigger_agent_if_enabled
)


router = APIRouter(
    prefix="/policies",
    tags=["Policies"]
)


class PolicyUpdate(BaseModel):
    speed_weight: int = Field(ge=0, le=100)
    cost_weight: int = Field(ge=0, le=100)
    reliability_weight: int = Field(ge=0, le=100)
    max_budget: float = Field(gt=0)
    max_delivery_days: int = Field(ge=1)
    approval_threshold: float = Field(ge=0)


@router.get("/")
def read_policy():
    return get_policy()


@router.put("/")
def update_policy(
    data: PolicyUpdate,
    background_tasks: BackgroundTasks
):
    total = (
        data.speed_weight
        + data.cost_weight
        + data.reliability_weight
    )

    if total <= 0:
        raise HTTPException(
            400,
            "At least one priority must be positive"
        )

    # First save the manager's new policy.
    with get_db() as db:
        db.execute(
            """
            UPDATE policies
            SET speed_weight = ?,
                cost_weight = ?,
                reliability_weight = ?,
                max_budget = ?,
                max_delivery_days = ?,
                approval_threshold = ?
            WHERE id = 1
            """,
            (
                data.speed_weight,
                data.cost_weight,
                data.reliability_weight,
                data.max_budget,
                data.max_delivery_days,
                data.approval_threshold,
            )
        )

    # Review existing changeable orders.
    decisions = review_recovery(
        trigger="policy_changed"
    )

    # Only replace after a cancellation
    # was actually confirmed.
    confirmed = any(
        decision["status"] in (
            "simulated_cancellation_confirmed",
            "cancelled_before_approval"
        )
        for decision in decisions
    )

    if confirmed:
        execute_replacements()

    if decisions:
        trigger_agent_if_enabled(
            background_tasks,
            "AUTO_AGENT_ON_EVENTS",
            "Company policy changed; review existing orders"
        )

    return get_policy()
