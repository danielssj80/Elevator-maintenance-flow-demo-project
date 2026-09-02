"""Carry the orchestrator's execution identity into the trace.

Trace *linkage* needs no code: n8n injects a W3C ``traceparent`` into outbound
HTTP and the FastAPI instrumentation continues it. This is the other half —
recording n8n's own identifiers as span attributes, so that a span can be taken
back to the execution that produced it and a failed execution forward to its
backend trace.

It is also the honest fallback. If header injection is ever off, or the
orchestrator's tracing is misconfigured, these attributes still land on the
server span: a degraded signal rather than none.

Deliberately one-way. Nothing under ``app/`` learns that n8n exists beyond two
header names, the middleware is a no-op when they are absent, and the backend
behaves identically with no orchestrator at all.
"""

from opentelemetry import trace
from starlette.types import ASGIApp, Receive, Scope, Send

EXECUTION_ID_HEADER = b"x-n8n-execution-id"
WORKFLOW_ID_HEADER = b"x-n8n-workflow-id"

EXECUTION_ID_ATTRIBUTE = "n8n.execution.id"
WORKFLOW_ID_ATTRIBUTE = "n8n.workflow.id"

# The header is caller-controlled and lands in a span attribute, so it is
# bounded. Real n8n ids are short; anything approaching this is not one, and
# truncating keeps the signal rather than dropping it.
MAX_VALUE_LENGTH = 128


class OrchestrationContextMiddleware:
    """Stamp ``X-N8N-Execution-Id`` / ``X-N8N-Workflow-Id`` onto the server span.

    Plain ASGI rather than ``BaseHTTPMiddleware``: this runs on every request and
    has no reason to buffer a body or spawn the anyio task pair that
    ``BaseHTTPMiddleware`` needs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        span = trace.get_current_span()
        # False when telemetry is disabled, where `span` is a non-recording
        # default. Skipping keeps this inert rather than relying on set_attribute
        # tolerating it.
        if span.is_recording():
            headers = dict(scope.get("headers") or [])
            for header, attribute in (
                (EXECUTION_ID_HEADER, EXECUTION_ID_ATTRIBUTE),
                (WORKFLOW_ID_HEADER, WORKFLOW_ID_ATTRIBUTE),
            ):
                value = _clean(headers.get(header))
                # Absent, not empty. Recording "" for every human-made request
                # would put an execution id on traces no orchestrator touched,
                # and make "filter to orchestrated requests" mean nothing.
                if value:
                    span.set_attribute(attribute, value)

        await self._app(scope, receive, send)


def _clean(raw: bytes | None) -> str | None:
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace").strip()[:MAX_VALUE_LENGTH]
