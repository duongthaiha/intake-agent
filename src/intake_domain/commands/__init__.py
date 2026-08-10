"""Command models — envelopes and typed data payloads."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ActorPayload(BaseModel):
    user_id: str
    tenant_id: str
    actor_type: str = "user"
    agent_identity: str = ""


class CommandEnvelope(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    command_type: str
    request_id: str
    expected_revision: int
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: str = ""
    actor: ActorPayload
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.idempotency_key:
            self.idempotency_key = self.command_id


# ---------------------------------------------------------------------------
# Specific command data models
# ---------------------------------------------------------------------------

class FieldUpdateItem(BaseModel):
    field_path: str
    value: Any
    source_reference: str | None = None
    model_confidence: float | None = None


class ProposeFieldUpdatesData(BaseModel):
    updates: list[FieldUpdateItem]


class SubmitForReviewData(BaseModel):
    pass


class RecordReviewDecisionData(BaseModel):
    decision: str
    rationale: str
