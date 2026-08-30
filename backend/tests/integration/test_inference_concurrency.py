"""The advisory lock, and rollback with real commit semantics.

Both of these were shipped without tests and caught by an independent review.
They need real sessions rather than the rolled-back `db_session` fixture: a
lock is only observable across two connections, and a rollback is only
observable if something could have been committed.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.models.telemetry import TelemetryReading
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.services.inference_service import (
    RUN_LOCK_KEY,
    FeatureBuildError,
    InferenceService,
)
from tests.conftest import TestSessionLocal

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

FEATURE_NAMES = [
    "Air_temperature__K",
    "Process_temperature__K",
    "Rotational_speed__rpm",
    "Torque__Nm",
    "Tool_wear__min",
    "Type_L",
    "Type_M",
]


def _elevator(id: str) -> Elevator:
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
        nl_explanation="seeded",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
        features=[ElevatorFeature(name="Seeded", impact=1.0, value="x", direction="increases")],
        trend_points=[ElevatorTrendPoint(day_index=i, score=0.1) for i in range(6)],
    )


def _reading(elevator_id: str) -> TelemetryReading:
    return TelemetryReading(
        elevator_id=elevator_id,
        recorded_at=NOW - timedelta(minutes=5),
        ingested_at=NOW,
        ambient_temperature_c=27.0,
        motor_temperature_c=37.0,
        motor_speed_rpm=1500.0,
        load_torque_nm=40.0,
        motor_run_hours_cumulative=12_000.0,
        source="test",
        batch_id="b1",
        trace_id=None,
    )


class _Client:
    """Scores the first elevator and then fails, so the failure lands mid-loop."""

    def __init__(self, fail_after: int | None = None) -> None:
        self._fail_after = fail_after

    async def feature_names(self) -> list[str]:
        return list(FEATURE_NAMES)

    async def score(self, feature_names, rows):
        contributions = []
        for i in range(len(rows)):
            if self._fail_after is not None and i >= self._fail_after:
                # All-zero: cannot be normalised, so _apply raises for this row
                # only — after the earlier rows have already been written.
                contributions.append([0.0] * len(feature_names))
            else:
                contributions.append([0.5, -0.4, 0.3, -0.2, 0.1, 0.05, -0.01])
        return [0.9] * len(rows), contributions, "model-abc"


def _service(session, client) -> InferenceService:
    return InferenceService(
        session=session,
        elevator_repository=ElevatorRepository(session),
        telemetry_repository=TelemetryRepository(session),
        inference_client=client,
    )


@pytest.mark.asyncio
async def test_a_run_holds_the_lock_against_another_connection(setup_test_db):
    """Two runs must not overlap.

    Without the lock both read `last_scored_at` before either commits, both
    conclude the elevator has not been scored today, and both shift the trend
    window — advancing one day twice and dropping the oldest real point.

    Driven through `run()`, not by calling `_acquire_run_lock()` directly. The
    first version of this test called the helper, so deleting the call from
    `run()` left it green: it proved the lock exists, not that the run takes it.
    That is the same toothless-guard mistake this change keeps finding, and it
    is only caught by mutating.

    Asserted with `pg_try_advisory_xact_lock`, which answers "could I take this
    lock?" without blocking. Waiting on the blocking form leaves the cancelled
    query's connection unusable and proves nothing.
    """
    async with TestSessionLocal() as holder:
        async with holder.begin():
            # The lock is taken at the top of the run and held for the whole
            # transaction, so it is still held here.
            await _service(holder, _Client()).run(now=NOW)

            async with TestSessionLocal() as contender:
                async with contender.begin():
                    got_it = await contender.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:key)"),
                        {"key": RUN_LOCK_KEY},
                    )

    assert got_it is False, "a second run could take the lock while one was in progress"


@pytest.mark.asyncio
async def test_the_lock_is_released_when_the_transaction_ends(setup_test_db):
    """Transaction-scoped, so there is no cleanup path to get wrong."""
    async with TestSessionLocal() as first:
        async with first.begin():
            await _service(first, _Client())._acquire_run_lock()

    async with TestSessionLocal() as second:
        async with second.begin():
            got_it = await second.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": RUN_LOCK_KEY}
            )

    assert got_it is True, "the lock outlived the transaction that took it"


@pytest.mark.asyncio
async def test_a_failure_after_the_first_elevator_commits_nothing(setup_test_db):
    """Real rollback, not the fixture's.

    The `db_session` fixture rolls back regardless, so it cannot tell a run that
    rolled back from one that was never committed. This drives its own session,
    lets the failure land on the *second* elevator so the first has already been
    written, and then checks a fresh session.
    """
    ids = ("ELV-X01", "ELV-X02")
    async with TestSessionLocal() as setup:
        async with setup.begin():
            for elevator_id in ids:
                setup.add(_elevator(elevator_id))
            await setup.flush()
            for elevator_id in ids:
                setup.add(_reading(elevator_id))

    try:
        async with TestSessionLocal() as session:
            with pytest.raises(FeatureBuildError):
                async with session.begin():
                    await _service(session, _Client(fail_after=1)).run(now=NOW)

        # A fresh session, so nothing is served from the identity map.
        async with TestSessionLocal() as check:
            result = await check.execute(select(Elevator).where(Elevator.id.in_(ids)))
            for elevator in result.scalars().all():
                assert elevator.last_scored_at is None, f"{elevator.id} was committed"
                assert elevator.risk_score == 0.4
                assert elevator.nl_explanation == "seeded"
    finally:
        async with TestSessionLocal() as cleanup:
            async with cleanup.begin():
                await cleanup.execute(
                    text("DELETE FROM elevators WHERE id = ANY(:ids)"), {"ids": list(ids)}
                )
