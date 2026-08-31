---
description: Backend development standards for the Elevator Maintenance FastAPI/Python application — architecture, patterns, testing, and best practices.
globs: ["backend/**/*.py", "backend/alembic/**/*", "backend/requirements*.txt", "backend/Dockerfile"]
alwaysApply: true
---

# Backend Standards and Best Practices

## Technology Stack

| Component | Choice | Version |
|---|---|---|
| Language | Python | 3.12 |
| Framework | FastAPI | 0.115+ |
| Validation | Pydantic | v2 |
| ORM | SQLAlchemy | 2.x (async) |
| Database | PostgreSQL | 16+ |
| Migrations | Alembic | latest |
| Server | Uvicorn | latest |
| Testing | pytest + httpx | latest |
| Linting | Ruff | latest |

## Architecture Overview

The backend follows a three-layer architecture. Each layer has a single responsibility and dependencies only flow downward.

```
HTTP Request
    ↓
routers/        — HTTP boundary: parse request, call service, return response
    ↓
services/       — Business logic: rules, orchestration, domain decisions
    ↓
repositories/   — Data access: SQLAlchemy queries, no business logic
    ↓
PostgreSQL (via SQLAlchemy)
```

Models are split into two distinct types:

- `app/models/` — SQLAlchemy ORM classes (map to DB tables)
- `app/schemas/` — Pydantic models (validate API input/output)

## Project Structure

```
backend/
├── app/
│   ├── main.py                  # App factory, middleware, router registration
│   ├── database.py              # SQLAlchemy engine, session, Base
│   ├── models/                  # ORM models (one file per domain entity)
│   │   └── elevator.py
│   ├── schemas/                 # Pydantic schemas (one file per domain entity)
│   │   └── elevator.py
│   ├── repositories/            # Data access (one file per aggregate root)
│   │   └── elevator_repository.py
│   ├── services/                # Business logic (one file per domain area)
│   │   └── elevator_service.py
│   ├── routers/                 # HTTP endpoints (one file per resource)
│   │   └── elevators.py
│   └── core/
│       ├── config.py            # App settings loaded from environment
│       └── exceptions.py        # Custom exception classes
├── alembic/                     # Migration scripts
│   ├── versions/
│   └── env.py
├── tests/
│   ├── conftest.py              # Shared fixtures (test DB, client)
│   ├── unit/                    # Test services in isolation (mock repositories)
│   └── integration/             # Test endpoints with TestClient + real test DB
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt         # pytest, ruff, httpx, etc.
└── Dockerfile
```

## Layer Responsibilities

### Routers (`app/routers/`)

- Handle HTTP concerns only: path params, query params, request body, response status codes.
- Validate input via Pydantic schemas (FastAPI does this automatically).
- Call one service method per endpoint — no business logic here.
- Use `Annotated` + `Depends` for dependency injection (DB session, services).

```python
# Good
@router.get("/{elevator_id}", response_model=ElevatorDetailSchema)
async def get_elevator(
    elevator_id: str,
    service: Annotated[ElevatorService, Depends(get_elevator_service)],
) -> ElevatorDetailSchema:
    return await service.get_by_id(elevator_id)

# Bad — business logic in router
@router.get("/{elevator_id}")
async def get_elevator(elevator_id: str, db: Session = Depends(get_db)):
    elevator = db.query(Elevator).filter(Elevator.id == elevator_id).first()
    if not elevator:
        raise HTTPException(status_code=404, detail="Not found")
    elevator.risk_level = "high" if elevator.risk_score > 0.7 else "low"
    return elevator
```

### Services (`app/services/`)

- Contain all business logic and domain rules.
- Orchestrate calls to one or more repositories.
- Raise `HTTPException` or custom domain exceptions — never return raw DB objects.
- Must not import SQLAlchemy directly; receive repositories via constructor injection.

```python
class ElevatorService:
    def __init__(self, repository: ElevatorRepository) -> None:
        self._repo = repository

    async def get_by_id(self, elevator_id: str) -> ElevatorDetailSchema:
        elevator = await self._repo.get_by_id(elevator_id)
        if elevator is None:
            raise HTTPException(status_code=404, detail="Elevator not found")
        return ElevatorDetailSchema.model_validate(elevator)
```

### Repositories (`app/repositories/`)

- Contain only SQLAlchemy queries — no business rules, no HTTP exceptions.
- Return ORM model instances or `None` — never raise `HTTPException`.
- Accept a `Session` (or `AsyncSession`) via constructor.
- Name methods clearly: `get_by_id`, `list_all`, `create`, `update`, `delete`.
- **A repeatable write uses `ON CONFLICT DO NOTHING`, never read-then-insert.**
  `TelemetryRepository.create_many` inserts with
  `pg_insert(Model).values([...]).on_conflict_do_nothing(index_elements=[...]).returning(Model.id)`
  and returns the number of rows it actually wrote, which is what the service
  reports to the caller. Read-then-insert loses the race two concurrent retries
  produce: both read "absent", both insert. A single multi-row `VALUES` clause
  also covers repeats *within* one payload, because PostgreSQL skips a row
  conflicting with one inserted earlier in the same statement — so do not add a
  Python pre-deduplication pass on top. One was written here and deleted when
  removing it left every test green.

```python
class ElevatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, elevator_id: str) -> Elevator | None:
        result = await self._session.execute(
            select(Elevator).where(Elevator.id == elevator_id)
        )
        return result.scalar_one_or_none()
```

### ORM Models (`app/models/`)

- Define database tables using SQLAlchemy declarative syntax.
- Use `mapped_column` and `Mapped` (SQLAlchemy 2.x style) for full type safety.
- Never add business logic or validation here.

```python
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Elevator(Base):
    __tablename__ = "elevators"

    id: Mapped[str] = mapped_column(primary_key=True)
    building_name: Mapped[str]
    risk_score: Mapped[float]
    risk_level: Mapped[str]
    in_model_scope: Mapped[bool] = mapped_column(default=True)
```

### Pydantic Schemas (`app/schemas/`)

- Define request/response shapes — completely independent of SQLAlchemy.
- Use `model_config = ConfigDict(from_attributes=True)` to allow `.model_validate(orm_obj)`.
- Separate `Create`, `Update`, and `Read` schemas when input and output differ.

```python
from pydantic import BaseModel, ConfigDict

class ElevatorSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    building_name: str
    risk_score: float
    risk_level: str
```

## Coding Standards

### Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Files/modules | `snake_case` | `elevator_repository.py` |
| Classes | `PascalCase` | `ElevatorService` |
| Functions/methods | `snake_case` | `get_by_id` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RISK_SCORE` |
| Pydantic schemas | `PascalCase` + `Schema` suffix | `ElevatorDetailSchema` |
| ORM models | `PascalCase` (no suffix) | `Elevator` |
| Repositories | `PascalCase` + `Repository` suffix | `ElevatorRepository` |
| Services | `PascalCase` + `Service` suffix | `ElevatorService` |

### Type Annotations

All functions must be fully typed. No `Any` unless explicitly justified with a comment.

```python
# Good
async def calculate_risk(score: float, age_years: int) -> str:
    ...

# Bad
def calculate_risk(score, age_years):
    ...
```

Use `X | None` instead of `Optional[X]` (Python 3.10+ syntax).

### Error Handling

- Raise `HTTPException` from services, not from repositories.
- Define custom exception classes in `app/core/exceptions.py` for domain errors.
- Use FastAPI exception handlers in `main.py` for cross-cutting error formatting.

```python
# app/core/exceptions.py
class ElevatorNotFoundError(Exception):
    def __init__(self, elevator_id: str) -> None:
        self.elevator_id = elevator_id
        super().__init__(f"Elevator {elevator_id} not found")
```

### Async

All route handlers and service/repository methods must be `async`. Use `AsyncSession` from SQLAlchemy.

```python
# Good
async def list_elevators() -> list[ElevatorSummarySchema]:
    ...

# Bad
def list_elevators() -> list[ElevatorSummarySchema]:
    ...
```

## Database and Migrations

### SQLAlchemy Setup (`app/database.py`)

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db/elevator_db")

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
        await session.commit()  # commit on success; session.__aexit__ rolls back on exception
```

### Alembic Migrations

Every schema change (new table, new column, renamed column, added index) requires an Alembic migration. Never alter DB schema manually or with `Base.metadata.create_all()` in production.

**Workflow:**

```bash
# After changing an ORM model, generate a migration
alembic revision --autogenerate -m "add zone column to elevators"

# Review the generated file in alembic/versions/ before applying
# Then apply
alembic upgrade head
```

**Rules:**
- Always review autogenerated migrations before committing — Alembic misses some changes (e.g., column renames).
- Migration files are checked into git.
- Never delete or modify a migration that has been applied to any environment.
- `alembic downgrade` is available but requires explicit user decision.

### Environment Variables

Database connection and secrets must come from environment variables, never be hardcoded.

Required variables (defined in `docker-compose.yml` and `.env`):

```
DATABASE_URL=postgresql+asyncpg://user:password@db:5432/elevator_db
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=elevator_db
```


`Settings` evaluates `os.getenv` in class-level attributes at import time, and `settings` is a module singleton. Consequently `monkeypatch.setenv` followed by a re-import does **not** change these values in tests. Either patch the singleton directly with `monkeypatch.setattr(settings, "flag", True)`, or give the function an explicit override argument — the approach `configure_telemetry(app, enabled=True)` takes, which leaves the singleton untouched so assertions about defaults stay meaningful.

## Testing Standards

### Tools

- **pytest** — test runner
- **pytest-asyncio** — async test support
- **httpx** / **FastAPI TestClient** — API integration tests
- **pytest-cov** — coverage reports
- **ruff** — linting (run before tests in CI)

### Test Structure

```
tests/
├── conftest.py          # DB fixtures, TestClient, shared setup
├── unit/
│   ├── test_elevator_service.py    # Service logic with mocked repositories
│   └── test_risk_calculator.py    # Pure domain logic
└── integration/
    ├── test_elevators_router.py    # Full endpoint tests with test DB
    └── test_elevator_repository.py # Repository tests against test DB
```

### Unit Tests (Services)

Mock the repository layer to test business logic in isolation.

```python
# tests/unit/test_elevator_service.py
from unittest.mock import AsyncMock
import pytest
from app.services.elevator_service import ElevatorService

@pytest.mark.asyncio
async def test_get_by_id_raises_404_when_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    service = ElevatorService(repository=mock_repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_by_id("nonexistent")

    assert exc_info.value.status_code == 404
```

### Integration Tests (Routers)

Use `TestClient` with a dedicated test database. Never use the production/development DB for tests.

```python
# tests/conftest.py
@pytest.fixture
async def client(test_db_session):
    app.dependency_overrides[get_db] = lambda: test_db_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

# tests/integration/test_elevators_router.py
@pytest.mark.asyncio
async def test_get_elevator_returns_404_for_unknown_id(client):
    response = await client.get("/api/elevators/unknown-id")
    assert response.status_code == 404
```

### Coverage Requirements

- Minimum **80% coverage** for services and repositories.
- Routers are covered by integration tests.
- Pure utility/domain logic: aim for **100%**.

## API Design

### URL Conventions

- Use plural nouns: `/api/elevators`, not `/api/elevator`
- Resource hierarchy: `/api/elevators/{id}/reports`
- Use kebab-case for multi-word segments: `/maintenance-zones`
- Version prefix is `/api/` (no versioning for now; add `/api/v2/` when breaking changes occur)

### Response Conventions

- `200 OK` — successful GET, PUT/PATCH
- `201 Created` — successful POST that creates a resource
- `204 No Content` — successful DELETE
- `404 Not Found` — resource does not exist
- `422 Unprocessable Entity` — FastAPI's default for validation errors (do not override)

### Error Response Shape

All error responses follow this format (FastAPI default for HTTP exceptions):

```json
{
  "detail": "Elevator not found"
}
```

For validation errors FastAPI returns `422` with a structured `detail` array — do not override this behavior.

## Docker

The backend runs in Docker for all environments (dev, staging, production).

### Dockerfile Requirements

- Use a multi-stage build: `builder` stage installs deps, `runtime` stage copies only what's needed.
- Base image: `python:3.12-slim`
- Run as non-root user.
- `CMD` must use `uvicorn` with `--host 0.0.0.0`.

### docker-compose (development)

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:password@db:5432/elevator_db
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./backend:/app   # hot-reload in dev

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: elevator_db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 5s
      timeout: 5s
      retries: 5
```

Alembic migrations run as a separate step before the app starts:

```yaml
  migrate:
    build: ./backend
    command: alembic upgrade head
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:password@db:5432/elevator_db
    depends_on:
      db:
        condition: service_healthy
```

## Observability

OpenTelemetry is configured programmatically in `app/core/telemetry.py`, called from `main.py` before middleware and routers. The `opentelemetry-instrument` CLI wrapper is deliberately not used: it offers no hook to register observable-gauge callbacks, cannot express the SQLAlchemy engine binding below, and would also instrument the one-shot `migrate` container, which reuses the same image.

`OTEL_ENABLED` defaults to `false`. CI and the test suite must never require a Collector.

**Bind SQLAlchemy to the existing engine.**

```python
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
```

The unbound call also patches `Engine.connect` class-wide, so an engine built at import time — as ours is — still emits `connect` spans. What it loses is **per-statement** spans: those come from event listeners the `engine=` argument registers on that specific engine. Measured on 0.65b0, one query yields `['connect', 'SELECT']` bound versus `['connect']` unbound.

The failure is therefore not "no database spans" but "no idea which query ran or how long it took", while connection spans keep arriving and everything looks instrumented. A guarding test must assert on a span carrying **`db.statement`** — asserting on `db.system` passes on the `connect` span alone and catches nothing.

**OTLP endpoints are base URLs.** `settings.otel_exporter_otlp_endpoint` holds a base; the signal path is appended explicitly. Passing a base URL as an exporter's `endpoint=` makes the SDK treat it as the full URL, and the resulting 404 is only logged at DEBUG. The same ambiguity appears in the Collector config and in n8n's OTel variables.

**Instrument the service layer, not repositories or routers.** Domain spans belong where the business meaning is: `BriefingService` owns `briefing.generate` because only it knows whether a result came from Bedrock or the fallback. Repository and router spans come free from instrumentation.

**Never record prompt or completion content.** `gen_ai.input.messages` and `gen_ai.output.messages` are not set. Briefing prompts embed fleet risk data, technician names and free-text visit notes. This is a decision, not an omission to be "completed" later.

**Metric attributes must be bounded.** `elevator.id` is never a metric attribute: 100 elevators across 4 risk levels is 400 series against a 10,000-series budget. HTTP metrics are labelled by route template, not raw path.

## Machine Learning at Runtime

**The model lives in its own service.** `backend/inference/` is a stateless
FastAPI app with no database session and no `DATABASE_URL`; it takes a matrix
and returns scores and contributions. It is the only image carrying
`model.joblib`. Keeping xgboost out of the runtime image saves ~300 MB on an
image deployed to a ~916 MB-RAM instance and ~40 s of install on every CI run,
for a capability production never invokes. It also earns a genuine multi-service
trace, which is why the observability work has something to show.

**Read column order from the model, never from a literal.** Build the feature
matrix in the order the booster reports in `feature_names`, and reject a
mismatch. A transposed or reordered matrix scores without error and returns
entirely plausible numbers derived from the wrong features.

**Convert units at exactly one boundary, and guard the input.** The booster was
trained on absolute temperatures in Kelvin; readings are stored in Celsius.
`K = C + 273.15` is applied while building the matrix and nowhere else, and the
resulting columns are range-checked before anything is scored.

The instinctive guard — assert the scored fleet has non-zero variance — was
measured against this model and **does not work**. Celsius input does not
collapse the fleet: the remaining five features still discriminate, so 51 of 70
scores stay distinct and the standard deviation lands within 0.002 of correct,
while 10 of 70 elevators quietly move into the wrong risk band. Output that is
wrong but survives every distributional check is the reason the guard belongs on
the input. Generalise the rule: **when a corruption leaves the output
well-formed, validate the input, not the output.**

**Contributions come from the booster, not from `shap`.**
`Booster.predict(dmatrix, pred_contribs=True)` returns exact TreeSHAP — verified
identical to `shap.TreeExplainer` on the committed predictions, max delta 0.0 —
so the `shap → numba → llvmlite` chain (~250 MB) is not a dependency of this
project. The trailing column of `pred_contribs` is the bias, not a feature, and
must be dropped.

**Anything shared between the offline script and the runtime lives in
`app/ml/`.** `app/ml/feature_mapping.py` holds the feature map, dataset means,
run parameters, value formatting, the risk-level thresholds and the explanation
template, imported by both `backend/ml/generate_predictions.py` and the online
service. Two copies would let the same reading render a different displayed
value online and offline, with the score agreeing and the text beside it not.
The module sits under `app/` because the Dockerfile already does
`COPY app/ ./app/`.

Consequently the offline script runs as a module, from `backend/`:

```bash
cd backend && python -m ml.generate_predictions

# Regenerate the golden fixture the online scorer is tested against:
cd backend && python -m ml.generate_predictions --dump-vectors
```

`python backend/ml/generate_predictions.py` from the repository root leaves
`backend/` off `sys.path` and the shared import raises `ImportError`.

**`predictions.json` is not byte-reproducible.** `_days_ago()` derives
`last_visit_date` from `date.today()`, so a regeneration on another day differs
in that field for every row and no seed can pin it. Verify a refactor field-wise
against `risk_score`, `risk_level`, `features`, `trend` and `nl_explanation`
instead.

## Rebuilding Compose Images

`docker compose build backend` is **not enough** before trusting the live stack.
Services that share a build context still get their own images: `migrate` builds
from `./backend` but produces `…-migrate`, so building only `backend` leaves it
running yesterday's `alembic/versions/`, and the stack fails to start with
`Can't locate revision identified by <rev>` even though the file is right there
in the source tree.

Rebuild every service whose image is affected:

```bash
docker compose build backend migrate inference
```

The general trap: the test suite mounts `backend/` as a volume and always sees
current code, while compose runs baked images. When the two disagree, the tests
are right and the stack is stale.

## Security Basics

- Never log passwords, tokens, or PII.
- Validate all input at the router layer via Pydantic (FastAPI enforces this).
- Use `HTTPException` with generic messages for auth failures — never reveal internal details.
- Database credentials only via environment variables.
- CORS: restrict `allow_origins` to known frontend origins (no `*` in production).
- **`DEPLOYMENT_ENVIRONMENT` is fail-closed and every non-production
  environment must declare itself.** It defaults to `production`, which gates
  the telemetry and inference routers off. `docker-compose.yml` sets `local`
  and `tests/conftest.py` sets `local`, but a bare
  `uvicorn app.main:app --reload` from `backend/` inherits the default and will
  return 404 on those endpoints with no explanation. Run it as:

  ```bash
  cd backend && DEPLOYMENT_ENVIRONMENT=local uvicorn app.main:app --reload
  ```

  The default is this way round because `docker-compose.prod.yml` sets the
  variable nowhere and loads an out-of-repo env file: with a default of `local`,
  *forgetting* it published two unauthenticated write endpoints. An unset
  variable has to be the safe answer.

- **Do not register unauthenticated write endpoints in production.** This API
  has no authentication anywhere, and `docker-compose.prod.yml` auto-deploys on
  merge to the default branch, so any write route reaching production is a
  public one. `build_app()` gates the telemetry and inference routers on
  `deployment_environment != "production"`. Gate at **registration**, not inside
  the handler: an unregistered route cannot be reached by a guard that was
  written wrong.

- **`X-Ingest-Token` guards the write endpoints outside production.**
  `app/core/ingest_auth.py` holds `require_ingest_token`, applied as a route
  dependency on `POST /api/telemetry/readings` and `POST /api/inference/run`.
  It compares with `secrets.compare_digest` and answers one 401 for both an
  absent and an incorrect token, so the endpoint cannot be used to discover
  whether a guard is configured.

  This one is **fail-open** — unset means open — which is the opposite of
  `DEPLOYMENT_ENVIRONMENT` above and deliberately so. It only ever runs on
  routers production does not register, and a fail-closed default would break
  `pytest` and a bare `uvicorn` run for anyone with no configuration. The safety
  comes from the other end: `docker-compose.yml` sets `TELEMETRY_INGEST_TOKEN`,
  `build_app()` logs a warning when it registers those routers without one, and
  `tests/unit/test_dev_compose.py` asserts both against the compose files.

- **Assert a guard against the configuration that runs it, not only against a
  fixture.** Round 3 of `telemetry-ingestion-inference` found the production
  gate open in the one environment it existed to protect, after three rounds of
  tests that all set the variable by hand. `tests/unit/test_dev_compose.py`
  parses `docker-compose.yml` and `docker-compose.prod.yml` and is the only
  place in the suite that would notice a guard correct in Python and absent from
  the deployment. Add to it whenever a new guard depends on an environment
  variable.
