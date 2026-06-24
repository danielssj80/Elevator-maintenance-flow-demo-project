# Spec Delta: dev-workflow

## ADDED Requirements

### Requirement: Portable dev-stack setup primitive
The project SHALL provide an idempotent setup script (`scripts/dev-setup.sh`) that prepares the development/test Docker stack on any Linux host with Docker and Docker Compose available. The script SHALL pull the database image and build the application images defined for the dev/test stack, SHALL be safe to run repeatedly, and SHALL NOT leave application services running or mutate persisted data. It SHALL exit non-zero if a required step fails.

#### Scenario: Fresh host preparation
- **WHEN** `scripts/dev-setup.sh` is run on a host with Docker and Docker Compose but no project images
- **THEN** the database image is pulled and the application images are built
- **AND** the script exits 0 with the dev/test stack ready to start

#### Scenario: Idempotent re-run
- **WHEN** `scripts/dev-setup.sh` is run again on a host that already has the images
- **THEN** it completes successfully without error
- **AND** it does not start services or alter existing data

#### Scenario: Portable across environments
- **WHEN** the script is run inside the Claude Code web sandbox, on the future dev EC2, or on a laptop
- **THEN** it produces the same ready dev/test stack with no per-environment edits

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

### Requirement: Documented cloud development workflow
The repository SHALL document the cloud development workflow in `docs/dev-workflow.md`, and `docs/base-standards.md` SHALL reference it. The documentation SHALL cover: the branch → PR → review/merge → auto-deploy flow and that `main` is protected; how to connect the repo and configure the cloud environment (network access **Trusted**; setup script invoking `scripts/dev-setup.sh`); how to run the backend test suite in Docker; moving sessions between web and terminal with `--remote` / `--teleport`; the shared Claude usage-quota note; and that the setup is portable to a future dedicated dev EC2.

#### Scenario: A developer can start from the doc alone
- **WHEN** a developer follows `docs/dev-workflow.md`
- **THEN** they can start a cloud session, bring up and test the stack in Docker, and open a PR
- **AND** they do not need undocumented tribal knowledge

#### Scenario: Standards point to the workflow
- **WHEN** a developer reads `docs/base-standards.md`
- **THEN** it links to `docs/dev-workflow.md` as the cloud/dev workflow reference
