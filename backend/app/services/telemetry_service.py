"""Ingest of elevator telemetry batches.

Two decisions live here and are both load-bearing:

* **A batch survives an unknown elevator id.** The producer is a scheduled n8n
  workflow reading the fleet and posting one reading per elevator. Failing the
  whole request over one stale id would drop 99 good readings, so unknown ids
  are filtered and reported instead. A batch in which *nothing* is valid is a
  different situation — a misconfigured producer, not a stale row — and is
  rejected outright so it cannot fail silently.

* **Readings are persisted exactly as submitted.** No unit conversion happens
  here. The model's Kelvin feature space is reached at one boundary inside the
  inference path; converting here too would double-apply the offset.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from opentelemetry import trace

from app.models.telemetry import TelemetryReading
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.telemetry import (
    TelemetryBatchSchema,
    TelemetryIngestResponseSchema,
    TelemetryReadingSchema,
)


def current_trace_id() -> str | None:
    """The active trace id as 32 lowercase hex characters, or None.

    Returns None when tracing is disabled or no span is recording, so that a
    row's provenance is honestly empty rather than carrying the all-zero id
    that ``format_trace_id`` would produce for an invalid context.
    """
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return trace.format_trace_id(span_context.trace_id)


class TelemetryService:
    def __init__(
        self,
        telemetry_repository: TelemetryRepository,
        elevator_repository: ElevatorRepository,
    ) -> None:
        self._telemetry_repo = telemetry_repository
        self._elevator_repo = elevator_repository

    async def ingest(self, batch: TelemetryBatchSchema) -> TelemetryIngestResponseSchema:
        submitted_ids = {r.elevator_id for r in batch.readings}
        known_ids = await self._elevator_repo.filter_existing_ids(submitted_ids)
        rejected = sorted(submitted_ids - known_ids)

        valid = [r for r in batch.readings if r.elevator_id in known_ids]
        if not valid:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No reading in the batch references a known elevator: "
                    f"{', '.join(rejected)}"
                ),
            )

        batch_id = str(uuid.uuid4())
        trace_id = current_trace_id()
        ingested_at = datetime.now(UTC)

        await self._telemetry_repo.create_many(
            [
                TelemetryReading(
                    elevator_id=r.elevator_id,
                    recorded_at=r.recorded_at,
                    ingested_at=ingested_at,
                    ambient_temperature_c=r.ambient_temperature_c,
                    motor_temperature_c=r.motor_temperature_c,
                    motor_speed_rpm=r.motor_speed_rpm,
                    load_torque_nm=r.load_torque_nm,
                    motor_run_hours_cumulative=r.motor_run_hours_cumulative,
                    vibration_mm_s=r.vibration_mm_s,
                    door_cycles=r.door_cycles,
                    door_errors=r.door_errors,
                    motor_current_a=r.motor_current_a,
                    source=batch.source,
                    batch_id=batch_id,
                    trace_id=trace_id,
                )
                for r in valid
            ]
        )

        return TelemetryIngestResponseSchema(
            batch_id=batch_id,
            accepted=len(valid),
            rejected_elevator_ids=rejected,
            trace_id=trace_id,
        )

    async def list_readings(
        self, elevator_id: str, since: datetime, limit: int
    ) -> list[TelemetryReadingSchema]:
        rows = await self._telemetry_repo.list_for_elevator(elevator_id, since, limit)
        return [TelemetryReadingSchema.model_validate(r) for r in rows]
