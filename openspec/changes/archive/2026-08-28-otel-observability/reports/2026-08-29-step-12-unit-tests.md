# Step 12 Report — Unit Tests and DB State Verification

- **Date**: 2026-08-29
- **Change**: 2026-08-28-otel-observability
- **Branch**: `feature/2026-08-28-otel-observability`

## Commands Executed

Pre- and post-test database baseline (against the dev database, `elevator_db`):

```bash
docker exec "$(docker compose ps -q db)" psql -U user -d elevator_db -t -A -F'|' -c \
  "SELECT 'elevators', count(*) FROM elevators
   UNION ALL SELECT 'elevator_features', count(*) FROM elevator_features
   UNION ALL SELECT 'elevator_trend_points', count(*) FROM elevator_trend_points
   UNION ALL SELECT 'visit_reports', count(*) FROM visit_reports ORDER BY 1;"
```

Targeted suites:

```bash
docker run --rm --network "${PROJECT}_default" -v "$PWD/backend":/app -w /app \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  "${PROJECT}-backend:latest" \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest \
     tests/unit/test_telemetry_spans.py tests/unit/test_fleet_health_service.py -v"
```

Full suite with coverage:

```bash
... python -m pytest tests/ -q --cov=app --cov-report=term-missing
... python -m ruff check .
```

## Results

**83 passed**, 0 failed. Ruff: all checks passed.

Coverage — total **94%**. Modules touched by this change:

| Module | Coverage |
|---|---|
| `app/core/config.py` | 100% |
| `app/core/metrics.py` | 97% |
| `app/core/telemetry.py` | 94% |
| `app/services/fleet_health_service.py` | 100% |
| `app/services/genai_attributes.py` | 100% |
| `app/services/briefing_service.py` | 95% |
| `app/services/elevator_service.py` | 100% |
| `app/repositories/*` | 100% |

All are above the 80% bar in `docs/backend-standards.md`.

`app/main.py` sits at 58%. The uncovered lines are the `lifespan` body, which
httpx's `ASGITransport` does not execute. Its behaviour is covered indirectly:
the refresh task's start, failure and cancellation paths are all tested against
`refresh_snapshot_periodically` directly. Noted rather than papered over.

### Tests added in this step

Two gaps found while reviewing, both for behaviour the spec requires but
nothing verified:

1. **`test_concurrent_briefings_are_not_serialised`** — covers the spec scenario
   "Concurrent requests are not serialised behind a slow briefing". Verified to
   have teeth: with the `anyio.to_thread` offload temporarily reverted to a
   direct call, it fails with *"two briefings took 0.60s for a 0.3s call each —
   the event loop is being blocked"*. With the offload in place the pair
   completes in 0.53s.
2. **`test_loop_survives_a_failing_session_factory`** — the refresh loop is the
   application's only scheduler; a database error must not kill it.

Plus four registration tests that lifted `app/core/metrics.py` from 78% (below
the bar) to 97%.

### Existing tests reviewed

- `tests/unit/test_briefing_service.py` — still valid. The mocked client is
  called synchronously inside the worker thread, so `side_effect` and
  `call_count` assertions behave unchanged.
- `tests/integration/test_elevators_router.py`, `test_migrations.py` — unaffected;
  no response shape or schema changed.
- No test depends on telemetry being enabled. The session fixture passes
  `enabled=True` explicitly instead of mutating the `settings` singleton, so the
  two assertions that telemetry is off by default stay meaningful.

### Fixture defect found and fixed

`briefing_service._CACHE` is a module-level dict shared across the whole
process, but the fixture clearing it lived in `test_briefing_service.py`. New
tests in another module silently inherited a cached briefing and asserted the
wrong source. The fixture moved to `conftest.py`.

## DB State

| Table | Before | After |
|---|---|---|
| `elevators` | 100 | 100 |
| `elevator_features` | 210 | 210 |
| `elevator_trend_points` | 420 | 420 |
| `visit_reports` | 0 | 0 |

`diff` of the before/after snapshots: identical. **Restored: not applicable —
nothing was mutated.** The suite runs against a separate `elevator_test_db`
whose schema is created and dropped per session.

## Outcome

**PASS**
