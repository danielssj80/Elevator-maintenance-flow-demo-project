# Tasks: github-aws-deploy-pipeline

> Infrastructure-only change: no backend/frontend source, no DB schema, no UI changes.
> TDD service-level steps and Alembic migration do not apply (no application code).
> E2E Playwright step does not apply (no frontend change).
> Endpoint testing maps to the production smoke verification (AGENT MUST EXECUTE).

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/github-aws-deploy-pipeline` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. AWS: OIDC Provider and Deploy Role (one-time, via AWS CLI)

- [x] 1.1 OIDC provider created: `arn:aws:iam::150911080650:oidc-provider/token.actions.githubusercontent.com` (none existed)
- [x] 1.2 Created IAM role `github-actions-deploy` with trust scoped to `repo:danielssj80/Elevator-maintenance-flow-demo-project:ref:refs/heads/main`
- [x] 1.3 Attached policy `ssm-deploy`: `ssm:SendCommand` on instance `i-01b732fefb1dd6303` + `AWS-RunShellScript` doc (eu-north-1), and `ssm:GetCommandInvocation`
- [x] 1.4 Verified trust conditions (aud=sts.amazonaws.com, sub pinned to main) — other repos/branches cannot assume
- [x] 1.5 Recorded: role ARN `arn:aws:iam::150911080650:role/github-actions-deploy`, region `eu-north-1`, instance `i-01b732fefb1dd6303`

## 2. GitHub: Repository Configuration

- [x] 2.1 Set Actions variables: `AWS_REGION=eu-north-1`, `EC2_INSTANCE_ID=i-01b732fefb1dd6303`, `AWS_DEPLOY_ROLE_ARN=arn:aws:iam::150911080650:role/github-actions-deploy`
- [x] 2.2 Confirm no AWS keys or SSH keys exist in repo secrets (`gh secret list`)

## 3. Workflow: deploy.yml

- [x] 3.1 Create `.github/workflows/deploy.yml`: trigger on push to `main`, `permissions: id-token: write, contents: read`, `concurrency` group to serialize deploys
- [x] 3.2 Step: assume role via `aws-actions/configure-aws-credentials@v4` with OIDC
- [x] 3.3 Step: `aws ssm send-command` (AWS-RunShellScript) running on the instance: `cd /opt/elevator && git fetch origin main && git reset --hard origin/main && docker compose -f docker-compose.prod.yml up --build -d` with execution timeout 1800 s
- [x] 3.4 Step: poll `aws ssm get-command-invocation` until terminal status; print remote stdout/stderr to the log; exit non-zero unless status is `Success`
- [x] 3.5 Step: smoke check — curl `https://elevator.dsaavedra.dev/health` with retries, fail if not 200
- [x] 3.6 Validate workflow syntax (actionlint via Docker — exit 0, no findings)

## 4. Review and Update Existing Tests (MANDATORY)

- [x] 4.1 Review backend test suite for anything affected by this change (expected: none — no application code touched)
- [x] 4.2 Confirm no test updates required; note it in the step-5 report

## 5. Unit Tests and DB State Verification (MANDATORY)

- [x] 5.1 Capture pre-test DB baseline (local dev DB table counts) — N/A, unit tests mock the repository layer
- [x] 5.2 Run full backend unit test suite (sanity: change must not break anything) — 8 passed
- [x] 5.3 Verify post-test DB state matches baseline — N/A, no DB access
- [x] 5.4 Create report `openspec/changes/github-aws-deploy-pipeline/reports/2026-06-14-step-5-unit-tests.md`

## 6. End-to-End Pipeline Verification (MANDATORY — AGENT MUST EXECUTE)

- [x] 6.1 PR #4 merged to `main` (user-approved) → run `27504696400` triggered automatically
- [x] 6.2 Run completed `success` in 28s — OIDC auth, SSM command, polling, and smoke check all passed
- [x] 6.3 Production verified: `/health` → 200 `{"status":"ok"}`; `/api/elevators` → 200 with 100 elevators (ELV-001 risk 0.91)
- [x] 6.4 Failure propagation confirmed via run log: polling step ends with `test "$STATUS" = "Success"` → non-Success fails the job
- [x] 6.5 Security group ingress is only TCP 80/443 — port 22 closed, no SSH used
- [x] 6.6 Created report `openspec/changes/github-aws-deploy-pipeline/reports/2026-06-14-step-6-pipeline-verification.md`

## 7. E2E Testing with Playwright MCP (NOT APPLICABLE)

- [x] 7.1 No frontend changes in this change — not applicable (no UI/workflow touched; pipeline verification in section 6 covers the change)

## 8. Update Technical Documentation (MANDATORY)

- [x] 8.1 Update `openspec/specs/production-deployment/spec.md` out-of-scope list at archive time (CI/CD no longer out of scope) — deferred to archive/spec-sync
- [x] 8.2 Documented the deploy pipeline in `docs/deployment.md`: CI/CD section (how deploys work, required vars/IAM, `gh run watch` for logs) + reframed manual deploy as rollback fallback
- [x] 8.3 `docs/api-spec.yml` and `docs/data-model.md`: no updates required (no API or entity changes)
