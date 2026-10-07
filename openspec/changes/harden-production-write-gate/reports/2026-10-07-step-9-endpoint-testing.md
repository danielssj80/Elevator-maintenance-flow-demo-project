# Step 9 Report — Endpoint Testing

- Date: 2026-10-07
- Change: harden-production-write-gate

Backend run with `uvicorn app.main:app` from the CI-equivalent image against a migrated
`elevator_db` (`alembic upgrade head`) on `postgres:16-alpine`, exposed on `localhost:8001`.

## 9.1 Production, no token
| Request | Status |
|---|---|
| `POST /api/telemetry/readings` | 404 ✓ |
| `POST /api/inference/run` | 404 ✓ |
| `GET /api/telemetry/readings?elevator_id=ELV-001` | 404 ✓ |
| `GET /health` | 200 ✓ |
| `GET /api/elevators` | 200 ✓ |

Log: `Ingest and inference routers not registered: the deployment environment 'production' is treated as production and TELEMETRY_INGEST_TOKEN is not configured.`

## 9.2 Production, 43-character token (`secrets.token_urlsafe(32)`)
| Request | Status |
|---|---|
| `POST /api/telemetry/readings`, no header | 401 ✓ |
| same, wrong header | 401 `{"detail":"Invalid or missing X-Ingest-Token"}` ✓ |
| same, correct header, one reading for ELV-001 | 201 `accepted: 1` ✓ |
| `GET /api/telemetry/readings`, no header | 401 ✓ |
| same, correct header | 200, the reading returned ✓ |
| `POST /api/inference/run`, no header | 401 ✓ |

`POST /api/inference/run` with the token was deliberately not called: it re-scores the fleet.
DB state: `telemetry_readings` 0 → 1 → deleted (`source='gate-endpoint-test'`) → 0. Restored.
The token appears 0 times in the container log.

## 9.3 Production, 31-character token
`POST /api/telemetry/readings` with that token → 404 ✓. Log: `… TELEMETRY_INGEST_TOKEN is too short to be accepted there.` Token in log: 0 occurrences ✓.

## 9.4 `DEPLOYMENT_ENVIRONMENT=prod`
`POST /api/telemetry/readings` → 404 ✓. Log names `'prod'` as treated as production.
Control, `local` with no token: route registered (422 on an empty body) and the
"registered and accept unauthenticated requests" warning logged ✓.

## 9.5 nginx (`nginx/prod.conf`, `nginx:alpine`, throwaway self-signed cert, stub upstreams)
- `nginx -t`: syntax is ok, test is successful ✓
- Burst of 25 from one client, fresh zone:
  - `POST /api/telemetry/readings`: 11 × 200, 14 × 429 ✓ (1 + burst 10)
  - then `GET /api/telemetry/readings?...`: 25 × 429; `POST /api/inference/run`: 25 × 429 — one shared bucket per client, by design
  - `GET /api/elevators`: 25 × 200 ✓ (not limited)
- nginx logged `limiting requests` 64 times.
- Producer cadence, fresh zone: one request to each limited route → 200, 200, 200 ✓

## Outcome
PASS
