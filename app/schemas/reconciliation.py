from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class StatusBreakdown(BaseModel):
    status: str
    count: int
    total_amount: Decimal
    avg_amount: Decimal
    min_amount: Decimal
    max_amount: Decimal


class MerchantSummary(BaseModel):
    merchant_id: str
    merchant_name: str
    total_transactions: int
    total_amount: Decimal
    by_status: dict[str, int]


class ReconciliationSummary(BaseModel):
    total_transactions: int
    total_amount: Decimal
    by_status: list[StatusBreakdown]
    by_merchant: list[MerchantSummary]
    generated_at: datetime


class DiscrepancyItem(BaseModel):
    transaction_id: str
    current_status: str
    amount: Decimal
    currency: str
    merchant_id: str
    merchant_name: str
    discrepancy_type: str
    detail: str
    occurred_at: datetime | None = None


class ReconciliationDiscrepancies(BaseModel):
    total_discrepancies: int
    items: list[DiscrepancyItem]
    generated_at: datetime
