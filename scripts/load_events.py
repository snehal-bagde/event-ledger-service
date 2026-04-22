"""
Bulk-load sample_events.json into the database.

Runs directly against the DB (bypasses HTTP) for maximum throughput.
Safe to re-run: duplicate event_ids are silently skipped (ON CONFLICT DO NOTHING).

Usage:
    python scripts/load_events.py                         # default: sample_events.json
    python scripts/load_events.py --file path/to/file.json
    python scripts/load_events.py --batch-size 500
    python scripts/load_events.py --dry-run
"""

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.event import Event
from app.models.merchant import Merchant
from app.models.transaction import Transaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_events")

# Maps event_type → transaction status, ordered by priority (higher = wins)
EVENT_TO_STATUS: dict[str, str] = {
    "payment_initiated": "initiated",
    "payment_processed": "processed",
    "payment_failed": "failed",
    "settled": "settled",
}
STATUS_PRIORITY: dict[str, int] = {
    "initiated": 1,
    "processed": 2,
    "failed": 3,
    "settled": 4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk load payment events")
    parser.add_argument(
        "--file",
        default="sample_events.json",
        help="Path to JSON file (default: sample_events.json)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Events per DB transaction (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and parse only — do not write to DB",
    )
    return parser.parse_args()


def load_file(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        logger.error("File not found: %s", p.resolve())
        sys.exit(1)
    logger.info("Loading %s ...", p.resolve())
    with open(p) as f:
        data = json.load(f)
    logger.info("Parsed %d events from file", len(data))
    return data


def validate_event(raw: dict, idx: int) -> dict | None:
    required = {"event_id", "event_type", "transaction_id", "merchant_id",
                "merchant_name", "amount", "currency", "timestamp"}
    missing = required - set(raw.keys())
    if missing:
        logger.warning("Event[%d] missing fields %s — skipped", idx, missing)
        return None
    if raw["event_type"] not in EVENT_TO_STATUS:
        logger.warning("Event[%d] unknown event_type '%s' — skipped", idx, raw["event_type"])
        return None
    return {
        "event_id": str(raw["event_id"]),
        "event_type": str(raw["event_type"]),
        "transaction_id": str(raw["transaction_id"]),
        "merchant_id": str(raw["merchant_id"]),
        "merchant_name": str(raw["merchant_name"]),
        "amount": Decimal(str(raw["amount"])),
        "currency": str(raw.get("currency", "INR")).upper(),
        "timestamp": datetime.fromisoformat(str(raw["timestamp"])),
    }


async def upsert_merchants(session: AsyncSession, merchants: dict[str, str]) -> dict[str, uuid.UUID]:
    """Insert merchants (ignore conflicts) and return merchant_id → UUID map."""
    rows = [{"merchant_id": mid, "name": name} for mid, name in merchants.items()]
    stmt = pg_insert(Merchant).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["merchant_id"])
    await session.execute(stmt)

    result = await session.execute(
        text("SELECT merchant_id, id FROM merchants WHERE merchant_id = ANY(:ids)"),
        {"ids": list(merchants.keys())},
    )
    return {row.merchant_id: row.id for row in result}


async def upsert_transactions(
    session: AsyncSession,
    transactions: dict[str, dict],
    merchant_map: dict[str, uuid.UUID],
) -> dict[str, uuid.UUID]:
    """Insert transactions (ignore conflicts on transaction_id) and return transaction_id → UUID map."""
    rows = []
    for txn_id, txn_data in transactions.items():
        merchant_uuid = merchant_map.get(txn_data["merchant_id"])
        if not merchant_uuid:
            continue
        rows.append({
            "transaction_id": txn_id,
            "merchant_id": merchant_uuid,
            "amount": txn_data["amount"],
            "currency": txn_data["currency"],
            "status": txn_data["status"],
        })

    if rows:
        stmt = pg_insert(Transaction).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["transaction_id"])
        await session.execute(stmt)

    result = await session.execute(
        text("SELECT transaction_id, id FROM transactions WHERE transaction_id = ANY(:ids)"),
        {"ids": list(transactions.keys())},
    )
    return {row.transaction_id: row.id for row in result}


async def update_transaction_statuses(
    session: AsyncSession,
    status_updates: dict[str, str],
    txn_id_map: dict[str, uuid.UUID],
) -> None:
    """Apply priority-based status updates to transactions already in DB."""
    if not status_updates:
        return

    # Fetch current statuses for all affected transactions
    txn_ids = list(status_updates.keys())
    result = await session.execute(
        text("SELECT transaction_id, status FROM transactions WHERE transaction_id = ANY(:ids)"),
        {"ids": txn_ids},
    )
    current_statuses = {row.transaction_id: row.status for row in result}

    to_update: list[dict] = []
    for txn_id, new_status in status_updates.items():
        current = current_statuses.get(txn_id, "initiated")
        if STATUS_PRIORITY.get(new_status, 0) > STATUS_PRIORITY.get(current, 0):
            to_update.append({"tid": txn_id, "status": new_status})

    for item in to_update:
        await session.execute(
            text(
                "UPDATE transactions SET status = :status, updated_at = now() "
                "WHERE transaction_id = :tid"
            ),
            item,
        )


async def insert_events_batch(
    session: AsyncSession,
    events: list[dict],
    txn_id_map: dict[str, uuid.UUID],
) -> int:
    """Bulk insert events; skip duplicates via ON CONFLICT DO NOTHING."""
    rows = []
    now = datetime.now(tz=timezone.utc)
    for e in events:
        txn_uuid = txn_id_map.get(e["transaction_id"])
        if txn_uuid is None:
            continue
        rows.append({
            "event_id": e["event_id"],
            "event_type": e["event_type"],
            "transaction_id": txn_uuid,
            "amount": e["amount"],
            "currency": e["currency"],
            "timestamp": e["timestamp"],
            "received_at": now,
        })

    if not rows:
        return 0

    stmt = pg_insert(Event).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
    result = await session.execute(stmt)
    return result.rowcount if result.rowcount >= 0 else len(rows)


async def run(args: argparse.Namespace) -> None:
    raw_events = load_file(args.file)

    # Validate all events upfront
    validated: list[dict] = []
    invalid = 0
    for i, raw in enumerate(raw_events):
        parsed = validate_event(raw, i)
        if parsed:
            validated.append(parsed)
        else:
            invalid += 1

    logger.info("Valid: %d | Invalid/skipped: %d", len(validated), invalid)

    if args.dry_run:
        logger.info("[DRY RUN] No changes written to database.")
        return

    # Deduplicate merchants and build transaction snapshots
    # For transactions: track the highest-priority status seen across all events
    merchants: dict[str, str] = {}
    txn_snapshot: dict[str, dict] = {}
    txn_final_status: dict[str, str] = {}

    for e in validated:
        merchants[e["merchant_id"]] = e["merchant_name"]

        tid = e["transaction_id"]
        if tid not in txn_snapshot:
            txn_snapshot[tid] = {
                "merchant_id": e["merchant_id"],
                "amount": e["amount"],
                "currency": e["currency"],
                "status": "initiated",
            }

        incoming_status = EVENT_TO_STATUS[e["event_type"]]
        current_priority = STATUS_PRIORITY.get(txn_final_status.get(tid, "initiated"), 0)
        if STATUS_PRIORITY[incoming_status] > current_priority:
            txn_final_status[tid] = incoming_status

    # Set final status on snapshot
    for tid, status in txn_final_status.items():
        if tid in txn_snapshot:
            txn_snapshot[tid]["status"] = status

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_inserted = 0
    total_skipped = 0
    start_time = time.perf_counter()

    async with async_session() as session:
        # 1. Upsert all merchants (single batch)
        logger.info("Upserting %d merchants ...", len(merchants))
        merchant_map = await upsert_merchants(session, merchants)
        await session.commit()

        # 2. Upsert all transactions (single batch)
        logger.info("Upserting %d transactions ...", len(txn_snapshot))
        txn_id_map = await upsert_transactions(session, txn_snapshot, merchant_map)
        await session.commit()

    # 3. Insert events in batches; update statuses per batch
    batch_size = args.batch_size
    batches = [validated[i:i + batch_size] for i in range(0, len(validated), batch_size)]

    logger.info(
        "Inserting %d events in %d batches of %d ...",
        len(validated),
        len(batches),
        batch_size,
    )

    for batch_num, batch in enumerate(batches, 1):
        async with async_session() as session:
            # Re-fetch txn map (may have grown across batches if new txns appear)
            batch_txn_ids = list({e["transaction_id"] for e in batch})
            result = await session.execute(
                text("SELECT transaction_id, id FROM transactions WHERE transaction_id = ANY(:ids)"),
                {"ids": batch_txn_ids},
            )
            batch_txn_map = {row.transaction_id: row.id for row in result}

            inserted = await insert_events_batch(session, batch, batch_txn_map)
            total_inserted += inserted
            total_skipped += len(batch) - inserted

            # Update statuses for transactions in this batch
            batch_status_updates = {
                e["transaction_id"]: txn_final_status.get(e["transaction_id"], "initiated")
                for e in batch
            }
            await update_transaction_statuses(session, batch_status_updates, batch_txn_map)

            await session.commit()

        if batch_num % 5 == 0 or batch_num == len(batches):
            elapsed = time.perf_counter() - start_time
            rate = (batch_num * batch_size) / elapsed
            logger.info(
                "Progress: batch %d/%d | ~%.0f events/sec | inserted=%d skipped=%d",
                batch_num,
                len(batches),
                rate,
                total_inserted,
                total_skipped,
            )

    await engine.dispose()

    elapsed = time.perf_counter() - start_time
    logger.info(
        "Done in %.2fs | Inserted: %d | Skipped (duplicates): %d",
        elapsed,
        total_inserted,
        total_skipped,
    )


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
