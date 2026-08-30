# Proposal: otel-observability

## Why

The service has no observability. The only telemetry in the entire codebase is a liveness `GET /health` that does not touch the database, and one `logger.warning` in `briefing_service.py`; there is no logging configuration, no metrics endpoint, no tracing, and no request correlation. When the Bedrock briefing call fails, the deterministic fallback silently absorbs it and the response still returns HTTP 200 with `source: "fallback"` — an outage is invisible unless someone inspects individual responses.

Two further problems are structurally invisible today:

- `BedrockClient.generate()` is a blocking boto3 call with a 5-second timeout, invoked from inside `async def get_briefing`. It stalls the event loop for every concurrent request.
- Milestone M5 introduces a scheduled ingest and inference path spanning three services. Without tracing there is no way to tell whether a run failed, how long it took, or where.

This change also produces the primary artifact for a Grafana Labs application, where the role owns the end-to-end journey of instrumenting a workload and sending useful OpenTelemetry data to Grafana Cloud.

## What Changes

- Add the OpenTelemetry SDK and instrumentation packages to `backend/requirements.txt`, pinned.
- Add `backend/app/core/telemetry.py` configuring a `TracerProvider` and `MeterProvider` programmatically and enabling instrumentation for FastAPI, SQLAlchemy, httpx and botocore. Configuration is read from new `Settings` attributes; `OTEL_ENABLED` defaults to `false` so CI and the test suite are unaffected.
- Add a domain span `briefing.generate` around the Bedrock path, supplemented with `gen_ai.*` attributes, and move the blocking boto3 call onto a worker thread with `anyio.to_thread.run_sync`.
- Add `backend/app/services/fleet_health_service.py` and `backend/app/core/metrics.py`: a periodically refreshed snapshot of fleet state, exposed through observable-gauge callbacks as a small number of low-cardinality metrics.
- Add an OTel Collector and a local `grafana/otel-lgtm` stack to `docker-compose.yml`, with the Collector exporting to both the local stack and Grafana Cloud.
- Add four provisioned Grafana dashboards under `observability/grafana/dashboards/`.

## Capabilities

### New Capabilities

- `observability`: the system emits traces, metrics and logs over OTLP; a Collector routes them to a local stack and to Grafana Cloud; a defined set of fleet-health metrics is exposed; telemetry never carries prompt or completion content.

### Modified Capabilities

- None. No existing requirement changes behaviour. API responses, database schema and the frontend are untouched.

## Impact

- **New files**: `backend/app/core/telemetry.py`, `backend/app/core/metrics.py`, `backend/app/services/fleet_health_service.py`, `backend/app/services/genai_attributes.py`, `backend/tests/unit/test_telemetry_spans.py`, `backend/tests/unit/test_fleet_health_service.py`, `observability/otel-collector-config.yaml`, `observability/.env.example`, `observability/grafana/dashboards/*.json`
- **Modified files**: `backend/requirements.txt`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/services/briefing_service.py`, `backend/app/services/bedrock_client.py`, `backend/tests/conftest.py`, `docker-compose.yml`, `.gitignore`, `docs/backend-standards.md`
- **Not modified**: `docker-compose.prod.yml`. The observability stack is local-only; production behaviour is unchanged and no new port is exposed there.
- **Frontend**: none. Grafana is a separate audience on its own port; no API response shape changes.
- **Database**: no schema change, no migration.
- **Secrets**: `GRAFANA_CLOUD_INSTANCE_ID` and `GRAFANA_CLOUD_API_TOKEN` in a git-ignored `.env`, with a committed `.env.example`.
- **Runtime cost**: two additional containers locally (`otel-collector` ~120 MB, `lgtm` ~0.9–1.2 GB), both with explicit `mem_limit`.
