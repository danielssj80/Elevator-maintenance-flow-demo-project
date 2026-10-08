"""The scorer reached as a Lambda function instead of over HTTP.

Production has no scoring container: the backend invokes `elevator-scorer`
with the instance role. The contract the rest of the backend relies on is the
HTTP client's, so this transport has to keep it exactly:

- anything that stops the call from reaching the scorer → 503 (absent);
- the scorer running and failing → 502 (it answered, badly).

The boto3 client is a stub throughout. Nothing here touches the network.
"""

import asyncio
import io
import json
import threading
import time
from typing import Any

import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
    ResponseStreamingError,
)
from fastapi import HTTPException

from app.core import telemetry as telemetry_module
from app.core.config import settings
from app.services.inference_client import (
    InferenceClient,
    LambdaInferenceClient,
    get_inference_client,
)

FUNCTION = "elevator-scorer"
FEATURE_NAMES = ["Air_temperature__K", "Torque__Nm"]
ROWS = [[300.15, 40.0]]


class StubLambda:
    """Records each invoke and answers with a canned result or raises."""

    def __init__(
        self,
        body: dict | None = None,
        function_error: str | None = None,
        raises: Exception | None = None,
        on_invoke=None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._body = body if body is not None else {}
        self._function_error = function_error
        self._raises = raises
        self._on_invoke = on_invoke

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._on_invoke is not None:
            self._on_invoke()
        if self._raises is not None:
            raise self._raises
        response: dict[str, Any] = {
            "StatusCode": 200,
            "Payload": io.BytesIO(json.dumps(self._body).encode()),
        }
        if self._function_error:
            response["FunctionError"] = self._function_error
        return response


def _client(stub: StubLambda) -> LambdaInferenceClient:
    return LambdaInferenceClient(function_name=FUNCTION, boto_client=stub)


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Invoke")


# ── Happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_score_round_trips_through_the_function():
    stub = StubLambda(
        body={"scores": [0.42], "contributions": [[0.1, -0.2]], "model_version": "abc123"}
    )

    scores, contributions, version = await _client(stub).score(FEATURE_NAMES, ROWS)

    assert (scores, contributions, version) == ([0.42], [[0.1, -0.2]], "abc123")
    [call] = stub.calls
    assert call["FunctionName"] == FUNCTION
    assert call["InvocationType"] == "RequestResponse"
    payload = json.loads(call["Payload"])
    assert payload["operation"] == "score"
    assert payload["feature_names"] == FEATURE_NAMES
    assert payload["rows"] == ROWS


@pytest.mark.asyncio
async def test_feature_names_asks_the_function_for_the_model():
    stub = StubLambda(body={"feature_names": FEATURE_NAMES, "model_version": "abc123"})

    names = await _client(stub).feature_names()

    assert names == FEATURE_NAMES
    assert json.loads(stub.calls[0]["Payload"])["operation"] == "model"


# ── Could not reach the scorer → 503 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "error",
    [
        EndpointConnectionError(endpoint_url="https://lambda.eu-north-1.amazonaws.com"),
        ReadTimeoutError(endpoint_url="https://lambda.eu-north-1.amazonaws.com"),
        NoCredentialsError(),
        _client_error("TooManyRequestsException"),
        _client_error("AccessDeniedException"),
        _client_error("ResourceNotFoundException"),
    ],
    ids=["unreachable", "timeout", "no-credentials", "throttled", "access-denied", "no-function"],
)
@pytest.mark.asyncio
async def test_failing_to_invoke_is_unavailability(error: Exception):
    """Unreachable, throttled, unauthorised or missing: the scorer never ran.

    The HTTP client maps the whole transport family to 503 because the service
    may be absent; these are the Lambda equivalents of a refused connection.
    """
    with pytest.raises(HTTPException) as exc:
        await _client(StubLambda(raises=error)).score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 503
    assert exc.value.detail == "Inference service is unavailable"


@pytest.mark.asyncio
async def test_feature_names_maps_unavailability_the_same_way():
    stub = StubLambda(raises=EndpointConnectionError(endpoint_url="https://x"))

    with pytest.raises(HTTPException) as exc:
        await _client(stub).feature_names()

    assert exc.value.status_code == 503


# ── The scorer ran and failed → 502 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_function_error_is_not_disguised_as_absence():
    """The handler crashed. That is the service failing, not the service missing."""
    stub = StubLambda(
        body={"errorMessage": "boom", "errorType": "RuntimeError"},
        function_error="Unhandled",
    )

    with pytest.raises(HTTPException) as exc:
        await _client(stub).score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_a_client_error_result_is_502_with_its_detail():
    """A column-order mismatch comes back as a result, not a crash.

    Same status the HTTP client gives the service's 422 today, so the run
    endpoint answers the same way whichever transport is configured.
    """
    stub = StubLambda(
        body={"error": {"type": "client", "detail": "expected columns ['a', 'b']"}}
    )

    with pytest.raises(HTTPException) as exc:
        await _client(stub).score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 502
    assert "expected columns" in exc.value.detail


# ── Off the event loop, inside the trace ─────────────────────────────────────


@pytest.mark.asyncio
async def test_the_invoke_runs_off_the_event_loop():
    """boto3 is synchronous. On the loop thread it would stall every request."""
    loop_thread = threading.get_ident()
    seen: list[int] = []
    stub = StubLambda(
        body={"scores": [0.1], "contributions": [[0.0, 0.0]], "model_version": "v"},
        on_invoke=lambda: seen.append(threading.get_ident()),
    )

    await _client(stub).score(FEATURE_NAMES, ROWS)

    assert seen and seen[0] != loop_thread


@pytest.mark.asyncio
async def test_concurrent_invocations_overlap():
    delay = 0.4
    body = {"scores": [0.1], "contributions": [[0.0, 0.0]], "model_version": "v"}

    started = time.perf_counter()
    await asyncio.gather(
        _client(StubLambda(body=body, on_invoke=lambda: time.sleep(delay))).score(
            FEATURE_NAMES, ROWS
        ),
        _client(StubLambda(body=body, on_invoke=lambda: time.sleep(delay))).score(
            FEATURE_NAMES, ROWS
        ),
    )

    assert time.perf_counter() - started < delay * 1.5, "the event loop is being blocked"


@pytest.mark.asyncio
async def test_the_trace_context_travels_in_the_payload(span_exporter):
    """The scorer continues the caller's trace from the payload.

    Lambda carries no HTTP headers for a direct invoke, so W3C context has to
    ride in the event or the scorer's span becomes a detached root.
    """
    stub = StubLambda(
        body={"scores": [0.1], "contributions": [[0.0, 0.0]], "model_version": "v"}
    )

    with telemetry_module.get_tracer("test").start_as_current_span("caller") as span:
        await _client(stub).score(FEATURE_NAMES, ROWS)
        trace_id = format(span.get_span_context().trace_id, "032x")

    carrier = json.loads(stub.calls[0]["Payload"])["trace_context"]
    assert trace_id in carrier["traceparent"]


# ── Transport selection ──────────────────────────────────────────────────────


def test_the_lambda_transport_is_chosen_when_a_function_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "inference_lambda_function", FUNCTION)
    monkeypatch.setattr(
        "app.services.inference_client._lambda_boto_client", lambda: StubLambda()
    )

    assert isinstance(get_inference_client(), LambdaInferenceClient)


@pytest.mark.parametrize("unset", [None, ""])
def test_the_http_transport_is_kept_when_no_function_is_configured(monkeypatch, unset):
    """Local keeps its container. An empty value must not mean "invoke ''"."""
    monkeypatch.setattr(settings, "inference_lambda_function", unset)

    def _no_boto():
        raise AssertionError("the HTTP path built a boto3 client")

    monkeypatch.setattr("app.services.inference_client._lambda_boto_client", _no_boto)

    assert type(get_inference_client()) is InferenceClient


def test_the_run_endpoint_uses_the_configured_transport(monkeypatch):
    """The factory is only worth something if the router asks it.

    A router still constructing `InferenceClient()` directly would keep
    production on the HTTP URL, where no scorer runs, and answer 503 forever.
    """
    from app.routers.inference import get_inference_service

    monkeypatch.setattr(settings, "inference_lambda_function", FUNCTION)
    monkeypatch.setattr(
        "app.services.inference_client._lambda_boto_client", lambda: StubLambda()
    )

    service = get_inference_service(db=None)

    assert isinstance(service._client, LambdaInferenceClient)


# ── Failures while reading the answer ────────────────────────────────────────


class BrokenPayload:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def read(self) -> bytes:
        raise self._exc


class RawLambda(StubLambda):
    """Answers with an arbitrary payload object or raw bytes."""

    def __init__(self, payload, function_error: str | None = None) -> None:
        super().__init__()
        self._payload = payload
        self._fe = function_error

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        response = {"StatusCode": 200, "Payload": self._payload}
        if self._fe:
            response["FunctionError"] = self._fe
        return response


@pytest.mark.parametrize(
    "error",
    [
        ReadTimeoutError(endpoint_url="https://lambda.eu-north-1.amazonaws.com"),
        ResponseStreamingError(error="connection reset"),
    ],
    ids=["read-timeout", "stream-reset"],
)
@pytest.mark.asyncio
async def test_a_response_that_dies_while_being_read_is_unavailability(error):
    """The HTTP transport's "connection dies mid-response" case: still 503, never 500."""
    with pytest.raises(HTTPException) as exc:
        await _client(RawLambda(BrokenPayload(error))).score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"null", b"[]", b'{"scores": [0.1]}', b'"a string"'],
    ids=["not-json", "null", "list", "missing-keys", "string"],
)
@pytest.mark.asyncio
async def test_a_malformed_answer_is_502_not_500(raw):
    with pytest.raises(HTTPException) as exc:
        await _client(RawLambda(io.BytesIO(raw))).score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_a_function_error_with_an_unreadable_body_is_still_502():
    stub = RawLambda(io.BytesIO(b"<html>oops"), function_error="Unhandled")

    with pytest.raises(HTTPException) as exc:
        await _client(stub).score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 502


def test_botocore_makes_exactly_one_attempt():
    """`max_attempts` counts RETRIES in botocore: 1 meant two calls, and a
    read timeout re-invoked the scorer and doubled the wait."""
    from app.services.inference_client import _lambda_boto_client

    config = _lambda_boto_client().meta.config

    assert config.retries.get("total_max_attempts") == 1
    assert "max_attempts" not in config.retries
