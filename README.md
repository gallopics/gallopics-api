# Gallopics API

Backend API for gallopics.com -- an equestrian event platform that aggregates events from TDB, enriches them with results from Equipe, and supports photographer galleries with Klarna payments.

## Prerequisites

- Python 3.10+
- PostgreSQL (running locally)
- Redis (running locally)

## Quick Start

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Set up environment variables
cp .env.example .env
# Edit .env with your actual credentials (database, Clerk, Klarna, etc.)

# 4. Create the database
createdb gallopics_dev

# 5. Run migrations
alembic upgrade head

# 6. Start the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at http://localhost:8000. Interactive docs at http://localhost:8000/docs.

## Render Deployment

This repo includes a `render.yaml` Blueprint that provisions the web service, Postgres database, and Redis-compatible Key Value instance.

Render runs `scripts/deploy.sh` before starting the web service. That command:

1. Applies Alembic migrations so the database schema matches the SQLAlchemy models.
2. Populates event data by running the TDB and Equipe sync logic directly.

Set `TDB_BASE_URL` and `EQUIPE_BASE_URL` in Render for population to run. If either value is empty, that sync is skipped.

After the service is live, you can rerun the same imports through the API:

```bash
SERVICE_URL=https://gallopics-api.onrender.com bash scripts/post_deploy_sync.sh
```

## Running Tests

Tests use SQLite (in-memory) and fakeredis -- no real database or Redis needed.

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

# Start the Celery Beat scheduler (periodic TDB/Equipe sync)
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
  services/            Business logic (EventService, MatchingService, ...)
  integrations/        External API clients (TDB, Equipe, Klarna, Clerk)
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

### Authenticated (Bearer token)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/me` | Current user profile |
| GET | `/api/v1/me/orders` | My orders |
| POST | `/api/v1/checkout/sessions` | Create Klarna checkout session |
| POST | `/api/v1/checkout/authorize` | Authorize payment |
| GET | `/api/v1/orders/{id}` | Get order (owner or admin) |

### Photographer (role: photographer)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/photographer/uploads/sessions` | Create upload session |
| POST | `/api/v1/photographer/uploads/complete` | Complete upload |
| GET | `/api/v1/photographer/photos` | List my photos |
| PATCH | `/api/v1/photographer/photos/{id}` | Update photo |
| DELETE | `/api/v1/photographer/photos/{id}` | Delete photo |

### Admin (role: admin)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/orders` | List all orders |
| POST | `/api/v1/admin/events/{id}/match` | Manual event match |
| POST | `/api/v1/admin/events/{id}/unmatch` | Remove event match |
| POST | `/api/v1/orders/{id}/capture` | Capture payment |
| POST | `/api/v1/orders/{id}/refund` | Refund payment |
| POST | `/api/v1/orders/{id}/cancel` | Cancel payment |

### Integrations (admin)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/integrations/tdb/sync` | Trigger TDB event sync |
| POST | `/api/v1/integrations/equipe/sync` | Trigger Equipe sync + matching |
| POST | `/api/v1/integrations/events/rematch` | Re-run matching |
| GET | `/api/v1/integrations/events/unmatched` | List unmatched events |

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://localhost/gallopics_dev` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `CLERK_JWKS_URL` | Clerk JWKS endpoint for JWT validation | -- |
| `KLARNA_API_URL` | Klarna API base URL | `https://api.playground.klarna.com` |
| `STORAGE_BACKEND` | `local` or `s3` | `local` |
| `STORAGE_LOCAL_PATH` | Path for local file storage | `./uploads` |
| `CELERY_BROKER_URL` | Redis URL for Celery broker | `redis://localhost:6379/1` |
| `TDB_BASE_URL` | TDB API base URL | -- |
| `EQUIPE_BASE_URL` | Equipe API base URL | -- |
