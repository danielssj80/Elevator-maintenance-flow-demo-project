# Step 9 Report — Adversarial Review Blocker Fix Verification

- Date: 2026-07-17
- Change: docker-images-to-ghcr
- PR: #28 (merged to `main`, commit `97034ac74718171bb09c64fc0c5d5fe63b792406`)

## Background

An `/adversarial-review` pass on the already-archived, already-merged `docker-images-to-ghcr` change (PR #27) found a **Blocker**: `build-images.yml` had no `concurrency` group, and both `docker-compose.prod.yml` and `deploy.yml` resolved images via the mutable `:latest` tag. Two rapid pushes to `main` could interleave `:latest` pushes across builds, and a deploy gated only on "its own build succeeded" could still pull a `latest` overwritten mid-flight by a different commit's build — pairing a backend from one commit with a frontend from another.

Fix (PR #28): `concurrency` group on `build-images.yml`; `docker-compose.prod.yml` images changed to `${IMAGE_TAG:-latest}`; `deploy.yml` exports `IMAGE_TAG=${{ github.event.workflow_run.head_sha }}` before `pull`/`up -d`.

## Runs Observed

### Build: `Build and push images` — run [29590745414](https://github.com/danielssj80/Elevator-maintenance-flow-demo-project/actions/runs/29590745414)
- Trigger: `push` to `main` (commit `97034ac`)
- Status: `completed` / `success`, all steps green including both "Clean up old image versions" cleanup steps
- Duration: 15:06:28Z → 15:07:03Z (~35s)

### Deploy: `Deploy to production` — run [29590792598](https://github.com/danielssj80/Elevator-maintenance-flow-demo-project/actions/runs/29590792598)
- Trigger: `workflow_run` (fired after the build run's `success` conclusion)
- Status: `completed` / `success`, all 5 steps green
- Duration: 15:07:09Z → 15:07:56Z (~47s)

## Evidence: Deploy Pinned to Commit SHA, Not `latest`

SSM command sent by the workflow includes:
```
"export IMAGE_TAG=97034ac74718171bb09c64fc0c5d5fe63b792406",
```

Remote command log confirms the images actually pulled carry that exact tag:
```
Image ghcr.io/danielssj80/elevator-backend:97034ac74718171bb09c64fc0c5d5fe63b792406 Pulling
Image ghcr.io/danielssj80/elevator-frontend:97034ac74718171bb09c64fc0c5d5fe63b792406 Pulling
Image ghcr.io/danielssj80/elevator-backend:97034ac74718171bb09c64fc0c5d5fe63b792406 Pulled
Image ghcr.io/danielssj80/elevator-frontend:97034ac74718171bb09c64fc0c5d5fe63b792406 Pulled
```
No `:latest` appears anywhere in the pull output — confirms the blocker fix works as designed: the deploy resolves to the specific commit's image pair, not to the shared mutable tag.

## Evidence: No Outage

```
Health check passed on attempt 1
```
(15:07:54Z, first attempt, immediately after the SSM command returned success) — consistent with a pull-based, no-build deploy; no retries needed.

## Outcome

PASS — the adversarial review's Blocker finding is resolved and verified against a real merge to `main`. Concurrency guard on `build-images.yml` and SHA-pinned `IMAGE_TAG` on `deploy.yml`/`docker-compose.prod.yml` together close the race that could previously leave `latest` (and therefore a deploy) pointing at a mismatched backend/frontend pair.

Task 9.5 (actionlint) remains unchecked: not runnable in this sandbox (no Docker daemon, no network access outside the scoped GitHub repo). Substituted a `yaml.safe_load` syntax check on both workflow files (passes) as a partial substitute; a real actionlint run is still recommended in an environment with Docker or direct internet access.
