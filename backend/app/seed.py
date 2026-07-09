import json
import pathlib
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint

_PREDICTIONS_PATH = pathlib.Path(__file__).parent.parent / "ml" / "predictions.json"
_PREDICTIONS: dict[str, dict] = {}


def _load_predictions() -> None:
    global _PREDICTIONS
    if _PREDICTIONS:
        return
    with open(_PREDICTIONS_PATH, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    _PREDICTIONS = {item["id"]: item for item in data}


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _build_elevators() -> list[Elevator]:
    _load_predictions()
    elevators: list[Elevator] = []

    for pred in _PREDICTIONS.values():
        eid = pred["id"]
        raw_score = pred["risk_score"]
        in_scope = pred["in_model_scope"]

        # Out-of-scope elevators are never run through the model: null risk fields and
        # no trend history. Showing a flat 6-point trend of zeros would be misleading
        # (absence of data, not data that happens to be zero), so we leave it empty.
        if raw_score is None:
            risk_score = 0.0
            risk_level = "low"
            nl_explanation = ""
            trend_points: list[ElevatorTrendPoint] = []
        else:
            risk_score = float(raw_score)
            risk_level = pred["risk_level"]
            nl_explanation = pred["nl_explanation"]
            trend_points = [
                ElevatorTrendPoint(day_index=j, score=s)
                for j, s in enumerate(pred["trend"])
            ]

        # Out-of-scope entries provide features=[], so this naturally yields no rows.
        features = [
            ElevatorFeature(name=f["name"], impact=f["impact"], value=f["value"])
            for f in pred["features"]
        ]

        elevators.append(Elevator(
            id=eid,
            building_name=pred["building_name"],
            building_type=pred["building_type"],
            floor_count=pred["floor_count"],
            model=pred["model"],
            brand=pred["brand"],
            age_years=pred["age_years"],
            risk_score=risk_score,
            risk_level=risk_level,
            last_visit_date=pred["last_visit_date"],
            last_visit_technician=pred["last_visit_technician"],
            last_visit_notes=pred["last_visit_notes"],
            nl_explanation=nl_explanation,
            in_model_scope=in_scope,
            hourly_trips_avg=pred["hourly_trips_avg"],
            zone=pred["zone"],
            features=features,
            trend_points=trend_points,
        ))

    return sorted(elevators, key=lambda e: e.risk_score, reverse=True)


async def seed_database(session: AsyncSession) -> None:
    count = (await session.execute(select(func.count()).select_from(Elevator))).scalar_one()
    if count > 0:
        return

    for elevator in _build_elevators():
        session.add(elevator)
    await session.flush()
