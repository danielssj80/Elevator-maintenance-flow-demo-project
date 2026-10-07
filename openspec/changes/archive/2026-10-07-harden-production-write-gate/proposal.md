## Why

The orchestration tier is moving to production (Notion: *Run the n8n orchestration tier in production*, change 1 of 2), and its producer needs `POST /api/telemetry/readings` and `POST /api/inference/run` to exist there. Today production makes them unreachable by not registering the routers at all, and two weaknesses make simply flipping that switch unsafe:

- **The gate is an inequality against one exact string.** `environment != "production"` treats `prod`, `Production`, `PRODUCTION`, a typo or any unknown value as *not* production and opens the write endpoints — the same fail-open class the `telemetry-ingestion-inference` review found as a Blocker (backlog task *Harden the production gate*).
- **The ingest token is fail-open by design**, which was correct only because it never guarded anything in production. The moment the routers register there, an unset or empty token would publish unauthenticated write endpoints on the internet.

This change makes registering the routers in production safe *before* anything calls them. It is mergeable on its own: with no token provisioned, production behaves exactly as it does today.

## What Changes

- **Environment classification becomes an allow-list.** Only `local`, `test` and `ci` are non-production; every other value — including unset, empty, `prod`, `staging`, or a different case — is production.
- **Production registers the telemetry and inference routers only when an ingest token is configured** and is at least 32 characters long. Without one, or with one that is too short, the routers stay unregistered and the startup log says why.
- **The ingest guard is fail-closed in production**: an empty configured token rejects with 401 instead of letting the request through. The documented fail-open behaviour remains for non-production environments only.
- **`GET /api/telemetry/readings` is guarded by the same token.** It has no consumer and would otherwise become a public read of raw telemetry. **BREAKING** for anyone calling it locally without the header (nothing in the repository does).
- **nginx rate-limits the two write endpoints** in production and answers 429 above the limit, without reaching the backend.
- **The test suite stops inheriting `DEPLOYMENT_ENVIRONMENT` from the shell** (`conftest` used `setdefault`).
- The token is **not** provisioned in production by this change; that happens with the producer in change 2 (`serverless-n8n-orchestration`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `telemetry-ingestion`: *The ingest and inference endpoints are unreachable in production* becomes conditional on a configured token, with allow-list environment classification; *The write endpoints require an ingest token when one is configured* becomes fail-closed in production and covers the read endpoint.
- `production-deployment`: adds rate limiting of the ingest and inference endpoints at the reverse proxy.

## Impact

- **Code**: `backend/app/core/config.py` (environment classification), `backend/app/main.py` (registration rule), `backend/app/core/ingest_auth.py` (fail-closed in production), `backend/app/routers/telemetry.py` (guard on GET), `nginx/prod.conf` (rate limit), `backend/tests/conftest.py`.
- **Tests**: `test_production_gating.py`, `test_ingest_auth.py`, `test_dev_compose.py`, new nginx config test.
- **API**: no new endpoints or schemas. Availability in production changes from "never" to "only with a configured token"; the read endpoint now requires the token everywhere.
- **Docs**: `docs/api-spec.yml` (availability notes, security on GET), `docs/backend-standards.md` (gate and token rules), `docker-compose.prod.yml` comment.
- **Production**: no behaviour change at merge — no token is configured there, so the routers remain unregistered.
