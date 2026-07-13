from typing import Literal

from pydantic import BaseModel, ConfigDict


class FeatureSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    impact: float
    value: str
    direction: str


class ElevatorSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class ElevatorDetailSchema(ElevatorSummarySchema):
    brand: str
    trend: list[float]
    last_visit_notes: str
    nl_explanation: str
    features: list[FeatureSchema]
    hourly_trips_avg: int
