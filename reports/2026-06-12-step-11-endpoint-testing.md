# Step 11 — Manual Endpoint Testing

**Date:** 2026-06-12
**Change:** migrate-backend-postgresql

## Bug found and fixed

`app/database.py` — `get_db()` was missing `await session.commit()`. The repository called `flush()` (sends SQL to DB) but the transaction was never committed, so data was silently discarded when the session closed. Fixed by adding `await session.commit()` after `yield`. All 22 tests remain green after the fix.

## Results

| Step | Check | Result |
|------|-------|--------|
| 11.2 | `GET /api/elevators` → 200, 100 items, sorted by `risk_score` desc | PASS |
| 11.3 | `GET /api/elevators/ELV-001` → 200, 3 features, 6-element trend | PASS |
| 11.4 | `GET /api/elevators/UNKNOWN` → 404 | PASS |
| 11.5 | `POST /api/elevators/ELV-001/report` → 201, row verified in `visit_reports`, row deleted | PASS |
| 11.6a | `POST /api/elevators/UNKNOWN/report` → 404 | PASS |
| 11.6b | `POST` with empty body → 422 | PASS |
| 11.6c | No rows persisted after error cases | PASS |
| 11.7 | Stack restarted; data persisted; no duplicate seeding (100 rows each time) | PASS |

## Stack state

- Backend: healthy at `http://localhost:8000`
- DB: `elevator_db` — 100 elevators, 300 features, 600 trend points, 0 visit reports
- Port 5432 mapped to host (added to `docker-compose.yml` to allow test suite to reach the DB directly)
