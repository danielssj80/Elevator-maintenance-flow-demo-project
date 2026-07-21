# Design: fix-resync-migration-empty-db

## Root cause

`0aac4958720e` iterates every prediction and, per elevator id `eid`:

1. `UPDATE elevators SET ... WHERE id = eid` — matches an existing row, or **zero rows** on an
   empty database.
2. `DELETE FROM elevator_features WHERE elevator_id = eid` — no-op on empty DB.
3. `DELETE FROM elevator_trend_points WHERE elevator_id = eid` — no-op on empty DB.
4. `INSERT INTO elevator_features (...)` — **fires unconditionally**, and on an empty DB there is
   no parent `elevators` row, so the `elevator_features_elevator_id_fkey` foreign key is violated.

Step 4 is the defect: the child-row replacement assumes the parent row exists, but nothing
guarantees it. On the persisted-volume case (production/dev EC2) the parent always exists, which is
why this shipped without being noticed.

## Fix: guard on `UPDATE` rowcount

The elevator `UPDATE` already tells us whether the parent row exists. Capture its `rowcount` and
skip the child-table work when it is `0`:

```python
result = bind.execute(
    elevators_t.update().where(elevators_t.c.id == eid).values(...)
)

# On an empty/fresh database the elevator row does not exist yet, so the UPDATE
# matches nothing. Its features/trend points must NOT be inserted (they would
# violate the FK). seed_database() populates the full fleet — elevators, features,
# and trend points — from this same predictions.json at backend startup.
if result.rowcount == 0:
    continue

# Row exists: safe to fully replace its derived rows.
bind.execute(features_t.delete().where(features_t.c.elevator_id == eid))
bind.execute(trend_points_t.delete().where(trend_points_t.c.elevator_id == eid))
# ... conditional inserts as before ...
```

`rowcount` on a `WHERE id = <pk>` `UPDATE` is `0` or `1`, so the guard is exact. asyncpg (the
project's async driver, used by the `migrate` service) reports `rowcount` correctly for `UPDATE`.

### Why this over the alternatives

- **Add `INSERT ... ON CONFLICT` / upsert the elevator row in the migration** — rejected. The
  original design (`archive/2026-06-12-migrate-backend-postgresql/design.md`) deliberately keeps
  data seeding out of migrations ("rejected — mixes schema with data, hard to evolve"). Making the
  migration insert elevators would duplicate `seed_database()` and fight that decision.
- **Wrap the whole thing so it only runs when `elevators` is non-empty** — coarser and less clear
  than the per-row guard; the per-row `rowcount` check is the precise expression of "resync the
  rows that exist."
- **Make the FK deferrable / drop-and-recreate** — far more invasive for no benefit.

The chosen fix is minimal, matches the migration's stated intent ("re-sync the *existing* elevator
rows in place"), and leaves the persisted-volume behaviour byte-for-byte identical.

## Sibling migrations

`2c43876e02dd` and the `feature-direction` feature migration use the same "delete + reinsert child
rows per elevator" pattern. They run **after** `0aac4958720e` in the chain, so once `0aac4958720e`
is a no-op on an empty DB, `elevators` is still empty when they run and they hit the same FK
violation. The scope of *this* change is `0aac4958720e` plus a regression test that runs the
**whole** `alembic upgrade head` chain against an empty DB — which therefore also exercises the
siblings. If the test reveals the siblings fail for the same reason, the same one-line guard is
applied to each (they share the identical structure). The test is the source of truth for how far
the fix must reach.

## Test: run the real migration chain against an empty database

The coverage gap: `backend/tests/conftest.py` creates the schema with
`Base.metadata.create_all` (session-scoped `setup_test_db`) and never runs Alembic, so the
`migrate`-service code path is untested. The new integration test exercises it directly.

Approach (integration test, real Postgres — the test DB is already available via
`settings.test_database_url`):

1. Create an **isolated, empty database** distinct from the shared test DB and from the dev DB
   (e.g. `elevator_migration_test_db`), so it does not collide with the `create_all` schema the
   session fixture builds. Create it via an `asyncpg`/psycopg admin connection (`CREATE DATABASE`),
   drop it at teardown.
2. Point an Alembic `Config` at that database URL and run `command.upgrade(cfg, "head")`
   (equivalent to the `migrate` service's `alembic upgrade head`).
3. Assert the upgrade completes with no exception.
4. Assert `SELECT count(*)` is `0` for `elevators`, `elevator_features`, and
   `elevator_trend_points` — the migration chain must be a no-op on an empty DB; populating the
   fleet is `seed_database()`'s job, not the migrations'.

**Red before green:** against the current `0aac4958720e`, step 2 raises `IntegrityError`
(FK violation) and the test fails — reproducing the bug. After the guard, it passes.

Isolating the migration run in its own database keeps it from disturbing the session-scoped
`setup_test_db` schema and the other integration tests. Alembic's `env.py` must resolve the target
URL for this run — the test sets it explicitly on the `Config` (and/or via the same `DATABASE_URL`
env var the migration `env.py` reads) rather than relying on the shared settings.

## Out of scope

- Retraining the model or regenerating `predictions.json`.
- Any schema, API, or frontend change.
- Reworking `seed_database()` — its behaviour is correct and unchanged.
- Migrating `conftest.py` off `Base.metadata.create_all` to an Alembic-based schema build.
  (The spec says `create_all` should not be used in "any environment"; the test conftest still
  does, as a pre-existing convenience. Aligning it is a separate cleanup, noted but not undertaken
  here to keep this fix minimal.)
