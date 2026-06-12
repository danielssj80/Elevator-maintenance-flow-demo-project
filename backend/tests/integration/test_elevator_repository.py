import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.repositories.elevator_repository import ElevatorRepository


def _make_elevator(id: str, risk_score: float) -> Elevator:
    return Elevator(
        id=id,
        building_name="Test Building",
        building_type="office",
        floor_count=5,
        model="Test Model",
        brand="own",
        age_years=3,
        risk_score=risk_score,
        risk_level="low",
        last_visit_date="2026-01-01",
        last_visit_technician="Ana",
        last_visit_notes="ok",
        nl_explanation="all good",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
        features=[
            ElevatorFeature(name="Vibration", impact=0.5, value="1x"),
            ElevatorFeature(name="Temperature", impact=0.3, value="normal"),
            ElevatorFeature(name="Motor current", impact=0.2, value="ok"),
        ],
        trend_points=[ElevatorTrendPoint(day_index=i, score=0.2) for i in range(6)],
    )


@pytest.mark.asyncio
async def test_list_all_returns_elevators_sorted_by_risk_desc(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-T01", 0.9))
    db_session.add(_make_elevator("ELV-T02", 0.3))
    db_session.add(_make_elevator("ELV-T03", 0.6))
    await db_session.flush()

    repo = ElevatorRepository(db_session)
    results = await repo.list_all()

    scores = [e.risk_score for e in results]
    assert scores == sorted(scores, reverse=True)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_by_id_returns_elevator_with_features_and_trend(db_session: AsyncSession):
    db_session.add(_make_elevator("ELV-T04", 0.5))
    await db_session.flush()

    repo = ElevatorRepository(db_session)
    elevator = await repo.get_by_id("ELV-T04")

    assert elevator is not None
    assert len(elevator.features) == 3
    assert len(elevator.trend_points) == 6
    assert elevator.trend_points[0].day_index == 0
    assert elevator.trend_points[5].day_index == 5


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown(db_session: AsyncSession):
    repo = ElevatorRepository(db_session)
    result = await repo.get_by_id("DOES-NOT-EXIST")
    assert result is None
