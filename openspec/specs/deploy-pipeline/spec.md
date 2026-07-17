# Spec: deploy-pipeline

## Purpose

Automated GitHub → AWS deployment for the Elevator Maintenance application. A push to `main` deploys to the production EC2 instance via AWS SSM Run Command, authenticated with GitHub OIDC (no long-lived credentials, no SSH).

## Requirements
### Requirement: Images are built in CI and published to GHCR
The system SHALL build the `elevator-backend` and `elevator-frontend` Docker images in a GitHub Actions workflow on every push to `main`, and SHALL push them to GHCR tagged with the commit SHA and `latest`.

#### Scenario: Push to main builds and publishes both images
- **WHEN** a commit is pushed to `main`
- **THEN** the build workflow builds `elevator-backend` and `elevator-frontend`
- **AND** pushes each to `ghcr.io/danielssj80/<image>` tagged `latest` and `${{ github.sha }}`

#### Scenario: Build failure blocks deployment
- **WHEN** the build workflow fails (e.g. a Dockerfile or dependency error)
- **THEN** the deploy workflow does not run
- **AND** production continues serving the previously deployed images

### Requirement: Old GHCR image versions are cleaned up
The system SHALL retain only the `latest` tag and the most recent 10 commit-SHA-tagged versions per GHCR package, deleting older versions automatically.

#### Scenario: Retention cleanup runs after a successful push
- **WHEN** the build workflow publishes a new image version
- **THEN** a cleanup step removes GHCR versions beyond the retained `latest` + 10 most recent SHA tags for that package

### Requirement: Deployment only runs after images are published
The deploy workflow SHALL trigger only after the image build workflow completes successfully for the same commit, ensuring the instance never pulls a partially published or stale image set.

#### Scenario: Deploy waits for build completion
- **WHEN** a commit is pushed to `main`
- **THEN** the deploy workflow starts only after the build workflow reports a successful conclusion for that commit

#### Scenario: Deploy does not run if build fails or is skipped
- **WHEN** the build workflow's conclusion is not `success`
- **THEN** the deploy workflow does not execute its deploy steps

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
The workflow SHALL deploy by sending an SSM `AWS-RunShellScript` command to the production EC2 instance. The command SHALL update the working copy to the latest `main` and recreate the stack with `docker compose pull` followed by `docker compose up -d`. The instance SHALL NOT build any Docker image during deployment. The Compose file list SHALL always include `docker-compose.prod.yml` and SHALL additionally include the portfolio override `/opt/portfolio/docker-compose.portfolio.yml` **only when that file exists**, so a co-located static site sharing the nginx container is preserved across Elevator deploys and the Elevator deploy still works unchanged when the portfolio is absent. When the override is included, the workflow SHALL validate the merged nginx configuration (`nginx -t` in a throwaway container) **before** recreating the shared nginx, and SHALL fall back to deploying Elevator alone (override dropped) if the merged configuration is invalid, so a broken co-located config cannot take Elevator down. Port 22 SHALL remain closed.

#### Scenario: Successful remote deployment
- **WHEN** the SSM command runs on the instance
- **THEN** the project working copy is updated to the pushed commit
- **AND** the `backend` and `frontend` images are pulled from GHCR rather than built locally
- **AND** all services in `docker-compose.prod.yml` are recreated and restarted with the pulled images
- **AND** Alembic migrations run via the existing `migrate` service using the pulled backend image

#### Scenario: No image build occurs on the instance
- **WHEN** the deployment runs
- **THEN** no `docker compose build` or `--build` step executes on the EC2 instance
- **AND** the instance's available memory is not consumed by a `vite build` or Python dependency build during deploy

#### Scenario: Portfolio override included when present
- **WHEN** `/opt/portfolio/docker-compose.portfolio.yml` exists at deploy time
- **THEN** the `docker compose up` invocation includes both `docker-compose.prod.yml` and the portfolio override
- **AND** the recreated nginx container retains the portfolio's mounts (static root and `conf.d` drop-in)

#### Scenario: Portfolio absent does not break the deploy
- **WHEN** `/opt/portfolio/docker-compose.portfolio.yml` does not exist at deploy time
- **THEN** the `docker compose up` invocation uses only `docker-compose.prod.yml`
- **AND** the Elevator deployment completes exactly as before

#### Scenario: Broken co-located config does not take Elevator down
- **WHEN** the portfolio override is present but the merged nginx configuration fails `nginx -t` at deploy time (e.g. a broken `portfolio.conf` is on disk)
- **THEN** the workflow drops the portfolio override and recreates nginx with `docker-compose.prod.yml` only
- **AND** the Elevator site stays up
- **AND** a warning is emitted to the deploy log

#### Scenario: No SSH involved
- **WHEN** the deployment runs
- **THEN** no SSH connection is opened and the security group keeps port 22 closed

### Requirement: Deployment failures fail the workflow
The workflow SHALL poll the SSM command invocation until it reaches a terminal status, SHALL print the remote stdout and stderr to the Actions log, and SHALL exit non-zero if the command status is not `Success`. Printing the logs SHALL NOT itself be able to fail the job — only the status assertion determines the result.

#### Scenario: Remote command fails
- **WHEN** the remote deploy command exits non-zero (e.g. a Docker build error)
- **THEN** the workflow job fails
- **AND** the remote command output is visible in the GitHub Actions log

#### Scenario: Remote command succeeds
- **WHEN** the remote deploy command completes with status `Success`
- **THEN** the workflow proceeds to the smoke check step

#### Scenario: Transient log-fetch error does not fail a good deploy
- **WHEN** the command status is `Success` but fetching the remote stdout/stderr for logging errors transiently
- **THEN** the workflow still reports success (log fetch is guarded; only the status assertion decides)

### Requirement: Post-deploy smoke check
After a successful deployment the workflow SHALL verify that the public application is healthy before reporting success.

#### Scenario: Smoke check passes
- **WHEN** the deployment completes successfully
- **THEN** the workflow requests `https://elevator.dsaavedra.dev/health` and receives HTTP 200 with `{"status": "ok"}`

#### Scenario: Smoke check fails
- **WHEN** the health endpoint does not return 200 within the retry window
- **THEN** the workflow job fails

### Requirement: Concurrent deploys are serialized on the host
Because the nginx container is shared with a co-located site deployed from a separate repository, the workflow SHALL wrap the `docker compose ... up` invocation in a host-level advisory lock with a bounded wait (`flock -w 600 /opt/deploy.lock`) so that the Elevator and portfolio pipelines cannot mutate Docker state concurrently. If the lock cannot be acquired within the timeout the deploy SHALL fail rather than hang indefinitely. The lock SHALL be released automatically when the deploy process exits.

#### Scenario: Two deploys overlap in time
- **WHEN** an Elevator deploy and a portfolio deploy reach their `docker compose up` step at the same time
- **THEN** one acquires `/opt/deploy.lock` and runs to completion while the other waits
- **AND** neither deploy corrupts the shared Docker/nginx state

#### Scenario: Lock is released after a deploy
- **WHEN** a deploy holding `/opt/deploy.lock` finishes or its process is killed
- **THEN** the lock is released so the next deploy can acquire it without manual cleanup

#### Scenario: Lock wait is bounded
- **WHEN** a deploy cannot acquire `/opt/deploy.lock` within the `flock -w` timeout (600 s)
- **THEN** the deploy fails (non-zero) rather than blocking indefinitely

---

## Files

| File | Purpose |
|---|---|
| `.github/workflows/build-images.yml` | Build workflow: builds `elevator-backend`/`elevator-frontend`, pushes to GHCR, cleans up old versions |
| `.github/workflows/deploy.yml` | Deploy workflow: triggered by `workflow_run` on build success → OIDC auth → SSM Run Command (pull + up) → poll/propagate → smoke check |

---

## Constraints

- Auth: GitHub OIDC → IAM role `github-actions-deploy`, trust scoped to `repo:danielssj80/Elevator-maintenance-flow-demo-project:ref:refs/heads/main`
- IAM permissions (least privilege): `ssm:SendCommand` on the production instance + `AWS-RunShellScript` document, and `ssm:GetCommandInvocation`
- No SSH; port 22 stays closed (deploy uses the SSM channel)
- Region `eu-north-1`, instance `i-01b732fefb1dd6303`, app directory `/opt/elevator`
- Concurrency group serializes production deploys (`cancel-in-progress: false`)
- Repo configuration via GitHub Actions variables: `AWS_REGION`, `EC2_INSTANCE_ID`, `AWS_DEPLOY_ROLE_ARN`

---

## Out of Scope

- Multi-arch image builds (runner and instance are both `linux/amd64`)
- Private registry / GHCR pull authentication on the instance (images are public, matching the public repo)
- Running tests in CI before deploy
- Staging environment, blue/green, zero-downtime, automated rollback
- Deploy notifications
- Version-asserting smoke check (liveness only — see backlog)
