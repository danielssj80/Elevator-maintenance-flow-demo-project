# Step 7 Report — Mutation Checks

- **Date**: 2026-08-31
- **Change**: harden-telemetry-ingest
- **Branch**: `feature/harden-telemetry-ingest`

Every guard this change adds was broken deliberately and the suite re-run. A
guard that survives its own deletion is not tested. Across the previous change
this method found five defects that no amount of reading the tests had found.

## Results

| # | Mutation | Expected | Result |
|---|---|---|---|
| A | Delete the dedup `DELETE` from the migration, keeping the constraint | red | **red** — `test_upgrade_dedups_existing_readings_and_then_constrains` |
| B | `on_conflict_do_nothing(...)` → plain insert | red | **red** — 5 of 6 idempotency tests |
| C | Drop `UniqueConstraint` from the model | red | **red** — all 6 idempotency tests |
| D | `for r in distinct` → `for r in valid` (no in-service dedup) | red | **GREEN — see below** |
| E | `accepted=inserted` → `accepted=len(valid)` | red | **red** — 3 service tests |
| F | Remove `Depends(require_ingest_token)` from `POST /api/telemetry/readings` | red | **red** — 4 auth tests |
| G | Remove `Depends(require_ingest_token)` from `POST /api/inference/run` | red | **red** — 1 auth test |
| H | `secrets.compare_digest(...)` → `!=` | red | **GREEN — see below** |
| I | Remove the `if not configured: return` short-circuit (fail-closed) | red | **red** — `test_an_unconfigured_token_leaves_ingest_open` |
| J | Remove the startup warning from `build_app` | red | **red** — `test_registering_the_routers_unguarded_logs_a_warning` |
| K | Delete `TELEMETRY_INGEST_TOKEN` from `docker-compose.yml` | red | **red** — `test_dev_compose_configures_an_ingest_token` |

Restored after each. A second round followed the self-review below:

| # | Mutation | Expected | Result |
|---|---|---|---|
| L | `_as_insert_values` stops skipping columns with a server default | red | **red** — `test_a_column_with_a_server_default_is_omitted_when_unset` |
| M | Give `door_cycles` a real Python-side default (`default=0`) | red | **red** — `test_no_column_carries_a_python_side_default` |
| O | Remove the `TELEMETRY_INGEST_TOKEN` pop from `conftest.py`, with the variable exported | red | **red** — 10 tests fail with unexplained 401s |

The suite is green at **214 passed**, and green again with
`TELEMETRY_INGEST_TOKEN` exported into the environment, which is what O shows is
not free.

## D — the in-service deduplication was dead code, and was deleted

The batch was pre-deduplicated in `TelemetryService.ingest` before the ORM
objects were built, so that the intra-batch rule was stated in Python rather
than resting on PostgreSQL's semantics. Removing that pass left **every test
green**.

The reason is that the repository issues a *single* multi-row `INSERT ... ON
CONFLICT DO NOTHING`, and PostgreSQL's speculative insertion already skips a row
conflicting with one inserted earlier in the same statement. The Python pass
never had anything to do.

It was **removed rather than kept and excused.** Ten lines that look like a
guard and enforce nothing are precisely the defect this project has paid for
across seven review rounds. The reliance on the `ON CONFLICT` clause is now
documented in `create_many`'s docstring, in `docs/backend-standards.md`, and
pinned by `test_a_reading_repeated_within_one_batch_is_persisted_once`, which
goes red under mutation B.

## H — constant-time comparison is not test-detectable

Replacing `secrets.compare_digest` with `!=` keeps every test green, and no
unit test can distinguish them: the difference is a timing property, not a
behavioural one. Asserting on wall-clock timing would be flaky and would prove
nothing on a loaded CI runner.

This one rests on review, and is recorded here so that the green suite is not
mistaken for evidence. The reason it matters is small but real — the header is
attacker-controlled and the comparison is against a shared secret — and the
mitigating context is that these routers do not exist in production at all.

## Two toothless tests found and fixed while writing them

- `test_a_duplicated_batch_does_not_move_the_window_aggregate` first passed with
  no constraint in the database. It reused the same ORM instances for the retry,
  and `add_all` on an already-persistent instance is a no-op, so the identity
  map absorbed the duplication the constraint was supposed to catch. It now
  builds a fresh payload per call, as a real retry does.
- `test_upgrade_dedups_existing_readings_and_then_constrains` exists because
  `test_alembic_upgrade_head_succeeds_on_empty_db` passes just as happily with
  the dedup `DELETE` removed — every table is empty there, so the `DELETE` is a
  no-op and the constraint has nothing to reject.

## Findings from the self-review, and their fixes

Three things the first pass got wrong, all found by attacking the change rather
than re-reading it:

1. **An overstated mechanism.** The model comment, the migration, the proposal
   and the design all claimed PostgreSQL serves the `DESC` ordering "by scanning
   the btree backwards". Measured on a 200,000-row table, the planner picks a
   *bitmap* index scan on `uq_telemetry_readings_identity` and sorts the 14
   matched rows — 4 buffer hits, 0.28 ms. The conclusion (the old index is
   redundant) holds and is now evidence-backed; the stated reason was wrong and
   is corrected in all four places. The first `EXPLAIN` was run against an empty
   table and showed a seq scan, which proved nothing either way.
2. **A latent NULL-instead-of-default trap.** `_as_insert_values` names every
   non-primary-key column, so a column carrying a Python-side default would be
   written as NULL rather than taking it. No such column exists today. Rather
   than add a branch nothing would exercise — the exact defect D is about —
   `test_no_column_carries_a_python_side_default` asserts the invariant, and
   mutation M shows it fires.
3. **The suite was not hermetic against this change's own variable.** A
   developer with `TELEMETRY_INGEST_TOKEN` exported would have got 10 failing
   tests that CI does not reproduce. `conftest.py` now pops it explicitly, the
   same way it already pins `DEPLOYMENT_ENVIRONMENT`, with the reason written
   down. Mutation O shows the pop is load-bearing.

One thing checked and deliberately left alone: an **unparseable** body with no
token answers 422 rather than 401, because JSON parsing precedes dependency
resolution. A structured-but-invalid body correctly answers 401. This leaks
nothing — the response is identical whether or not a token is configured — and
nothing is persisted either way, so the spec's "reject before any reading is
persisted" holds. Recorded so it is a known shape rather than a surprise.

## Outcome

**PASS** — 11 of 14 mutations detected. Of the three that were not: one
(constant-time comparison) is not detectable by any unit test and rests on
review; one (the in-service dedup) was resolved by deleting the code; and the
third was the empty-table `EXPLAIN`, which was replaced by a measurement that
actually discriminates.
