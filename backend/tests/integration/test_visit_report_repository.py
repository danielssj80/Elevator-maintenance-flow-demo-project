import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.models.visit_report import VisitReport
from app.repositories.visit_report_repository import VisitReportRepository


@pytest.fixture
async def seeded_elevator(db_session: AsyncSession) -> Elevator:
    elevator = Elevator(
        id="ELV-VR01",
        building_name="Test",
        building_type="office",
        floor_count=3,
        model="Model X",
        brand="own",
        age_years=1,
        risk_score=0.4,
        risk_level="low",
        last_visit_date="2026-01-01",
        last_visit_technician="Carlos",
        last_visit_notes="ok",
        nl_explanation="all good",
        in_model_scope=True,
        hourly_trips_avg=5,
        zone="Madrid",
        features=[
            ElevatorFeature(name="Vibration", impact=0.5, value="1x", direction="increases"),
            ElevatorFeature(name="Temperature", impact=0.3, value="normal", direction="increases"),
            ElevatorFeature(name="Motor", impact=0.2, value="ok", direction="increases"),
        ],
        trend_points=[ElevatorTrendPoint(day_index=i, score=0.4) for i in range(6)],
    )
    db_session.add(elevator)
    await db_session.flush()
    return elevator


@pytest.mark.asyncio
async def test_create_persists_report(db_session: AsyncSession, seeded_elevator: Elevator):
    repo = VisitReportRepository(db_session)
    report = await repo.create(
        VisitReport(
            elevator_id=seeded_elevator.id,
            technician_name="Ana García",
            visit_date="2026-06-11",
            failure_found=False,
            components_replaced=[],
            parameters_corrected=[],
            notes="looks fine",
        )
    )

    assert report.id is not None
    assert report.elevator_id == seeded_elevator.id
    assert report.technician_name == "Ana García"
    assert report.created_at is not None
