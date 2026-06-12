from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.visit_report_repository import VisitReportRepository
from app.schemas.elevator import ElevatorDetailSchema, ElevatorSummarySchema
from app.schemas.visit_report import PostVisitReportSchema, ReportResponseSchema
from app.services.elevator_service import ElevatorService

router = APIRouter(prefix="/api/elevators", tags=["elevators"])


def get_elevator_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ElevatorService:
    return ElevatorService(
        elevator_repository=ElevatorRepository(db),
        visit_report_repository=VisitReportRepository(db),
    )


@router.get("", response_model=list[ElevatorSummarySchema])
async def list_elevators(
    service: Annotated[ElevatorService, Depends(get_elevator_service)],
) -> list[ElevatorSummarySchema]:
    return await service.list_elevators()


@router.get("/{elevator_id}", response_model=ElevatorDetailSchema)
async def get_elevator(
    elevator_id: str,
    service: Annotated[ElevatorService, Depends(get_elevator_service)],
) -> ElevatorDetailSchema:
    return await service.get_elevator(elevator_id)


@router.post("/{elevator_id}/report", response_model=ReportResponseSchema, status_code=201)
async def submit_report(
    elevator_id: str,
    report: PostVisitReportSchema,
    service: Annotated[ElevatorService, Depends(get_elevator_service)],
) -> ReportResponseSchema:
    return await service.submit_report(elevator_id, report)
