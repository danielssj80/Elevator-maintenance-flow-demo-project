"""resync elevators from predictions.json (motor-life feature)

Revision ID: 2c43876e02dd
Revises: 0aac4958720e
Create Date: 2026-07-10 12:00:00.000000

Data migration, not a schema change. The motor-life-feature change regenerates
backend/ml/predictions.json (new "Motor useful life remaining" feature, per-typology
usage scaling, and a populated medium-risk tier). Because seed_database() only seeds an
empty table, environments whose Postgres volume persists across deploys (production, dev
EC2) would keep serving the previous predictions. This migration re-applies the
regenerated predictions to the existing rows.

Same in-place, PK-preserving strategy as revision 0aac4958720e: UPDATE each elevator by
primary key and fully replace its features/trend_points, rather than delete+reseed — so
the ON DELETE CASCADE from visit_reports to elevators.id never fires and any
(public, unauthenticated) post-visit report is preserved. Safe on an empty table too:
every UPDATE matches zero rows and seed_database() fills it on the next startup.
"""
from __future__ import annotations

import json
import pathlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import column, table

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c43876e02dd'
down_revision: Union[str, None] = '0aac4958720e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# backend/alembic/versions/<this file>.py -> parents[2] == backend/ (== /app in the image)
_PREDICTIONS_PATH = pathlib.Path(__file__).resolve().parents[2] / "ml" / "predictions.json"

elevators_t = table(
    "elevators",
    column("id", sa.String),
    column("building_name", sa.String),
    column("building_type", sa.String),
    column("floor_count", sa.Integer),
    column("model", sa.String),
    column("brand", sa.String),
    column("age_years", sa.Integer),
    column("risk_score", sa.Float),
    column("risk_level", sa.String),
    column("last_visit_date", sa.String),
    column("last_visit_technician", sa.String),
    column("last_visit_notes", sa.String),
    column("nl_explanation", sa.String),
    column("in_model_scope", sa.Boolean),
    column("hourly_trips_avg", sa.Integer),
    column("zone", sa.String),
)

features_t = table(
    "elevator_features",
    column("elevator_id", sa.String),
    column("name", sa.String),
    column("impact", sa.Float),
    column("value", sa.String),
)

trend_points_t = table(
    "elevator_trend_points",
    column("elevator_id", sa.String),
    column("day_index", sa.Integer),
    column("score", sa.Float),
)


def upgrade() -> None:
    if not _PREDICTIONS_PATH.exists():
        # Never true in a built image (Dockerfile copies ml/predictions.json), but guard
        # so a bare `alembic upgrade head` outside the image doesn't hard-fail.
        print(f"WARNING: {_PREDICTIONS_PATH} not found; skipping elevator resync")
        return

    predictions: list[dict] = json.loads(_PREDICTIONS_PATH.read_text(encoding="utf-8"))
    bind = op.get_bind()

    for pred in predictions:
        eid = pred["id"]
        raw_score = pred["risk_score"]

        if raw_score is None:
            risk_score, risk_level, nl_explanation = 0.0, "low", ""
            trend = []
        else:
            risk_score = float(raw_score)
            risk_level = pred["risk_level"]
            nl_explanation = pred["nl_explanation"]
            trend = pred["trend"]

        bind.execute(
            elevators_t.update().where(elevators_t.c.id == eid).values(
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
                in_model_scope=pred["in_model_scope"],
                hourly_trips_avg=pred["hourly_trips_avg"],
                zone=pred["zone"],
            )
        )

        # Full replace: features/trend_points hold only model-derived rows, never user data.
        bind.execute(features_t.delete().where(features_t.c.elevator_id == eid))
        bind.execute(trend_points_t.delete().where(trend_points_t.c.elevator_id == eid))

        if pred["features"]:
            bind.execute(
                features_t.insert(),
                [
                    {"elevator_id": eid, "name": f["name"], "impact": f["impact"], "value": f["value"]}
                    for f in pred["features"]
                ],
            )
        if trend:
            bind.execute(
                trend_points_t.insert(),
                [{"elevator_id": eid, "day_index": j, "score": s} for j, s in enumerate(trend)],
            )


def downgrade() -> None:
    # Irreversible by design: the pre-migration values are not recoverable from JSON.
    pass
