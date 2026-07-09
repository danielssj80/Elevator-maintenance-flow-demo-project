import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.seed import seed_database


@pytest.mark.asyncio
async def test_seed_creates_100_elevators(db_session: AsyncSession):
    await seed_database(db_session)
    count = (await db_session.execute(select(func.count()).select_from(Elevator))).scalar_one()
    assert count == 100


async def _count_in_scope(db_session: AsyncSession) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(Elevator).where(Elevator.in_model_scope.is_(True))
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_seed_creates_3_features_per_in_scope_elevator(db_session: AsyncSession):
    await seed_database(db_session)
    # Since ml-offline-training, only in-scope elevators carry model features (3 each);
    # out-of-scope elevators have features=[]. Derive the expectation from the actual
    # in-scope count so this does not break if the fleet's scope split changes.
    features = (await db_session.execute(select(func.count()).select_from(ElevatorFeature))).scalar_one()
    assert features == await _count_in_scope(db_session) * 3


@pytest.mark.asyncio
async def test_seed_creates_6_trend_points_per_in_scope_elevator(db_session: AsyncSession):
    await seed_database(db_session)
    # Only in-scope elevators have a trend (6 points each); out-of-scope elevators have
    # no model output, hence no trend history. Derive from the actual in-scope count.
    trend_points = (await db_session.execute(select(func.count()).select_from(ElevatorTrendPoint))).scalar_one()
    assert trend_points == await _count_in_scope(db_session) * 6


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession):
    await seed_database(db_session)
    await seed_database(db_session)
    count = (await db_session.execute(select(func.count()).select_from(Elevator))).scalar_one()
    assert count == 100
