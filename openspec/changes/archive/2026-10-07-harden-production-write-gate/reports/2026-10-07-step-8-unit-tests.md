# Step 8 Report — Unit Tests

- Date: 2026-10-07
- Change: harden-production-write-gate

## Environment
Run the way CI does: `python:3.12-slim` with the pinned `requirements.txt` + `requirements-dev.txt`,
repo root mounted at `/repo`, working directory `/repo/backend`, `postgres:16-alpine` as the
test database (`TEST_DATABASE_URL=postgresql+asyncpg://user:password@gate-pg:5432/elevator_test_db`).

## Commands Executed
- `ruff check .`
- `python -m pytest tests/ -q`
- Targeted: `python -m pytest tests/unit/test_config_environment.py tests/unit/test_production_gating.py tests/unit/test_ingest_auth.py tests/unit/test_nginx_prod_conf.py tests/unit/test_dev_compose.py -q`

## Results
- ruff: All checks passed
- Full suite: **286 passed**, 0 failed, 0 skipped
- Coverage: not measured (`pytest-cov` is not in `requirements-dev.txt`; CI does not measure it either)

## Mutations (each run inline, before the guard's task was ticked)
| Guard | Mutation | Result |
|---|---|---|
| `is_production` | `environment.strip().lower() not in …` | 5 failed |
| `is_production` | deny-list `environment == "production"` | 11 failed |
| registration | revert to `environment != "production"` | 8 failed |
| registration | drop the length check | 1 new failure |
| registration | register in production without a token | 11 failed |
| registration | `<` → `<=` (off by one) | 1 new failure |
| guard | remove the production fail-closed branch | 2 failed |
| guard | fail-closed everywhere | 2 failed |
| POST route | remove `require_ingest_token` | 7 failed |
| GET route | remove `require_ingest_token` | 2 failed |
| nginx | comment out `limit_req` on `/api/inference/run` | 1 failed |
| nginx | add `limit_req` to the generic `/api/` location | 1 failed |
| conftest | `setdefault` with `DEPLOYMENT_ENVIRONMENT=production` exported | 12 failed before the fix, 34 passed after |

## DB State
- Pre-test: `elevator_test_db` public schema, 0 tables
- Post-test: 0 tables (the session fixture creates and drops the schema)
- State restored: Yes

## Outcome
PASS
