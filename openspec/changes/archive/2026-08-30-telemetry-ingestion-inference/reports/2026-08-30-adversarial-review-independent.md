# Adversarial Review (independent) — telemetry-ingestion-inference

- **Date**: 2026-08-30
- **Change**: `telemetry-ingestion-inference`
- **Branch**: `feature/telemetry-ingestion-inference` (stacked on `feature/2026-08-28-otel-observability`)
- **Reviewer**: independent session, no prior context on this work
- **Base for the diff**: `git diff feature/2026-08-28-otel-observability..feature/telemetry-ingestion-inference`

## Scope and sources

- `proposal.md`, `design.md`, `tasks.md`, `specs/telemetry-ingestion/spec.md`, `specs/risk-inference/spec.md`
- `CLAUDE.md`, `docs/base-standards.md`, `docs/backend-standards.md`, `docs/data-model.md`,
  `docs/api-spec.yml`, `docs/openspec-tasks-mandatory-steps.md`
- The full branch diff (50 files, +5231 / −130)
- The running compose stack (`backend`, `inference`, `db`, `otel-collector`, `lgtm`), rebuilt-image
  check confirmed the running backend matches the source tree by `md5sum`
- 24 independent mutations of the backend suite, 3 of the inference suite, 3 purpose-written probe
  tests, one live concurrency probe, one live fault-injection probe, one migration up/down probe
- The author's own review (`reports/2026-08-30-adversarial-review.md`) was read **last**, after all
  findings below were formed

Baseline before any mutation: **153 passed** (backend), **7 passed** (inference), `ruff` clean,
dev DB at 100 / 210 / 420 / 0 / 0 with risk-score checksum `2d3eaded7d948dca394034571e88eb5b`.

---

## Verification of the `[M]` mutation claims

The brief said not to trust `tasks.md`. Every `[M]` task was re-mutated from scratch. **All 17
reproduced.** No completion claim in `tasks.md` was found to be false.

| Task | Mutation applied | Result |
|---|---|---|
| 4.3 | drop `recorded_at >= since` from `aggregate_window` | 2 red ✓ |
| 5.5 | `valid = list(batch.readings)` | 3 red ✓ |
| 5.6 | `if not valid:` → `if False:` | 2 red ✓ |
| 5.7 | drop `min_length=1, max_length=MAX_BATCH_SIZE` | 2 red ✓ |
| 6.3 | `if environment != "production":` → `if True:` | 2 red ✓ |
| 9.3 | perturb `Torque__Nm` by 1 % in `golden_vectors.json` | 1 red ✓ |
| 10.4 | `except Exception` + 503 → 500 | 5 red ✓ (incl. `test_a_programming_error_is_not_disguised_as_an_absent_service`) |
| 11.1 | drop `+ KELVIN_OFFSET` from `Air_temperature__K` | 15 red ✓ |
| 11.2 | apply `+ KELVIN_OFFSET` twice to `Process_temperature__K` | 13 red ✓ |
| 11.3 | `[values[name] for name in sorted(values)]` | 6 red ✓ (incl. `test_the_matrix_follows_the_booster_column_order` — the strengthened version does catch it) |
| 11.4 | drop the `in_model_scope` filter | 2 red ✓ |
| 11.5 | `targets = list(in_scope)` | 3 red ✓ |
| 11.6 | run-hours fallback returns a constant | 1 red ✓ |
| 11.7 | each trend branch inverted separately | 1 red each ✓ |
| 11.8 | `UPDATE … SET day_index = day_index - 1` instead of DELETE+INSERT | 1 red ✓, with the predicted `asyncpg UniqueViolationError` |
| 11.9 | drop the `/ total` normalisation | 11 red ✓ |
| 11.10 | delete the `assert_temperatures_are_absolute` call from `run()` | 3 red ✓ (the guard is now genuinely wired) |
| 11.11 | `if total == 0:` → `if False:` | 1 red ✓ |
| 11.12 | `delete_older_than` returns 0 without deleting | 2 red ✓ |

Also independently confirmed: task 3.2 (index DDL really is `… (elevator_id, recorded_at DESC)` and
`… (recorded_at DESC)` in `pg_indexes`, and `alembic check` reports "No new upgrade operations
detected"); task 3.4 (`upgrade head` → `downgrade -1` ×2 → `upgrade head` on a scratch database,
clean); task 7.4 (regenerated `predictions.json` differs from the committed file in
`last_visit_date` only, for exactly 100 of 100 elevators; `golden_vectors.json` regenerates
byte-identical); task 8.5 (nothing under `backend/inference/` imports SQLAlchemy, asyncpg or
`DATABASE_URL`); task 14.2/14.3 (Tempo reports both `elevator-backend` and `elevator-inference`).

**One guard in this change was never mutation-checked and cannot pass one: the advisory lock added
at task 20.0.** See Major 1.

---

## Findings

| Severity | Area | Finding | Evidence | Suggested fix |
|---|---|---|---|---|
| **Major** | Concurrency / toothless guard | The `pg_advisory_xact_lock` that task 20.0 added in response to the author's own review **has no test**. Deleting the `await self._acquire_run_lock()` call leaves the suite fully green. The spec scenario "Two overlapping runs do not double-shift the trend" is asserted nowhere. This is exactly the failure class the change's own mutation rule was written to prevent, and it entered the change *after* the mutation discipline stopped being applied | Replaced the call with `pass`: **153 passed, 0 failed**. The behaviour itself is correct today — two concurrent `POST /api/inference/run` on the live stack serialised (0.183 s vs 0.098 s) and `ELV-002`'s trend went `0,0,0,0,0,0.9994` → `0,0,0,0,0.9994,0.9994`, i.e. one shift — but nothing protects it | **Tests.** An integration test with two overlapping sessions. Then correct the step-16 report's "every guard … verified by breaking it" and the self-review's "every scenario … maps to at least one test" |
| **Major** | Data / spec violation | `aggregate_window` and `list_for_elevator` filter only `recorded_at >= since`, with **no upper bound**, and `delete_older_than` prunes only `recorded_at < cutoff`. A single future-dated reading therefore (a) is accepted by ingest, (b) counts as "inside the 24-hour window" forever, and (c) is never pruned. The elevator is permanently scored from one frozen row and can never be reported as stale — the direct negation of "An in-scope elevator with no readings in the window SHALL be skipped entirely … so that a unit which stopped reporting appears stale rather than suddenly low-risk" | Live stack: one reading for `ELV-002` dated `2099-01-01` → `POST /api/inference/run` returned `scored: 2` and `ELV-002.risk_score = 0.9994`, `pruned_readings: 0`. Reproduced at unit level (probe test, since deleted): a reading dated ~2076 makes `summary.scored == 1` in a run with `now = 2026-08-30` | **Code + tests.** Bound the window at `now` in `aggregate_window`/`list_for_elevator`, and reject `recorded_at` beyond a small future tolerance in `TelemetryReadingInput`. Add the window's upper edge as a spec scenario |
| **Major** | Availability / error handling | **One bad reading stops the whole fleet, with an HTTP 500 and a stack trace.** `TelemetryReadingInput` puts no range constraint on the temperature fields, so a *data* value trips a guard designed to catch a *code* unit error, and `assert_temperatures_are_absolute` aborts the entire run before any elevator is scored. It repeats on every run for as long as the reading sits in the window — permanently, if the reading is also future-dated (Major 2) | Live stack: ingest `{"ambient_temperature_c": -400.0}` for `ELV-003` → 201; then `POST /api/inference/run` → **500 `Internal Server Error`**, full `FeatureBuildError` traceback in the backend log, 0 elevators scored, nothing written. `docs/backend-standards.md` (added by this change) and `specs/risk-inference` both treat "500 with a stack trace" as the thing not to do | **Code + spec.** Validate a plausible Celsius band at ingest, and/or drop the offending elevator from the run instead of failing the fleet; map `FeatureBuildError` to a response with a clean body. Decide and record which of "fail the run" and "skip the row" applies to a *data* fault as opposed to a *code* fault |
| **Major** | Atomicity / toothless guard | The spec scenario "A failure mid-run leaves no partial state — WHEN a run fails **after scoring some elevators** but before completing" is not tested. Both atomicity tests fail *before or at the first* elevator (`BadContributionClient` returns all-zero contributions for every row; the band check fires before the loop), so no test ever writes an elevator and then fails. The rollback itself lives in `get_db`, and both `client` fixtures in `conftest.py` override `get_db` with a generator that neither commits nor rolls back — so the actual mechanism is exercised by no test at all | Read of `tests/unit/test_inference_service.py` (`test_a_mid_run_failure_propagates_instead_of_returning_a_summary`, `test_an_out_of_band_temperature_aborts_before_any_elevator_is_written`) and `tests/conftest.py`. I verified rollback live only for a *pre-loop* failure (`ELV-003` untouched after the 500); I could not verify the partial-loop case | **Tests.** A test where elevator #1 scores and elevator #2 raises, asserting #1 is unchanged after the session rolls back |
| Minor | Retention | The retention prune is skipped whenever a run has no targets: `_run` returns early with `pruned_readings=0` before reaching `delete_older_than`. The requirement says readings beyond the window are deleted "at the end of each inference run", and the case that is skipped — no in-scope elevator reporting — is exactly when old rows most need clearing | Probe test (since deleted): an in-scope elevator with a single 400-day-old reading yields `scored == 0`, `pruned_readings == 0`, and the row survives | **Code.** Prune before the early return |
| Minor | Online/offline drift | The "Online and offline scoring cannot drift" requirement is only partly satisfied. `FEATURE_NAME_MAP`, `FEATURE_MEANS`, `RUN_PARAMS`, `MAX_MOTOR_HOURS`, `format_value`, `risk_level` and `nl_explanation` were extracted, but the two actual *mapping computations* are still duplicated verbatim: the `Type_L`/`Type_M` one-hot and the run-hours → `Tool_wear__min` proxy exist independently in `app/services/inference_service.py` and `backend/ml/generate_predictions.py`. No test compares them, and no test executes the offline generator at all (`grep` for `generate_predictions` in `tests/` and `inference/tests/` returns only docstrings) | `inference_service.py` `_tool_wear_from_run_hours` / `build_feature_row` vs `generate_predictions.py:177-187` | **Code.** Move both into `app/ml/feature_mapping.py` and have `generate_predictions.py` import them |
| Minor | Golden fixture | The golden test is self-referential. `expected_scores` in `golden_vectors.json` is dumped from the same `generate_predictions.py` run that writes `predictions.json`, not read from the committed `predictions.json` — so a regeneration after an unintended change re-baselines the "golden" values silently. The spec says the scorer "SHALL reproduce the **committed** `predictions.json` risk scores". They do agree today (I compared all 70 in-scope: max delta 0.0), so this is latent, not live | `ml/generate_predictions.py` `dump_vectors_path` block; `inference/tests/test_scorer_golden.py` | **Tests.** Assert against `ml/predictions.json` directly, or additionally |
| Minor | Test coverage | **None of the three new endpoints has an HTTP-layer test.** `grep` for `api/telemetry` / `api/inference` in `tests/` hits only `test_production_gating.py`'s 404 assertions. The spec scenarios that are explicitly about status codes — 201 on partial accept, 422 on an all-unknown batch, 422 on >1000, 200-with-empty-list for an unknown elevator, 503 when the scorer is down — are proven only by the manual step-17 report. I re-ran all of them live and they do pass (201 / 422 / 200 `[]` / 503), but a regression in the router layer would be caught by nothing | `grep -rn "api/telemetry\|api/inference" backend/tests/` | **Tests.** Router-level tests via the existing `client` fixture |
| Minor | Artifact drift | `elevators.last_scored_at` and migration `3d92a2ed3fb5` are absent from `proposal.md` and from `tasks.md` §3. The proposal's Impact section still asserts "**Database**: one new table with two indexes. Existing tables unchanged; `elevators` … gain new *rows* during a run, not new columns" — which the change contradicts. `docs/data-model.md` documents the column correctly, so only the OpenSpec artifacts are stale. `base-standards.md` §5 requires artifacts to lead code between `/apply` and `/archive` | `proposal.md` "Impact"; `tasks.md` §3; `alembic/versions/3d92a2ed3fb5_*.py` | **OpenSpec artifacts** |
| Minor | Mandatory steps | The step-16 report is stale and now overstates its own result: it records **151 passed** where the suite is now **153**, and states "Every guard in this change was verified by breaking it … Fifteen mutations in total", which cannot include the advisory lock added afterwards at task 20.0. `docs/openspec-tasks-mandatory-steps.md` §6.2 requires the report to reflect the executed state, and `base-standards.md` §5 requires re-running verification before archiving | `reports/2026-08-30-step-16-unit-tests.md` vs the current suite | **Documentation.** Re-run and regenerate step 16 after the fixes |
| Minor | API documentation | `docs/api-spec.yml` documents 200 / 404 / 502 / 503 for `POST /api/inference/run`. The 500 that Major 3 reaches is undocumented | `docs/api-spec.yml` `/api/inference/run` | **Documentation** (or moot, if Major 3 is fixed in code) |
| Minor | Idempotency | Ingest has no dedup key: nothing constrains `(elevator_id, recorded_at, source)`, and the aggregation is an `AVG`. A retried batch — and change 3 introduces a retrying n8n producer — double-weights the duplicated readings in the score. Neither the spec nor the design states a position on replay | `telemetry_repository.create_many`, `aggregate_window` | **Spec decision, then code** |
| Minor | Task hygiene | Task 19.4 (`/update-docs`) is still `[ ]`, and step N+4 is a mandatory step | `tasks.md` §19 | **Tasks** |
| Question | Locking | `pg_advisory_xact_lock` blocks indefinitely, and the transaction that holds it makes two HTTP calls to the scorer (30 s timeout each) while holding it. A slow or hanging scorer queues every subsequent run behind it with no timeout and no 409. Deliberate? | `inference_service._acquire_run_lock`, `InferenceClient` | **Spec / design note** |
| Question | Trend semantics | The requirement is worded "overwrite index 5 when **the newest existing point** already belongs to today", but the code decides from `elevators.last_scored_at`. Equivalent for a fleet that has only ever been scored by a run, but not for a freshly seeded fleet: `last_scored_at` is NULL while trend index 5 already represents today's seeded score, so the first run of the day shifts the window and drops a real point | `inference_service._apply`, `specs/risk-inference` | **Spec wording**, or accept and document |

Trivia, not findings: an empty untracked `backend/backend/` directory exists in the tree (left as
found); mutation 11.1 turned 15 tests red rather than the 13 recorded on the task line, because
`test_inference_service.py` has grown since that line was written.

---

## Comparison with the author's own review

Read only after the above was complete.

**Reproduced independently**

- The `pg_advisory_xact_lock` fix works. I measured the same serialisation live (0.183 s vs
  0.098 s, one shift of the trend window) that the author reports.
- The all-zero contribution guard exists and is exercised: `if total == 0:` → `if False:` turns
  `test_a_mid_run_failure_propagates_instead_of_returning_a_summary` red.
- The two spot-checked mutations (6.3 production gate, 11.1 Kelvin) reproduce exactly as claimed —
  as do the fifteen the author did not spot-check.
- The statement-volume Question is accurate and correctly parked.

**Wrong or overstated**

- "**Every scenario in both spec files now maps to at least one test**" is **false**, and it is the
  claim that most matters. It fails for at least: "Two overlapping runs do not double-shift the
  trend" (Major 1 — no test, the guard survives deletion), "A failure mid-run leaves no partial
  state" for the *partial* case (Major 4), and every scenario stated as an HTTP status code on the
  three new endpoints (Minor).
- The `recorded_at`-in-the-future item is filed as a **Minor** "follow-up" described as a skewed
  clock that "could **dominate** every subsequent window". That understates it in two ways the
  author did not test: the reading is also **never pruned**, and the effect is not domination but
  the permanent defeat of an explicit `SHALL` — the elevator can never be reported as stale again.
  I raise it to Major on measured evidence.
- The verdict "PASS WITH GAPS in the current state" is not supported by the report's own severity
  rules: the skill defines PASS WITH GAPS as "minors only".

**Missed**

- Major 1 — the fix the author wrote in response to their own review shipped without a test, and
  cannot survive its own mutation rule.
- Major 3 — one out-of-band reading aborts the whole fleet with a 500 and a stack trace, and keeps
  doing so. This is the compound consequence of the author's own Minor (no `recorded_at` /
  temperature validation) meeting their own most-emphasised guard, and neither half was tested
  against the other.
- Minor — the retention prune never runs when the window is empty.
- Minor — `Type_L`/`Type_M` and the tool-wear proxy are still duplicated between the online and
  offline paths, so the "cannot drift" requirement is only half-implemented; no test runs the
  offline generator.
- Minor — the golden fixture is generated by the code it certifies, not read from the committed
  `predictions.json` the spec names.
- Minor — `elevators.last_scored_at` contradicts the proposal's Impact section, and the second
  migration appears in no task.
- Minor — the step-16 report is stale (151 vs 153) and its blanket mutation claim no longer holds.

---

## Verdict

**FAIL**

Four Majors: an untested concurrency guard that its own mutation cannot catch (Major 1), a
window with no upper bound that permanently defeats the staleness requirement (Major 2), a
single-reading fleet-wide abort returning 500 with a stack trace (Major 3), and an atomicity
scenario whose only real case is untested (Major 4). Majors 1 and 4 are test gaps against
behaviour that is correct today; Majors 2 and 3 are measured defects in running code.

**Archiving is not advisable in the current state.** The engineering is otherwise careful and the
mutation record in `tasks.md` is honest — all 17 `[M]` claims reproduced, which is not what the
brief led me to expect — but the two fixes made *after* the mutation discipline lapsed (the
advisory lock, and the atomicity tests) are precisely where the remaining holes are, and the
change's own step-16 report and self-review both assert a coverage completeness that does not hold.

## Recommended next steps (before archive)

1. Fix Majors 2 and 3 in code: bound `aggregate_window`/`list_for_elevator` at `now`, reject
   future-dated readings and implausible temperatures at ingest, and decide whether a bad row skips
   its elevator or fails the run — updating `specs/risk-inference` first, per `base-standards.md` §5.
2. Close Majors 1 and 4 with tests: concurrent-run serialisation, and a mid-loop failure that leaves
   an already-scored elevator unchanged. Mutation-check both.
3. Prune before the early return; move the `Type_L`/`Type_M` and tool-wear derivations into
   `app/ml/feature_mapping.py`; anchor the golden test to `ml/predictions.json`.
4. Add router-level tests for the three new endpoints (201 / 422 / 200-empty / 503).
5. Update `proposal.md` and `tasks.md` §3 for `elevators.last_scored_at` and migration
   `3d92a2ed3fb5`; complete task 19.4; regenerate the step-16 report against the final suite.
6. Register the remaining Minors and both Questions as Notion backlog tasks.
7. Re-review after the fixes — on this change, every unreviewed batch of fixes has introduced a
   fresh defect of the class it was fixing.

---

## Working-tree hygiene

Every mutation was reverted with `git checkout backend/` and re-confirmed against the baseline.
Three probe tests were mounted into the test container and deleted afterwards. `predictions.json`
and `golden_vectors.json` were regenerated for verification and restored from the index. Two scratch
databases (`rev_dg_db`, `rev_chk_db`) and one scratch Docker image were created and removed. The dev
database was mutated by the live probes and restored by `TRUNCATE telemetry_readings, elevators
CASCADE` + `docker compose restart backend`; counts are back to 100 / 210 / 420 / 0 / 0 and the
risk-score checksum is back to `2d3eaded7d948dca394034571e88eb5b`. Final suite: **153 passed**,
inference **7 passed**, `ruff` clean, `git status` clean. Nothing was committed and nothing was
fixed.
