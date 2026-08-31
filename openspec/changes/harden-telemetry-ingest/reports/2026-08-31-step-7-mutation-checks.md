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

Restored after each; the suite is green at 212 passed.

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

## Outcome

**PASS** — 9 of 11 mutations detected; the 2 that were not are analysed above,
one resolved by deleting the code and one accepted with its reasoning recorded.
