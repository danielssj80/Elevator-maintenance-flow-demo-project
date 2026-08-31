# Step 9 Report — Unit Tests and DB State Verification

- **Date**: 2026-08-31
- **Change**: harden-telemetry-ingest
- **Branch**: `feature/harden-telemetry-ingest`

## Commands Executed

Database baseline, against the dev database `elevator_db`:

```bash
docker exec "$(docker compose ps -q db)" psql -U user -d elevator_db -t -A -F'|' -c \
  "SELECT 'elevators', count(*) FROM elevators
   UNION ALL SELECT 'elevator_features', count(*) FROM elevator_features
   UNION ALL SELECT 'elevator_trend_points', count(*) FROM elevator_trend_points
   UNION ALL SELECT 'telemetry_readings', count(*) FROM telemetry_readings
   UNION ALL SELECT 'visit_reports', count(*) FROM visit_reports ORDER BY 1;"
```

Backend suite, against `elevator_test_db`:

```bash
docker run --rm --network elevator-maintenance-flow-demo-project_default \
  -v "$REPO":/repo -w /repo/backend \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  elevator-backend:dev \
  python -m pytest tests/ -q --cov=app --cov-report=term-missing
```

Lint:

```bash
python -m ruff check .
```

> **The harness changed during this change, and the change is the point.** The
> previous change ran the suite with `-v "$PWD/backend":/app -w /app`. That
> mounts `backend/` alone, so the compose files at the repository root do not
> exist inside the container and `tests/unit/test_dev_compose.py` errored out
> while passing in CI. `ci.yml` sets `working-directory: backend` inside a full
> checkout, so mounting the whole repository and working from `backend/` is what
> actually mirrors CI. Anything that reads a file above `backend/` is invisible
> to the old harness.
>
> `elevator-backend:dev` is the compose backend image with `requirements-dev.txt`
> layered on, built once instead of `pip install`-ing on every run. It is a local
> convenience, not a repository artifact — the Notion task *Backend dev Docker
> image: multi-stage Dockerfile with a dev target* is the real fix.

## Results

- Full suite: **212 passed**, 0 failed, 0 skipped (was 186 before this change).
- Coverage: **96%** (1084 statements, 46 missed).
- `app/core/ingest_auth.py`: **100%** (11 statements).
- `app/models/telemetry.py`: **100%**. `app/repositories/telemetry_repository.py`: 96%.
- `ruff check .`: **All checks passed!**

`ruff format --check` was deliberately not run: 49 pre-existing files fail it, so
the project does not use it, and running it here would report noise rather than
findings. `ci.yml` runs `ruff check` only.

### Tests added

| File | Tests | Covers |
|---|---|---|
| `tests/integration/test_telemetry_idempotency.py` | 6 | identity, DO NOTHING, distinct `source`, window aggregate |
| `tests/integration/test_migrations.py` (appended) | 1 | the dedup `DELETE` against a database that already holds duplicates |
| `tests/unit/test_telemetry_service.py` (appended) | 5 | `accepted` / `duplicates_ignored`, retry is 201 not 422, `batch_id` provenance |
| `tests/unit/test_ingest_auth.py` | 10 | 401 on both write routes, indistinguishable rejections, fail-open, startup warning |
| `tests/unit/test_dev_compose.py` | 4 | the guards asserted against `docker-compose.yml` and `docker-compose.prod.yml` |

### Test invalidated by this change

`tests/unit/test_inference_service.py::test_ten_consecutive_shifts_never_violate_the_unique_constraint`
seeded a reading and then seeded the same `(elevator_id, recorded_at, source)`
again on day 0 of its loop. The collision is in the fixture data, not in the
product: the loop already seeds one reading per iteration, so the pre-seeded row
was redundant and was removed. No assertion changed.

## DB State

| Table | Pre-test | Post-test |
|---|---|---|
| `elevators` | 100 | 100 |
| `elevator_features` | 210 | 210 |
| `elevator_trend_points` | 420 | 420 |
| `telemetry_readings` | 0 | 0 |
| `visit_reports` | 0 | 0 |

The suite runs against `elevator_test_db` and never touches `elevator_db`. The
dev database was mutated by step 10's endpoint testing and restored there; see
that report.

## Outcome

**PASS**
