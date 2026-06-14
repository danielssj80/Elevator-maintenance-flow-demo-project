# Design: github-aws-deploy-pipeline

## Context

The application is deployed at `https://elevator.dsaavedra.dev` on a single `t3.micro` EC2 instance (Amazon Linux 2023, 1 GB RAM). The instance is already SSM-managed: the SSM Agent runs, the instance profile includes `AmazonSSMManagedInstanceCore`, port 22 is closed, and the operator accesses the box via SSM Session Manager. The production stack runs from `docker-compose.prod.yml`, which includes a `migrate` service that applies Alembic migrations automatically on `up`.

Deployments are currently manual (SSM session + git pull + compose up). This change automates them. No application code (backend three-layer architecture, frontend service layer) is touched — this is purely CI/CD infrastructure.

## Goals / Non-Goals

**Goals:**
- Every push to `main` deploys to production automatically.
- Zero long-lived credentials in GitHub (no AWS keys, no SSH keys).
- Port 22 stays closed; deployment uses the existing SSM channel.
- Failures on the instance propagate to a red workflow with readable logs.
- Post-deploy smoke check against the public health endpoint.

**Non-Goals:**
- Container registry (ECR/Docker Hub) — images build on the instance.
- Running tests in CI before deploy.
- Staging environment, blue/green, zero-downtime, automated rollback.
- Deploy notifications.

## Decisions

### D1 — SSM Run Command over SSH

The instance is already SSM-managed and port 22 is closed. `aws ssm send-command` with the `AWS-RunShellScript` document executes the deploy script remotely with IAM auth and CloudTrail audit. Re-opening SSH and storing a private key in GitHub would be a security regression.

*Alternatives considered*: SSH + `appleboy/ssh-action` (requires opening port 22 and a key secret — rejected); self-hosted runner on the instance (zero credentials but consumes RAM on a 1 GB box and adds runner maintenance — rejected).

### D2 — OIDC federation over static AWS keys

GitHub's OIDC provider (`token.actions.githubusercontent.com`) lets the workflow assume an IAM role with short-lived credentials. Trust policy condition: `token.actions.githubusercontent.com:sub = repo:<owner>/<repo>:ref:refs/heads/main` — only this repo's `main` branch can assume the role.

*Alternative considered*: IAM user with access keys stored as secrets — works but reintroduces long-lived credentials; rejected.

### D3 — Least-privilege deploy role

The deploy role's permission policy allows only:
- `ssm:SendCommand` on the specific instance ARN and the `AWS-RunShellScript` document ARN
- `ssm:GetCommandInvocation` (read-only polling)

It cannot start sessions, touch other instances, or run other documents.

### D4 — Build on the instance, no registry

The stack is two small images on one box. Building in CI and pushing to ECR adds an AWS service, auth complexity, and image pull configuration for marginal benefit at this scale. `docker compose up --build -d` on the instance only recreates containers whose images changed.

*Mitigation for 1 GB RAM*: the instance already builds these images today during manual deploys, so this is proven to work. If builds start failing with OOM, fall back to `docker compose build` one service at a time before `up -d` (documented in tasks as a contingency, not implemented preemptively).

### D5 — Poll command invocation, don't fire-and-forget

`aws ssm send-command` returns immediately. The workflow polls `aws ssm get-command-invocation` until a terminal status (`Success`, `Failed`, `Cancelled`, `TimedOut`), prints `StandardOutputContent`/`StandardErrorContent` to the Actions log, and exits non-zero unless the status is `Success`. SSM truncates output at 24 KB per stream — acceptable; full logs remain on the instance via `docker compose logs`.

A generous SSM timeout (`--timeout-seconds` / execution timeout ≥ 900 s) covers slow image builds on the t3.micro.

### D6 — Smoke check in the workflow, not on the instance

After SSM reports success, the workflow curls `https://elevator.dsaavedra.dev/health` (with retries, since containers restart) from the GitHub runner. Checking from outside validates the full chain: DNS, TLS, nginx, backend.

### D7 — Repo configuration as Actions variables

`AWS_REGION`, `EC2_INSTANCE_ID`, and `AWS_DEPLOY_ROLE_ARN` are stored as GitHub Actions **variables** (not secrets) — none of them is sensitive (role ARN and instance ID are identifiers, not credentials). This keeps them visible in logs for debugging.

## Risks / Trade-offs

- [OOM during image build on 1 GB instance] → already proven to work in manual deploys; contingency: sequential `docker compose build` per service; last resort: add swap.
- [Brief downtime while containers restart] → acceptable for a portfolio demo; nginx `restart: always` recovers automatically.
- [SSM output truncated at 24 KB] → enough to see the failing step; full logs available on the instance.
- [git conflict on the instance working copy (locally modified files)] → deploy command uses `git fetch` + `git reset --hard origin/main` instead of `git pull` to make the working copy converge unconditionally.
- [Concurrent pushes racing] → GitHub Actions `concurrency` group on the workflow cancels/queues overlapping deploys.

## Migration Plan

1. One-time manual AWS setup (operator, via console or CLI): create the GitHub OIDC provider and the `github-actions-deploy` IAM role.
2. Configure the three Actions variables in the GitHub repo.
3. Commit `.github/workflows/deploy.yml` to a feature branch; merge to `main`.
4. The merge itself is the first end-to-end test of the pipeline.

**Rollback**: delete or disable the workflow file; manual deploys via SSM Session Manager keep working unchanged. To roll back a bad release: SSM session → `git reset --hard <previous-sha>` → `docker compose up --build -d`.

## Open Questions

- None — instance ID, region, and role ARN are known to the operator and supplied as repo variables.
