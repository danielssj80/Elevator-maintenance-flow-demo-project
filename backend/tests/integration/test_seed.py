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


@pytest.mark.asyncio
async def test_seed_creates_3_features_per_elevator(db_session: AsyncSession):
    await seed_database(db_session)
    count = (await db_session.execute(select(func.count()).select_from(ElevatorFeature))).scalar_one()
    assert count == 300


@pytest.mark.asyncio
async def test_seed_creates_6_trend_points_per_elevator(db_session: AsyncSession):
    await seed_database(db_session)
    count = (await db_session.execute(select(func.count()).select_from(ElevatorTrendPoint))).scalar_one()
    assert count == 600


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession):
    await seed_database(db_session)
    await seed_database(db_session)
    count = (await db_session.execute(select(func.count()).select_from(Elevator))).scalar_one()
    assert count == 100
