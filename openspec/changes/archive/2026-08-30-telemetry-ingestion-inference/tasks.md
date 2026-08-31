# Tasks: telemetry-ingestion-inference

> **Mutation rule for this change.** Every task marked **[M]** is only complete
> once the guard has been broken and the suite observed to go red. Delete or
> invert the guard, run the specific test, see it fail, restore, see it pass —
> before moving to the next task, not as a sweep at the end. Record the mutation
> and its result on the task line. Three adversarial rounds on the previous
> change kept finding tests that passed with the implementation deleted, and an
> end-of-change audit did not catch them.

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/telemetry-ingestion-inference` — stacked on `feature/2026-08-28-otel-observability`, not `main`, because `app/core/telemetry.py` and the OTel settings this change consumes are unmerged
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. Telemetry: Failing Repository Test (TDD)

- [x] 1.1 Write `tests/integration/test_telemetry_repository.py` asserting `create_many()` persists a batch and `list_for_elevator()` returns it newest-first — failing, because nothing exists yet
- [x] 1.2 Confirm the failure is `ImportError`/`NoSuchTableError`, not an assertion typo

## 2. Telemetry: ORM Model

- [x] 2.1 Add `app/models/telemetry.py` with `TelemetryReading` per `design.md`: model-input columns in human units, four persisted-but-unconsumed domain signals, provenance (`source`, `batch_id`, `trace_id`), `recorded_at`, `ingested_at`
- [x] 2.2 Export it from `app/models/__init__.py` so `Base.metadata` sees it in tests
- [x] 2.3 Document in the module docstring which columns the current model consumes and which it does not

## 3. Telemetry: Alembic Migration

- [x] 3.1 Generate the migration with `down_revision = 'aa3f0fc81e9c'`
- [x] 3.2 Hand-write the two indexes: `(elevator_id, recorded_at DESC)` and `(recorded_at DESC)`. Autogenerate did emit DESC, but only because the model expressed it through `postgresql_ops` — the operator-class slot, not the sort order. Model now uses `.desc()` and the migration `sa.text('recorded_at DESC')`; verified the DDL is unchanged and `alembic check` is clean
- [x] 3.3 Add a comment recording that partitioning and BRIN are deferred until ~50 M rows
- [x] 3.4 `alembic upgrade head`, then `alembic downgrade -1` and `upgrade head` again to prove the downgrade works
- [x] 3.5 Verify `test_migrations.py` still passes
- [x] 3.6 **Added mid-implementation, not foreseen in the plan.** `elevators.last_scored_at` + migration `3d92a2ed3fb5`: the trend window shifts on date change and `elevator_trend_points` carries no date, so the decision is not derivable from the trend. Recorded here because the independent review found it present in the code and in no task

## 4. Telemetry: Repository

- [x] 4.1 Implement `create_many()`, `list_for_elevator()` (window + limit, newest first), `aggregate_window()` (AVG temps/speed/torque, MAX run hours, COUNT) and `delete_older_than(days)`
- [x] 4.2 Task 1's tests pass
- [x] 4.3 **[M]** Test `aggregate_window()` excludes readings outside the window — mutated by deleting the `recorded_at >= since` predicate; `test_aggregate_window_excludes_readings_outside_the_window` went red and no other test did; restored, 7 passed

## 5. Telemetry: Schemas, Service, Router (TDD)

- [x] 5.1 Write failing service tests: full batch accepted; partial batch persists valid rows and reports rejected ids; all-invalid batch raises 422; `batch_id` shared across the batch
- [x] 5.2 Add `app/schemas/telemetry.py` with `max_length=1000` on the batch
- [x] 5.3 Implement `app/services/telemetry_service.py`, resolving the current trace id to 32 hex chars, null when no span is recording
- [x] 5.4 Implement `app/routers/telemetry.py` — `POST /api/telemetry/readings`, `GET /api/telemetry/readings`
- [x] 5.5 **[M]** Mutated `valid = [...]` to `list(batch.readings)`; 3 tests went red (partial-batch, all-invalid 422, nothing-persisted); restored, 9 passed
- [x] 5.6 **[M]** Mutated `if not valid:` to `if False:`; `test_batch_with_no_valid_readings_is_rejected` and `test_nothing_is_persisted_when_every_reading_is_invalid` went red; restored
- [x] 5.7 **[M]** Removed `min_length=1, max_length=MAX_BATCH_SIZE` from the batch field; both the oversize and the empty-batch tests went red; restored
- [x] 5.8 Test that ingest succeeds with telemetry disabled and writes a null `trace_id`

## 6. Security: Production Router Gating

- [x] 6.1 Write a failing test asserting that with `deployment_environment == "production"` the telemetry and inference routes return 404 while `GET /api/elevators` and `/health` still work
- [x] 6.2 Gate router registration in `app/main.py`
- [x] 6.3 **[M]** Mutated `if environment != "production":` to `if True:`; `test_gated_routes_are_absent_in_production` and `test_gated_routes_return_404_in_production` went red; restored. The inference router joins `GATED_ROUTES` at task 12.3 — the gate block is written once and covers whatever is inside it

## 7. Refactor: Extract `feature_mapping.py`

- [x] 7.1 Create `app/ml/feature_mapping.py` holding `FEATURE_NAME_MAP`, `FEATURE_MEANS`, `RUN_PARAMS`, `MAX_MOTOR_HOURS`, `_format_value`, `_risk_level`, `_nl_explanation`
- [x] 7.2 Import them in `backend/ml/generate_predictions.py`, deleting the originals
- [x] 7.3 Change the documented invocation to `cd backend && python -m ml.generate_predictions` in the module docstring
- [x] 7.4 Regenerated and compared. **The byte-for-byte claim in the proposal and in the plan was wrong**, and not because of the refactor: `_days_ago()` derives `last_visit_date` from `date.today()`, so `predictions.json` is not reproducible across days. All 100 rows differ in `last_visit_date` and in nothing else. Verified field-wise instead: `risk_score`, `risk_level`, `features`, `trend` and `nl_explanation` are identical for all 100 elevators, which is what the extraction could have broken. Committed file restored rather than churning 100 date lines
- [x] 7.5 Verify `_risk_level` and `elevator_service._derive_risk_level` still agree, and have the service import the shared one rather than keeping its own copy

## 8. Inference Service

- [x] 8.1 Create `backend/inference/` — `main.py` (`POST /score`), `scorer.py`, `requirements.txt` (fastapi, uvicorn, xgboost, joblib, numpy — no shap), `Dockerfile` copying `model.joblib`
- [x] 8.2 Implement scoring with `Booster.predict(dmatrix, pred_contribs=True)`; return `{scores, contributions, model_version}`
- [x] 8.3 Expose the booster's `feature_names` so the caller can order its matrix by them
- [x] 8.4 Drop `shap` from `requirements-ml.txt`
- [x] 8.5 Confirm the service holds no database session and no `DATABASE_URL`

## 9. Golden Test: No Scoring Drift

- [x] 9.1 Write a test feeding the committed feature vectors through the new scorer and asserting each score matches `predictions.json` to 1e-6
- [x] 9.2 Assert the contributions' top-3 impacts sum to within `[0.99, 1.01]`
- [x] 9.3 **[M]** Perturbed `Torque__Nm` by 1% in `golden_vectors.json`; `test_scores_reproduce_the_committed_predictions` went red and nothing else did; restored, 7 passed

## 10. Inference Client

- [x] 10.1 Add `httpx` to `requirements.txt` at the version `requirements-dev.txt` pins
- [x] 10.2 Implement `app/services/inference_client.py` mirroring `BedrockClient`'s structure, with a configurable timeout
- [x] 10.3 Write failing tests: `httpx.ConnectError` → `HTTPException(503)`; `httpx.TimeoutException` → 503
- [x] 10.4 **[M]** Broadened to `except Exception` and switched 503 → 500; 5 tests went red, including `test_a_programming_error_is_not_disguised_as_an_absent_service`; restored, 8 passed

## 11. Inference Service Logic (TDD)

- [x] 11.1 **[M]** Removed `+ KELVIN_OFFSET` from `Air_temperature__K`; **13 of 22 tests went red**, the band check catching it downstream as well; restored
- [x] 11.2 **[M]** Applied `+ KELVIN_OFFSET` twice to `Process_temperature__K`; 11 tests went red; restored
- [x] 11.3 **[M]** Replaced `for name in feature_names` with `sorted(values)`, which swaps `Tool_wear__min` and `Torque__Nm`. First run: 5 red — but `test_the_matrix_follows_the_booster_column_order` **survived**, because it compared only the names sent, not which column each value landed in. Strengthened it to assert every value against its own column; re-ran, 6 red including that one; restored
- [x] 11.4 **[M]** Dropped the `in_model_scope` filter; `test_out_of_scope_elevators_are_never_touched` went red; restored
- [x] 11.5 **[M]** Made `targets = list(in_scope)` so elevators without telemetry are scored; 2 tests went red, including the out-of-window one; restored
- [x] 11.6 **[M]** Made the fallback return a constant 100.0; `test_missing_run_hours_falls_back_to_the_offline_proxy` went red; restored
- [x] 11.7 **[M]** Both branches mutated separately. Same-day branch made to shift → `test_second_run_of_the_same_day_overwrites_index_five` red. New-day branch made to overwrite → `test_first_run_of_a_new_day_shifts_the_window` red. Restored after each
- [x] 11.8 **[M]** Replaced the DELETE+INSERT with `UPDATE ... SET day_index = day_index - 1`. The loop test failed with `asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint "elevator_trend_points_elevator_id_day_index_key"` — the predicted trap, reproduced; restored
- [x] 11.9 **[M]** Removed the `/ total` normalisation; 9 tests went red, the run's own impact-sum assertion firing first; restored
- [x] 11.10 **[M]** Range assertion on both temperature columns before scoring. **Replaces the fleet-variance canary the plan called for**, which was measured against this model and does not fire: Celsius input leaves 51 of 70 scores distinct with the standard deviation within 0.002 of correct, while moving 10 elevators into the wrong band.

      First mutation run: deleting the `assert_temperatures_are_absolute` call from `run()` left **all 22 tests green**. The only test covering it called the function directly, so the guard existed and nothing exercised it through the real path — the most important guard in the change was decoration. Added `test_the_run_refuses_to_score_an_out_of_band_temperature` and `test_the_run_never_reaches_the_model_with_an_out_of_band_row`; re-ran the same mutation, both went red; restored
- [x] 11.11 Whole run executes in one transaction; a mid-run failure leaves the database unchanged. **Marked complete in error on the first pass — no test existed.** Caught by the adversarial review. Writing it surfaced two real defects: an all-zero contribution vector raised an unhandled `ZeroDivisionError` in `_top_features` before the impact-sum check could fire, and nothing asserted that a failing run raises rather than returning a summary (swallowing it would let the request commit partial state under a 200). Both fixed and mutation-checked
- [x] 11.12 `delete_older_than(30)` is called at the end of a successful run

## 12. Inference Router

- [x] 12.1 Implement `app/routers/inference.py` — `POST /api/inference/run`
- [x] 12.2 Return a run summary: scored count, skipped count, out-of-scope count, duration, model version
- [x] 12.3 `POST /api/inference/run` added to `GATED_ROUTES`; the gate block covers it and the production tests assert its 404

## 13. Compose (dev only)

- [x] 13.1 Add the `inference` service to `docker-compose.yml` with a `mem_limit` and a healthcheck
- [x] 13.2 Point the backend at it via `INFERENCE_URL`
- [x] 13.3 Confirm `docker-compose.prod.yml` is **not** modified
- [x] 13.4 **`backend inference` was not enough.** `migrate` is a separate compose service with `build: ./backend`, so it has its own image (`…-migrate`); building only backend and inference left it running the old `alembic/versions/` and the stack failed with `Can't locate revision identified by '3d92a2ed3fb5'`. Correct command is `docker compose build backend migrate inference`; recorded in `docs/backend-standards.md`

## 14. Inference Spans

- [x] 14.1 Add a domain span around the run carrying scored/skipped counts and model version
- [x] 14.2 Instrument the inference service with the OTel SDK so the trace spans three services
- [x] 14.3 Verified in Tempo: one trace from `POST /api/inference/run` carries `elevator-backend` (server + `inference.run` + 79 SQL spans) and `elevator-inference` (`GET /model`, `POST /score`, `inference.score`). n8n becomes the third service in change 3
- [x] 14.4 Confirm no telemetry values or elevator identifiers beyond ids are recorded as span attributes

## 15. Review and Update Existing Tests (MANDATORY)

- [x] 15.1 Review `tests/unit/test_elevator_service.py` for tests invalidated by the shared `_risk_level` import
- [x] 15.2 Review `tests/integration/test_seed.py` and `test_migrations.py` against the new table
- [x] 15.3 Review `tests/conftest.py` — the new table must be created and torn down with the rest
- [x] 15.4 Update whatever the change invalidated; note anything deliberately left alone

## 16. Unit Tests and DB State Verification (MANDATORY)

- [x] 16.1 Capture pre-test DB baseline (row counts for `elevators`, `elevator_features`, `elevator_trend_points`, `telemetry_readings`)
- [x] 16.2 Run targeted tests for the new modules
- [x] 16.3 Run the full suite: `pytest tests/ -v --cov=app --cov-report=term-missing`, ≥80% on services and repositories
- [x] 16.4 Verify post-test DB state matches the baseline
- [x] 16.5 Create `reports/2026-08-30-step-16-unit-tests.md`
- [x] 16.6 Mark complete only after the report exists and the suite passes

## 17. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [x] 17.1 Rebuild and start the stack; confirm the running image matches the source tree
- [x] 17.2 `POST /api/telemetry/readings` with a valid batch → 201, rows carry a `trace_id`
- [x] 17.3 `POST /api/telemetry/readings` with a batch containing unknown ids → 201, partial accept reported
- [x] 17.4 `POST /api/telemetry/readings` with an all-unknown batch → 422
- [x] 17.5 `POST /api/telemetry/readings` with >1000 readings → 422
- [x] 17.6 `GET /api/telemetry/readings` → 200, newest first; unknown elevator → 200 with an empty list
- [x] 17.7 `POST /api/inference/run` → 200, run summary; verify scores changed and fleet variance > 0
- [x] 17.8 `docker compose stop inference` → **503**, `{"detail":"Inference service is unavailable"}`, zero traceback lines in the backend log, and `last_scored_at IS NOT NULL` still 14 — the failed run wrote nothing
- [x] 17.9 Start with `DEPLOYMENT_ENVIRONMENT=production` → both new endpoints 404, `GET /api/elevators` still 200
- [x] 17.10 Restore DB state after every mutating call
- [x] 17.11 Create `reports/2026-08-30-step-17-endpoint-testing.md`

## 18. E2E Testing with Playwright MCP — N/A

- [x] 18.1 **Not applicable.** No file under `frontend/` is touched and no API response shape changes. The dashboard reads the same fields it reads today; only their values change. Recorded as an explicit N/A rather than skipped silently, as `2026-07-17-docker-images-to-ghcr/tasks.md` §7 did

## 19. Update Technical Documentation (MANDATORY)

- [x] 19.1 `docs/api-spec.yml` — add `POST /api/telemetry/readings`, `GET /api/telemetry/readings`, `POST /api/inference/run` with schemas and error responses
- [x] 19.2 `docs/data-model.md` — add `TelemetryReading`, and **fix the stale "known feature names" table**, which documents vibration/current/door signals the model has never consumed. State which columns feed the model and which are persisted only
- [x] 19.3 `docs/backend-standards.md` — the inference-service pattern, the `feature_mapping` shared module, and the new `cd backend && python -m ml.generate_predictions` invocation
- [x] 19.4 Docs updated directly: `data-model.md` (stale feature table, `TelemetryReading`, `last_scored_at`, trend-shift rule), `api-spec.yml` (3 paths, 5 schemas, the 500), `backend-standards.md` (ML-at-runtime section, compose rebuild trap, production gating)

## 20. Adversarial Review

- [x] 20.0 **Concurrency, found by the review.** Two concurrent `POST /api/inference/run` against the live stack both returned 200 and both took the new-day branch, shifting the trend window twice for one day — a literal violation of the date-change requirement, in the exact scenario it exists to protect. Fixed with `pg_advisory_xact_lock` for the transaction's duration; re-measured on the live stack, the second run now waits (0.464s vs 0.205s) and the window advances once

- [x] 20.1 Round 1, by the implementing session. Found 3 Majors (no test for task 11.11; unhandled `ZeroDivisionError` on a degenerate contribution vector; concurrent runs double-shifting the trend). Report: `reports/2026-08-30-adversarial-review.md`
- [x] 20.2 Round 2, **independent session with no prior context**. Verdict FAIL, 4 Majors. It reproduced all 17 `[M]` claims from scratch and found what round 1 could not see — including that round 1's own fix, the advisory lock, shipped with no test at all. Report: `reports/2026-08-30-adversarial-review-independent.md`
- [x] 20.3 Findings addressed: ingest range + no-future validation; window and prune bounded at both ends; out-of-band rows skipped per elevator instead of aborting the fleet, with the abort kept for the all-rows case that means a broken conversion; `FeatureBuildError` mapped to a described 500 instead of a traceback; prune runs even when nothing is scored; the one-hot and tool-wear proxy genuinely shared with the offline generator; the golden fixture anchored to `predictions.json`. **Seven new guards, each mutation-checked** — including the lock, whose first test called the helper directly and survived deletion of the call from `run()`, which is the same mistake a third time
- [x] 20.4 **Round 3, independent.** Verdict FAIL — 2 Blockers, 5 Majors. It reproduced 21 of 22 mutation claims and confirmed the live behaviour was correct in every probe, then found the two things nobody had asked. Report: `reports/2026-08-30-adversarial-review-round3.md`
- [x] 20.5 Round 3 findings addressed:
    - **Blocker — the gate was fail-open.** `docker-compose.prod.yml` sets `DEPLOYMENT_ENVIRONMENT` nowhere and loads an out-of-repo env file, while the default was `local`. Merging would have published two unauthenticated write endpoints. Rounds 1 and 2 both tested the gate by setting the variable by hand, which only ever asks whether the mechanism works when configured. Default is now `production`, prod compose states it explicitly, `conftest` declares the suite local, and the built image with the variable unset was verified to return 404 on both routes and 200 on the rest
    - **Blocker — `7074d51` changed behaviour and touched no spec.** Both spec files realigned: the out-of-band response is now specified as two distinct faults with opposite handling, and ingest validation, the run summary, the read window and the fail-closed default have requirements of their own
    - **Major — silent data loss I introduced.** Ingest accepted +5 min of clock skew while the window excluded and the prune deleted anything past `now`. One tolerance now, used by all three
    - **Major — a dead `until` parameter** that `proposal.md` was simultaneously edited to claim was in use. Now passed by `list_readings`, and tested
    - **Major — a seeded fleet lost a trend point** on the first run of its seeding day. Seeding now records `last_scored_at`, because loading model output is a scoring event
    - Five new guards, each mutation-checked. **One of them was not caught on the first attempt** — the read endpoint's upper bound had no test, which is the fourth instance of the same pattern in this change and was again only found by mutating rather than by reading
- [x] 20.6 Steps 16 and 17 re-run against the current code and both reports refreshed. Step 17 gained a re-run section covering ingest validation, the new summary field, the trend fix, and the gate with the variable unset entirely — the state prod compose actually produces
- [x] 20.7 **Round 4, independent.** Verdict FAIL — 3 Majors, no Blockers. Report: `reports/2026-08-30-adversarial-review-round4.md`. Findings addressed:
    - **Major — round 3's Blocker fix had no regression guard.** Reverting the `os.getenv` default to `"local"`, literally the bug round 3 found, left all 180 tests green. One test asserted the *constant*; the other monkeypatched `settings` **to** that constant. Neither exercised the environment read. Replaced with a subprocess test that removes the variable from the environment and asserts on the routes the resulting app registers — this process cannot test it, because `conftest` sets the variable before anything imports and `Settings` reads it once at import. **Fifth instance in this change of a guard tested beside the real path, and on the security control itself**
    - **Major — only two members of the transport-fault family were caught.** `RemoteProtocolError`, `ReadError` and `WriteError` escaped as an unhandled 500 with a traceback, which the spec forbids in those words, and the scorer runs under `mem_limit: 512m` so a connection dying mid-response is ordinary. Now catches `httpx.TransportError`; `HTTPStatusError` is deliberately still not caught, since the service answering badly is not the service being absent
    - **Major — the step-16 coverage table was stale in all ten rows** while task 20.6 claimed the report was refreshed; the refresh had changed only the pass counts. Regenerated from an actual run
    - Round 3's Major 3, which round 4 found had been dropped rather than fixed: the conversion check fired only when **every** row was out of band, so one row landing inside the band disabled it for the rest. Now a majority
    - Two stale claims this change created elsewhere: the comment in `app/core/telemetry.py` saying httpx is not a runtime dependency (this change made it one), and `inference/telemetry.py` still defaulting its environment label to `local`
    - Documented that a bare `uvicorn app.main:app` now needs `DEPLOYMENT_ENVIRONMENT=local`, since the fail-closed default otherwise 404s these endpoints with no explanation
    - Five new guards, each mutation-checked
