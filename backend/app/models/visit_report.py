from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VisitReport(Base):
    __tablename__ = "visit_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    elevator_id: Mapped[str] = mapped_column(ForeignKey("elevators.id", ondelete="CASCADE"))
    technician_name: Mapped[str]
    visit_date: Mapped[str]
    failure_found: Mapped[bool]
    components_replaced: Mapped[list[str]] = mapped_column(JSONB, default=list)
    parameters_corrected: Mapped[list[str]] = mapped_column(JSONB, default=list)
    notes: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    elevator: Mapped["Elevator"] = relationship()  # type: ignore[name-defined]
