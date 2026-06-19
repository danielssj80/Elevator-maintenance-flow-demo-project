# Spec Delta: deploy-pipeline

## MODIFIED Requirements

### Requirement: Deployment executes via SSM Run Command
The workflow SHALL deploy by sending an SSM `AWS-RunShellScript` command to the production EC2 instance. The command SHALL update the working copy to the latest `main` and recreate the stack with `docker compose up --build -d`. The Compose file list SHALL always include `docker-compose.prod.yml` and SHALL additionally include the portfolio override `/opt/portfolio/docker-compose.portfolio.yml` **only when that file exists**, so a co-located static site sharing the nginx container is preserved across Elevator deploys and the Elevator deploy still works unchanged when the portfolio is absent. When the override is included, the workflow SHALL validate the merged nginx configuration (`nginx -t` in a throwaway container) **before** recreating the shared nginx, and SHALL fall back to deploying Elevator alone (override dropped) if the merged configuration is invalid, so a broken co-located config cannot take Elevator down. Port 22 SHALL remain closed.

#### Scenario: Successful remote deployment
- **WHEN** the SSM command runs on the instance
- **THEN** the project working copy is updated to the pushed commit
- **AND** all services in `docker-compose.prod.yml` are rebuilt and restarted
- **AND** Alembic migrations run via the existing `migrate` service

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

## ADDED Requirements

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
