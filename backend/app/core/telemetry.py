"""OpenTelemetry configuration.

Set up programmatically rather than through the ``opentelemetry-instrument``
CLI wrapper because:

- the MeterProvider needs observable-gauge callbacks registered into it, and
  the wrapper offers no hook for that;
- SQLAlchemy must be bound to the already-built async engine, which has no
  environment-variable expression (see ``_instrument_sqlalchemy``);
- the ``migrate`` service reuses this image with an overridden command and
  must not export spans;
- only programmatic setup can be driven by an in-memory exporter in tests.

Everything here is a no-op unless ``OTEL_ENABLED`` is true.
"""

from __future__ import annotations

import logging
import os
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from app.core.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Health checks fire every 10s from the container healthcheck. Excluding them
# keeps the trace store readable and the free-tier budget intact.
_EXCLUDED_URLS = "health"

# "http" = emit stable HTTP semantic conventions only. "http/dup" would emit
# both old and new names, doubling attribute volume for a migration we do not
# need to straddle: nothing consumes the legacy names yet.
_SEMCONV_OPT_IN = "http"

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_instrumented_app: FastAPI | None = None


def _build_resource() -> Resource:
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.otel_service_version,
            "deployment.environment.name": settings.deployment_environment,
        }
    )


def _signal_endpoint(signal_path: str) -> str:
    """Append a signal path to the configured BASE endpoint.

    ``settings.otel_exporter_otlp_endpoint`` holds a base URL. The SDK only
    appends ``/v1/traces`` when it reads the endpoint from the environment; an
    endpoint passed to an exporter constructor is treated as the FULL url and
    used verbatim. Rather than depend on an environment variable also being
    set, the signal path is appended explicitly here, which is deterministic.
    Getting this wrong POSTs to the base url and the resulting 404 is only
    logged at DEBUG, so it looks like nothing is being exported at all.
    """
    return f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}{signal_path}"


def _instrument_sqlalchemy(db_engine: AsyncEngine) -> None:
    """Bind SQLAlchemy instrumentation to the already-constructed engine.

    ``SQLAlchemyInstrumentor().instrument()`` with no arguments patches
    ``create_engine``. Our engine is built by ``create_async_engine`` at
    ``app.database`` import time, which happens before this function runs, so
    the unbound call would miss it entirely and emit ZERO database spans with
    no error raised. The async engine's sync facade is the object the
    instrumentation understands.
    """
    SQLAlchemyInstrumentor().instrument(
        engine=db_engine.sync_engine,
        tracer_provider=_tracer_provider,
    )


def configure_telemetry(
    app: FastAPI,
    *,
    enabled: bool | None = None,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
    db_engine: AsyncEngine | None = None,
) -> None:
    """Configure tracing and metrics. A no-op when telemetry is disabled.

    The keyword arguments exist for tests: ``enabled`` overrides the setting so
    the test suite never has to mutate the ``settings`` singleton, an in-memory
    exporter and reader replace the OTLP ones, and an explicit engine replaces
    the application's.
    """
    global _tracer_provider, _meter_provider, _instrumented_app

    if enabled is None:
        enabled = settings.otel_enabled
    if not enabled:
        return

    if _tracer_provider is not None:
        logger.debug("Telemetry already configured; skipping")
        return

    resource = _build_resource()

    _tracer_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        _tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_signal_endpoint("/v1/traces")))
        )
    trace.set_tracer_provider(_tracer_provider)

    reader = metric_reader or PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=_signal_endpoint("/v1/metrics"))
    )
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_meter_provider)

    # Opt into the STABLE HTTP semantic conventions before any instrumentor
    # initialises its stability singleton. Without this the instrumentation
    # emits the legacy names (`http.status_code`, `http.host`, `http.target`),
    # dashboards built on the stable names silently show nothing, and the
    # migration becomes a breaking change later. `setdefault` so an explicit
    # environment override still wins.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", _SEMCONV_OPT_IN)

    if db_engine is None:
        from app.database import engine as default_engine

        db_engine = default_engine

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=_tracer_provider,
        meter_provider=_meter_provider,
        excluded_urls=_EXCLUDED_URLS,
    )
    _instrumented_app = app

    _instrument_sqlalchemy(db_engine)
    # httpx is not a runtime dependency yet — it arrives with the inference
    # client in the next change. Instrumenting it unconditionally logs a
    # confusing "DependencyConflict: requested httpx >= 0.18.0 but found None"
    # on every start, so guard it and let it switch on by itself later.
    if find_spec("httpx") is not None:
        HTTPXClientInstrumentor().instrument(tracer_provider=_tracer_provider)
    BotocoreInstrumentor().instrument(tracer_provider=_tracer_provider)
    LoggingInstrumentor().instrument(set_logging_format=True)

    logger.info(
        "OpenTelemetry configured: service=%s environment=%s endpoint=%s",
        settings.otel_service_name,
        settings.deployment_environment,
        settings.otel_exporter_otlp_endpoint,
    )


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer. Safe to call whether or not telemetry is configured."""
    return trace.get_tracer(name)


def shutdown_telemetry() -> None:
    """Flush and shut down the providers. Safe to call when never configured."""
    global _tracer_provider, _meter_provider, _instrumented_app

    if _tracer_provider is not None:
        _tracer_provider.shutdown()
    if _meter_provider is not None:
        _meter_provider.shutdown()

    _tracer_provider = None
    _meter_provider = None
    _instrumented_app = None


def _uninstrument_for_tests(app: FastAPI | None = None) -> None:
    """Undo instrumentation so a test can reconfigure from a clean slate.

    Instrumentors are process-global singletons, so without this a second
    ``configure_telemetry`` call in the same test session would warn and leave
    spans attached to the previous provider.
    """
    global _instrumented_app

    target = app or _instrumented_app
    if target is not None:
        FastAPIInstrumentor.uninstrument_app(target)

    for instrumentor in (
        SQLAlchemyInstrumentor(),
        HTTPXClientInstrumentor(),
        BotocoreInstrumentor(),
        LoggingInstrumentor(),
    ):
        try:
            instrumentor.uninstrument()
        except Exception:  # pragma: no cover - defensive, varies by instrumentor
            logger.debug("Uninstrument failed for %s", instrumentor, exc_info=True)

    shutdown_telemetry()


def _current_providers() -> tuple[Any, Any]:
    """Expose provider state for assertions in tests."""
    return _tracer_provider, _meter_provider
