# Design: cloud-dev-workflow

## Context

Claude Code on the web runs each session in an Anthropic-managed cloud sandbox (Ubuntu, root) cloned from the GitHub repo at the selected branch. The intent was to run the project's Docker Compose dev/test stack there. **Live validation in a real web session disproved that assumption** — see "Validated sandbox findings". The result is a **two-track** workflow.

## Validated sandbox findings (live)

Tested empirically in a Claude Code web session on this repo's branch:

1. **Docker daemon not auto-started.** `docker` works only after starting `dockerd` (we are root, so no real sudo needed). The cache stores files, not processes, so any daemon must be (re)started per session.
2. **Setup script CWD is not the repo root.** `bash scripts/dev-setup.sh` as the environment setup script failed `exit 127` (file not found), while the same command run interactively worked (repo at `/home/user/<repo>`). Setup scripts must use an absolute path / `cd`.
3. **`Trusted` network blocks Docker Hub's CDN.** `docker compose pull` of `postgres:16-alpine` got `403 Forbidden` from `production.cloudfront.docker.com`. The Trusted allowlist includes the `cloudflare` variant but not `cloudfront`. Needs **Full** (or Custom + that host).
4. **The wall: image builds fail TLS through the MITM proxy.** With the daemon up and network Full, `docker compose build` failed: `pip install` inside the build container hit `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` against pypi.org. The sandbox's security proxy does TLS interception with a CA that is trusted on the host but **not inside `docker build` containers**. `npm ci` would hit the same wall.
5. **Non-Docker work is fine.** On the host (CA trusted), `python3 -m venv … && pip install xgboost scikit-learn pandas` succeeds (`HOST-PIP-OK`). M1's offline ML needs no Docker, no DB, no stack.

Conclusion: forcing docker-in-docker in the sandbox means hacking the production Dockerfiles (inject the proxy CA, `--trusted-host`, `--strict-ssl false`) or pushing pre-built images to a registry — not worth it for a portfolio project, especially when M1 needs none of it.

## Decisions

### D1. Portable `scripts/dev-setup.sh`, not UI-only setup
Setup logic lives in the repo as `scripts/dev-setup.sh`; a host calls it directly. This makes it reusable on the dev EC2 and locally with no rewrite — a drop-in for the "Provision dev EC2" backlog task.

### D2. Compose CLI: support both v2 and v1
`scripts/dev-setup.sh` and the documented commands **detect** the Compose CLI (prefer `docker compose` v2, fall back to `docker-compose` v1). Verified: it selected v2 in the sandbox and v1 locally. The documented test command derives the Compose project name as the **lowercased** repo directory name (fixing a mis-cased network name caught in adversarial review).

### D3. Two-track workflow (the core decision)
**Track A — Claude Code on the web**: non-Docker work only (Python/ML for M1, edits, docs, PRs). **Track B — local or the dedicated dev EC2**: the full Docker stack and backend/integration/E2E tests via `scripts/dev-setup.sh`. Rationale: the validated findings above. This also makes the dev-EC2 backlog task a **real dependency** for the Docker loop, not a nice-to-have — its priority is raised and its rationale updated.

### D4. No Docker dependency for Track A
M1 (and other Python work) runs in a plain venv on the sandbox host, where the proxy CA is trusted. No daemon start, no network widening, no Dockerfile hacks. The web environment needs no special setup script for Track A, and **no AWS credentials** (no secrets store; env vars are visible to environment editors).

### D5. Idempotency
`scripts/dev-setup.sh` is safe to re-run; it only pulls/builds images and never starts services or mutates data.

## Risks / Trade-offs

- **Quota**: cloud sessions draw on the shared Claude usage quota (no separate VM charge). Doc advises one task at a time on Pro.
- **Two environments to keep in sync**: mitigated by the single portable `scripts/dev-setup.sh` (same stack on local and EC2) and a documented workflow.
- **Dev EC2 not yet provisioned**: until then, the Docker loop is local-only; acceptable for M1, which is non-Docker.
