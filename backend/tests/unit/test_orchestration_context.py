"""Stamping the orchestrator's execution onto the server span.

Trace linkage between n8n and this service needs no code: n8n injects a W3C
`traceparent` into outbound HTTP and the FastAPI instrumentation continues it
(`TestTraceContextPropagation` in test_telemetry_spans.py covers that half).

This middleware is the other direction — carrying n8n's *own* identifiers into
the trace so a span can be taken back to the execution that produced it, and a
failed execution forward to its backend trace. It also stands in if header
injection is ever off: the attributes are still there even when the trace is not
linked, which is the difference between a degraded signal and none.

Configuration note, per test_telemetry_spans.py: `Settings` reads `os.getenv` at
import time and `settings` is a singleton, so patch its attributes directly.
"""

from opentelemetry.trace import SpanKind

EXECUTION_ID_HEADER = "X-N8N-Execution-Id"
WORKFLOW_ID_HEADER = "X-N8N-Workflow-Id"
EXECUTION_ID_ATTRIBUTE = "n8n.execution.id"
MAX_VALUE_LENGTH = 128
WORKFLOW_ID_ATTRIBUTE = "n8n.workflow.id"


def _server_span(span_exporter):
    spans = [s for s in span_exporter.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert spans, "the request should have produced a server span"
    return spans[-1]


class TestOrchestrationAttributes:
    async def test_execution_and_workflow_ids_reach_the_span(
        self, traced_client, span_exporter
    ) -> None:
        await traced_client.get(
            "/api/elevators",
            headers={EXECUTION_ID_HEADER: "4821", WORKFLOW_ID_HEADER: "wf-ingest-15m"},
        )

        span = _server_span(span_exporter)
        assert span.attributes.get(EXECUTION_ID_ATTRIBUTE) == "4821"
        assert span.attributes.get(WORKFLOW_ID_ATTRIBUTE) == "wf-ingest-15m"

    async def test_a_request_without_the_headers_carries_no_orchestration_attributes(
        self, traced_client, span_exporter
    ) -> None:
        """Absent, not empty.

        Recording "" for every human-made request would put an
        `n8n.execution.id` on traces no orchestrator was involved in, and make
        "filter to orchestrated requests" quietly meaningless.
        """
        response = await traced_client.get("/api/elevators")
        assert response.status_code == 200

        span = _server_span(span_exporter)
        assert EXECUTION_ID_ATTRIBUTE not in span.attributes
        assert WORKFLOW_ID_ATTRIBUTE not in span.attributes

    async def test_one_header_without_the_other_records_only_what_was_sent(
        self, traced_client, span_exporter
    ) -> None:
        await traced_client.get(
            "/api/elevators", headers={EXECUTION_ID_HEADER: "77"}
        )

        span = _server_span(span_exporter)
        assert span.attributes.get(EXECUTION_ID_ATTRIBUTE) == "77"
        assert WORKFLOW_ID_ATTRIBUTE not in span.attributes

    async def test_an_empty_header_value_is_not_recorded(
        self, traced_client, span_exporter
    ) -> None:
        """An orchestrator that sends the header but has nothing to put in it is
        the same situation as not sending it."""
        await traced_client.get(
            "/api/elevators",
            headers={EXECUTION_ID_HEADER: "", WORKFLOW_ID_HEADER: "   "},
        )

        span = _server_span(span_exporter)
        assert EXECUTION_ID_ATTRIBUTE not in span.attributes
        assert WORKFLOW_ID_ATTRIBUTE not in span.attributes

    async def test_an_overlong_header_value_is_truncated_not_dropped(
        self, traced_client, span_exporter
    ) -> None:
        """The header is caller-controlled and lands in a span attribute.

        Dropping it would lose the signal; storing it whole would let a caller
        push arbitrarily large strings into the trace backend.
        """
        await traced_client.get(
            "/api/elevators", headers={EXECUTION_ID_HEADER: "9" * 500}
        )

        span = _server_span(span_exporter)
        recorded = span.attributes.get(EXECUTION_ID_ATTRIBUTE)
        assert recorded is not None, "an overlong value must still be recorded"
        # The actual bound, not merely "shorter than what was sent". Asserting
        # `< 500` left the 128-character limit free to become 499 with the suite
        # still green, which is a bound in a constant rather than in the code.
        assert len(recorded) == MAX_VALUE_LENGTH


class TestOrchestrationAttributesAreInert:
    async def test_the_request_succeeds_when_tracing_is_not_recording(
        self, client
    ) -> None:
        """The `client` fixture is not the instrumented one.

        The middleware must not assume a recording span exists — `get_current_span`
        returns a non-recording span when telemetry is off, and calling
        `set_attribute` on it has to stay a no-op rather than an AttributeError
        on every request in a deployment with OTel disabled.
        """
        response = await client.get(
            "/api/elevators",
            headers={EXECUTION_ID_HEADER: "1", WORKFLOW_ID_HEADER: "wf"},
        )
        assert response.status_code == 200


class TestTheRecordingGuard:
    async def test_nothing_is_stamped_on_a_non_recording_span(self, monkeypatch) -> None:
        """The `span.is_recording()` check, asserted rather than assumed.

        `TestOrchestrationAttributesAreInert` only proves the request does not
        crash, and it would not crash without the guard either: `set_attribute`
        on a non-recording span is a silent no-op. So that test passed with the
        guard deleted, which left task 5.5 a claim rather than a check.

        Driven directly rather than through the client. Patching
        `get_current_span` on the shared `opentelemetry.trace` module also
        patches it for the SDK, and the FastAPI instrumentation then produces no
        server span at all — the test fails, but for the wrong reason. Replacing
        only the middleware module's own binding keeps the blast radius to the
        code under test.
        """
        from app.core import orchestration_context as module

        calls: list[tuple[str, object]] = []

        class NonRecordingSpan:
            def is_recording(self) -> bool:
                return False

            def set_attribute(self, key, value) -> None:
                calls.append((key, value))

        monkeypatch.setattr(
            module, "trace", type("T", (), {"get_current_span": staticmethod(lambda: NonRecordingSpan())})
        )

        seen = {}

        async def app(scope, receive, send):
            seen["called"] = True

        middleware = module.OrchestrationContextMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(module.EXECUTION_ID_HEADER, b"99"), (module.WORKFLOW_ID_HEADER, b"wf")],
        }
        await middleware(scope, None, None)

        assert seen.get("called"), "the request must still be served"
        assert calls == [], f"attributes were stamped on a non-recording span: {calls}"

    async def test_a_non_http_scope_passes_straight_through(self, monkeypatch) -> None:
        """Websocket and lifespan scopes have no headers to read."""
        from app.core import orchestration_context as module

        seen = {}

        async def app(scope, receive, send):
            seen["called"] = True

        await module.OrchestrationContextMiddleware(app)({"type": "lifespan"}, None, None)
        assert seen.get("called")
