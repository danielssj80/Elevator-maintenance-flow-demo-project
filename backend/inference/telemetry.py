"""Tracing for the scoring service.

Deliberately much smaller than the backend's ``app/core/telemetry.py``: this
service has no database, no metrics of its own and no log pipeline. Its only
job in the trace is to be the third span — the one that shows scoring is a
separate hop and how long it takes.

It cannot import the backend's module: different image, and ``app/`` is not
there. The two things that had to be copied rather than shared are the ones the
previous change learned the hard way, so both carry their reasoning:

* ``OTEL_EXPORTER_OTLP_ENDPOINT`` is a BASE url. The SDK appends ``/v1/traces``
  itself; passing a full path produces a 404 that is only logged at DEBUG.
* Instrumentation must wrap the ASGI app before anything else takes a reference
  to it.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def _enabled() -> bool:
    return os.getenv("OTEL_ENABLED", "false").lower() == "true"


def configure_telemetry(app: FastAPI) -> None:
    """A no-op when disabled, so tests and CI need no Collector."""
    global _provider
    if not _enabled() or _provider is not None:
        return

    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318").rstrip("/")

    _provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", "elevator-inference"),
                "service.version": os.getenv("OTEL_SERVICE_VERSION", "0.1.0"),
                # Same default as the backend. This one only labels spans — it
                # gates nothing — but two services disagreeing about which
                # environment they are in makes a dashboard lie.
                "deployment.environment.name": os.getenv(
                    "DEPLOYMENT_ENVIRONMENT", "production"
                ),
            }
        )
    )
    _provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
    )
    trace.set_tracer_provider(_provider)

    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def shutdown_telemetry() -> None:
    if _provider is not None:
        _provider.shutdown()
