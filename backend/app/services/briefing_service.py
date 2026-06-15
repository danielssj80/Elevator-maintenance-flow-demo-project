import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.models.elevator import Elevator
from app.repositories.elevator_repository import ElevatorRepository
from app.schemas.briefing import BriefingSchema
from app.services.bedrock_client import BedrockClient
from app.services.elevator_service import _derive_risk_level

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a field-service assistant. Write a concise spoken pre-visit briefing of 4-8 sentences "
    "for a lift technician about to visit a unit. Use plain language. "
    "Ground your briefing ONLY in the facts supplied — never invent numbers or events. "
    "End with one or two concrete, actionable recommendations. "
    "Do NOT repeat the elevator id mechanically in every sentence."
)

_CACHE: dict[tuple[str, float], str] = {}


def _trend_direction(trend: list[float]) -> str:
    if len(trend) < 2:
        return "stable"
    delta = trend[-1] - trend[0]
    if delta > 0.05:
        return "rising"
    if delta < -0.05:
        return "falling"
    return "stable"


def _days_since(date_str: str) -> int:
    try:
        last = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (datetime.now(timezone.utc).date() - last).days
    except (ValueError, TypeError):
        return 0


def _build_fallback_briefing(elevator: Elevator) -> str:
    risk_level = _derive_risk_level(elevator.risk_score)
    days = _days_since(elevator.last_visit_date)

    if not elevator.in_model_scope:
        return (
            f"Unit {elevator.id} at {elevator.building_name} is outside model scope — "
            "no model prediction is available for this unit. "
            f"Last visited {days} day(s) ago by {elevator.last_visit_technician}. "
            f"Refer to the last-visit notes for context: {elevator.last_visit_notes}. "
            "Carry out a visual inspection and update the visit report after your visit."
        )

    features = sorted(elevator.features, key=lambda f: f.impact, reverse=True)
    driver_names = ", ".join(f.name for f in features[:2]) if features else "unknown factors"

    trend_points = sorted(elevator.trend_points, key=lambda tp: tp.day_index)
    trend_scores = [tp.score for tp in trend_points]
    direction = _trend_direction(trend_scores)

    return (
        f"Unit {elevator.id} at {elevator.building_name} is at {risk_level} risk "
        f"(score {elevator.risk_score:.2f}). "
        f"Main drivers are {driver_names}. "
        f"Risk is {direction} over the last 6 days. "
        f"Last visited {days} day(s) ago by {elevator.last_visit_technician}. "
        f"Recommend scheduling maintenance and inspecting the top-contributing components. "
        f"Update the visit report after your inspection."
    )


def _build_prompt_message(elevator: Elevator) -> str:
    trend_points = sorted(elevator.trend_points, key=lambda tp: tp.day_index)
    trend_scores = [tp.score for tp in trend_points]
    direction = _trend_direction(trend_scores)
    days = _days_since(elevator.last_visit_date)
    risk_level = _derive_risk_level(elevator.risk_score)

    features_text = "; ".join(
        f"{f.name} (impact {f.impact:.2f}, value: {f.value})"
        for f in sorted(elevator.features, key=lambda f: f.impact, reverse=True)
    )

    scope_note = "" if elevator.in_model_scope else "NOTE: This unit is outside model scope — state that no prediction is available and refer to last-visit notes."

    return (
        f"Elevator: {elevator.id}\n"
        f"Building: {elevator.building_name} ({elevator.building_type})\n"
        f"Risk level: {risk_level} (score: {elevator.risk_score:.2f})\n"
        f"Top prediction drivers: {features_text}\n"
        f"6-day risk trend: {direction} ({', '.join(f'{s:.2f}' for s in trend_scores)})\n"
        f"Last visit: {days} day(s) ago by {elevator.last_visit_technician}\n"
        f"Last visit notes: {elevator.last_visit_notes}\n"
        f"Model explanation: {elevator.nl_explanation}\n"
        f"{scope_note}"
    ).strip()


class BriefingService:
    def __init__(
        self,
        elevator_repository: ElevatorRepository,
        bedrock_client: Any,
    ) -> None:
        self._elev_repo = elevator_repository
        self._client = bedrock_client

    async def get_briefing(self, elevator_id: str) -> BriefingSchema:
        elevator = await self._elev_repo.get_by_id(elevator_id)
        if elevator is None:
            raise HTTPException(status_code=404, detail="Elevator not found")

        cache_key = (elevator_id, elevator.risk_score)
        if cache_key in _CACHE:
            return BriefingSchema(
                elevator_id=elevator_id,
                text=_CACHE[cache_key],
                source="bedrock",
                generated_at=datetime.now(timezone.utc),
            )

        try:
            text = self._client.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_message=_build_prompt_message(elevator),
            )
            if not text or not text.strip():
                raise ValueError("Bedrock returned empty briefing text")
            _CACHE[cache_key] = text
            source = "bedrock"
        except Exception:
            logger.warning(
                "Bedrock briefing generation failed for %s; using deterministic fallback",
                elevator_id,
                exc_info=True,
            )
            text = _build_fallback_briefing(elevator)
            source = "fallback"

        return BriefingSchema(
            elevator_id=elevator_id,
            text=text,
            source=source,
            generated_at=datetime.now(timezone.utc),
        )
