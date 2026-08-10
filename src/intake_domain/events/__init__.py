"""Domain event models — envelope and typed payloads."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventActorPayload(BaseModel):
    user_id: str
    actor_type: str = "user"


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    event_version: str = "1.0"
    request_id: str
    revision: int
    correlation_id: str
    causation_id: str  # command_id that caused this event
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: EventActorPayload
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Typed event data helpers
# ---------------------------------------------------------------------------

class RequestCreatedData(BaseModel):
    template_id: str
    template_version: str
    requester_id: str


class RequestFieldsUpdatedData(BaseModel):
    accepted_fields: list[str]
    resolved_gaps: list[str]
    new_gaps: list[str]


class RequestSubmittedData(BaseModel):
    revision: int
    quality_score: float | None = None


class RequestApprovedData(BaseModel):
    reviewer_id: str
    revision: int
    rationale: str


class RequestRejectedData(BaseModel):
    reviewer_id: str
    revision: int
    rationale: str


class ChangesRequestedData(BaseModel):
    reviewer_id: str
    feedback: str
