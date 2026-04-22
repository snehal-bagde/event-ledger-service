import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

VALID_EVENT_TYPES = frozenset(
    {"payment_initiated", "payment_processed", "payment_failed", "settled"}
)


class EventCreate(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=36)
    event_type: str = Field(..., min_length=1, max_length=50)
    transaction_id: str = Field(..., min_length=1, max_length=36)
    merchant_id: str = Field(..., min_length=1, max_length=50)
    merchant_name: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    currency: str = Field(default="INR", max_length=3)
    timestamp: datetime

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(VALID_EVENT_TYPES)}")
        return v

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        return v.upper()


class EventResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_id: str
    event_type: str
    # transaction_id here is the internal FK UUID (transactions.id).
    # The human-readable transaction_id string lives on the parent TransactionDetail.
    transaction_id: uuid.UUID
    amount: Decimal
    currency: str
    timestamp: datetime
    received_at: datetime


class EventIngestResponse(BaseModel):
    event_id: str
    status: Literal["accepted", "duplicate"]
    transaction_id: str
    transaction_status: str
    message: str = ""
