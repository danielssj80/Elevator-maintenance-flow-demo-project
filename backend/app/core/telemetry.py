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
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider, LogRecordProcessor
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
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
#
# Anchored at the END only. The instrumentation matches this regex against the
# FULL url ("http://host:8000/health"), not the path, so a leading "^" can
# never match and silently disables the exclusion entirely — which is exactly
# what a previous "tightening" of this value did. A bare "health" would instead
# over-match a future /api/fleet-health. Verified against
# opentelemetry.util.http.parse_excluded_urls:
#   'health'    -> /health True,  /api/fleet-health True   (over-matches)
#   '^/health$' -> /health False, /api/fleet-health False  (matches nothing)
#   '/health$'  -> /health True,  /api/fleet-health False  (correct)
_EXCLUDED_URLS = r"/health$"

# "http" = emit stable HTTP semantic conventions only. "http/dup" would emit
# both old and new names, doubling attribute volume for a migration we do not
# need to straddle: nothing consumes the legacy names yet.
_SEMCONV_OPT_IN = "http"

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_logger_provider: LoggerProvider | None = None
_log_handler: LoggingHandler | None = None
_instrumented_app: FastAPI | None = None

# The global tracer provider can only be set once per process, so a second
# configure after a shutdown would be silently ineffective. Tracked separately
# from `_tracer_provider`, which shutdown resets to None.
_has_been_configured = False
_reconfiguration_allowed = False


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

    The unbound ``SQLAlchemyInstrumentor().instrument()`` also patches
    ``Engine.connect`` class-wide, so an engine built before instrumentation —
    as ours is, at ``app.database`` import time — still produces ``connect``
    spans. What it does NOT produce is per-statement spans: those come from
    event listeners registered on a specific engine, which only the ``engine=``
    argument installs.

    Measured on opentelemetry-instrumentation-sqlalchemy 0.65b0, one query:

        with    engine=  ->  ['connect', 'SELECT'], 1 span with db.statement
        without engine=  ->  ['connect'],           0 spans with db.statement

    So the failure mode is not "no database spans" but "no visibility into
    which query ran or how long it took" — quieter, and easy to mistake for
    working instrumentation. The async engine's sync facade is the object the
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
    log_record_processor: LogRecordProcessor | None = None,
    db_engine: AsyncEngine | None = None,
) -> None:
    """Configure tracing and metrics. A no-op when telemetry is disabled.

    The keyword arguments exist for tests: ``enabled`` overrides the setting so
    the test suite never has to mutate the ``settings`` singleton, an in-memory
    exporter, reader and log processor replace the OTLP ones, and an explicit
    engine replaces the application's.
    """
    global _tracer_provider, _meter_provider, _logger_provider, _log_handler
    global _instrumented_app, _has_been_configured

    if enabled is None:
        enabled = settings.otel_enabled
    if not enabled:
        return

    if _tracer_provider is not None:
        logger.debug("Telemetry already configured; skipping")
        return

    if _has_been_configured and not _reconfiguration_allowed:
        # `trace.set_tracer_provider` only takes effect once per process. After
        # a shutdown, a second configure builds a new provider that the global
        # API will refuse to adopt, so every `get_tracer()` keeps writing into
        # the provider that was just shut down and domain spans vanish with no
        # error anywhere. Reachable via `uvicorn --reload` or any host that
        # runs the lifespan twice.
        raise RuntimeError(
            "OpenTelemetry cannot be reconfigured after shutdown in the same "
            "process: the global tracer provider can only be set once, so the "
            "new provider would be ignored and all spans silently discarded. "
            "Start a fresh process instead."
        )

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

    # Console logging FIRST. `LoggingInstrumentor(set_logging_format=True)`
    # calls `logging.basicConfig`, which is a no-op once the root logger has any
    # handler. Attaching the OTLP handler before that point leaves the root
    # logger with no StreamHandler at all, so application logs stop reaching
    # stdout and exist only inside the OTLP pipeline — invisible precisely when
    # that pipeline is what broke.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )

    # LoggingInstrumentor alone only injects trace ids into the log FORMAT; it
    # does not ship anything. Without an explicit LoggerProvider the Collector's
    # logs pipeline receives nothing at all, silently.
    _logger_provider = LoggerProvider(resource=resource)
    # A seam for tests, matching the span and metric ones. Without it the test
    # suite opens a real OTLP connection and ships every log record it produces
    # under the production service name, indistinguishable from real traffic —
    # and blocks for ~30s per run when no Collector is listening.
    _logger_provider.add_log_record_processor(
        log_record_processor
        or BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=_signal_endpoint("/v1/logs"))
        )
    )
    set_logger_provider(_logger_provider)

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
    # httpx became a runtime dependency with the inference client
    # (telemetry-ingestion-inference), so this guard is now normally satisfied.
    # It stays because the instrumentation package can still be installed
    # without the library — an install from requirements.txt alone in some
    # future split — and instrumenting unconditionally then logs a confusing
    # "DependencyConflict: requested httpx >= 0.18.0 but found None" on every
    # start rather than failing usefully.
    if find_spec("httpx") is not None:
        HTTPXClientInstrumentor().instrument(tracer_provider=_tracer_provider)
    BotocoreInstrumentor().instrument(tracer_provider=_tracer_provider)
    # This attaches the OTLP log handler to the root logger itself. Adding
    # another one here would export every record twice, doubling log volume and
    # making any log-derived rate read 2x.
    #
    # `set_logging_format=True` is effectively inert: it calls basicConfig
    # without force=, and root already has the handler installed above. Console
    # lines therefore carry no trace id; the exported records do, via
    # otelTraceID/otelSpanID. Kept because the flag also governs handler
    # installation, not only formatting.
    LoggingInstrumentor().instrument(set_logging_format=True)
    _log_handler = next(
        (h for h in logging.getLogger().handlers if isinstance(h, LoggingHandler)),
        None,
    )

    _has_been_configured = True

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
    global _tracer_provider, _meter_provider, _logger_provider, _log_handler
    global _instrumented_app

    if _log_handler is not None:
        logging.getLogger().removeHandler(_log_handler)
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
    if _meter_provider is not None:
        _meter_provider.shutdown()
    if _logger_provider is not None:
        _logger_provider.shutdown()

    _tracer_provider = None
    _meter_provider = None
    _logger_provider = None
    _log_handler = None
    _instrumented_app = None


def _allow_reconfiguration_for_tests(allowed: bool) -> None:
    """Let a test reconfigure after shutdown, which production forbids."""
    global _reconfiguration_allowed
    _reconfiguration_allowed = allowed


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


def _current_providers() -> tuple[TracerProvider | None, MeterProvider | None]:
    """Expose provider state for assertions in tests."""
    return _tracer_provider, _meter_provider
