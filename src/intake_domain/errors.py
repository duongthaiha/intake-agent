"""Domain error hierarchy.

All errors are typed, carry structured context, and map to a stable error_code string
that is included in API responses and event envelopes.
"""
from __future__ import annotations

from typing import Any


class IntakeDomainError(Exception):
    """Base for all domain errors."""

    error_code: str = "DOMAIN_ERROR"
    retry_eligible: bool = False

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error_code": self.error_code,
            "message": self.message,
            "retry_eligible": self.retry_eligible,
            **self.context,
        }


class NotFoundError(IntakeDomainError):
    error_code = "NOT_FOUND"


class ConflictError(IntakeDomainError):
    """Optimistic concurrency failure."""

    error_code = "CONFLICT"
    retry_eligible = True

    def __init__(
        self,
        message: str,
        current_revision: int = -1,
        current_etag: str = "",
        **ctx: Any,
    ) -> None:
        super().__init__(
            message,
            current_revision=current_revision,
            current_etag=current_etag,
            **ctx,
        )
        self.current_revision = current_revision
        self.current_etag = current_etag


class ValidationError(IntakeDomainError):
    error_code = "VALIDATION_ERROR"


class AuthorizationDeniedError(IntakeDomainError):
    error_code = "AUTHORIZATION_DENIED"


class InvalidTransitionError(IntakeDomainError):
    error_code = "INVALID_TRANSITION"


class PreconditionFailedError(IntakeDomainError):
    error_code = "PRECONDITION_FAILED"


class IdempotencyKeyCollisionError(IntakeDomainError):
    """Command already processed; caller should use stored result."""

    error_code = "IDEMPOTENCY_COLLISION"


class TransientError(IntakeDomainError):
    error_code = "TRANSIENT_ERROR"
    retry_eligible = True


class PermanentError(IntakeDomainError):
    error_code = "PERMANENT_ERROR"
