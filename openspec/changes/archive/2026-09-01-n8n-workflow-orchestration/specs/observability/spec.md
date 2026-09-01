# Spec Delta: observability

## ADDED Requirements

### Requirement: The Collector scrapes the orchestration tier
The system SHALL scrape the orchestrator's Prometheus endpoint from every process it runs, labelled by role so main and worker are distinguishable, and SHALL route those metrics through the same pipeline as the rest.

A target that does not resolve SHALL be reported as down rather than failing the Collector, because the queue tier is optional and "the worker is not running" is a truthful thing for a metric to say.

#### Scenario: Orchestrator metrics reach the metrics backend
- **WHEN** the stack is running and a workflow has executed
- **THEN** the orchestrator's workflow-execution metric is queryable in the metrics backend
- **AND** each series carries a label identifying which process it came from

#### Scenario: An absent worker is reported, not fatal
- **WHEN** the queue profile is not running and the worker target cannot be resolved
- **THEN** the Collector keeps running and keeps scraping the main process
- **AND** the worker's `up` series reads 0

### Requirement: The external pipeline drops per-node orchestration spans
The system SHALL drop the orchestrator's per-node execution spans from the pipeline that exports outside the local stack, and SHALL keep them in the local pipeline where they are what makes a slow or failing node visible.

Because a processor belongs to a pipeline rather than to an exporter, this SHALL be expressed as two separate trace pipelines reading the same receiver — one filtered and exporting outward, one unfiltered and exporting locally. A single pipeline carrying both exporters cannot express it: a filter there removes the spans from the local backend too.

The filter SHALL fail loudly rather than silently. An expression that cannot be evaluated SHALL surface as an error, because a filter that quietly matches nothing is indistinguishable from there being nothing to match.

#### Scenario: Per-node spans stay local
- **WHEN** a workflow executes and its spans are exported
- **THEN** per-node execution spans are present in the local backend
- **AND** they are absent from the external pipeline

#### Scenario: Every span reaches the local backend exactly once
- **WHEN** the external-export overlay is active
- **THEN** each span appears once in the local backend, not twice
- **AND** the merged configuration defines exactly two trace pipelines

#### Scenario: Configuration added to the base survives the overlay
- **WHEN** a receiver is added to a pipeline in the base configuration
- **THEN** it is still present when the external-export overlay is merged on top

### Requirement: Requests carry the orchestrator's execution identity into the trace
The system SHALL record the orchestrator's execution and workflow identifiers as span attributes when a request carries them, so that a trace can be taken back to the execution that produced it and a failed execution forward to its trace.

The values are caller-supplied and SHALL be bounded in length and recorded as absent rather than empty, so that a request no orchestrator was involved in does not acquire an execution id. Recording SHALL be a no-op when the span is not recording.

#### Scenario: Execution identifiers reach the span
- **WHEN** a request carries the orchestrator's execution and workflow id headers
- **THEN** the server span records both as attributes

#### Scenario: A request without those headers acquires no attributes
- **WHEN** a request arrives with neither header
- **THEN** it is served normally
- **AND** the span carries no orchestration attributes rather than empty ones

#### Scenario: An oversized identifier is truncated rather than dropped
- **WHEN** a request carries an identifier longer than the recorded bound
- **THEN** the value is recorded, truncated to that bound
