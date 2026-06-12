from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator


class ElevatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Elevator]:
        result = await self._session.execute(
            select(Elevator).order_by(Elevator.risk_score.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, elevator_id: str) -> Elevator | None:
        result = await self._session.execute(
            select(Elevator).where(Elevator.id == elevator_id)
        )
        return result.scalar_one_or_none()
