# Adversarial Review (independent, round 4) — telemetry-ingestion-inference

- **Date**: 2026-08-30
- **Change**: `telemetry-ingestion-inference`
- **Branch**: `feature/telemetry-ingestion-inference` (stacked on `feature/2026-08-28-otel-observability`)
- **Reviewer**: independent session, no prior context on this work
- **Diff base**: `git diff feature/2026-08-28-otel-observability..feature/telemetry-ingestion-inference` (58 files, +6753 / −142)
- **Weighted at**: `712e4f4`, round 3's unreviewed fix batch (17 files, +527 / −14)

## Scope and sources

- `proposal.md`, `design.md`, `tasks.md`, `README.md`, both delta specs
- `CLAUDE.md`, `docs/base-standards.md`, `docs/backend-standards.md`, `docs/data-model.md`,
  `docs/api-spec.yml`, `docs/openspec-tasks-mandatory-steps.md`, `openspec/specs/*`
- The full branch diff, read in full for `app/`, `inference/`, `tests/`, `docs/`, migrations
- **Deployment artifacts as primary evidence**: `docker-compose.yml`, `docker-compose.prod.yml`,
  `docker-compose.cloud.yml`, `.github/workflows/{ci,build-images,deploy}.yml`, `nginx/prod.conf`,
  `scripts/dev-setup.sh`, both Dockerfiles, `e2e/playwright.config.ts`
- **33 mutations** of the backend suite, run against a copy of `backend/` in the session scratchpad
  mounted into the test container — the repository working tree was never modified
- Two purpose-written probe tests (transport-fault taxonomy; route-level rollback with real commit
  semantics), deleted afterwards
- A live probe of the **built** backend image with `DEPLOYMENT_ENVIRONMENT` unset
- FastAPI 0.115.6 source inspection to settle where the dependency exit stack sits relative to the
  exception middleware
- The three prior reports were read **last**, after every finding below was formed

**Baseline reproduced**: 180 backend tests passed, 8 inference tests passed, `ruff` 0.8.4 clean,
coverage 96%, `openspec validate` passes, dev DB at 100 / 210 / 420 / 0 with checksum
`2d3eaded7d948dca394034571e88eb5b`.

---

## Verification of the mutation claims

`tasks.md` was not trusted. Thirty-three mutations were applied independently, each restored and the
suite reconfirmed. **Thirty went red on the right tests. Three survived.**

| # | Mutation | Result |
|---|---|---|
| M1 | production gate `if environment != "production":` → `if True:` | 3 red ✓ |
| M2 | drop `+ KELVIN_OFFSET` from `Air_temperature__K` | 19 red ✓ |
| M3 | delete the `assert_conversion_is_not_broken` call from `_run` | 4 red ✓ |
| M4 | `out_of_band_row_indices` returns `[]` unconditionally | 8 red ✓ |
| M5 | delete `await self._acquire_run_lock()` from `_run` | 1 red ✓ |
| M6 | `valid = list(batch.readings)` | 5 red ✓ |
| M7 | prune drops its future arm (`< cutoff` only) | 2 red ✓ |
| M8 | `list_readings` stops passing `until=` | 1 red ✓ |
| M9 | seed stops setting `last_scored_at` | 1 red ✓ |
| M10 | `aggregate_window` drops `recorded_at >= since` | 3 red ✓ |
| M11 | `aggregate_window` drops `recorded_at <= until` | 2 red ✓ |
| M12 | build the matrix in `sorted(values)` order | 6 red ✓ |
| M13 | drop the `in_model_scope` filter | 2 red ✓ |
| M14 | `targets = list(in_scope)` (score elevators with no telemetry) | 5 red ✓ |
| M15 | `_top_features` zero-contribution guard → `if False:` | 2 red ✓ |
| M16 | drop the `/ total` normalisation | 14 red ✓ |
| M17 | same-day trend branch made to shift | 2 red ✓ |
| M18 | new-day trend branch made to overwrite | 1 red ✓ |
| M19 | remove `min_length`/`max_length` from the batch field | 2 red ✓ |
| M20 | drop the Celsius `ge`/`le` bounds from the ingest schema | 2 red ✓ |
| M21 | `_not_from_the_future` → `if False:` | 1 red ✓ |
| M22 | `current_trace_id()` never returns `None` | 1 red ✓ |
| M23 | client `except Exception` + 503 → 500 | 1 red ✓ |
| M24 | `pruned = 0` (skip the prune call) | 1 red ✓ |
| M25 | router `return InferenceRunResponseSchema(...)` → `raise` | 1 red ✓ |
| M26 | `list_readings` return → `raise` | 3 red ✓ |
| M27 | rename `RunSummary.pruned_readings` → `pruned_rows` | 21 red ✓ |
| M28 | `assert_conversion_is_not_broken`'s all-rows condition → `if False:` | 5 red ✓ |
| M29 | `build_feature_row` never reports a missing feature | 1 red ✓ |
| M30 | `conftest.py` stops declaring `DEPLOYMENT_ENVIRONMENT=local` | 13 red ✓ |
| **M31** | **`os.getenv("DEPLOYMENT_ENVIRONMENT", DEFAULT)` → `os.getenv(..., "local")`** | **180 passed — guard not exercised ✗** |
| **M32** | **`_apply`'s impact-sum assertion → `if False:`** | **180 passed — guard not exercised ✗** |
| **M33** | **`_not_from_the_future`'s naive-datetime coercion → `raise`** | **180 passed — path never taken ✗** |

Also independently confirmed: the built `…-backend:latest` image byte-matches the source tree under
`app/`; with `DEPLOYMENT_ENVIRONMENT` unset that image reports
`settings.deployment_environment == 'production'`, returns **404** on all three gated routes, **200**
on `/api/elevators` and `/health`, and its `/openapi.json` lists only the five pre-existing paths;
`openspec validate` passes; `docker-compose.prod.yml` remains free of an `inference` service; the
inference image carries no SQLAlchemy, asyncpg or `DATABASE_URL`; `ruff==0.8.4` (the pinned version,
not a newer one) is clean across `backend/`.

---

## Findings

| Severity | Area | Finding | Evidence | Suggested fix |
|---|---|---|---|---|
| **Major 1** | Security / toothless guard | **Round 3's Blocker fix has no regression guard, in the one place the regression already happened.** The behaviour is correct — I verified it on the built image with the variable unset — but reverting the *one line that makes it correct* is invisible to the suite. `config.py` reads `os.getenv("DEPLOYMENT_ENVIRONMENT", DEFAULT_DEPLOYMENT_ENVIRONMENT)`; changing that default back to `"local"` — literally the bug round 3 found — leaves **180 passed**. The two tests written to cover it do not: `test_the_default_environment_is_fail_closed` asserts the *constant*, and `test_build_app_with_no_argument_gates_off_when_the_variable_is_unset` **monkeypatches `settings.deployment_environment` to that constant**, so it tests the gate given a value, never the env-var read that supplies it. The spec scenario "*An unconfigured deployment environment is treated as production*" is therefore verified by nothing. This is the fifth instance in this change of a guard tested beside the real path rather than on it, and it is on the change's headline security control | M31: 180 passed, 0 failed. Read of `tests/unit/test_production_gating.py:73-102`. `tasks.md` §20.5's verification ("the built image with the variable unset was verified to return 404") was a **manual probe**, not a suite guard — and manual probes are what rounds 1 and 2 also relied on for this control | **Tests.** Assert the env read itself: a subprocess (or `importlib.reload` with `DEPLOYMENT_ENVIRONMENT` popped from `os.environ`) that imports `app.core.config` and asserts `settings.deployment_environment == "production"`, then mutation-check it. The change's own `[M]` rule requires this before the task is complete |
| **Major 2** | Availability / spec violation | **A mid-request disconnect from the scorer produces HTTP 500 with a traceback, which the spec forbids outright.** `InferenceClient` catches only `httpx.ConnectError` and `httpx.TimeoutException`. Three other `httpx.TransportError` subclasses — `RemoteProtocolError` (peer closed the connection mid-response), `ReadError`, `WriteError` — escape uncaught and become an unhandled 500. `specs/risk-inference`: the backend "SHALL translate a connection failure or timeout into HTTP 503 — **never HTTP 500 and never a stack trace** — because the service is deliberately absent in production". The reachable trigger is not exotic: the `inference` service runs under `mem_limit: 512m`, and an OOM kill, a container restart or a uvicorn worker death **during** a run yields exactly `RemoteProtocolError`. Task 17.8 tested only the service being down *before* the call, which is the one transport fault that is a `ConnectError` | Probe test through `httpx.MockTransport`: `RemoteProtocolError → RemoteProtocolError` (uncaught), `ReadError → ReadError` (uncaught), `WriteError → WriteError` (uncaught), `PoolTimeout → HTTPException 503` ✓. `tests/unit/test_inference_client.py` covers only `ConnectError`, `ReadTimeout`, `ConnectTimeout` | **Code + tests.** Catch `httpx.TransportError`, which is the exact superclass of every "cannot reach / lost the service" fault and still excludes programming errors — `test_a_programming_error_is_not_disguised_as_an_absent_service` (a `ValueError`) continues to pass. Add the three variants to the client tests |
| **Major 3** | Mandatory verification steps | **The step-16 report's coverage table is stale again — every row of it — and `tasks.md` §20.6 claims it was refreshed.** Round 3 raised this as its Major 5. `git show --stat 712e4f4` shows the step-16 report changed by **4 lines**: the pass counts. The coverage table was not regenerated and now misstates all ten modules. `docs/openspec-tasks-mandatory-steps.md` §6.2 permits `[x]` only after execution; `base-standards.md` §5 requires re-running verification before archiving. Third consecutive round in which this exact artifact is found not to describe the code, and the second time after a claimed refresh | Measured (`pytest --cov=app`) vs the report: `inference_service.py` **142/5/96%** vs claimed 122/4/97%; `telemetry_service.py` **32/1/97%** vs 32/2/94%; `inference_client.py` **33/3/91%** vs 33/5/85%; `telemetry_repository.py` **30** stmts vs 27; `schemas/telemetry.py` **51/1/98%** vs 40/0/100%; `schemas/inference.py` **11** vs 10; `routers/inference.py` **1 miss / 94%** vs 3/81%; `routers/telemetry.py` **0 miss / 100%** vs 4/80%; `main.py` **51** stmts vs 43; `feature_mapping.py` **78%** vs 72%. The narrative "Both routers sit at the 80% threshold; the uncovered lines are the FastAPI dependency-provider bodies" is also now false | **Documentation.** Regenerate the table from an actual run. Also update the "Superseded in part" note, which still names only rounds 1 and 2 and its "Fifteen mutations" figure |
| Minor 1 | Spec `SHALL` exercised by nothing — **carried forward unaddressed from round 3 (its Minor 1)** | `specs/risk-inference` says a run "SHALL assert that sum lies within `[0.99, 1.01]`". Disabling that assertion leaves the whole suite green, and it remains structurally unable to fire: `_top_features` normalises three magnitudes and rounds each to 3 dp, so the sum cannot leave `[0.9985, 1.0015]`. §20.5 does not mention this finding at all — it was neither fixed nor recorded as declined | M32: 180 passed. Coverage: `inference_service.py:351` never executes | **Tests or spec.** Assert on the pre-rounding values where it can fire, or drive it with a stubbed `_top_features` — then mutation-check. Or downgrade the `SHALL` to describe what the normalisation actually guarantees |
| Minor 2 | Round-3 Major silently dropped | Round 3's **Major 3** (one in-band row defeats the fleet-wide Kelvin abort, because `assert_conversion_is_not_broken` fires only when `len(out_of_band) == len(rows)`) appears nowhere in §20.5, and the spec was rewritten in the same commit to **codify** the all-or-nothing rule. My own analysis is that the residual risk is now small — ingest bounds Celsius to `[-60, 120]`, so a correctly-converted row always lands in `[213, 393] ⊂ [200, 400]`, and defeating the abort needs a hand-inserted row of exactly the wrong magnitude co-occurring with a code fault — so the decision is defensible. But it was taken silently. A corollary nobody has written down: with the ingest bounds in place, `skipped_out_of_range` and the "one row out of band skips that elevator only" scenario are **unreachable through any API path**, and exist only as a second line of defence against direct database writes | Read of `inference_service.py:159`, `schemas/telemetry.py:15-16`; §20.5 lists 2 Blockers + 3 Majors against round 3's 2 + 5 | **Design + spec.** Record the decision and the reasoning in `design.md`, and say in the requirement that the per-row skip guards direct writes rather than the ingest path |
| Minor 3 | Dead code — **carried forward from round 3 (its Minor 2)** | `inference_service.py:291` (`model_version = None`) is unreachable: `targets` empties after filtering only when every row is out of band, which `assert_conversion_is_not_broken` has already raised on | Coverage line 291; control-flow reading | **Code.** Delete the arm or make the invariant explicit |
| Minor 4 | Silent timezone coercion — **carried forward from round 3 (its Minor 3)** | `_not_from_the_future` rewrites a naive `recorded_at` to UTC. No test takes that path (M33 survives), and the assumption is documented nowhere: `api-spec.yml`'s `recorded_at` description mentions only the no-future rule. A producer posting `"2026-08-30T12:00:00"` in local wall-clock time has every reading silently shifted by its UTC offset — potentially out of the window, or into the future where the prune deletes it. n8n, the producer change 3 introduces, is exactly the kind of client that emits offset-less timestamps | M33: 180 passed. Coverage `schemas/telemetry.py:57` | **Tests + docs.** A test for the naive case, and one line in `api-spec.yml` stating that a missing offset is read as UTC (or reject offset-less timestamps outright) |
| Minor 5 | Blast radius of the inverted default not propagated | `backend/inference/telemetry.py:50` still defaults `DEPLOYMENT_ENVIRONMENT` to `"local"` while the backend now defaults to `"production"`. Harmless today (the scorer is dev-only and compose sets the variable), but the two halves of the same distributed trace would disagree about `deployment.environment.name` for anyone running the scorer without it | `grep -rn DEPLOYMENT_ENVIRONMENT` | **Code.** Match the backend's fail-closed default, or state in the docstring why this service does not need one |
| Minor 6 | Stale precondition created by this change | `app/core/telemetry.py:246-251` guards `HTTPXClientInstrumentor` behind `find_spec("httpx")` with a comment reading "*httpx is not a runtime dependency yet — it arrives with the inference change*". This **is** the inference change: `httpx==0.28.1` moved into `requirements.txt`. The branch is now dead and the comment false | `backend/requirements.txt:12` vs `app/core/telemetry.py:246` | **Code.** Remove the guard (or keep it and correct the comment to say why) |
| Minor 7 | Documented local workflow now silently broken | `docs/openspec-tasks-mandatory-steps.md` §3 tells the agent to start the backend for manual endpoint testing with `cd backend && uvicorn app.main:app --reload`. With the inverted default that invocation now returns **404** for all three endpoints this change adds, with no message explaining why. Nothing in `docs/dev-workflow.md`, `docs/backend-standards.md` or the change's own docs tells a non-Docker local runner to set `DEPLOYMENT_ENVIRONMENT=local` — and `dev-workflow`'s Track A is explicitly the non-Docker track | The doc line; `build_app()`; verified live on the built image | **Documentation.** One line in `backend-standards.md`'s gating bullet and in the mandatory-steps command |
| Minor 8 | Task claim not matched by the tree | Task 2.2 — "Export it from `app/models/__init__.py` so `Base.metadata` sees it in tests" — is ticked, but `app/models/__init__.py` is **0 bytes**. The table reaches `Base.metadata` only through the transitive import chain `conftest → app.main → routers.telemetry → services → models.telemetry`; it works, but not for the stated reason, and it would break silently if that chain ever changed | `wc -c backend/app/models/__init__.py` → 0 | **Tasks (correct the claim) or code (do the export)** |
| Minor 9 | Gate is typo-sensitive — **carried forward from round 3, unrecorded** | Round 3's Blocker 1 noted that "`prod`, `Production`" also opens the endpoints and suggested an allow-list of recognised non-production values. The fix inverted the default but kept the exact, case-sensitive, unstripped `!= "production"`. The residual risk is now much smaller — `docker-compose.prod.yml`'s `environment:` block sets it explicitly and **overrides `env_file`**, which I confirmed against the compose precedence rules — but the suggestion was neither adopted nor recorded as declined | `app/main.py:82`; `docker-compose.prod.yml:26-37` | **Design note**, or an allow-list |
| Minor 10 | Round-1/round-3 minor still open | The all-invalid-batch 422 still interpolates every rejected id (`', '.join(rejected)` over up to 1000 ids). Raised by round 1 and again by round 3's Minor 5; still no cap and no backlog note in `tasks.md` | `telemetry_service.ingest` | **Code or backlog** |
| Minor 11 | Round-2/round-3 minor still open | Ingest still has no dedup key on `(elevator_id, recorded_at, source)`, and `aggregate_window` averages — a retried batch double-weights its readings, and change 3 introduces a retrying n8n producer. Rounds 2 and 3 both asked for a spec position; none is stated anywhere. (Impact is low for an *identical* replay — the average is unchanged and only `readings_considered` inflates — but that is the argument, and it is not written down) | `create_many`, `aggregate_window` | **Spec decision, then code or backlog** |
| Minor 12 | Round-3 minor still open, verbatim | `docs/data-model.md`'s `TelemetryReading` table still lists the temperature columns as merely "required" and `recorded_at` as "required, tz-aware" with no future constraint, while `docs/api-spec.yml` documents `minimum: -60 / maximum: 120` and the no-future rule. Round 3's Minor 8 named this exact disagreement | Both files | **Documentation** |
| Minor 13 | Round-3 minor still open | `_shift_trend`'s pad and trim arms (`inference_service.py:412,414`) and `format_value`'s `Torque__Nm`, `Tool_wear__min` and `Type_*` arms (`feature_mapping.py:91-101`) are executed by no automated test | Coverage | **Tests** |
| Minor 14 | Report self-contradiction | The step-17 re-run says the gate was tested with the variable unset because that is "the state `docker-compose.prod.yml` actually produces, since it sets the variable nowhere" — which the same commit made false by adding `DEPLOYMENT_ENVIRONMENT: production` to that file. Testing unset is still the right test; the justification is stale | `reports/2026-08-30-step-17-endpoint-testing.md` vs `docker-compose.prod.yml:35` | **Documentation** |
| Minor 15 | Standards omit the round-3 lesson | `docs/backend-standards.md` gained "gate at **registration**, not inside the handler", which was never the failure. The failure was the *default*, and the generalisable rule — a security-relevant configuration default must be fail-closed, and must be verified with the variable unset — lives only in a `config.py` comment and in one delta spec. This change wrote that section of the standards, so it should carry the lesson that cost the most | `docs/backend-standards.md` "Security Basics" | **Documentation** |
| Minor 16 | Working-tree litter | A root-owned, untracked `backend/backend/.pytest_cache/` directory sits in the tree, invisible to `git status` because pytest writes its own `.gitignore`. Round 3 noted it and left it; it is still there. Left as found | `ls -la backend/` | **Housekeeping** |
| Question 1 | Round-3 Question 1, unanswered | `_top_features` (online) and `_shap_features` (offline) still select and normalise the top three independently, with different tie-breaking (`np.argsort(...)[-3:][::-1]` reverses ties, `sorted(..., reverse=True)` preserves them), so an exact tie orders `nl_explanation` differently on the two paths. The "cannot drift" requirement enumerates what must be shared and excludes this. Deliberate? | `generate_predictions.py` vs `inference_service.py:170-197` | **Author confirmation** |
| Question 2 | Round-2/round-3 question, half-answered | `pg_advisory_xact_lock` blocks indefinitely, and the transaction holding it makes two HTTP calls to the scorer at 30 s each. The spec now says "the second waits for the first to complete"; the *unbounded* wait behind a hung scorer is explained only in a code docstring, not in `design.md` | `_acquire_run_lock`, `InferenceClient` | **Design note** |
| Question 3 | Suite environment declaration is ambient-overridable | `conftest.py` uses `os.environ.setdefault("DEPLOYMENT_ENVIRONMENT", "local")`. A developer with `DEPLOYMENT_ENVIRONMENT=production` exported in their shell gets 13 confusing failures rather than a clear message. Deliberate (so CI can override), or worth an explicit assertion? | `tests/conftest.py:10`; M30 shows the line is load-bearing (13 red) | **Author confirmation** |

---

## Verified as genuinely working (not taken on trust)

These were checked because they are the load-bearing claims, and each could have been wrong.

- **The production gate is really closed in the artifact that deploys.** The built image, run with
  `DEPLOYMENT_ENVIRONMENT` unset on the compose network: `POST /api/telemetry/readings` → 404,
  `GET /api/telemetry/readings` → 404, `POST /api/inference/run` → 404, `GET /api/elevators` → 200,
  `GET /health` → 200, and `/openapi.json` lists only the five pre-existing paths. Round 3's Blocker
  1 is fixed **in behaviour**; only its regression guard is missing (Major 1).
- **Atomicity holds through the real HTTP path**, not just at the service layer. I read FastAPI
  0.115.6's `get_request_handler` and confirmed the dependency `AsyncExitStack` is entered *inside*
  the route handler and therefore inside `ExceptionMiddleware` — so an exception unwinds `get_db`
  (skipping `await session.commit()`) *before* the `FeatureBuildError` handler converts it to a
  response. Then I proved it: a probe driving `POST /api/inference/run` against the real app with a
  real committing session returned **500 with the described detail** and left the elevator at
  `last_scored_at=None`, `risk_score=0.4`, `nl_explanation='seeded'`. The existing test suite proves
  this only at the session level, so this was worth confirming independently.
- **Round 3's Major 1 (clock-skew data loss)** is completely fixed: one `MAX_CLOCK_SKEW` shared by
  ingest, `aggregate_window` and `prune`, with both directions mutation-covered (M7, M11).
- **Round 3's Major 2 (dead `until` parameter)** is completely fixed: `list_readings` passes it,
  `proposal.md` is now accurate, and M8 turns the new test red.
- **Round 3's Major 4 (seeded fleet loses a trend point)** is completely fixed: `seed.py` records
  `last_scored_at`, M9 turns `test_seeding_records_when_the_fleet_was_scored` red, and
  `test_a_fleet_scored_earlier_today_has_its_last_point_overwritten` asserts index 0 survives.
- **Round 3's Blocker 2 (spec drift)** is substantially fixed. All five behaviours it named now have
  requirements or scenarios: ingest range validation, no-future validation, `skipped_out_of_range`,
  the described 500, and the shared skew tolerance. One residual gap: the prune now also deletes
  rows **beyond** the skew tolerance, which is tested but stated in no requirement — the spec says
  only "delete readings older than a configurable retention window".
- The 28 other mutations listed above, including every guard round 2 and round 3 verified.

---

## Comparison with the three prior rounds

Read only after everything above was formed. Every claimed fix was re-verified by mutation or probe.

### Genuinely and completely fixed

Round 3's **Major 1** (clock skew), **Major 2** (dead `until`), **Major 4** (seeded-fleet trend) and
**Major 5** for step 17 specifically; round 2's Majors 1–4 and its prune, duplication, golden-fixture
and HTTP-layer-test minors, all of which round 3 had already confirmed and which I re-confirmed by
mutation (M5, M8, M12, M14, M16, M24, M26). Round 3's **Blocker 1** is fixed in behaviour, and its
documentation half — an explicit line in `docker-compose.prod.yml` — is done well: the value sits in
`environment:`, which overrides `env_file`, so an out-of-repo `.env` cannot reopen the gate.

### Fixed incompletely

- **Blocker 1's regression guard does not exist** (Major 1). The fix is correct and the test that
  claims to cover it monkeypatches past the line that makes it correct. Round 3's own recommendation
  — "Verify against an image with the variable *unset*" — was honoured as a manual probe and never
  encoded, which is the same category of evidence rounds 1 and 2 relied on and that round 3 rejected.
- **Blocker 2** left one behaviour (the prune's future arm) tested but unspecified.
- **Major 5 was fixed for step 17 and not for step 16** (Major 3). The step-16 coverage table has now
  been found stale by rounds 2, 3 and 4.

### Carried forward without being fixed or recorded

Round 3's **Major 3** (Minor 2 above) and its **Minors 1, 2, 3, 4, 5, 6, 7, 8** and **Question 1**
are all still open. `tasks.md` §20.5 addresses 5 of round 3's 7 Blocker/Major findings and none of
its 8 Minors; round 3's recommendation #8 — "*Register Minors 5–8 and Question 1 as Notion backlog
tasks rather than letting a fourth round rediscover them*" — has no trace in the repository, and a
fourth round has now rediscovered them. I cannot see Notion and do not claim they were not filed
there; I claim only that nothing in the repository records it.

### What all three rounds missed

1. **The transport-fault taxonomy** (Major 2). Three rounds tested the scorer being *absent* and
   never the connection *breaking*. `RemoteProtocolError`, `ReadError` and `WriteError` all produce
   the 500-with-a-traceback that the spec, `design.md` and `backend-standards.md` each name as the
   thing not to do — and the service runs under a memory limit that makes an OOM kill mid-request a
   realistic trigger.
2. **The fail-closed default is a guard whose own mutation nobody ran** (Major 1). Round 3 found the
   bug by reading deployment artifacts; the fix was verified the same way rounds 1 and 2 verified the
   original — by hand, against a configured environment — and the `[M]` rule at the top of `tasks.md`
   was not applied to it.
3. **Blast radius of the inverted default** (Minors 5 and 7): the scorer's own default was left at
   `local`, and the project's documented non-Docker local run now 404s the change's own endpoints
   with no explanation.
4. **A precondition this change invalidated elsewhere** (Minor 6): moving `httpx` into
   `requirements.txt` made a guard and a comment in `app/core/telemetry.py` false.

The engineering underneath remains careful — 30 of 33 mutations turned the suite red on the right
tests, the live behaviour was correct in every probe I ran, and the two Blockers from round 3 are
genuinely closed in the running system. What has not changed across four rounds is the *shape* of
what is left: a control that works, tested somewhere other than where it runs.

---

## Verdict

**FAIL**

Three Majors. Major 2 is a defect in running code and a literal violation of a `SHALL` in
`specs/risk-inference`. Major 1 is a test gap, but on the one control whose absence would have
published two unauthenticated write endpoints to a stack that auto-deploys on merge — and it is a
gap of exactly the kind that let the original bug survive two reviews. Major 3 is the third
consecutive failure of the same mandatory artifact, the second after a claimed refresh.

No Blockers: I could not reproduce any incorrect security behaviour. The gate holds in the built
image with nothing configured, `docker-compose.prod.yml` states it explicitly in the block that wins
over `env_file`, and the run is atomic through the real request path.

**Archiving and merging are not advisable in the current state.** Major 2 should be fixed in code
before merge; Majors 1 and 3 are cheap and should be closed before archive, because archiving syncs
a spec whose fail-closed scenario nothing verifies and a report that does not describe the code.

## Recommended next steps (before archive)

1. **Catch `httpx.TransportError`** in `InferenceClient` and add the three uncovered variants to
   `test_inference_client.py`. Mutation-check.
2. **Test the env read itself**: import `app.core.config` with `DEPLOYMENT_ENVIRONMENT` unset and
   assert `"production"`. Mutate `config.py`'s `os.getenv` default to `"local"` and confirm red.
   This is the one guard in the change that its own `[M]` rule has never been applied to.
3. **Regenerate the step-16 coverage table** from a real run, and update its superseded-note.
4. Record decisions rather than dropping findings: round 3's Major 3 (all-rows abort), Minors 1–8
   and Question 1 either get a fix, a spec line, or an explicit "considered and declined, because…"
   in `design.md` / `tasks.md`. Nine open items surviving two rounds unrecorded is the process
   defect underneath the technical ones.
5. Add a requirement for the prune's future arm, and one line to `api-spec.yml` about naive
   `recorded_at` being read as UTC.
6. One line in `backend-standards.md` and in `openspec-tasks-mandatory-steps.md` §3 telling a
   non-Docker local run to set `DEPLOYMENT_ENVIRONMENT=local`, and the fail-closed-defaults rule in
   Security Basics.
7. **Re-review the fix batch.** Four for four: every unreviewed batch on this change has shipped a
   fresh defect of the class it was fixing, and this round's Major 1 is that pattern applied to
   round 3's own fix.

## Working-tree hygiene

Every mutation ran against a copy of `backend/` in the session scratchpad, mounted into the test
container; the repository working tree was never modified. Two probe tests were written into that
copy and deleted. The live gate probe ran the built image in a throwaway container against the dev
database; it triggered only the idempotent seed, which returns early on a populated fleet. Dev DB
counts are **100 / 210 / 420 / 0** and the risk-score checksum is
**`2d3eaded7d948dca394034571e88eb5b`**, both identical to the documented baseline. Final state: 180
backend tests passed, 8 inference tests passed, `ruff` 0.8.4 clean, coverage 96%, **`git status`
clean apart from this report**. Nothing was committed and nothing was fixed.
