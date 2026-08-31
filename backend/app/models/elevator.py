from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ElevatorFeature(Base):
    __tablename__ = "elevator_features"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    elevator_id: Mapped[str] = mapped_column(ForeignKey("elevators.id", ondelete="CASCADE"))
    name: Mapped[str]
    impact: Mapped[float]
    value: Mapped[str]
    # SHAP sign: "increases" (raises risk) or "decreases" (protective)
    direction: Mapped[str]

    elevator: Mapped["Elevator"] = relationship(back_populates="features")


class ElevatorTrendPoint(Base):
    __tablename__ = "elevator_trend_points"
    __table_args__ = (UniqueConstraint("elevator_id", "day_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    elevator_id: Mapped[str] = mapped_column(ForeignKey("elevators.id", ondelete="CASCADE"))
    day_index: Mapped[int]
    score: Mapped[float]

    elevator: Mapped["Elevator"] = relationship(back_populates="trend_points")


class Elevator(Base):
    __tablename__ = "elevators"

    id: Mapped[str] = mapped_column(primary_key=True)
    building_name: Mapped[str]
    building_type: Mapped[str]
    floor_count: Mapped[int]
    model: Mapped[str]
    brand: Mapped[str]
    age_years: Mapped[int]
    risk_score: Mapped[float]
    risk_level: Mapped[str]
    last_visit_date: Mapped[str]
    last_visit_technician: Mapped[str]
    last_visit_notes: Mapped[str]
    nl_explanation: Mapped[str]
    in_model_scope: Mapped[bool]
    hourly_trips_avg: Mapped[int]
    zone: Mapped[str]
    # When an inference run last scored this elevator. Null for a fleet that has
    # only ever been seeded from predictions.json.
    #
    # It exists because the 6-day trend window shifts on date change rather than
    # on every run, and elevator_trend_points carries only day_index and score —
    # a trend point cannot say which day it belongs to, so the decision "is the
    # newest point today's?" is not derivable from the trend itself. Runs happen
    # more than once a day (a schedule plus manual demo triggers), so without
    # this the window would shift on every run and "index 5 = today" would stop
    # being true after the second run of any day.
    last_scored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    features: Mapped[list[ElevatorFeature]] = relationship(
        back_populates="elevator",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    trend_points: Mapped[list[ElevatorTrendPoint]] = relationship(
        back_populates="elevator",
        cascade="all, delete-orphan",
        order_by=ElevatorTrendPoint.day_index,
        lazy="selectin",
    )
