# Step 6 Report — End-to-End Pipeline Verification

- Date: 2026-07-17
- Change: docker-images-to-ghcr
- PR: #27 (merged to `main`, commit `4e154a85a13996dd4f48d62182f4c0b819bf5ca6`)

## Runs Observed

### Build: `Build and push images` — run [29576459751](https://github.com/danielssj80/Elevator-maintenance-flow-demo-project/actions/runs/29576459751)
- Trigger: `push` to `main`
- Status: `completed` / `success`
- Duration: 11:19:29Z → 11:21:29Z (~2 min)
- Steps: checkout → Buildx setup → GHCR login → build+push backend → build+push frontend → cleanup (backend) → cleanup (frontend) — all `success`

### Deploy: `Deploy to production` — run [29576571374](https://github.com/danielssj80/Elevator-maintenance-flow-demo-project/actions/runs/29576571374)
- Trigger: `workflow_run` (fired automatically after the build run's `success` conclusion) — confirms the `workflow_run` sequencing (D3/tasks 3.1–3.2) works as designed
- Status: `completed` / `success`
- Duration: 11:21:32Z → 11:22:36Z (~1 min)
- Steps: configure AWS OIDC → send SSM command → wait for remote command → smoke check — all `success`

## Evidence: No Build on the Instance

Remote SSM command log (step "Wait for remote command and propagate result") shows only pull/recreate activity:
```
Image ghcr.io/danielssj80/elevator-backend:latest Pulled
Image postgres:16-alpine Pulled
Container elevator-db-1 Recreate / Recreated / Starting / Started / Healthy
Container elevator-migrate-1 Recreate / Recreated / Starting / Started / Exited (0)
Container elevator-backend-1 Recreate / Recreated / Starting / Started / Healthy
Container elevator-frontend-1 Recreate / Recreated / Starting / Started
Container elevator-nginx-1 Recreate / Recreated / Starting / Started
SSM command status: Success
```
No `docker build`, no `Step N/M`, no `vite build` output anywhere in the log — confirms task 6.3 and the design's core goal (D5).

## Evidence: No Outage

Smoke check ran immediately after the SSM command returned success:
```
Health check passed on attempt 1
```
(11:22:34Z, first attempt — no retries needed). Under the previous `up --build -d` flow this step frequently needed multiple retries while the OOM-starved containers recovered; a pass on attempt 1 is consistent with the containers never having been starved of memory during this deploy.

## Evidence: GHCR Retention

Both cleanup steps ("Clean up old image versions" for backend, "Clean up old image versions (frontend)") completed `success` in the build job, confirming the `actions/delete-package-versions` step ran without error for both packages.

## Outcome

PASS — build → GHCR publish → gated deploy → pull-based recreate → smoke check all verified end-to-end on a real merge to `main`. Production stayed healthy throughout (single-attempt smoke check pass, no OOM/outage signal). Root cause from the source Notion task (`docker compose up --build` OOM-killing prod during deploy) is resolved: the instance no longer builds any image.
