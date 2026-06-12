# Tasks: Migrate backend to PostgreSQL + SQLAlchemy

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/migrate-backend-postgresql` from `main`
- [x] 0.2 Verify current branch with `git branch --show-current`

## 1. Backend Foundation

- [x] 1.1 Add `sqlalchemy[asyncio]`, `asyncpg`, `alembic` to `requirements.txt`; create `requirements-dev.txt` (pytest, pytest-asyncio, pytest-cov, httpx, ruff); install into `backend/venv`
- [x] 1.2 Create `app/core/config.py` — settings loaded from environment (`DATABASE_URL`)
- [x] 1.3 Create `app/core/exceptions.py` — `ElevatorNotFoundError`
- [x] 1.4 Create `app/database.py` — async engine, `AsyncSessionLocal`, `Base`, `get_db` dependency

## 2. ORM Models and Initial Alembic Migration

- [x] 2.1 Create `app/models/elevator.py` — `Elevator`, `ElevatorFeature`, `ElevatorTrendPoint` (SQLAlchemy 2.x `Mapped`/`mapped_column`, FKs with cascade delete, unique `(elevator_id, day_index)` on trend points)
- [x] 2.2 Create `app/models/visit_report.py` — `VisitReport` (JSONB for `components_replaced` and `parameters_corrected`, `created_at` server default)
- [x] 2.3 Initialise Alembic (`alembic init`), wire `env.py` to async engine and `Base.metadata`
- [x] 2.4 Generate initial migration: `alembic revision --autogenerate -m "create elevators, features, trend points, visit reports"`
- [x] 2.5 Review the generated migration by hand (constraints, server defaults, JSONB types)
- [x] 2.6 Start a local PostgreSQL and apply: `alembic upgrade head`; verify the four tables exist

## 3. Pydantic Schemas

- [x] 3.1 Create `app/schemas/elevator.py` — `FeatureSchema`, `ElevatorSummarySchema`, `ElevatorDetailSchema` with `from_attributes=True`, shapes identical to the current API responses
- [x] 3.2 Create `app/schemas/visit_report.py` — `PostVisitReportSchema` (request), `ReportResponseSchema`

## 4. Repositories (TDD)

- [x] 4.1 Create `tests/conftest.py` — test DB engine/session fixtures, transaction rollback per test, httpx client with `get_db` override
- [x] 4.2 Write failing integration tests for `ElevatorRepository` (`list_all` ordered by `risk_score` desc, `get_by_id` with features + trend eager-loaded, `get_by_id` returns `None` for unknown id)
- [x] 4.3 Implement `app/repositories/elevator_repository.py`; tests pass
- [x] 4.4 Write failing integration test for `VisitReportRepository.create`
- [x] 4.5 Implement `app/repositories/visit_report_repository.py`; test passes

## 5. Service Layer (TDD)

- [x] 5.1 Write failing unit tests for `ElevatorService` with mocked repositories: list mapping, detail mapping, `risk_level` derived from `risk_score` (all three bands, including divergent stored value), 404 on unknown id, report creation, 404 on report for unknown elevator
- [x] 5.2 Implement `app/services/elevator_service.py`; tests pass

## 6. Routers

- [x] 6.1 Rewrite `app/routers/elevators.py` — async handlers, `Annotated`/`Depends` injection, report endpoint declares `status_code=201`
- [x] 6.2 Write integration tests for the three endpoints asserting the exact JSON contract and status codes (`200`, `200`, `201`, `404`, `422`)
- [x] 6.3 Tests pass

## 7. Idempotent Seeder

- [x] 7.1 Write failing integration test: seeding an empty DB creates 100 elevators each with exactly 3 features and 6 trend points; running the seeder again changes no row counts
- [x] 7.2 Implement `app/seed.py` reusing the deterministic generator (seed 42); hook it into backend startup after a table-presence check; tests pass

## 8. Infrastructure and Cleanup

- [x] 8.1 Update `docker-compose.yml` — add `db` (postgres:16-alpine, `pg_isready` healthcheck, named volume) and `migrate` (`alembic upgrade head`) services; backend gets `DATABASE_URL` and `depends_on` db (healthy) + migrate (completed)
- [x] 8.2 Delete `app/data.py` and the old `app/models.py`; fix all imports; `grep` confirms no references remain
- [x] 8.3 `docker compose up` from a clean state works end to end (db → migrate → backend healthy and seeded)

## 9. Review and Update Existing Tests (MANDATORY)

- [x] 9.1 Review `e2e/` and any pre-existing tests for assumptions invalidated by this change (e.g. report status code)
- [x] 9.2 Update any invalidated tests

## 10. Unit Tests and DB State Verification (MANDATORY)

- [x] 10.1 Capture pre-test DB baseline (row counts for the four tables)
- [x] 10.2 Run targeted unit tests for changed modules
- [x] 10.3 Run full suite with coverage: `backend/venv/bin/python -m pytest tests/ -v --cov=app --cov-report=term-missing` (≥80% on services/repositories)
- [x] 10.4 Verify post-test DB state matches baseline
- [x] 10.5 Create report `reports/YYYY-MM-DD-step-10-unit-tests.md`
- [x] 10.6 Mark complete only after report exists and tests pass

## 11. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [x] 11.1 Ensure stack is running (`docker compose up -d`)
- [x] 11.2 `GET /api/elevators` → 200, 100 items, sorted by `risk_score` desc
- [x] 11.3 `GET /api/elevators/ELV-001` → 200, 3 features, 6-element trend
- [x] 11.4 `GET /api/elevators/UNKNOWN` → 404
- [x] 11.5 `POST /api/elevators/ELV-001/report` (valid body) → 201; verify row in `visit_reports`; then delete the row to restore DB state
- [x] 11.6 `POST /api/elevators/UNKNOWN/report` → 404; `POST` with missing field → 422; verify nothing persisted
- [x] 11.7 Restart the stack; verify data persisted and no duplicate seeding
- [x] 11.8 Create report `reports/YYYY-MM-DD-step-11-endpoint-testing.md`

## 12. E2E Testing with Playwright MCP (MANDATORY — AGENT MUST EXECUTE)

- [x] 12.1 Ensure frontend and backend are running
- [x] 12.2 Navigate the dashboard; verify the fleet list renders from PostgreSQL data
- [x] 12.3 Open an elevator detail; verify trend sparkline and features render
- [x] 12.4 Submit a post-visit report through the form; verify the success flow is unchanged (201 transparent to the UI) and the row exists in `visit_reports`
- [x] 12.5 Restore DB state (delete the test report row)
- [x] 12.6 Create report `reports/YYYY-MM-DD-step-12-e2e-testing.md`

## 13. Update Technical Documentation (MANDATORY)

- [x] 13.1 Update `docs/api-spec.yml` — report endpoint responds `201`
- [x] 13.2 Update `docs/data-model.md` — storage section now reflects implemented tables; move `VisitReport` out of "Planned Extensions"
- [x] 13.3 Review `docs/backend-standards.md` for anything new to document (expected: none — implementation follows it)
