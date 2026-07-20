"""add direction column to elevator_features and backfill from predictions.json

Revision ID: 97f03bcd4e85
Revises: 2c43876e02dd
Create Date: 2026-07-13 00:00:00.000000

Schema + data migration. Adds `elevator_features.direction` (the SHAP sign: "increases"
raises risk / "decreases" is protective) and backfills every feature row from the
regenerated backend/ml/predictions.json.

The column is added NOT NULL with a temporary server_default so it succeeds on existing
rows; those rows are then deleted and reinserted per elevator (in place, by elevator PK,
so the visit_reports ON DELETE CASCADE never fires), and finally the server_default is
dropped to match the ORM (which declares the column with no default). Safe on an empty
table: the reinsert loop matches nothing and seed_database() populates it on startup.
"""
from __future__ import annotations

import json
import pathlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import column, table

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '97f03bcd4e85'
down_revision: Union[str, None] = '2c43876e02dd'
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

elevators_t = table(
    "elevators",
    column("id", sa.String),
)


def upgrade() -> None:
    op.add_column(
        "elevator_features",
        sa.Column("direction", sa.String(), nullable=False, server_default="increases"),
    )

    if _PREDICTIONS_PATH.exists():
        predictions: list[dict] = json.loads(_PREDICTIONS_PATH.read_text(encoding="utf-8"))
        bind = op.get_bind()
        # Only backfill features for elevators that already exist. On a fresh/empty database
        # there are none yet, so this is a no-op and seed_database() inserts features (with
        # direction) at backend startup; touching them here would violate the FK.
        existing_ids = {row[0] for row in bind.execute(sa.select(elevators_t.c.id)).fetchall()}
        for pred in predictions:
            eid = pred["id"]
            if eid not in existing_ids:
                continue
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
    else:
        print(f"WARNING: {_PREDICTIONS_PATH} not found; direction backfilled with server_default only")

    # Drop the temporary default now that every row carries a real direction.
    op.alter_column("elevator_features", "direction", server_default=None)


def downgrade() -> None:
    op.drop_column("elevator_features", "direction")
