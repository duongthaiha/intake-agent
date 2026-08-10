"""
Reference domain implementations derived from ADR-013 and contracts.

These serve as:
1. Contract documentation — the authoritative shape of every domain entity.
2. Test doubles — allow all unit/component/contract tests to run before
   Trinity delivers the real ``src/intake_domain`` package.

When ``intake_domain`` is importable, tests should switch to the real
package via the helpers at the bottom of this file.  The reference
implementations are kept to validate structural parity.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Value types
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
# Entities  (ADR-013)
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
    etag: str


@dataclass
class RequestRevision:
    request_id: str
    revision: int
    fields: dict[str, FieldValue]
    gaps: list[Gap]
    quality_score: float | None
    agent_version: str
    prompt_version: str
    model_version: str
    template_version: str
    created_at: datetime
    immutable: bool = False


@dataclass
class Review:
    review_id: str
    reviewer_id: str
    decision: ReviewDecision | None
    rationale: str
    decided_at: datetime | None


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
# Domain errors
# ---------------------------------------------------------------------------

class DomainError(Exception):
    """Base domain error."""
    error_code: str = "DOMAIN_ERROR"


class ConflictError(DomainError):
    error_code = "CONFLICT"

    def __init__(self, expected: str | int, current: str | int) -> None:
        self.expected = expected
        self.current = current
        super().__init__(f"Expected {expected!r} but current is {current!r}")


class AuthorizationDeniedError(DomainError):
    error_code = "AUTHORIZATION_DENIED"


class InvalidTransitionError(DomainError):
    error_code = "INVALID_TRANSITION"


class PreconditionFailedError(DomainError):
    error_code = "PRECONDITION_FAILED"


class NotFoundError(DomainError):
    error_code = "NOT_FOUND"


class ValidationError(DomainError):
    error_code = "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Repository protocols
# ---------------------------------------------------------------------------

class RequestRepository(ABC):
    @abstractmethod
    async def get(self, request_id: str) -> Request | None: ...

    @abstractmethod
    async def get_or_create(
        self, request_id: str, factory: Callable[[], Request]
    ) -> tuple[Request, bool]: ...

    @abstractmethod
    async def save(
        self,
        request: Request,
        revision: RequestRevision,
        events: list[WorkflowEvent],
        expected_etag: str,
    ) -> str: ...

    @abstractmethod
    async def get_current_revision(self, request_id: str) -> RequestRevision | None: ...


class IdempotencyStore(ABC):
    @abstractmethod
    async def check(self, scope_id: str, key: str) -> Any | None: ...

    @abstractmethod
    async def store(self, scope_id: str, key: str, result: Any, ttl_days: int = 7) -> None: ...


# ---------------------------------------------------------------------------
# In-memory implementations
# ---------------------------------------------------------------------------

class InMemoryRequestRepository(RequestRepository):
    """Production-quality in-memory implementation.

    Enforces the same ETag-based optimistic concurrency semantics that
    CosmosRequestRepository will enforce.
    """

    def __init__(self) -> None:
        self._requests: dict[str, Request] = {}
        self._revisions: dict[str, RequestRevision] = {}
        self._events: list[WorkflowEvent] = []
        self._lock = asyncio.Lock()

    async def get(self, request_id: str) -> Request | None:
        return self._requests.get(request_id)

    async def get_or_create(
        self, request_id: str, factory: Callable[[], Request]
    ) -> tuple[Request, bool]:
        async with self._lock:
            if request_id in self._requests:
                return self._requests[request_id], False
            req = factory()
            self._requests[request_id] = req
            return req, True

    async def save(
        self,
        request: Request,
        revision: RequestRevision,
        events: list[WorkflowEvent],
        expected_etag: str,
    ) -> str:
        async with self._lock:
            existing = self._requests.get(request.request_id)
            if existing is not None and existing.etag != expected_etag:
                raise ConflictError(expected=expected_etag, current=existing.etag)
            new_etag = str(uuid.uuid4())
            request.etag = new_etag
            self._requests[request.request_id] = request
            self._revisions[request.request_id] = revision
            self._events.extend(events)
            return new_etag

    async def get_current_revision(self, request_id: str) -> RequestRevision | None:
        return self._revisions.get(request_id)

    def all_events(self) -> list[WorkflowEvent]:
        return list(self._events)


class InMemoryIdempotencyStore(IdempotencyStore):
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], Any] = {}

    async def check(self, scope_id: str, key: str) -> Any | None:
        return self._store.get((scope_id, key))

    async def store(self, scope_id: str, key: str, result: Any, ttl_days: int = 7) -> None:
        self._store[(scope_id, key)] = result


# ---------------------------------------------------------------------------
# Helpers for request_id determinism  (ADR-013)
# ---------------------------------------------------------------------------

def derive_request_id(tenant_id: str, conversation_id: str) -> str:
    """Deterministic request_id: hash(tenant_id, conversation_id)."""
    raw = f"{tenant_id}:{conversation_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# State machine transitions  (ADR-013 / contracts)
# ---------------------------------------------------------------------------

# Valid forward transitions
ALLOWED_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.NEW: {RequestStatus.IN_REVIEW},
    RequestStatus.IN_REVIEW: {
        RequestStatus.APPROVED,
        RequestStatus.REJECTED,
        RequestStatus.AWAITING_FEEDBACK,
    },
    RequestStatus.AWAITING_FEEDBACK: {RequestStatus.IN_REVIEW},
    RequestStatus.APPROVED: {RequestStatus.COMPLETED},
    RequestStatus.REJECTED: set(),
    RequestStatus.COMPLETED: set(),
}


def assert_valid_transition(current: RequestStatus, target: RequestStatus) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Transition {current.value!r} → {target.value!r} is not permitted. "
            f"Allowed targets: {[s.value for s in allowed]}"
        )


# ---------------------------------------------------------------------------
# Authorization matrix  (ADR-013 / POC-03)
# ---------------------------------------------------------------------------

# role → permitted commands
AUTHORIZATION_MATRIX: dict[str, set[str]] = {
    "requester": {
        "get_or_create_request",
        "propose_field_updates",
        "get_request_context",
        "submit_for_review",
    },
    "reviewer": {
        "get_request_context",
        "record_review_decision",
    },
    "admin": {
        "get_or_create_request",
        "propose_field_updates",
        "get_request_context",
        "submit_for_review",
        "record_review_decision",
        "cancel_request",
    },
}


def assert_authorized(actor: ActorContext, command: str) -> None:
    for role in actor.roles:
        if command in AUTHORIZATION_MATRIX.get(role, set()):
            return
    raise AuthorizationDeniedError(
        f"Actor {actor.user_id!r} with roles {set(actor.roles)!r} "
        f"is not authorized for command {command!r}"
    )


# ---------------------------------------------------------------------------
# Factory helpers used in tests
# ---------------------------------------------------------------------------

def now() -> datetime:
    return datetime.now(UTC)


def make_request(
    tenant_id: str = "tenant-1",
    conversation_id: str = "conv-1",
    requester_id: str = "user-1",
    template_id: str = "general-intake-v1",
    template_version: str = "1.0.0",
    status: RequestStatus = RequestStatus.NEW,
    revision: int = 1,
) -> Request:
    request_id = derive_request_id(tenant_id, conversation_id)
    ts = now()
    return Request(
        request_id=request_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        requester_id=requester_id,
        status=status,
        current_revision=revision,
        template_id=template_id,
        template_version=template_version,
        created_at=ts,
        updated_at=ts,
        etag=str(uuid.uuid4()),
    )


def make_revision(
    request_id: str,
    revision: int = 1,
    fields: dict[str, FieldValue] | None = None,
    gaps: list[Gap] | None = None,
    quality_score: float | None = None,
    immutable: bool = False,
) -> RequestRevision:
    return RequestRevision(
        request_id=request_id,
        revision=revision,
        fields=fields or {},
        gaps=gaps or [],
        quality_score=quality_score,
        agent_version="0.1.0",
        prompt_version="0.1.0",
        model_version="gpt-4o",
        template_version="1.0.0",
        created_at=now(),
        immutable=immutable,
    )


def make_actor(
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    roles: frozenset[str] | None = None,
    conversation_id: str = "conv-1",
) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=frozenset(["requester"]) if roles is None else roles,
        conversation_id=conversation_id,
        activity_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        agent_identity="local-agent",
    )
