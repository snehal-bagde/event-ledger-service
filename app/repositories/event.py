import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event


class EventRepository:
    async def get_by_event_id(
        self, db: AsyncSession, event_id: str
    ) -> Event | None:
        result = await db.execute(
            select(Event).where(Event.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        *,
        event_id: str,
        event_type: str,
        transaction_id: uuid.UUID,
        amount,
        currency: str,
        timestamp: datetime,
    ) -> Event:
        event = Event(
            event_id=event_id,
            event_type=event_type,
            transaction_id=transaction_id,
            amount=amount,
            currency=currency,
            timestamp=timestamp,
            received_at=datetime.now(tz=timezone.utc),
        )
        db.add(event)
        await db.flush()
        return event


event_repo = EventRepository()
