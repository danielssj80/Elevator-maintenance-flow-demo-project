# Tasks: docker-images-to-ghcr

> Infrastructure-only change: no backend/frontend source, no DB schema, no UI changes.
> TDD service-level steps and Alembic migration do not apply (no application code).
> E2E Playwright step does not apply (no frontend change).
> Endpoint testing maps to production smoke verification (AGENT MUST EXECUTE).

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/docker-images-to-ghcr` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. GitHub Actions: Build & Push Workflow

- [x] 1.1 Create `.github/workflows/build-images.yml`: trigger on push to `main`, `permissions: contents: read, packages: write`
- [x] 1.2 Step: `docker/setup-buildx-action`, `docker/login-action` against `ghcr.io` using `GITHUB_TOKEN`
- [x] 1.3 Step: build+push `elevator-backend` from `./backend` tagged `ghcr.io/danielssj80/elevator-backend:latest` and `:${{ github.sha }}`
- [x] 1.4 Step: build+push `elevator-frontend` from `./frontend` tagged `ghcr.io/danielssj80/elevator-frontend:latest` and `:${{ github.sha }}`
- [x] 1.5 Step: retention cleanup using `actions/delete-package-versions` — keep `latest` + 10 most recent SHA-tagged versions per package
- [ ] 1.6 Validate workflow syntax (actionlint via Docker — exit 0, no findings)

## 2. Compose: Reference GHCR Images

- [x] 2.1 `docker-compose.prod.yml`: `migrate` and `backend` services — replace `build: ./backend` with `image: ghcr.io/danielssj80/elevator-backend:latest`
- [x] 2.2 `docker-compose.prod.yml`: `frontend` service — replace `build: ./frontend` with `image: ghcr.io/danielssj80/elevator-frontend:latest`
- [x] 2.3 Confirm `docker-compose.yml` (local dev) is untouched — still builds from source

## 3. Deploy Workflow: Pull Instead of Build

- [x] 3.1 `.github/workflows/deploy.yml`: change trigger from `push: branches: [main]` to `workflow_run: workflows: ["Build and push images"], types: [completed], branches: [main]`
- [x] 3.2 Add job-level `if: github.event.workflow_run.conclusion == 'success'` guard
- [x] 3.3 Update deploy step's remote SSM command from `docker compose $CF up --build -d` to `docker compose $CF pull && docker compose $CF up -d` (wrapped in `sh -c '...'` under the existing `flock`)
- [x] 3.4 Update `--comment` in `send-command` to reference `github.event.workflow_run.head_sha` (the `push` event's `github.sha` is no longer available directly under `workflow_run`)
- [ ] 3.5 Validate workflow syntax (actionlint via Docker — exit 0, no findings)

## 4. Review and Update Existing Tests (MANDATORY)

- [x] 4.1 Review backend test suite for anything affected by this change (expected: none — no application code touched)
- [x] 4.2 Confirm no test updates required; note it in the step-5 report

## 5. Unit Tests and DB State Verification (MANDATORY)

- [x] 5.1 Capture pre-test DB baseline (local dev DB table counts) — N/A, unit tests mock the repository layer
- [x] 5.2 Run full backend unit test suite (sanity: change must not break anything)
- [x] 5.3 Verify post-test DB state matches baseline — N/A, no DB access
- [x] 5.4 Create report `openspec/changes/2026-07-17-docker-images-to-ghcr/reports/2026-07-17-step-5-unit-tests.md`

## 6. End-to-End Pipeline Verification (MANDATORY — AGENT MUST EXECUTE)

- [x] 6.1 Merge PR to `main` (user-approved) — run 29576459751 "Build and push images" completed `success` in ~2min (build 11:19:29–11:21:29Z)
- [x] 6.2 `deploy.yml` triggered automatically via `workflow_run` — run 29576571374 (event `workflow_run`), completed `success`
- [x] 6.3 SSM deploy log shows `Image ghcr.io/danielssj80/elevator-backend:latest Pulled` / `postgres:16-alpine Pulled` and container `Recreate`/`Started`/`Healthy` — no `Building`/`Step N/M` build output anywhere in the log; `SSM command status: Success`
- [x] 6.4 Smoke check step ran immediately after the SSM command returned and passed on the first attempt (`Health check passed on attempt 1`, 11:22:34Z) — no retry needed, no observed outage window
- [x] 6.5 Deploy log shows `elevator-backend-1`, `elevator-frontend-1`, `elevator-migrate-1`, `elevator-db-1`, `elevator-nginx-1` all `Recreated`/`Started`/`Healthy` for commit `4e154a8` (the images pulled were the ones just published by the build job for this same commit/tag `latest`)
- [x] 6.6 Build job steps "Clean up old image versions" (backend) and "Clean up old image versions (frontend)" both completed `success`
- [x] 6.7 Report created: `openspec/changes/2026-07-17-docker-images-to-ghcr/reports/2026-07-17-step-6-pipeline-verification.md`

## 7. E2E Testing with Playwright MCP (NOT APPLICABLE)

- [x] 7.1 No frontend changes in this change — not applicable (no UI/workflow touched; pipeline verification in section 6 covers the change)

## 8. Update Technical Documentation (MANDATORY)

- [x] 8.1 Update `docs/deployment.md` (or equivalent): describe the build → GHCR → pull deploy flow, replacing the old "builds on the instance" description
- [x] 8.2 `docs/api-spec.yml` and `docs/data-model.md`: no updates required (no API or entity changes)
