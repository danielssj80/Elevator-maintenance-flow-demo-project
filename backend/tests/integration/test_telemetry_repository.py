from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator
from app.models.telemetry import TelemetryReading
from app.repositories.telemetry_repository import TelemetryRepository

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _make_elevator(id: str, *, in_scope: bool = True) -> Elevator:
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
        in_model_scope=in_scope,
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
        source="test",
        batch_id=batch_id,
        trace_id="0af7651916cd43dd8448eb211c80319c",
    )


@pytest.mark.asyncio
async def test_create_many_persists_a_batch(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-R01"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many(
        [_make_reading("ELV-R01", NOW - timedelta(minutes=i)) for i in range(3)]
    )
    await db_session.flush()

    rows = await repo.list_for_elevator("ELV-R01", since=NOW - timedelta(hours=1), limit=10)
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_list_for_elevator_returns_newest_first(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-R02"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many(
        [
            _make_reading("ELV-R02", NOW - timedelta(minutes=30)),
            _make_reading("ELV-R02", NOW - timedelta(minutes=10)),
            _make_reading("ELV-R02", NOW - timedelta(minutes=20)),
        ]
    )
    await db_session.flush()

    rows = await repo.list_for_elevator("ELV-R02", since=NOW - timedelta(hours=1), limit=10)
    recorded = [r.recorded_at for r in rows]
    assert recorded == sorted(recorded, reverse=True)


@pytest.mark.asyncio
async def test_readings_are_stored_in_celsius_exactly_as_submitted(db_session: AsyncSession):
    """The table is the system of record in human units.

    Kelvin conversion belongs to the inference path and to nowhere else; a
    reading that arrives as 27.0 must come back as 27.0.
    """
    db_session.add(_make_elevator("ELV-R03"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many([_make_reading("ELV-R03", NOW, ambient_c=27.0)])
    await db_session.flush()

    rows = await repo.list_for_elevator("ELV-R03", since=NOW - timedelta(hours=1), limit=10)
    assert rows[0].ambient_temperature_c == 27.0


@pytest.mark.asyncio
async def test_aggregate_window_excludes_readings_outside_the_window(db_session: AsyncSession):
    """A reading older than the window must not reach the aggregate.

    If it does, the run scores an elevator from data it was not supposed to
    see — and because the score stays plausible, nothing else catches it.
    """
    db_session.add(_make_elevator("ELV-R04"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many(
        [
            # Inside the window: torque 40.0
            _make_reading("ELV-R04", NOW - timedelta(minutes=10), torque=40.0),
            # Outside it, and far enough off that including it moves the mean.
            _make_reading("ELV-R04", NOW - timedelta(days=3), torque=80.0),
        ]
    )
    await db_session.flush()

    aggregates = await repo.aggregate_window(since=NOW - timedelta(hours=1), until=NOW)

    assert aggregates["ELV-R04"].reading_count == 1
    assert aggregates["ELV-R04"].load_torque_nm == 40.0


@pytest.mark.asyncio
async def test_aggregate_window_omits_elevators_with_no_readings(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-R05"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    aggregates = await repo.aggregate_window(since=NOW - timedelta(hours=1), until=NOW)

    assert "ELV-R05" not in aggregates


@pytest.mark.asyncio
async def test_aggregate_window_maxes_run_hours_and_averages_conditions(
    db_session: AsyncSession,
):
    db_session.add(_make_elevator("ELV-R06"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many(
        [
            _make_reading("ELV-R06", NOW - timedelta(minutes=20), torque=30.0, run_hours=1000.0),
            _make_reading("ELV-R06", NOW - timedelta(minutes=10), torque=50.0, run_hours=1100.0),
        ]
    )
    await db_session.flush()

    aggregates = await repo.aggregate_window(since=NOW - timedelta(hours=1), until=NOW)
    agg = aggregates["ELV-R06"]

    assert agg.load_torque_nm == 40.0
    assert agg.motor_run_hours_cumulative == 1100.0
    assert agg.reading_count == 2


@pytest.mark.asyncio
async def test_prune_removes_only_readings_outside_the_retained_band(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-R07"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many(
        [
            _make_reading("ELV-R07", NOW - timedelta(days=40)),
            _make_reading("ELV-R07", NOW - timedelta(days=1)),
        ]
    )
    await db_session.flush()

    deleted = await repo.prune(cutoff=NOW - timedelta(days=30), future_cutoff=NOW)
    await db_session.flush()

    assert deleted == 1
    remaining = await repo.list_for_elevator(
        "ELV-R07", since=NOW - timedelta(days=365), limit=10
    )
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_a_future_dated_reading_is_outside_the_window(db_session: AsyncSession):
    """Bounded at both ends.

    With a lower bound only, one future-dated row sits inside every subsequent
    window for ever, so the elevator never reads as stale — and the prune, which
    only deletes below its cutoff, never reaches it either.
    """
    db_session.add(_make_elevator("ELV-R08"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many([_make_reading("ELV-R08", datetime(2099, 1, 1, tzinfo=UTC))])
    await db_session.flush()

    aggregates = await repo.aggregate_window(since=NOW - timedelta(hours=1), until=NOW)
    assert "ELV-R08" not in aggregates


@pytest.mark.asyncio
async def test_prune_removes_future_dated_readings(db_session: AsyncSession):
    """Ingest validation rejects them now, but rows predating that validation
    would otherwise be permanently unreachable."""
    db_session.add(_make_elevator("ELV-R09"))
    await db_session.flush()

    repo = TelemetryRepository(db_session)
    await repo.create_many(
        [
            _make_reading("ELV-R09", datetime(2099, 1, 1, tzinfo=UTC)),
            _make_reading("ELV-R09", NOW - timedelta(hours=1)),
        ]
    )
    await db_session.flush()

    deleted = await repo.prune(cutoff=NOW - timedelta(days=30), future_cutoff=NOW)
    await db_session.flush()

    assert deleted == 1
    remaining = await repo.list_for_elevator(
        "ELV-R09", since=NOW - timedelta(days=365), limit=10
    )
    assert len(remaining) == 1
