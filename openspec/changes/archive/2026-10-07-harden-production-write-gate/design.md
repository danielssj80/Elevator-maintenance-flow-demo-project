## Context

`build_app()` in `backend/app/main.py` decides at startup whether the telemetry and inference routers exist, with `if environment != "production"`. `deployment_environment` already defaults to `production` (fail-closed when unset), but the comparison itself is fail-open for every value other than the one exact string.

`require_ingest_token` in `backend/app/core/ingest_auth.py` guards the two POST routes. It is fail-open — an unset token means open — and its docstring argues this is safe *only because the routers it guards never exist in production*. Change 2 (`serverless-n8n-orchestration`) needs them to exist there, so that argument expires with this change.

`GET /api/telemetry/readings` lives on the same router and carries no guard. Nothing in the repository calls it: the n8n workflows only `POST` to it, and the frontend never touches telemetry.

Production runs on a `t3.micro` behind one nginx container (`nginx/prod.conf`, mounted as `conf.d/default.conf`, so it is included inside the `http {}` context). That nginx is shared with the co-located portfolio site through an optional override file.

## Goals / Non-Goals

**Goals:**
- A misnamed, mistyped or missing environment can never open the write endpoints.
- Production can host the routers, but only behind a token that cannot be empty or trivially short, and only fail-closed.
- Bound the request rate on the endpoints that write to the database and start inference runs.
- Mergeable alone with zero production behaviour change.

**Non-Goals:**
- Provisioning the token in production (change 2, together with its only consumer).
- Per-client credentials, token rotation, or any user authentication for the rest of the API.
- Backend OTel export from production (change 2).
- Any frontend change. The frontend never calls these endpoints, so the frontend service-layer pattern is untouched.

## Decisions

### D1 — Allow-list classification in `core/config.py`
Add `NON_PRODUCTION_ENVIRONMENTS = frozenset({"local", "test", "ci"})` and `is_production(environment: str) -> bool`, which returns `environment not in NON_PRODUCTION_ENVIRONMENTS`. Matching is exact: no `.lower()`, no `.strip()`. Normalising would be friendlier, but every normalisation is a new way for an unexpected value to land on the open side. A developer who writes `Local` gets the closed side and a log line, which is the cheap failure.

*Alternatives:* a deny-list of production spellings (`production`, `prod`, …) — rejected: it is the current bug with more strings. A Pydantic `Literal` that refuses to start on unknown values — rejected: crashing production on a typo in an env file is an outage, and treating it as production is both safe and available.

`staging` and `development` are deliberately left off the list. No such environment exists today. The existing test that parametrises them as non-production is inverted to assert the opposite.

### D2 — Registration rule in `build_app()`
```
if not is_production(environment):        register; warn if no token (unchanged)
elif token and len(token) >= 32:          register
else:                                     do not register; log why (no token / token too short)
```
The guard remains at registration, which is the existing principle ("an unregistered route cannot be reached by a guard that was written wrong"). The 32-character floor makes an accidental `TELEMETRY_INGEST_TOKEN=x` the closed outcome. The intended value is `secrets.token_urlsafe(32)`, which yields 43 characters. The log names the reason and never the token or its length.

`build_app()` keeps reading the token from `settings` at build time; the tests already monkeypatch `settings.telemetry_ingest_token`, so no new parameter is needed.

### D3 — Fail-closed guard in production
`require_ingest_token` reads `settings.deployment_environment` per request. If the configured token is empty and `is_production(...)` is true, it raises the same 401 with the same body as a wrong token. This is defence in depth beside D2: it covers a token cleared at runtime and any future registration path that forgets D2. The response stays identical to the wrong-token case, so it is not an oracle for "is a guard configured".

The routers are layered correctly: the guard is a route dependency at the HTTP boundary, and services and repositories are untouched.

### D4 — Guard `GET /api/telemetry/readings`
Add `dependencies=[Depends(require_ingest_token)]` to the GET route. A public read of raw telemetry has no consumer and is free information for anyone probing the ingest path. Locally the dev compose already sets a token, so manual calls need the header. `docs/api-spec.yml` gains the security requirement on that operation.

### D5 — Rate limit in `nginx/prod.conf`
```
limit_req_zone $binary_remote_addr zone=elevator_ingest:1m rate=12r/m;
location = /api/telemetry/readings { limit_req zone=elevator_ingest burst=10 nodelay; limit_req_status 429; proxy_pass ...; }
location = /api/inference/run      { (same) }
```
Exact-match locations take precedence over the `/api/` prefix block, so no other API route is affected. `limit_req_zone` sits at the top of `prod.conf`, which nginx includes inside `http {}`. The zone name is prefixed `elevator_` so it cannot collide with the portfolio override. The rates leave about 360× headroom over the producer: one batch every 30 minutes, one run a day.

*Alternative:* rate limiting in FastAPI (slowapi) — rejected: it spends backend memory and a database session on requests that should never reach it, on the smallest instance we run.

### D6 — `conftest.py` pins the environment instead of defaulting it
`os.environ.setdefault("DEPLOYMENT_ENVIRONMENT", "local")` becomes an unconditional assignment, so a shell with `DEPLOYMENT_ENVIRONMENT=production` exported no longer silently changes what the suite tests. Tests that need another value already pass it explicitly to `build_app(environment=...)` or use a subprocess with their own environment.

## Risks / Trade-offs

- **A developer runs `uvicorn` with `DEPLOYMENT_ENVIRONMENT=dev`** and gets 404s on the ingest routes. → The startup log states why, and `docs/backend-standards.md` lists the three accepted names.
- **The read endpoint now needs the token locally.** → Nothing calls it; the docs show the header.
- **Rate limit per IP while Lambda egress IPs vary.** → Irrelevant at one request per 30 minutes; the limit exists for abuse, not for the producer.
- **The fail-closed guard reads `settings`, not `build_app`'s `environment` argument.** In tests that build a production app while `settings` says `local`, the guard follows `settings`. → The production-with-token tests also set `settings.deployment_environment`, so both halves agree.

## Migration Plan

Merge → deploy as usual. Production has no token in `/etc/elevator/.env`, so D2 keeps the routers unregistered: the same 404 as today, now with an explicit log line. Verify after deploy that `POST /api/telemetry/readings` returns 404 in production and that the log line appears. Rollback is a revert; there is no data or schema involved.

## Open Questions

None blocking. Where the token canonically lives (SSM SecureString) and how it reaches `/etc/elevator/.env` is decided in change 2.
