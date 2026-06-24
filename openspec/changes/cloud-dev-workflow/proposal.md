# Proposal: cloud-dev-workflow

## Why

All development on this project currently depends on the local machine. We want to be able to run the full development flow from **Claude Code on the web** (claude.ai/code) — working directly against the GitHub repo, with no local-machine dependency — so feature work (starting with M1) can happen from anywhere, including mobile monitoring.

The risk this must respect: production (`https://elevator.dsaavedra.dev`) auto-deploys on every push to `main` (GitHub Actions → OIDC → SSM). Two safety properties already protect it and are leveraged here rather than re-built: `main` branch protection (PR required, `enforce_admins`, no direct/force push) and the web sandbox's GitHub proxy, which restricts every cloud session to pushing **only its working branch**. A cloud session therefore cannot reach `main` except through a reviewed PR.

What is missing is the project-side glue: a reproducible way to bring up the dev/test stack inside a cloud session, the environment configuration to do it, and the documentation tying it together — kept portable so a future dedicated dev EC2 is a drop-in.

## What Changes

- Add `scripts/dev-setup.sh`: an **idempotent**, host-agnostic script that prepares the dev/test Docker stack (Compose `pull` for `db`, `build` for the app images). It is the single setup primitive, runnable identically in the web sandbox (invoked from the environment *setup script*), on a future dev EC2, and on a laptop. It **auto-detects the Compose CLI** (`docker compose` v2 / `docker-compose` v1) so it runs in the sandbox (v2) and on the production-style host (v1) alike. Final proof that it runs end-to-end *inside the web sandbox* is the post-merge round-trip (task 6.1), not yet executed.
- Add `docs/dev-workflow.md`: the canonical guide — branch → PR → review/merge → auto-deploy; how to connect the repo and configure the cloud environment (network access **Trusted**, setup script calling `dev-setup.sh`); how to run backend tests in Docker; `--remote` / `--teleport`; the shared-quota note; and portability to the dev EC2.
- Cross-reference the new doc from `docs/base-standards.md`.
- No backend, frontend, API, or DB schema changes.

This change also carries the already-made `CLAUDE.md` §7 edit (planning model Fable → Opus 4.8, routine → Sonnet), which was left uncommitted pending this branch.

## Capabilities

### Added Capabilities

- `dev-workflow`: a documented, reproducible, production-safe development workflow runnable from Claude Code on the web, backed by a portable dev-stack setup primitive.

## Impact

- **New files**: `scripts/dev-setup.sh`, `docs/dev-workflow.md`
- **Modified files**: `docs/base-standards.md` (reference the new doc), `CLAUDE.md` (§7 planning model, already edited)
- **Cloud environment config**: one-time, in the claude.ai/code web UI (network = Trusted; setup script = `bash scripts/dev-setup.sh`). Documented, not code.
- **Application code**: none
- **AWS / IAM**: none

## Out of Scope

- A previewable **staging** environment (explicitly decided against; PR + branch protection suffice).
- **Provisioning** the dedicated dev EC2 (separate Backlog task — this change only keeps the setup portable for it).
- A `SessionStart` hook for auto-setup (decided against — would rebuild images every session; the cached environment setup script is used instead).
- Secrets management / live Amazon Bedrock from cloud sessions (dev/test runs without AWS creds; the briefing endpoint uses its deterministic fallback).
- Any application feature work (M1 etc.) — that runs on top of this workflow afterwards.
