import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint


def _seed_elevator(id: str, risk_score: float) -> Elevator:
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
        trend_points=[ElevatorTrendPoint(day_index=i, score=risk_score) for i in range(6)],
    )


@pytest.mark.asyncio
async def test_list_elevators_returns_200(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_seed_elevator("ELV-R01", 0.8))
    db_session.add(_seed_elevator("ELV-R02", 0.4))
    await db_session.flush()

    response = await client.get("/api/elevators")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["risk_score"] >= data[1]["risk_score"]


@pytest.mark.asyncio
async def test_get_elevator_returns_200_with_contract(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_seed_elevator("ELV-R03", 0.7))
    await db_session.flush()

    response = await client.get("/api/elevators/ELV-R03")
    assert response.status_code == 200
    data = response.json()
    assert len(data["features"]) == 3
    assert len(data["trend"]) == 6
    assert data["trend"][5] == data["risk_score"]
    assert data["risk_level"] == "medium"


@pytest.mark.asyncio
async def test_get_elevator_returns_404_for_unknown(client: AsyncClient):
    response = await client.get("/api/elevators/DOES-NOT-EXIST")
    assert response.status_code == 404
    assert response.json() == {"detail": "Elevator not found"}


@pytest.mark.asyncio
async def test_submit_report_returns_201(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_seed_elevator("ELV-R04", 0.5))
    await db_session.flush()

    response = await client.post(
        "/api/elevators/ELV-R04/report",
        json={
            "technician_name": "Carlos",
            "visit_date": "2026-06-11",
            "failure_found": False,
            "notes": "all good",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_submit_report_returns_404_for_unknown_elevator(client: AsyncClient):
    response = await client.post(
        "/api/elevators/UNKNOWN/report",
        json={
            "technician_name": "Carlos",
            "visit_date": "2026-06-11",
            "failure_found": False,
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_submit_report_returns_422_for_invalid_body(client: AsyncClient):
    response = await client.post("/api/elevators/ELV-R04/report", json={})
    assert response.status_code == 422
