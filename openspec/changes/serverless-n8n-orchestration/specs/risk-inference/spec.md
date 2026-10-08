## MODIFIED Requirements

### Requirement: Scoring runs in a dedicated service that the backend can survive without
The system SHALL compute scores and feature contributions in a separate stateless service with no database access. The service takes feature names and rows and returns scores, contributions and a model version. It SHALL be reachable through one of two transports, selected by configuration:
- **HTTP (`POST /score`):** the local stack's container.
- **Direct invocation of an AWS Lambda function (`INFERENCE_LAMBDA_FUNCTION`):** production, where no scoring container runs on the application host.

Both transports SHALL carry the same request and response and the same scoring code.

The backend SHALL translate **any transport-level failure** into HTTP 503, never HTTP 500 and never a stack trace, because the service may be absent. Connection refusal and timeout are not the whole family:
- **HTTP:** a connection dying mid-response is an ordinary event for a container under a memory limit.
- **Lambda:** an unreachable endpoint, a throttle or a credential failure are the equivalents.

None of these SHALL be reported differently from the service being absent.

A failure the service itself reports, as opposed to one the transport reports, is a different situation and SHALL NOT be disguised as unavailability:
- an HTTP error status;
- a function error raised by the Lambda handler.

#### Scenario: The backend scores a batch through the inference service
- **WHEN** an inference run is triggered and the inference service is reachable
- **THEN** the backend sends one request containing the feature names and one row per in-scope elevator
- **AND** it receives one score and one contribution vector per row

#### Scenario: The inference service is unreachable
- **WHEN** an inference run is triggered and the inference service refuses the connection
- **THEN** the endpoint responds with HTTP 503
- **AND** no elevator score, feature or trend point is modified

#### Scenario: The connection dies mid-response
- **WHEN** the connection to the inference service is reset or the response is truncated part-way
- **THEN** the endpoint responds with HTTP 503
- **AND** no stack trace reaches the caller

#### Scenario: The inference service times out
- **WHEN** the inference service does not respond within the configured timeout
- **THEN** the endpoint responds with HTTP 503
- **AND** the database is left exactly as it was

#### Scenario: Production scores through the Lambda transport
- **WHEN** `INFERENCE_LAMBDA_FUNCTION` is configured and an inference run is triggered
- **THEN** the backend invokes that function once with the feature names and rows
- **AND** it makes no HTTP request to the scoring URL

#### Scenario: The scoring function cannot be invoked
- **WHEN** invoking the function fails at the transport or authorisation level (endpoint unreachable, throttled, access denied, timeout)
- **THEN** the endpoint responds with HTTP 503
- **AND** the database is left exactly as it was

#### Scenario: The scoring function reports an error
- **WHEN** the function runs and returns a function error
- **THEN** the endpoint responds with HTTP 502, not 503
- **AND** the database is left exactly as it was

## ADDED Requirements

### Requirement: The scoring function returns exactly what the scoring service returns
The system SHALL package the existing scorer as an AWS Lambda container image whose handler accepts:
- `{"operation": "model"}`, which returns the booster's feature names and model version;
- `{"operation": "score", "feature_names": [...], "rows": [[...]]}`, which returns scores, contributions and model version.

Both SHALL be computed by the same `Scorer` class the HTTP service uses. A column-order mismatch SHALL be returned as a client error naming the expected columns, as the HTTP service does with 422, and SHALL NOT be raised as a function error.

The function SHALL continue the caller's trace when the request carries W3C trace context. It SHALL flush its spans before returning, and SHALL never fail scoring because telemetry export failed.

#### Scenario: The function reproduces the golden vectors
- **WHEN** the function is invoked with the golden-vector rows
- **THEN** its scores and contributions equal the golden expected values

#### Scenario: A wrong column order is a client error, not a crash
- **WHEN** the function is invoked with feature names in a different order
- **THEN** it returns an error result naming the expected columns
- **AND** the backend reports it as it reports the HTTP service's 422

#### Scenario: An unknown operation is refused
- **WHEN** the function is invoked with an operation other than `model` or `score`
- **THEN** it returns an error result naming the accepted operations
