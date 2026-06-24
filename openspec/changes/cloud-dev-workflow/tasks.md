# Tasks: cloud-dev-workflow

> Infrastructure/docs-only change: no backend/frontend source, no DB schema, no UI, no API surface.
> TDD service-level steps and Alembic migration do not apply (no application code).
> E2E Playwright step does not apply (no frontend change).
> "Endpoint testing" maps to running `scripts/dev-setup.sh` and the backend suite in Docker as the verification (AGENT MUST EXECUTE).

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/cloud-dev-workflow` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. Setup primitive: `scripts/dev-setup.sh`

- [x] 1.1 Add `scripts/dev-setup.sh`: idempotent; `docker-compose pull db` + `docker-compose build` for the dev/test images; `set -euo pipefail`; clear echo of each step; do NOT start services
- [x] 1.2 Make it executable (`chmod +x`) and host-agnostic (resolves repo root from the script location)
- [x] 1.3 Confirm it uses `docker-compose` (v1) per project convention, not `docker compose`

## 2. Documentation: `docs/dev-workflow.md` (+ cross-reference)

- [x] 2.1 Write `docs/dev-workflow.md`: branch → PR → review/merge → auto-deploy; `main` is protected (PR required, enforce_admins, no direct/force push)
- [x] 2.2 Document cloud-environment setup: connect GitHub repo; network access **Trusted**; setup script = `bash scripts/dev-setup.sh`; no AWS creds in the environment (no secrets store; Bedrock falls back)
- [x] 2.3 Document running the backend test suite in Docker; the shared Claude usage-quota note (one task at a time on Pro); `--remote` / `--teleport`
- [x] 2.4 Document portability: the same `scripts/dev-setup.sh` is the drop-in for the future dev EC2
- [x] 2.5 Add a reference to `docs/dev-workflow.md` from `docs/base-standards.md`

## 3. Verification (MANDATORY — AGENT MUST EXECUTE)

- [x] 3.1 Run `scripts/dev-setup.sh` locally in Docker; confirm exit 0 and images ready
- [x] 3.2 Re-run it to confirm idempotency (exit 0, no services started)
- [x] 3.3 Run the backend unit suite in-Docker as a regression baseline: **22 passed, 0 failed**
- [x] 3.4 Create `reports/2026-06-24-step-3-verification.md` documenting the runs

## 4. Review Existing Tests (MANDATORY)

- [x] 4.1 Reviewed the backend test suite — no application code touched, nothing affected
- [x] 4.2 Confirmed no test updates required; noted in the step-3 report

## 5. E2E Testing with Playwright MCP

- [x] 5.1 Not applicable — no frontend change. Noted in the step-3 report.

## 6. Cloud round-trip evidence (workflow validation)

- [ ] 6.1 After merge, start a real Claude Code web session for the repo with the documented environment; run `dev-setup.sh` + the backend suite in the sandbox; open a throwaway PR from the session to prove the branch-scoped push; record evidence in a report
      (Depends on the user connecting the repo in claude.ai/code — manual step. Deferred to post-merge.)

## 7. Update Technical Documentation (MANDATORY)

- [x] 7.1 `docs/dev-workflow.md` + `docs/base-standards.md` reference complete and accurate
- [x] 7.2 Confirmed no `docs/api-spec.yml` or `docs/data-model.md` changes are needed (no API/entity change)
- [ ] 7.3 Update the Notion task and move it to Done (after merge)
