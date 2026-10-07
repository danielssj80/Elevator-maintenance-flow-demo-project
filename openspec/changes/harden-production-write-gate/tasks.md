# Tasks: harden-production-write-gate

> Backend + nginx only. No frontend change (E2E step not applicable), no DB schema change (no Alembic step).
> Every guard gets its mutation run inline: break it, see the named test go red, restore it — noted on the task line.

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/harden-production-write-gate` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. Environment classification (TDD)

- [ ] 1.1 Write failing tests for `is_production()`: `local`/`test`/`ci` → False; `production`, `prod`, `Production`, `PRODUCTION`, `staging`, `development`, `""`, `" local"`, `"local "` → True
- [ ] 1.2 Implement `NON_PRODUCTION_ENVIRONMENTS` and `is_production()` in `app/core/config.py`
- [ ] 1.3 Tests pass; mutation: add `.lower()` or a deny-list → red

## 2. Registration rule (TDD)

- [ ] 2.1 Update `test_production_gating.py`: `staging`/`development` now gated off; add production-without-token (404 + reason logged), production-with-short-token (absent + "too short" logged, token not in log), production-with-valid-token (registered; no token → 401; token → processed), unknown names gated off
- [ ] 2.2 Implement D2 in `build_app()` (`MIN_PRODUCTION_INGEST_TOKEN_LENGTH = 32`)
- [ ] 2.3 Tests pass; mutations: revert to `!= "production"`; drop the length check; register regardless of token → each red

## 3. Fail-closed guard in production (TDD)

- [ ] 3.1 Write failing tests in `test_ingest_auth.py`: production + empty token → 401 with and without header, same body as the wrong-token case; non-production + empty token → still open
- [ ] 3.2 Implement D3 in `require_ingest_token`
- [ ] 3.3 Tests pass; mutation: remove the production branch → red

## 4. Guard the read endpoint (TDD)

- [ ] 4.1 Write failing test: token configured, `GET /api/telemetry/readings` without header → 401, with header → 200
- [ ] 4.2 Add `Depends(require_ingest_token)` to the GET route
- [ ] 4.3 Tests pass; mutation: remove the dependency → red; update existing GET tests that relied on no guard

## 5. Rate limit at the proxy

- [ ] 5.1 Write failing static test (`test_nginx_prod_conf.py`): `limit_req_zone` declared; exact-match locations for `/api/telemetry/readings` and `/api/inference/run` carry `limit_req` + `limit_req_status 429`; the generic `/api/` location carries no `limit_req`
- [ ] 5.2 Implement D5 in `nginx/prod.conf`
- [ ] 5.3 Tests pass; mutation: drop `limit_req` from one location → red

## 6. Suite hygiene

- [ ] 6.1 `conftest.py`: assign `DEPLOYMENT_ENVIRONMENT=local` unconditionally (D6)
- [ ] 6.2 Verify: run the gating tests with `DEPLOYMENT_ENVIRONMENT=production` exported → still green

## 7. Review and Update Existing Tests (MANDATORY)

- [ ] 7.1 Review `test_production_gating.py`, `test_ingest_auth.py`, `test_dev_compose.py`, telemetry router tests for assumptions invalidated by D1–D4 (docstrings included)
- [ ] 7.2 Update the affected tests and docstrings; `test_prod_compose_does_not_configure_an_ingest_token` keeps its assertion (the token belongs in the out-of-repo env file) with a rewritten rationale

## 8. Unit Tests and DB State Verification (MANDATORY)

- [ ] 8.1 Capture pre-test DB baseline (table counts in the test database)
- [ ] 8.2 Run targeted tests (`test_production_gating`, `test_ingest_auth`, `test_nginx_prod_conf`, `test_config_environment`)
- [ ] 8.3 Run the full backend suite + `ruff check .` the way CI does (Python 3.12, `postgres:16-alpine`)
- [ ] 8.4 Verify post-test DB state matches baseline
- [ ] 8.5 Create report `openspec/changes/harden-production-write-gate/reports/YYYY-MM-DD-step-8-unit-tests.md`

## 9. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [ ] 9.1 Backend with `DEPLOYMENT_ENVIRONMENT=production`, no token → `POST /api/telemetry/readings` and `POST /api/inference/run` 404; `/health`, `GET /api/elevators` 200; startup log line present
- [ ] 9.2 Production + 43-char token → POST without header 401, with header 200/201 (a single test reading; delete it afterwards to restore DB state); GET readings without header 401
- [ ] 9.3 Production + short token → routes 404, "too short" in log, token absent from log
- [ ] 9.4 `DEPLOYMENT_ENVIRONMENT=prod` → treated as production (404)
- [ ] 9.5 nginx: `nginx -t` on `prod.conf` with throwaway self-signed certs → valid; burst against the limited location → 429s appear, `GET /api/elevators` burst → no 429
- [ ] 9.6 Create report `reports/YYYY-MM-DD-step-9-endpoint-testing.md`

## 10. E2E Testing with Playwright (NOT APPLICABLE)

- [ ] 10.1 No frontend change — not applicable

## 11. Update Technical Documentation (MANDATORY)

- [ ] 11.1 `docs/api-spec.yml`: availability notes on telemetry/inference (production only with a configured token), security on `GET /api/telemetry/readings`, 429 response on the limited operations
- [ ] 11.2 `docs/backend-standards.md`: allow-list rule, registration rule, fail-closed-in-production guard
- [ ] 11.3 `docker-compose.prod.yml`: rewrite the "Do not set this to anything else" comment to describe the new rule
- [ ] 11.4 `docs/data-model.md`: no change (no entity changes)

## 12. Independent Adversarial Review (MANDATORY before archive)

- [ ] 12.1 Cold-start agent in a worktree, mutation-first, given branch + base commit only
- [ ] 12.2 Address findings; record them in `reports/`

## 13. Archive and PR

- [ ] 13.1 Sync delta specs into `openspec/specs/`, archive the change
- [ ] 13.2 Commit, push, open PR (merge needs user approval)
- [ ] 13.3 After merge and deploy: verify production still answers 404 on `POST /api/telemetry/readings` and the startup log names the reason
