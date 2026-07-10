"""resync elevators, features, trend points from predictions.json

Revision ID: 0aac4958720e
Revises: 638e311fa8e1
Create Date: 2026-07-10 00:00:00.000000

Data migration, not a schema change. `seed_database()` only seeds when the
`elevators` table is empty (`if count > 0: return`), so environments whose
Postgres volume persists across deploys (production, dev EC2) never picked
up backend/ml/predictions.json after the ml-offline-training change (#14) —
they kept serving whatever was seeded the first time the table was created,
before a real model existed.

This migration re-syncs the *existing* elevator rows in place, by primary
key, instead of deleting and letting seed_database() recreate them. That
matters because `elevators.id` has an `ON DELETE CASCADE` foreign key from
`visit_reports` — deleting and recreating elevator rows would silently wipe
any post-visit report a (public, unauthenticated) visitor already
submitted. Only `elevator_features` and `elevator_trend_points` are fully
replaced per elevator; they hold no independent user data.

Safe to run against an empty `elevators` table too: every UPDATE simply
matches zero rows, and the normal seed_database() path fills it in on the
next backend startup, same as always.
"""
from __future__ import annotations

import json
import pathlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import table, column

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0aac4958720e'
down_revision: Union[str, None] = '638e311fa8e1'
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
        # Never true in a built image (Dockerfile copies ml/predictions.json), but
        # guard so a bare `alembic upgrade head` outside the image doesn't hard-fail.
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

        # Full replace: features/trend_points hold only model-derived rows, never
        # user data, so it's safe to drop and reinsert rather than diff them.
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
    # Irreversible by design: the pre-migration values (whatever the first-ever
    # seed happened to write) aren't recoverable from predictions.json.
    pass
