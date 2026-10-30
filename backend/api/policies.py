
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.database.connection import get_db
from backend.services.policy_engine import get_policy

router = APIRouter(prefix="/policies", tags=["Policies"])


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
def update_policy(data: PolicyUpdate):
    if (
        data.speed_weight
        + data.cost_weight
        + data.reliability_weight
    ) <= 0:
        raise HTTPException(
            400, "At least one weight must be positive"
        )

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
                data.approval_threshold
            )
        )

    return get_policy()
