import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.services import reconciliation as recon_service
from app.utils.messages import INTERNAL_SERVER_ERROR, SuccessMessages
from app.utils.response_format import Result

logger = logging.getLogger("event_ledger")

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.get(
    "/summary",
    response_model=Result,
    summary="Aggregated transaction summary by status and merchant",
    description="All aggregation is performed at the DB level — no Python-side iteration over rows.",
)
async def reconciliation_summary(
    db: AsyncSession = Depends(db_session),
) -> Result:
    try:
        summary = await recon_service.get_summary(db)
        return Result(
            data=summary.model_dump(),
            status=200,
            message=SuccessMessages.RECONCILIATION_SUMMARY,
        )
    except Exception as exc:
        logger.exception("Error fetching reconciliation summary: %s", exc)
        return Result(
            status=500,
            message=INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/discrepancies",
    response_model=Result,
    summary="Detect reconciliation discrepancies",
    description=(
        "Detects: stale processed transactions, conflicting terminal events "
        "(both settled and failed), and late failure events after settlement."
    ),
)
async def reconciliation_discrepancies(
    db: AsyncSession = Depends(db_session),
) -> Result:
    try:
        discrepancies = await recon_service.get_discrepancies(db)
        return Result(
            data=discrepancies.model_dump(),
            status=200,
            message=SuccessMessages.RECONCILIATION_DISCREPANCIES,
        )
    except Exception as exc:
        logger.exception("Error fetching reconciliation discrepancies: %s", exc)
        return Result(
            status=500,
            message=INTERNAL_SERVER_ERROR,
        )
