from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visit_report import VisitReport


class VisitReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, report: VisitReport) -> VisitReport:
        self._session.add(report)
        await self._session.flush()
        await self._session.refresh(report)
        return report
