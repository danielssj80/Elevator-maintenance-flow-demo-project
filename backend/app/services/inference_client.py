"""Clients for the scoring service, over HTTP or as a Lambda function.

Structurally twins of ``BedrockClient``: thin wrappers that own the timeout,
take an injectable transport for tests, and translate transport failures into
an HTTP status the caller can return unchanged.

The 503 is the important part. The scoring service may be absent — no
container runs on the production host — so "cannot reach it" is an expected
state, not a bug. A 500 with a stack trace would misreport an absence as a
crash. A scorer that *ran* and failed is the other case, and answers 502.

``get_inference_client()`` picks the transport: the local stack keeps the HTTP
container, production invokes ``INFERENCE_LAMBDA_FUNCTION``.
"""

from __future__ import annotations

import json
from typing import Any

import anyio.to_thread
import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from opentelemetry import propagate

from app.core.config import settings

UNAVAILABLE_DETAIL = "Inference service is unavailable"


class InferenceClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or settings.inference_url).rstrip("/")
        self._timeout = timeout_seconds or settings.inference_timeout_seconds
        self._client = client

    async def score(
        self, feature_names: list[str], rows: list[list[float]]
    ) -> tuple[list[float], list[list[float]], str]:
        payload = {"feature_names": feature_names, "rows": rows}
        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self._base_url}/score", json=payload, timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(f"{self._base_url}/score", json=payload)
        except httpx.TransportError as exc:
            # The whole transport family, not two hand-picked members of it.
            # ConnectError and TimeoutException alone leave RemoteProtocolError,
            # ReadError and WriteError escaping as an unhandled 500 with a
            # traceback — and the scorer runs under a 512m limit, so a
            # connection dying mid-request is a real event, not a hypothetical.
            #
            # Still narrow where it matters: HTTPStatusError is not a
            # TransportError, and neither is a programming error in this module,
            # so neither is disguised as a missing service.
            raise HTTPException(
                status_code=503,
                detail=UNAVAILABLE_DETAIL,
            ) from exc

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Inference service returned {response.status_code}",
            )

        body = response.json()
        return body["scores"], body["contributions"], body["model_version"]

    async def feature_names(self) -> list[str]:
        """The column order the booster expects, read from the model itself."""
        try:
            if self._client is not None:
                response = await self._client.get(
                    f"{self._base_url}/model", timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(f"{self._base_url}/model")
        except httpx.TransportError as exc:
            raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from exc

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Inference service returned {response.status_code}",
            )
        return response.json()["feature_names"]


def _lambda_boto_client() -> Any:
    timeout = settings.inference_timeout_seconds
    return boto3.client(
        "lambda",
        region_name=settings.inference_lambda_region,
        config=Config(
            connect_timeout=timeout,
            read_timeout=timeout,
            # One attempt: a retried invoke doubles the wait for a scorer that
            # is down, and the run endpoint is the caller's to retry.
            retries={"max_attempts": 1},
        ),
    )


class LambdaInferenceClient:
    """The scorer invoked as ``elevator-scorer`` with the instance role.

    Same two methods and the same failure contract as ``InferenceClient``:
    anything that stops the invoke reaching the scorer is 503, the scorer
    answering with an error is 502.
    """

    def __init__(self, function_name: str | None = None, boto_client: Any = None) -> None:
        self._function_name = function_name or settings.inference_lambda_function
        self._client = boto_client or _lambda_boto_client()

    async def score(
        self, feature_names: list[str], rows: list[list[float]]
    ) -> tuple[list[float], list[list[float]], str]:
        body = await self._invoke(
            {"operation": "score", "feature_names": feature_names, "rows": rows}
        )
        return body["scores"], body["contributions"], body["model_version"]

    async def feature_names(self) -> list[str]:
        body = await self._invoke({"operation": "model"})
        return body["feature_names"]

    async def _invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        # A direct invoke carries no HTTP headers, so W3C context rides in the
        # event; without it the scorer's span would be a detached root.
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        event = {**payload, "trace_context": carrier}

        try:
            # boto3 is synchronous. anyio copies contextvars into the worker
            # thread, so the botocore client span still nests under the run.
            response = await anyio.to_thread.run_sync(
                lambda: self._client.invoke(
                    FunctionName=self._function_name,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(event).encode(),
                )
            )
        except (BotoCoreError, ClientError) as exc:
            # Unreachable endpoint, timeout, missing credentials, throttling,
            # access denied, unknown function: in every case the scorer never
            # ran, which is what 503 means here.
            raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from exc

        body = json.loads(response["Payload"].read() or b"{}")
        if response.get("FunctionError"):
            raise HTTPException(
                status_code=502,
                detail="Inference service returned a function error",
            )
        error = body.get("error") if isinstance(body, dict) else None
        if error:
            # The scorer refused the input (column order, unknown operation).
            # 502, the status the HTTP client gives the service's 422.
            raise HTTPException(
                status_code=502,
                detail=f"Inference service rejected the request: {error.get('detail', '')}",
            )
        return body


def get_inference_client() -> InferenceClient | LambdaInferenceClient:
    """The Lambda transport when a function is configured, HTTP otherwise.

    An empty value counts as unset, so a blank line in an env file keeps the
    HTTP client rather than invoking a function named "".
    """
    if settings.inference_lambda_function:
        return LambdaInferenceClient(boto_client=_lambda_boto_client())
    return InferenceClient()
