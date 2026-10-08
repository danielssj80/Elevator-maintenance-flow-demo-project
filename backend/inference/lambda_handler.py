"""AWS Lambda entry point for the scorer.

Production runs no scoring container: the backend invokes this function with
the instance role (``LambdaInferenceClient``). It is the same ``Scorer`` the
HTTP service in ``main.py`` uses, behind a different door:

* ``{"operation": "model"}`` → ``{feature_names, model_version}``
* ``{"operation": "score", "feature_names": [...], "rows": [[...]]}``
  → ``{scores, contributions, model_version}``

A request the scorer cannot consume is **returned** as
``{"error": {"type": "client", "detail": ...}}``, never raised. A raised
exception becomes a Lambda function error, which the backend reports as the
scorer crashing; a wrong column order is the caller's mistake, the HTTP
service's 422, and must stay distinguishable from that.

Tracing: a direct invoke carries no HTTP headers, so the caller's W3C context
arrives in ``event["trace_context"]``. Spans are flushed before returning —
Lambda freezes the sandbox the moment the handler returns, and a batch
processor's pending spans would otherwise leave with it. Export is
best-effort: nothing about telemetry can fail a score.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import TracerProvider

from inference.scorer import FeatureOrderMismatch, Scorer

logger = logging.getLogger(__name__)

OPERATIONS = ("model", "score")

# Loaded once per sandbox: joblib.load plus the booster is the whole cost of a
# cold start, and a warm invocation must not pay it again.
_scorer: Scorer | None = None
_provider: TracerProvider | None = None


def _get_scorer() -> Scorer:
    global _scorer
    if _scorer is None:
        _scorer = Scorer()
    return _scorer


def _client_error(detail: str) -> dict[str, Any]:
    return {"error": {"type": "client", "detail": detail}}


def _ssm_value(name: str) -> str:
    import boto3

    response = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"]


def _parse_headers(raw: str) -> dict[str, str]:
    """``k=v,k2=v2``, the OTEL_EXPORTER_OTLP_HEADERS format."""
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        key, sep, value = pair.partition("=")
        if sep:
            headers[key.strip()] = value.strip()
    return headers


def configure_tracing() -> None:
    """Export to Grafana Cloud when enabled; a no-op otherwise.

    The endpoint and the auth header are SSM parameter *names* in the
    environment, read here with the function role. Their values never sit in
    the function configuration, where `GetFunctionConfiguration` would show
    them.
    """
    global _provider
    if _provider is not None or os.getenv("OTEL_ENABLED", "false").lower() != "true":
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    try:
        base = _ssm_value(os.environ["OTEL_ENDPOINT_PARAMETER"]).rstrip("/")
        headers = _parse_headers(_ssm_value(os.environ["OTEL_HEADERS_PARAMETER"]))
    except Exception:
        # No telemetry is better than no score.
        logger.exception("Tracing disabled: could not read the OTLP settings from SSM")
        return

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", "elevator-scorer"),
                "deployment.environment.name": os.getenv(
                    "DEPLOYMENT_ENVIRONMENT", "production"
                ),
            }
        )
    )
    # BASE url: the SDK does not append the signal path when given endpoint=.
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces", headers=headers))
    )
    _provider = provider


def _flush() -> None:
    if _provider is None:
        return
    try:
        _provider.force_flush(timeout_millis=5000)
    except Exception:
        logger.exception("Span export failed; the score is unaffected")


def _tracer() -> trace.Tracer:
    return (_provider or trace.get_tracer_provider()).get_tracer(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    operation = event.get("operation")
    if operation not in OPERATIONS:
        return _client_error(
            f"unknown operation {operation!r}; expected one of {', '.join(OPERATIONS)}"
        )

    configure_tracing()
    parent = propagate.extract(event.get("trace_context") or {})
    scorer = _get_scorer()
    try:
        if operation == "model":
            return {
                "feature_names": scorer.feature_names,
                "model_version": scorer.model_version,
            }
        return _score(scorer, event, parent)
    finally:
        _flush()


def _score(scorer: Scorer, event: dict[str, Any], parent: Any) -> dict[str, Any]:
    feature_names = event.get("feature_names") or []
    rows = event.get("rows") or []
    with _tracer().start_as_current_span("inference.score", context=parent) as span:
        # Shape and identity only, the same rule as the HTTP route: telemetry
        # values are fleet operating data and do not belong on a span.
        span.set_attribute("inference.row_count", len(rows))
        span.set_attribute("inference.feature_count", len(feature_names))
        span.set_attribute("inference.model_version", scorer.model_version)
        if not feature_names or not rows:
            span.set_attribute("inference.rejected", True)
            return _client_error("feature_names and rows must both be non-empty")
        try:
            scores, contributions = scorer.score(feature_names, rows)
        except FeatureOrderMismatch as exc:
            span.set_attribute("inference.rejected", True)
            return _client_error(str(exc))

    return {
        "scores": scores,
        "contributions": contributions,
        "model_version": scorer.model_version,
    }
