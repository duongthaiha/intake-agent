"""Stable domain failure vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    AUTHORIZATION_DENIED = "authorization_denied"
    CONCURRENCY_CONFLICT = "concurrency_conflict"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INVALID_TRANSITION = "invalid_transition"
    NOT_FOUND = "not_found"
    INCOMPLETE_REQUEST = "incomplete_request"
    CLARIFICATION_LIMIT_REACHED = "clarification_limit_reached"
    RATIONALE_REQUIRED = "rationale_required"
    SEPARATION_OF_DUTIES = "separation_of_duties"


@dataclass(frozen=True, slots=True)
class DomainError(Exception):
    code: ErrorCode
    message: str
    field_path: str | None = None
    latest_revision: int | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.message

