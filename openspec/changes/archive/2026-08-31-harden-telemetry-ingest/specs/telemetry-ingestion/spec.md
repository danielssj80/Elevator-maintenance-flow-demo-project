# Spec Delta: telemetry-ingestion

## ADDED Requirements

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

### Requirement: The write endpoints require an ingest token when one is configured
The system SHALL accept a configured shared secret in an `X-Ingest-Token` request header on `POST /api/telemetry/readings` and `POST /api/inference/run`, SHALL compare it in constant time, and SHALL reject a request that does not carry the configured value with HTTP 401 before any reading is persisted and before any inference run is started. The rejection SHALL NOT distinguish an absent token from an incorrect one.

When no token is configured the endpoints SHALL remain reachable without one, so that a fresh checkout with no configuration still works, and the application SHALL emit a startup warning naming the endpoints it has registered without a guard. Every environment that registers these routers SHALL configure a token, so that the guard is exercised by the configuration that actually runs rather than only by tests that set it by hand.

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

#### Scenario: An unconfigured token leaves the endpoints open and says so
- **WHEN** the application starts outside production with no ingest token configured
- **THEN** the write endpoints accept a request with no `X-Ingest-Token` header
- **AND** a warning is logged naming those endpoints as unguarded

#### Scenario: The environment that registers the routers configures a token
- **WHEN** the development compose file is inspected
- **THEN** it sets an ingest token for the backend service

## MODIFIED Requirements

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
