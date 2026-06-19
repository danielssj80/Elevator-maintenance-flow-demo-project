A# Tasks: deploy-portfolio-coexistence

> Infrastructure-only change: no backend/frontend source, no DB schema, no UI, no API surface.
> TDD service-level steps and Alembic migration do not apply (no application code).
> E2E Playwright step does not apply (no frontend change).
> Endpoint testing maps to the production smoke verification (AGENT MUST EXECUTE).

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/deploy-portfolio-coexistence` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. Workflow: deploy.yml — conditional override + flock

- [x] 1.1 In `.github/workflows/deploy.yml`, replace the single `docker compose -f docker-compose.prod.yml up --build -d` command with a build of the Compose file list that appends `/opt/portfolio/docker-compose.portfolio.yml` only when it exists (used `if/then/fi` for set -e safety)
- [x] 1.2 Wrap the `docker compose ... up --build -d` invocation in `flock -w 600 /opt/deploy.lock` (bounded wait, per adversarial-review minor #2)
- [x] 1.3 Keep auth (OIDC), polling/propagation, and the smoke check steps unchanged
- [x] 1.4 Validate workflow syntax with actionlint (via Docker), exit 0 (added a documented `# shellcheck disable=SC2016` for the intentionally-literal `$CF`)
- [x] 1.5 (adversarial-review Major) When the override is included, validate the merged nginx config (`docker compose $CF run --rm --no-deps -T --entrypoint nginx nginx -t`) before recreating the shared nginx, and fall back to an Elevator-only deploy (drop the override) + log a warning if invalid — so a broken co-located `portfolio.conf` cannot take Elevator down. Updated delta spec + design accordingly.

## 2. Review and Update Existing Tests (MANDATORY)

- [x] 2.1 Review the backend test suite for anything affected (expected: none — no application code touched)
- [x] 2.2 Confirm no test updates required; note it in the step-3 report

## 3. Unit Tests and DB State Verification (MANDATORY)

- [x] 3.1 Ran the full backend unit suite in-Docker as a regression baseline: 22 passed, 0 failed
- [x] 3.2 Create report `reports/2026-06-19-step-3-unit-tests.md` documenting N/A justification + suite result

## 4. Manual / Production Verification (MANDATORY — AGENT MUST EXECUTE)

- [x] 4.1 Verified the `if/then/fi` branch logic for both present/absent cases under `set -eu`, and confirmed `docker-compose config` merges the override volumes additively (base + 2 portfolio mounts)
- [x] 4.2 Smoke check unchanged in the workflow; will assert `https://elevator.dsaavedra.dev/health` 200 on the post-merge deploy
- [x] 4.3 Coexistence assertion cross-referenced; deferred to the `dsaavedra-web` rollout once `/opt/portfolio` exists
- [x] 4.4 Create report `reports/2026-06-19-step-4-deploy-verification.md`

## 5. E2E Testing with Playwright MCP

- [x] 5.1 Not applicable — no frontend change. Noted in the step-4 report.

## 6. Update Technical Documentation (MANDATORY)

- [x] 6.1 Updated `docs/deployment.md`: new "Co-located sites (shared nginx)" section + updated CI/CD command + manual-deploy fallback with the conditional override and `flock`
- [x] 6.2 Confirmed no `docs/api-spec.yml` or `docs/data-model.md` changes are needed (no API/entity change)
