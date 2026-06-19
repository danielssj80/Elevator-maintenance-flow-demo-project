# Step 3 Report — Unit Tests

- Date: 2026-06-19
- Change: deploy-portfolio-coexistence

## Scope Note
Infrastructure-only change: the only modified source is `.github/workflows/deploy.yml`
(the SSM deploy command) plus OpenSpec artifacts. No backend/frontend application
code, no DB schema, no API surface. `git diff main` confirms zero Python delta.
Therefore:
- Step 2 (review existing tests): no tests are affected — none required updating.
- The unit suite is run purely as a regression sanity baseline.

## Commands Executed
- `docker-compose up -d db` (dev PostgreSQL)
- `docker exec ... createdb -U user elevator_test_db` (already existed)
- Unit suite inside the backend image, joined to the compose network:
  ```
  docker run --rm --network elevator-maintenance-flow-demo-project_default \
    -v "$PWD/backend":/app -w /app \
    -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
    elevator-...-backend:latest \
    sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/unit/ -q"
  ```

## Results
- Full unit suite: **22 passed, 0 failed, 0 skipped**

## DB State
- Pre-test: not applicable — change touches no data; unit tests manage their own test DB
- Post-test: test DB (`elevator_test_db`) state managed by the suite's own fixtures
- State restored: Not needed (no production/dev data touched)

## Notes
- The prod backend image ships without dev dependencies, so `pytest` was installed
  ephemerally for this run. Captured as a future improvement (dev image variant /
  baked-in pytest) — see project notes.

## Outcome
PASS
