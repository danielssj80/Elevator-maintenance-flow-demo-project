## MODIFIED Requirements

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

## RENAMED Requirements

- FROM: `### Requirement: The ingest and inference endpoints are unreachable in production`
- TO: `### Requirement: The ingest and inference endpoints are reachable in production only behind a token`
