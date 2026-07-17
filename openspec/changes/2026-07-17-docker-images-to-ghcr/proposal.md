# Proposal: docker-images-to-ghcr

## Why

Every deploy runs `docker compose -f docker-compose.prod.yml up --build -d` directly on the production EC2 instance (~916 MB RAM, previously 0 swap). Building the frontend image (`vite build`) is memory-hungry and starves the running containers, OOM-killing both `elevator.dsaavedra.dev` and `dsaavedra.dev` for the duration of every deploy (self-recovers once the build ends). This was confirmed live on the box (`free -h` ~67Mi free, `dmesg` OOM evidence). PR #25 (raise the SSM execution timeout) was the wrong fix — a longer in-place build means a **longer** outage, not a smaller one — and was reverted.

A 2 GB swapfile has already been added manually as an immediate mitigation so builds degrade instead of OOM-killing prod. This proposal is the root fix: stop building images on the production host at all.

## What Changes

- Add a GitHub Actions workflow (`.github/workflows/build-images.yml`) that builds the `elevator-backend` and `elevator-frontend` images and pushes them to GHCR (`ghcr.io/danielssj80/elevator-backend`, `ghcr.io/danielssj80/elevator-frontend`), tagged by commit SHA and `latest`. Public repo → free unlimited Actions minutes; public GHCR packages → free storage/bandwidth, no pull auth needed on the EC2.
- `docker-compose.prod.yml`: replace `build: ./backend` / `build: ./frontend` on the `migrate`, `backend`, and `frontend` services with `image: ghcr.io/danielssj80/elevator-backend:latest` / `image: ghcr.io/danielssj80/elevator-frontend:latest`.
- `.github/workflows/deploy.yml`: the remote SSM command changes from `docker compose $CF up --build -d` to `docker compose $CF pull && docker compose $CF up -d` — no build on the host.
- Sequence the two workflows so a push to `main` builds images first and only deploys once they're published (`workflow_run` trigger, or a single workflow with a build job followed by a deploy job).
- Add GHCR tag retention/cleanup for old image versions (keep `latest` + a bounded number of recent SHA tags).

## Capabilities

### New Capabilities

- None — this modifies the existing `deploy-pipeline` capability's deployment mechanism.

### Modified Capabilities

- `deploy-pipeline`: deployment no longer builds images on the production instance; it pulls pre-built images from GHCR. Adds an image-build stage ahead of deployment.

## Impact

- **New files**: `.github/workflows/build-images.yml`
- **Modified files**: `docker-compose.prod.yml`, `.github/workflows/deploy.yml`
- **GitHub**: GHCR packages `elevator-backend`, `elevator-frontend` (public, created automatically on first push); no new secrets — `GITHUB_TOKEN` has package write permission by default for the repo's own packages.
- **AWS EC2**: no IAM/infra changes — the instance already pulls images implicitly via `docker compose up`; explicit `pull` step is new but needs no new credentials since images are public.
- **Application code**: none — backend and frontend untouched, only how their images are built and delivered.
- **Runtime constraint removed**: production instance no longer needs enough free RAM to run `vite build` during deploy; the 2 GB swapfile mitigation remains as a safety net but is no longer load-bearing for deploys.
