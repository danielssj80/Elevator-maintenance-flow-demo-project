"""The scorer behind a Lambda handler must answer exactly as the HTTP service.

Production reaches the model only through this handler, so the golden vectors
are asserted here too: a handler that reshaped the rows, or swapped scores for
probabilities of the other class, would still return floats between 0 and 1.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from inference import lambda_handler

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden_vectors.json").read_text())
TOLERANCE = 1e-6


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch):
    """No scorer or provider leaks between tests; tracing env off by default."""
    monkeypatch.setattr(lambda_handler, "_scorer", None)
    monkeypatch.setattr(lambda_handler, "_provider", None)
    monkeypatch.delenv("OTEL_ENABLED", raising=False)


@pytest.fixture
def spans(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(lambda_handler, "_provider", provider)
    return exporter


def _score_event(**overrides) -> dict:
    event = {
        "operation": "score",
        "feature_names": GOLDEN["feature_names"],
        "rows": GOLDEN["rows"],
    }
    event.update(overrides)
    return event


def test_model_returns_the_boosters_columns_and_version():
    result = lambda_handler.handler({"operation": "model"})

    assert result["feature_names"] == GOLDEN["feature_names"]
    assert len(result["model_version"]) == 12


def test_score_reproduces_the_golden_vectors():
    result = lambda_handler.handler(_score_event())

    assert "error" not in result
    expected = GOLDEN["expected_scores"]
    assert len(result["scores"]) == len(expected)
    for got, want in zip(result["scores"], expected, strict=True):
        assert abs(got - want) < TOLERANCE
    assert len(result["contributions"]) == len(GOLDEN["rows"])
    assert all(len(c) == len(GOLDEN["feature_names"]) for c in result["contributions"])


def test_a_wrong_column_order_is_returned_not_raised():
    reordered = list(reversed(GOLDEN["feature_names"]))

    result = lambda_handler.handler(_score_event(feature_names=reordered))

    assert result["error"]["type"] == "client"
    assert "expected columns" in result["error"]["detail"]


def test_an_empty_matrix_is_a_client_error():
    result = lambda_handler.handler(_score_event(rows=[]))

    assert result["error"]["type"] == "client"


@pytest.mark.parametrize("operation", [None, "", "predict", "SCORE"])
def test_an_unknown_operation_names_the_accepted_ones(operation):
    result = lambda_handler.handler({"operation": operation})

    assert result["error"]["type"] == "client"
    assert "model" in result["error"]["detail"] and "score" in result["error"]["detail"]


def test_the_scorer_loads_once_per_sandbox(monkeypatch):
    loads = 0
    real = lambda_handler.Scorer

    def counting(*args, **kwargs):
        nonlocal loads
        loads += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(lambda_handler, "Scorer", counting)

    lambda_handler.handler({"operation": "model"})
    lambda_handler.handler(_score_event())
    lambda_handler.handler(_score_event())

    assert loads == 1


def test_the_span_continues_the_callers_trace(spans):
    caller = TracerProvider().get_tracer("caller")
    with caller.start_as_current_span("backend.run") as parent:
        carrier: dict[str, str] = {}
        from opentelemetry import propagate

        propagate.inject(carrier)
        parent_ctx = parent.get_span_context()

    # Called outside the caller's context: only the payload links them.
    lambda_handler.handler(_score_event(trace_context=carrier))

    [span] = [s for s in spans.get_finished_spans() if s.name == "inference.score"]
    assert span.context.trace_id == parent_ctx.trace_id
    assert span.parent.span_id == parent_ctx.span_id
    # Shape only: no telemetry values on the span.
    assert span.attributes["inference.row_count"] == len(GOLDEN["rows"])
    assert not any(isinstance(v, float) for v in span.attributes.values())


def test_spans_are_flushed_before_returning(monkeypatch):
    flushed = []

    class RecordingProvider(TracerProvider):
        def force_flush(self, timeout_millis: int = 30000) -> bool:
            flushed.append(timeout_millis)
            return True

    monkeypatch.setattr(lambda_handler, "_provider", RecordingProvider())

    lambda_handler.handler(_score_event())

    assert flushed, "the handler returned without flushing its spans"


def test_a_failing_exporter_never_fails_the_score(monkeypatch):
    class Broken(SpanExporter):
        def export(self, spans):
            raise ConnectionError("grafana cloud unreachable")

        def shutdown(self):
            pass

    class FlushRaises(TracerProvider):
        def force_flush(self, timeout_millis: int = 30000) -> bool:
            raise ConnectionError("grafana cloud unreachable")

    provider = FlushRaises()
    provider.add_span_processor(SimpleSpanProcessor(Broken()))
    monkeypatch.setattr(lambda_handler, "_provider", provider)

    result = lambda_handler.handler(_score_event())

    assert "error" not in result
    assert len(result["scores"]) == len(GOLDEN["rows"])


def test_unreadable_otlp_settings_disable_tracing_not_scoring(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_ENDPOINT_PARAMETER", "/elevator/otel/grafana-otlp-endpoint")
    monkeypatch.setenv("OTEL_HEADERS_PARAMETER", "/elevator/otel/grafana-otlp-auth")

    def denied(name):
        raise PermissionError(f"AccessDenied on {name}")

    monkeypatch.setattr(lambda_handler, "_ssm_value", denied)

    result = lambda_handler.handler(_score_event())

    assert "error" not in result
    assert lambda_handler._provider is None


def test_otlp_headers_are_parsed_like_the_sdk_variable():
    parsed = lambda_handler._parse_headers("Authorization=Basic abc=,X-Scope=1")

    assert parsed == {"Authorization": "Basic abc=", "X-Scope": "1"}


def test_no_global_provider_is_installed():
    """A global provider set from a Lambda sandbox would outlive the test, and
    in production would make every library's spans compete for the flush."""
    before = trace.get_tracer_provider()

    lambda_handler.handler(_score_event())

    assert trace.get_tracer_provider() is before
