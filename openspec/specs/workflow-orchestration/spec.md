# Spec: workflow-orchestration

## Purpose

The system runs its telemetry ingest and its fleet re-scoring on schedules owned
by a self-hosted orchestrator, rather than waiting for someone to call the
endpoints by hand.

Two cadences, deliberately separate: ingest is frequent, re-scoring is daily.
Collapsing them would leave the six-day trend holding six *last runs of a day*
rather than six days of scoring.

The orchestration tier is **local-only**. Schedules fire while the development
stack is up; production carries no orchestrator, and the endpoints it drives are
not registered there. Every artifact describing it has to be readable as that by
someone who did not build it.

Scope boundary: this capability covers what runs on a schedule, how a scheduled
execution is traced and authenticated, and how its definitions are published.
How readings are stored is `telemetry-ingestion`; how they are scored is
`risk-inference`; how any of it is observed is `observability`.

## Requirements

### Requirement: Ingest and re-scoring run on separate schedules
The system SHALL trigger telemetry ingest and fleet re-scoring from two independent scheduled workflows, and SHALL NOT combine them into one. Ingest SHALL run at a high cadence (15 minutes) and re-scoring at a daily cadence. The re-scoring workflow SHALL additionally expose a manual trigger, so that a demonstration does not have to wait for the schedule.

The separation is a correctness constraint, not a preference. `risk-inference` maintains a six-day trend in which index 5 is today, and it survives repeated runs by overwriting today's point rather than shifting the window. A single workflow doing both would therefore not corrupt the trend, but each of its six points would hold the last run of its day rather than that day's scoring, and the dashboard would quietly stop meaning what it says.

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

### Requirement: A scheduled execution is one distributed trace
The system SHALL propagate W3C trace context from the orchestrator into the API, so that a scheduled execution appears as a single trace spanning the orchestrator, the backend, the inference service and the database. The orchestrator SHALL be configured to export traces for scheduled executions, and every orchestrator process SHALL carry an identical telemetry configuration.

The backend SHALL additionally record the orchestrator's execution and workflow identifiers as span attributes when the request carries them, so that a failed execution can be reached from a trace, and a trace from an execution, even if header injection is unavailable.

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

### Requirement: A retried node cannot corrupt the fleet's scores
The system SHALL rely on ingest idempotency rather than on the orchestrator not retrying. The orchestrator retries a failed node by re-sending the same payload, and the re-scoring run averages readings over a window, so a batch stored twice would move a risk score with no error and no log line.

The ingest workflow SHALL therefore submit readings whose `recorded_at` is fixed at the moment of generation and carried unchanged through a retry, so that a re-sent payload is recognisable as the same readings.

#### Scenario: A retried ingest node stores nothing new
- **WHEN** the ingest workflow's HTTP node fails and n8n retries it with the same payload
- **THEN** the retry answers 201 with `accepted` 0
- **AND** the number of stored readings is unchanged

#### Scenario: A retry does not move the resulting score
- **WHEN** a batch is ingested, retried, and the fleet is then re-scored
- **THEN** the resulting scores equal those produced by a single ingest of that batch

#### Scenario: Timestamps are generated once, not per attempt
- **WHEN** the workflow's Code node builds a batch
- **THEN** each reading's `recorded_at` is fixed in that node's output
- **AND** a retry of the HTTP node that follows submits the identical timestamps

### Requirement: The orchestrator authenticates to the write endpoints
The system SHALL send the configured `X-Ingest-Token` from every workflow node that posts telemetry or triggers a re-scoring run, holding it as an orchestrator credential rather than inline in the workflow definition.

#### Scenario: Scheduled ingest is accepted
- **WHEN** the ingest workflow runs against a backend with a token configured
- **THEN** the request carries `X-Ingest-Token` and is accepted

#### Scenario: A workflow without the credential fails loudly
- **WHEN** the credential is absent or wrong
- **THEN** the node fails with HTTP 401
- **AND** the execution is recorded as failed rather than silently storing nothing

### Requirement: Generated telemetry is deterministic and in human units
The system SHALL generate telemetry values in code, not in a language model's output. A model MAY be used to invent an operating *scenario* — a small, typed, schema-validated object — from which a code step derives the numeric readings.

Readings SHALL be submitted in the units the ingest endpoint documents: degrees Celsius, rpm, Nm and cumulative hours. A model asked directly for a machine temperature will emit an absolute value on some runs and a Celsius value on others, and both fall inside ranges the endpoint accepts; the resulting corruption reaches the scorer silently.

#### Scenario: The model's output is a scenario, not readings
- **WHEN** the ingest workflow's agent step completes
- **THEN** its output validates against the scenario schema
- **AND** it contains no per-elevator numeric readings

#### Scenario: The same scenario yields the same readings
- **WHEN** the code step is given the same scenario and elevator list twice
- **THEN** it produces identical readings both times

#### Scenario: Submitted temperatures are Celsius
- **WHEN** a generated batch is submitted
- **THEN** every temperature falls inside the plausible Celsius range the endpoint enforces
- **AND** no absolute-temperature value is submitted

### Requirement: The orchestration tier is observable
The system SHALL expose orchestrator metrics for Prometheus scraping, SHALL have them collected by the Collector, and SHALL label them so that cardinality stays bounded — workflow-id and node-type labels SHALL be off. Queue depth is reported by the main process only; a scrape target that does not answer SHALL be discovered before a dashboard panel is built on it.

#### Scenario: Orchestrator metrics reach the metrics backend
- **WHEN** the stack is running and a workflow has executed
- **THEN** workflow execution counts are queryable in Prometheus
- **AND** the orchestration dashboard renders them instead of a placeholder

#### Scenario: Queue depth is reported in queue mode
- **WHEN** the queue profile is enabled and jobs are enqueued
- **THEN** queue depth is queryable from the main process's metrics

#### Scenario: Metric cardinality is bounded
- **WHEN** orchestrator metrics are collected
- **THEN** no metric carries a workflow id or a node type as a label

### Requirement: Exported workflow definitions carry no secrets or instance internals
The system SHALL export workflow definitions through a script that removes credential blocks, instance identifiers, and per-instance ids before the JSON is committed, so that a published definition is importable elsewhere and leaks nothing about the instance that produced it.

#### Scenario: An exported definition is scrubbed
- **WHEN** a workflow is exported by the script
- **THEN** the resulting JSON contains no `credentials` block, no `meta.instanceId`, no `versionId` and no node `id`

#### Scenario: A scrubbed definition is still importable
- **WHEN** a scrubbed definition is imported into a fresh orchestrator instance
- **THEN** it loads with its nodes and connections intact
- **AND** the import succeeds despite carrying no credentials

#### Scenario: A definition imported without credentials fails at execution, not at import
- **WHEN** a scrubbed definition is imported and run without its credentials attached
- **THEN** the import reports success
- **AND** the execution fails on the node that needed a credential
- **AND** the documented import path attaches the credentials so this does not happen

### Requirement: The orchestration tier is local-only and says so
The system SHALL NOT deploy the orchestrator to the production environment, and SHALL state in its documentation that scheduled work runs only while the local stack is up. The production compose definition SHALL remain free of orchestrator services.

This is a truthfulness requirement. The pipeline is a scheduled local demonstration, not an autonomous service, and every artifact describing it must be readable as such by someone who did not build it.

#### Scenario: Production carries no orchestrator
- **WHEN** the production compose definition is inspected
- **THEN** it defines no orchestrator, queue or worker service

#### Scenario: The documentation states the limitation
- **WHEN** the orchestration documentation is read
- **THEN** it states that schedules fire only while the local stack is running
- **AND** it records moving the orchestration tier to the cloud as future work

### Requirement: Agent prompts and outputs are not exported as telemetry
The system SHALL disable recording of agent inputs and outputs in the orchestrator's tracing, which is enabled by default, so that prompts and model output are not shipped to an external telemetry backend. The Collector SHALL drop the orchestrator's per-node execution spans from the pipeline that exports outside the local stack.

#### Scenario: Agent input and output recording is off
- **WHEN** the orchestrator's tracing configuration is inspected
- **THEN** agent input recording and agent output recording are both disabled

#### Scenario: Per-node spans stay local
- **WHEN** a workflow executes and its spans are exported
- **THEN** per-node execution spans are present in the local backend
- **AND** they are absent from the external pipeline
