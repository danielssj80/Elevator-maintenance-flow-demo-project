# Tasks: otel-observability

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/2026-08-28-otel-observability` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. Dependencies

- [x] 1.1 Add pinned OTel packages to `backend/requirements.txt`: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-semantic-conventions`, `opentelemetry-exporter-otlp-proto-http`, and instrumentation for `fastapi`, `sqlalchemy`, `httpx`, `botocore`, `logging`
- [x] 1.2 Do NOT add `opentelemetry-distro` (see design.md D2) and do NOT add the asyncpg instrumentation (D3)
- [x] 1.3 Install into the dev environment and confirm pip resolves without conflicts
- [x] 1.4 Run `ruff check .` — clean

## 2. Configuration

- [x] 2.1 Write failing test asserting `settings.otel_enabled` is `False` when `OTEL_ENABLED` is unset
- [x] 2.2 Add to `backend/app/core/config.py`: `otel_enabled`, `otel_exporter_otlp_endpoint`, `otel_service_name`, `otel_service_version`, `deployment_environment`, `fleet_metrics_refresh_seconds`
- [x] 2.3 Test passes

## 3. Telemetry Core (TDD)

- [x] 3.1 Add an `InMemorySpanExporter` fixture to `backend/tests/conftest.py`
- [x] 3.2 Write failing test: `configure_telemetry()` registers no provider and opens no connection when `otel_enabled` is `False` (patch via `monkeypatch.setattr(settings, ...)`, not `setenv` — see design.md D8)
- [x] 3.3 Write failing test: with telemetry enabled, `GET /api/elevators` produces a server span whose `http.route` is the route template
- [x] 3.4 Write failing test: that same request produces a child span for the `SELECT` against `elevators` (guards the silent `sync_engine` failure, D3)
- [x] 3.5 Write failing test: a request carrying a `traceparent` header produces a server span with the caller's trace ID
- [x] 3.6 Implement `backend/app/core/telemetry.py`: `Resource`, `TracerProvider`, `MeterProvider`, OTLP HTTP exporters, and `configure_telemetry(app)` / `shutdown_telemetry()`
- [x] 3.7 Instrument FastAPI, SQLAlchemy (bound with `engine=engine.sync_engine`), httpx, botocore and logging
- [x] 3.8 All tests in 3.2–3.5 pass

## 4. Application Wiring

- [x] 4.1 Call `configure_telemetry(app)` in `backend/app/main.py` before middleware and router registration
- [x] 4.2 Wrap `seed_database` in `lifespan` with a root span so startup seeding is visible
- [x] 4.3 Register `shutdown_telemetry()` on lifespan shutdown
- [x] 4.4 Confirm the existing test suite still passes with telemetry disabled

## 5. Observability Stack (docker-compose)

- [x] 5.1 Create `observability/otel-collector-config.yaml`: OTLP receiver, `memory_limiter` / `batch` / `resource` processors, local exporter only at this stage
- [x] 5.2 Add `otel-collector` and `lgtm` services to `docker-compose.yml` with pinned image tags and explicit `mem_limit`
- [x] 5.3 Publish Grafana as `3001:3000` (host `3000` belongs to `frontend`); only the Collector publishes `4317`/`4318`
- [x] 5.4 Wire the backend service's OTel environment variables, using the **base** endpoint URL (see the base-vs-full trap in design.md)
- [x] 5.5 Bring the stack up and confirm all services are healthy

## 6. Verify Real Telemetry Reaches the Collector

- [x] 6.1 Call `GET /api/elevators` against the running stack
- [x] 6.2 Confirm in Tempo that the trace exists with an HTTP server span
- [x] 6.3 Confirm the same trace contains database spans — if absent, the SQLAlchemy binding is wrong (D3)
- [x] 6.4 Confirm HTTP metrics appear in Prometheus labelled by route template, not raw path

## 7. Fleet Health Metrics (TDD)

- [ ] 7.1 Write failing tests for `FleetHealthService.compute_snapshot()`: counts by risk level, inference run age, stale-telemetry count
- [ ] 7.2 Implement `backend/app/services/fleet_health_service.py`
- [ ] 7.3 Implement `backend/app/core/metrics.py`: frozen `FleetHealthSnapshot`, module singleton, instruments and observable-gauge callbacks that only read the snapshot (D5)
- [ ] 7.4 Write failing test: the refresh task starts on startup and is cancelled cleanly on shutdown
- [ ] 7.5 Add the refresh task to `lifespan` with `asyncio.create_task` and graceful cancellation
- [ ] 7.6 Write failing test: a refresh failure leaves the previous snapshot intact and does not raise
- [ ] 7.7 All tests pass; confirm no metric carries `elevator.id` as an attribute

## 8. GenAI Instrumentation and Event-Loop Fix (TDD)

- [ ] 8.1 Write failing test: `briefing.generate` span records `briefing.source` `bedrock` on success and `fallback` when Bedrock raises
- [ ] 8.2 Write failing test: no span attribute contains prompt or completion text
- [ ] 8.3 Write failing test: a cache hit records `briefing.cache_hit` true and produces no model span
- [ ] 8.4 Implement `backend/app/services/genai_attributes.py` emitting both `gen_ai.provider.name` and the deprecated `gen_ai.system` (D4)
- [ ] 8.5 Add the `briefing.generate` domain span in `briefing_service.py`
- [ ] 8.6 Move the blocking `BedrockClient.generate()` call onto a worker thread with `anyio.to_thread.run_sync` (D6)
- [ ] 8.7 Write failing test: the botocore model span is a child of `briefing.generate` after the thread offload
- [ ] 8.8 All tests pass

## 9. Grafana Cloud Export

- [ ] 9.1 Add `basicauth` extension and the `otlphttp/grafana_cloud` exporter to the Collector config, using the **base** gateway URL
- [ ] 9.2 Create `observability/.env.example`; confirm `.env` is git-ignored and add it if not
- [ ] 9.3 Enable Collector self-telemetry so `otelcol_exporter_send_failed_spans` is observable
- [ ] 9.4 Verify a trace reaches BOTH local Tempo and Grafana Cloud
- [ ] 9.5 Verify `otelcol_exporter_send_failed_spans` for the cloud exporter is 0

## 10. Dashboards

- [ ] 10.1 Build `fleet-health.json`: counts by risk level, inference last-run age, stale-telemetry count
- [ ] 10.2 Build `api-red.json`: rate, errors and duration by route and status code
- [ ] 10.3 Build `genai.json`: bedrock vs fallback split, fallback rate, token usage, latency, cache hit ratio
- [ ] 10.4 Build `orchestration.json` skeleton — panels for the n8n change to fill
- [ ] 10.5 Export dashboard JSON into `observability/grafana/dashboards/` and verify the provisioning mount path works on a fresh start

## 11. Review and Update Existing Tests (MANDATORY)

- [ ] 11.1 Review `backend/tests/` for tests affected by the `main.py`, `config.py`, `briefing_service.py` and `bedrock_client.py` changes
- [ ] 11.2 Update any test invalidated by the `anyio.to_thread` offload in `briefing_service`
- [ ] 11.3 Confirm no test depends on telemetry being enabled

## 12. Unit Tests and DB State Verification (MANDATORY)

- [ ] 12.1 Capture pre-test DB baseline (row counts for `elevators`, `elevator_features`, `elevator_trend_points`, `visit_reports`)
- [ ] 12.2 Run targeted unit tests: `pytest tests/unit/test_telemetry_spans.py tests/unit/test_fleet_health_service.py -v`
- [ ] 12.3 Run the full suite with coverage: `pytest tests/ -v --cov=app --cov-report=term-missing`
- [ ] 12.4 Confirm coverage on new services and core modules is at least 80%
- [ ] 12.5 Verify post-test DB state is unchanged from the baseline
- [ ] 12.6 Create report `reports/2026-08-28-step-12-unit-tests.md`
- [ ] 12.7 Mark complete only after the report exists and all tests pass

## 13. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [ ] 13.1 Ensure the backend and the observability stack are running (start them if not)
- [ ] 13.2 `GET /api/elevators` — verify 200 and that the trace appears in Tempo with database spans
- [ ] 13.3 `GET /api/elevators/{id}` — verify 200 and route-template span naming
- [ ] 13.4 `GET /api/elevators/{id}/briefing` — verify 200, and that the trace shows `briefing.generate` with a nested GenAI span carrying token counts and no message content
- [ ] 13.5 `GET /api/elevators/ELV-999` — verify 404 and that the span is not marked as an error
- [ ] 13.6 `POST /api/elevators/{id}/report` with an invalid body — verify 422; then a valid body, verify 201, then DELETE the created row to restore DB state
- [ ] 13.7 `GET /health` — verify 200
- [ ] 13.8 Verify the DB is back to its pre-test state
- [ ] 13.9 Create report `reports/2026-08-28-step-13-endpoint-testing.md`

## 14. E2E Testing with Playwright MCP (NOT APPLICABLE)

- [ ] 14.1 Not applicable — this change touches no file under `frontend/` and changes no API response shape. Grafana is a separate audience on its own port. Record this explicitly in the step 13 report rather than creating an E2E report.

## 15. Update Technical Documentation (MANDATORY)

- [ ] 15.1 Add an observability section to `docs/backend-standards.md`: the OTel setup pattern, the `sync_engine` binding requirement, the base-vs-full endpoint rule, and the no-prompt-content policy
- [ ] 15.2 Document in `docs/backend-standards.md` that configuration-dependent tests must patch `settings` attributes directly, because `Settings` is evaluated at import time
- [ ] 15.3 `docs/api-spec.yml` — no update required (no endpoint or schema change); state this explicitly
- [ ] 15.4 `docs/data-model.md` — no update required (no entity or field change); state this explicitly
- [ ] 15.5 Propose exact wording for each `docs/` edit and wait for explicit approval before writing (per `docs/documentation-standards.md`)
