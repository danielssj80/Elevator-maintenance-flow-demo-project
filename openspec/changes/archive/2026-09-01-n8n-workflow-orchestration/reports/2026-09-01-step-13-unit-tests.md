# Step 13 Report — Unit Tests and DB State Verification

- **Date**: 2026-09-01
- **Change**: n8n-workflow-orchestration

This report was marked complete before it existed. The independent review caught
that; it is written now from a re-run rather than from memory.

## Commands

```bash
docker run --rm --network elevator-maintenance-flow-demo-project_default \
  -v "$REPO":/repo -w /repo/backend \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  elevator-backend:dev python -m pytest tests/ -q --cov=app --cov-report=term-missing
docker run --rm -v "$REPO/backend":/app -w /app elevator-backend:dev python -m ruff check .
```

## Results

- **232 passed**, 0 failed, 0 skipped (was 226 before the review fixes, 223 before
  this change).
- Coverage **96%**.
- `ruff check .` — All checks passed.

`ruff format --check` is deliberately not run: 49 pre-existing files fail it, the
project does not use it, and `ci.yml` runs `ruff check` only.

### Tests this change adds

| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_orchestration_context.py` | 8 | the middleware: attributes recorded, absent rather than empty, truncation at the real bound, non-recording spans untouched, non-HTTP scopes passed through |
| `tests/unit/test_dev_compose.py` (appended) | 7 | production defines no orchestrator; the queue tier stays behind its profile; main and worker agree; and — added after the review — the privacy, cardinality, production-only and module settings asserted **by value** |

## DB state

| Table | Pre | Post |
|---|---|---|
| `elevators` | 100 | 100 |
| `telemetry_readings` | 2660 | 2660 |

The suite runs against `elevator_test_db` and never touches `elevator_db`. The
row count above is the dev database, which carries real n8n-produced telemetry —
this change's whole point — and is unchanged by the suite. Step 14's own writes
were removed there; see that report.

## Outcome

**PASS**
