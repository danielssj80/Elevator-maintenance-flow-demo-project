"""HTTP client for the scoring service.

Structurally a twin of ``BedrockClient``: a thin wrapper that owns the
timeout, takes an injectable transport for tests, and translates transport
failures into an HTTP status the caller can return unchanged.

The 503 is the important part. The scoring service is deliberately absent in
production, so "cannot reach it" is an expected state, not a bug. A 500 with a
stack trace would misreport a designed absence as a crash.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from app.core.config import settings


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
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            # Narrow on purpose. A bare `except Exception` here would also
            # swallow a programming error in this module and report it as a
            # missing service.
            raise HTTPException(
                status_code=503,
                detail="Inference service is unavailable",
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
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=503, detail="Inference service is unavailable"
            ) from exc

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Inference service returned {response.status_code}",
            )
        return response.json()["feature_names"]
