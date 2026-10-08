## ADDED Requirements

### Requirement: Production ingests telemetry and re-scores the fleet on its own
The system SHALL, in production and with no machine of the developer's running:
- store one telemetry reading per in-scope elevator every 30 minutes;
- re-score the fleet once a day.

The production application host SHALL gain no new process for this. The orchestrator and the scorer run as AWS Lambda functions outside the host.

#### Scenario: Readings arrive on schedule
- **WHEN** the ingest schedule has fired in production
- **THEN** each in-scope elevator has a new reading with source `n8n-telemetry-ingest`
- **AND** an unauthenticated request to the same endpoint is still rejected with 401

#### Scenario: The fleet is re-scored daily
- **WHEN** the daily schedule has fired in production
- **THEN** the dashboard shows risk scores computed that day
- **AND** the run reported which elevators it scored and which it skipped

#### Scenario: The host runs the same services as before
- **WHEN** the production compose definition is inspected
- **THEN** its services are exactly `db`, `migrate`, `backend`, `frontend` and `nginx`

### Requirement: Production secrets live in SSM Parameter Store, never in the repository
The system SHALL store the production ingest token and the Grafana Cloud OTLP credentials as SecureString parameters under `/elevator/`. It SHALL generate the ingest token with at least 32 characters, and SHALL write the host's copies into `/etc/elevator/.env` from SSM.

Neither the repository, nor any image, nor any workflow definition SHALL contain them. Each function role SHALL read only the parameters it uses.

#### Scenario: The backend and the orchestrator share one token
- **WHEN** provisioning (Terraform apply, then the secret-value script) has run
- **THEN** `/etc/elevator/.env` and the SSM parameter hold the same ingest token
- **AND** the backend registers the ingest and inference routers

#### Scenario: Re-running provisioning does not rotate the token
- **WHEN** Terraform is applied again and the secret-value script runs a second time
- **THEN** the existing token is kept
- **AND** no resource is duplicated

#### Scenario: A function cannot read another function's secrets
- **WHEN** the scorer role's policy is inspected
- **THEN** it grants no read on the ingest token parameter

### Requirement: The application host may invoke only the scoring function
The system SHALL grant the instance role `lambda:InvokeFunction` on the scoring function's ARN only, as a customer-managed policy. The grant SHALL NOT use a wildcard resource, and SHALL NOT allow invoking the orchestrator.

The instance role SHALL additionally read exactly the three production parameters (`ssm:GetParameter`, no wildcard). The host env file is then written from SSM on the host itself, so the values never pass through an operator's machine or a Run Command parameter.

The orchestrator function role SHALL be limited to:
- `bedrock:InvokeModel` on the same pinned EU Nova Lite ARNs the backend uses;
- reading its own SSM parameters;
- writing its own logs.

#### Scenario: The backend invokes the scorer with the instance role
- **WHEN** a production inference run is triggered
- **THEN** the backend invokes `elevator-scorer` with credentials from IMDSv2
- **AND** no AWS key exists in `/etc/elevator/.env`

#### Scenario: The host cannot trigger orchestration
- **WHEN** the instance role attempts to invoke `elevator-orchestrator`
- **THEN** AWS denies the request

### Requirement: Serverless usage and failures raise alarms
The system SHALL alarm, through an SNS topic with an email subscription, when either of these happens:
- **Daily compute.** Daily Lambda compute across both functions exceeds 70 % of the free-tier allowance's daily pace. That is 400,000 GB-s per month, so roughly 9,300 GB-s per day.
- **Function errors.** Either function reports any error in a period.

The system SHALL also alarm when scheduled work goes silent:
- no successful daily run in 26 hours;
- no successful ingest in 2 hours.

These silence alarms SHALL treat missing data as breaching, so a schedule that stops firing does not read as healthy. They SHALL notify only while the schedules are enabled, so the time between provisioning and cutover is not a stream of alarm emails. Error alarms treat missing data as not breaching, because a period with no runs has no errors, and silence is the silence alarms' job.

The 70 % alarm is the agreed trigger to redesign before the free tier is exhausted.

#### Scenario: A failed invocation notifies
- **WHEN** an orchestrator invocation fails
- **THEN** the error alarm enters ALARM and a notification is sent

#### Scenario: Excess compute notifies before the free tier is spent
- **WHEN** a day's GB-s exceeds 70 % of the daily free-tier pace
- **THEN** the usage alarm enters ALARM

#### Scenario: Ingest that stops is noticed within hours
- **WHEN** no telemetry-ingest run succeeded in the last 2 hours while the schedules are enabled
- **THEN** the ingest-silence alarm enters ALARM and notifies

#### Scenario: Before cutover, silence does not notify
- **WHEN** the schedules are disabled
- **THEN** the silence alarms have their actions disabled

#### Scenario: Silence is not health
- **WHEN** no successful daily run was recorded in the last 26 hours
- **THEN** an alarm enters ALARM rather than INSUFFICIENT_DATA
- **AND** frequent ingest runs cannot keep that alarm quiet, because success is counted per workflow

### Requirement: The serverless tier is declared in Terraform, and its state holds no secret
The system SHALL declare every AWS resource of the serverless tier in Terraform under `infra/terraform/`, with the state in a private, encrypted, versioned S3 bucket using S3-native locking.

Pre-existing resources (the EC2 instance, its role, the GitHub OIDC deploy role, the Bedrock policy) SHALL be referenced as data sources and SHALL NOT be created, modified or destroyed by this configuration, apart from attaching the new policies to the two existing roles.

No secret value SHALL appear in the Terraform configuration, plan or state. Terraform declares the SSM parameters and ignores their values; a script writes the values. Terraform SHALL ignore the functions' image URI, which CI owns.

#### Scenario: An apply is idempotent
- **WHEN** `terraform apply` has completed and `terraform plan` is run again
- **THEN** the plan shows no changes

#### Scenario: CI deploying a new image is not drift
- **WHEN** CI has moved a function to a new image and `terraform plan` is run
- **THEN** the plan shows no change to that function

#### Scenario: The state holds no secret
- **WHEN** the state is inspected after the secret values were written
- **THEN** the SSM parameters hold only the placeholder value
- **AND** no ingest token, Grafana credential or AWS key appears in it

#### Scenario: Existing resources are untouched
- **WHEN** the plan is inspected
- **THEN** it creates, changes or destroys none of the pre-existing instance, roles or policies

#### Scenario: The configuration is checked without credentials
- **WHEN** a pull request touches `infra/terraform/`
- **THEN** CI runs `terraform fmt -check` and `terraform validate` and fails on either

