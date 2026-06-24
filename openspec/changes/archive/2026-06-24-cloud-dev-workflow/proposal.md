# Proposal: cloud-dev-workflow

## Why

All development on this project currently depends on the local machine. We want to develop from **Claude Code on the web** (claude.ai/code) — directly against the GitHub repo, with no local-machine dependency — so feature work (starting with M1) can happen from anywhere.

Production (`https://elevator.dsaavedra.dev`) auto-deploys on every push to `main`. Two safety properties protect it and are leveraged here: `main` branch protection (PR required, `enforce_admins`, no direct/force push) and the web sandbox's GitHub proxy, which restricts every cloud session to pushing **only its working branch**. A cloud session therefore cannot reach `main` except through a reviewed PR.

**Empirical finding (validated live in a real web session):** the Claude Code web sandbox is **not a practical Docker host**. The daemon is not auto-started; its setup script does not run from the repo root; `Trusted` network access blocks Docker Hub's CDN; and — the real wall — `pip`/`npm` **inside a `docker build`** fail TLS verification because the sandbox's security proxy does MITM interception with a CA that build containers do not trust. The sandbox **does** run language toolchains directly (host `pip install xgboost scikit-learn pandas` succeeds). So this change adopts a **two-track** workflow instead of pretending the full Docker stack runs in the cloud.

## What Changes

- **Track A — Claude Code on the web (non-Docker)**: used for Python/ML work (M1 trains offline — no Docker, no DB, no stack), code edits, docs, and opening PRs. Documented setup that does **not** rely on Docker.
- **Track B — local or the dedicated dev EC2 (full Docker)**: the Docker Compose stack and the backend/integration/E2E tests run here, via the portable `scripts/dev-setup.sh`.
- Add `scripts/dev-setup.sh`: an **idempotent**, host-agnostic primitive that prepares the dev/test Docker stack (Compose `pull` + `build`), auto-detecting the Compose CLI (`docker compose` v2 / `docker-compose` v1). Verified locally; reusable on the dev EC2 with no changes. (Not for the web sandbox — see the Docker finding.)
- Add `docs/dev-workflow.md`: the two-track guide — branch → PR → review/merge → auto-deploy; what each track is for; the non-Docker web-session setup; running the Docker stack/tests on local/EC2; the validated sandbox constraints; `--remote` / `--teleport`; the shared-quota note.
- Cross-reference the new doc from `docs/base-standards.md`.
- Carries the already-made `CLAUDE.md` §7 edit (planning model Fable → Opus 4.8; routine → Sonnet).
- No backend, frontend, API, or DB schema changes.

## Capabilities

### Added Capabilities

- `dev-workflow`: a documented, production-safe, two-track development workflow — Claude Code on the web for non-Docker work, local/EC2 for the full Docker stack — backed by a portable dev-stack setup primitive.

## Impact

- **New files**: `scripts/dev-setup.sh`, `docs/dev-workflow.md`
- **Modified files**: `docs/base-standards.md`, `CLAUDE.md`
- **Cloud environment config**: documented (web UI). For non-Docker/M1 work no special setup is needed beyond a Python venv; **no AWS creds** in the environment.
- **Application code**: none. **AWS / IAM**: none.

## Out of Scope

- Running the full **Docker Compose stack inside the web sandbox** — proven impractical (no practical docker-in-docker: MITM-proxy TLS failures in image builds). The dev EC2 backlog task is the home for the Docker loop.
- A previewable **staging** environment (decided against; PR + branch protection suffice).
- **Provisioning** the dedicated dev EC2 (separate, now-elevated backlog task — this change keeps the setup portable for it and documents why it is needed).
- Secrets management / live Amazon Bedrock from cloud sessions.
- Application feature work (M1 etc.) — runs on top of this workflow.
