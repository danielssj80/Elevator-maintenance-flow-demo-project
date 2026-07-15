# Tasks: fix-resync-migration-empty-db

## Status: ready

## Task list

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/fix-resync-migration-empty-db` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

---

## 1. Reproduce the bug with a failing integration test (TDD)

**Files:** new `backend/tests/integration/test_migrations.py`

- [x] 1.1 Write a failing test that creates an isolated, empty database
      (`elevator_migration_test_db`) and runs `alembic upgrade head` (as a subprocess with
      `DATABASE_URL` pointed at it — the same code path as the `migrate` service).
- [x] 1.2 Assert the upgrade completes without error, and that `elevators`,
      `elevator_features`, and `elevator_trend_points` are all empty afterwards (migrations are a
      no-op on an empty DB — seeding is the backend's job).
- [x] 1.3 Run it and confirm it **fails red** with the FK violation
      (`elevator_features_elevator_id_fkey`), reproducing the reported bug. ✅ Failed at
      `0aac4958720e` as expected.
- [x] 1.4 Ensure the test creates and drops its isolated database in fixtures so it does not
      disturb the session-scoped `create_all` schema used by other integration tests.

---

## 2. Fix the resync migration (make the test pass)

**Files:** `backend/alembic/versions/0aac4958720e_resync_elevators_from_predictions_json.py`

- [x] 2.1 Capture the `UPDATE` result and `continue` when `result.rowcount == 0` (parent
      `elevators` row absent), skipping the `DELETE`/`INSERT` of that elevator's features and trend
      points.
- [x] 2.2 Correct the docstring so the "safe against an empty table" claim reflects the guarded
      behaviour (child rows are only touched when the parent row exists).
- [x] 2.3 Re-run the Step 1 test — the chain advanced past `0aac4958720e` and revealed the same
      bug in sibling `2c43876e02dd` (see Task 3).

---

## 3. Extend the fix to sibling resync migrations if the chain still fails

**Files:** `backend/alembic/versions/2c43876e02dd_*.py`, the `feature-direction` migration
(`*_add_feature_direction.py`), only if step 2.3 shows they hit the same FK violation.

- [x] 3.1 The full-chain test revealed three affected siblings: `2c43876e02dd` (same UPDATE +
      child-insert pattern), `97f03bcd4e85` (add-direction backfill) and `56cd241fcfd6`
      (celsius feature resync), all with unconditional child inserts. `aa3f0fc81e9c`
      (nl_explanation) only UPDATEs elevators → harmless no-op, no guard needed.
- [x] 3.2 Applied the `rowcount == 0 → continue` guard to `2c43876e02dd`; for the two
      feature-only migrations (no elevators UPDATE) added an `existing_ids` parent-existence
      guard (skip elevator ids absent from `elevators`).
- [x] 3.3 Re-ran the Step 1 test — full `alembic upgrade head` now passes **green** on an
      empty DB with all data tables empty.

---

## 4. Review and Update Existing Tests (MANDATORY)

- [x] 4.1 Reviewed `backend/tests/**`: no existing test asserts migration behaviour (the gap
      this change closes). No test constructs rows in a way the fix invalidates — the fix is a
      no-op on the persisted-volume path. Baseline suite: 39 passed unchanged.
- [x] 4.2 No existing test invalidated. One iteration issue found & fixed in the *new* test:
      an initial `asyncio.run`-based version closed the pytest-asyncio session loop and broke
      18 downstream async tests; switched to a private-loop `_run` helper. Full suite: 40 passed.

---

## 5. Unit Tests and DB State Verification (MANDATORY)

- [x] 5.1 Baseline captured: tests use `elevator_test_db` + ephemeral
      `elevator_migration_test_db`; dev `elevator_db` untouched.
- [x] 5.2 Ran the new migration test — passes (red→green documented in step 5 report).
- [x] 5.3 Full backend suite (unit + integration): **40 passed, 0 failed**, no regressions.
- [x] 5.4 Post-test state verified: isolated migration DB dropped by fixture; dev DB untouched.
- [x] 5.5 Report created: `reports/2026-07-15-step-5-unit-tests.md`.
- [x] 5.6 Complete — report exists and tests pass.

---

## 6. Clean-stack verification — the original goal (MANDATORY — AGENT MUST EXECUTE)

- [x] 6.1 `docker compose down -v` — postgres volume removed (verified clean).
- [x] 6.2 `docker compose up -d --build` — images rebuilt (migration code is baked into the
      image, not bind-mounted) and stack started.
- [x] 6.3 `migrate` **Exited (0)**, full chain applied with no FK violation; `backend`
      **healthy**. The "Clean stack startup" scenario now passes.
- [x] 6.4 `GET /api/elevators` → 100 elevators; `GET /api/elevators/ELV-001` → 3 features
      (with `direction`) + 6 trend points; `/health` ok; frontend HTTP 200.
- [x] 6.5 Report created: `reports/2026-07-15-step-6-clean-stack.md`.

> No E2E Playwright step: this change touches no frontend/UI. (Mandatory-steps §4 — E2E only
> when the frontend changes.)

---

## 7. Update Technical Documentation (MANDATORY)

- [x] 7.1 `docs/dev-workflow.md`: the documented `docker compose up -d` flow is unchanged and
      now works from a clean volume (verified in step 6, using `--build` to pick up the fixed
      migration). No documentation update required.
- [x] 7.2 `docs/data-model.md` / `docs/api-spec.yml`: no schema/API change — no documentation
      update required.
- [x] 7.3 Confirmed: the `database-infrastructure` delta spec captures the
      "Resync migrations are a no-op on an empty database" requirement/scenario (source of
      truth for `/adversarial-review` and `/archive`).

---

## 8. Adversarial review before archive (MANDATORY)

- [x] 8.1 Ran `/adversarial-review` (same session — see caveat). Verdict: **PASS WITH GAPS**.
      Resolved the one Major (verified `rowcount` reliability empirically: matched=1,
      unmatched=0, persisted-volume resync path sound).
- [x] 8.2 Re-ran `/adversarial-review` in an **independent agent session** (satisfies the skill).
      Verdict again **PASS WITH GAPS**, archiving advisable; the independent reviewer also
      verified the populated-volume path live (stale rows resynced, `visit_report` preserved).
- [x] 8.3 Addressed adversarial finding #1 (highest value): added
      `test_resync_updates_existing_rows_and_preserves_visit_reports` — plants a stale
      elevator + a `visit_report`, upgrades to head, asserts the resync overwrote derived rows
      and preserved the report. Suite: **41 passed**.
- [x] 8.4 Addressed adversarial finding #2: corrected `proposal.md` §Capabilities to reference
      the "Seeding is deterministic and idempotent" requirement (not "Clean stack startup").
- [ ] 8.5 Follow-ups left as separate backlog items (not blockers): #3 migrate `conftest.py`
      off `Base.metadata.create_all` onto an Alembic-built schema; #4 confirm `elevator_test_db`
      provisioning in the dev/CI bootstrap (doc note).
