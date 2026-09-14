# Spec Delta: deploy-pipeline

## ADDED Requirements

### Requirement: The deploy re-asserts host-level TLS renewal configuration
The deploy workflow SHALL install the version-controlled TLS renewal
configuration onto the production instance on every deployment, so that host
configuration is continuously restored from the repository rather than typed once
into an interactive session.

The deploy SHALL also report certificate health by running the same expiry check
the scheduled workflow runs. That report SHALL retry a transient failure before
failing the run — a network fault on the runner must not mark a successful
production deploy as failed — and SHALL fail the run when the certificate is
genuinely inside its threshold. Neither outcome reverts the deploy.

The installation SHALL be idempotent, SHALL run after the application has been
confirmed healthy, and SHALL NOT be able to prevent or roll back an application
deploy. It SHALL nevertheless fail the workflow run when it cannot guarantee
renewal — in particular when the binary named by the installed unit is absent or
not executable — because a warning that does not fail anything is how the
preceding renewal failure survived thirty consecutive nights.

#### Scenario: A deployment installs and enables the renewal schedule
- **WHEN** a deployment runs
- **THEN** the renewal unit, timer and deploy hook are installed from the
  repository checkout on the instance
- **AND** the timer is enabled and its next scheduled run is reported in the run
  log

#### Scenario: Drift introduced on the host is corrected
- **WHEN** the installed unit, timer or hook on the instance differs from the
  repository
- **THEN** the next deployment overwrites it with the repository's version

#### Scenario: A renewal install failure is loud but not blocking
- **WHEN** the renewal configuration cannot be installed or the certbot binary it
  names is missing
- **THEN** the application deploy and its health check have already completed and
  are not reverted
- **AND** the workflow run fails, reporting the reason

#### Scenario: A transient check failure does not fail a successful deploy
- **WHEN** the certificate health check fails once because of a network fault on
  the runner
- **THEN** it is retried before the run is failed
- **AND** a deploy that has already passed its health check is not reverted

#### Scenario: A certificate inside the threshold fails the run
- **WHEN** the served certificate has fewer days remaining than the threshold
- **THEN** every attempt fails and the workflow run is marked failed
- **AND** the deployed application keeps running

#### Scenario: Repeated deployments change nothing
- **WHEN** two deployments run in succession with no change to the renewal files
- **THEN** the second leaves the same units installed and enabled, and reports
  the same state
