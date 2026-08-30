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

- [ ] 1.1 Write `tests/integration/test_telemetry_repository.py` asserting `create_many()` persists a batch and `list_for_elevator()` returns it newest-first — failing, because nothing exists yet
- [ ] 1.2 Confirm the failure is `ImportError`/`NoSuchTableError`, not an assertion typo

## 2. Telemetry: ORM Model

- [ ] 2.1 Add `app/models/telemetry.py` with `TelemetryReading` per `design.md`: model-input columns in human units, four persisted-but-unconsumed domain signals, provenance (`source`, `batch_id`, `trace_id`), `recorded_at`, `ingested_at`
- [ ] 2.2 Export it from `app/models/__init__.py` so `Base.metadata` sees it in tests
- [ ] 2.3 Document in the module docstring which columns the current model consumes and which it does not

## 3. Telemetry: Alembic Migration

- [ ] 3.1 Generate the migration with `down_revision = 'aa3f0fc81e9c'`
- [ ] 3.2 Hand-write the two indexes: `(elevator_id, recorded_at DESC)` and `(recorded_at DESC)` — autogenerate will not produce the DESC ordering
- [ ] 3.3 Add a comment recording that partitioning and BRIN are deferred until ~50 M rows
- [ ] 3.4 `alembic upgrade head`, then `alembic downgrade -1` and `upgrade head` again to prove the downgrade works
- [ ] 3.5 Verify `test_migrations.py` still passes

## 4. Telemetry: Repository

- [ ] 4.1 Implement `create_many()`, `list_for_elevator()` (window + limit, newest first), `aggregate_window()` (AVG temps/speed/torque, MAX run hours, COUNT) and `delete_older_than(days)`
- [ ] 4.2 Task 1's tests pass
- [ ] 4.3 **[M]** Test `aggregate_window()` excludes readings outside the window — mutate by widening the window predicate, confirm red

## 5. Telemetry: Schemas, Service, Router (TDD)

- [ ] 5.1 Write failing service tests: full batch accepted; partial batch persists valid rows and reports rejected ids; all-invalid batch raises 422; `batch_id` shared across the batch
- [ ] 5.2 Add `app/schemas/telemetry.py` with `max_length=1000` on the batch
- [ ] 5.3 Implement `app/services/telemetry_service.py`, resolving the current trace id to 32 hex chars, null when no span is recording
- [ ] 5.4 Implement `app/routers/telemetry.py` — `POST /api/telemetry/readings`, `GET /api/telemetry/readings`
- [ ] 5.5 **[M]** Mutate the unknown-id filter to accept everything; confirm the partial-batch test goes red
- [ ] 5.6 **[M]** Mutate the all-invalid guard to return 201; confirm the 422 test goes red
- [ ] 5.7 **[M]** Remove `max_length=1000`; confirm the oversize-batch test goes red
- [ ] 5.8 Test that ingest succeeds with telemetry disabled and writes a null `trace_id`

## 6. Security: Production Router Gating

- [ ] 6.1 Write a failing test asserting that with `deployment_environment == "production"` the telemetry and inference routes return 404 while `GET /api/elevators` and `/health` still work
- [ ] 6.2 Gate router registration in `app/main.py`
- [ ] 6.3 **[M]** Remove the gate; confirm the test goes red. This guard is the one standing between an auto-deploying production API with no authentication and a public write endpoint — it does not get taken on trust

## 7. Refactor: Extract `feature_mapping.py`

- [ ] 7.1 Create `app/ml/feature_mapping.py` holding `FEATURE_NAME_MAP`, `FEATURE_MEANS`, `RUN_PARAMS`, `MAX_MOTOR_HOURS`, `_format_value`, `_risk_level`, `_nl_explanation`
- [ ] 7.2 Import them in `backend/ml/generate_predictions.py`, deleting the originals
- [ ] 7.3 Change the documented invocation to `cd backend && python -m ml.generate_predictions` in the module docstring
- [ ] 7.4 Regenerate `predictions.json` and verify it is **byte-for-byte identical** to the committed file (`git diff --exit-code backend/ml/predictions.json`) — the seeded RNG makes this checkable
- [ ] 7.5 Verify `_risk_level` and `elevator_service._derive_risk_level` still agree, and have the service import the shared one rather than keeping its own copy

## 8. Inference Service

- [ ] 8.1 Create `backend/inference/` — `main.py` (`POST /score`), `scorer.py`, `requirements.txt` (fastapi, uvicorn, xgboost, joblib, numpy — no shap), `Dockerfile` copying `model.joblib`
- [ ] 8.2 Implement scoring with `Booster.predict(dmatrix, pred_contribs=True)`; return `{scores, contributions, model_version}`
- [ ] 8.3 Expose the booster's `feature_names` so the caller can order its matrix by them
- [ ] 8.4 Drop `shap` from `requirements-ml.txt`
- [ ] 8.5 Confirm the service holds no database session and no `DATABASE_URL`

## 9. Golden Test: No Scoring Drift

- [ ] 9.1 Write a test feeding the committed feature vectors through the new scorer and asserting each score matches `predictions.json` to 1e-6
- [ ] 9.2 Assert the contributions' top-3 impacts sum to within `[0.99, 1.01]`
- [ ] 9.3 **[M]** Perturb one input column by 1%; confirm the golden test goes red — proving it compares values rather than shapes

## 10. Inference Client

- [ ] 10.1 Add `httpx` to `requirements.txt` at the version `requirements-dev.txt` pins
- [ ] 10.2 Implement `app/services/inference_client.py` mirroring `BedrockClient`'s structure, with a configurable timeout
- [ ] 10.3 Write failing tests: `httpx.ConnectError` → `HTTPException(503)`; `httpx.TimeoutException` → 503
- [ ] 10.4 **[M]** Broaden the except clause to bare `Exception` and return 500; confirm both tests go red

## 11. Inference Service Logic (TDD)

- [ ] 11.1 **[M]** Kelvin: test that `ambient_temperature_c = 27.0` becomes `Air_temperature__K = 300.15` in the matrix — mutate by removing `+ 273.15`, confirm red. **This is the single most important test in the change**
- [ ] 11.2 **[M]** Kelvin applied exactly once: test that no later stage re-offsets — mutate by adding a second conversion, confirm red
- [ ] 11.3 **[M]** Column order comes from the booster's `feature_names`, not a literal — mutate by hardcoding a reordered list, confirm red
- [ ] 11.4 **[M]** Out-of-scope elevators are untouched — mutate by dropping the `in_model_scope` filter, confirm red
- [ ] 11.5 **[M]** In-scope elevator with zero readings in the window is skipped, not zeroed — mutate by scoring it with defaults, confirm red
- [ ] 11.6 **[M]** Missing `motor_run_hours_cumulative` falls back to the `age_years × hourly_trips_avg × RUN_PARAMS` proxy — mutate the fallback to a constant, confirm red
- [ ] 11.7 **[M]** Trend stays exactly 6 points; same-day run overwrites index 5; new-day run shifts and appends — mutate each branch separately, confirm red
- [ ] 11.8 **[M]** Repeated shift ×10 never violates the unique constraint and index 5 always equals the score just written — mutate to `UPDATE ... day_index - 1`, confirm it fails (this is the trap the DELETE+INSERT exists to avoid)
- [ ] 11.9 **[M]** Impacts sum ∈ [0.99, 1.01] — mutate the normalisation, confirm red
- [ ] 11.10 **[M]** Fleet score variance > 0 across a varied fleet — mutate by feeding Celsius, confirm red. This is the canary for the failure that produces no error at all
- [ ] 11.11 Whole run executes in one transaction; a mid-run failure leaves the database unchanged
- [ ] 11.12 `delete_older_than(30)` is called at the end of a successful run

## 12. Inference Router

- [ ] 12.1 Implement `app/routers/inference.py` — `POST /api/inference/run`
- [ ] 12.2 Return a run summary: scored count, skipped count, out-of-scope count, duration, model version
- [ ] 12.3 Verify the production gate from task 6 covers this router too

## 13. Compose (dev only)

- [ ] 13.1 Add the `inference` service to `docker-compose.yml` with a `mem_limit` and a healthcheck
- [ ] 13.2 Point the backend at it via `INFERENCE_URL`
- [ ] 13.3 Confirm `docker-compose.prod.yml` is **not** modified
- [ ] 13.4 `docker compose build backend inference` before testing anything against the live stack — the running image goes stale against the source tree and has produced wrong conclusions three times

## 14. Inference Spans

- [ ] 14.1 Add a domain span around the run carrying scored/skipped counts and model version
- [ ] 14.2 Instrument the inference service with the OTel SDK so the trace spans three services
- [ ] 14.3 Verify in Tempo that one trace covers `backend → inference → postgres`
- [ ] 14.4 Confirm no telemetry values or elevator identifiers beyond ids are recorded as span attributes

## 15. Review and Update Existing Tests (MANDATORY)

- [ ] 15.1 Review `tests/unit/test_elevator_service.py` for tests invalidated by the shared `_risk_level` import
- [ ] 15.2 Review `tests/integration/test_seed.py` and `test_migrations.py` against the new table
- [ ] 15.3 Review `tests/conftest.py` — the new table must be created and torn down with the rest
- [ ] 15.4 Update whatever the change invalidated; note anything deliberately left alone

## 16. Unit Tests and DB State Verification (MANDATORY)

- [ ] 16.1 Capture pre-test DB baseline (row counts for `elevators`, `elevator_features`, `elevator_trend_points`, `telemetry_readings`)
- [ ] 16.2 Run targeted tests for the new modules
- [ ] 16.3 Run the full suite: `pytest tests/ -v --cov=app --cov-report=term-missing`, ≥80% on services and repositories
- [ ] 16.4 Verify post-test DB state matches the baseline
- [ ] 16.5 Create `reports/2026-08-30-step-16-unit-tests.md`
- [ ] 16.6 Mark complete only after the report exists and the suite passes

## 17. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [ ] 17.1 Rebuild and start the stack; confirm the running image matches the source tree
- [ ] 17.2 `POST /api/telemetry/readings` with a valid batch → 201, rows carry a `trace_id`
- [ ] 17.3 `POST /api/telemetry/readings` with a batch containing unknown ids → 201, partial accept reported
- [ ] 17.4 `POST /api/telemetry/readings` with an all-unknown batch → 422
- [ ] 17.5 `POST /api/telemetry/readings` with >1000 readings → 422
- [ ] 17.6 `GET /api/telemetry/readings` → 200, newest first; unknown elevator → 200 with an empty list
- [ ] 17.7 `POST /api/inference/run` → 200, run summary; verify scores changed and fleet variance > 0
- [ ] 17.8 Stop the inference container and `POST /api/inference/run` → **503, not 500**, no stack trace, DB unchanged
- [ ] 17.9 Start with `DEPLOYMENT_ENVIRONMENT=production` → both new endpoints 404, `GET /api/elevators` still 200
- [ ] 17.10 Restore DB state after every mutating call
- [ ] 17.11 Create `reports/2026-08-30-step-17-endpoint-testing.md`

## 18. E2E Testing with Playwright MCP — N/A

- [ ] 18.1 **Not applicable.** No file under `frontend/` is touched and no API response shape changes. The dashboard reads the same fields it reads today; only their values change. Recorded as an explicit N/A rather than skipped silently, as `2026-07-17-docker-images-to-ghcr/tasks.md` §7 did

## 19. Update Technical Documentation (MANDATORY)

- [ ] 19.1 `docs/api-spec.yml` — add `POST /api/telemetry/readings`, `GET /api/telemetry/readings`, `POST /api/inference/run` with schemas and error responses
- [ ] 19.2 `docs/data-model.md` — add `TelemetryReading`, and **fix the stale "known feature names" table**, which documents vibration/current/door signals the model has never consumed. State which columns feed the model and which are persisted only
- [ ] 19.3 `docs/backend-standards.md` — the inference-service pattern, the `feature_mapping` shared module, and the new `cd backend && python -m ml.generate_predictions` invocation
- [ ] 19.4 Run `/update-docs` to catch anything missed

## 20. Adversarial Review

- [ ] 20.1 Run `/adversarial-review`, with explicit instruction to verify every **[M]** claim by re-running the mutation rather than trusting the task line
- [ ] 20.2 Address findings, then re-review — each unreviewed batch of fixes on the previous change introduced fresh defects of the class it was fixing
