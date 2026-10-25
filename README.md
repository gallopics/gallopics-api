# Gallopics API

Backend API for gallopics.com -- an equestrian event platform that aggregates events from TDB, enriches them with results from Equipe, and supports photographer galleries with Stripe payments (Stripe Checkout for buyers, Stripe Connect payouts to photographers).

## Prerequisites

- Python 3.10+
- PostgreSQL (running locally)
- Redis (running locally, for Celery)
- [Stripe CLI](https://docs.stripe.com/stripe-cli) (to receive Stripe webhooks locally)

## Quick Start

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Set up environment variables
# Create .env with the variables listed under "Environment Variables" below
# (database, Clerk, Stripe, etc.)

# 4. Create the database
createdb gallopics_dev

# 5. Run migrations
alembic upgrade head

# 6. Start the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at http://localhost:8000. Interactive docs at http://localhost:8000/docs.

## Stripe (local development)

Use a Stripe test-mode (sandbox) secret key in `STRIPE_SECRET_KEY`. Webhooks reach your machine through the Stripe CLI; run both listeners while testing:

```bash
# Checkout events (orders are paid / expire here)
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired --forward-to localhost:8000/api/v1/checkout/webhook/stripe

# Connect "thin" events (photographers' Stripe accounts: onboarding status)
stripe listen --all-thin --forward-to localhost:8000/api/v1/stripe/connect/webhook
```

Put the `whsec_...` secret printed by the CLI in `STRIPE_WEBHOOK_SECRET`. Locally both listeners use the same secret, so `STRIPE_CONNECT_WEBHOOK_SECRET` can stay empty.

How money flows:

- The buyer pays Gallopics through Stripe Checkout (prices: `app/services/pricing.py`).
- Each sale records the photographer's share (100% - `PLATFORM_COMMISSION_PERCENT`) and transfers it to their connected Stripe account; a share stays owed until the photographer finishes Stripe onboarding.
- Stripe pays connected accounts out monthly, on the 15th.
- Admins can refund an order with `POST /api/v1/orders/{id}/refund` (the photographer's share is reversed or cancelled).

## Server Deployment

Production runs on the server. On each deploy:

1. Pull the code and install dependencies: `pip install -e .` (new dependencies, e.g. `stripe`, are not installed by the deploy script).
2. Run the deploy script: `bash scripts/deploy.sh`.
3. Restart the API process (and the Celery worker and beat, if running).

The deploy script:

1. Applies Alembic migrations so the database schema matches the SQLAlchemy models.
2. Populates event data by running the Equipe sync logic directly.

Set `EQUIPE_BASE_URL` in the server environment for population to run. If it is empty, the sync is skipped.

The API refuses to start when `.env` contains a variable it doesn't know (`Extra inputs are not permitted`), so check variable names when editing `.env`. The old `KLARNA_*` variables are still accepted until they are removed from every server.

For Stripe on a server, create two webhook endpoints in the Stripe Dashboard and put their signing secrets in the environment:

| Endpoint | Events | Secret |
|----------|--------|--------|
| `https://<api-host>/api/v1/checkout/webhook/stripe` | `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired` | `STRIPE_WEBHOOK_SECRET` |
| `https://<api-host>/api/v1/stripe/connect/webhook` (event destination, thin events from connected accounts) | `v2.core.account[...]` events (requirements / configuration updates) | `STRIPE_CONNECT_WEBHOOK_SECRET` |

Live mode requires HTTPS endpoints; test mode also accepts plain HTTP.

After the service is live, you can rerun the same imports through the API by pointing `SERVICE_URL` at the server:

```bash
SERVICE_URL=http://82.96.43.103:8081 bash scripts/post_deploy_sync.sh
```

Production should also run a Celery worker and Celery Beat so the Equipe recent-meetings feed stays fresh (Beat only schedules the sync every 30 minutes; the worker runs it):

```bash
celery -A app.tasks.celery_app worker --loglevel=info
celery -A app.tasks.celery_app beat --loglevel=info
```

Without the periodic sync, newly created Equipe meetings will not appear in `/api/v1/events` until `scripts/post_deploy_sync.sh` or `POST /api/v1/integrations/equipe/sync` is run.

## Running Tests

Tests use SQLite (in-memory) and fakeredis -- no real database, Redis or Stripe needed (Stripe calls are faked).

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v

# Run only Celery task tests
pytest tests/tasks/ -v
```

## Background Workers (Celery)

```bash
# Start a Celery worker
celery -A app.tasks.celery_app worker --loglevel=info

# Start the Celery Beat scheduler (periodic Equipe sync)
celery -A app.tasks.celery_app beat --loglevel=info

# Start both in one command (dev only)
celery -A app.tasks.celery_app worker --beat --loglevel=info
```

## Linting

```bash
ruff check app/ tests/
ruff format app/ tests/
```

## Project Structure

```
app/
  main.py              App factory, router registration
  config.py            Pydantic settings (reads .env)
  database.py          Async SQLAlchemy engine + session
  redis.py             Redis client + CacheService
  exceptions.py        Custom exception hierarchy
  dependencies.py      Shared FastAPI dependencies
  models/              SQLAlchemy models (Event, User, Order, Photo, ...)
  schemas/             Pydantic request/response schemas
  routers/             FastAPI route handlers
  services/            Business logic (EventService, CheckoutService, PayoutService, ...)
  integrations/        External API clients (TDB, Equipe, Stripe, Clerk)
  storage/             Abstract storage backend (local, S3)
  tasks/               Celery background tasks
  middleware/           Logging, error handling, rate limiting
tests/
  conftest.py          Shared fixtures (DB, auth, async client)
  factories.py         Test data factories
  unit/                Unit tests for services, clients, schemas
  integration/         API endpoint tests
  tasks/               Celery task tests
```

## API Endpoints

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/events` | List events (filterable, paginated) |
| GET | `/api/v1/events/{id}` | Get event by ID |
| GET | `/api/v1/events/{id}/results` | Get event results |
| GET | `/api/v1/events/{event_id}/gallery` | Public photo gallery for event |
| GET | `/api/v1/events/{event_id}/gallery/search` | Search gallery by tag |
| GET | `/api/v1/photos/{id}` | Get photo detail |
| GET | `/api/v1/photographers/{slug_or_id}` | Public photographer profile (approved photographers only) |
| POST | `/api/v1/checkout/sessions` | Create a Stripe Checkout session (guest checkout) |
| GET | `/api/v1/checkout/sessions/{session_id}` | Order status + downloads after Checkout |
| POST | `/api/v1/checkout/webhook/stripe` | Stripe Checkout webhook (signed) |
| POST | `/api/v1/stripe/connect/webhook` | Stripe Connect webhook (signed) |

### Authenticated (Bearer token)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/me` | Current user profile |
| GET | `/api/v1/me/orders` | My orders |
| GET | `/api/v1/orders/{id}` | Get order (owner or admin) |

### Photographer (role: photographer)
Writes (bookings, uploads, photo edits, highlights) also require an approved photographer profile.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/photographer/uploads/sessions` | Create upload session |
| POST | `/api/v1/photographer/uploads/complete` | Complete upload |
| GET | `/api/v1/photographer/photos` | List my photos |
| PATCH | `/api/v1/photographer/photos/{id}` | Update photo |
| DELETE | `/api/v1/photographer/photos/{id}` | Delete photo (409 if it has been sold) |
| GET | `/api/v1/photographer/stripe` | My Stripe Connect status |
| POST | `/api/v1/photographer/stripe/onboarding-link` | Link to Stripe onboarding |
| POST | `/api/v1/photographer/stripe/dashboard-link` | Link to the Stripe Express dashboard |
| GET | `/api/v1/photographer/sales` | My sales, shares and payout status |

### Admin (role: admin)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/orders` | List all orders |
| GET | `/api/v1/admin/photographers` | List photographers (`?status=pending\|approved\|suspended`) |
| PATCH | `/api/v1/admin/photographers/{id}` | Approve / reject a photographer (`{"status": ...}`; "suspended" = rejected) |
| POST | `/api/v1/admin/events/{id}/match` | Manual event match |
| POST | `/api/v1/admin/events/{id}/unmatch` | Remove event match |
| POST | `/api/v1/admin/equipe/shows/{meeting_id}/import` | Import one Equipe show |
| POST | `/api/v1/orders/{id}/refund` | Refund an order in Stripe and reverse the photographer's share |

### Integrations (admin)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/integrations/tdb/sync` | Trigger TDB event sync |
| POST | `/api/v1/integrations/equipe/sync` | Trigger Equipe sync + matching |
| POST | `/api/v1/integrations/events/rematch` | Re-run matching |
| GET | `/api/v1/integrations/events/unmatched` | List unmatched events |

## Environment Variables

Key variables (all settings are in `app/config.py`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://localhost/gallopics_dev` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Allowed frontend origins (comma-separated) | `http://localhost:5173,https://gallopics.com,https://www.gallopics.com` |
| `FRONTEND_BASE_URL` | Frontend URL; Stripe sends buyers and photographers back here | `http://localhost:5173` |
| `API_PUBLIC_BASE_URL` | Public API URL used for email download links | -- |
| `CLERK_JWKS_URL` | Clerk JWKS endpoint for JWT validation | -- |
| `CLERK_SECRET_KEY` | Clerk secret key (reads a new user's email from Clerk) | -- |
| `CLERK_JWT_KEY` | Optional Clerk PEM public key: verifies tokens without network calls | -- |
| `CLERK_AUTHORIZED_PARTIES` | Sites allowed in a token's `azp` claim; empty = `CORS_ORIGINS` + `FRONTEND_BASE_URL` | -- |
| `STRIPE_SECRET_KEY` | Stripe secret key (test or live) | -- |
| `STRIPE_WEBHOOK_SECRET` | Signing secret of the Checkout webhook | -- |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Signing secret of the Connect webhook; empty = `STRIPE_WEBHOOK_SECRET` | -- |
| `PLATFORM_COMMISSION_PERCENT` | Gallopics' share of each sale, in percent | `25` |
| `TRANSACTIONAL_EMAIL_ENABLED` | Send Gallopics purchase receipts through Resend | `false` |
| `RESEND_API_KEY` | Resend API key for transactional email | -- |
| `RESEND_API_URL` | Resend API base URL | `https://api.resend.com` |
| `TRANSACTIONAL_EMAIL_FROM` | From address for purchase receipts | `Gallopics <onboarding@resend.dev>` |
| `TRANSACTIONAL_EMAIL_REPLY_TO` | Optional reply-to address for purchase receipts | -- |
| `STORAGE_BACKEND` | `local` or `s3` | `local` |
| `STORAGE_LOCAL_PATH` | Path for local file storage | `./uploads` |
| `CELERY_BROKER_URL` | Redis URL for Celery broker | `redis://localhost:6379/1` |
| `TDB_BASE_URL` | TDB API base URL | -- |
| `EQUIPE_BASE_URL` | Equipe API base URL | `https://online.equipe.com/api/v1` |
