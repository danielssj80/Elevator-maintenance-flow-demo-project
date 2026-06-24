# Spec Delta: dev-workflow

## ADDED Requirements

### Requirement: Portable dev-stack setup primitive
The project SHALL provide an idempotent setup script (`scripts/dev-setup.sh`) that prepares the development/test Docker stack on any Linux host with a working Docker daemon and a Compose CLI. It SHALL auto-detect the Compose CLI (prefer `docker compose` v2, fall back to `docker-compose` v1), pull the database image, build the application images, be safe to run repeatedly, and NOT start services or mutate persisted data. It is intended for **local machines and the dedicated dev EC2**; it is not used in the Claude Code web sandbox, which cannot run Docker builds (see "Two-track development workflow").

#### Scenario: Fresh host preparation
- **WHEN** `scripts/dev-setup.sh` is run on a host with a running Docker daemon and a Compose CLI but no project images
- **THEN** the database image is pulled and the application images are built
- **AND** the script exits 0 with the dev/test stack ready to start

#### Scenario: Idempotent re-run
- **WHEN** `scripts/dev-setup.sh` is run again on a host that already has the images
- **THEN** it completes successfully without error
- **AND** it does not start services or alter existing data

#### Scenario: Compose CLI auto-detection
- **WHEN** the host provides `docker compose` (v2) or `docker-compose` (v1)
- **THEN** the script detects and uses whichever is present
- **AND** fails with a clear message only if neither is available

### Requirement: Production-safe cloud development
A change developed in a Claude Code web (cloud) session SHALL be deliverable only through a reviewed pull request; it SHALL NOT be possible to push directly to `main` or to deploy to production from a cloud session. This is guaranteed by `main` branch protection (PR required, `enforce_admins`, no direct or force push) together with the web sandbox GitHub proxy restricting each session's push to its own working branch.

#### Scenario: Cloud session pushes only its working branch
- **WHEN** a cloud session attempts to push
- **THEN** the push targets the session's feature branch
- **AND** a push to `main` is rejected

#### Scenario: Production reached only via PR merge
- **WHEN** a feature branch from a cloud session is ready
- **THEN** it reaches production only after the change is merged into `main` via pull request
- **AND** the existing push-to-`main` deploy pipeline runs on that merge

### Requirement: Documented two-track development workflow
The repository SHALL document a two-track workflow in `docs/dev-workflow.md`, referenced from `docs/base-standards.md`. **Track A (Claude Code on the web)** is for non-Docker work — Python/ML (e.g. M1 offline training), code edits, docs, and opening PRs — and the doc SHALL state that the web sandbox cannot practically run the Docker stack and SHALL record the validated constraints (daemon not auto-started; setup script CWD is not the repo root; `Trusted` network blocks Docker Hub's CDN; image builds fail TLS through the sandbox's MITM proxy). **Track B (local machine or the dedicated dev EC2)** is for the full Docker Compose stack and the backend/integration/E2E tests, via `scripts/dev-setup.sh`. The doc SHALL also cover the branch → PR → review/merge → auto-deploy flow (and that `main` is protected), `--remote` / `--teleport`, and the shared Claude usage-quota note.

#### Scenario: Non-Docker work from the web
- **WHEN** a developer follows Track A for M1-style Python work
- **THEN** they can create a venv, install Python dependencies, run the work, and open a PR from the web sandbox without Docker

#### Scenario: Docker stack on local or EC2
- **WHEN** a developer needs the full stack or backend/integration tests
- **THEN** the doc directs them to Track B (local or dev EC2) and `scripts/dev-setup.sh`

#### Scenario: Standards point to the workflow
- **WHEN** a developer reads `docs/base-standards.md`
- **THEN** it links to `docs/dev-workflow.md` as the development-workflow reference
