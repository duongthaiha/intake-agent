"""Domain entities, value objects, events, and immutable revisions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ActorRole(StrEnum):
    REQUESTER = "requester"
    REVIEWER = "reviewer"
    ADMINISTRATOR = "administrator"
    COMPLETION_WORKER = "completion_worker"
    INTEGRATION_WORKER = "integration_worker"
    NOTIFICATION_WORKER = "notification_worker"
    RETENTION_WORKER = "retention_worker"


class AgentKind(StrEnum):
    HOSTED = "hosted"
    PROMPT = "prompt"
    LOCAL = "local"
    SERVICE = "service"


class RequestStatus(StrEnum):
    NEW = "new"
    IN_REVIEW = "in_review"
    AWAITING_USER_FEEDBACK = "awaiting_user_feedback"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class ValidationStatus(StrEnum):
    VALID = "valid"
    NEEDS_CLARIFICATION = "needs_clarification"


class FieldKind(StrEnum):
    TEXT = "text"
    CHOICE = "choice"
    NUMBER = "number"
    DATE = "date"


class DeliveryStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConversationEntry:
    conversation_key: str
    sequence: int
    role: str
    actor_id: str
    content: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class Provenance:
    agent_kind: AgentKind
    agent_version: str
    instructions_version: str
    model_version: str
    toolbox_version: str
    mcp_contract_version: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class ActorContext:
    tenant_id: str
    actor_id: str
    roles: frozenset[ActorRole]
    provenance: Provenance
    correlation_id: str


@dataclass(frozen=True, slots=True)
class TemplateField:
    path: str
    title: str
    kind: FieldKind
    required: bool
    minimum_length: int = 0
    maximum_length: int = 4000
    choices: tuple[str, ...] = ()
    minimum_number: float | None = None


@dataclass(frozen=True, slots=True)
class ContradictionRule:
    left_path: str
    operator: str
    right_path: str
    message: str


@dataclass(frozen=True, slots=True)
class TemplateVersion:
    template_id: str
    version: str
    schema_version: str
    fields: tuple[TemplateField, ...]
    contradiction_rules: tuple[ContradictionRule, ...]
    quality_threshold: float
    confidence_threshold: float
    maximum_clarification_attempts: int
    mandatory_handover: bool

    def field(self, path: str) -> TemplateField | None:
        return next((item for item in self.fields if item.path == path), None)


@dataclass(frozen=True, slots=True)
class FieldValue:
    field_path: str
    value: str
    source_reference: str
    confidence: float
    validation_status: ValidationStatus
    updated_by: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Gap:
    gap_id: str
    field_path: str
    category: str
    severity: str
    message: str
    clarification_attempts: int
    clarification_limit_reached: bool


@dataclass(frozen=True, slots=True)
class ReviewComment:
    comment_id: str
    reviewer_id: str
    revision_number: int
    comment: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    review_id: str
    reviewer_id: str
    revision_number: int
    decision: str
    rationale: str
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class RequestRevision:
    revision_number: int
    fields: tuple[FieldValue, ...]
    quality_score: float
    provenance: Provenance
    template_version: str
    schema_version: str
    submitted_by: str
    submitted_at: datetime


@dataclass(slots=True)
class IntakeRequest:
    request_id: str
    tenant_id: str
    requester_id: str
    conversation_key: str
    template: TemplateVersion
    assigned_reviewer_id: str
    status: RequestStatus = RequestStatus.NEW
    version: int = 0
    fields: dict[str, FieldValue] = field(default_factory=dict)
    clarification_attempts: dict[str, int] = field(default_factory=dict)
    revisions: list[RequestRevision] = field(default_factory=list)
    review_comments: list[ReviewComment] = field(default_factory=list)
    review_decisions: list[ReviewDecision] = field(default_factory=list)
    approved_revision_number: int | None = None
    delivery_status: DeliveryStatus = DeliveryStatus.NOT_REQUIRED
    delivery_failure_reason: str | None = None
    notification_results: dict[str, str] = field(default_factory=dict)
    retention_status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def latest_revision_number(self) -> int:
        return self.revisions[-1].revision_number if self.revisions else 0

    @property
    def approved_revision(self) -> RequestRevision | None:
        return next(
            (
                revision
                for revision in self.revisions
                if revision.revision_number == self.approved_revision_number
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class PendingEvent:
    event_type: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Mutation:
    data: dict[str, Any]
    events: tuple[PendingEvent, ...]


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    data: dict[str, Any]
    replayed: bool


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    request_id: str
    revision: int
    actor_id: str
    actor_roles: tuple[str, ...]
    correlation_id: str
    command_id: str
    prior_state: str | None
    new_state: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    event_type: str
    event_version: str
    request_id: str
    revision: int
    correlation_id: str
    causation_id: str
    occurred_at: datetime
    actor_id: str
    data: dict[str, Any]
