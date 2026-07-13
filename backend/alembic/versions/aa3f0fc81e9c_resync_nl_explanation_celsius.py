"""resync elevators.nl_explanation to °C (follow-up to 56cd241fcfd6)

Revision ID: aa3f0fc81e9c
Revises: 56cd241fcfd6
Create Date: 2026-07-13 00:00:00.000000

Follow-up data migration. The previous celsius resync (56cd241fcfd6) converted the two
temperature feature `value` strings to °C but did not touch `elevators.nl_explanation`,
which embeds the same values — so the "Model explanation" panel kept showing Kelvin while
the drivers and briefing showed °C. Since 56cd241fcfd6 has already run in production, it
cannot be edited; this new revision applies the missing nl_explanation resync.

UPDATE each elevator's nl_explanation from predictions.json, by primary key (no feature
rows or visit_reports touched). Safe on an empty table: every UPDATE matches nothing and
seed_database() fills it on startup.
"""
from __future__ import annotations

import json
import pathlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import column, table

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'aa3f0fc81e9c'
down_revision: Union[str, None] = '56cd241fcfd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREDICTIONS_PATH = pathlib.Path(__file__).resolve().parents[2] / "ml" / "predictions.json"

elevators_t = table(
    "elevators",
    column("id", sa.String),
    column("nl_explanation", sa.String),
)


def upgrade() -> None:
    if not _PREDICTIONS_PATH.exists():
        print(f"WARNING: {_PREDICTIONS_PATH} not found; skipping nl_explanation resync")
        return

    predictions: list[dict] = json.loads(_PREDICTIONS_PATH.read_text(encoding="utf-8"))
    bind = op.get_bind()
    for pred in predictions:
        # nl_explanation is empty for out-of-scope elevators (raw_score is None).
        nl = pred["nl_explanation"] if pred["risk_score"] is not None else ""
        bind.execute(
            elevators_t.update().where(elevators_t.c.id == pred["id"]).values(nl_explanation=nl)
        )


def downgrade() -> None:
    # Irreversible by design: the pre-migration K-formatted explanations are not recoverable.
    pass
