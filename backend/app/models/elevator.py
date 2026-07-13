from sqlalchemy import ForeignKey, UniqueConstraint
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
