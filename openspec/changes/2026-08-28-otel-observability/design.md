# Design: otel-observability

## Architecture placement

The three-layer backend architecture is unchanged: routers → services → repositories. Observability attaches at two points only.

- **Cross-cutting setup** lives in `app/core/telemetry.py`, called once from `main.py` before routers are registered. `core/` already holds `config.py` and `exceptions.py`; framework-level wiring belongs there, not in a service.
- **Domain spans and metrics** live in the **service layer**, where the business meaning is. `BriefingService` owns the `briefing.generate` span because only it knows whether a result came from Bedrock or the fallback. `FleetHealthService` owns the snapshot because deriving risk levels is a domain rule.

Repositories stay pure SQLAlchemy and gain no telemetry code; their spans come free from SQLAlchemy instrumentation. Routers are untouched; their spans come free from FastAPI instrumentation.

The frontend service-layer pattern is not involved — no frontend file changes.

## Key decisions

### D1 — Programmatic setup, not the `opentelemetry-instrument` CLI wrapper

Four reasons specific to this repository:

1. A MeterProvider with observable-gauge callbacks is required (D5). The CLI wrapper creates a provider but offers no hook to register callbacks into it, so `telemetry.py` would have to exist anyway — and then two configuration sources compete.
2. The SQLAlchemy async-engine binding (D3) cannot be expressed as an environment variable.
3. The `migrate` service reuses the backend image with an overridden `command`. Wrapping the Dockerfile `ENTRYPOINT` would instrument a one-shot migration container; programmatic setup scopes instrumentation to the app that calls it.
4. `configure_telemetry()` can be driven by an `InMemorySpanExporter` in tests, which is how this code reaches the 80% coverage bar. The CLI wrapper is untestable in-process.

### D2 — `-proto-http`, and no `opentelemetry-distro`

HTTP avoids the `grpcio` C-extension wheel, matches the Collector's `:4318`, and matches Grafana Cloud's OTLP gateway, which is HTTP-only. `opentelemetry-distro` exists to power the CLI wrapper rejected in D1 and would add a competing auto-configuration path.

### D3 — Instrument SQLAlchemy, not asyncpg, and bind the existing engine

Enabling both instrumentations nests an `asyncpg` span inside every SQLAlchemy span, doubling trace volume for no extra information.

The engine in `app/database.py` is created by `create_async_engine` **at module import time**, before `configure_telemetry()` runs. `SQLAlchemyInstrumentor().instrument()` with no arguments patches `create_engine` and therefore misses it entirely, producing **zero database spans with no error raised**. The instrumentation must be bound explicitly:

```python
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
```

A test asserting that a `SELECT` span exists after `GET /api/elevators` is mandatory, because this failure is silent.

### D4 — GenAI attributes: supplement, do not hand-roll

`opentelemetry-instrumentation-botocore` already emits `gen_ai.*` spans for `bedrock-runtime.converse()`, including token usage. Hand-writing a model span would duplicate it. Instead a domain span wraps the call and `genai_attributes.py` centralises attribute names.

As of 2026 the GenAI conventions were moved out of the main semantic-conventions repository and remain entirely in Development status, with no tagged release and therefore no schema URL to pin. Attribute names have already moved once (`gen_ai.system` → `gen_ai.provider.name`, `prompt_tokens` → `input_tokens`). Both generations are emitted so that dashboards keep working across the rename, and every name is defined in one module so a future rename is a single edit.

Prompt and completion content is deliberately never recorded. `_build_prompt_message` embeds fleet risk data, technician names and visit notes; recording it would ship that to Grafana Cloud. The omission carries an explicit comment so it is not "fixed" later.

### D5 — Metrics: a refreshed snapshot, not a database query in the callback

The metric reader invokes observable-gauge callbacks on its own background thread, where there is no event loop and an `AsyncSession` cannot be awaited. Two tempting approaches are rejected:

- `asyncio.run_coroutine_threadsafe` back onto the main loop deadlocks precisely when the loop is blocked — which, until D6, is every uncached briefing.
- Adding a synchronous driver just for metrics introduces a second connection pool and a second credentials path.

Instead an immutable `FleetHealthSnapshot` is rebound by an async refresh task owned by the FastAPI `lifespan`, and the callbacks only read it. Rebinding a frozen dataclass is atomic, so no lock is needed. The snapshot is also refreshed synchronously at the end of a successful inference run so dashboards react within a second rather than up to the refresh interval.

This loop is a scheduler. Naming it as such is preferable to pretending the application has none.

### D6 — Move the blocking Bedrock call to a worker thread

`BedrockClient.generate()` is a blocking boto3 call inside `async def get_briefing`, stalling the event loop for up to its 5-second timeout. `anyio.to_thread.run_sync` copies contextvars into the worker thread, so the OpenTelemetry context propagates and the botocore span still nests under `briefing.generate`. Instrumenting the service is what makes this defect visible; fixing it is in scope because D5 must not depend on a blockable loop.

### D7 — Run our own Collector alongside `grafana/otel-lgtm`

The LGTM image bundles a Collector, but it is an ingest endpoint for its own backends. Ours owns routing: the Grafana Cloud fan-out, batching, memory limiting, redaction, and later the n8n Prometheus scrape. Only our Collector publishes `4317`/`4318` to the host; LGTM's Grafana is published as `3001:3000` because the `frontend` service already owns host port `3000`.

Cardinality and volume are actively managed: `elevator.id` is never a metric attribute, HTTP metrics are labelled by route template, and explicit `mem_limit` values prevent a runaway container from taking down the host.

### D8 — Configuration on the existing hand-rolled `Settings`

`Settings` uses plain `os.getenv` in class-level attributes evaluated at import time, and `settings` is a module singleton. This is fine here because values come from compose environment, not from anything mutable at runtime. It does dictate how tests patch configuration: `monkeypatch.setenv` followed by re-import does **not** work, and tests must use `monkeypatch.setattr(settings, "otel_enabled", True)`. This is documented in `docs/backend-standards.md` because it will affect every future configuration-dependent test.

## Trap: base URL versus full URL

`OTEL_EXPORTER_OTLP_ENDPOINT` is a reserved SDK variable holding a **base** URL to which the SDK appends `/v1/traces`. Passing an explicit `endpoint=` to an exporter constructor makes the SDK treat it as the **full** URL and skip that append, so spans are POSTed to the base and rejected — and the failure is logged at DEBUG, so it looks like nothing is being exported.

The same base-versus-full ambiguity recurs at the Collector's Grafana Cloud exporter, and again in the n8n change. The rule in all three places: set the base URL, never pass an explicit endpoint alongside it.

## Out of scope

- **Production.** `docker-compose.prod.yml` is untouched. No Collector, no LGTM stack, no new exposed port in production.
- **Frontend.** No file under `frontend/` changes, and no API response shape changes. Grafana is a separate audience on its own port; embedding dashboards in the React app is explicitly not done.
- **Logs pipeline beyond local.** Logs are correlated and exported to the local stack only, to stay inside the Grafana Cloud free tier.
- **Telemetry ingestion and inference.** `telemetry_readings`, the ingest endpoint and the inference service belong to the next change. The metric instruments that describe them are defined here but read from an empty snapshot until that change lands.
- **n8n.** Workflow orchestration and the Prometheus scrape of n8n belong to the third change; the Collector configuration leaves room for it but does not define it.
- **eBPF / zero-code instrumentation.** Comparing SDK instrumentation against OBI is interesting for the write-up but is not built here.
