from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, case, exists, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.event import Event
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.schemas.reconciliation import (
    DiscrepancyItem,
    MerchantSummary,
    ReconciliationDiscrepancies,
    ReconciliationSummary,
    StatusBreakdown,
)


async def get_summary(db: AsyncSession) -> ReconciliationSummary:
    # --- Status breakdown (single aggregation pass) ---
    status_q = await db.execute(
        select(
            Transaction.status,
            func.count().label("count"),
            func.sum(Transaction.amount).label("total_amount"),
            func.avg(Transaction.amount).label("avg_amount"),
            func.min(Transaction.amount).label("min_amount"),
            func.max(Transaction.amount).label("max_amount"),
        ).group_by(Transaction.status)
    )
    status_rows = status_q.all()

    by_status = [
        StatusBreakdown(
            status=row.status,
            count=row.count,
            total_amount=row.total_amount or Decimal(0),
            avg_amount=round(row.avg_amount or Decimal(0), 2),
            min_amount=row.min_amount or Decimal(0),
            max_amount=row.max_amount or Decimal(0),
        )
        for row in status_rows
    ]

    total_transactions = sum(b.count for b in by_status)
    total_amount = sum(b.total_amount for b in by_status)

    # --- Per-merchant, per-status aggregation (one query, no N+1) ---
    merchant_q = await db.execute(
        select(
            Merchant.merchant_id,
            Merchant.name.label("merchant_name"),
            Transaction.status,
            func.count().label("count"),
            func.sum(Transaction.amount).label("total_amount"),
        )
        .join(Merchant, Transaction.merchant_id == Merchant.id)
        .group_by(Merchant.merchant_id, Merchant.name, Transaction.status)
        .order_by(Merchant.merchant_id)
    )
    merchant_rows = merchant_q.all()

    # Pivot in Python (small result set — number of merchants × statuses)
    merchant_map: dict[str, MerchantSummary] = {}
    for row in merchant_rows:
        if row.merchant_id not in merchant_map:
            merchant_map[row.merchant_id] = MerchantSummary(
                merchant_id=row.merchant_id,
                merchant_name=row.merchant_name,
                total_transactions=0,
                total_amount=Decimal(0),
                by_status={},
            )
        m = merchant_map[row.merchant_id]
        m.total_transactions += row.count
        m.total_amount += row.total_amount or Decimal(0)
        m.by_status[row.status] = row.count

    return ReconciliationSummary(
        total_transactions=total_transactions,
        total_amount=total_amount,
        by_status=by_status,
        by_merchant=list(merchant_map.values()),
        generated_at=datetime.now(tz=timezone.utc),
    )


async def get_discrepancies(db: AsyncSession) -> ReconciliationDiscrepancies:
    items: list[DiscrepancyItem] = []
    now = datetime.now(tz=timezone.utc)

    # --- 1. Processed but not settled after threshold (stale) ---
    from datetime import timedelta

    stale_cutoff = now - timedelta(hours=settings.PROCESSED_STALE_HOURS)
    stale_q = await db.execute(
        select(
            Transaction.transaction_id,
            Transaction.status,
            Transaction.amount,
            Transaction.currency,
            Transaction.updated_at,
            Merchant.merchant_id,
            Merchant.name.label("merchant_name"),
        )
        .join(Merchant, Transaction.merchant_id == Merchant.id)
        .where(
            and_(
                Transaction.status == "processed",
                Transaction.updated_at < stale_cutoff,
            )
        )
    )
    for row in stale_q.all():
        items.append(
            DiscrepancyItem(
                transaction_id=row.transaction_id,
                current_status=row.status,
                amount=row.amount,
                currency=row.currency,
                merchant_id=row.merchant_id,
                merchant_name=row.merchant_name,
                discrepancy_type="stale_processed",
                detail=f"Processed but not settled after {settings.PROCESSED_STALE_HOURS}h",
                occurred_at=row.updated_at,
            )
        )

    # --- 2. Conflicting events: both 'settled' and 'payment_failed' exist ---
    failed_subq = (
        select(Event.transaction_id)
        .where(Event.event_type == "payment_failed")
        .correlate(Transaction)
        .where(Event.transaction_id == Transaction.id)
    )
    settled_subq = (
        select(Event.transaction_id)
        .where(Event.event_type == "settled")
        .correlate(Transaction)
        .where(Event.transaction_id == Transaction.id)
    )
    conflict_q = await db.execute(
        select(
            Transaction.transaction_id,
            Transaction.status,
            Transaction.amount,
            Transaction.currency,
            Transaction.updated_at,
            Merchant.merchant_id,
            Merchant.name.label("merchant_name"),
        )
        .join(Merchant, Transaction.merchant_id == Merchant.id)
        .where(exists(failed_subq))
        .where(exists(settled_subq))
    )
    for row in conflict_q.all():
        items.append(
            DiscrepancyItem(
                transaction_id=row.transaction_id,
                current_status=row.status,
                amount=row.amount,
                currency=row.currency,
                merchant_id=row.merchant_id,
                merchant_name=row.merchant_name,
                discrepancy_type="conflicting_terminal_events",
                detail="Transaction has both 'settled' and 'payment_failed' events",
                occurred_at=row.updated_at,
            )
        )

    # --- 3. Failed event arrived AFTER a settled event (late failure) ---
    # Uses a correlated subquery joining the two event rows to compare timestamps.
    failed_e = Event.__table__.alias("failed_e")
    settled_e = Event.__table__.alias("settled_e")
    late_failure_q = await db.execute(
        select(
            Transaction.transaction_id,
            Transaction.status,
            Transaction.amount,
            Transaction.currency,
            Transaction.updated_at,
            Merchant.merchant_id,
            Merchant.name.label("merchant_name"),
        )
        .join(Merchant, Transaction.merchant_id == Merchant.id)
        .join(settled_e, settled_e.c.transaction_id == Transaction.id)
        .join(failed_e, failed_e.c.transaction_id == Transaction.id)
        .where(settled_e.c.event_type == "settled")
        .where(failed_e.c.event_type == "payment_failed")
        .where(failed_e.c.timestamp > settled_e.c.timestamp)
        .distinct()
    )
    existing_conflicts = {i.transaction_id for i in items if i.discrepancy_type == "conflicting_terminal_events"}
    for row in late_failure_q.all():
        if row.transaction_id not in existing_conflicts:
            items.append(
                DiscrepancyItem(
                    transaction_id=row.transaction_id,
                    current_status=row.status,
                    amount=row.amount,
                    currency=row.currency,
                    merchant_id=row.merchant_id,
                    merchant_name=row.merchant_name,
                    discrepancy_type="late_failure_after_settlement",
                    detail="A payment_failed event arrived after the transaction was settled",
                    occurred_at=row.updated_at,
                )
            )

    return ReconciliationDiscrepancies(
        total_discrepancies=len(items),
        items=items,
        generated_at=now,
    )
