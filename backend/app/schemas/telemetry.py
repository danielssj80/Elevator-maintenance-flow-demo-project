from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# One producer submitting one 15-minute tick for a 100-elevator fleet sends 100
# readings. The bound is an order of magnitude above that: large enough for a
# catch-up batch after an outage, small enough that one request cannot pin the
# event loop or the database.
MAX_BATCH_SIZE = 1000


class TelemetryReadingInput(BaseModel):
    """One sensor reading, in the units the sensor reports.

    Temperatures are Celsius. They are converted to the model's Kelvin feature
    space during inference and nowhere else — do not pre-convert here.
    """

    elevator_id: str
    recorded_at: datetime

    # Consumed by the model.
    ambient_temperature_c: float
    motor_temperature_c: float
    motor_speed_rpm: float = Field(ge=0)
    load_torque_nm: float = Field(ge=0)
    motor_run_hours_cumulative: float | None = Field(default=None, ge=0)

    # Persisted, not consumed by the current model.
    vibration_mm_s: float | None = Field(default=None, ge=0)
    door_cycles: int | None = Field(default=None, ge=0)
    door_errors: int | None = Field(default=None, ge=0)
    motor_current_a: float | None = Field(default=None, ge=0)


class TelemetryBatchSchema(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    readings: list[TelemetryReadingInput] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class TelemetryIngestResponseSchema(BaseModel):
    batch_id: str
    accepted: int
    rejected_elevator_ids: list[str]
    trace_id: str | None


class TelemetryReadingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    elevator_id: str
    recorded_at: datetime
    ingested_at: datetime
    ambient_temperature_c: float
    motor_temperature_c: float
    motor_speed_rpm: float
    load_torque_nm: float
    motor_run_hours_cumulative: float | None
    vibration_mm_s: float | None
    door_cycles: int | None
    door_errors: int | None
    motor_current_a: float | None
    source: str
    batch_id: str
    trace_id: str | None
