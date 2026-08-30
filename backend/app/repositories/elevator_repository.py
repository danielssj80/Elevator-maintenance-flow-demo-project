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

    async def filter_existing_ids(self, candidate_ids: set[str]) -> set[str]:
        """Return the subset of ``candidate_ids`` that exist.

        One round trip for a whole batch: telemetry ingest needs to know which
        of up to 1000 submitted elevator ids are real, and doing that per
        reading would be 1000 queries.
        """
        if not candidate_ids:
            return set()
        result = await self._session.execute(
            select(Elevator.id).where(Elevator.id.in_(candidate_ids))
        )
        return set(result.scalars().all())
