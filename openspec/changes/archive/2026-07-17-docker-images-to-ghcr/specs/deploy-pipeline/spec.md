# Spec Delta: deploy-pipeline

## ADDED Requirements

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

### Requirement: Concurrent builds are serialized
The build workflow SHALL run under a `concurrency` group so that two pushes to `main` cannot build and push images in parallel. This prevents the `latest` tag from being left pointing at an inconsistent pairing of backend/frontend images from different commits.

#### Scenario: Two pushes to main in quick succession
- **WHEN** a second commit is pushed to `main` while a build for an earlier commit is still running
- **THEN** the second build waits for the first to finish before starting
- **AND** at no point does `latest` reflect a backend image from one commit paired with a frontend image from another

## MODIFIED Requirements

### Requirement: Deployment executes via SSM Run Command
The workflow SHALL deploy by sending an SSM `AWS-RunShellScript` command to the production EC2 instance. The command SHALL update the working copy to the latest `main`, SHALL export `IMAGE_TAG` as the commit SHA of the build that triggered this deploy (`workflow_run.head_sha`), and SHALL recreate the stack with `docker compose -f docker-compose.prod.yml pull` followed by `docker compose -f docker-compose.prod.yml up -d`, so the images pulled are pinned to that specific commit's tag rather than to the shared mutable `latest` tag. The instance SHALL NOT build any Docker images during deployment. Port 22 SHALL remain closed.

#### Scenario: Successful remote deployment
- **WHEN** the SSM command runs on the instance
- **THEN** the project working copy is updated to the pushed commit
- **AND** the `backend` and `frontend` images are pulled from GHCR, tagged with the exact commit SHA that triggered the deploy, rather than built locally
- **AND** all services in `docker-compose.prod.yml` are recreated and restarted with the pulled images
- **AND** Alembic migrations run via the existing `migrate` service using the pulled backend image

#### Scenario: Deploy is pinned to the triggering commit's images, not to a moving `latest`
- **WHEN** a build for a later commit publishes a new `latest` while an earlier commit's deploy is in flight
- **THEN** the in-flight deploy still pulls the image pair tagged with its own commit SHA
- **AND** the deployed backend and frontend images are always the pair built together for the same commit

#### Scenario: No image build occurs on the instance
- **WHEN** the deployment runs
- **THEN** no `docker compose build` or `--build` step executes on the EC2 instance
- **AND** the instance's available memory is not consumed by a `vite build` or Python dependency build during deploy

#### Scenario: No SSH involved
- **WHEN** the deployment runs
- **THEN** no SSH connection is opened and the security group keeps port 22 closed

### Requirement: Deployment only runs after images are published
The deploy workflow SHALL trigger only after the image build workflow completes successfully for the same commit, ensuring the instance never pulls a partially published or stale image set.

#### Scenario: Deploy waits for build completion
- **WHEN** a commit is pushed to `main`
- **THEN** the deploy workflow starts only after the build workflow reports a successful conclusion for that commit

#### Scenario: Deploy does not run if build fails or is skipped
- **WHEN** the build workflow's conclusion is not `success`
- **THEN** the deploy workflow does not execute its deploy steps
