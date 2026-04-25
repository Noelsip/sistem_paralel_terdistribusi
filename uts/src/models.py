from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    topic: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    source: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
