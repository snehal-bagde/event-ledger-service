import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.repositories.transaction import transaction_repo
from app.schemas.transaction import TransactionDetail, TransactionSummary
from app.utils.messages import INTERNAL_SERVER_ERROR, ErrorMessages, SuccessMessages
from app.utils.response_format import Result

logger = logging.getLogger("event_ledger")

router = APIRouter(prefix="/transactions", tags=["Transactions"])

SORTABLE_FIELDS = frozenset({"created_at", "updated_at", "amount", "status"})


@router.get(
    "",
    response_model=Result,
    summary="List transactions with filtering and pagination",
)
async def list_transactions(
    merchant_id: str | None = Query(None, description="Filter by merchant_id"),
    status: str | None = Query(None, description="Filter by status"),
    date_from: datetime | None = Query(None, description="Filter by created_at >= date_from"),
    date_to: datetime | None = Query(None, description="Filter by created_at <= date_to"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> Result:
    if sort_by not in SORTABLE_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=f"{ErrorMessages.INVALID_SORT_FIELD} Must be one of {sorted(SORTABLE_FIELDS)}.",
        )

    try:
        transactions, total = await transaction_repo.list_with_filters(
            db,
            merchant_id=merchant_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
        items = [TransactionSummary.model_validate(t).model_dump() for t in transactions]
        return Result(
            data={
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total,
            },
            status=200,
            message=SuccessMessages.TRANSACTIONS_FETCHED,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error listing transactions: %s", exc)
        return Result(
            status=500,
            message=INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/{transaction_id}",
    response_model=Result,
    summary="Get full transaction details including event history",
)
async def get_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(db_session),
) -> Result:
    try:
        txn = await transaction_repo.get_by_id_with_details(db, transaction_id)
        if txn is None:
            raise HTTPException(
                status_code=404,
                detail=ErrorMessages.TRANSACTION_NOT_FOUND,
            )
        return Result(
            data=TransactionDetail.model_validate(txn).model_dump(),
            status=200,
            message=SuccessMessages.TRANSACTION_FETCHED,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error fetching transaction %s: %s", transaction_id, exc)
        return Result(
            status=500,
            message=INTERNAL_SERVER_ERROR,
        )
