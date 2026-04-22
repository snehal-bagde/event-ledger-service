import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.utils.uuid import new_uuid


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    __table_args__ = (
        Index("idx_transactions_merchant_status", "merchant_id", "status"),
        Index("idx_transactions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    transaction_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="initiated", index=True
    )

    merchant: Mapped["Merchant"] = relationship(
        back_populates="transactions", lazy="raise"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="transaction",
        order_by="Event.timestamp",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.transaction_id} status={self.status}>"
