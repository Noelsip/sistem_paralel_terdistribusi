"""Skema validasi event (Pydantic)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field, field_validator


class Event(BaseModel):
    topic: str = Field(..., min_length=1, max_length=256)
    event_id: str = Field(..., min_length=1, max_length=256)
    timestamp: datetime  # Pydantic memvalidasinya sebagai ISO8601
    source: str = Field(..., min_length=1, max_length=256)
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("topic", "event_id", "source")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tidak boleh kosong/whitespace")
        return v


class PublishResponse(BaseModel):
    accepted: int
    rejected: int = 0
    detail: str = "ok"

# Body /publish menerima single event ATAU batch (list of events).
PublishBody = Union[Event, List[Event]]

class StatsResponse(BaseModel):
    received: int
    unique_processed: int
    duplicate_dropped: int
    topics: int
    uptime_seconds: float
    queue_depth: int
