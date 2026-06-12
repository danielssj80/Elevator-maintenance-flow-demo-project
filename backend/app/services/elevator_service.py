from fastapi import HTTPException

from app.models.visit_report import VisitReport
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.visit_report_repository import VisitReportRepository
from app.schemas.elevator import ElevatorDetailSchema, ElevatorSummarySchema, FeatureSchema
from app.schemas.visit_report import PostVisitReportSchema, ReportResponseSchema


def _derive_risk_level(score: float) -> str:
    if score > 0.80:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


class ElevatorService:
    def __init__(
        self,
        elevator_repository: ElevatorRepository,
        visit_report_repository: VisitReportRepository,
    ) -> None:
        self._elev_repo = elevator_repository
        self._report_repo = visit_report_repository

    async def list_elevators(self) -> list[ElevatorSummarySchema]:
        elevators = await self._elev_repo.list_all()
        result = []
        for e in elevators:
            data = ElevatorSummarySchema.model_validate(e)
            data = data.model_copy(update={"risk_level": _derive_risk_level(e.risk_score)})
            result.append(data)
        return result

    async def get_elevator(self, elevator_id: str) -> ElevatorDetailSchema:
        elevator = await self._elev_repo.get_by_id(elevator_id)
        if elevator is None:
            raise HTTPException(status_code=404, detail="Elevator not found")

        trend = [tp.score for tp in sorted(elevator.trend_points, key=lambda tp: tp.day_index)]
        features = [FeatureSchema.model_validate(f) for f in elevator.features]

        return ElevatorDetailSchema(
            id=elevator.id,
            building_name=elevator.building_name,
            building_type=elevator.building_type,
            floor_count=elevator.floor_count,
            model=elevator.model,
            brand=elevator.brand,
            age_years=elevator.age_years,
            risk_score=elevator.risk_score,
            risk_level=_derive_risk_level(elevator.risk_score),
            last_visit_date=elevator.last_visit_date,
            last_visit_technician=elevator.last_visit_technician,
            last_visit_notes=elevator.last_visit_notes,
            nl_explanation=elevator.nl_explanation,
            in_model_scope=elevator.in_model_scope,
            hourly_trips_avg=elevator.hourly_trips_avg,
            zone=elevator.zone,
            trend=trend,
            features=features,
        )

    async def submit_report(
        self, elevator_id: str, payload: PostVisitReportSchema
    ) -> ReportResponseSchema:
        elevator = await self._elev_repo.get_by_id(elevator_id)
        if elevator is None:
            raise HTTPException(status_code=404, detail="Elevator not found")

        report = VisitReport(
            elevator_id=elevator_id,
            technician_name=payload.technician_name,
            visit_date=payload.visit_date,
            failure_found=payload.failure_found,
            components_replaced=payload.components_replaced,
            parameters_corrected=payload.parameters_corrected,
            notes=payload.notes,
        )
        await self._report_repo.create(report)

        return ReportResponseSchema(
            status="ok",
            message=f"Report for {elevator_id} received. Data queued for model retraining.",
        )
