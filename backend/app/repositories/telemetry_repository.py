from datetime import datetime

from sqlalchemy import delete, func, inspect, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryReading

# The columns that identify a reading. Repeating one is a retry, not a new
# observation — see the model docstring for why `source` is among them.
IDENTITY_COLUMNS = ("elevator_id", "recorded_at", "source")


def _as_insert_values(reading: TelemetryReading) -> dict[str, object]:
    """One ORM instance flattened into values for a core INSERT.

    The conflict-tolerant insert has to be a core statement, but the service
    still speaks in domain objects, so the translation lives here. The primary
    key is left out so the sequence assigns it, and a column that is unset and
    carries a server default is left out too — naming it would insert NULL,
    because a server default only applies to a column the statement omits.
    """
    columns = inspect(TelemetryReading).local_table.columns
    values: dict[str, object] = {}
    for column in columns:
        if column.primary_key:
            continue
        value = getattr(reading, column.key)
        if value is None and column.server_default is not None:
            continue
        values[column.key] = value
    return values


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

    async def create_many(self, readings: list[TelemetryReading]) -> int:
        """Insert readings, skipping any whose identity is already stored.

        Returns the number of rows actually inserted, which is what the caller
        reports as ``accepted``.

        ``ON CONFLICT DO NOTHING`` rather than a read-then-insert: two
        simultaneous retries would both read "absent" and both insert, which is
        precisely the race a scheduler produces. Rather than ``DO UPDATE``
        because a reading is an observation — a second report of the same
        identity carries no new information, and overwriting would let a late
        retry replace a value the last inference run already consumed.

        A single multi-row VALUES clause, not executemany, so the ``RETURNING``
        count is unambiguous. At the 1000-reading batch bound that is ~14k bound
        parameters, well inside PostgreSQL's 65535 limit.
        """
        if not readings:
            return 0

        result = await self._session.execute(
            pg_insert(TelemetryReading)
            .values([_as_insert_values(r) for r in readings])
            .on_conflict_do_nothing(index_elements=list(IDENTITY_COLUMNS))
            .returning(TelemetryReading.id)
        )
        return len(result.scalars().all())

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
