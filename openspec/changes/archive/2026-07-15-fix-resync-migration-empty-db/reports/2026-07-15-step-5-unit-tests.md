# Step 5 Report — Unit + Integration Tests

- Date: 2026-07-15
- Change: fix-resync-migration-empty-db

## Commands Executed

Run inside the backend image on the compose network (per `docs/dev-workflow.md`):

```bash
docker run --rm --network elevator-maintenance-flow-demo-project_default \
  -v "$PWD/backend":/app -w /app \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  elevator-maintenance-flow-demo-project-backend:latest \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"
```

Also run in isolation while iterating:
`python -m pytest tests/integration/test_migrations.py -v`

## Results

- New migration test (`test_alembic_upgrade_head_succeeds_on_empty_db`):
  - **Red** against the unfixed migration — failed with
    `ForeignKeyViolationError: elevator_features_elevator_id_fkey` at revision `0aac4958720e`,
    reproducing the reported bug.
  - After fixing `0aac4958720e`, the full chain revealed the same bug in sibling
    `2c43876e02dd`; after guarding all affected siblings, the test passes **green**.
- Baseline (suite excluding the new test): **39 passed**.
- Full suite (including the new test): **40 passed, 0 failed**.

Note: the new test is synchronous and drives asyncpg on a private event loop (`_run`) rather
than `asyncio.run`, so it does not close the pytest-asyncio session loop the async tests share
(an earlier version using `asyncio.run` broke 18 downstream async tests — fixed).

## DB State

- Pre-test: dev DB (`elevator_db`) untouched by tests (tests use `elevator_test_db` and an
  ephemeral `elevator_migration_test_db`).
- The migration test creates and drops its own isolated `elevator_migration_test_db` in a
  fixture (with `WITH (FORCE)`), leaving no residue.
- Post-test: State restored — Yes (isolated DB dropped; shared test DB managed by the existing
  session fixture).

## Outcome

PASS
