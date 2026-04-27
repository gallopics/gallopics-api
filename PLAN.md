# Gallopics API — Phased Implementation Plan

## Context

Build a production-grade FastAPI backend for gallopics.com — an equestrian event platform. The system ingests events from TDB (Swedish equestrian database), enriches them with results from Equipe, matches/merges across sources, manages photographer photo uploads with galleries, handles Klarna payments, and uses Clerk for auth. This is a greenfield project (only `spec.txt` exists).

**Key decisions**: Python 3.10+, local Postgres/Redis (no Docker), Celery for background jobs, abstract storage interface (S3/R2/local swappable), phased build with tests at every sub-step.

---

## Target Directory Layout

```
by-spec/
├── pyproject.toml
├── alembic.ini
├── .env.example / .env (gitignored)
├── .gitignore
├── alembic/
│   ├── env.py, script.py.mako, versions/
├── app/
│   ├── main.py                    # FastAPI app factory + lifespan
│   ├── config.py                  # pydantic-settings
│   ├── database.py                # async SQLAlchemy engine + session
│   ├── redis.py                   # Redis client + CacheService
│   ├── dependencies.py            # shared Depends helpers
│   ├── exceptions.py              # custom exception hierarchy
│   ├── middleware/                 # rate_limit, logging, error_handler
│   ├── models/                    # base, enums, event, user, order, photographer
│   ├── schemas/                   # common, event, user, order, photographer, checkout, admin
│   ├── routers/                   # health, events, users, checkout, orders, photographer, gallery, photo_purchase, integrations, admin
│   ├── services/                  # event, user, order, photographer, gallery, photo_purchase, matching, image_processing, audit
│   ├── integrations/              # tdb/, equipe/, klarna/, clerk/
│   ├── storage/                   # base (ABC), local, s3
│   └── tasks/                     # celery_app, tdb_sync, equipe_sync, matching, image_processing
└── tests/
    ├── conftest.py, factories.py
    ├── unit/                      # test per service, client, normalizer, storage, auth
    ├── integration/               # test per router endpoint group
    └── tasks/                     # test per Celery task
```

---

## Phase 0: Project Scaffolding (7 sub-steps)

### 0.1 — Git init, pyproject.toml, .gitignore, .env.example
- **Create**: `.gitignore`, `pyproject.toml` (all deps + dev deps + pytest/ruff config), `.env.example`
- **Deps**: fastapi, uvicorn, sqlalchemy[asyncio], alembic, asyncpg, psycopg[binary], redis[hiredis], httpx, pydantic, pydantic-settings, python-slugify, rapidfuzz, structlog, tenacity, python-dateutil, celery[redis], PyJWT[crypto], Pillow
- **Dev deps**: pytest, pytest-asyncio, pytest-cov, httpx, factory-boy, respx, fakeredis[lua], aiosqlite, ruff
- **Verify**: `git init && pip install -e ".[dev]"`

### 0.2 — Configuration (pydantic-settings)
- **Create**: `app/__init__.py`, `app/config.py` — `Settings` class with all env vars, `get_settings()` with `@lru_cache`
- **Tests**: `tests/unit/test_config.py` — default values, env override, singleton
- **Verify**: `pytest tests/unit/test_config.py -v`

### 0.3 — Structured logging
- **Create**: `app/middleware/__init__.py`, `app/middleware/logging.py` — `setup_logging()`, `RequestLoggingMiddleware` (request_id, X-Request-ID header, duration_ms)
- **Tests**: `tests/unit/test_logging.py` — renderer selection

### 0.4 — Database connection (async SQLAlchemy)
- **Create**: `app/database.py` — async engine, `async_session_factory`, `get_db()` dependency, `init_db()`
- **Tests**: `tests/conftest.py` — SQLite test engine, `create_tables` fixture, `db_session` fixture with rollback

### 0.5 — Redis connection + CacheService
- **Create**: `app/redis.py` — `get_redis()`, `CacheService` with `get_cached()`, `set_cached()`, `invalidate()`
- **Tests**: `tests/unit/test_cache.py` — using `fakeredis` — set/get, expiry, invalidate pattern

### 0.6 — FastAPI app, exceptions, error handler, health endpoint
- **Create**: `app/main.py`, `app/exceptions.py` (NotFoundError, ConflictError, ForbiddenError, UnauthorizedError, BadRequestError, ExternalServiceError, RateLimitError), `app/middleware/error_handler.py`, `app/dependencies.py`, `app/routers/health.py`, `app/schemas/common.py` (HealthResponse, ErrorResponse, PaginatedResponse)
- **Tests**: `tests/integration/test_health.py` — 200, schema, version field; conftest adds `async_client` fixture
- **Verify**: `pytest tests/ -v` + `uvicorn app.main:app --reload` + `curl /health`

### 0.7 — Alembic initialization
- **Create**: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`
- **Verify**: `alembic check`

---

## Phase 1: Core Models + Migrations + Schemas + Base CRUD (8 sub-steps)

### 1.1 — Base model mixin + enums
- **Create**: `app/models/__init__.py`, `app/models/base.py` (Base, TimestampMixin, UUIDPrimaryKeyMixin), `app/models/enums.py` (EventStatus, MatchStatus, UserRole, OrderStatus, PaymentTransactionType/Status, PhotographerStatus, PhotoStatus, PhotoVisibility, PhotoTagType)
- **Tests**: `tests/unit/test_models.py` — enum values, UUID generation, timestamp columns

### 1.2 — Event + EventResult models
- **Create**: `app/models/event.py` — all columns per spec, relationship, indexes on tdb_id/equipe_id/slug
- **Tests**: extend `test_models.py` — table name, columns, FK, default match_status

### 1.3 — User + Order + PaymentTransaction models
- **Create**: `app/models/user.py`, `app/models/order.py` — including idempotency_key on Order
- **Tests**: extend `test_models.py`

### 1.4 — Photographer + Photo + PhotoTag + PhotoOrder models
- **Create**: `app/models/photographer.py` — PhotoTag has composite PK
- **Tests**: extend `test_models.py`

### 1.5 — Import all models, generate initial Alembic migration
- **Modify**: `app/models/__init__.py` — import all models
- **Run**: `alembic revision --autogenerate -m "initial_schema"` + `alembic upgrade head`
- **Tests**: `test_all_tables_created`

### 1.6 — Pydantic schemas
- **Create**: `app/schemas/event.py` (EventResponse, EventFilters, EventResultResponse), `app/schemas/user.py`, `app/schemas/order.py`, `app/schemas/photographer.py` (PhotoResponse, UploadSessionResponse, UpdatePhotoRequest, etc.)
- **Tests**: `tests/unit/test_schemas.py` — from_orm conversion, defaults, validation

### 1.7 — EventService CRUD + factories
- **Create**: `app/services/__init__.py`, `app/services/event_service.py` (list, get, get_by_slug, create, update, upsert_by_tdb_id, get_results, upsert_results), `tests/factories.py`
- **Tests**: `tests/unit/test_event_service.py` — 15 tests covering CRUD, filtering, pagination, upsert

### 1.8 — UserService + OrderService base CRUD
- **Create**: `app/services/user_service.py` (get_or_create_by_clerk_id, get_user), `app/services/order_service.py` (create_order with idempotency, get, list, update_status, record_transaction)
- **Tests**: `tests/unit/test_user_service.py` (3 tests), `tests/unit/test_order_service.py` (7 tests)

---

## Phase 2: TDB Event Ingestion + Caching (6 sub-steps)

### 2.1 — TDB HTTP client
- **Create**: `app/integrations/tdb/client.py` (httpx + tenacity retries), `app/integrations/tdb/schemas.py`
- **Tests**: `tests/unit/test_tdb_client.py` — success, retry, timeout, params (respx mocks)

### 2.2 — TDB normalizer
- **Create**: `app/integrations/tdb/normalizer.py` — field mapping, date parsing, slug generation, raw payload preservation
- **Tests**: `tests/unit/test_tdb_normalizer.py` — 8 tests: full/minimal events, slug, dates, status mapping

### 2.3 — TDB sync orchestration
- **Modify**: `app/services/event_service.py` — add `sync_from_tdb()` method
- **Tests**: extend `test_event_service.py` — creates events, updates existing, handles errors, returns counts

### 2.4 — Redis caching for event listings
- Cache key: `events:list:{hash}` with 5-min TTL; sync invalidates cache
- **Tests**: extend `test_cache.py` — cache hit, cache miss populates, sync invalidates

### 2.5 — Events API endpoints
- **Create**: `app/routers/events.py` — GET /api/v1/events (with filters+pagination), GET /events/{id}, GET /events/{id}/results
- **Tests**: `tests/integration/test_events_api.py` — 10 tests: empty, data, pagination, filters, not found

### 2.6 — TDB sync trigger endpoint
- **Create**: `app/routers/integrations.py` — POST /api/v1/integrations/tdb/sync (synchronous for now)
- **Tests**: `tests/integration/test_integrations_api.py` — returns counts

---

## Phase 3: Equipe Integration + Matching Engine (5 sub-steps)

### 3.1 — Equipe HTTP client
- **Create**: `app/integrations/equipe/client.py`, schemas — `get_meetings()`, `get_meeting_results()`
- **Tests**: `tests/unit/test_equipe_client.py` — 3 tests with respx

### 3.2 — Equipe normalizer
- **Create**: `app/integrations/equipe/normalizer.py` — meeting + results normalization
- **Tests**: `tests/unit/test_equipe_normalizer.py` — 4 tests

### 3.3 — Matching service (core scoring algorithm)
- **Create**: `app/services/matching_service.py` — `MatchingService` with `find_match()`, `apply_match()`, `run_matching_batch()`, `manual_match()`, `unmatch()`, `get_unmatched_events()`
- Priority chain: tdb_id (1.00) → date+strong name (0.85) → date+partial (0.75) → reject (<0.70)
- Uses `rapidfuzz.fuzz.token_sort_ratio` for name, `fuzz.ratio` for organizer/venue
- **Tests**: `tests/unit/test_matching_service.py` — **22 tests**: normalization, similarity scoring, priority chain, threshold rejection, best-match selection, organizer boost, apply/unmatch/manual/batch

### 3.4 — Equipe sync orchestration
- **Modify**: `event_service.py` — add `sync_from_equipe()` (fetch meetings, run matching, import results for matched)
- **Tests**: extend `test_event_service.py` — 3 tests

### 3.5 — Integration endpoints (Equipe sync, rematch, unmatched)
- **Modify**: `app/routers/integrations.py` — POST /equipe/sync, POST /events/rematch, GET /events/unmatched
- **Tests**: extend `test_integrations_api.py` — 4 tests

---

## Phase 4: Authentication — Clerk JWT (3 sub-steps)

### 4.1 — Clerk JWT validation + role-based access
- **Create**: `app/integrations/clerk/auth.py` — `ClerkAuth.validate_token()`, `get_current_user()` dependency, `require_role()` factory
- **Conftest**: RSA keypair fixtures, `make_jwt()`, `auth_headers`, `admin_auth_headers`, `photographer_auth_headers`
- **Tests**: `tests/unit/test_clerk_auth.py` — 9 tests: valid/expired/invalid tokens, create/return user, missing header, role allow/deny

### 4.2 — User endpoints
- **Create**: `app/routers/users.py` — GET /api/v1/me, GET /api/v1/me/orders
- **Tests**: `tests/integration/test_users_api.py` — 4 tests: unauth, auth, orders empty/with data

### 4.3 — Protect integration endpoints
- **Modify**: `app/routers/integrations.py` — add admin auth to all sync/rematch endpoints
- **Tests**: extend `test_integrations_api.py` — 3 tests: 401, 403 for non-admin

---

## Phase 5: Payments — Klarna (4 sub-steps)

### 5.1 — Klarna HTTP client
- **Create**: `app/integrations/klarna/client.py` (create_session, create_order, capture, refund, cancel), schemas
- **Tests**: `tests/unit/test_klarna_client.py` — 8 tests with respx

### 5.2 — Order service with Klarna + idempotency
- **Modify**: `app/services/order_service.py` — `create_checkout_session()`, `authorize_payment()`, `capture_payment()`, `refund_payment()`, `cancel_payment()`
- State machine: PENDING → AUTHORIZED → CAPTURED → REFUNDED; AUTHORIZED → CANCELLED
- **Tests**: extend `test_order_service.py` — 12 tests: full lifecycle, idempotency, invalid transitions (ConflictError), transaction recording

### 5.3 — Checkout endpoints
- **Create**: `app/routers/checkout.py`, `app/schemas/checkout.py` — POST /checkout/sessions, POST /checkout/authorize, POST /checkout/callback/klarna
- **Tests**: `tests/integration/test_checkout_api.py` — 6 tests

### 5.4 — Order management endpoints
- **Create**: `app/routers/orders.py` — GET /orders/{id}, POST capture/refund/cancel (admin only)
- **Tests**: `tests/integration/test_orders_api.py` — 10 tests: ownership, admin access, state transitions, full lifecycle

---

## Phase 6: Photographer Module (6 sub-steps)

### 6.1 — Abstract storage backend
- **Create**: `app/storage/base.py` (ABC: presigned upload/download URLs, download/upload, delete, exists), `app/storage/local.py`, `app/storage/s3.py` (stubbed), factory `get_storage_backend()`
- **Tests**: `tests/unit/test_storage.py` — 7 tests with local backend

### 6.2 — Photographer service
- **Create**: `app/services/photographer_service.py` — get_photographer, create_upload_session, complete_upload, list_photos, update_photo, delete_photo
- **Tests**: `tests/unit/test_photographer_service.py` — 13 tests: upload sessions, complete, list/filter, update, delete, ownership checks

### 6.3 — Photographer API endpoints
- **Create**: `app/routers/photographer.py` — all require PHOTOGRAPHER role
- POST /uploads/sessions, POST /uploads/complete, GET/PATCH/DELETE /photos
- **Tests**: `tests/integration/test_photographer_api.py` — 11 tests

### 6.4 — Public gallery service + endpoints
- **Create**: `app/services/gallery_service.py`, `app/routers/gallery.py` — public, no auth
- GET /events/{id}/gallery, GET /events/{id}/gallery/search, GET /photos/{id}
- Only PUBLISHED + READY photos shown; thumbnails in listings, watermarked preview in detail
- **Tests**: `tests/integration/test_gallery_api.py` — 13 tests: visibility filtering, search by tag, pagination

### 6.5 — Photo purchase flow
- **Create**: `app/services/photo_purchase_service.py`, `app/routers/photo_purchase.py`
- POST /photo-checkout/sessions, GET /me/purchases/photos, POST /photos/{id}/download
- Download returns presigned URL for original (unwatermarked) after purchase verification
- **Tests**: `tests/integration/test_photo_purchase_api.py` — 8 tests

### 6.6 — Image processing utilities
- **Create**: `app/services/image_processing.py` — `generate_thumbnail()`, `generate_preview()`, `apply_watermark()`, `process_photo()` pipeline
- Uses Pillow; test with programmatic `Image.new("RGB", (2000,1500))`
- **Tests**: `tests/unit/test_image_processing.py` — 6 tests: size, aspect ratio, watermark, full pipeline

---

## Phase 7: Admin Endpoints (1 sub-step)

### 7.1 — Admin router
- **Create**: `app/routers/admin.py`, `app/schemas/admin.py`
- GET /admin/orders (paginated, filterable), POST /admin/events/{id}/match, POST /admin/events/{id}/unmatch
- Router-level `require_role(ADMIN)` dependency
- **Tests**: `tests/integration/test_admin_api.py` — 9 tests: auth, role, orders, match/unmatch

---

## Phase 8: Background Jobs — Celery (5 sub-steps)

### 8.1 — Celery app config
- **Create**: `app/tasks/celery_app.py` — broker/backend from settings, JSON serializer, UTC

### 8.2 — TDB sync task
- **Create**: `app/tasks/tdb_sync.py` — wraps async sync in `asyncio.run()`
- **Modify**: POST /tdb/sync dispatches task, returns `{"task_id", "status": "queued"}`
- **Tests**: `tests/tasks/test_tdb_sync.py` — eager mode, 3 tests

### 8.3 — Equipe sync + matching tasks
- **Create**: `app/tasks/equipe_sync.py`, `app/tasks/matching.py`
- **Tests**: `tests/tasks/test_equipe_sync.py`, `test_matching_task.py`

### 8.4 — Image processing task
- **Create**: `app/tasks/image_processing.py` — dispatched from `complete_upload()`
- **Tests**: `tests/tasks/test_image_processing.py` — 3 tests

### 8.5 — Celery Beat schedule
- TDB sync hourly, Equipe sync every 30 min
- **Tests**: verify schedule config exists

---

## Phase 9: Non-Functional Hardening (5 sub-steps)

### 9.1 — Rate limiting middleware
- **Create**: `app/middleware/rate_limit.py` — Redis sliding window, per-IP (60/min public, 120/min authed, 5/min sync)
- **Tests**: `tests/unit/test_rate_limit.py` — 4 tests

### 9.2 — Enhanced request logging
- Add user_id, body sizes, client_ip to structured log entries

### 9.3 — Audit logging
- **Create**: `app/services/audit_service.py` — structlog-based audit events for orders, uploads, matches, syncs

### 9.4 — Coverage review
- `pytest tests/ -v --cov=app --cov-report=term-missing` — target 80%+

### 9.5 — API documentation review
- Verify OpenAPI docs at /docs, add response schemas for error codes

---

## Dependency Graph

```
Phase 0 → Phase 1 → Phase 2 → Phase 3
                  ↘ Phase 4 → Phase 5
                             → Phase 6 (6.5 needs Phase 5)
                             → Phase 7
                  ↘ Phase 8 (needs 2, 3, 6)
                             → Phase 9
```

## Verification Commands

```bash
pytest tests/ -v                                          # all tests
pytest tests/ -v --cov=app --cov-report=term-missing      # with coverage
pytest tests/unit/ -v                                      # unit only
pytest tests/integration/ -v                               # integration only
alembic upgrade head                                       # apply migrations
uvicorn app.main:app --reload                              # dev server
celery -A app.tasks.celery_app worker --loglevel=info      # worker (Phase 8+)
celery -A app.tasks.celery_app beat --loglevel=info        # scheduler (Phase 8.5+)
```

## Critical Implementation Files

- `app/config.py` — central config, every module depends on it
- `app/services/matching_service.py` — core domain logic with fuzzy scoring
- `app/services/order_service.py` — payment state machine with idempotency
- `app/integrations/clerk/auth.py` — auth dependency used by all protected routes
- `tests/conftest.py` — shared test infrastructure (DB, auth, fixtures)
