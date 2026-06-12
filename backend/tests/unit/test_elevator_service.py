from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.models.visit_report import VisitReport
from app.schemas.visit_report import PostVisitReportSchema
from app.services.elevator_service import ElevatorService


def _make_orm_elevator(
    id: str = "ELV-001",
    risk_score: float = 0.9,
    stored_risk_level: str = "high",
) -> Elevator:
    e = Elevator(
        id=id,
        building_name="Test",
        building_type="office",
        floor_count=5,
        model="Model",
        brand="own",
        age_years=2,
        risk_score=risk_score,
        risk_level=stored_risk_level,
        last_visit_date="2026-01-01",
        last_visit_technician="Ana",
        last_visit_notes="ok",
        nl_explanation="fine",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
    )
    e.features = [
        ElevatorFeature(name="Vibration", impact=0.5, value="1x"),
        ElevatorFeature(name="Temperature", impact=0.3, value="normal"),
        ElevatorFeature(name="Motor", impact=0.2, value="ok"),
    ]
    e.trend_points = [ElevatorTrendPoint(day_index=i, score=risk_score) for i in range(6)]
    return e


def _make_service(elevators: list[Elevator] | None = None, single: Elevator | None = None):
    elev_repo = AsyncMock()
    report_repo = AsyncMock()
    elev_repo.list_all.return_value = elevators or []
    elev_repo.get_by_id.return_value = single
    report_repo.create.return_value = MagicMock(spec=VisitReport)
    return ElevatorService(elevator_repository=elev_repo, visit_report_repository=report_repo)


# --- list ---

@pytest.mark.asyncio
async def test_list_returns_summary_schemas():
    service = _make_service(elevators=[_make_orm_elevator()])
    result = await service.list_elevators()
    assert len(result) == 1
    assert result[0].id == "ELV-001"


# --- detail ---

@pytest.mark.asyncio
async def test_get_by_id_returns_detail_schema():
    service = _make_service(single=_make_orm_elevator())
    result = await service.get_elevator("ELV-001")
    assert result.id == "ELV-001"
    assert len(result.features) == 3
    assert len(result.trend) == 6


@pytest.mark.asyncio
async def test_get_by_id_raises_404_when_not_found():
    service = _make_service(single=None)
    with pytest.raises(HTTPException) as exc:
        await service.get_elevator("UNKNOWN")
    assert exc.value.status_code == 404


# --- risk_level derivation ---

@pytest.mark.asyncio
async def test_risk_level_high_above_080():
    elev = _make_orm_elevator(risk_score=0.85, stored_risk_level="low")  # stored is wrong
    service = _make_service(single=elev)
    result = await service.get_elevator("ELV-001")
    assert result.risk_level == "high"


@pytest.mark.asyncio
async def test_risk_level_medium_between_050_and_080():
    elev = _make_orm_elevator(risk_score=0.65, stored_risk_level="high")
    service = _make_service(single=elev)
    result = await service.get_elevator("ELV-001")
    assert result.risk_level == "medium"


@pytest.mark.asyncio
async def test_risk_level_low_below_050():
    elev = _make_orm_elevator(risk_score=0.3, stored_risk_level="high")
    service = _make_service(single=elev)
    result = await service.get_elevator("ELV-001")
    assert result.risk_level == "low"


# --- report ---

@pytest.mark.asyncio
async def test_submit_report_returns_response():
    service = _make_service(single=_make_orm_elevator())
    payload = PostVisitReportSchema(
        technician_name="Carlos",
        visit_date="2026-06-11",
        failure_found=False,
    )
    result = await service.submit_report("ELV-001", payload)
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_submit_report_raises_404_for_unknown_elevator():
    service = _make_service(single=None)
    payload = PostVisitReportSchema(
        technician_name="Carlos",
        visit_date="2026-06-11",
        failure_found=False,
    )
    with pytest.raises(HTTPException) as exc:
        await service.submit_report("UNKNOWN", payload)
    assert exc.value.status_code == 404
