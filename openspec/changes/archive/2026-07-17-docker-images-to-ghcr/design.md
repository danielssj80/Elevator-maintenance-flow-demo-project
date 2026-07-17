# Design: docker-images-to-ghcr

## Context

Production runs on a single `t3.micro` EC2 instance (~916 MB RAM) via `docker-compose.prod.yml`. The existing `deploy-pipeline` (from `github-aws-deploy-pipeline`) authenticates GitHub Actions to AWS via OIDC and runs the deploy command remotely through SSM `AWS-RunShellScript`. That command currently does `docker compose $CF up --build -d`, which builds `backend` and `frontend` images in place on the instance. `frontend`'s multi-stage Dockerfile runs `npm run build` (`vite build`) — memory-hungry enough to OOM the box mid-deploy, taking down both hosted sites until the build finishes.

A 2 GB swapfile was added manually as an immediate mitigation (`Done when` item 1 in the source task). This design is the root fix: move image builds off the instance entirely.

## Goals / Non-Goals

**Goals:**
- No image building happens on the production EC2 instance during deploy.
- Images are built once in CI and reused for every deploy of that commit.
- No new long-lived credentials or secrets required.
- Deploy pipeline still fails loudly (existing SSM polling + smoke check behavior preserved).
- Old GHCR image versions don't accumulate unbounded.

**Non-Goals:**
- Multi-arch builds (the runner and the EC2 instance are both `linux/amd64`).
- Private registry / registry auth on the EC2 instance (GHCR packages stay public, matching the public repo).
- Blue/green or zero-downtime deploys — out of scope, unchanged from the existing pipeline.
- Changing the OIDC/SSM deployment mechanism itself.

## Decisions

### D1 — GHCR over ECR

The repo is public, so GHCR gives free unlimited Actions minutes and free public package storage/bandwidth. ECR would need AWS IAM policy work on the deploy role (`ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, etc.) and per-account storage costs, for a project with no other reason to touch AWS IAM here.

*Alternative considered*: Docker Hub — free tier has stricter public-image pull-rate limits than GHCR; rejected.

### D2 — Public GHCR images, no pull auth on the EC2

Since the repo and images are public, `docker compose pull` on the EC2 instance needs no registry login. This avoids adding a `GHCR_PAT` secret or configuring `docker login` in the SSM deploy script — one less credential to manage on the box.

### D3 — Separate build workflow, sequenced ahead of deploy

`build-images.yml` triggers on push to `main`, builds both images with `docker/build-push-action`, and pushes `:latest` and `:${{ github.sha }}` tags. `deploy.yml` is changed to trigger via `workflow_run` on `build-images.yml`'s completion (instead of directly on `push`), so the deploy step never races a build that hasn't finished. `deploy.yml` keeps its own `if: github.event.workflow_run.conclusion == 'success'` guard so a failed build never deploys stale or broken code silently.

*Alternative considered*: a single workflow with `build` as job 1 and `deploy` as job 2 (`needs: build`). Simpler dependency graph, but couples the two concerns into one file and makes it harder to re-run just the deploy step against an already-built image. Two workflows chosen for separability; both are one-time CI concerns, not application code, so the extra file is low cost.

### D4 — Compose changes: `build:` → `image:`

`docker-compose.prod.yml`'s `migrate`, `backend`, and `frontend` services drop their `build:` key and get `image: ghcr.io/danielssj80/elevator-backend:latest` / `image: ghcr.io/danielssj80/elevator-frontend:latest` (the `migrate` service reuses the backend image, matching today's behavior where it builds from the same `./backend` context). `docker-compose.yml` (local dev) is untouched — local dev still builds from source for fast iteration.

### D5 — Deploy command: `pull` replaces `up --build`

The SSM command changes:
```
flock -w 600 /opt/deploy.lock docker compose $CF up --build -d
```
to:
```
flock -w 600 /opt/deploy.lock sh -c 'docker compose $CF pull && docker compose $CF up -d'
```
`pull` only downloads the two GHCR images (`postgres:16-alpine` and `nginx:alpine` are already pulled and unchanged most deploys); `up -d` recreates only the containers whose image digest changed. No `vite build` — no OOM risk — regardless of swap.

### D6 — Tag retention via `actions/delete-package-versions`

A separate scheduled/triggered cleanup step (in `build-images.yml`, running after push) keeps `latest` plus the most recent 10 SHA-tagged versions per package, deleting older untagged/excess versions. Runs with `packages: write` permission, no extra secret (uses `GITHUB_TOKEN`).

## Risks / Trade-offs

- [`workflow_run` adds a hop of latency/complexity vs. direct `push` trigger] → acceptable; deploy already waits on a multi-minute SSM round trip, an extra ~1-2 min build stage before it is not user-visible.
- [Build workflow succeeds but deploy workflow never fires, e.g. workflow_run misconfigured] → mitigated by testing an end-to-end push to `main` as part of verification (tasks §6).
- [GHCR image the EC2 pulls could momentarily lag the `:latest` tag mid-build] → deploy only runs after `build-images.yml` reports success, so `:latest` is fully published before `pull` runs.
- [Public GHCR images expose Dockerfile/dependency versions] → already true today: `backend/Dockerfile`, `frontend/Dockerfile`, and `requirements.txt`/`package.json` are all in the public repo.
- [Swapfile mitigation becomes stale/forgotten] → no longer load-bearing for deploys after this change; left in place as a general safety margin, not removed by this change.

## Migration Plan

1. Add `.github/workflows/build-images.yml` (build + push + retention cleanup); verify on a feature branch that it can build and push (dry run against a non-`main` branch first, or scoped to the PR).
2. Update `docker-compose.prod.yml` to reference GHCR images.
3. Update `.github/workflows/deploy.yml`: `workflow_run` trigger + `pull`-based deploy command.
4. Merge to `main`: first end-to-end run builds images, publishes to GHCR, then deploys via pull.
5. Verify: trigger a deploy (e.g. trivial commit to `main`), confirm the site stays up throughout (no `/health` outage window), confirm containers are running the new commit's images.

**Rollback**: revert the three changed/added files. Manual deploy via SSM Session Manager (`docker compose up --build -d`) still works unchanged since the compose file's services keep the same names/ports — only the image source differs.

## Open Questions

- None — GHCR namespace (`ghcr.io/danielssj80/...`), retention count (10 SHA tags), and workflow sequencing are decided above; revisit retention count only if GHCR storage becomes a practical concern (unlikely at this scale, since public package storage is free).
