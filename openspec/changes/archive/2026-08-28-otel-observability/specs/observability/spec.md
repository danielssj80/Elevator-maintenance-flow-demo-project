# Spec Delta: observability

## ADDED Requirements

### Requirement: Telemetry export is opt-in and inert when disabled
The system SHALL read observability configuration from environment variables exposed on `Settings`, and `OTEL_ENABLED` SHALL default to `false`. When disabled, `configure_telemetry()` SHALL install no instrumentation, register no providers, and open no network connection, so that CI runs and the test suite are unaffected by the absence of a Collector.

#### Scenario: Telemetry disabled by default
- **WHEN** the application starts with `OTEL_ENABLED` unset
- **THEN** `configure_telemetry()` returns without registering a tracer or meter provider
- **AND** no OTLP connection is attempted
- **AND** all existing endpoints behave exactly as before

#### Scenario: Collector unreachable while telemetry is enabled
- **WHEN** `OTEL_ENABLED` is `true` and the Collector endpoint refuses connections
- **THEN** the application still starts and serves requests normally
- **AND** the export failure is logged, not raised to the caller

### Requirement: HTTP requests and database queries produce a single linked trace
The system SHALL instrument FastAPI and SQLAlchemy so that every HTTP request produces a server span, and every database query issued while handling that request produces a child span of it. SQLAlchemy instrumentation SHALL be bound to the application's existing async engine so that database spans are actually emitted.

#### Scenario: Listing elevators produces a server span with database children
- **WHEN** a client calls `GET /api/elevators` with telemetry enabled
- **THEN** a server span named for the route template `/api/elevators` is recorded
- **AND** at least one child span representing the `SELECT` against `elevators` is recorded under it

#### Scenario: Route templates are used instead of raw paths
- **WHEN** clients call `GET /api/elevators/ELV-001` and `GET /api/elevators/ELV-002`
- **THEN** both server spans carry the same `http.route` value `/api/elevators/{elevator_id}`
- **AND** HTTP metrics are not split into one series per elevator

#### Scenario: A request for a missing elevator is recorded as a handled 404
- **WHEN** a client calls `GET /api/elevators/ELV-999` and no such elevator exists
- **THEN** the server span records `http.response.status_code` 404
- **AND** the span is not marked with an error status, because a 404 is an expected outcome

### Requirement: Incoming trace context is continued
The system SHALL use W3C trace-context propagation and SHALL make a server span a child of an incoming `traceparent` header when one is present, so that calls originating from an external orchestrator appear in the same trace.

#### Scenario: Request carrying traceparent joins the caller's trace
- **WHEN** a request arrives with a valid `traceparent` header
- **THEN** the resulting server span carries the trace ID from that header
- **AND** its parent is the span ID from that header

#### Scenario: Request with a malformed traceparent still succeeds
- **WHEN** a request arrives with an unparseable `traceparent` header
- **THEN** the request is served normally
- **AND** a new root span is started instead of failing the request

### Requirement: Bedrock briefing calls are traced without recording prompt content
The system SHALL wrap the briefing path in a domain span carrying the elevator identifier, risk level, briefing source, cache outcome and the configured model. Token usage and finish reason are emitted by the botocore instrumentation on its own child span and SHALL NOT be duplicated onto the domain span, so that model attributes have a single source of truth. Because the GenAI semantic conventions remain in Development status and the provider attribute has already been renamed once, the system SHALL emit both `gen_ai.provider.name` and the deprecated `gen_ai.system` on the domain span, so dashboards keep working across the rename. The system SHALL NOT record prompt or completion content on any signal it exports — spans, metrics or log records, including those produced by instrumentation it enables — as briefing prompts contain fleet risk data, technician names and visit notes. Where an instrumentation library can capture message content, the system SHALL pin that capture off explicitly rather than relying on its default.

#### Scenario: Successful briefing records provider identity but no message content
- **WHEN** a briefing is generated through Bedrock
- **THEN** the domain span records `briefing.source` as `bedrock`
- **AND** it records both `gen_ai.provider.name` and `gen_ai.system` as `aws.bedrock`
- **AND** it records `gen_ai.request.model` as the configured model id
- **AND** no attribute on it contains prompt or completion text

#### Scenario: Bedrock failure is visible as a fallback rather than as success
- **WHEN** the Bedrock call raises and the deterministic fallback is returned
- **THEN** the domain span records `briefing.source` as `fallback`
- **AND** the exception is recorded on the span
- **AND** the endpoint still returns HTTP 200

#### Scenario: Cached briefing is distinguishable from a generated one
- **WHEN** a briefing is served from the in-process cache
- **THEN** the domain span records `briefing.cache_hit` as true
- **AND** no GenAI model span is produced for that request

### Requirement: The event loop is not blocked by the Bedrock call
The system SHALL execute the blocking boto3 Bedrock call on a worker thread so that it does not stall the event loop, and SHALL propagate the tracing context into that thread so the model span remains a child of the domain span.

#### Scenario: Concurrent requests are not serialised behind a slow briefing
- **WHEN** one request is awaiting a slow Bedrock response
- **THEN** other requests continue to be served concurrently

#### Scenario: The model span nests under the domain span
- **WHEN** a briefing is generated through Bedrock
- **THEN** the model span produced on the worker thread is a child of `briefing.generate`

### Requirement: Fleet-health metrics are exposed with bounded cardinality
The system SHALL expose fleet-health as OpenTelemetry metrics derived from a snapshot refreshed on a fixed interval and immediately after a successful inference run: fleet count by risk level, age of the last inference run, and count of elevators without recent telemetry. Metric attributes SHALL be drawn from a bounded set; the elevator identifier SHALL NOT be used as a metric attribute.

#### Scenario: Fleet counts are reported per risk level
- **WHEN** the metric reader collects observations
- **THEN** `elevator.fleet.count` is reported once per risk level value
- **AND** the total across levels equals the number of elevators in the fleet

#### Scenario: Snapshot refresh failure does not break metric collection
- **WHEN** the refresh task fails to query the database
- **THEN** the previous snapshot continues to be reported
- **AND** the application continues serving requests

#### Scenario: Refresh task stops cleanly on shutdown
- **WHEN** the application shuts down
- **THEN** the refresh task is cancelled and awaited
- **AND** shutdown completes without an unhandled cancellation error

### Requirement: The Collector routes telemetry locally and to Grafana Cloud, and cloud failures are detectable
The system SHALL run an OTel Collector that receives OTLP over HTTP and exports traces and metrics to both a local Grafana stack and Grafana Cloud, with credentials supplied from environment variables and never committed. Because a failing cloud exporter leaves the local pipeline healthy and the dashboards plausible, the Collector SHALL expose its own internal telemetry so that cloud export failures are observable.

#### Scenario: A trace reaches both destinations
- **WHEN** the backend exports a trace with both exporters configured
- **THEN** the trace is queryable in the local Tempo instance
- **AND** the same trace is queryable in Grafana Cloud

#### Scenario: Invalid Grafana Cloud credentials are surfaced
- **WHEN** the Grafana Cloud exporter is rejected with an authentication error
- **THEN** the local pipeline continues to receive telemetry
- **AND** the Collector's `otelcol_exporter_send_failed_spans` metric for that exporter increases
