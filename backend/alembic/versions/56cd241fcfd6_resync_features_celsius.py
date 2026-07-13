"""resync elevator_features from predictions.json (temperatures in °C)

Revision ID: 56cd241fcfd6
Revises: 97f03bcd4e85
Create Date: 2026-07-13 00:00:00.000000

Data migration (no schema change). The celsius-temperature-display change regenerates
backend/ml/predictions.json so the two temperature feature `value` strings read in °C
instead of K (e.g. "25°C (−2.0°C, within range)"). Since seed_database() only seeds an
empty table, environments whose Postgres volume persists (production, dev EC2) keep the
old K strings until re-applied here.

Same in-place, PK-preserving pattern as the previous feature resyncs: delete + reinsert
each elevator's feature rows from predictions.json (name/impact/value/direction), so the
visit_reports ON DELETE CASCADE never fires. Safe on an empty table (matches nothing;
seed_database() fills it on startup).
"""
from __future__ import annotations

import json
import pathlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import column, table

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '56cd241fcfd6'
down_revision: Union[str, None] = '97f03bcd4e85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREDICTIONS_PATH = pathlib.Path(__file__).resolve().parents[2] / "ml" / "predictions.json"

features_t = table(
    "elevator_features",
    column("elevator_id", sa.String),
    column("name", sa.String),
    column("impact", sa.Float),
    column("value", sa.String),
    column("direction", sa.String),
)


def upgrade() -> None:
    if not _PREDICTIONS_PATH.exists():
        print(f"WARNING: {_PREDICTIONS_PATH} not found; skipping feature resync")
        return

    predictions: list[dict] = json.loads(_PREDICTIONS_PATH.read_text(encoding="utf-8"))
    bind = op.get_bind()
    for pred in predictions:
        eid = pred["id"]
        bind.execute(features_t.delete().where(features_t.c.elevator_id == eid))
        if pred["features"]:
            bind.execute(
                features_t.insert(),
                [
                    {
                        "elevator_id": eid,
                        "name": f["name"],
                        "impact": f["impact"],
                        "value": f["value"],
                        "direction": f["direction"],
                    }
                    for f in pred["features"]
                ],
            )


def downgrade() -> None:
    # Irreversible by design: the pre-migration K-formatted strings are not recoverable
    # from the current predictions.json.
    pass
