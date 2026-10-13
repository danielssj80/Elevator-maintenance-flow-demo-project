## ADDED Requirements

### Requirement: Production exports traces directly to Grafana Cloud
The system SHALL export traces from the production backend, the orchestrator function and the scoring function directly to Grafana Cloud's OTLP endpoint. It SHALL authenticate with credentials read from SSM, and SHALL run no Collector in production.

Export SHALL be best-effort:
- an unreachable or rejecting endpoint SHALL NOT fail a request, a workflow execution or a scoring call;
- an export failure SHALL be logged.

Production SHALL export traces only. Metrics and logs from production are out of scope, because the free tier's series and log limits were sized for the local stack's selection.

#### Scenario: A production execution is one trace in Grafana Cloud
- **WHEN** the daily workflow runs in production
- **THEN** one trace in Grafana Cloud contains the orchestrator, `elevator-backend`, the scoring function and the database spans

#### Scenario: Grafana Cloud unreachable
- **WHEN** the OTLP endpoint refuses connections or rejects the credentials
- **THEN** ingest and scoring still complete and persist their results
- **AND** the export failure appears in the service's log

#### Scenario: Production does not need the local stack
- **WHEN** the production compose definition is inspected
- **THEN** it defines no Collector, Grafana, Prometheus, Tempo or Loki service
- **AND** the backend's OTLP endpoint is Grafana Cloud's
