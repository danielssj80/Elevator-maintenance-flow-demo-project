# Spec Delta: deploy-pipeline

## ADDED Requirements

### Requirement: Push to main triggers automated deployment
The system SHALL run a GitHub Actions deploy workflow on every push to the `main` branch, with no manual intervention required.

#### Scenario: Workflow triggers on push to main
- **WHEN** a commit is pushed to `main`
- **THEN** the `deploy` workflow starts automatically in GitHub Actions

#### Scenario: Other branches do not trigger deployment
- **WHEN** a commit is pushed to any branch other than `main`
- **THEN** the deploy workflow does not run

### Requirement: GitHub authenticates to AWS via OIDC
The workflow SHALL authenticate to AWS by assuming an IAM role through GitHub's OIDC identity provider. The repository SHALL NOT store any long-lived AWS credentials or SSH keys.

#### Scenario: Workflow assumes the deploy role
- **WHEN** the workflow runs on `main`
- **THEN** it obtains temporary AWS credentials by assuming the deploy role via OIDC
- **AND** no `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or SSH private key exists in the repository secrets

#### Scenario: Trust policy rejects other sources
- **WHEN** a workflow from another repository or a non-`main` ref attempts to assume the deploy role
- **THEN** AWS STS denies the AssumeRoleWithWebIdentity request

### Requirement: Deployment executes via SSM Run Command
The workflow SHALL deploy by sending an SSM `AWS-RunShellScript` command to the production EC2 instance. The command SHALL update the working copy to the latest `main` and recreate the stack with `docker compose -f docker-compose.prod.yml up --build -d`. Port 22 SHALL remain closed.

#### Scenario: Successful remote deployment
- **WHEN** the SSM command runs on the instance
- **THEN** the project working copy is updated to the pushed commit
- **AND** all services in `docker-compose.prod.yml` are rebuilt and restarted
- **AND** Alembic migrations run via the existing `migrate` service

#### Scenario: No SSH involved
- **WHEN** the deployment runs
- **THEN** no SSH connection is opened and the security group keeps port 22 closed

### Requirement: Deployment failures fail the workflow
The workflow SHALL poll the SSM command invocation until it reaches a terminal status, SHALL print the remote stdout and stderr to the Actions log, and SHALL exit non-zero if the command status is not `Success`.

#### Scenario: Remote command fails
- **WHEN** the remote deploy command exits non-zero (e.g. a Docker build error)
- **THEN** the workflow job fails
- **AND** the remote command output is visible in the GitHub Actions log

#### Scenario: Remote command succeeds
- **WHEN** the remote deploy command completes with status `Success`
- **THEN** the workflow proceeds to the smoke check step

### Requirement: Post-deploy smoke check
After a successful deployment the workflow SHALL verify that the public application is healthy before reporting success.

#### Scenario: Smoke check passes
- **WHEN** the deployment completes successfully
- **THEN** the workflow requests `https://elevator.dsaavedra.dev/health` and receives HTTP 200 with `{"status": "ok"}`

#### Scenario: Smoke check fails
- **WHEN** the health endpoint does not return 200 within the retry window
- **THEN** the workflow job fails
