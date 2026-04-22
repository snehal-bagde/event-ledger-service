# Event Ledger Service

Payment lifecycle event ingestion and reconciliation API built with FastAPI, PostgreSQL, and Redis.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.14+ | `brew install python@3.14` |
| Poetry | 2.x | [poetry install docs](https://python-poetry.org/docs/#installation) |
| PostgreSQL | 14+ | `brew install postgresql@16` |
| Redis | 7+ | `brew install redis` _(optional — see below)_ |

> **pyenv users:** pyenv sets `VIRTUAL_ENV` in the shell and overrides Poetry's
> env detection. Run `deactivate` or open a fresh terminal before using Poetry.

---

## Setup

```bash
# 1. Install dependencies
poetry install

# 2. Configure environment (create .env with required variables — see below)
touch .env

# 3. Run database migrations
poetry run alembic upgrade head

# 4. Start the server
poetry run uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`

---

## Environment Variables

Create a `.env` file in the project root with the following:

```ini
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>
REDIS_URL=redis://<host>:6379/0
REDIS_ENABLED=true

# Optional overrides (these are the defaults)
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_EVENTS_POST=500/minute
LOG_LEVEL=INFO
LOG_JSON=true
PROCESSED_STALE_HOURS=24
```

Set `REDIS_ENABLED=false` to fall back to in-memory rate limiting (development only).

---

## Daily Commands

```bash
poetry run uvicorn app.main:app --reload          # dev server
poetry run alembic upgrade head                   # apply migrations
poetry run alembic revision --autogenerate -m ""  # generate a new migration
poetry run python scripts/load_events.py          # bulk load sample_events.json
poetry add <package>                              # add a dependency
```

---

## Loading Sample Data

```bash
# Load sample_events.json — idempotent, safe to re-run
poetry run python scripts/load_events.py

# Options
poetry run python scripts/load_events.py --file path/to/file.json --batch-size 1000
poetry run python scripts/load_events.py --dry-run   # validate only, no DB writes
```

The loader handles duplicates (`ON CONFLICT DO NOTHING`), out-of-order events, and
re-runs without breaking existing data.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/events` | Ingest a payment event (idempotent) |
| `GET` | `/api/v1/transactions` | List transactions with filters + pagination |
| `GET` | `/api/v1/transactions/{id}` | Transaction detail + full event history |
| `GET` | `/api/v1/reconciliation/summary` | Aggregated stats by status and merchant |
| `GET` | `/api/v1/reconciliation/discrepancies` | Detect anomalous transactions |
| `GET` | `/api/v1/health` | Health check |

### POST /api/v1/events

```json
{
  "event_id": "b768e3a7-9eb3-4603-b21c-a54cc95661bc",
  "event_type": "payment_initiated",
  "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
  "merchant_id": "merchant_1",
  "merchant_name": "QuickMart",
  "amount": "1500.00",
  "currency": "INR",
  "timestamp": "2026-01-08T12:11:58+00:00"
}
```

Valid `event_type` values: `payment_initiated` · `payment_processed` · `payment_failed` · `settled`

**202 Accepted:**
```json
{ "event_id": "...", "status": "accepted", "transaction_id": "...", "transaction_status": "initiated" }
```

Re-submitting the same `event_id` returns `"status": "duplicate"` — no state changes applied.

### GET /api/v1/transactions

| Param | Type | Description |
|-------|------|-------------|
| `merchant_id` | string | Filter by merchant |
| `status` | string | `initiated` · `processed` · `failed` · `settled` |
| `date_from` / `date_to` | ISO 8601 | Filter by `created_at` range |
| `sort_by` | string | `created_at` · `updated_at` · `amount` · `status` |
| `sort_order` | string | `asc` · `desc` (default `desc`) |
| `limit` / `offset` | int | Pagination (limit max 100, default 20) |

---

## Architecture

```
app/
├── api/v1/          # Thin route handlers — delegate to services
├── services/        # Business logic: state machine, reconciliation queries
├── repositories/    # Async SQLAlchemy 2.0 queries
├── models/          # ORM models (UUID v7 primary keys)
├── schemas/         # Pydantic v2 request / response models
├── core/            # Config, structured logging, exception handlers
└── db/              # Async engine + session factory
```

### Event State Machine

Status advances by priority only — never regresses. Handles out-of-order delivery correctly.

```
payment_initiated → initiated  (priority 1)
payment_processed → processed  (priority 2)
payment_failed    → failed     (priority 3)
settled           → settled    (priority 4)
```

If `settled` arrives before `processed`, the transaction lands in `settled` immediately.
All events are preserved in the append-only `events` table regardless of arrival order.

### Idempotency

`event_id` carries a `UNIQUE` constraint at the database level — concurrent duplicates
are rejected before any application logic runs. The service layer also does an early
read to return a clean `"status": "duplicate"` response without opening a write transaction.

### Reconciliation Discrepancies

| Type | Condition |
|------|-----------|
| `stale_processed` | `status = processed` for longer than `PROCESSED_STALE_HOURS` |
| `conflicting_terminal_events` | Both `settled` and `payment_failed` events exist on the same transaction |
| `late_failure_after_settlement` | A `payment_failed` event has a later timestamp than the `settled` event |

---

## Future Improvements

### Async Queue-Based Event Processing

Currently `POST /api/v1/events` processes events synchronously — the state machine runs and the DB is written within the same HTTP request before the `202` is returned. This works correctly but couples ingestion latency to DB write latency.

A production-grade improvement is to decouple ingestion from processing:

```
Client → POST /events → push raw event to queue → 202 immediately
                                ↓
                         Worker consumes queue
                                ↓
                    State machine + DB write
```

**Retry strategy — exponential backoff with jitter**

If the worker fails to process an event (transient DB error, network blip), it should retry with:

```
delay = min(cap, base × 2^attempt) + random(0, jitter)
```

For example with `base=1s`, `cap=60s`, `jitter=2s`:

| Attempt | Base delay | +jitter | Actual wait |
|---------|-----------|---------|-------------|
| 1 | 2s | +0.8s | 2.8s |
| 2 | 4s | +1.4s | 5.4s |
| 3 | 8s | +0.3s | 8.3s |
| 4 | 16s | +1.9s | 17.9s |
| 5 | 32s | +1.1s | 33.1s |

The random jitter prevents a thundering herd — if many workers restart simultaneously, they don't all hammer the DB at the same intervals.

**Dead Letter Queue (DLQ)**

Events that exhaust all retries are moved to a Dead Letter Queue instead of being silently dropped. This provides:

- **Alerting** — ops team is notified when events land in the DLQ
- **Inspection** — the raw event payload is preserved for debugging
- **Replay** — once the root cause is fixed, events can be replayed from the DLQ back into the main queue without re-ingestion from the source system

Suitable queue backends: Redis Streams, AWS SQS + SQS DLQ, RabbitMQ with dead-letter exchanges.

---