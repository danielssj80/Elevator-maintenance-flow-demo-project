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

## Security Basics

- Never log passwords, tokens, or PII.
- Validate all input at the router layer via Pydantic (FastAPI enforces this).
- Use `HTTPException` with generic messages for auth failures — never reveal internal details.
- Database credentials only via environment variables.
- CORS: restrict `allow_origins` to known frontend origins (no `*` in production).
