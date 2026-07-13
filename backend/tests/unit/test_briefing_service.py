from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.schemas.briefing import BriefingSchema


@pytest.fixture(autouse=True)
def _clear_briefing_cache():
    """Reset the process-local briefing cache so tests do not couple through it."""
    from app.services import briefing_service

    briefing_service._CACHE.clear()
    yield
    briefing_service._CACHE.clear()


def _make_orm_elevator(
    id: str = "ELV-001",
    risk_score: float = 0.85,
    in_model_scope: bool = True,
    last_visit_date: str = "2026-01-01",
    last_visit_notes: str = "Vibration noted",
) -> Elevator:
    e = Elevator(
        id=id,
        building_name="Edificio Central",
        building_type="office",
        floor_count=10,
        model="Model X",
        brand="Otis",
        age_years=8,
        risk_score=risk_score,
        risk_level="high",
        last_visit_date=last_visit_date,
        last_visit_technician="Ana",
        last_visit_notes=last_visit_notes,
        nl_explanation="High vibration detected in motor.",
        in_model_scope=in_model_scope,
        hourly_trips_avg=15,
        zone="Madrid",
    )
    e.features = [
        ElevatorFeature(name="Vibration", impact=0.6, value="2.1x", direction="increases"),
        ElevatorFeature(name="Temperature", impact=0.25, value="high", direction="increases"),
        ElevatorFeature(name="Motor wear", impact=0.15, value="elevated", direction="increases"),
    ]
    e.trend_points = [ElevatorTrendPoint(day_index=i, score=0.7 + i * 0.03) for i in range(6)]
    return e


# ---------------------------------------------------------------------------
# 3.1 Fallback builder for in-scope unit
# ---------------------------------------------------------------------------

def test_fallback_builder_references_risk_level():
    from app.services.briefing_service import _build_fallback_briefing

    elevator = _make_orm_elevator(risk_score=0.85)
    text = _build_fallback_briefing(elevator)

    assert "high" in text.lower()


def test_fallback_builder_references_drivers():
    from app.services.briefing_service import _build_fallback_briefing

    elevator = _make_orm_elevator()
    text = _build_fallback_briefing(elevator)

    assert "vibration" in text.lower() or "Vibration" in text


def test_fallback_builder_references_trend_direction():
    from app.services.briefing_service import _build_fallback_briefing

    elevator = _make_orm_elevator()
    text = _build_fallback_briefing(elevator)

    assert any(word in text.lower() for word in ["rising", "stable", "falling"])


def test_fallback_builder_contains_recommendation():
    from app.services.briefing_service import _build_fallback_briefing

    elevator = _make_orm_elevator()
    text = _build_fallback_briefing(elevator)

    assert any(word in text.lower() for word in ["recommend", "schedule", "priorit", "inspect", "check"])


# ---------------------------------------------------------------------------
# 3.3 Out-of-scope unit
# ---------------------------------------------------------------------------

def test_fallback_builder_out_of_scope_no_risk_invented():
    from app.services.briefing_service import _build_fallback_briefing

    elevator = _make_orm_elevator(in_model_scope=False, risk_score=0.0)
    text = _build_fallback_briefing(elevator)

    assert any(phrase in text.lower() for phrase in ["no model", "not in model", "no prediction", "outside"])


def test_fallback_builder_out_of_scope_references_last_visit():
    from app.services.briefing_service import _build_fallback_briefing

    elevator = _make_orm_elevator(in_model_scope=False, last_visit_notes="Cable tension normal")
    text = _build_fallback_briefing(elevator)

    assert any(phrase in text.lower() for phrase in ["last visit", "visit notes", "notes", "last-visit"])


# ---------------------------------------------------------------------------
# 4.1 Bedrock client (mocked boto3)
# ---------------------------------------------------------------------------

def test_bedrock_client_calls_converse_with_model_id():
    from app.services.bedrock_client import BedrockClient

    mock_boto_client = MagicMock()
    mock_boto_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "Briefing text here."}]}}
    }

    client = BedrockClient(boto_client=mock_boto_client, model_id="eu.amazon.nova-lite-v1:0")
    result = client.generate(system_prompt="Be concise.", user_message="Summarise unit ELV-001.")

    mock_boto_client.converse.assert_called_once()
    call_kwargs = mock_boto_client.converse.call_args.kwargs
    assert call_kwargs["modelId"] == "eu.amazon.nova-lite-v1:0"
    assert result == "Briefing text here."


def test_bedrock_client_returns_assistant_text():
    from app.services.bedrock_client import BedrockClient

    mock_boto_client = MagicMock()
    mock_boto_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "Unit is at high risk."}]}}
    }

    client = BedrockClient(boto_client=mock_boto_client, model_id="eu.amazon.nova-lite-v1:0")
    result = client.generate(system_prompt="s", user_message="u")

    assert result == "Unit is at high risk."


# ---------------------------------------------------------------------------
# 5.1-5.3 BriefingService
# ---------------------------------------------------------------------------

def _make_briefing_service(elevator=None, bedrock_text=None, bedrock_raises=None):
    from app.services.briefing_service import BriefingService

    elev_repo = AsyncMock()
    elev_repo.get_by_id.return_value = elevator

    mock_client = MagicMock()
    if bedrock_raises:
        mock_client.generate.side_effect = bedrock_raises
    else:
        mock_client.generate.return_value = bedrock_text or "Generated briefing."

    return BriefingService(elevator_repository=elev_repo, bedrock_client=mock_client)


@pytest.mark.asyncio
async def test_briefing_service_returns_bedrock_source_on_success():
    elevator = _make_orm_elevator()
    service = _make_briefing_service(elevator=elevator, bedrock_text="Detailed bedrock briefing.")

    result = await service.get_briefing("ELV-001")

    assert isinstance(result, BriefingSchema)
    assert result.source == "bedrock"
    assert result.text == "Detailed bedrock briefing."
    assert result.elevator_id == "ELV-001"


@pytest.mark.asyncio
async def test_briefing_service_falls_back_on_bedrock_error():
    elevator = _make_orm_elevator(id="ELV-002", risk_score=0.72)
    service = _make_briefing_service(elevator=elevator, bedrock_raises=Exception("Timeout"))

    result = await service.get_briefing("ELV-001")

    assert result.source == "fallback"
    assert len(result.text) > 0


@pytest.mark.asyncio
async def test_briefing_service_raises_404_for_unknown_elevator():
    service = _make_briefing_service(elevator=None)

    with pytest.raises(HTTPException) as exc:
        await service.get_briefing("UNKNOWN")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_briefing_service_falls_back_on_empty_bedrock_text():
    elevator = _make_orm_elevator(id="ELV-003", risk_score=0.66)
    service = _make_briefing_service(elevator=elevator, bedrock_text="   ")

    result = await service.get_briefing("ELV-003")

    assert result.source == "fallback"
    assert result.text.strip() != ""


@pytest.mark.asyncio
async def test_briefing_service_caches_and_does_not_reinvoke_client():
    from app.services.briefing_service import BriefingService

    elevator = _make_orm_elevator(id="ELV-010", risk_score=0.77)
    elev_repo = AsyncMock()
    elev_repo.get_by_id.return_value = elevator
    mock_client = MagicMock()
    mock_client.generate.return_value = "Cached briefing text."
    service = BriefingService(elevator_repository=elev_repo, bedrock_client=mock_client)

    first = await service.get_briefing("ELV-010")
    second = await service.get_briefing("ELV-010")

    assert first.text == second.text == "Cached briefing text."
    assert mock_client.generate.call_count == 1


def test_bedrock_client_uses_model_id_from_settings(monkeypatch):
    from app.core.config import settings
    from app.services.bedrock_client import BedrockClient

    monkeypatch.setattr(settings, "bedrock_model_id", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
    mock_boto_client = MagicMock()
    mock_boto_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "ok"}]}}
    }

    client = BedrockClient(boto_client=mock_boto_client)
    client.generate(system_prompt="s", user_message="u")

    assert mock_boto_client.converse.call_args.kwargs["modelId"] == (
        "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
