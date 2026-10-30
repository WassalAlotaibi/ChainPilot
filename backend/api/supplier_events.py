
import os
import secrets

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    HTTPException
)

from backend.schemas.supplier_event import SupplierEvent
from backend.services.supplier_event_service import (
    apply_supplier_event
)
from backend.agents.supply_agent import (
    trigger_agent_if_enabled
)


router = APIRouter(
    prefix="/supplier-events",
    tags=["Supplier Events"]
)


@router.post("/")
def receive_supplier_update(
    event: SupplierEvent,
    background_tasks: BackgroundTasks,
    x_supplier_secret: str | None = Header(
        default=None
    )
):
    expected = os.getenv(
        "SUPPLIER_WEBHOOK_SECRET"
    )

    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Configure SUPPLIER_WEBHOOK_SECRET "
                "in .env first"
            )
        )

    if (
        not x_supplier_secret
        or not secrets.compare_digest(
            x_supplier_secret,
            expected
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid supplier webhook secret"
        )

    try:
        result = apply_supplier_event(event)

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

    should_evaluate = (
        not result["duplicate_event"]
        and event.event_type in (
            "delayed",
            "cancelled",
            "partial_fulfillment"
        )
    )

    if should_evaluate:
        triggered = trigger_agent_if_enabled(
            background_tasks,
            "AUTO_AGENT_ON_EVENTS",
            (
                f"Supplier reported "
                f"{event.event_type} "
                f"for order {event.order_id}"
            )
        )

        result["agent_triggered"] = triggered

    else:
        result["agent_triggered"] = False

    return result
