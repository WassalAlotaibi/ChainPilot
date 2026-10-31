
"""Supplier events and simulated delivery receiving for ChainPilot."""

import os
import secrets

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    HTTPException,
)

from backend.database.connection import get_db
from backend.schemas.supplier_event import SupplierEvent
from backend.services.supplier_event_service import (
    apply_supplier_event,
)
from backend.services.procurement_service import (
    receive_purchase_order,
)
from backend.services.recovery_service import (
    review_recovery,
    execute_replacements,
)
from backend.agents.supply_agent import (
    trigger_agent_if_enabled,
)


router = APIRouter(
    prefix="/supplier-events",
    tags=["Supplier Events"],
)


def demo_enabled():
    return os.getenv(
        "ENABLE_DEMO_CONTROLS", "false"
    ).lower() in ("true", "1", "yes")


@router.post("/")
def receive_supplier_update(
    event: SupplierEvent,
    background_tasks: BackgroundTasks,
    x_supplier_secret: str | None = Header(
        default=None
    ),
):
    # Authenticate simulated supplier messages.
    expected = os.getenv("SUPPLIER_WEBHOOK_SECRET")

    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Configure SUPPLIER_WEBHOOK_SECRET "
                "in .env first"
            ),
        )

    if (
        not x_supplier_secret
        or not secrets.compare_digest(
            x_supplier_secret,
            expected,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid supplier webhook secret",
        )

    # Record the supplier's reported event.
    try:
        result = apply_supplier_event(event)

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    # ==========================================
    # AUTOMATIC WAREHOUSE RECEIPT — LOCAL DEMO
    # ==========================================
    #
    # Shipped:
    #   The order is in transit.
    #   Factory inventory does not change.
    #
    # Delivered:
    #   In demo mode, simulate the warehouse
    #   confirming receipt of all remaining
    #   units on this selected order.
    #
    # The existing procurement service already
    # handles inventory, order status, receipts,
    # duplicate protection, and supplier restock.
    #
    if (
        event.event_type == "delivered"
        and demo_enabled()
    ):
        with get_db() as db:
            order = db.execute(
                """
                SELECT
                    component,
                    fulfillable_quantity,
                    received_quantity,
                    status
                FROM purchase_orders
                WHERE id = ?
                """,
                (event.order_id,),
            ).fetchone()

            if order is None:
                raise HTTPException(
                    status_code=404,
                    detail="Order not found",
                )

            remaining = max(
                0,
                int(order["fulfillable_quantity"])
                - int(order["received_quantity"]),
            )

            component = order["component"]

        if remaining > 0:
            try:
                receipt = receive_purchase_order(
                    order_id=event.order_id,
                    quantity=remaining,
                    receipt_id=(
                        f"supplier-delivered:{event.event_id}"
                    ),
                )

            except ValueError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

        else:
            receipt = {
                "order_id": event.order_id,
                "quantity_added": 0,
                "already_processed": True,
            }

        # Tell the frontend what happened.
        result["warehouse_receipt"] = receipt

        result["message"] = (
            f"Supplier delivery confirmed for "
            f"order #{event.order_id}. "
            f"{receipt['quantity_added']} "
            f"{component} units added to warehouse; "
            "the same units no longer count "
            "as outstanding orders."
        )

    # ==========================================
    # DELAY RECOVERY — EXISTING FUNCTIONALITY
    # ==========================================

    if (
        not result["duplicate_event"]
        and event.event_type == "delayed"
    ):
        decisions = review_recovery(
            trigger="supplier_delay",
            order_id=event.order_id,
        )

        result["recovery_decisions"] = decisions

        cancellation_confirmed = any(
            decision["status"] in (
                "simulated_cancellation_confirmed",
                "cancelled_before_approval",
            )
            for decision in decisions
        )

        if cancellation_confirmed:
            result["replacement_evaluation"] = (
                execute_replacements()
            )

    # ==========================================
    # CHAINPILOT AGENT TRIGGER — UNCHANGED
    # ==========================================

    should_evaluate = (
        not result["duplicate_event"]
        and event.event_type in (
            "delayed",
            "cancelled",
            "partial_fulfillment",
        )
    )

    if should_evaluate:
        result["agent_triggered"] = (
            trigger_agent_if_enabled(
                background_tasks,
                "AUTO_AGENT_ON_EVENTS",
                (
                    f"Supplier reported "
                    f"{event.event_type} "
                    f"for order {event.order_id}"
                ),
            )
        )
    else:
        result["agent_triggered"] = False

    return result
