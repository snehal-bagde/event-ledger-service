import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.uuid import new_uuid


class Event(Base):
    __tablename__ = "events"

    __table_args__ = (
        Index("idx_events_transaction_id", "transaction_id"),
        Index("idx_events_event_type", "event_type"),
        Index("idx_events_timestamp", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    # Unique per external event — this is the idempotency key
    event_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="events", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<Event {self.event_id} type={self.event_type}>"
