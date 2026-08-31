# Tasks: harden-telemetry-ingest

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/harden-telemetry-ingest` from `main`
- [x] 0.2 Verify current branch with `git branch --show-current`
- [x] 0.3 Confirm `main` is at the merge of #32 (`git log --oneline -1 main`)

## 1. Identity constraint on `telemetry_readings`

- [x] 1.1 Write a **failing** repository test: inserting two readings sharing
      `(elevator_id, recorded_at, source)` leaves exactly one row
      (`tests/integration/test_telemetry_idempotency.py`)
- [x] 1.2 Add `UniqueConstraint("elevator_id", "recorded_at", "source")` as
      `uq_telemetry_readings_identity` to `app/models/telemetry.py`, and document
      in the module docstring why identity is these three columns
- [x] 1.3 Remove the now-redundant `ix_telemetry_readings_elevator_recorded`
      declaration, leaving a comment pointing at the unique index that subsumes it
- [x] 1.4 Write the migration by hand (`down_revision = '3d92a2ed3fb5'`):
      delete duplicates keeping the lowest `id`, create the unique constraint,
      drop the old index
- [x] 1.5 Verify the migration is a no-op on an empty table, and that the
      dedup DELETE runs before the constraint is created
- [x] 1.6 Write the `downgrade()`: drop the constraint, recreate the old index,
      docstring stating deleted rows are not restored
- [x] 1.7 Apply: `alembic upgrade head`, then `alembic downgrade -1`, then
      `alembic upgrade head` again — both directions must run clean
- [x] 1.8 Test 1.1 passes

## 2. Repository: conflict-tolerant insert (TDD)

- [x] 2.1 Write a **failing** test: `create_many` returns the count of rows it
      actually inserted, 0 when every reading is already stored
- [x] 2.2 Write a **failing** test: a stored reading is not overwritten when a
      reading with the same identity and different sensor values is inserted
- [x] 2.3 Write a **failing** test: two readings sharing elevator and timestamp
      but with different `source` are both inserted
- [x] 2.4 Change `create_many` to `pg_insert(...).on_conflict_do_nothing(
      index_elements=[...]).returning(TelemetryReading.id)` and return the
      number of returned ids
- [x] 2.5 Write a **failing** test: aggregating the window after ingesting the
      same batch twice gives the same averages and `reading_count` as after one
- [x] 2.6 Tests 2.1–2.5 pass

## 3. Service: intra-batch dedup and honest counts (TDD)

- [x] 3.1 Write a **failing** test: a batch containing the same identity twice
      persists one row and reports one duplicate
- [x] 3.2 Write a **failing** test: a partially overlapping batch reports
      `accepted` for the new readings and `duplicates_ignored` for the rest
- [x] 3.3 Write a **failing** test: re-submitting an identical batch returns 201
      with `accepted: 0` and `duplicates_ignored` equal to the valid count
- [x] 3.4 ~~Deduplicate within the batch in `TelemetryService.ingest`~~ —
      **written, then removed.** Deleting the pass left every test green: the
      single multi-row `INSERT ... ON CONFLICT DO NOTHING` already skips a row
      conflicting with one inserted earlier in the same statement. Documented
      in `create_many` and in `docs/backend-standards.md` instead (step 7, D)
- [x] 3.5 Set `accepted` from the repository's insert count and
      `duplicates_ignored` from the difference
- [x] 3.6 Verify the existing "batch with zero valid readings → 422" path still
      fires on unknown elevators only, not on an all-duplicate batch
- [x] 3.7 Tests 3.1–3.3 pass

## 4. Schema and response contract

- [x] 4.1 Add `duplicates_ignored: int` to `TelemetryIngestResponseSchema`
- [x] 4.2 Update the docstrings in `schemas/telemetry.py` and
      `services/telemetry_service.py` to state what `accepted` now counts and
      that `batch_id` labels only the rows this request inserted
- [x] 4.3 Write a test asserting a retried batch does not relabel stored rows
      with the new `batch_id`

## 5. Ingest token guard (TDD)

- [x] 5.1 Write a **failing** test: `POST /api/telemetry/readings` without
      `X-Ingest-Token` returns 401 and persists nothing, when a token is
      configured (`tests/unit/test_ingest_auth.py`)
- [x] 5.2 Write a **failing** test: a wrong token returns 401 with a body
      identical to the absent-token response
- [x] 5.3 Write a **failing** test: the correct token is accepted
- [x] 5.4 Write a **failing** test: `POST /api/inference/run` is guarded by the
      same token and starts no run when it is missing
- [x] 5.5 Write a **failing** test: with no token configured, the endpoints
      accept a request with no header
- [x] 5.6 Add `telemetry_ingest_token: str | None` to `app/core/config.py`,
      documenting why this guard is fail-open while the production gate is
      fail-closed
- [x] 5.7 Implement `require_ingest_token` in `app/core/ingest_auth.py` using
      `secrets.compare_digest`
- [x] 5.8 Apply it as a route dependency on the two write endpoints
- [x] 5.9 Log a startup warning in `build_app` when the routers are registered
      with no token configured, and test that the warning is emitted
- [x] 5.10 Tests 5.1–5.5 and 5.9 pass

## 6. The guard in the configuration that actually runs

- [x] 6.1 Add `TELEMETRY_INGEST_TOKEN` to the `backend` service environment in
      `docker-compose.yml`, with a comment explaining it is a local development
      credential and not a secret
- [x] 6.2 Write a test that parses `docker-compose.yml` and asserts the
      `backend` service sets `TELEMETRY_INGEST_TOKEN` to a non-empty value
- [x] 6.3 Confirm `docker-compose.prod.yml` is untouched and still sets
      `DEPLOYMENT_ENVIRONMENT: production`

## 7. Mutation-check every guard added by this change

Each sub-task means: break the implementation, run the suite, confirm it goes
**red**, restore. A guard that survives its own deletion is not tested.

- [x] 7.1 Drop the unique constraint from the migration → idempotency tests red
- [x] 7.2 Replace `on_conflict_do_nothing` with a plain insert → red
- [x] 7.3 Remove the intra-batch dedup → **GREEN**, so the code was deleted
      rather than kept and excused
- [x] 7.4 Return `len(valid)` as `accepted` again → the count tests red
- [x] 7.5 Remove the `require_ingest_token` dependency from each route in turn
      → the 401 tests red for that route
- [x] 7.6 Replace `compare_digest` with `==` → **GREEN** as expected; a timing
      property is not assertable in a unit test, so this one rests on review
      and is recorded in the step 7 report rather than left implied
- [x] 7.7 Delete `TELEMETRY_INGEST_TOKEN` from `docker-compose.yml` → 6.2 red
- [x] 7.8 Record every mutation and its result in
      `reports/2026-08-31-step-7-mutation-checks.md`

## 8. Review and Update Existing Tests (MANDATORY)

- [x] 8.1 Review `tests/unit/test_telemetry_service.py` for tests invalidated by
      the new `accepted` semantics
- [x] 8.2 Review `tests/unit/test_inference_service.py` and
      `tests/unit/test_production_gating.py` for fixtures that now need the
      token header
- [x] 8.3 Review `tests/conftest.py`: decide explicitly whether the suite runs
      with a token configured or not, and document the choice
- [x] 8.4 Update every test the change invalidates, and no others

## 9. Unit Tests and DB State Verification (MANDATORY)

- [x] 9.1 Capture pre-test DB baseline (`telemetry_readings` and `elevators`
      row counts)
- [x] 9.2 Run targeted tests: `pytest tests/unit/test_telemetry_service.py
      tests/unit/test_ingest_auth.py tests/integration/test_telemetry_idempotency.py -v`
- [x] 9.3 Run the full suite with coverage:
      `pytest tests/ -v --cov=app --cov-report=term-missing`
- [x] 9.4 Run `ruff check` (the project does not use `ruff format`; 49 pre-existing
      files fail `format --check`, so running it would report noise, not findings)
- [x] 9.5 Verify post-test DB state matches the baseline
- [x] 9.6 Create `reports/2026-08-31-step-9-unit-tests.md`
- [x] 9.7 Mark complete only after the report exists and the suite passes

## 10. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [x] 10.1 `docker compose build backend` **and `migrate`** — rebuilding the
      backend alone left `migrate` on its old image, so it exited successfully
      having applied nothing and the database was silently unmigrated
- [x] 10.2 Bring up `db`, `backend`, `inference`; run `alembic upgrade head`
- [x] 10.3 `POST /api/telemetry/readings` with a valid token → 201, note
      `accepted` and `duplicates_ignored`
- [x] 10.4 Repeat the identical request → 201, `accepted: 0`, duplicates equal
      to the batch size; confirm the row count in the DB did not change
- [x] 10.5 Same batch with one reading changed → only that one accepted
- [x] 10.6 `POST /api/telemetry/readings` with no header → 401; with a wrong
      header → 401; compare the two bodies
- [x] 10.7 `POST /api/inference/run` with no header → 401; with the token → runs
- [x] 10.8 Run inference twice over a window containing a duplicated batch and
      confirm the score is the one a single ingest produces
- [x] 10.9 Delete the rows created by this testing and confirm the DB is back to
      its pre-test state
- [x] 10.10 Create `reports/2026-08-31-step-10-endpoint-testing.md`

## 11. E2E Testing with Playwright MCP (MANDATORY if frontend changed)

- [x] 11.1 **N/A** — no frontend file is touched and no response the dashboard
      reads changes shape. Record this determination in the step 10 report.

## 12. Update Technical Documentation (MANDATORY)

- [x] 12.1 `docs/api-spec.yml`: add `duplicates_ignored` to the ingest response,
      restate what `accepted` counts, document the `X-Ingest-Token` header and
      the 401 response on both write endpoints
- [x] 12.2 `docs/data-model.md`: document the `TelemetryReading` identity and
      the uniqueness rule
- [x] 12.3 `docs/backend-standards.md`: note the `ON CONFLICT DO NOTHING`
      ingest pattern and the route-dependency guard, if either is a new pattern
      for the project
- [x] 12.4 Run `/update-docs` and act on anything it finds that 12.1–12.3 missed

## 13. Independent Review and Close-out

- [ ] 13.1 Run `/adversarial-review`, fix every finding, and re-run the mutation
      checks in step 7 afterwards — the previous change's fixes introduced fresh
      defects of the class they were fixing in three separate rounds
- [ ] 13.2 `/archive` the change and sync `openspec/specs/telemetry-ingestion/`
- [ ] 13.3 `/commit` and open the PR (merge needs approval)
- [ ] 13.4 Set the Notion task *Make telemetry ingest idempotent before n8n
      starts retrying batches* to Done, and the *X-Ingest-Token* task to Done
      noting that the n8n-side credential wiring moves to change 3
