"""HTTP-layer coverage for the three new endpoints.

Their status codes rested on the manual endpoint report alone, which is a
document rather than a guard: nothing would have caught a regression from 201
to 200, or a 422 quietly becoming a 500.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.routers.inference import get_inference_service
from app.services.inference_client import InferenceClient
from app.services.inference_service import InferenceService


def _elevator(id: str) -> Elevator:
    return Elevator(
        id=id,
        building_name="Test Building",
        building_type="office",
        floor_count=5,
        model="Test Model",
        brand="own",
        age_years=3,
        risk_score=0.4,
        risk_level="low",
        last_visit_date="2026-01-01",
        last_visit_technician="Ana",
        last_visit_notes="ok",
        nl_explanation="seeded",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
        features=[ElevatorFeature(name="Seeded", impact=1.0, value="x", direction="increases")],
        trend_points=[ElevatorTrendPoint(day_index=i, score=0.1) for i in range(6)],
    )


def _reading_payload(elevator_id: str, **overrides) -> dict:
    payload = {
        "elevator_id": elevator_id,
        "recorded_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        "ambient_temperature_c": 27.0,
        "motor_temperature_c": 37.0,
        "motor_speed_rpm": 1500.0,
        "load_torque_nm": 40.0,
        "motor_run_hours_cumulative": 12000.0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_ingest_returns_201_with_a_batch_id(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_elevator("ELV-H01"))
    await db_session.flush()

    response = await client.post(
        "/api/telemetry/readings",
        json={"source": "test", "readings": [_reading_payload("ELV-H01")]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] == 1
    assert body["rejected_elevator_ids"] == []
    assert body["batch_id"]


@pytest.mark.asyncio
async def test_ingest_reports_unknown_ids_without_losing_the_batch(
    client: AsyncClient, db_session: AsyncSession
):
    db_session.add(_elevator("ELV-H02"))
    await db_session.flush()

    response = await client.post(
        "/api/telemetry/readings",
        json={
            "source": "test",
            "readings": [_reading_payload("ELV-H02"), _reading_payload("ELV-GONE")],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] == 1
    assert body["rejected_elevator_ids"] == ["ELV-GONE"]


@pytest.mark.asyncio
async def test_ingest_returns_422_when_no_reading_is_valid(client: AsyncClient):
    response = await client.post(
        "/api/telemetry/readings",
        json={"source": "test", "readings": [_reading_payload("ELV-NOBODY")]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_an_implausible_temperature(
    client: AsyncClient, db_session: AsyncSession
):
    db_session.add(_elevator("ELV-H03"))
    await db_session.flush()

    response = await client.post(
        "/api/telemetry/readings",
        json={
            "source": "test",
            "readings": [_reading_payload("ELV-H03", ambient_temperature_c=-400.0)],
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_a_kelvin_value_submitted_as_celsius(
    client: AsyncClient, db_session: AsyncSession
):
    """The unit mix-up caught at the door rather than three layers down."""
    db_session.add(_elevator("ELV-H04"))
    await db_session.flush()

    response = await client.post(
        "/api/telemetry/readings",
        json={
            "source": "test",
            "readings": [_reading_payload("ELV-H04", ambient_temperature_c=300.15)],
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_a_future_reading(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_elevator("ELV-H05"))
    await db_session.flush()

    response = await client.post(
        "/api/telemetry/readings",
        json={
            "source": "test",
            "readings": [
                _reading_payload(
                    "ELV-H05",
                    recorded_at=(datetime.now(UTC) + timedelta(days=365)).isoformat(),
                )
            ],
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_readings_returns_200_and_an_empty_list_for_an_unknown_elevator(
    client: AsyncClient,
):
    response = await client.get("/api/telemetry/readings?elevator_id=ELV-NOBODY")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_readings_returns_what_was_ingested(
    client: AsyncClient, db_session: AsyncSession
):
    db_session.add(_elevator("ELV-H06"))
    await db_session.flush()
    await client.post(
        "/api/telemetry/readings",
        json={"source": "test", "readings": [_reading_payload("ELV-H06")]},
    )

    response = await client.get("/api/telemetry/readings?elevator_id=ELV-H06")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ambient_temperature_c"] == 27.0
    assert body[0]["source"] == "test"


@pytest.mark.asyncio
async def test_inference_run_returns_503_when_the_scorer_is_unreachable(
    client: AsyncClient, db_session: AsyncSession
):
    """503 through the router, not just from the client in isolation.

    The scorer is pointed at a closed port explicitly. Relying on it merely
    being absent does not work: the test container runs on the compose network
    and reaches the real inference service, so the first version of this test
    got a 200 with a real model_version. An integration test that passes or
    fails depending on whether a container happens to be up is worse than no
    test.
    """
    db_session.add(_elevator("ELV-H07"))
    await db_session.flush()
    await client.post(
        "/api/telemetry/readings",
        json={"source": "test", "readings": [_reading_payload("ELV-H07")]},
    )

    def _unreachable_service(db=None) -> InferenceService:
        return InferenceService(
            session=db_session,
            elevator_repository=ElevatorRepository(db_session),
            telemetry_repository=TelemetryRepository(db_session),
            # Nothing listens here, and nothing is supposed to.
            inference_client=InferenceClient(base_url="http://127.0.0.1:1"),
        )

    app.dependency_overrides[get_inference_service] = _unreachable_service
    try:
        response = await client.post("/api/inference/run")
    finally:
        app.dependency_overrides.pop(get_inference_service, None)

    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "Inference service is unavailable"}


@pytest.mark.asyncio
async def test_inference_run_returns_200_when_there_is_nothing_to_score(client: AsyncClient):
    """An empty run is a successful run, not an error — and it must not need
    the scorer to say so."""
    response = await client.post("/api/inference/run")

    assert response.status_code == 200
    body = response.json()
    assert body["scored"] == 0
    assert body["model_version"] is None


@pytest.mark.asyncio
async def test_a_broken_conversion_returns_a_described_500_not_a_traceback(
    client: AsyncClient, db_session: AsyncSession
):
    """docs/backend-standards.md names 500-with-traceback as the thing not to do.

    The scorer is stubbed rather than left to chance. `run()` fetches the
    booster's column order over the network *before* it validates the rows it
    already holds, so with no scorer reachable this returns 503 and never
    reaches the guard under test. Locally the test container can reach the live
    inference service and it returned 500; in CI, where nothing is listening, it
    returned 503. A test whose outcome depends on whether a container happens to
    be running is not a test.

    The row is inserted through the model rather than the API because ingest
    validation now refuses it — which is the point: this is the second line of
    defence, for a row that arrived some other way.
    """
    from app.models.telemetry import TelemetryReading

    db_session.add(_elevator("ELV-H08"))
    await db_session.flush()
    db_session.add(
        TelemetryReading(
            elevator_id="ELV-H08",
            recorded_at=datetime.now(UTC) - timedelta(minutes=5),
            ingested_at=datetime.now(UTC),
            ambient_temperature_c=-400.0,
            motor_temperature_c=-400.0,
            motor_speed_rpm=1500.0,
            load_torque_nm=40.0,
            motor_run_hours_cumulative=12000.0,
            source="direct-insert",
            batch_id="b1",
            trace_id=None,
        )
    )
    await db_session.flush()

    class _StubClient:
        """Answers the column-order call so the run reaches the band check."""

        async def feature_names(self):
            return [
                "Air_temperature__K",
                "Process_temperature__K",
                "Rotational_speed__rpm",
                "Torque__Nm",
                "Tool_wear__min",
                "Type_L",
                "Type_M",
            ]

        async def score(self, feature_names, rows):  # pragma: no cover - must not run
            raise AssertionError("the run must abort before scoring")

    def _stubbed_service(db=None) -> InferenceService:
        return InferenceService(
            session=db_session,
            elevator_repository=ElevatorRepository(db_session),
            telemetry_repository=TelemetryRepository(db_session),
            inference_client=_StubClient(),
        )

    app.dependency_overrides[get_inference_service] = _stubbed_service
    try:
        response = await client.post("/api/inference/run")
    finally:
        app.dependency_overrides.pop(get_inference_service, None)

    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert "every row" in detail
    assert "Traceback" not in detail


@pytest.mark.asyncio
async def test_the_read_endpoint_hides_readings_the_inference_window_refuses(
    client: AsyncClient, db_session: AsyncSession
):
    """The two must agree about what telemetry exists.

    The upper bound on `list_for_elevator` shipped with no caller and then with
    no test: mutating it away left the suite green. If the read endpoint reports
    a reading the run will not consider, an operator debugging a skipped
    elevator sees data that the scorer does not.

    Inserted through the model because ingest validation refuses a future
    timestamp — which is the point: this is the second line of defence.
    """
    from app.models.telemetry import TelemetryReading

    db_session.add(_elevator("ELV-H09"))
    await db_session.flush()
    db_session.add(
        TelemetryReading(
            elevator_id="ELV-H09",
            recorded_at=datetime.now(UTC) + timedelta(days=365),
            ingested_at=datetime.now(UTC),
            ambient_temperature_c=27.0,
            motor_temperature_c=37.0,
            motor_speed_rpm=1500.0,
            load_torque_nm=40.0,
            motor_run_hours_cumulative=12000.0,
            source="direct-insert",
            batch_id="b1",
            trace_id=None,
        )
    )
    await db_session.flush()

    response = await client.get("/api/telemetry/readings?elevator_id=ELV-H09&hours=2160")

    assert response.status_code == 200
    assert response.json() == [], "a future-dated reading must not be reported as present"
