from pydantic import BaseModel
from typing import Literal


class Feature(BaseModel):
    name: str
    impact: float
    value: str


class ElevatorSummary(BaseModel):
    id: str
    building_name: str
    building_type: str
    floor_count: int
    model: str
    age_years: int
    risk_score: float
    risk_level: Literal["high", "medium", "low"]
    last_visit_date: str
    last_visit_technician: str
    in_model_scope: bool
    zone: str


class ElevatorDetail(ElevatorSummary):
    brand: str
    trend: list[float]
    last_visit_notes: str
    nl_explanation: str
    features: list[Feature]
    hourly_trips_avg: int


class PostVisitReport(BaseModel):
    technician_name: str
    visit_date: str
    failure_found: bool
    components_replaced: list[str] = []
    parameters_corrected: list[str] = []
    notes: str = ""


class ReportResponse(BaseModel):
    status: str
    message: str
