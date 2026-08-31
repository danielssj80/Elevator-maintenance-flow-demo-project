"""The shared secret on the two unauthenticated write endpoints.

The production gate stops these routers being registered at all when the
deployment environment is production. That says nothing about who may write in
the environments where they *are* registered, and the next change introduces
exactly such a producer — a scheduled n8n workflow posting telemetry and
triggering runs. This is the guard for those environments.

The suite runs with **no token configured**, so every other test keeps posting
without a header and the fail-open default is exercised by default. These tests
configure one explicitly, which is also the only shape in which a 401 can be
asserted at all.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.main import app
from app.models.elevator import Elevator
from app.models.telemetry import TelemetryReading

TOKEN = "a-local-development-token"
INGEST_PATH = "/api/telemetry/readings"
RUN_PATH = "/api/inference/run"


@pytest.fixture
def configured_token(monkeypatch) -> str:
    monkeypatch.setattr(settings, "telemetry_ingest_token", TOKEN)
    return TOKEN


@pytest.fixture
def no_configured_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "telemetry_ingest_token", None)


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
        nl_explanation="all good",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
    )


def _batch(elevator_id: str, recorded_at: str) -> dict:
    return {
        "source": "test",
        "readings": [
            {
                "elevator_id": elevator_id,
                "recorded_at": recorded_at,
                "ambient_temperature_c": 27.0,
                "motor_temperature_c": 37.0,
                "motor_speed_rpm": 1500.0,
                "load_torque_nm": 40.0,
                "motor_run_hours_cumulative": 12_000.0,
            }
        ],
    }


async def _reading_count(session: AsyncSession, elevator_id: str) -> int:
    result = await session.execute(
        select(func.count(TelemetryReading.id)).where(
            TelemetryReading.elevator_id == elevator_id
        )
    )
    return int(result.scalar_one())


def _now_iso() -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(minutes=5)).isoformat()


# ── Ingest ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_configured_token_is_accepted(
    client: AsyncClient, db_session: AsyncSession, configured_token: str
):
    db_session.add(_elevator("ELV-A01"))
    await db_session.flush()

    response = await client.post(
        INGEST_PATH,
        json=_batch("ELV-A01", _now_iso()),
        headers={"X-Ingest-Token": configured_token},
    )

    assert response.status_code == 201
    assert response.json()["accepted"] == 1


@pytest.mark.asyncio
async def test_a_request_with_no_token_is_rejected_and_stores_nothing(
    client: AsyncClient, db_session: AsyncSession, configured_token: str
):
    db_session.add(_elevator("ELV-A02"))
    await db_session.flush()

    response = await client.post(INGEST_PATH, json=_batch("ELV-A02", _now_iso()))

    assert response.status_code == 401
    assert await _reading_count(db_session, "ELV-A02") == 0


@pytest.mark.asyncio
async def test_a_request_with_the_wrong_token_is_rejected_and_stores_nothing(
    client: AsyncClient, db_session: AsyncSession, configured_token: str
):
    db_session.add(_elevator("ELV-A03"))
    await db_session.flush()

    response = await client.post(
        INGEST_PATH,
        json=_batch("ELV-A03", _now_iso()),
        headers={"X-Ingest-Token": "not-the-token"},
    )

    assert response.status_code == 401
    assert await _reading_count(db_session, "ELV-A03") == 0


@pytest.mark.asyncio
async def test_the_rejection_does_not_reveal_whether_a_token_was_sent(
    client: AsyncClient, db_session: AsyncSession, configured_token: str
):
    """Absent and wrong must be indistinguishable.

    A different body or status for the two would turn the endpoint into an
    oracle for whether a guard is configured at all.
    """
    db_session.add(_elevator("ELV-A04"))
    await db_session.flush()
    payload = _batch("ELV-A04", _now_iso())

    absent = await client.post(INGEST_PATH, json=payload)
    wrong = await client.post(
        INGEST_PATH, json=payload, headers={"X-Ingest-Token": "not-the-token"}
    )

    assert absent.status_code == wrong.status_code == 401
    assert absent.json() == wrong.json()


@pytest.mark.asyncio
async def test_a_prefix_of_the_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession, configured_token: str
):
    """A guard that compared prefixes, or truthiness, would pass everything above."""
    db_session.add(_elevator("ELV-A05"))
    await db_session.flush()

    response = await client.post(
        INGEST_PATH,
        json=_batch("ELV-A05", _now_iso()),
        headers={"X-Ingest-Token": configured_token[:-1]},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_unconfigured_token_leaves_ingest_open(
    client: AsyncClient, db_session: AsyncSession, no_configured_token: None
):
    """Fail-open, deliberately, and the other half of the mutation.

    A guard that rejected everything would pass every test above. This is what
    keeps a fresh checkout and a bare `uvicorn` run working — and why
    docker-compose.yml has to configure a token, which
    `test_dev_compose_configures_an_ingest_token` asserts separately.
    """
    db_session.add(_elevator("ELV-A06"))
    await db_session.flush()

    response = await client.post(INGEST_PATH, json=_batch("ELV-A06", _now_iso()))

    assert response.status_code == 201


# ── Inference trigger ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_inference_trigger_is_guarded_by_the_same_token(
    client: AsyncClient, configured_token: str
):
    response = await client.post(RUN_PATH)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_rejected_trigger_starts_no_run(
    client: AsyncClient, configured_token: str
):
    """The spec says "before any inference run is started", so assert that.

    The status code alone does not say it. An unguarded `POST /api/inference/run`
    against an empty test database answers **200**, not an error: there is no
    telemetry in the window, so every elevator is skipped and the run completes
    without ever calling the scorer. So 401-vs-200 is the only thing a status
    assertion distinguishes, and nothing would notice a guard that rejected the
    response *after* the run had already rewritten scores.

    A spy in place of the real service is what closes that. It records the call
    and returns nothing usable — reaching it at all is the failure.
    """
    from app.routers.inference import get_inference_service

    started = False

    class SpyInferenceService:
        async def run(self):
            nonlocal started
            started = True
            raise AssertionError("the run was started despite a rejected token")

    app.dependency_overrides[get_inference_service] = lambda: SpyInferenceService()
    try:
        response = await client.post(RUN_PATH)
    finally:
        app.dependency_overrides.pop(get_inference_service, None)

    assert response.status_code == 401
    assert started is False, "the guard resolved after the service, not before it"


# ── The startup warning ──────────────────────────────────────────────────────


def test_registering_the_routers_unguarded_logs_a_warning(caplog, no_configured_token):
    """Fail-open has to be audible.

    An environment that registers these routers without a token looks identical
    at runtime to one that configured it correctly. The startup line is what
    tells them apart in a log, and it is the reason the fail-open default is
    defensible at all.
    """
    from app.main import build_app

    with caplog.at_level("WARNING", logger="app.main"):
        build_app(environment="local")

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("TELEMETRY_INGEST_TOKEN" in message for message in warnings), warnings


def test_a_configured_token_logs_no_warning(caplog, configured_token):
    from app.main import build_app

    with caplog.at_level("WARNING", logger="app.main"):
        build_app(environment="local")

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert not any("TELEMETRY_INGEST_TOKEN" in message for message in warnings), warnings


def test_production_logs_no_warning_because_the_routers_are_absent(
    caplog, no_configured_token
):
    """Nothing is unguarded in production — the routes do not exist there.

    Warning anyway would train the reader to ignore the line in the one log
    where it would matter.
    """
    from app.main import build_app

    with caplog.at_level("WARNING", logger="app.main"):
        build_app(environment="production")

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert not any("TELEMETRY_INGEST_TOKEN" in message for message in warnings), warnings
