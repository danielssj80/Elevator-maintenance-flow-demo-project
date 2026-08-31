from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ingest_auth import require_ingest_token
from app.database import get_db
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.telemetry import (
    TelemetryBatchSchema,
    TelemetryIngestResponseSchema,
    TelemetryReadingSchema,
)
from app.services.telemetry_service import TelemetryService

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

DEFAULT_WINDOW_HOURS = 24


def get_telemetry_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TelemetryService:
    return TelemetryService(
        telemetry_repository=TelemetryRepository(db),
        elevator_repository=ElevatorRepository(db),
    )


@router.post(
    "/readings",
    response_model=TelemetryIngestResponseSchema,
    status_code=201,
    # On the write route only. The read route below answers what telemetry
    # exists and is not a way to change anything.
    dependencies=[Depends(require_ingest_token)],
)
async def ingest_readings(
    batch: TelemetryBatchSchema,
    service: Annotated[TelemetryService, Depends(get_telemetry_service)],
) -> TelemetryIngestResponseSchema:
    return await service.ingest(batch)


@router.get("/readings", response_model=list[TelemetryReadingSchema])
async def list_readings(
    service: Annotated[TelemetryService, Depends(get_telemetry_service)],
    elevator_id: Annotated[str, Query(min_length=1)],
    hours: Annotated[int, Query(ge=1, le=24 * 90)] = DEFAULT_WINDOW_HOURS,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[TelemetryReadingSchema]:
    """Readings for one elevator, newest first.

    An unknown elevator id returns an empty list rather than 404: the caller is
    asking what telemetry exists, and "none" is a real answer, not an error.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    return await service.list_readings(elevator_id, since=since, limit=limit)
