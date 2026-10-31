
import os
import secrets

from fastapi import (
    APIRouter,
    Header,
    HTTPException
)

from backend.services.recovery_service import (
    confirm_cancellation,
    execute_replacements,
    recent_recovery_decisions,
)


router = APIRouter(
    prefix="/recovery",
    tags=["Order Recovery"]
)


@router.get("/decisions")
def decisions():
    return recent_recovery_decisions()


@router.post("/orders/{order_id}/confirm-cancellation")
def confirm_supplier_cancellation(
    order_id: int,
    x_supplier_secret: str | None = Header(None)
):
    enabled = os.getenv(
        "ENABLE_DEMO_CONTROLS",
        "false"
    ).lower() in ("true", "1", "yes")

    if not enabled:
        raise HTTPException(
            403,
            "Demo controls are disabled"
        )

    expected = os.getenv(
        "SUPPLIER_WEBHOOK_SECRET"
    )

    if (
        not expected
        or not x_supplier_secret
        or not secrets.compare_digest(
            expected,
            x_supplier_secret
        )
    ):
        raise HTTPException(
            401,
            "Invalid supplier demo secret"
        )

    try:
        result = confirm_cancellation(order_id)

    except LookupError as exc:
        raise HTTPException(
            404, str(exc)
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            409, str(exc)
        ) from exc

    result["replacement_evaluation"] = (
        execute_replacements()
    )

    return result
