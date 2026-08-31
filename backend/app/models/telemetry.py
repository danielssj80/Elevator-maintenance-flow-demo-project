"""Telemetry readings — the system of record for elevator sensor data.

Column groups, and why the split matters:

**Model inputs.** ``ambient_temperature_c``, ``motor_temperature_c``,
``motor_speed_rpm``, ``load_torque_nm`` and ``motor_run_hours_cumulative`` are
the only columns the trained booster consumes. They map onto AI4I's feature
space (``Air_temperature__K``, ``Process_temperature__K``,
``Rotational_speed__rpm``, ``Torque__Nm``, ``Tool_wear__min``) in
``app/ml/feature_mapping.py``.

**Persisted but not consumed.** ``vibration_mm_s``, ``door_cycles``,
``door_errors`` and ``motor_current_a`` are real domain signals that the
current model has no input for. ``docs/data-model.md`` used to describe them as
model features; it described a model that was never built. They are stored
because the domain produces them and a future model may use them, and they are
documented here as unused so nobody wires them into a feature vector by
mistake.

**Units.** Everything is stored as a sensor reports it and a human reads it:
degrees Celsius, rpm, Nm, cumulative hours. The booster was trained on absolute
temperatures in Kelvin, and that conversion happens at exactly one place — the
construction of the feature matrix in the inference service. It must not be
duplicated here: Celsius reaching the model raises no error, it simply gives
every elevator the same plausible score.

**Provenance.** ``trace_id`` is the W3C trace id of the ingesting request as 32
hex characters, so a suspicious row can be traced back to the request that
created it. It is nullable because ingest must work with tracing disabled.

**Identity.** A reading is identified by ``(elevator_id, recorded_at, source)``
and stored at most once. The inference run averages *rows* over its window
rather than distinct readings, so a batch present twice is weighted twice and
moves the resulting score with no error and no log line — and the producer is a
scheduled workflow whose orchestrator retries a failed node by re-sending the
same payload. ``source`` belongs in the key because two producers reporting the
same elevator at the same instant are two independent observations and
averaging both is correct; a retry never changes it.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.elevator import Elevator


class TelemetryReading(Base):
    __tablename__ = "telemetry_readings"

    __table_args__ = (
        UniqueConstraint(
            "elevator_id",
            "recorded_at",
            "source",
            name="uq_telemetry_readings_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    elevator_id: Mapped[str] = mapped_column(ForeignKey("elevators.id", ondelete="CASCADE"))

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Model inputs (human units) ──────────────────────────────────────────
    ambient_temperature_c: Mapped[float]
    motor_temperature_c: Mapped[float]
    motor_speed_rpm: Mapped[float]
    load_torque_nm: Mapped[float]
    # Nullable: a producer that cannot report cumulative run hours falls back to
    # the age × usage × building-type proxy the offline script uses, so online
    # and offline scoring agree.
    motor_run_hours_cumulative: Mapped[float | None] = mapped_column(default=None)

    # ── Persisted, NOT consumed by the current model ────────────────────────
    vibration_mm_s: Mapped[float | None] = mapped_column(default=None)
    door_cycles: Mapped[int | None] = mapped_column(default=None)
    door_errors: Mapped[int | None] = mapped_column(default=None)
    motor_current_a: Mapped[float | None] = mapped_column(default=None)

    # ── Provenance ──────────────────────────────────────────────────────────
    source: Mapped[str]
    batch_id: Mapped[str]
    trace_id: Mapped[str | None] = mapped_column(default=None)

    elevator: Mapped["Elevator"] = relationship()


# There is deliberately no index on ``(elevator_id, recorded_at DESC)`` any
# more. The unique index behind ``uq_telemetry_readings_identity`` leads with
# exactly those two columns, and PostgreSQL serves a DESC ordering from it by
# scanning the btree backwards, so the per-elevator window query and the read
# endpoint are covered. Keeping both would pay a second index write on every
# insert into the hottest table in the schema for no read benefit.
#
# Declared after the class so the DESC ordering can be expressed with the
# column's own ``.desc()`` rather than through ``postgresql_ops``. That
# parameter is the slot for operator classes (``varchar_pattern_ops`` and the
# like); passing "DESC" through it happens to render correctly today because
# SQLAlchemy appends the string after the column name, but sort order is not
# what it means and nothing guarantees it keeps working.
Index(
    # The retention prune and the fleet-staleness gauge, neither of which
    # filters by elevator.
    "ix_telemetry_readings_recorded",
    TelemetryReading.recorded_at.desc(),
)
