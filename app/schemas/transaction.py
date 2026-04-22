from datetime import datetime
from decimal import Decimal

import uuid

from pydantic import BaseModel

from app.schemas.event import EventResponse


class MerchantInfo(BaseModel):
    model_config = {"from_attributes": True}

    merchant_id: str
    name: str


class TransactionSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    transaction_id: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime
    updated_at: datetime
    merchant: MerchantInfo


class TransactionDetail(TransactionSummary):
    events: list[EventResponse]
