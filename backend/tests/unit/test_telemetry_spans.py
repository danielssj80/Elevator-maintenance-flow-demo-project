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
    saved = (
        telemetry_module._tracer_provider,
        telemetry_module._meter_provider,
        telemetry_module._logger_provider,
        telemetry_module._log_handler,
    )
    # ALL of them, not just tracer and meter: shutdown_telemetry() detaches the
    # log handler from the root logger, and leaving that out silently removed
    # the session's handler for every later test.
    telemetry_module._tracer_provider = None
    telemetry_module._meter_provider = None
    telemetry_module._logger_provider = None
    telemetry_module._log_handler = None
    try:
        yield
    finally:
        (
            telemetry_module._tracer_provider,
            telemetry_module._meter_provider,
            telemetry_module._logger_provider,
            telemetry_module._log_handler,
        ) = saved


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

        Must assert on ``db.statement``, not ``db.system``. Without ``engine=``
        the instrumentation still patches ``Engine.connect`` class-wide, so a
        ``connect`` span carrying ``db.system`` still arrives and an assertion
        on that attribute passes while per-statement visibility is gone. The
        first version of this test did exactly that and survived the mutation.
        """
        await traced_client.get("/api/elevators")

        statement_spans = [
            s
            for s in span_exporter.get_finished_spans()
            if s.kind is SpanKind.CLIENT and s.attributes.get("db.statement")
        ]
        assert statement_spans, (
            "no per-statement database spans — is the engine bound with "
            "engine=engine.sync_engine? connect spans alone are not enough"
        )

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


class TestBriefingSpans:
    """The briefing path is where a silent failure is most costly: Bedrock can
    be down and the endpoint still returns HTTP 200 with a plausible briefing.
    """

    @staticmethod
    def _service(*, raises: Exception | None = None, text: str = "Generated briefing."):
        from unittest.mock import AsyncMock, MagicMock

        from tests.unit.test_briefing_service import _make_orm_elevator

        from app.services.briefing_service import BriefingService

        repo = AsyncMock()
        repo.get_by_id.return_value = _make_orm_elevator()

        client = MagicMock()
        if raises is not None:
            client.generate.side_effect = raises
        else:
            client.generate.return_value = text
        return BriefingService(elevator_repository=repo, bedrock_client=client)

    @staticmethod
    def _briefing_span(span_exporter):
        spans = [
            s
            for s in span_exporter.get_finished_spans()
            if s.name == "briefing.generate"
        ]
        assert spans, "no briefing.generate span was recorded"
        return spans[-1]

    async def test_successful_briefing_records_bedrock_as_the_source(
        self, span_exporter
    ) -> None:
        await self._service().get_briefing("ELV-001")

        span = self._briefing_span(span_exporter)
        assert span.attributes["briefing.source"] == "bedrock"
        assert span.attributes["briefing.cache_hit"] is False
        assert span.attributes["elevator.id"] == "ELV-001"
        assert span.attributes["elevator.risk_level"] == "high"

    async def test_provider_is_recorded_under_both_attribute_generations(
        self, span_exporter
    ) -> None:
        """`gen_ai.system` was renamed to `gen_ai.provider.name`; emit both so a
        dashboard written against either keeps working."""
        await self._service().get_briefing("ELV-001")

        span = self._briefing_span(span_exporter)
        assert span.attributes["gen_ai.provider.name"] == "aws.bedrock"
        assert span.attributes["gen_ai.system"] == "aws.bedrock"
        assert span.attributes["gen_ai.request.model"] == settings.bedrock_model_id

    async def test_bedrock_failure_is_visible_as_a_fallback_not_a_success(
        self, span_exporter
    ) -> None:
        result = await self._service(
            raises=RuntimeError("bedrock unavailable")
        ).get_briefing("ELV-001")

        assert result.source == "fallback"
        span = self._briefing_span(span_exporter)
        assert span.attributes["briefing.source"] == "fallback"
        assert any(e.name == "exception" for e in span.events), (
            "the swallowed exception must be recorded on the span"
        )

    async def test_cache_hit_is_distinguishable_and_skips_the_model(
        self, span_exporter
    ) -> None:
        service = self._service()
        await service.get_briefing("ELV-001")
        span_exporter.clear()
        await service.get_briefing("ELV-001")

        span = self._briefing_span(span_exporter)
        assert span.attributes["briefing.cache_hit"] is True
        assert "gen_ai.request.model" not in span.attributes, (
            "a cache hit never reaches the model, so it must not claim to"
        )

    async def test_no_span_attribute_carries_prompt_or_completion_text(
        self, span_exporter
    ) -> None:
        """Briefing prompts embed technician names and free-text visit notes."""
        secret = "Vibration noted"  # appears in the elevator's last_visit_notes
        await self._service(text="Generated briefing.").get_briefing("ELV-001")

        for span in span_exporter.get_finished_spans():
            for key, value in span.attributes.items():
                assert "gen_ai.input.messages" not in key
                assert "gen_ai.output.messages" not in key
                if isinstance(value, str):
                    assert secret not in value, f"visit notes leaked into {key}"
                    assert "Generated briefing." not in value, (
                        f"completion text leaked into {key}"
                    )

    async def test_tracing_context_survives_the_worker_thread_offload(
        self, span_exporter
    ) -> None:
        """The boto3 call runs via anyio.to_thread so it cannot stall the event
        loop. anyio copies contextvars into that thread, which is what keeps the
        model span nested under briefing.generate instead of becoming a
        detached root. Assert that directly, since the real botocore span is
        not available with a mocked client.
        """
        from unittest.mock import AsyncMock, MagicMock

        from tests.unit.test_briefing_service import _make_orm_elevator

        from app.services.briefing_service import BriefingService

        def _generate_in_thread(**kwargs):
            with telemetry_module.get_tracer("test").start_as_current_span(
                "fake.model.call"
            ):
                pass
            return "Generated briefing."

        repo = AsyncMock()
        repo.get_by_id.return_value = _make_orm_elevator()
        client = MagicMock()
        client.generate.side_effect = _generate_in_thread

        await BriefingService(
            elevator_repository=repo, bedrock_client=client
        ).get_briefing("ELV-001")

        spans = {s.name: s for s in span_exporter.get_finished_spans()}
        assert "fake.model.call" in spans, "no span was created inside the thread"
        model_span = spans["fake.model.call"]
        briefing = spans["briefing.generate"]

        assert model_span.parent is not None, "span in the worker thread is detached"
        assert model_span.parent.span_id == briefing.context.span_id
        assert model_span.context.trace_id == briefing.context.trace_id

    async def test_concurrent_briefings_are_not_serialised(self) -> None:
        """The whole point of the thread offload.

        boto3 is synchronous with a multi-second timeout. Awaited directly from
        an async handler it stalls the event loop, so two concurrent briefings
        take twice as long as one. Run on a worker thread they overlap.
        """
        import asyncio
        import time
        from unittest.mock import AsyncMock, MagicMock

        from tests.unit.test_briefing_service import _make_orm_elevator

        from app.services.briefing_service import BriefingService

        call_delay = 0.5

        def _slow_generate(**kwargs):
            time.sleep(call_delay)
            return "Generated briefing."

        def _service_for(elevator_id: str) -> BriefingService:
            repo = AsyncMock()
            repo.get_by_id.return_value = _make_orm_elevator(id=elevator_id)
            client = MagicMock()
            client.generate.side_effect = _slow_generate
            return BriefingService(elevator_repository=repo, bedrock_client=client)

        started = time.perf_counter()
        await asyncio.gather(
            _service_for("ELV-101").get_briefing("ELV-101"),
            _service_for("ELV-102").get_briefing("ELV-102"),
        )
        elapsed = time.perf_counter() - started

        # Serialised would be ~2x call_delay (1.0s); concurrent ~1x (0.5s).
        # 1.5x leaves 250ms of headroom on a loaded machine and still fails
        # decisively if the loop is blocked.
        assert elapsed < call_delay * 1.5, (
            f"two briefings took {elapsed:.2f}s for a {call_delay}s call each — "
            "the event loop is being blocked"
        )


class TestLogExport:
    """Guards a regression that shipped silently once already.

    `LoggingInstrumentor` only injects trace ids into the log *format*. Without
    an explicit LoggerProvider and handler the Collector's logs pipeline
    receives nothing at all, and nothing anywhere reports an error — the
    dashboards simply have no logs.
    """

    def test_a_logger_provider_is_registered(self) -> None:
        from opentelemetry._logs import get_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider

        assert isinstance(get_logger_provider(), LoggerProvider), (
            "no SDK LoggerProvider registered — log records go nowhere"
        )

    def test_a_log_handler_is_attached_to_the_root_logger(self) -> None:
        import logging

        from opentelemetry.instrumentation.logging.handler import LoggingHandler

        handlers = logging.getLogger().handlers
        otel = [h for h in handlers if isinstance(h, LoggingHandler)]
        assert otel, "no OTel handler on the root logger — nothing is exported"
        assert len(otel) == 1, (
            f"{len(otel)} OTel handlers on root — every record would be "
            "exported once per handler, doubling volume and any log-derived rate"
        )

    def test_console_logging_survives_instrumentation(self) -> None:
        """Attaching the OTLP handler before basicConfig makes basicConfig a
        no-op, leaving the root logger with no StreamHandler. Application logs
        then exist ONLY inside the OTLP pipeline — invisible exactly when that
        pipeline is what broke.
        """
        import logging

        handlers = logging.getLogger().handlers
        assert any(type(h) is logging.StreamHandler for h in handlers), (
            "no StreamHandler on root — console logging was destroyed, so an "
            "export failure would be silent"
        )
