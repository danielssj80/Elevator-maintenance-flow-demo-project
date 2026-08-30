"""The scoring service is absent in production by design.

Unreachable therefore means 503 — a designed absence — and never 500 with a
stack trace, which would report it as a crash.
"""

import httpx
import pytest
from fastapi import HTTPException

from app.services.inference_client import InferenceClient

FEATURE_NAMES = ["Air_temperature__K", "Torque__Nm"]
ROWS = [[300.15, 40.0]]


def _client_raising(exc: Exception) -> InferenceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    transport = httpx.MockTransport(handler)
    return InferenceClient(
        base_url="http://inference:8001",
        client=httpx.AsyncClient(transport=transport),
    )


def _client_returning(status_code: int, json_body: dict | None = None) -> InferenceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body or {})

    transport = httpx.MockTransport(handler)
    return InferenceClient(
        base_url="http://inference:8001",
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.mark.asyncio
async def test_connect_error_becomes_503():
    client = _client_raising(httpx.ConnectError("connection refused"))

    with pytest.raises(HTTPException) as exc:
        await client.score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_timeout_becomes_503():
    client = _client_raising(httpx.ReadTimeout("timed out"))

    with pytest.raises(HTTPException) as exc:
        await client.score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_connect_timeout_becomes_503():
    client = _client_raising(httpx.ConnectTimeout("timed out connecting"))

    with pytest.raises(HTTPException) as exc:
        await client.score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_a_programming_error_is_not_disguised_as_an_absent_service():
    """The except clause must stay narrow.

    Broadening it to `except Exception` would report a bug in this module as a
    missing inference service, which is exactly the kind of misdirection that
    costs an afternoon.
    """
    client = _client_raising(ValueError("bug in the client"))

    with pytest.raises(ValueError):
        await client.score(FEATURE_NAMES, ROWS)


@pytest.mark.asyncio
async def test_a_non_200_from_the_service_is_502_not_503():
    """Reachable but unhappy is a different situation from absent."""
    client = _client_returning(422, {"detail": "column mismatch"})

    with pytest.raises(HTTPException) as exc:
        await client.score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_a_successful_score_is_unpacked():
    client = _client_returning(
        200,
        {"scores": [0.9], "contributions": [[0.1, -0.2]], "model_version": "abc123"},
    )

    scores, contributions, version = await client.score(FEATURE_NAMES, ROWS)

    assert scores == [0.9]
    assert contributions == [[0.1, -0.2]]
    assert version == "abc123"


@pytest.mark.asyncio
async def test_feature_names_are_read_from_the_service():
    client = _client_returning(200, {"feature_names": FEATURE_NAMES, "model_version": "x"})

    assert await client.feature_names() == FEATURE_NAMES


@pytest.mark.asyncio
async def test_feature_names_connect_error_becomes_503():
    client = _client_raising(httpx.ConnectError("connection refused"))

    with pytest.raises(HTTPException) as exc:
        await client.feature_names()

    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "exception",
    [
        httpx.RemoteProtocolError("server disconnected mid-response"),
        httpx.ReadError("connection reset while reading"),
        httpx.WriteError("connection reset while writing"),
        httpx.PoolTimeout("no connection available"),
    ],
    ids=["remote_protocol", "read", "write", "pool_timeout"],
)
@pytest.mark.asyncio
async def test_every_transport_fault_becomes_503(exception: Exception):
    """Not just the two ways the service can be absent.

    ConnectError and TimeoutException cover "nothing is listening" and "it never
    answered". They do not cover the connection dying mid-request — and the
    scorer runs under a 512 MB limit, so an OOM kill part-way through a response
    is an ordinary event, not a hypothetical. Before this, those escaped as an
    unhandled 500 with a traceback, which specs/risk-inference forbids in those
    words.
    """
    client = _client_raising(exception)

    with pytest.raises(HTTPException) as exc:
        await client.score(FEATURE_NAMES, ROWS)

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_an_http_status_error_is_not_mistaken_for_a_transport_fault():
    """The catch must stay a transport catch.

    HTTPStatusError is not a TransportError: the service answered, and answered
    badly. Reporting that as "unavailable" would send someone looking for a dead
    container instead of a bad request.
    """
    client = _client_raising(
        httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"), response=httpx.Response(500))
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.score(FEATURE_NAMES, ROWS)
