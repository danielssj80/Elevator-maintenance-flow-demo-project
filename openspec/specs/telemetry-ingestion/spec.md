# Spec: telemetry-ingestion

## Purpose

The system accepts and persists elevator sensor readings, and is the system of
record for them: raw readings live in PostgreSQL and never in the metrics
pipeline.

Readings are stored in the units a sensor reports and a person reads — degrees
Celsius, rpm, Nm, cumulative hours. The trained model's own feature space is
Kelvin, and that conversion belongs to the inference path alone; this capability
never performs it. Values that cannot be a real reading, and timestamps from the
future, are refused at the point of entry rather than becoming rows that fail
every later run.

A reading is identified by `(elevator_id, recorded_at, source)` and stored at
most once, so that a producer resubmitting a batch changes nothing. That is a
property of this capability rather than a convenience for its callers: the
inference run averages rows over its window, so a batch stored twice would be
weighted twice and move a risk score with no error and no log line.

Scope boundary: this capability covers accepting, storing, querying and pruning
readings. What is done with them is `risk-inference`. Who produces them is the
orchestration layer.
## Requirements
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

### Requirement: A reading has an identity, and submitting it twice changes nothing
The system SHALL treat `(elevator_id, recorded_at, source)` as the identity of a telemetry reading and SHALL persist at most one row per identity. A submitted reading whose identity is already stored SHALL be ignored — neither inserted again nor used to update the stored row — and SHALL be counted back to the caller as a duplicate rather than as accepted. This SHALL hold both for a reading repeated inside a single batch and for a batch submitted more than once.

The guarantee exists because the inference run averages rows over its window rather than distinct readings, so a batch present twice is weighted twice and moves the resulting risk score with no error and no log line. The producer is a scheduled workflow whose orchestrator retries a failed node by re-sending the same payload, which makes a repeated batch an expected event rather than an anomaly.

Storing the reading exactly once is chosen over updating it because a reading is an observation: a second report of the same identity carries no new information, and overwriting would let a late retry silently replace a value the last inference run already consumed.

#### Scenario: An identical batch submitted twice persists one set of rows
- **WHEN** a batch is ingested successfully and the identical batch is submitted again
- **THEN** no additional rows are persisted
- **AND** the response reports `accepted` as 0 and `duplicates_ignored` as the number of readings referencing a known elevator
- **AND** the response status is 201

#### Scenario: A partially overlapping batch persists only what is new
- **WHEN** a batch is submitted in which some readings are already stored and some are not
- **THEN** only the readings that are not already stored are persisted
- **AND** `accepted` counts exactly those, and `duplicates_ignored` counts the rest

#### Scenario: A reading repeated within one batch is persisted once
- **WHEN** a single batch contains two readings sharing an elevator id, `recorded_at` and `source`
- **THEN** exactly one row is persisted for that identity
- **AND** the repetition is counted in `duplicates_ignored`

#### Scenario: The stored reading wins over the resubmitted one
- **WHEN** a reading is ingested, and a reading with the same identity but different sensor values is submitted afterwards
- **THEN** the stored row still carries the values from the first submission

#### Scenario: The same instant from a different producer is a different reading
- **WHEN** two readings share an elevator id and `recorded_at` but declare different `source` values
- **THEN** both are persisted

#### Scenario: A duplicated batch does not move the inference window aggregate
- **WHEN** a batch is ingested, the window is aggregated, the identical batch is ingested again and the window is aggregated a second time
- **THEN** both aggregates report the same averages and the same reading count for every elevator

### Requirement: Every reading records where it came from
The system SHALL store ingest provenance on each reading: a `source` identifying the producer, a `batch_id` shared by all readings submitted together, and the W3C trace id of the ingesting request as 32 hexadecimal characters when one is available. This allows a suspicious row in the database to be traced back to the request that created it.

A `batch_id` SHALL label the rows a request actually inserted. A request whose readings were all already stored inserts nothing, and its returned `batch_id` therefore labels no rows — the provenance of those readings remains the request that first stored them, which is the honest answer for a retry.

#### Scenario: Readings ingested together share a batch id
- **WHEN** a batch of 50 readings is ingested in one request
- **THEN** all 50 persisted rows carry the same `batch_id`
- **AND** that `batch_id` is returned in the response

#### Scenario: A retried batch does not relabel the rows it already stored
- **WHEN** a batch is ingested and then submitted a second time
- **THEN** the stored rows still carry the `batch_id` of the first request

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

### Requirement: The write endpoints require an ingest token when one is configured
The system SHALL accept a configured shared secret in an `X-Ingest-Token` request header on `POST /api/telemetry/readings`, `POST /api/inference/run` and `GET /api/telemetry/readings`, SHALL compare it in constant time, and SHALL reject a request that does not carry the configured value with HTTP 401 before any reading is persisted, read or any inference run is started. The rejection SHALL NOT distinguish an absent token from an incorrect one.

Outside production, when no token is configured the endpoints SHALL remain reachable without one, so that a fresh checkout with no configuration still works, and the application SHALL emit a startup warning naming the endpoints it has registered without a guard. Every non-production environment that registers these routers SHALL configure a token, so that the guard is exercised by the configuration that actually runs rather than only by tests that set it by hand.

In production the guard SHALL be fail-closed: when the configured token is unset or empty at request time, every request SHALL be rejected with HTTP 401. The production gate already refuses to register the routers without a token; this is the second, independent reason for the same outcome, so that a token cleared after startup cannot open the endpoints.

#### Scenario: A request carrying the configured token is accepted
- **WHEN** a token is configured and a batch is submitted with a matching `X-Ingest-Token` header
- **THEN** the request is processed normally

#### Scenario: A request with no token is rejected
- **WHEN** a token is configured and a batch is submitted with no `X-Ingest-Token` header
- **THEN** the response status is 401
- **AND** nothing from that batch is persisted

#### Scenario: A request with the wrong token is rejected
- **WHEN** a token is configured and a batch is submitted with a non-matching `X-Ingest-Token` header
- **THEN** the response status is 401
- **AND** nothing from that batch is persisted
- **AND** the response body is identical to the one returned when the header is absent

#### Scenario: The inference trigger is guarded by the same token
- **WHEN** a token is configured and `POST /api/inference/run` is called without a matching `X-Ingest-Token` header
- **THEN** the response status is 401
- **AND** no inference run is started

#### Scenario: Reading telemetry is guarded by the same token
- **WHEN** a token is configured and `GET /api/telemetry/readings` is called without a matching `X-Ingest-Token` header
- **THEN** the response status is 401
- **AND** no readings are returned

#### Scenario: An unconfigured token leaves the endpoints open and says so
- **WHEN** the application starts in a non-production environment with no ingest token configured
- **THEN** the write endpoints accept a request with no `X-Ingest-Token` header
- **AND** a warning is logged naming those endpoints as unguarded

#### Scenario: An empty token in production rejects everything
- **WHEN** the deployment environment is production and the configured token is empty at request time
- **THEN** a request to any guarded endpoint answers 401, with or without an `X-Ingest-Token` header

#### Scenario: The environment that registers the routers configures a token
- **WHEN** the development compose file is inspected
- **THEN** it sets an ingest token for the backend service

### Requirement: The ingest and inference endpoints are reachable in production only behind a token
The system SHALL classify the deployment environment against an allow-list of non-production names — `local`, `test` and `ci`, matched exactly — and SHALL treat every other value as production, including an unset or empty value, a different letter case, an abbreviation such as `prod`, and any name not on the list. Forgetting or mistyping the setting SHALL therefore produce the safe outcome rather than the dangerous one.

In production the system SHALL NOT register the telemetry or inference routers unless an ingest token is configured and is at least 32 characters long. When the routers are withheld for that reason, the application SHALL log why at startup. When a token meeting that rule is configured, the routers SHALL be registered and every request to them SHALL be subject to the ingest token guard.

`docker-compose.prod.yml` auto-deploys on merge to the default branch and the deployed API has no user authentication, so a write route reaching production without a guard would let anyone inject telemetry and re-score the live fleet. Gating at registration, rather than only inside the handler, means a misconfigured guard cannot be reached at all.

#### Scenario: Routers are absent in production
- **WHEN** the application starts with the deployment environment set to `production` and no ingest token configured
- **THEN** `POST /api/telemetry/readings` returns HTTP 404
- **AND** `POST /api/inference/run` returns HTTP 404
- **AND** every pre-existing route still responds normally
- **AND** the startup log states that the routers were not registered because no ingest token is configured

#### Scenario: A short token does not open production
- **WHEN** the application starts in production with an ingest token shorter than 32 characters
- **THEN** the telemetry and inference routes are not registered
- **AND** the startup log states that the configured token was rejected as too short, without logging the token

#### Scenario: Routers are present in production with a valid token
- **WHEN** the application starts in production with an ingest token of at least 32 characters
- **THEN** the telemetry and inference routes are registered
- **AND** a request without the token answers 401
- **AND** a request with the token is processed normally

#### Scenario: An unconfigured deployment environment is treated as production
- **WHEN** the application is built with no deployment environment configured
- **THEN** it is classified as production
- **AND** without an ingest token the telemetry and inference routes are not registered
- **AND** every pre-existing route still responds normally

#### Scenario: An unrecognised environment name is treated as production
- **WHEN** the deployment environment is `prod`, `Production`, `PRODUCTION`, `staging`, `development`, an empty string, or a recognised name with surrounding whitespace
- **THEN** it is classified as production

#### Scenario: Routers are present outside production
- **WHEN** the application starts with the deployment environment set to `local`, `test` or `ci`
- **THEN** the telemetry and inference routes are registered and reachable

#### Scenario: The test suite does not inherit the environment from the shell
- **WHEN** the backend test suite runs in a shell that exports `DEPLOYMENT_ENVIRONMENT=production`
- **THEN** the suite still runs with the deployment environment declared by the suite itself

