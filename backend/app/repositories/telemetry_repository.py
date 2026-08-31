from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryReading


class WindowAggregate:
    """One elevator's telemetry summarised over an inference window.

    Temperatures, speed and torque are averaged because they are operating
    conditions sampled repeatedly; cumulative run hours are taken as the
    maximum because they only ever increase and averaging them would understate
    consumed motor life.
    """

    def __init__(
        self,
        elevator_id: str,
        ambient_temperature_c: float,
        motor_temperature_c: float,
        motor_speed_rpm: float,
        load_torque_nm: float,
        motor_run_hours_cumulative: float | None,
        reading_count: int,
    ) -> None:
        self.elevator_id = elevator_id
        self.ambient_temperature_c = ambient_temperature_c
        self.motor_temperature_c = motor_temperature_c
        self.motor_speed_rpm = motor_speed_rpm
        self.load_torque_nm = load_torque_nm
        self.motor_run_hours_cumulative = motor_run_hours_cumulative
        self.reading_count = reading_count


class TelemetryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, readings: list[TelemetryReading]) -> None:
        self._session.add_all(readings)

    async def list_for_elevator(
        self, elevator_id: str, since: datetime, limit: int, until: datetime | None = None
    ) -> list[TelemetryReading]:
        conditions = [
            TelemetryReading.elevator_id == elevator_id,
            TelemetryReading.recorded_at >= since,
        ]
        if until is not None:
            conditions.append(TelemetryReading.recorded_at <= until)
        result = await self._session.execute(
            select(TelemetryReading)
            .where(*conditions)
            .order_by(TelemetryReading.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def aggregate_window(
        self, since: datetime, until: datetime
    ) -> dict[str, WindowAggregate]:
        """Summarise each elevator's readings in the window, keyed by elevator id.

        Elevators with no readings in the window are simply absent from the
        result. That absence is what the inference service uses to skip them:
        a unit that stopped reporting must show as stale, not as suddenly
        low-risk.

        The window is bounded at **both** ends. With a lower bound only, a
        single future-dated reading stays inside every subsequent window for
        ever, so the elevator never falls out of scope and never reads as
        stale — and the retention prune, which only deletes below its cutoff,
        never reaches it either. That combination permanently defeats the
        skip-when-silent rule for that elevator.
        """
        result = await self._session.execute(
            select(
                TelemetryReading.elevator_id,
                func.avg(TelemetryReading.ambient_temperature_c),
                func.avg(TelemetryReading.motor_temperature_c),
                func.avg(TelemetryReading.motor_speed_rpm),
                func.avg(TelemetryReading.load_torque_nm),
                func.max(TelemetryReading.motor_run_hours_cumulative),
                func.count(TelemetryReading.id),
            )
            .where(
                TelemetryReading.recorded_at >= since,
                TelemetryReading.recorded_at <= until,
            )
            .group_by(TelemetryReading.elevator_id)
        )
        return {
            row[0]: WindowAggregate(
                elevator_id=row[0],
                ambient_temperature_c=float(row[1]),
                motor_temperature_c=float(row[2]),
                motor_speed_rpm=float(row[3]),
                load_torque_nm=float(row[4]),
                motor_run_hours_cumulative=None if row[5] is None else float(row[5]),
                reading_count=int(row[6]),
            )
            for row in result.all()
        }

    async def prune(self, cutoff: datetime, future_cutoff: datetime) -> int:
        """Delete readings outside the retained band.

        Both ends again: ingest validation rejects future timestamps, but rows
        predating that validation, or inserted by any other route, would
        otherwise be unreachable by the prune and permanently resident in the
        window.
        """
        result = await self._session.execute(
            delete(TelemetryReading).where(
                or_(
                    TelemetryReading.recorded_at < cutoff,
                    TelemetryReading.recorded_at > future_cutoff,
                )
            )
        )
        return result.rowcount or 0
