# Proposal: github-aws-deploy-pipeline

## Why

The application is live at `https://elevator.dsaavedra.dev`, but every deployment is manual: open an SSM session, pull the code, rebuild the stack. This is slow, error-prone, and leaves the production state dependent on remembering the right commands. A CI/CD pipeline closes the last gap of milestone M3 (AWS Deployment) and makes `main` the single source of truth for what runs in production.

## What Changes

- Add a GitHub Actions workflow (`.github/workflows/deploy.yml`) that triggers on every push to `main`.
- The workflow authenticates to AWS via **OIDC federation** — no long-lived AWS credentials or SSH keys stored in GitHub.
- Deployment is executed remotely through **AWS SSM Run Command** (`AWS-RunShellScript`): the EC2 instance pulls the latest `main` and runs `docker compose -f docker-compose.prod.yml up --build -d`.
- The workflow polls the SSM command result, surfaces its stdout/stderr in the Actions log, and fails the job if the remote command fails.
- A final smoke check verifies `https://elevator.dsaavedra.dev/health` returns 200 after deployment.
- One-time AWS IAM setup (manual, documented in design): GitHub OIDC identity provider + a deploy role with least-privilege SSM permissions, trust-scoped to this repository's `main` branch.

## Capabilities

### New Capabilities

- `deploy-pipeline`: Automated GitHub → AWS deployment on push to `main` via OIDC-authenticated SSM Run Command, with failure propagation and post-deploy smoke check.

### Modified Capabilities

<!-- none — production-deployment requirements are unchanged; this change only removes
     "CI/CD pipeline" from its out-of-scope list, which is informational, not a requirement -->

## Impact

- **New files**: `.github/workflows/deploy.yml`
- **AWS (manual, one-time)**: IAM OIDC provider for `token.actions.githubusercontent.com`; IAM role `github-actions-deploy` with `ssm:SendCommand` (scoped to the instance and the `AWS-RunShellScript` document) and `ssm:GetCommandInvocation`
- **GitHub repo settings**: Actions variables `AWS_REGION`, `EC2_INSTANCE_ID`, `AWS_DEPLOY_ROLE_ARN`
- **Application code**: none — backend and frontend untouched
- **Runtime constraint**: the `t3.micro` instance (1 GB RAM) must build both Docker images; the deploy command must account for limited memory
