# Spec Delta: telemetry-ingestion

## ADDED Requirements

### Requirement: Telemetry readings are stored in human units, not model units
The system SHALL persist telemetry readings in the units a sensor reports and a human reads — degrees Celsius, rpm, Nm, cumulative run hours — and SHALL NOT store values in the model's feature space. Conversion into model units is the responsibility of the inference path and SHALL happen at exactly one boundary there.

#### Scenario: A reading is stored exactly as submitted
- **WHEN** a batch containing `ambient_temperature_c` of `27.0` is ingested
- **THEN** the persisted row carries `27.0`
- **AND** no Kelvin value is written to the table

#### Scenario: An implausible temperature is refused
- **WHEN** a batch contains a temperature outside the plausible Celsius range
- **THEN** the request is rejected with HTTP 422
- **AND** nothing from that batch is persisted

#### Scenario: Domain signals outside the model's feature space are still accepted
- **WHEN** a reading includes `vibration_mm_s`, `door_cycles`, `door_errors` or `motor_current_a`
- **THEN** those values are persisted
- **AND** they are recorded as not consumed by the current model

### Requirement: Every reading records where it came from
The system SHALL store ingest provenance on each reading: a `source` identifying the producer, a `batch_id` shared by all readings submitted together, and the W3C trace id of the ingesting request as 32 hexadecimal characters when one is available. This allows a suspicious row in the database to be traced back to the request that created it.

#### Scenario: Readings ingested together share a batch id
- **WHEN** a batch of 50 readings is ingested in one request
- **THEN** all 50 persisted rows carry the same `batch_id`
- **AND** that `batch_id` is returned in the response

#### Scenario: The active trace id is recorded on each row
- **WHEN** a batch is ingested while tracing is enabled and a span is recording
- **THEN** each persisted row carries the current trace id as 32 lowercase hex characters

#### Scenario: Ingest works when tracing is disabled
- **WHEN** a batch is ingested with telemetry disabled
- **THEN** the readings are persisted with a null `trace_id`
- **AND** the request succeeds

### Requirement: A batch is not lost to one unknown elevator
The system SHALL accept a batch containing readings for elevator ids that do not exist, persisting the valid readings and reporting the rejected ids in the response, so that a scheduled producer does not lose an entire batch over one stale identifier. A batch in which no reading references a known elevator SHALL be rejected with HTTP 422.

#### Scenario: Partial batch is accepted and the unknown ids reported
- **WHEN** a batch of 10 readings is ingested and 2 reference unknown elevator ids
- **THEN** 8 readings are persisted
- **AND** the response reports `accepted` as 8 and lists the 2 rejected ids
- **AND** the response status is 201

#### Scenario: A batch with no valid readings is rejected
- **WHEN** every reading in a batch references an unknown elevator id
- **THEN** nothing is persisted
- **AND** the response status is 422

#### Scenario: Batch size is bounded
- **WHEN** a batch containing more than 1000 readings is submitted
- **THEN** the request is rejected with HTTP 422
- **AND** nothing is persisted

### Requirement: Readings can be queried by elevator and time window
The system SHALL expose a read endpoint returning readings for an elevator within a time window, ordered newest first and bounded by an explicit limit, so that an operator can inspect what the last inference run actually consumed. The window SHALL be bounded at both ends with the same tolerance the inference run uses, so that the endpoint and the run cannot disagree about what telemetry exists — an operator debugging a skipped elevator must not be shown rows the scorer refuses to consider.

#### Scenario: Readings are returned newest first
- **WHEN** readings exist for an elevator across several timestamps and the endpoint is called for that elevator
- **THEN** the response lists them ordered by `recorded_at` descending

#### Scenario: A reading outside the run's window is not reported as present
- **WHEN** a reading exists whose timestamp the inference window excludes
- **THEN** the read endpoint does not return it

#### Scenario: An unknown elevator returns an empty list, not an error
- **WHEN** the endpoint is called for an elevator id that does not exist
- **THEN** the response is HTTP 200 with an empty list

### Requirement: Stored readings are pruned to a retention window
The system SHALL delete readings older than a configurable retention window at the end of each inference run, defaulting to 30 days, so that an unattended local database cannot grow without bound.

#### Scenario: Readings beyond the window are deleted after a run
- **WHEN** an inference run completes and readings older than the retention window exist
- **THEN** those readings are deleted
- **AND** readings inside the window are left untouched

### Requirement: The ingest and inference endpoints are unreachable in production
The system SHALL NOT register the telemetry or inference routers when the deployment environment is production. The deployment environment SHALL default to production when it is not configured, so that **forgetting** to set it is the safe outcome rather than the dangerous one: the production compose file loads an out-of-repo environment file, so a default of "local" meant the gate was open in precisely the environment it exists to protect. Non-production environments SHALL declare themselves explicitly. `docker-compose.prod.yml` auto-deploys on merge to the default branch and the deployed API has no authentication of any kind, so registering these routers there would publish unauthenticated endpoints allowing anyone to inject telemetry and re-score the live fleet.

#### Scenario: Routers are absent in production
- **WHEN** the application starts with the deployment environment set to `production`
- **THEN** `POST /api/telemetry/readings` returns HTTP 404
- **AND** `POST /api/inference/run` returns HTTP 404
- **AND** every pre-existing route still responds normally

#### Scenario: An unconfigured deployment environment is treated as production
- **WHEN** the application is built with no deployment environment configured
- **THEN** the telemetry and inference routes are not registered
- **AND** every pre-existing route still responds normally

#### Scenario: Routers are present outside production
- **WHEN** the application starts with the deployment environment set to `local`
- **THEN** the telemetry and inference routes are registered and reachable
