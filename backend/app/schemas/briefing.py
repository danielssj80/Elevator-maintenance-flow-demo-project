from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class BriefingSchema(BaseModel):
    elevator_id: str
    text: str
    source: Literal["bedrock", "fallback"]
    generated_at: datetime
