# Step 12 Report — Independent Adversarial Review

- Date: 2026-10-07
- Change: harden-production-write-gate
- Reviewer: cold-start agent in an isolated worktree, given only the branch, base commit (`2c45d7f`), the skill and how to run the suite
- Reviewed: `2c45d7f...7d59c6f`

## Verdict
**PASS WITH GAPS.** No blocker, no major. No way found to reach the telemetry/inference routes in
production without the token; every mutation weakening the primary gate was caught. Reproduced the
step-9 claims (11×200 then 429; shared bucket) and probed path variants (`%72`, `%2F`, `//`, `/./`,
`;x`, trailing slash, HEAD), header edge cases (underscore, duplicate, whitespace) and log leakage
(token 0 times in logs).

## Findings and resolution

| # | Severity | Finding | Resolution | Evidence after fix |
|---|---|---|---|---|
| 1 | Minor | Fail-closed guard only tested with the literal `production`; mutation `== "production"` (M8) survived | `test_an_empty_token_in_production_rejects_everything` parametrised over `production`, `prod`, `staging`, `""` | M8 → 6 failed |
| 2 | Minor | `POST …/readings/` → 307 `Location: http://…`: a client re-sending `X-Ingest-Token` on redirect would put it on port 80 | `proxy_redirect http:// https://;` in the two exact locations and `/api/`; new spec requirement *API redirects keep the client on HTTPS* | Live: 307 `Location=https://…` for both routes; static test fails when removed from `/api/` |
| 3 | Minor | nginx tests pinned shape, not values: `rate=100000r/s` (M17), `burst=100000` (M18), `limit_req_dry_run on` (M22), port-80 server proxying `/api/` (M21) all survived | Tests pin `rate=12r/m`, `burst=10 nodelay`, forbid `limit_req_dry_run`, require the port-80 server to contain only `listen`/`server_name`/`return 301` | M17, M18, M22 → 1 failed each; M21 → 2 failed |
| 4 | Minor | Leak check covered only the whole token and its length; logging `token[:4]` (M13) survived | Every 4-character window of the token is checked against the log messages | M13 → 1 failed |
| 5 | Minor | Spec scenario "suite does not inherit the environment from the shell" had no test; `setdefault` (M16) survived | Subprocess test runs `conftest.py` with `DEPLOYMENT_ENVIRONMENT=production` exported and expects `local` | M16 → 1 failed |
| N1 | Nit | Stale comments in `config.py` ("only ever applies to routers that do not exist in production") | Rewritten | — |
| N2 | Nit | `build_app(environment=…)` and the guard read the environment from different places | Comment in `require_ingest_token` | — |
| N3 | Nit | Per-IP bucket shared across GET/POST/inference; IPv6 rotation | Accepted by design: the 32+ character token makes guessing infeasible; the limit bounds cost, not authentication | — |

## After the fixes
- `ruff check .`: All checks passed
- `pytest tests/`: **298 passed** (286 + 12 new parametrisations/tests)

## Outcome
PASS
