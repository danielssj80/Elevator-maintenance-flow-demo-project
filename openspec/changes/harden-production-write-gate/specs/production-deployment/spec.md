## ADDED Requirements

### Requirement: The ingest and inference endpoints are rate-limited at the proxy
The production reverse proxy SHALL rate-limit `POST /api/telemetry/readings`, `GET /api/telemetry/readings` and `POST /api/inference/run` per client address, and SHALL answer requests above the limit with HTTP 429 without forwarding them to the backend. The limit SHALL accommodate the scheduled producer (one ingest batch every 30 minutes and one inference run per day) with ample headroom, and SHALL NOT apply to any other route.

The token guard decides *who* may write; the limit bounds how fast anyone — including a holder of a leaked token, or a client probing for one — can hit the endpoints that write to the database and start inference runs on a single small instance.

#### Scenario: A burst above the limit is refused at the proxy
- **WHEN** one client sends more requests to `POST /api/telemetry/readings` than the limit and burst allow within the window
- **THEN** the excess requests answer HTTP 429
- **AND** those requests do not reach the backend

#### Scenario: The scheduled producer is never limited
- **WHEN** a client sends one request to each limited endpoint in a minute
- **THEN** none of them answers 429

#### Scenario: Other routes are not limited
- **WHEN** a client sends a burst of requests to `GET /api/elevators`
- **THEN** none of them answers 429 because of this limit

#### Scenario: The proxy configuration is valid
- **WHEN** the production nginx configuration is checked with `nginx -t`
- **THEN** it reports the configuration as valid
