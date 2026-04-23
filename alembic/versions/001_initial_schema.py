"""Initial schema: merchants, transactions, events

Revision ID: 001
Revises:
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- merchants ---
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", name="uq_merchants_merchant_id"),
    )
    op.create_index("idx_merchants_merchant_id", "merchants", ["merchant_id"])

    # --- transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", sa.String(36), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(20), nullable=False, server_default="initiated"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name="fk_transactions_merchant"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_transactions_transaction_id"),
    )
    op.create_index("idx_transactions_transaction_id", "transactions", ["transaction_id"])
    op.create_index("idx_transactions_merchant_id", "transactions", ["merchant_id"])
    op.create_index("idx_transactions_status", "transactions", ["status"])
    op.create_index("idx_transactions_created_at", "transactions", ["created_at"])
    op.create_index(
        "idx_transactions_merchant_status", "transactions", ["merchant_id", "status"]
    )

    # --- events ---
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name="fk_events_transaction"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_events_event_id"),
    )
    op.create_index("idx_events_event_id", "events", ["event_id"])
    op.create_index("idx_events_transaction_id", "events", ["transaction_id"])
    op.create_index("idx_events_event_type", "events", ["event_type"])
    op.create_index("idx_events_timestamp", "events", ["timestamp"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("transactions")
    op.drop_table("merchants")
