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

### Requirement: API redirects keep the client on HTTPS
The production reverse proxy SHALL rewrite any `Location` header returned by the API from `http://` to `https://`, so that a redirect issued by the application (for example Starlette's trailing-slash redirect, which builds its URL from the plain-HTTP hop between the proxy and the backend) never sends a client — and any `X-Ingest-Token` header the client re-sends on redirect — to the cleartext port.

#### Scenario: A trailing-slash request is redirected to HTTPS
- **WHEN** a client sends `POST https://elevator.dsaavedra.dev/api/telemetry/readings/`
- **THEN** the response is a redirect whose `Location` begins with `https://`

#### Scenario: The cleartext server only redirects
- **WHEN** the production proxy configuration is inspected
- **THEN** the server listening on port 80 contains nothing but a redirect to HTTPS
