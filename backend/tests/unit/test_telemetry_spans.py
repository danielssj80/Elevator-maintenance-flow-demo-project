"""Tests for OpenTelemetry configuration and span emission.

Configuration note: ``Settings`` evaluates ``os.getenv`` in class-level
attributes at import time, and ``settings`` is a module singleton. Therefore
``monkeypatch.setenv`` followed by a re-import does NOT change these values.
Tests must patch the singleton's attributes directly with
``monkeypatch.setattr(settings, ...)``, or use an explicit override argument
where the production code offers one.
"""

from contextlib import contextmanager

from opentelemetry.trace import SpanKind, StatusCode

from app.core import telemetry as telemetry_module
from app.core.config import settings
from app.main import app


class TestTelemetrySettings:
    def test_otel_is_disabled_by_default(self) -> None:
        """Telemetry must be opt-in so CI and the test suite need no Collector."""
        assert settings.otel_enabled is False

    def test_otlp_endpoint_defaults_to_the_collector_base_url(self) -> None:
        """The endpoint is a BASE url; the signal path is appended separately."""
        assert settings.otel_exporter_otlp_endpoint == "http://otel-collector:4318"
        assert not settings.otel_exporter_otlp_endpoint.endswith("/v1/traces")

    def test_service_identity_defaults(self) -> None:
        assert settings.otel_service_name == "elevator-backend"
        assert settings.deployment_environment == "local"

    def test_fleet_metrics_refresh_interval_is_a_positive_int(self) -> None:
        assert isinstance(settings.fleet_metrics_refresh_seconds, int)
        assert settings.fleet_metrics_refresh_seconds > 0

    def test_signal_endpoint_appends_the_path_to_the_base(self) -> None:
        assert (
            telemetry_module._signal_endpoint("/v1/traces")
            == "http://otel-collector:4318/v1/traces"
        )


@contextmanager
def _unconfigured_telemetry():
    """Temporarily present module state as "never configured", then restore.

    The session fixture configures telemetry once for the whole run, and
    tearing that down here would shut down the shared in-memory exporter —
    after which it silently records nothing and every later span assertion
    fails for the wrong reason.
    """
    saved_tracer = telemetry_module._tracer_provider
    saved_meter = telemetry_module._meter_provider
    telemetry_module._tracer_provider = None
    telemetry_module._meter_provider = None
    try:
        yield
    finally:
        telemetry_module._tracer_provider = saved_tracer
        telemetry_module._meter_provider = saved_meter


class TestTelemetryIsOptIn:
    def test_configure_registers_nothing_when_explicitly_disabled(self) -> None:
        with _unconfigured_telemetry():
            telemetry_module.configure_telemetry(app, enabled=False)
            assert telemetry_module._current_providers() == (None, None)

    def test_configure_registers_nothing_when_settings_default_applies(self) -> None:
        """With no `enabled` argument it must follow the (disabled) setting."""
        assert settings.otel_enabled is False
        with _unconfigured_telemetry():
            telemetry_module.configure_telemetry(app)
            assert telemetry_module._current_providers() == (None, None)

    def test_shutdown_is_safe_when_never_configured(self) -> None:
        """Shutdown must not raise if telemetry was never set up."""
        with _unconfigured_telemetry():
            assert telemetry_module.shutdown_telemetry() is None


class TestHttpSpans:
    async def test_listing_elevators_produces_a_server_span(
        self, traced_client, span_exporter
    ) -> None:
        response = await traced_client.get("/api/elevators")
        assert response.status_code == 200

        spans = span_exporter.get_finished_spans()
        server_spans = [s for s in spans if s.kind is SpanKind.SERVER]
        assert server_spans, "no server span was recorded for GET /api/elevators"

    async def test_server_span_uses_the_route_template_not_the_raw_path(
        self, traced_client, span_exporter
    ) -> None:
        """Guards metric cardinality: one series per route, not per elevator."""
        await traced_client.get("/api/elevators/ELV-001")
        await traced_client.get("/api/elevators/ELV-002")

        routes = {
            s.attributes.get("http.route")
            for s in span_exporter.get_finished_spans()
            if s.kind is SpanKind.SERVER
        }
        assert routes == {"/api/elevators/{elevator_id}"}

    async def test_database_queries_produce_child_spans(
        self, traced_client, span_exporter
    ) -> None:
        """Guards the silent SQLAlchemy failure.

        ``SQLAlchemyInstrumentor().instrument()`` without ``engine=`` patches
        ``create_engine`` and therefore misses an engine that was already
        constructed at import time, emitting zero database spans and raising
        nothing. Without this test that regression is invisible.
        """
        await traced_client.get("/api/elevators")

        client_spans = [
            s
            for s in span_exporter.get_finished_spans()
            if s.kind is SpanKind.CLIENT and s.attributes.get("db.system")
        ]
        assert client_spans, "no database spans recorded — is the engine bound?"

    async def test_unknown_elevator_is_a_handled_404_not_an_error(
        self, traced_client, span_exporter
    ) -> None:
        response = await traced_client.get("/api/elevators/ELV-999")
        assert response.status_code == 404

        server_spans = [
            s for s in span_exporter.get_finished_spans() if s.kind is SpanKind.SERVER
        ]
        assert server_spans
        span = server_spans[-1]
        assert span.attributes.get("http.response.status_code") == 404
        assert "http.status_code" not in span.attributes, (
            "legacy HTTP semconv leaked; OTEL_SEMCONV_STABILITY_OPT_IN is wrong"
        )
        assert span.status.status_code is not StatusCode.ERROR


class TestTraceContextPropagation:
    async def test_incoming_traceparent_is_continued(
        self, traced_client, span_exporter
    ) -> None:
        """An orchestrator's trace must continue into this service."""
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        parent_span_id = "00f067aa0ba902b7"
        traceparent = f"00-{trace_id}-{parent_span_id}-01"

        await traced_client.get(
            "/api/elevators", headers={"traceparent": traceparent}
        )

        server_spans = [
            s for s in span_exporter.get_finished_spans() if s.kind is SpanKind.SERVER
        ]
        assert server_spans
        span = server_spans[-1]
        assert format(span.context.trace_id, "032x") == trace_id
        assert span.parent is not None
        assert format(span.parent.span_id, "016x") == parent_span_id

    async def test_malformed_traceparent_does_not_break_the_request(
        self, traced_client, span_exporter
    ) -> None:
        response = await traced_client.get(
            "/api/elevators", headers={"traceparent": "not-a-valid-traceparent"}
        )
        assert response.status_code == 200

        server_spans = [
            s for s in span_exporter.get_finished_spans() if s.kind is SpanKind.SERVER
        ]
        assert server_spans, "request should still be traced as a new root"
        assert server_spans[-1].parent is None
