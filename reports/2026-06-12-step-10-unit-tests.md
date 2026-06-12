# Step 10 — Unit Tests & DB State Verification

**Date:** 2026-06-12
**Change:** migrate-backend-postgresql

## Pre-test DB baseline (elevator_db)

| Table                  | Rows |
|------------------------|------|
| elevators              | 100  |
| elevator_features      | 300  |
| elevator_trend_points  | 600  |
| visit_reports          | 0    |

## Test run

```
22 passed in 5.23s
```

### Coverage

| Module                                      | Cover |
|---------------------------------------------|-------|
| app/repositories/elevator_repository.py    | 100%  |
| app/repositories/visit_report_repository.py| 100%  |
| app/services/elevator_service.py           | 100%  |
| app/routers/elevators.py                   | 100%  |
| app/schemas/elevator.py                    | 100%  |
| app/schemas/visit_report.py                | 100%  |
| app/models/elevator.py                     | 100%  |
| app/models/visit_report.py                 | 100%  |
| app/seed.py                                | 100%  |
| **TOTAL**                                  | **96%** |

> Uncovered lines: `app/core/exceptions.py` (4 lines — never raised in tests because service raises `HTTPException` directly) and `app/main.py` lines 14-17, 34 (lifespan startup/shutdown path not exercised by unit tests).

## Post-test DB state (elevator_db)

| Table                  | Rows |
|------------------------|------|
| elevators              | 100  |
| elevator_features      | 300  |
| elevator_trend_points  | 600  |
| visit_reports          | 0    |

**Matches baseline — no production data modified by test run.**

## Result

PASS — all 22 tests green, ≥80% coverage requirement met (96% total, 100% on services/repositories).
