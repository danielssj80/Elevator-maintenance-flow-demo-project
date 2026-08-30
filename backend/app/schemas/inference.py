from pydantic import BaseModel


class InferenceRunResponseSchema(BaseModel):
    """What a run did, in terms an operator can act on.

    `skipped_no_telemetry` is the number that matters most: it is how a fleet
    that has quietly stopped reporting becomes visible, rather than showing as
    uniformly low risk.
    """

    scored: int
    skipped_no_telemetry: int
    out_of_scope: int
    readings_considered: int
    model_version: str | None
    window_hours: int
    duration_seconds: float
    pruned_readings: int
