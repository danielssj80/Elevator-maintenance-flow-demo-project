# Independent Adversarial Review

- **Date**: 2026-08-31
- **Change**: harden-telemetry-ingest
- **Reviewer**: independent session, cold start, own git worktree, no access to the
  implementing session's reasoning
- **Branch reviewed**: `feature/harden-telemetry-ingest` @ `f5fa25c`

## Verdict

**PASS WITH GAPS** — no Blocker, no Major. Seven findings: five Minor, two
Question.

The reviewer re-derived its own mutation set rather than replaying the step 7
report's. Thirteen mutations, twelve red. It also independently exercised the
1000-reading batch bound through the real route (`201 accepted:1000`, then
`accepted:0 duplicates_ignored:1000`), the full migration up/down/up cycle, the
deploy path in `.github/workflows/deploy.yml`, the CI layout, and
`docker-compose.cloud.yml` — a third compose file this change never mentions,
which turns out to be an overlay touching only `otel-collector` and therefore
inherits the token. It confirmed the two claims that matter: a resubmitted batch
stores nothing and reports it honestly, and both write endpoints reject an
absent or wrong token identically.

## Findings and disposition

| # | Severity | Finding | Disposition |
|---|---|---|---|
| F1 | Minor | The migration's `op.drop_index(...)` **survives its own deletion**. Nothing compares the migrated schema to `Base.metadata`; `conftest` builds the test schema with `create_all`, so migration/model drift is invisible. Step 7 ran 14 mutations and missed this one. | **Fixed** — `test_the_migrated_schema_matches_the_orm_models` runs `alembic upgrade head` on a fresh database and asserts `compare_metadata(...) == []`. Mutation P: removing the `op.drop_index` now fails it. This pins every future migration, not just this one. |
| F2 | Minor | `test_the_inference_trigger_is_guarded_by_the_same_token`'s docstring asserted as fact that an unguarded run "would answer 503 or 500, never 401". It answers **200** — the empty test database has no telemetry in the window, so nothing is scored. Stated as fact, never measured. | **Fixed** — the false docstring is gone. |
| F3 | Minor | The spec clause "before any inference run is started" and the scenario "AND no inference run is started" were asserted by nothing but a status code — and per F2 the unguarded endpoint completes a run and returns 200. | **Fixed** — `test_a_rejected_trigger_starts_no_run` substitutes a spy service that raises if reached. Mutation Q: it goes red with the guard removed. |
| F4 | Minor | The scenario says the **identical** batch is ingested twice; the test re-sent a *superset* and asserted the aggregate changes. The literal case was covered nowhere, and only `reading_count` discriminates it (identical duplication leaves averages unchanged by arithmetic). | **Fixed** — `test_re_ingesting_the_identical_batch_leaves_the_aggregate_untouched` asserts the scenario as written. Mutation R: red under a plain insert. The spec is unchanged; the test now matches it. |
| F5 | Minor | `design.md`, the model comment and the migration all credited the dropped index to "the per-elevator window query the inference run issues once per elevator". **No such query exists** — `aggregate_window` filters on `recorded_at` alone and groups by `elevator_id`. The only consumer of a leading `elevator_id` index is the read endpoint's `list_for_elevator`. | **Fixed** in all three places, naming the right query and noting what the old comment claimed. |
| F6 | Minor | The measurement stated as fact — "bitmap index scan … 4 buffer hits … 14-row sort, 0.28 ms" — does not reproduce. On the reviewer's 200k-row build it plans `Index Scan Backward`, 5 buffers, 0.31 ms. That is the plan shape the step 7 report claims to have *corrected away from*. The conclusion was independently confirmed anyway: 4 buffers / 0.21 ms with the old index also present. | **Fixed** — the plan-node claim is replaced everywhere by the buffer/time comparison that actually carries the decision, with an explicit note that the plan shape is data-dependent. |
| Q1 | Question | The migration's unbounded `DELETE … USING` is defended by "a no-op on an empty table, which is what production has". Consistent with the code but unverifiable without prod access. If prod ever held rows, this is an unbounded delete plus an index build under `ACCESS EXCLUSIVE` during `migrate`. | **Open — needs the author.** `SELECT count(*) FROM telemetry_readings` on production before merge closes it. |
| Q2 | Question | `test_prod_compose_does_not_configure_an_ingest_token` reads the `environment:` block only; prod `backend` also loads `env_file: /etc/elevator/.env`, invisible from the repository. The test's guarantee is narrower than its name. | **Fixed** — docstring now states the limit rather than implying a stronger guarantee. |

## Areas the reviewer checked that held

The 422 ordering (an all-duplicate batch is 201, an all-unknown batch is still
422); the fail-open default and all three startup-warning tests; both
`_as_insert_values` traps; `docs/api-spec.yml` resolving and parsing;
`docker-compose.prod.yml` untouched and its explicit
`DEPLOYMENT_ENVIRONMENT: production` winning over `env_file`; the absence of a
NULL hole in the identity index (all three columns are NOT NULL, so PostgreSQL's
"NULLs never conflict" rule cannot apply); `openspec/specs/` header alignment, so
archiving will modify the `Every reading records where it came from` requirement
rather than duplicate it; and that `TelemetryService.ingest` is the only caller
of `create_many`, so the `None → int` signature change has no other consumer.

It also confirmed the step 7 report's two honest non-detections — the deleted
dead dedup and the untestable constant-time comparison — are recorded as
non-detections rather than dressed up.

## After the fixes

- Suite: **217 passed** (was 214), `ruff check` clean.
- Mutations re-run per task 13.1, since F1 invited a migration edit: P (drop the
  `op.drop_index`) → red; Q (drop the inference guard) → red on both trigger
  tests; R (plain insert) → red on both aggregate tests.

## Outstanding before archive

Q1 only, and it is a question for the author rather than a code change.
