# Proposal: Migrate backend to PostgreSQL + SQLAlchemy

## Why

The current backend serves all data from an in-memory generator (`backend/app/data.py`), so every container restart regenerates state and nothing a technician submits is ever stored. PostgreSQL with a proper persistence layer is required before the AWS deployment milestone (M3) so that data survives restarts and the architecture matches production standards.

## What Changes

- Replace the in-memory data layer with PostgreSQL 16 accessed through SQLAlchemy 2.x (async), restructuring the backend into the standard three-layer architecture (routers → services → repositories) with split ORM models (`app/models/`) and Pydantic schemas (`app/schemas/`).
- Introduce Alembic migrations as the only mechanism for schema changes; the initial migration creates the `elevators`, `elevator_features`, `elevator_trend_points`, and `visit_reports` tables.
- Seed the database idempotently on first run with the existing deterministic 100-elevator dataset (seed 42).
- Persist post-visit reports in the new `visit_reports` table — previously validated and discarded.
- **BREAKING** `POST /api/elevators/{id}/report` returns `201 Created` instead of `200 OK`, aligning with the API standards for resource-creating POSTs. The current frontend does not inspect the status code, so no frontend code change is expected.
- Update `docker-compose.yml` with a `db` service (postgres:16-alpine, healthcheck, named volume) and a `migrate` service that applies Alembic migrations before the backend starts.
- Rebuild the backend test suite against a dedicated test database (unit tests with mocked repositories, integration tests with httpx).

All other API behaviour (URLs, methods, request/response shapes, sort order) is preserved exactly.

## Capabilities

### New Capabilities

- `elevator-persistence` — elevator fleet data (including features and risk trend) stored in and served from PostgreSQL with the existing read API contract preserved.
- `visit-report-persistence` — post-visit reports persisted to the database and acknowledged with `201 Created`.
- `database-infrastructure` — PostgreSQL service, Alembic migration pipeline, idempotent seeding, and environment-based configuration in Docker Compose.

### Modified Capabilities

None — no existing specs in `openspec/specs/`.

## Impact

- **Backend**: `app/data.py` and the monolithic `app/models.py` are removed; new `database.py`, `core/`, `models/`, `schemas/`, `repositories/`, `services/`, `seed.py`; `routers/elevators.py` rewritten to async handlers delegating to a service; `requirements.txt` gains `sqlalchemy[asyncio]`, `asyncpg`, `alembic`; new `requirements-dev.txt`.
- **API**: contract unchanged except the report endpoint status code (`200` → `201`); `docs/api-spec.yml` must be updated.
- **Frontend**: no code changes expected (`PostVisitReport.tsx` ignores the response status); in scope only if required to keep standards.
- **Infrastructure**: `docker-compose.yml` gains `db` and `migrate` services; backend requires `DATABASE_URL`; data persisted in a named volume.
- **Docs**: `docs/data-model.md` storage section and `docs/api-spec.yml` updated on completion.
