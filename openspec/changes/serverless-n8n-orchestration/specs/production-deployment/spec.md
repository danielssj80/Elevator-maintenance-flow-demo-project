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
- **WHEN** the provisioning script has run
- **THEN** `/etc/elevator/.env` and the SSM parameter hold the same ingest token
- **AND** the backend registers the ingest and inference routers

#### Scenario: Re-running provisioning does not rotate the token
- **WHEN** the provisioning script runs a second time
- **THEN** the existing token is kept
- **AND** no resource is duplicated

#### Scenario: A function cannot read another function's secrets
- **WHEN** the scorer role's policy is inspected
- **THEN** it grants no read on the ingest token parameter

### Requirement: The application host may invoke only the scoring function
The system SHALL grant the instance role `lambda:InvokeFunction` on the scoring function's ARN only, as a customer-managed policy. The grant SHALL NOT use a wildcard resource, and SHALL NOT allow invoking the orchestrator.

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

The 70 % alarm is the agreed trigger to redesign before the free tier is exhausted. An alarm SHALL NOT be satisfiable by missing data, so a schedule that stops firing does not read as healthy.

#### Scenario: A failed invocation notifies
- **WHEN** an orchestrator invocation fails
- **THEN** the error alarm enters ALARM and a notification is sent

#### Scenario: Excess compute notifies before the free tier is spent
- **WHEN** a day's GB-s exceeds 70 % of the daily free-tier pace
- **THEN** the usage alarm enters ALARM

#### Scenario: Silence is not health
- **WHEN** no daily-run invocation happened in the last 26 hours
- **THEN** an alarm enters ALARM rather than INSUFFICIENT_DATA
