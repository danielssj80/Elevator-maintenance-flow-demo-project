# Step 5 Report — Unit Tests

- Date: 2026-07-17
- Change: docker-images-to-ghcr

## Scope Note

Infrastructure-only change: the only modified sources are `.github/workflows/build-images.yml`
(new), `.github/workflows/deploy.yml`, and `docker-compose.prod.yml`. No `backend/app/`,
`backend/ml/`, or `frontend/src/` file is touched. Therefore:
- Step 4 (review existing tests): no test is affected by this change — confirmed by `git diff`
  scope (workflows + compose only).
- The unit suite is run purely as a regression sanity baseline, matching the precedent set by
  `deploy-portfolio-coexistence` (also an infra-only change).

## Commands Executed

- `pip install -q -r requirements.txt -r requirements-dev.txt`
- `python -m ruff check .` (backend)
- `python -m pytest tests/unit/ -q`

## Results

- `ruff check .`: **clean, no findings**.
- `pytest tests/unit/`: 22 errors, all `ConnectionRefusedError` to `127.0.0.1:5432` —
  this is the Claude Code web sandbox (Track A), which has no Postgres and cannot run the
  Docker stack (see `docs/dev-workflow.md` §4). This is expected sandbox behavior, not a
  regression: the same 22 tests require `TEST_DATABASE_URL` against a real Postgres and have
  never been runnable from Track A in this project. No test failure is attributable to this
  change (zero application-code files touched).
- Full DB-backed test run is deferred to Track B (local/dev-EC2), consistent with the
  project's two-track workflow. Not required to validate this change's own scope
  (workflow/compose syntax), but available if the user wants to re-run the suite locally.

## DB State

- Not applicable — no database interaction in this change's scope.

## Outcome

PASS (ruff clean; DB-backed suite untouched in scope, sandbox-limited to run — Track B optional)
