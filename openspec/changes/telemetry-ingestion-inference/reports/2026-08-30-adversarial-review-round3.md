# Adversarial Review (independent, round 3) — telemetry-ingestion-inference

- **Date**: 2026-08-30
- **Change**: `telemetry-ingestion-inference`
- **Branch**: `feature/telemetry-ingestion-inference` (stacked on `feature/2026-08-28-otel-observability`)
- **Reviewer**: independent session, no prior context on this work
- **Diff base**: `git diff feature/2026-08-28-otel-observability..feature/telemetry-ingestion-inference`
- **Weighted at**: `7074d51`, the unreviewed fix batch (17 files, +1101 / −104)

## Scope and sources

- `proposal.md`, `design.md`, `tasks.md`, `specs/telemetry-ingestion/spec.md`, `specs/risk-inference/spec.md`, `README.md`
- `CLAUDE.md`, `docs/base-standards.md`, `docs/backend-standards.md`, `docs/data-model.md`, `docs/api-spec.yml`, `docs/openspec-tasks-mandatory-steps.md`
- The full branch diff (53 files), read in full for `app/`, `inference/`, `tests/`, `docs/`, compose and migrations
- **22 mutations** of the backend suite, run from a pristine copy of `backend/` mounted into the test container so the working tree was never touched, including one deliberate no-op as a harness control
- Two purpose-written probe scripts against `elevator_test_db` (clock skew, conversion-guard defeat)
- Live probing of the running compose stack: ingest, partial batch, read, two concurrent runs, one-bad-sensor run, all-rows-bad run, backend log inspection
- One offline regeneration of `predictions.json` + `golden_vectors.json` in `elevator-ml:noshap`
- The two prior reports were read **last**, after every finding below was formed

**Baseline reproduced**: 173 backend tests passed, 8 inference tests passed, `ruff` clean, coverage 96%, dev DB at 100 / 210 / 420 / 0 / 0 with checksum `2d3eaded7d948dca394034571e88eb5b`.

---

## Verification of the mutation claims

`tasks.md` was not trusted. Twenty-two mutations were applied independently, each restored and the suite reconfirmed. **All of the guards claimed by `tasks.md` and by `7074d51` are genuinely wired into the code path that runs in production**, with one exception (Minor 1).

| # | Mutation | Result |
|---|---|---|
| M1 | delete `await self._acquire_run_lock()` from `_run` | 1 red — `test_a_run_holds_the_lock_against_another_connection` ✓ |
| M2 | drop `recorded_at <= until` from `aggregate_window` | 1 red ✓ |
| M3 | prune only below `cutoff` (drop the future arm) | 1 red ✓ |
| M4 | drop the Celsius `ge`/`le` bounds from the ingest schema | 2 red ✓ |
| M5 | `_not_from_the_future` → `if False:` | 1 red ✓ |
| M6 | `assert_conversion_is_not_broken` → `if False:` | 5 red ✓ |
| M7 | `out_of_band_row_indices` never flags a row | 8 red ✓ |
| M8 | unregister the `FeatureBuildError` exception handler | 1 red ✓ |
| M9 | skip the prune on the no-targets early return | 1 red ✓ |
| M10 | `_top_features` zero-contribution guard → `if False:` | 2 red ✓ |
| M11 | drop `+ KELVIN_OFFSET` from `Air_temperature__K` | 17 red ✓ |
| **M12** | **`_apply` impact-sum assertion → `if False:`** | **173 passed — guard not exercised ✗** |
| M13 | `scored_today = False` | 1 red ✓ |
| M14 | drop the `in_model_scope` filter | 2 red ✓ |
| M15 | score elevators with no telemetry | 4 red ✓ |
| M16 | production gate → `if True:` | 2 red ✓ |
| M17 | remove `min_length`/`max_length` from the batch | 2 red ✓ |
| M18 | `valid = list(batch.readings)` | 5 red ✓ |
| M19 | `except Exception` + 503 → 500 in the client | 4 red ✓ |
| M20 | `current_trace_id()` always returns `None` | 1 red ✓ |
| M21 | build the matrix in `sorted(values)` order | 6 red ✓ |
| M22 | no-op control | 173 passed (harness restores correctly) |

Independently confirmed as well: the offline script still reproduces the committed artifact — a regeneration differs in `last_visit_date` for 100 of 100 elevators and in **nothing else**, and `golden_vectors.json` regenerates byte-identical; the `migrate` image contains both new revisions and its files match the source by `md5sum`, as do `backend` and `inference`; `openspec validate` passes; `docker-compose.prod.yml` is untouched; no `import shap` remains anywhere.

---

## Findings

| Severity | Area | Finding | Evidence | Suggested fix |
|---|---|---|---|---|
| **Blocker 1** | Security / production gating | **The production gate is fail-open and nothing in the repository ever closes it.** The entire security requirement of this change rests on `settings.deployment_environment == "production"`, which reads `DEPLOYMENT_ENVIRONMENT` and **defaults to `"local"`**. `docker-compose.prod.yml` sets no such variable; it loads `env_file: /etc/elevator/.env`, a file outside the repository that this change neither modifies nor documents — while the same file's other required variables (`BEDROCK_REGION`, `BEDROCK_MODEL_ID`) *are* documented in a comment block right there. Both prior rounds verified the gate by explicitly setting the variable, which proves the branch works and proves nothing about the deployment. On merge to `main`, `deploy.yml` auto-deploys, and unless someone has already added an undocumented line to that host file, `POST /api/telemetry/readings` and `POST /api/inference/run` become **public unauthenticated write endpoints that let anyone inject telemetry and re-score the live fleet** — precisely the outcome `design.md` says the gate exists to prevent | Ran the built backend image with `DEPLOYMENT_ENVIRONMENT` unset: `settings.deployment_environment == 'local'`, and the registered routes include `/api/inference/run` and `/api/telemetry/readings`. `grep -rn DEPLOYMENT_ENVIRONMENT` over the repo finds it in `docker-compose.yml` (`local`, twice), `config.py`, `inference/telemetry.py` and docs — **never in any production artifact**. I cannot inspect `/etc/elevator/.env`, so I state this as unverifiable rather than assume it is set | **Code + docs.** Invert the default so the gate fails closed (register only for an explicitly recognised non-production environment, or gate on a `TELEMETRY_INGEST_ENABLED` flag defaulting to off), **and** document the required `/etc/elevator/.env` line in `docker-compose.prod.yml` alongside the Bedrock block. A typo (`prod`, `Production`) currently also opens the endpoints |
| **Blocker 2** | Spec drift | **`7074d51` changed user-visible behaviour and updated no spec artifact.** The delta specs were last touched by `df46bd4`. `specs/risk-inference` still says the system "SHALL fail the run rather than score outside it" and carries the scenario *"An unconverted temperature is rejected before scoring → the run fails … **no elevator is scored**, and no score, feature or trend point is written."* The shipped code does the opposite for the single-bad-row case: it skips that elevator and scores the rest, returning 200. The same commit added behaviour with **no requirement and no scenario anywhere**: ingest range validation, ingest no-future validation, `skipped_out_of_range`, the `FeatureBuildError` → described-500 mapping, and the prune's future-end arm. `docs/base-standards.md` §5 is explicit: *"Never make code-only fixes between `/apply` and `/archive` without updating the relevant spec artifacts first."* Round 2's recommendation #1 said the same thing. Archiving now syncs specs that describe a system that does not exist | `git log --oneline …/specs/` returns only `df46bd4`, `5eae358`, `1e38eec`, `108837d` — not `7074d51`. Live: one out-of-band reading among four → `{"scored":3,"skipped_out_of_range":1}` with HTTP 200, where the scenario demands a failed run. The abort message also names neither the column nor the raw offending value, which the same scenario requires | **OpenSpec artifacts.** Rewrite the Kelvin requirement to state the two-fault split (some rows = data fault, skip and report; all rows = code fault, abort), add scenarios for the ingest validations, `skipped_out_of_range`, the described 500 and the future-end prune, then re-run verification |
| **Major 1** | Data loss (introduced by the unreviewed batch) | **Ingest accepts readings the very next run silently destroys.** `TelemetryReadingInput` tolerates `recorded_at` up to `now + 5 min` (`MAX_CLOCK_SKEW`), but `aggregate_window` bounds the window at `until=now` and `prune` deletes everything `> future_cutoff` where `future_cutoff = now`. A reading from a producer whose clock is two minutes fast is therefore accepted with a 201, never scored, and permanently deleted on the next inference run. The three bounds were introduced in one commit and do not agree with each other | Probe against `elevator_test_db`: `TelemetryReadingInput` accepts `now + 2 min`; `aggregate_window(now-24h, until=now)` → elevator absent; `prune(cutoff=now-30d, future_cutoff=now)` → **1 row deleted**, 0 surviving | **Code.** Use `now + MAX_CLOCK_SKEW` as the prune's future cutoff (and as the window's upper bound), or drop the skew tolerance from ingest. Whichever is chosen, state it in the spec |
| **Major 2** | Incomplete fix + artifact overclaim | **The read endpoint is still bounded at one end only, and `proposal.md` was edited in the same commit to claim it is not.** Round 2's Major 2 named `list_for_elevator` alongside `aggregate_window`. The fix added an `until: datetime \| None = None` parameter to `list_for_elevator` — and **no caller passes it**. `TelemetryService.list_readings` calls `list_for_elevator(elevator_id, since, limit)`. The parameter is dead code, and `7074d51` amended `proposal.md` to read "`GET /api/telemetry/readings` (windowed query, **bounded at both ends**)". This is the change's signature failure mode once more: a guard added beside the real path rather than on it | `grep -rn "until" backend/` shows the only production caller is `aggregate_window`; coverage reports `telemetry_repository.py:52` (`conditions.append(recorded_at <= until)`) as **never executed** by the 173-test suite | **Code + tests + proposal.** Pass an upper bound from the router (or delete the parameter and correct `proposal.md`); add a test that a future-dated row is absent from the GET response |
| **Major 3** | Weakened guard | **One in-band row disables the fleet-wide Kelvin guard entirely.** `assert_conversion_is_not_broken` aborts only when `len(out_of_band) == len(rows)`. With the conversion removed, a fleet containing a single anomalous row whose stored "Celsius" happens to land in `[200, 400]` no longer aborts: it returns 200, silently reports the rest of the fleet as `skipped_out_of_range`, and scores the anomalous elevator from an unconverted value. The change describes this conversion as "the single highest-risk detail", and its runtime guard is now defeatable by one row of the kind the guard's own test constructs | Probe with `KELVIN_OFFSET` monkeypatched to `0.0`, three elevators (two normal Celsius, one holding a Kelvin-valued reading): **`RUN SUCCEEDED … scored: 1, skipped_out_of_range: 2, rows sent to the model: [300.0]`**. Before `7074d51` this aborted | **Code + spec.** Abort on a majority (or any non-trivial fraction) of rows out of band rather than on all of them, and record the threshold in the requirement |
| **Major 4** | Spec vs code, unresolved from round 2 | **The first run over a freshly seeded fleet shifts the trend window and drops a real point.** The requirement says the system "SHALL overwrite index 5 when **the newest existing point already belongs to today**". The code decides from `elevators.last_scored_at`, which is `NULL` for every seeded elevator, so the first run takes the new-day branch even though index 5 already holds today's seeded score. Round 2 raised this as a Question; `tasks.md` §20.3 does not list it, and neither code nor spec was changed | Live, on the restored baseline: `ELV-001` trend `{0.6,0.65,0.68,0.75,0.78,0.8}` with `last_scored_at IS NULL` → after the run `{0.65,0.68,0.75,0.78,0.8,0.0002}`. The seeded 0.6 is gone and 0.8 is now labelled "yesterday" | **Spec or code.** Either reword the requirement to key on `last_scored_at` and accept the reseed behaviour, or treat `NULL` as "seeded today" |
| **Major 5** | Mandatory verification steps | **The step-16 and step-17 reports no longer describe the code, and step 17 was not re-executed for the behaviour `7074d51` added.** Step 16's coverage table claims `telemetry_repository.py` **100%** (actual 97%, and the missing line is exactly the dead `until` branch of Major 2), `schemas/telemetry.py` 100% (actual 98%), `inference_service.py` 122 stmts / 97% (actual 141 / 96%), total 95% (actual 96%). Step 17's `POST /api/inference/run` sample response has no `skipped_out_of_range` field — an API shape that no longer exists — and the report covers **none** of the new endpoint behaviour: the 422 for an implausible Celsius value, the 422 for a future timestamp, the described 500, the per-elevator skip, or the concurrency serialisation. `tasks.md` §17 was not extended, yet its boxes remain ticked. `docs/openspec-tasks-mandatory-steps.md` §6.2 permits `[x]` only after execution, and §3 requires "every endpoint affected by the change" | Diff of the reports against a fresh `pytest --cov` run and against `app/schemas/inference.py`; `git show --stat 7074d51` shows the step-16 report edited only in its mutation paragraph | **Documentation + tasks.** Re-execute step 17 against the current stack for the new behaviours and regenerate both reports. (I re-ran all of it myself and the runtime behaviour is correct — the gap is in the evidence, not the code) |
| Minor 1 | Untested / unreachable guard | The spec says a run "SHALL assert that sum lies within `[0.99, 1.01]`". That assertion exists at `inference_service.py:341-344`, but **M12 disabled it and all 173 tests still passed**, and coverage confirms line 342 never executes. It is also structurally unreachable: `_top_features` normalises three values and rounds each to 3 dp, so the sum cannot leave `[0.9985, 1.0015]`. `tasks.md` §11.9 mutated the *normalisation*, not the assertion, and read the resulting failure as proof of the assertion | M12 (green), coverage line 342, arithmetic on `round(x, 3)` | **Tests or spec.** Either drive it with a stubbed `_top_features` and mutation-check it, or move the assertion where it can fire (on the pre-rounding values) |
| Minor 2 | Dead code | `inference_service.py:284` (`model_version = None`) is unreachable: `targets` can only become empty after filtering when every row was out of band, which `assert_conversion_is_not_broken` has already raised on | Coverage line 284; control-flow reading | **Code.** Delete the `else` arm or make the invariant explicit |
| Minor 3 | Silent timezone coercion | `_not_from_the_future` rewrites a naive `recorded_at` to UTC (`schemas/telemetry.py:57`, never executed by the suite). A producer sending local wall-clock time has its readings shifted by the UTC offset — potentially outside the window, or into the future where Major 1 deletes them. Nothing rejects or warns | Coverage line 57; the validator body | **Code or spec.** Require an offset, or document the assumption in `api-spec.yml` |
| Minor 4 | Untested branches | `_shift_trend`'s pad and trim arms (lines 403, 405) are never executed by any test, and the pad fills missing history with the *new* score rather than the oldest known one. `format_value`'s `Torque__Nm`, `Tool_wear__min` and `Type_*` arms (`feature_mapping.py:91-101`) are covered by no automated test — only by a manual regeneration of `predictions.json` | Coverage | **Tests** |
| Minor 5 | Round-1 minor never addressed | The all-invalid-batch 422 still interpolates every rejected id: `', '.join(rejected)` over up to 1000 ids. Round 1 filed this as a follow-up; it appears in no backlog note in `tasks.md` | `telemetry_service.ingest` | **Code or backlog** |
| Minor 6 | Round-2 minor never addressed | Ingest still has no dedup key on `(elevator_id, recorded_at, source)` and `aggregate_window` averages, so a retried batch double-weights its readings — and change 3 introduces a retrying n8n producer. Round 2 asked for a spec position; none was taken, in the spec or in `tasks.md` §20.3 | `telemetry_repository.create_many`, `aggregate_window` | **Spec decision, then code** |
| Minor 7 | Round-2 question never addressed | `pg_advisory_xact_lock` blocks indefinitely, and the transaction holding it makes two HTTP calls to the scorer with a 30 s timeout each. A hung scorer queues every subsequent run behind it with no timeout and no 409. Now that the lock is a spec requirement, the unbounded wait deserves a line in the requirement or in `design.md` | `_acquire_run_lock`, `InferenceClient` | **Design note** |
| Minor 8 | Doc inconsistency inside the change | `docs/data-model.md`'s `TelemetryReading` table lists the temperature columns as merely "required" and `recorded_at` with no constraint, while `docs/api-spec.yml` — updated in the same commit — documents `minimum: -60 / maximum: 120` and the no-future rule. Two documents written by one change disagree about the same field | Both files | **Documentation** |
| Question 1 | Duplication | `_top_features` (online) and `_shap_features` (offline) still implement top-3 selection and normalisation independently. They agree numerically today, but their tie-breaking differs (`np.argsort(...)[-3:][::-1]` reverses ties; `sorted(..., reverse=True)` preserves them), so an exact tie would put a different feature first in `nl_explanation` on the two paths. The "cannot drift" requirement enumerates what must be shared and does not include this — deliberate? | `generate_predictions.py:325-345` vs `inference_service.py:169-196` | **Author confirmation** |

---

## Comparison with the two prior rounds

Read only after everything above was formed. Fixes were re-verified by mutation, not taken on trust.

### Genuinely fixed

| Prior finding | Verified how |
|---|---|
| R1/R2 Major — advisory lock shipped with no test | M1: deleting the call from `_run` turns `test_a_run_holds_the_lock_against_another_connection` red. The test drives `run()` and probes from a second connection with `pg_try_advisory_xact_lock`; it is not the toothless helper-call version. Live: two concurrent runs, one trend shift, 6 points each ✓ |
| R2 Major 2 — `aggregate_window` unbounded above, prune one-ended | M2 and M3 each turn a dedicated test red ✓ (but see Major 1 and Major 2 above: the fix is incomplete for the read path and inconsistent with the ingest skew tolerance) |
| R2 Major 3 — one bad reading aborts the fleet with a 500 + traceback | M4–M8 all red. Live: one bad sensor → 200 with `skipped_out_of_range: 1`; all rows bad → described 500, **zero traceback lines in the backend log** ✓ |
| R2 Major 4 — partial-run rollback untested | `test_a_failure_after_the_first_elevator_commits_nothing` drives real `TestSessionLocal` sessions and checks from a fresh one; M10 turns it red ✓ |
| R2 Minor — prune skipped when nothing scored | M9 red ✓ |
| R2 Minor — one-hot and tool-wear duplicated | Both now live in `feature_mapping.py` and are imported by the offline script; my own regeneration confirms the numbers are unchanged ✓ |
| R2 Minor — golden fixture self-certifying | `test_the_golden_fixture_agrees_with_the_committed_predictions` anchors it to `ml/predictions.json` ✓ |
| R2 Minor — no HTTP-layer tests | `tests/integration/test_telemetry_router.py`, 11 tests across all three endpoints ✓ |
| R2 Minor — `last_scored_at` absent from proposal/tasks | Both updated ✓ |
| R2 Minor — api-spec missing the 500 | Documented ✓ |
| R1 Minor — `recorded_at` unbounded in the future | M5 red ✓ |
| R2 Minor — task 19.4 unticked | Ticked, and the docs were genuinely written ✓ |

### Fixed badly or incompletely

- **R2 Major 2 is half-fixed.** `list_for_elevator` got an `until` parameter that nothing passes (Major 2 above), and `proposal.md` was simultaneously edited to claim the endpoint is bounded at both ends. The fix also introduced Major 1, silent deletion of readings ingest had accepted.
- **R2 Major 3's fix changed the contract without touching the spec** (Blocker 2) and weakened the fleet-wide guard to an all-or-nothing condition a single row defeats (Major 3).
- **R2's step-16 staleness Minor was patched, not fixed.** A "superseded in part" note was added and the pass count corrected to 173, but the coverage table was never regenerated and is wrong again — and step 17 has since gone stale in the same way (Major 5).
- **Three round-2 items were simply not carried forward**: dedup/idempotency (Minor 6), the indefinite lock wait (Minor 7), and the trend-semantics Question, which I have raised to Major 4 on live evidence.
- **One round-1 Minor was not carried forward**: the unbounded 422 message (Minor 5).

### What both rounds missed

1. **The production gate is fail-open and is never enabled in the environment it names** (Blocker 1). Both rounds tested the gate by setting `DEPLOYMENT_ENVIRONMENT=production` by hand, which validates the branch and never asks whether anything sets it on the deployed host. Nothing in the repository does, and the default is `"local"`. This is the change's stated headline security control.
2. **The spec artifacts were never updated for the largest behaviour change in the branch** (Blocker 2) — despite round 2 explicitly asking for it and `base-standards.md` §5 mandating it.
3. **A spec-mandated `SHALL assert` that no test exercises and that can never fire** (Minor 1) — the same class of defect as round 2's Major 1, still present, in a guard both rounds walked past because the neighbouring normalisation mutation goes red.

---

## Verdict

**FAIL**

Two Blockers and five Majors. Blocker 1 is the serious one: the change's own security requirement is satisfied only in a test harness, and the artifact that governs production sets nothing, so merging to `main` auto-deploys two unauthenticated write endpoints unless an undocumented line already exists in a host file no one in this repository can see. Blocker 2 means archiving would sync specs that contradict the shipped code and omit five behaviours it now has. Major 1 and Major 2 are, again, defects inside the batch of fixes that closed the previous round's defects — the third consecutive time that has happened on this change.

The engineering underneath remains careful: 21 of 22 mutations turned the suite red on the correct tests, the runtime behaviour I exercised live was correct in every case, the advisory lock and the partial-rollback tests are now real, and the offline generator still reproduces the committed artifact exactly.

**Archiving is not advisable in the current state.**

## Recommended next steps (before archive)

1. **Close the production gate properly**: fail closed by default, and document the required `/etc/elevator/.env` entry in `docker-compose.prod.yml` beside the Bedrock block. Verify against an image with the variable *unset*, not set.
2. **Update `specs/risk-inference` and `specs/telemetry-ingestion` first**, then re-verify: the two-fault split for out-of-band rows, the ingest range and no-future rules, `skipped_out_of_range`, the described 500, and the future-end prune.
3. **Reconcile the three time bounds** (ingest skew tolerance, window upper bound, prune future cutoff) so no accepted reading can be silently deleted, and add the test.
4. **Finish the read-path bound** — pass `until` from the router with a test, or delete the parameter and correct `proposal.md`.
5. **Make the all-rows abort a majority abort**, and mutation-check it with one in-band row present.
6. Decide Major 4 (seeded-fleet trend shift) in spec or in code.
7. Re-execute step 17 for the new behaviours and regenerate both mandatory reports.
8. Register Minors 5–8 and Question 1 as Notion backlog tasks rather than letting a fourth round rediscover them.
9. **Re-review after this batch.** Three for three so far.

## Working-tree hygiene

Every mutation ran against a copy of `backend/` in the session scratchpad, mounted into the test container; the repository working tree was never modified. The two probe scripts touched only `elevator_test_db` and deleted their own rows. The offline regeneration ran against a second scratch copy and its `predictions.json` / `golden_vectors.json` were restored inside that copy, never in the repository. The dev database was mutated by the live probes and restored with `TRUNCATE telemetry_readings, elevators CASCADE` + `docker compose restart backend`: counts are back to **100 / 210 / 420 / 0 / 0** and the risk-score checksum is back to **`2d3eaded7d948dca394034571e88eb5b`**. Final state: 173 backend tests passed, 8 inference tests passed, `ruff` clean, **`git status` clean apart from this report**. Nothing was committed and nothing was fixed.

Noted and left as found: an untracked, root-owned `backend/backend/.pytest_cache/` directory (invisible to `git status` because pytest writes its own `.gitignore`), and a regenerated `backend/.coverage` — both gitignored build artefacts.
