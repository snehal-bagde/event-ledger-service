import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.merchant import Merchant
from app.models.transaction import Transaction


class TransactionRepository:
    async def get_by_transaction_id(
        self, db: AsyncSession, transaction_id: str
    ) -> Transaction | None:
        result = await db.execute(
            select(Transaction).where(Transaction.transaction_id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_details(
        self, db: AsyncSession, transaction_id: str
    ) -> Transaction | None:
        result = await db.execute(
            select(Transaction)
            .options(
                selectinload(Transaction.merchant),
                selectinload(Transaction.events),
            )
            .where(Transaction.transaction_id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        *,
        transaction_id: str,
        merchant_id: uuid.UUID,
        amount: Decimal,
        currency: str,
    ) -> Transaction:
        txn = Transaction(
            transaction_id=transaction_id,
            merchant_id=merchant_id,
            amount=amount,
            currency=currency,
            status="initiated",
        )
        db.add(txn)
        await db.flush()
        return txn

    async def update_status(
        self, db: AsyncSession, pk: uuid.UUID, status: str
    ) -> None:
        txn = await db.get(Transaction, pk)
        if txn:
            txn.status = status
            txn.updated_at = datetime.now(tz=timezone.utc)
            await db.flush()

    async def list_with_filters(
        self,
        db: AsyncSession,
        *,
        merchant_id: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        base_query = (
            select(Transaction)
            .options(selectinload(Transaction.merchant))
            .join(Merchant, Transaction.merchant_id == Merchant.id)
        )
        count_query = (
            select(func.count())
            .select_from(Transaction)
            .join(Merchant, Transaction.merchant_id == Merchant.id)
        )

        filters = []
        if merchant_id:
            filters.append(Merchant.merchant_id == merchant_id)
        if status:
            filters.append(Transaction.status == status)
        if date_from:
            filters.append(Transaction.created_at >= date_from)
        if date_to:
            filters.append(Transaction.created_at <= date_to)

        if filters:
            from sqlalchemy import and_
            base_query = base_query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        sort_col = getattr(Transaction, sort_by, Transaction.created_at)
        if sort_order == "asc":
            base_query = base_query.order_by(sort_col.asc())
        else:
            base_query = base_query.order_by(sort_col.desc())

        base_query = base_query.limit(limit).offset(offset)

        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        result = await db.execute(base_query)
        transactions = list(result.scalars().all())

        return transactions, total


transaction_repo = TransactionRepository()
