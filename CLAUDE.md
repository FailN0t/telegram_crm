# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram CRM Console (MTProto) - A system for initiating first-contact messaging through Telegram using MTProto (personal accounts, not bots). Features multi-account support, local UI console, API endpoints, message queuing, anti-spam controls, and optional AmoCRM/Bitrix24 integration.

## Essential Development Commands

### Setup and Installation
```bash
# Install dependencies
pip3 install -r requirements-production.txt

# Development dependencies (includes testing tools)
pip3 install -r requirements-dev.txt

# Setup environment
cp env.template .env
# Edit .env with required values (see Minimum Configuration below)

# Run database migrations
python3 -m alembic upgrade head
```

### Running the Application
```bash
# Start main API server (includes MTProto client if OUTBOX_PROCESS_INLINE=true)
python3 -m src.main

# Start outbox worker separately (if OUTBOX_PROCESS_INLINE=false)
python3 -m src.outbox_worker
```

### Testing
```bash
# Run all tests (uses SQLite by default)
python3 -m unittest

# Run specific test module
python3 -m unittest tests.test_ui_api
python3 -m unittest tests.test_outbox_models
python3 -m unittest tests.test_migration_fk

# Run tests on PostgreSQL (recommended before production)
DATABASE_URL=postgresql://postgres:pass@localhost:5432/telegram_bot_test \
DB_ALLOW_CREATE_ALL=true \
DB_USE_NULL_POOL=true \
python3 -m unittest discover -s tests

# Load testing with Locust
locust -f tests/load/locustfile.py --host http://localhost:8000
```

### Database Migrations
```bash
# Create new migration
python3 -m alembic revision --autogenerate -m "description"

# Apply migrations
python3 -m alembic upgrade head

# Rollback one migration
python3 -m alembic downgrade -1

# Check current migration version
python3 -m alembic current
```

### Production Deployment
```bash
# Using Docker Compose
docker-compose -f docker-compose.production.yml up -d

# With observability stack
docker-compose -f docker-compose.production.yml -f docker-compose.observability.yml up -d
```

## Minimum Configuration

Required environment variables in `.env`:
- `TELEGRAM_API_ID` - From https://my.telegram.org
- `TELEGRAM_API_HASH` - From https://my.telegram.org
- `TELEGRAM_PHONE` - Phone number with + prefix
- `API_SECRET_KEY` - Secret key for external API authentication
- `DATABASE_URL` - PostgreSQL connection string

Supports `*_FILE` variables for Docker/K8s secrets (e.g., `API_SECRET_KEY_FILE=/run/secrets/api_secret_key`).

## Architecture Overview

### Core Components

1. **API Server** (`src/api_server.py`)
   - FastAPI application serving public API (`/api/*`) and UI API (`/api/ui/*`)
   - Static files and UI pages (`/ui`, `/ui/auth`, `/admin`)
   - SSE streaming endpoint (`/api/ui/stream`) for real-time UI updates
   - Metrics endpoint (`/metrics`) when `ENABLE_METRICS=true`

2. **MTProto Client Manager** (`src/telegram_manager.py`, `src/telegram_client.py`)
   - Multi-account support with round-robin selection
   - Telethon-based MTProto client for each account
   - Handles authorization, message sending, and incoming message events
   - Stores sessions in DB (`telegram_accounts.session_string`)

3. **Outbox Queue System** (`src/outbox.py`, `src/outbox_worker.py`)
   - Database-backed message queue (`message_outbox` table)
   - Retry logic with exponential backoff
   - Per-chat ordering guarantees
   - Two modes:
     - **Inline** (`OUTBOX_PROCESS_INLINE=true`): API server processes queue
     - **Worker** (`OUTBOX_PROCESS_INLINE=false`): Separate worker process

4. **Bridge Layer** (`src/bridge.py`)
   - Abstraction between Telegram and CRM systems
   - Maps Telegram chat_id ↔ CRM contact_id
   - Routes messages between systems
   - Provider-agnostic (AmoCRM or Bitrix24)

5. **CRM Clients** (`src/amocrm_client.py`, `src/bitrix24_client.py`)
   - OAuth token management with auto-refresh
   - Contact field mapping for Telegram data
   - Webhook handling for CRM events

6. **Anti-Spam Manager** (`src/antispam.py`)
   - Global limits: messages per hour, new chats per day, min delay between messages
   - Per-operator limits (stored in `operators` table)
   - Redis-backed counters for distributed rate limiting
   - Enforces compliance: consent checking, quiet hours, opt-out

### Data Flow

**Outgoing Messages (API)**:
```
POST /api/send-message
  → Idempotency check
  → Anti-spam validation
  → MessageOutbox (status=queued)
  → OutboxWorker polls queue
  → MTProto send
  → Update MessageOutbox (status=sent/failed)
  → MessageDeliveryAttempt record
  → UiMessageHistory record
```

**Outgoing Messages (UI)**:
```
POST /api/ui/send
  → Basic Auth (operator_id extracted from username)
  → Anti-spam validation (global + per-operator)
  → MessageOutbox + UiMessageHistory (status=queued)
  → OutboxWorker sends
  → UiMessageHistory updated (status=sent/failed)
  → SSE event to /api/ui/stream
```

**Incoming Messages**:
```
Telegram event (MTProto)
  → UiMessageHistory (status=received)
  → ChatMapping lookup for CRM mapping
  → MessageHistory record (if mapped)
  → SSE event to /api/ui/stream
```

### Key Database Tables

Account and mapping:
- `telegram_accounts` - Multi-account MTProto credentials and sessions
- `chat_mappings` - Telegram chat_id ↔ CRM contact_id links (includes `account_id`)
- `chat_profiles` - Per-chat metadata (tags, consent, quiet hours)

Messaging:
- `message_outbox` - Outgoing message queue (includes `account_id`, `operator_id`)
- `message_delivery_attempts` - Delivery attempt logs with backoff tracking
- `message_inbox` - Webhook deduplication via payload hash
- `message_history` - CRM-visible message history
- `ui_message_history` - UI-visible history with status tracking (includes `account_id`)

UI state:
- `ui_chats` - Aggregated chat state (last_message, unread count)
- `ui_event_log` - System event journal for UI display
- `message_templates` - Saved message templates
- `tag_catalog` - Available tags for chat categorization

Operations:
- `operators` - Operator metadata with hourly/daily limits
- `app_settings` - Admin UI overrides for .env settings (requires restart for some)
- `audit_log` - Admin action audit trail

### Multi-Account System

- Each Telegram account stored in `telegram_accounts` table with `phone_number` and `session_string`
- Default account created from `TELEGRAM_PHONE` + `TELEGRAM_STRING_SESSION` env vars
- UI allows switching between accounts (`/api/ui/accounts/switch`)
- Round-robin account selection for outgoing messages (`TelegramClientManager.select_account_id()`)
- All relevant tables include `account_id` foreign key with CASCADE delete

### Idempotency

- External API: `Idempotency-Key` header (auto-generated from payload if missing)
- Webhooks: `message_inbox` with `payload_hash` prevents duplicate processing
- UI sends: Optional `idempotency_key` parameter

### Two Operating Modes

**Inline Mode** (default, `OUTBOX_PROCESS_INLINE=true`):
- API server initializes MTProto clients on startup
- Messages sent immediately after queueing
- Simpler deployment (single process)

**Worker Mode** (`OUTBOX_PROCESS_INLINE=false`):
- API server does not connect to Telegram
- Separate `outbox_worker` process handles delivery
- Better separation of concerns for production
- Recommended for horizontal scaling

## Code Organization Patterns

### Configuration Priority
1. Admin UI overrides (`app_settings` table) - loaded at startup via `refresh_settings_from_db()`
2. Environment variables (`.env` file)
3. `*_FILE` secrets (Docker/K8s)
4. Pydantic defaults in `src/config.py`

### Database Access
- Async SQLAlchemy with asyncpg (Postgres) or aiosqlite (SQLite)
- Use `get_db()` dependency for FastAPI routes
- SessionLocal for standalone operations
- Foreign key constraints enabled with CASCADE deletes
- NullPool mode for testing (`DB_USE_NULL_POOL=true`)

### Error Handling
- Errors tracked via `src/observability.py` with optional Sentry-compatible DSN
- UI events logged to `ui_event_log` table
- Admin actions logged to `audit_log`
- Prometheus metrics exported at `/metrics`

### Testing Strategy
- Unit tests use SQLite in-memory or file-based DBs
- Critical tests should also run on Postgres (`test_migration_fk.py` example)
- Test files create isolated DBs: `test_ui.db`, `test_outbox.db`, etc.
- Clean test databases before running if seeing UNIQUE constraint errors
- Load tests in `tests/load/` using Locust

## Critical Development Notes

### MTProto Safety
- MTProto uses personal Telegram accounts (not bot API)
- Session files (`.session`) grant full account access - treat as credentials
- Use separate phone numbers for development/production
- Respect rate limits to avoid account restrictions
- Always obtain user consent before messaging

### Database Migrations
- Never edit existing migration files after they're committed
- Always use `alembic revision --autogenerate` for schema changes
- Test migrations on Postgres before merging (SQLite lacks some constraints)
- Foreign key constraints are enforced - ensure proper CASCADE settings

### Anti-Spam Enforcement
- Global limits in `.env` override by per-operator limits in DB
- Redis required for distributed rate limiting (falls back to in-memory)
- AntiSpamManager uses `try_register_send()` - never call `can_send_message()` directly
- Quiet hours respect `chat_profiles.quiet_hours_start/end` and `DEFAULT_TIMEZONE`

### CRM Provider Selection
- Set `CRM_PROVIDER=amocrm` or `CRM_PROVIDER=bitrix24` in `.env`
- Bridge layer (`src/bridge.py`) automatically routes to correct client
- Field mappings differ: AmoCRM uses numeric IDs, Bitrix24 uses `UF_CRM_*` names
- Bitrix24 supports Open Channels for bidirectional chat in contact cards

### UI Basic Auth and Operators
- Enable with `UI_BASIC_AUTH_ENABLED=true` and `UI_BASIC_AUTH_USERS=user:pass:role,...`
- Operators auto-created on first message send (username from Basic Auth)
- Operator limits editable at `/ui/operators` (admin role required)
- Operator username passed to outbox queue for per-operator anti-spam enforcement

### SSE Event Streaming
- UI subscribes to `/api/ui/stream` for real-time updates
- Event types: `ui_message` (new messages/status updates), `ui_event` (system events)
- Events published via in-memory deque (single-server architecture)
- No persistence - reconnect if connection drops

### Data Retention
- Cleanup runs via `src/retention.py` module
- Configurable retention periods: `UI_MESSAGE_RETENTION_DAYS`, `UI_EVENT_RETENTION_DAYS`, etc.
- Set to `0` to disable cleanup for that table
- Consider running as periodic job (not included in main server)

## Common Pitfalls

1. **Test database conflicts**: Delete SQLite test files (`test_*.db`) before running tests
2. **Redis auth errors**: Set `REDIS_URL` with password or configure Redis to allow no-auth
3. **Migration failures on Postgres**: Test with `DB_ALLOW_CREATE_ALL=true` and `DB_USE_NULL_POOL=true`
4. **Worker not processing**: Verify `OUTBOX_PROCESS_INLINE=false` and worker is running
5. **MTProto 2FA**: Phone code hash stored in Redis - ensure Redis is available during auth
6. **Account switching**: UI must call `/api/ui/accounts/switch` before sending from different account
7. **Admin settings changes**: Some settings require worker restart (noted in admin UI)

## Documentation Reference

Comprehensive documentation available:
- `QUICKSTART.md` - Step-by-step local setup
- `CONFIGURATION.md` - Full `.env` reference
- `ARCHITECTURE.md` - Detailed data flows and components
- `API.md` - API endpoint documentation with examples
- `TESTING.md` - Testing strategies and troubleshooting
- `DEPLOYMENT.md` - Production deployment guide
- `MTPROTO_GUIDE.md` - MTProto risks, limits, and compliance
- `OBSERVABILITY.md` - Metrics, logs, and error tracking
- `RUNBOOK.md` - Incident response and recovery procedures
