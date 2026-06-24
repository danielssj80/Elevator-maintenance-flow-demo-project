# Design: cloud-dev-workflow

## Context

Claude Code on the web runs each session in an Anthropic-managed cloud sandbox (Ubuntu 24.04) with `git`, `docker`, and `docker compose` pre-installed, cloned from the GitHub repo. Two mechanisms shape per-repo setup:

- **Environment setup script** — attached to the cloud environment (configured in the web UI), runs once before Claude launches; its filesystem result is **snapshotted/cached** (~7 days) so later sessions skip it. Cloud-only.
- **SessionStart hook** — committed to the repo's `.claude/settings.json`, runs every session (local + cloud).

Network access has levels None / **Trusted** / Full / Custom; Trusted already allows GitHub, npm/PyPI, and Docker Hub. The GitHub proxy restricts `git push` to the current working branch. There is **no secrets store yet** — environment variables are visible to anyone who can edit the environment.

## Goals

1. One setup primitive that works in the web sandbox, a future dev EC2, and locally (portability is an explicit project requirement).
2. Zero new production risk; rely on existing `main` protection + the branch-scoped push.
3. Keep cloud sessions cheap to start (use the cached environment, not per-session rebuilds).

## Key Decisions

### D1. Portable `scripts/dev-setup.sh`, not UI-only setup
The setup logic lives in the repo as `scripts/dev-setup.sh`. The cloud environment's setup script is a one-liner (`bash scripts/dev-setup.sh`). This makes the same setup reusable on the dev EC2 and locally with no rewrite — a drop-in for the "Provision dev EC2" Backlog task. **Alternative rejected**: pasting the full setup into the web UI setup script (not portable, not version-controlled).

### D2. Setup script (cached), not a SessionStart hook
Image build/pull goes through the environment setup script so it runs once and is captured in the environment snapshot; subsequent sessions start fast. A `SessionStart` hook would re-run every session and rebuild images needlessly. **Decision: no SessionStart hook** (also recorded in the enriched Notion task). The cache stores files, not running processes, so Claude still starts containers per session — `dev-setup.sh` only prepares images, it does not leave services running.

### D3. Network access = Trusted; no AWS creds in the cloud
Trusted covers everything dev/test needs (GitHub, PyPI, Docker Hub). Because there is no secrets store and env vars are visible to environment editors, **no AWS/Bedrock credentials are placed in the cloud environment**. The backend's briefing endpoint already has a deterministic fallback, and tests mock Bedrock, so live AWS is unnecessary in cloud sessions. Exercising the live briefing endpoint from the cloud (Custom network + temporary creds) is out of scope.

### D4. Idempotency
`dev-setup.sh` must be safe to re-run (the cache rebuilds on setup-script or allowed-host changes, ~weekly expiry, and humans will run it ad hoc). It only pulls/builds images and must not mutate running services or data.

### D5. Compose CLI: support both v2 and v1
The project convention (predating cloud sessions) is the `docker-compose` **v1** binary, which is what the production host and current laptops use. The Claude Code web sandbox, however, ships the `docker compose` **v2** plugin and may not have the v1 binary. Hard-coding either one breaks one of the target environments. **Decision**: `scripts/dev-setup.sh` and the documented commands **detect** the available CLI (prefer `docker compose` v2, fall back to `docker-compose` v1) and use it. This is the change that actually makes the workflow portable to the web sandbox. (Caught in adversarial review: the initial draft hard-required v1 and would have failed in the sandbox; the documented test command also mis-cased the Compose project name. Both fixed: the project name used for the default network/image is the **lowercased** repo directory name.)

## Risks / Trade-offs

- **Quota**: cloud sessions draw on the shared Claude usage quota (no separate VM compute charge). Mitigation: doc advises one task at a time on Pro.
- **Docker base image**: the sandbox does not allow replacing its base image; we run our images as side-containers via `docker compose`, which fits this project. No mitigation needed.
- **Cache staleness**: setup re-runs ~weekly or on config change; acceptable.
