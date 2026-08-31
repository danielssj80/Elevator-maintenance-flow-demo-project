"""A reading has an identity, and storing it twice must change nothing.

The reason this matters is one line away in `TelemetryRepository`: the inference
run builds its feature vector with `func.avg(...)` over the rows in the window,
not over distinct readings. A batch present twice is therefore weighted twice
and drags the aggregate toward itself — no exception, no log line, just a score
that is quietly wrong. The producer is a scheduled n8n workflow, and n8n retries
a failed node by re-sending the same payload, so a repeated batch is an expected
event rather than an anomaly.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator
from app.models.telemetry import TelemetryReading
from app.repositories.telemetry_repository import TelemetryRepository

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
WINDOW_START = NOW - timedelta(hours=24)


def _make_elevator(id: str) -> Elevator:
    return Elevator(
        id=id,
        building_name="Test Building",
        building_type="office",
        floor_count=5,
        model="Test Model",
        brand="own",
        age_years=3,
        risk_score=0.4,
        risk_level="low",
        last_visit_date="2026-01-01",
        last_visit_technician="Ana",
        last_visit_notes="ok",
        nl_explanation="all good",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
    )


def _make_reading(
    elevator_id: str,
    recorded_at: datetime,
    *,
    ambient_c: float = 27.0,
    motor_c: float = 37.0,
    rpm: float = 1500.0,
    torque: float = 40.0,
    run_hours: float | None = 12_000.0,
    source: str = "test",
    batch_id: str = "batch-1",
) -> TelemetryReading:
    return TelemetryReading(
        elevator_id=elevator_id,
        recorded_at=recorded_at,
        ingested_at=NOW,
        ambient_temperature_c=ambient_c,
        motor_temperature_c=motor_c,
        motor_speed_rpm=rpm,
        load_torque_nm=torque,
        motor_run_hours_cumulative=run_hours,
        source=source,
        batch_id=batch_id,
        trace_id="0af7651916cd43dd8448eb211c80319c",
    )


async def _count(session: AsyncSession, elevator_id: str) -> int:
    result = await session.execute(
        select(func.count(TelemetryReading.id)).where(
            TelemetryReading.elevator_id == elevator_id
        )
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_the_same_identity_is_stored_once(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-ID01"))
    await db_session.flush()
    repo = TelemetryRepository(db_session)

    await repo.create_many([_make_reading("ELV-ID01", NOW)])
    await repo.create_many([_make_reading("ELV-ID01", NOW)])
    await db_session.flush()

    assert await _count(db_session, "ELV-ID01") == 1


@pytest.mark.asyncio
async def test_create_many_reports_the_rows_it_actually_inserted(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-ID02"))
    await db_session.flush()
    repo = TelemetryRepository(db_session)

    readings = [_make_reading("ELV-ID02", NOW - timedelta(minutes=i)) for i in range(3)]

    assert await repo.create_many(readings) == 3
    assert await repo.create_many(readings) == 0


@pytest.mark.asyncio
async def test_a_partially_overlapping_batch_inserts_only_what_is_new(
    db_session: AsyncSession,
):
    db_session.add(_make_elevator("ELV-ID03"))
    await db_session.flush()
    repo = TelemetryRepository(db_session)

    await repo.create_many(
        [_make_reading("ELV-ID03", NOW - timedelta(minutes=i)) for i in range(2)]
    )
    inserted = await repo.create_many(
        [_make_reading("ELV-ID03", NOW - timedelta(minutes=i)) for i in range(4)]
    )
    await db_session.flush()

    assert inserted == 2
    assert await _count(db_session, "ELV-ID03") == 4


@pytest.mark.asyncio
async def test_a_stored_reading_is_not_overwritten_by_a_resubmission(
    db_session: AsyncSession,
):
    """DO NOTHING, not DO UPDATE.

    A reading is an observation: a second report of the same identity carries no
    new information, and overwriting would let a late retry silently replace a
    value the last inference run already consumed.
    """
    db_session.add(_make_elevator("ELV-ID04"))
    await db_session.flush()
    repo = TelemetryRepository(db_session)

    await repo.create_many([_make_reading("ELV-ID04", NOW, ambient_c=27.0)])
    await repo.create_many([_make_reading("ELV-ID04", NOW, ambient_c=99.0)])
    await db_session.flush()

    rows = await repo.list_for_elevator("ELV-ID04", since=WINDOW_START, limit=10)
    assert len(rows) == 1
    assert rows[0].ambient_temperature_c == 27.0


@pytest.mark.asyncio
async def test_the_same_instant_from_another_source_is_a_distinct_reading(
    db_session: AsyncSession,
):
    """Two producers reporting the same elevator at the same instant are two
    independent observations, and averaging both is correct. A retry never
    changes `source`, so keeping it in the identity costs the guarantee nothing.
    """
    db_session.add(_make_elevator("ELV-ID05"))
    await db_session.flush()
    repo = TelemetryRepository(db_session)

    await repo.create_many([_make_reading("ELV-ID05", NOW, source="n8n-ingest")])
    await repo.create_many([_make_reading("ELV-ID05", NOW, source="field-gateway")])
    await db_session.flush()

    assert await _count(db_session, "ELV-ID05") == 2


@pytest.mark.asyncio
async def test_a_duplicated_batch_does_not_move_the_window_aggregate(
    db_session: AsyncSession,
):
    """The guarantee this whole change exists to provide.

    Without the identity constraint the second ingest doubles every row in the
    window. The averages survive an exact duplication by arithmetic accident,
    but `reading_count` does not — and neither do the averages the moment the
    retry is partial, which is the realistic case.
    """
    db_session.add(_make_elevator("ELV-ID06"))
    await db_session.flush()
    repo = TelemetryRepository(db_session)

    # Built fresh on every call, exactly as a retry arrives: a new payload
    # carrying the same identities. Reusing the ORM instances would let the
    # identity map absorb the duplication and the test would pass with no
    # constraint in the database at all.
    def payload(*, with_late_reading: bool) -> list[TelemetryReading]:
        readings = [
            _make_reading("ELV-ID06", NOW - timedelta(minutes=15), ambient_c=20.0),
            _make_reading("ELV-ID06", NOW - timedelta(minutes=30), ambient_c=30.0),
        ]
        if with_late_reading:
            readings.append(
                _make_reading("ELV-ID06", NOW - timedelta(minutes=45), ambient_c=40.0)
            )
        return readings

    await repo.create_many(payload(with_late_reading=False))
    await db_session.flush()
    before = (await repo.aggregate_window(WINDOW_START, NOW))["ELV-ID06"]

    # The retry: the same two readings, plus one the producer captured later.
    await repo.create_many(payload(with_late_reading=True))
    await db_session.flush()
    after = (await repo.aggregate_window(WINDOW_START, NOW))["ELV-ID06"]

    assert before.reading_count == 2
    assert before.ambient_temperature_c == pytest.approx(25.0)
    # Three distinct readings, each counted once: 20, 30, 40.
    assert after.reading_count == 3
    assert after.ambient_temperature_c == pytest.approx(30.0)


# ── The assumptions `_as_insert_values` rests on ─────────────────────────────


def test_a_column_with_a_server_default_is_omitted_when_unset():
    """`ingested_at` must not be named in the INSERT when nothing set it.

    A server default only applies to a column the statement omits. Naming it
    with a None value writes NULL into a NOT NULL column, and the failure would
    surface as an IntegrityError from a code path that looks like it is just
    copying attributes across.
    """
    from app.repositories.telemetry_repository import _as_insert_values

    reading = TelemetryReading(
        elevator_id="ELV-ID07",
        recorded_at=NOW,
        ambient_temperature_c=27.0,
        motor_temperature_c=37.0,
        motor_speed_rpm=1500.0,
        load_torque_nm=40.0,
        source="test",
        batch_id="batch-1",
    )

    values = _as_insert_values(reading)

    assert "ingested_at" not in values
    assert "id" not in values
    # A nullable column with no default is still passed through as None: that is
    # the value, not an omission.
    assert values["trace_id"] is None
    assert values["elevator_id"] == "ELV-ID07"


def test_no_column_carries_a_python_side_default():
    """The invariant `_as_insert_values` relies on, asserted rather than assumed.

    It builds the INSERT by naming every non-primary-key column, so a column
    with a real Python-side default would be written as NULL instead of that
    default — silently, and only for rows that leave it unset. Every nullable
    column here is `mapped_column(default=None)`, which SQLAlchemy reads as "no
    default", so `column.default` is None throughout. This test is what turns
    adding one into a red suite rather than a data bug.
    """
    from sqlalchemy import inspect as sa_inspect

    columns = sa_inspect(TelemetryReading).local_table.columns
    with_python_default = sorted(c.key for c in columns if c.default is not None)

    assert with_python_default == [], (
        f"{with_python_default} now carry a Python-side default. "
        "_as_insert_values names every column explicitly, so an unset one would "
        "be written as NULL rather than taking that default — teach it to omit "
        "them, the way it already omits columns with a server default."
    )
