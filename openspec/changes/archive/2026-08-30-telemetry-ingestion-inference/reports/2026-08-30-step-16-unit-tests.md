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

- Backend suite: **186 passed**, 0 failed, 0 skipped.
- Inference suite: **8 passed**, 0 failed.
- Ruff: all checks passed.
- Coverage — total **96%**.

Modules introduced or changed by this change:

| Module | Stmts | Miss | Cover |
|---|---|---|---|
| `app/services/inference_service.py` | 142 | 5 | **96%** |
| `app/services/telemetry_service.py` | 32 | 1 | **97%** |
| `app/services/inference_client.py` | 33 | 3 | **91%** |
| `app/repositories/telemetry_repository.py` | 30 | 0 | **100%** |
| `app/models/telemetry.py` | 26 | 0 | **100%** |
| `app/schemas/telemetry.py` | 51 | 1 | **98%** |
| `app/schemas/inference.py` | 11 | 0 | **100%** |
| `app/routers/inference.py` | 16 | 1 | **94%** |
| `app/routers/telemetry.py` | 20 | 0 | **100%** |
| `app/main.py` | 51 | 0 | **100%** |

> Regenerated 2026-08-30 after round 4, which found this table stale in all ten
> rows while `tasks.md` claimed the report had been refreshed — the refresh had
> touched only the pass counts. These numbers come from the run recorded above.

Both routers are now covered through the HTTP layer as well; the single
uncovered line in `inference.py` is a dependency-provider body, exercised
through the live stack in step 17.

`app/ml/feature_mapping.py` reports 78%. The uncovered lines are branches of
`format_value` for feature columns that no test elevator happens to rank in its
top three. They are covered indirectly by the golden test, which reproduces the
committed `predictions.json` values, and they are unchanged extracted code.

## Mutation Verification

> **Superseded in part.** This section was written before the two adversarial
> rounds. Its claim that *every* guard was verified was true of the guards that
> existed when it was written, and false of three added afterwards — the
> advisory lock, the atomicity behaviour, and the degenerate-contribution
> check. See `2026-08-30-adversarial-review.md` and
> `2026-08-30-adversarial-review-independent.md`; all three are now
> mutation-checked, along with four more added in response to round 2.

Every guard existing at the time of this step was verified by breaking it and
observing the suite go red, before the task was marked complete. Fifteen
mutations; each was restored and the suite reconfirmed green. Two guards were
found toothless this way and fixed:

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
