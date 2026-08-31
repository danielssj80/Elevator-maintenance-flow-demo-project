"""telemetry_readings unique identity

Revision ID: 7c1e4b9a2d33
Revises: 3d92a2ed3fb5
Create Date: 2026-08-31 09:12:04.118722

Gives a reading an identity — (elevator_id, recorded_at, source) — so that a
resubmitted batch cannot be stored twice. The inference run averages *rows*
over its window rather than distinct readings, so a batch present twice is
weighted twice and moves the resulting risk score with no error and no log
line, and the producer introduced by the next change retries a failed node by
re-sending the same payload.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e4b9a2d33'
down_revision: Union[str, None] = '3d92a2ed3fb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creating the constraint on a table that already holds duplicates fails,
    # so they go first, keeping the lowest id per identity — the row that was
    # stored first, which is the one ON CONFLICT DO NOTHING would have kept.
    #
    # A no-op on an empty table, which is what production has: the telemetry
    # routers are not registered when the deployment environment is production,
    # so nothing has ever written there. In development it deletes whatever a
    # manual re-POST left behind.
    op.execute(
        """
        DELETE FROM telemetry_readings a
        USING telemetry_readings b
        WHERE a.elevator_id = b.elevator_id
          AND a.recorded_at = b.recorded_at
          AND a.source      = b.source
          AND a.id > b.id
        """
    )
    op.create_unique_constraint(
        'uq_telemetry_readings_identity',
        'telemetry_readings',
        ['elevator_id', 'recorded_at', 'source'],
    )
    # Redundant from here on: the unique index leads with (elevator_id,
    # recorded_at), and PostgreSQL serves the DESC ordering from it by scanning
    # the btree backwards. Keeping it would pay a second index write on every
    # insert into the hottest table in the schema for no read benefit.
    # ix_telemetry_readings_recorded stays — it does not lead with elevator_id,
    # so nothing subsumes it.
    op.drop_index('ix_telemetry_readings_elevator_recorded', table_name='telemetry_readings')


def downgrade() -> None:
    """Restores the index and drops the constraint.

    It does NOT restore rows deleted by the upgrade. Those were duplicate
    observations of an identity that is still present, so nothing an inference
    run consumes is lost — but the deletion is one-way and this is the note
    saying so.
    """
    op.create_index(
        'ix_telemetry_readings_elevator_recorded',
        'telemetry_readings',
        ['elevator_id', sa.text('recorded_at DESC')],
        unique=False,
    )
    op.drop_constraint(
        'uq_telemetry_readings_identity', 'telemetry_readings', type_='unique'
    )
