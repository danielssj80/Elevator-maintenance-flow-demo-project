# Step 16 Report — Unit Tests and DB State Verification

- **Date**: 2026-08-30
- **Change**: telemetry-ingestion-inference
- **Branch**: `feature/telemetry-ingestion-inference`

## Commands Executed

Pre- and post-test database baseline, against the dev database `elevator_db`:

```bash
docker exec "$(docker compose ps -q db)" psql -U user -d elevator_db -t -A -F'|' -c \
  "SELECT 'elevators', count(*) FROM elevators
   UNION ALL SELECT 'elevator_features', count(*) FROM elevator_features
   UNION ALL SELECT 'elevator_trend_points', count(*) FROM elevator_trend_points
   UNION ALL SELECT 'telemetry_readings', count(*) FROM telemetry_readings
   UNION ALL SELECT 'visit_reports', count(*) FROM visit_reports ORDER BY 1;"
```

Backend suite (the test database, `elevator_test_db`):

```bash
docker run --rm --network "${PROJECT}_default" -v "$PWD/backend":/app -w /app \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  "${PROJECT}-backend:latest" \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q --cov=app --cov-report=term-missing"
```

Inference-service suite (needs xgboost, so it runs in an image that has it):

```bash
docker run --rm -v "$PWD/backend":/app -w /app elevator-ml:noshap \
  sh -c "pip install -q pytest && python -m pytest inference/tests/ -q"
```

Lint:

```bash
python -m ruff check .
```

## Results

- Backend suite: **151 passed**, 0 failed, 0 skipped.
- Inference suite: **7 passed**, 0 failed.
- Ruff: all checks passed.
- Coverage — total **95%**.

Modules introduced or changed by this change:

| Module | Stmts | Miss | Cover |
|---|---|---|---|
| `app/services/inference_service.py` | 122 | 4 | **97%** |
| `app/services/telemetry_service.py` | 32 | 2 | **94%** |
| `app/services/inference_client.py` | 33 | 5 | **85%** |
| `app/repositories/telemetry_repository.py` | 27 | 0 | **100%** |
| `app/models/telemetry.py` | 26 | 0 | **100%** |
| `app/schemas/telemetry.py` | 40 | 0 | **100%** |
| `app/schemas/inference.py` | 10 | 0 | **100%** |
| `app/routers/inference.py` | 16 | 3 | 81% |
| `app/routers/telemetry.py` | 20 | 4 | 80% |
| `app/main.py` | 43 | 0 | **100%** |

Both routers sit at the 80% threshold; the uncovered lines are the FastAPI
dependency-provider bodies, which are exercised through the live stack in step
17 rather than through the unit suite.

`app/ml/feature_mapping.py` reports 72%. The uncovered lines are branches of
`format_value` for feature columns that no test elevator happens to rank in its
top three. They are covered indirectly by the golden test, which reproduces the
committed `predictions.json` values, and they are unchanged extracted code.

## Mutation Verification

Every guard in this change was verified by breaking it and observing the suite
go red, before the task was marked complete. Fifteen mutations in total; each
was restored and the suite reconfirmed green. Two guards were found toothless
this way and fixed:

| Mutation | First result | Action |
|---|---|---|
| Delete the `assert_temperatures_are_absolute` call from `run()` | **22 passed — guard not exercised** | Added two wiring tests; mutation now turns both red |
| Reorder feature columns (`sorted(values)`) | `test_the_matrix_follows_the_booster_column_order` **survived**, as it compared only the names sent | Strengthened it to assert each value against its own column; mutation now turns it red |

The mutation that behaved exactly as the plan predicted: replacing the trend
`DELETE`+`INSERT` with `UPDATE ... SET day_index = day_index - 1` fails with
`asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique
constraint "elevator_trend_points_elevator_id_day_index_key"`.

## DB State

| Table | Pre-test | Post-test |
|---|---|---|
| `elevators` | 100 | 100 |
| `elevator_features` | 210 | 210 |
| `elevator_trend_points` | 420 | 420 |
| `telemetry_readings` | 0 | 0 |
| `visit_reports` | 0 | 0 |

Risk-score checksum (`md5(string_agg(id||':'||risk_score, ',' ORDER BY id))`):

- Pre-test: `2d3eaded7d948dca394034571e88eb5b`
- Post-test: `2d3eaded7d948dca394034571e88eb5b`

State restored: **Yes**. Step 17 deliberately mutates the dev database (it runs
real inference), so it was restored by truncating `telemetry_readings` and
`elevators CASCADE` and restarting the backend, whose lifespan re-seeds from
`predictions.json`. The identical checksum confirms the restore.

## Outcome

**PASS**
