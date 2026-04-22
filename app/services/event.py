import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.event import event_repo
from app.repositories.merchant import merchant_repo
from app.repositories.transaction import transaction_repo
from app.schemas.event import EventCreate, EventIngestResponse

logger = logging.getLogger("event_ledger.event_service")

# Maps each event_type to its derived transaction status
EVENT_TO_STATUS: dict[str, str] = {
    "payment_initiated": "initiated",
    "payment_processed": "processed",
    "payment_failed": "failed",
    "settled": "settled",
}

# Higher priority = closer to a final resolved state.
# Out-of-order delivery is handled by only advancing to a higher-priority status.
# This means: if 'settled' arrives before 'processed', the transaction is settled.
# The original events are preserved in the append-only log for auditing.
STATUS_PRIORITY: dict[str, int] = {
    "initiated": 1,
    "processed": 2,
    "failed": 3,
    "settled": 4,
}


async def ingest_event(payload: EventCreate, db: AsyncSession) -> EventIngestResponse:
    # --- Idempotency check (fast path via indexed event_id lookup) ---
    existing = await event_repo.get_by_event_id(db, payload.event_id)
    if existing:
        logger.debug("Duplicate event received: %s", payload.event_id)
        txn = await transaction_repo.get_by_transaction_id(db, payload.transaction_id)
        return EventIngestResponse(
            event_id=payload.event_id,
            status="duplicate",
            transaction_id=payload.transaction_id,
            transaction_status=txn.status if txn else "unknown",
            message="Event already processed; no changes applied.",
        )

    # --- Upsert merchant ---
    merchant = await merchant_repo.get_or_create(
        db, merchant_id=payload.merchant_id, name=payload.merchant_name
    )

    # --- Get or create transaction ---
    txn = await transaction_repo.get_by_transaction_id(db, payload.transaction_id)
    if txn is None:
        txn = await transaction_repo.create(
            db,
            transaction_id=payload.transaction_id,
            merchant_id=merchant.id,
            amount=payload.amount,
            currency=payload.currency,
        )

    # --- Append event (append-only; duplicates already rejected above) ---
    await event_repo.create(
        db,
        event_id=payload.event_id,
        event_type=payload.event_type,
        transaction_id=txn.id,
        amount=payload.amount,
        currency=payload.currency,
        timestamp=payload.timestamp,
    )

    # --- State machine: only advance to higher-priority status ---
    incoming_status = EVENT_TO_STATUS[payload.event_type]
    current_priority = STATUS_PRIORITY.get(txn.status, 0)
    incoming_priority = STATUS_PRIORITY[incoming_status]

    if incoming_priority > current_priority:
        await transaction_repo.update_status(db, txn.id, incoming_status)
        final_status = incoming_status
        logger.info(
            "Transaction %s status: %s → %s",
            payload.transaction_id,
            txn.status,
            incoming_status,
        )
    else:
        final_status = txn.status
        logger.debug(
            "Out-of-order event for %s: incoming=%s (priority %d) <= current=%s (priority %d); status unchanged.",
            payload.transaction_id,
            incoming_status,
            incoming_priority,
            txn.status,
            current_priority,
        )

    return EventIngestResponse(
        event_id=payload.event_id,
        status="accepted",
        transaction_id=payload.transaction_id,
        transaction_status=final_status,
    )
