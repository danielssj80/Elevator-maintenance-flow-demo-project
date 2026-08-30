"""Stateless scoring service.

It has no database session, no DATABASE_URL and no knowledge of elevators. It
receives a matrix and returns scores and contributions. Keeping the model here
rather than in the backend keeps ~300 MB of xgboost out of an image deployed to
a t3.micro, and out of every CI run, for a capability production never invokes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from inference.scorer import FeatureOrderMismatch, Scorer
from inference.telemetry import configure_telemetry, get_tracer, shutdown_telemetry

_scorer: Scorer | None = None


def get_scorer() -> Scorer:
    if _scorer is None:  # pragma: no cover — lifespan always sets it
        raise RuntimeError("scorer not loaded")
    return _scorer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Loaded once at startup rather than per request: joblib.load plus the
    # booster is the whole cost of this service, and the healthcheck should
    # fail if the model is missing rather than the first score request.
    global _scorer
    _scorer = Scorer()
    yield
    shutdown_telemetry()


app = FastAPI(title="Elevator Inference", version="0.1.0", lifespan=lifespan)

# Before anything else takes a reference to the ASGI app.
configure_telemetry(app)

tracer = get_tracer(__name__)


class ScoreRequest(BaseModel):
    feature_names: list[str] = Field(min_length=1)
    rows: list[list[float]] = Field(min_length=1)


class ScoreResponse(BaseModel):
    scores: list[float]
    contributions: list[list[float]]
    model_version: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/model")
def model_info() -> dict[str, object]:
    """The column order a caller must build its matrix in."""
    scorer = get_scorer()
    return {"feature_names": scorer.feature_names, "model_version": scorer.model_version}


@app.post("/score", response_model=ScoreResponse)
def score(request: ScoreRequest) -> ScoreResponse:
    scorer = get_scorer()
    with tracer.start_as_current_span("inference.score") as span:
        # Shape and identity only. Telemetry values are fleet operating data and
        # do not belong on a span, the same rule the briefing path follows for
        # prompt content.
        span.set_attribute("inference.row_count", len(request.rows))
        span.set_attribute("inference.feature_count", len(request.feature_names))
        span.set_attribute("inference.model_version", scorer.model_version)
        try:
            scores, contributions = scorer.score(request.feature_names, request.rows)
        except FeatureOrderMismatch as exc:
            # 422, not 500: the caller sent something the model cannot consume,
            # and it needs to see which columns were expected.
            span.set_attribute("inference.rejected", True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ScoreResponse(
        scores=scores, contributions=contributions, model_version=scorer.model_version
    )
