import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.event import EventCreate
from app.services import event as event_service
from app.utils.messages import INTERNAL_SERVER_ERROR, SuccessMessages
from app.utils.response_format import Result

logger = logging.getLogger("event_ledger")

router = APIRouter(prefix="/events", tags=["Events"])


# NOTE: This endpoint processes events synchronously — the state machine runs and
# the DB is written within the same request before 202 is returned. The 202 status
# signals "event accepted into the ledger", not "queued for future processing".
#
# Production improvement: push the raw event onto a queue (Redis Streams / SQS /
# RabbitMQ) here and return 202 immediately. A separate worker consumes the queue,
# runs the state machine, and writes to the DB. Use exponential backoff with random
# jitter on retries (e.g. delay = min(cap, base * 2^attempt) + random(0, jitter))
# to avoid thundering herd on transient failures. Events that exceed the max retry
# count are moved to a Dead Letter Queue (DLQ) for manual inspection, alerting, and
# replay — ensuring no event is silently dropped even when the worker is degraded.
@router.post(
    "",
    response_model=Result,
    summary="Ingest a payment lifecycle event",
    description=(
        "Idempotent endpoint. Re-submitting an event with the same `event_id` "
        "returns 200 with `duplicate` status without modifying state."
    ),
)
@limiter.limit(settings.RATE_LIMIT_EVENTS_POST)
async def ingest_event(
    request: Request,
    payload: EventCreate,
    response: Response,
    db: AsyncSession = Depends(db_session),
) -> Result:
    try:
        result = await event_service.ingest_event(payload, db)

        if result.status == "duplicate":
            response.status_code = status.HTTP_200_OK
            return Result(
                data=result.model_dump(),
                status=status.HTTP_200_OK,
                message=SuccessMessages.EVENT_DUPLICATE,
            )

        response.status_code = status.HTTP_202_ACCEPTED
        return Result(
            data=result.model_dump(),
            status=status.HTTP_202_ACCEPTED,
            message=SuccessMessages.EVENT_ACCEPTED,
        )
    except Exception as exc:
        logger.exception("Error ingesting event %s: %s", payload.event_id, exc)
        return Result(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=INTERNAL_SERVER_ERROR,
        )
