## ADDED Requirements

### Requirement: In production, one invocation runs one workflow on a short-lived orchestrator
The system SHALL run production workflows inside an AWS Lambda function whose container image holds the orchestrator, both workflows (already imported and published), and credential placeholders. Each invocation SHALL run exactly one workflow:
- copy the seeded orchestrator folder into `/tmp`;
- start the orchestrator in server mode, so that its telemetry module loads;
- wait until it reports readiness;
- call the named workflow's Webhook Trigger on localhost;
- stop the orchestrator gracefully and wait for it to exit before returning.

No orchestrator state SHALL persist between invocations, and no editor SHALL be exposed.

The handler SHALL treat as a failure any webhook response that is not HTTP 200 with a JSON body, because a starting orchestrator answers 200 with a plain-text "starting up" page. It SHALL stop the orchestrator on every path, including failures, because a process left running in a reused sandbox answers the next invocation's readiness check falsely.

#### Scenario: An invocation runs the requested workflow
- **WHEN** the function is invoked with `{"workflow": "telemetry-ingest"}`
- **THEN** that workflow's webhook is called once
- **AND** the invocation returns success only after the orchestrator process has exited

#### Scenario: An unknown workflow is refused before anything starts
- **WHEN** the function is invoked with a workflow name that is not in the image
- **THEN** the invocation fails naming the workflow
- **AND** no orchestrator process is started

#### Scenario: A "starting up" answer is not success
- **WHEN** the webhook answers HTTP 200 with a non-JSON body
- **THEN** the invocation fails
- **AND** the orchestrator process is stopped before the failure is returned

#### Scenario: A failed invocation leaves nothing running
- **WHEN** an invocation fails at any step after the orchestrator was started
- **THEN** no orchestrator process remains when the invocation returns
- **AND** the next invocation in the same sandbox starts its own orchestrator rather than reusing a stale one

#### Scenario: The workflow result is recorded
- **WHEN** an invocation completes
- **THEN** the workflow's final output is written to the function's log
- **AND** the daily digest can therefore be read without an execution history

### Requirement: In the serverless image, only the webhook triggers a workflow
The system SHALL disable every Schedule Trigger in the workflows seeded into the Lambda image, so that only the external scheduler decides when work runs. A schedule that happened to fall inside an invocation's lifetime would otherwise start a second, unrequested execution, possibly of the other workflow.

The repository's workflow definitions SHALL keep their Schedule Triggers enabled for the local stack.

#### Scenario: Seeded Schedule Triggers are disabled
- **WHEN** the workflows inside the built image are inspected
- **THEN** every Schedule Trigger node is disabled
- **AND** every workflow has exactly one enabled Webhook Trigger

#### Scenario: The repository definitions still schedule locally
- **WHEN** the workflow definitions under `n8n/workflows/` are inspected
- **THEN** each keeps its Schedule Trigger enabled
- **AND** each also has a Webhook Trigger

### Requirement: Production schedules invoke the orchestrator
The system SHALL invoke the orchestrator function from two EventBridge Scheduler schedules:
- telemetry ingest every 30 minutes;
- inference and digest daily at 06:00 in Europe/Madrid.

Neither schedule SHALL retry a failed invocation. A retried ingest is harmless only because ingest is idempotent, and a retried re-score would hide the failure the alarm exists to report.

#### Scenario: Both schedules target the orchestrator with their workflow
- **WHEN** the schedules are inspected
- **THEN** the ingest schedule fires every 30 minutes with `{"workflow": "telemetry-ingest"}`
- **AND** the daily schedule fires at 06:00 Europe/Madrid with `{"workflow": "daily-inference-and-digest"}`
- **AND** both have retries disabled

### Requirement: Production credentials are injected at invocation and their absence fails fast
The system SHALL keep credential placeholders in the image with **empty** secret fields, and SHALL fill them at invocation through the orchestrator's credential-overwrite mechanism:
- the ingest token is read from SSM Parameter Store (SecureString);
- the model-provider credentials come from the function role's temporary credentials, including the session token.

The overwrite mechanism fills only empty fields, so a placeholder holding any value would silently win.

The handler SHALL refuse to start the orchestrator when the ingest token is missing or empty. Otherwise the HTTP node would send an empty header, the backend would reject it, and the failure would surface far from its cause.

#### Scenario: A missing token stops the invocation before n8n starts
- **WHEN** the SSM parameter is missing, empty or unreadable
- **THEN** the invocation fails with an error naming the parameter, not its value
- **AND** no orchestrator process is started

#### Scenario: Placeholders cannot shadow the injected secret
- **WHEN** the seeded credential placeholders are inspected
- **THEN** every secret field is empty

#### Scenario: The image carries no secret
- **WHEN** the orchestrator image's filesystem and environment are scanned
- **THEN** no ingest token, Grafana Cloud credential or AWS key is present

### Requirement: The backend address is configuration, not part of the workflow
The system SHALL resolve the backend base URL in every workflow HTTP node from orchestrator configuration. It SHALL default to the local compose address and use the production HTTPS origin in the Lambda.

#### Scenario: Local and production share one definition
- **WHEN** the same workflow definition runs locally and in the Lambda
- **THEN** locally its HTTP nodes call `http://backend:8000`
- **AND** in the Lambda they call `https://elevator.dsaavedra.dev`

#### Scenario: No node hard-codes the backend address
- **WHEN** the workflow definitions are inspected
- **THEN** no HTTP node URL contains a literal backend host

### Requirement: Where the orchestration tier runs is stated truthfully
The system SHALL NOT run an orchestrator service on the production application host. The production compose definition SHALL remain free of orchestrator, queue and worker services.

The documentation SHALL state where each part runs:
- the editor and local schedules run on the developer's machine;
- production schedules run in AWS Lambda with no persistent execution history.

#### Scenario: Production carries no orchestrator
- **WHEN** the production compose definition is inspected
- **THEN** it defines no orchestrator, queue or worker service

#### Scenario: The documentation states what runs where
- **WHEN** the orchestration documentation is read
- **THEN** it states that production schedules run in AWS Lambda
- **AND** it states that the editor and execution history exist only locally

## MODIFIED Requirements

### Requirement: Ingest and re-scoring run on separate schedules
The system SHALL trigger telemetry ingest and fleet re-scoring from two independent scheduled workflows, and SHALL NOT combine them into one. Ingest SHALL run at a high cadence and re-scoring at a daily cadence:
- **Locally:** ingest every 15 minutes.
- **In production:** ingest every 30 minutes. This halves the free-tier consumption, and the daily score averages over the same 24-hour window either way.

The re-scoring workflow SHALL additionally expose a manual trigger locally, so that a demonstration does not have to wait for the schedule.

The separation is a correctness constraint, not a preference. `risk-inference` maintains a six-day trend in which index 5 is today, and it survives repeated runs by overwriting today's point rather than shifting the window. A single workflow doing both would therefore not corrupt the trend. But each of its six points would hold the last run of its day rather than that day's scoring, and the dashboard would quietly stop meaning what it says.

#### Scenario: The ingest workflow does not trigger scoring
- **WHEN** the telemetry-ingest workflow completes a run
- **THEN** readings are persisted
- **AND** no inference run is started

#### Scenario: The re-scoring workflow can be run on demand
- **WHEN** the manual trigger of the inference workflow is fired
- **THEN** a re-scoring run is started without waiting for the schedule
- **AND** the six-day trend still holds exactly six points afterwards

#### Scenario: Repeated same-day scoring does not shift the trend window
- **WHEN** the inference workflow runs twice on the same calendar day
- **THEN** the trend still holds exactly six points
- **AND** index 5 carries the second run's score

#### Scenario: Production cadences are distinct
- **WHEN** the production schedules are inspected
- **THEN** ingest and re-scoring are two schedules targeting two different workflows

### Requirement: A scheduled execution is one distributed trace
The system SHALL propagate W3C trace context from the orchestrator into the API, so that a scheduled execution appears as a single trace spanning the orchestrator, the backend, the inference service and the database. The orchestrator SHALL be configured to export traces for scheduled and webhook-triggered executions, and every orchestrator process SHALL carry an identical telemetry configuration.

The backend SHALL additionally record the orchestrator's execution and workflow identifiers as span attributes when the request carries them, so that a failed execution can be reached from a trace, and a trace from an execution, even if header injection is unavailable. In production, the execution identifier sent SHALL be the Lambda request id. A fresh orchestrator database numbers every execution `1`, and the request id is what leads to the invocation's log.

#### Scenario: A scheduled run produces one linked trace
- **WHEN** an activated workflow posts a telemetry batch on its schedule
- **THEN** the orchestrator span and the backend server span share one trace id
- **AND** the backend server span's parent is the orchestrator's span

#### Scenario: Execution identifiers reach the trace
- **WHEN** a request carries `X-N8N-Execution-Id` and `X-N8N-Workflow-Id`
- **THEN** the server span records both as attributes

#### Scenario: A request without those headers is unaffected
- **WHEN** a request arrives with neither header
- **THEN** it is served normally
- **AND** the span carries no orchestration attributes rather than empty ones

#### Scenario: Every orchestrator process reports, not only the main one
- **WHEN** the orchestrator runs in queue mode and a worker executes a workflow
- **THEN** spans are exported for that execution
- **AND** the worker appears as its own service in the trace backend

#### Scenario: A production execution is identified by its invocation
- **WHEN** the Lambda runs a workflow that calls the backend
- **THEN** `X-N8N-Execution-Id` carries that invocation's Lambda request id, not `1`

#### Scenario: Spans are exported before the invocation returns
- **WHEN** an invocation completes
- **THEN** the orchestrator's spans for that execution have been exported
- **AND** they share one trace id with the backend span they caused

### Requirement: Agent prompts and outputs are not exported as telemetry
The system SHALL disable recording of agent inputs and outputs in the orchestrator's tracing, which is enabled by default, so that prompts and model output are not shipped to an external telemetry backend.

Per-node execution spans SHALL NOT be exported outside the local stack:
- **Locally:** the Collector drops them from the external pipeline.
- **In production:** the orchestrator exports directly with no Collector, so node spans are disabled at the source.

#### Scenario: Agent input and output recording is off
- **WHEN** the orchestrator's tracing configuration is inspected, locally or in the Lambda
- **THEN** agent input recording and agent output recording are both disabled

#### Scenario: Per-node spans stay local
- **WHEN** a workflow executes and its spans are exported
- **THEN** per-node execution spans are present in the local backend
- **AND** they are absent from the external pipeline

#### Scenario: The Lambda exports no node spans
- **WHEN** the orchestrator function's configuration is inspected
- **THEN** node spans are disabled

## REMOVED Requirements

### Requirement: The orchestration tier is local-only and says so
**Reason**: Production now runs scheduled ingest and daily re-scoring in AWS Lambda. The statement it enforced would become false.
**Migration**: Replaced by *Where the orchestration tier runs is stated truthfully*, which keeps the guarantee that the production host defines no orchestrator service.
