from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ingest_auth import require_ingest_token
from app.database import get_db
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.inference import InferenceRunResponseSchema
from app.services.inference_client import InferenceClient
from app.services.inference_service import InferenceService

router = APIRouter(prefix="/api/inference", tags=["inference"])


def get_inference_service(db: Annotated[AsyncSession, Depends(get_db)]) -> InferenceService:
    return InferenceService(
        session=db,
        elevator_repository=ElevatorRepository(db),
        telemetry_repository=TelemetryRepository(db),
        inference_client=InferenceClient(),
    )


@router.post(
    "/run",
    response_model=InferenceRunResponseSchema,
    dependencies=[Depends(require_ingest_token)],
)
async def run_inference(
    service: Annotated[InferenceService, Depends(get_inference_service)],
) -> InferenceRunResponseSchema:
    """Re-score the in-scope fleet from the telemetry window.

    Returns 503 when the scoring service is unreachable, which is the normal
    state anywhere it is not deployed — never a 500.
    """
    summary = await service.run()
    return InferenceRunResponseSchema(**summary.__dict__)
