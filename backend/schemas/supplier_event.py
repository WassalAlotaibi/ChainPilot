
from typing import Literal

from pydantic import BaseModel, Field


class SupplierEvent(BaseModel):
    event_id: str = Field(
        min_length=6,
        max_length=128
    )

    order_id: int = Field(gt=0)

    event_type: Literal[
        "delayed",
        "cancelled",
        "partial_fulfillment",
        "shipped",
        "delivered"
    ]

    expected_delivery_days: int | None = Field(
        default=None,
        ge=1
    )

    fulfillable_quantity: int | None = Field(
        default=None,
        ge=0
    )

    note: str | None = Field(
        default=None,
        max_length=500
    )
