# Proposal: fix-resync-migration-empty-db

## Why

`alembic upgrade head` fails on a **fresh/empty** database, so the stack cannot start from a
clean state. The `migrate` compose service exits `1` with:

```
IntegrityError: insert or update on table "elevator_features" violates foreign key
constraint "elevator_features_elevator_id_fkey"
DETAIL: Key (elevator_id)=(ELV-001) is not present in table "elevators".
```

Root cause is in the data migration
`backend/alembic/versions/0aac4958720e_resync_elevators_from_predictions_json.py`. It resyncs
existing elevators **in place** by primary key with `UPDATE` (never `INSERT`), then
**unconditionally** deletes and re-inserts `elevator_features` / `elevator_trend_points` rows
for every elevator in `predictions.json`. On a database whose Postgres volume persists across
deploys (production, dev EC2) the elevator rows already exist, so this works. But on a genuinely
empty database — any first-ever deploy, a new local volume, CI — the `UPDATE` matches zero rows
while the child `INSERT`s still fire and violate the foreign key.

This is a **design bug**, not an environment problem: `0aac4958720e` is the second migration ever
applied (immediately after the `CREATE TABLE` migration `638e311fa8e1`), so on any clean volume
`elevators` is guaranteed empty when it runs — long before the backend container and
`seed_database()` start. The migration's own docstring claims it is "safe to run against an empty
`elevators` table too" — true for the `elevators` `UPDATE`, but false for the child-table
`INSERT`s. The regression was never caught because `backend/tests/conftest.py` builds the schema
with `Base.metadata.create_all` and never runs the Alembic migrations, so no test exercises the
`alembic upgrade head` path the spec already requires.

The same unconditional-insert pattern was copied into sibling data migrations
(`2c43876e02dd`, and the `feature-direction` migration that repopulates features), so the fix and
its regression test also protect those.

## What Changes

- **Fix `0aac4958720e`**: guard the per-elevator child-table replacement on whether the parent
  `elevators` row actually exists. Use the `UPDATE` result `rowcount`: if it is `0` (row absent on
  an empty database), skip the `DELETE`/`INSERT` of that elevator's features and trend points and
  `continue`. `seed_database()` then populates the whole fleet — elevators, features, trend
  points — from the same `predictions.json` at backend startup, exactly as designed. On a
  persisted volume (rows present) behaviour is unchanged: the resync still runs.
- **Correct the migration docstring** so the "safe against an empty table" claim reflects the new
  guarded behaviour instead of the false original claim.
- **Add integration coverage** that runs the real Alembic chain (`alembic upgrade head`) against an
  empty, freshly created database and asserts it completes without error and leaves `elevators`,
  `elevator_features`, and `elevator_trend_points` empty (the migration is a no-op on an empty DB;
  seeding is the backend's job). This closes the gap where migrations were never exercised in
  tests.

No schema change, no data model change, no API change, no frontend change. The model is not
retrained. `predictions.json` is unchanged.

## Capabilities

### Modified Capabilities

- `database-infrastructure`: the "Seeding is deterministic and idempotent" requirement is
  reinforced — seeding is exclusively `seed_database()`'s responsibility, data migrations SHALL NOT
  insert `elevators` rows, and any migration resyncing elevator-derived rows MUST only touch rows
  whose parent already exists (a no-op against an empty database). A new scenario, "Resync
  migrations are a no-op on an empty database," captures this, so `alembic upgrade head` always
  succeeds from a clean state (satisfying the existing "Clean stack startup" scenario).

## Impact

- **Backend**: `backend/alembic/versions/0aac4958720e_resync_elevators_from_predictions_json.py`
  (guard + docstring); one new integration test exercising `alembic upgrade head` against an empty
  database (plus any minimal test scaffolding needed to run migrations in isolation).
- **Data / schema**: none. No new columns, tables, or rows produced by the migration itself.
- **API**: none.
- **Frontend**: none.
- **Deploy / AWS**: none in configuration. The immediate effect is that a clean deploy (or any
  fresh volume) now migrates successfully instead of failing at the `migrate` service.
