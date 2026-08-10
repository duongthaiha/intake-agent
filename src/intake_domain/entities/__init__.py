"""Domain entities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RequestStatus(StrEnum):
    NEW = "new"
    IN_REVIEW = "in_review"
    AWAITING_FEEDBACK = "awaiting_feedback"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class ValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    PENDING = "pending"


class GapCategory(StrEnum):
    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"


class GapSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class GapStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    WORKER = "worker"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass
class FieldValue:
    field_path: str
    value: Any
    source_reference: str | None = None
    model_confidence: float | None = None
    validation_status: ValidationStatus = ValidationStatus.PENDING


@dataclass
class Gap:
    gap_id: str
    field_path: str
    category: GapCategory
    severity: GapSeverity
    status: GapStatus = GapStatus.OPEN
    message: str = ""


@dataclass
class ActorContext:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    conversation_id: str
    activity_id: str
    correlation_id: str
    agent_identity: str


# ---------------------------------------------------------------------------
# Template entities
# ---------------------------------------------------------------------------

@dataclass
class FieldSchema:
    field_path: str
    label: str
    field_type: str          # "string" | "number" | "date" | "boolean" | "enum"
    required: bool = True
    enum_values: list[str] = field(default_factory=list)
    min_confidence: float = 0.7
    description: str = ""


@dataclass
class TemplateVersion:
    template_id: str
    version: str
    display_name: str
    fields: list[FieldSchema] = field(default_factory=list)
    quality_threshold: float = 0.8
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Aggregate roots
# ---------------------------------------------------------------------------

@dataclass
class Request:
    request_id: str
    tenant_id: str
    conversation_id: str
    requester_id: str
    status: RequestStatus
    current_revision: int
    template_id: str
    template_version: str
    created_at: datetime
    updated_at: datetime
    etag: str = ""


@dataclass
class RequestRevision:
    request_id: str
    revision: int
    fields: dict[str, FieldValue] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    quality_score: float | None = None
    agent_version: str = ""
    prompt_version: str = ""
    model_version: str = ""
    template_version: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    immutable: bool = False


@dataclass
class Review:
    review_id: str
    request_id: str
    reviewer_id: str
    decision: ReviewDecision | None = None
    rationale: str = ""
    decided_at: datetime | None = None


@dataclass
class WorkflowEvent:
    event_id: str
    request_id: str
    revision: int
    actor_id: str
    actor_type: ActorType
    command_id: str
    prior_state: RequestStatus | None
    new_state: RequestStatus | None
    occurred_at: datetime
    event_type: str = ""
    event_version: str = "1.0"
    correlation_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------

@dataclass
class OutboxItem:
    item_id: str
    request_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    dispatched: bool = False


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

@dataclass
class StoredResult:
    scope_id: str
    key: str
    result: Any
    stored_at: datetime
    expires_at: datetime
