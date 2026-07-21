# Change: fix-resync-migration-empty-db

| Field | Value |
|---|---|
| **Status** | Implemented — adversarial review PASS WITH GAPS; ready to archive |
| **Milestone** | Backlog improvements |
| **Notion task** | _None — no bug-tracking flow defined yet (to be added)_ |
| **Branch** | `feature/fix-resync-migration-empty-db` |
| **Started** | 2026-07-15 |

## Summary

Fixes a regression in the resync migration `0aac4958720e` that breaks `alembic upgrade head`
on a **fresh/empty** database. The migration `UPDATE`s `elevators` in place (never `INSERT`s)
but then **unconditionally** deletes and re-inserts `elevator_features` / `elevator_trend_points`
rows referencing each elevator id. On an empty database the `UPDATE` matches zero rows, yet the
child `INSERT`s still fire, violating the `elevator_features_elevator_id_fkey` foreign key and
aborting the `migrate` service (`exit 1`), so the stack never starts from a clean state.

The fix guards the child-table replacement on whether the parent `elevators` row actually
exists (via `UPDATE` rowcount): on an empty database every elevator becomes a no-op, and
`seed_database()` populates the fleet at backend startup exactly as designed. This restores
conformance with the existing `database-infrastructure` spec's **"Clean stack startup"**
scenario. A new integration test runs the real Alembic migration chain against an empty
database — closing the coverage gap where `conftest.py` builds the schema via
`Base.metadata.create_all` and never exercises migrations.

## Artifacts

- [proposal.md](./proposal.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)
- [specs/database-infrastructure/spec.md](./specs/database-infrastructure/spec.md)
