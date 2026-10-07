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

`build-images.yml` triggers on push to `main`, builds both images with `docker/build-push-action`, and pushes `:latest` and `:${{ github.sha }}` tags. `deploy.yml` is changed to trigger via `workflow_run` on `build-images.yml`'s completion (instead of directly on `push`), so the deploy step never races a build that hasn't finished. `deploy.yml` keeps its own `if: github.event.workflow_run.conclusion == 'success'` guard so a failed build never deploys stale or broken code silently. `build-images.yml` carries its own `concurrency: group: build-images` (no `cancel-in-progress`) so two rapid pushes to `main` can't run overlapping builds and interleave their `:latest` pushes — each build now fully completes (or fully fails) before the next one starts, closing the race that could otherwise leave `:latest` pointing at a backend from one commit and a frontend from another.

*Alternative considered*: a single workflow with `build` as job 1 and `deploy` as job 2 (`needs: build`). Simpler dependency graph, but couples the two concerns into one file and makes it harder to re-run just the deploy step against an already-built image. Two workflows chosen for separability; both are one-time CI concerns, not application code, so the extra file is low cost.

### D4 — Compose changes: `build:` → `image:`, tag pinned per deploy via `IMAGE_TAG`

`docker-compose.prod.yml`'s `migrate`, `backend`, and `frontend` services drop their `build:` key and get `image: ghcr.io/danielssj80/elevator-backend:${IMAGE_TAG:-latest}` / `image: ghcr.io/danielssj80/elevator-frontend:${IMAGE_TAG:-latest}` (the `migrate` service reuses the backend image, matching today's behavior where it builds from the same `./backend` context). `docker-compose.yml` (local dev) is untouched — local dev still builds from source for fast iteration.

`IMAGE_TAG` is not baked into the compose file; it's exported by the deploy step (D5) as the exact commit SHA being deployed, so `docker compose pull`/`up` always resolve to that commit's own tagged images rather than to the shared, mutable `latest` tag. `${IMAGE_TAG:-latest}` keeps `latest` as the fallback for any manual `docker compose up -d` run on the instance without the variable set (e.g. an ad-hoc operator command), matching the rollback plan below.

### D5 — Deploy command: `pull` replaces `up --build`, pinned to the deployed commit's images

The SSM command changes:
```
flock -w 600 /opt/deploy.lock docker compose $CF up --build -d
```
to:
```
export IMAGE_TAG=<workflow_run.head_sha>
flock -w 600 /opt/deploy.lock sh -c "docker compose $CF pull && docker compose $CF up -d"
```
`IMAGE_TAG` is set to `github.event.workflow_run.head_sha` — the exact commit the just-completed build workflow built and tagged — **not** re-derived from `git rev-parse HEAD` on the instance, so the pulled images are traceable to the specific build run that produced them rather than "whatever `main` happens to be at pull time." `pull` only downloads the two GHCR images (`postgres:16-alpine` and `nginx:alpine` are already pulled and unchanged most deploys); `up -d` recreates only the containers whose image digest changed. No `vite build` — no OOM risk — regardless of swap.

*Rejected alternative*: keep pulling `:latest` (as first implemented). An adversarial review after the initial merge found that without a `concurrency` guard on `build-images.yml`, two rapid pushes to `main` could interleave their `:latest` pushes, and a deploy gated only on "its own build succeeded" could still pull a `:latest` that had since been overwritten by a different commit's partial build — i.e. a backend from commit A paired with a frontend from commit B. Pinning to `head_sha` (combined with D3's build concurrency group) closes this: each deploy is now traceable to a single, fully-built commit's image pair by construction, not by the shared mutable tag's state at pull time.

### D6 — Tag retention via `actions/delete-package-versions`

A separate scheduled/triggered cleanup step (in `build-images.yml`, running after push) keeps `latest` plus the most recent 10 SHA-tagged versions per package, deleting older untagged/excess versions. Runs with `packages: write` permission, no extra secret (uses `GITHUB_TOKEN`).

## Risks / Trade-offs

- [`workflow_run` adds a hop of latency/complexity vs. direct `push` trigger] → acceptable; deploy already waits on a multi-minute SSM round trip, an extra ~1-2 min build stage before it is not user-visible.
- [Build workflow succeeds but deploy workflow never fires, e.g. workflow_run misconfigured] → mitigated by testing an end-to-end push to `main` as part of verification (tasks §6).
- [Two rapid pushes to `main` interleaving `:latest` pushes across builds] → closed by D3's `concurrency` group on `build-images.yml` (builds fully serialize) and D5's `IMAGE_TAG` pinning to the triggering build's `head_sha` (deploy never depends on the shared mutable `latest` tag's state at pull time).
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
