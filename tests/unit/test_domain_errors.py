"""Unit tests targeting src/intake_domain/errors.py.

Verifies the real error hierarchy: to_dict(), retry_eligible,
error_code values, and ConflictError attribute contract.
"""
from __future__ import annotations

import pytest

from intake_domain.errors import (
    AuthorizationDeniedError,
    ConflictError,
    IdempotencyKeyCollisionError,
    IntakeDomainError,
    InvalidTransitionError,
    NotFoundError,
    PermanentError,
    PreconditionFailedError,
    TransientError,
    ValidationError,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# error_code constants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,code", [
    (IntakeDomainError,        "DOMAIN_ERROR"),
    (NotFoundError,            "NOT_FOUND"),
    (ConflictError,            "CONFLICT"),
    (ValidationError,          "VALIDATION_ERROR"),
    (AuthorizationDeniedError, "AUTHORIZATION_DENIED"),
    (InvalidTransitionError,   "INVALID_TRANSITION"),
    (PreconditionFailedError,  "PRECONDITION_FAILED"),
    (IdempotencyKeyCollisionError, "IDEMPOTENCY_COLLISION"),
    (TransientError,           "TRANSIENT_ERROR"),
    (PermanentError,           "PERMANENT_ERROR"),
])
def test_error_code_constant(cls, code: str):
    assert cls.error_code == code


# ---------------------------------------------------------------------------
# retry_eligible
# ---------------------------------------------------------------------------

def test_transient_error_is_retry_eligible():
    assert TransientError.retry_eligible is True


def test_conflict_error_is_retry_eligible():
    assert ConflictError.retry_eligible is True


def test_permanent_error_is_not_retry_eligible():
    assert PermanentError.retry_eligible is False


def test_validation_error_is_not_retry_eligible():
    assert ValidationError.retry_eligible is False


# ---------------------------------------------------------------------------
# IntakeDomainError base — to_dict
# ---------------------------------------------------------------------------

def test_base_error_to_dict_has_required_keys():
    err = IntakeDomainError("something went wrong")
    d = err.to_dict()
    assert d["status"] == "error"
    assert d["error_code"] == "DOMAIN_ERROR"
    assert d["message"] == "something went wrong"
    assert "retry_eligible" in d


def test_base_error_to_dict_includes_extra_context():
    err = IntakeDomainError("failed", request_id="r-1", revision=3)
    d = err.to_dict()
    assert d["request_id"] == "r-1"
    assert d["revision"] == 3


# ---------------------------------------------------------------------------
# NotFoundError
# ---------------------------------------------------------------------------

def test_not_found_to_dict():
    err = NotFoundError("Request not found", request_id="r-abc")
    d = err.to_dict()
    assert d["error_code"] == "NOT_FOUND"
    assert d["request_id"] == "r-abc"
    assert d["retry_eligible"] is False


# ---------------------------------------------------------------------------
# ConflictError — constructor and attributes
# ---------------------------------------------------------------------------

def test_conflict_error_attributes():
    err = ConflictError("ETag mismatch", current_revision=4, current_etag="etag-xyz")
    assert err.current_revision == 4
    assert err.current_etag == "etag-xyz"
    assert err.error_code == "CONFLICT"
    assert err.retry_eligible is True


def test_conflict_error_to_dict():
    err = ConflictError("mismatch", current_revision=3, current_etag="e-3")
    d = err.to_dict()
    assert d["error_code"] == "CONFLICT"
    assert d["current_revision"] == 3
    assert d["current_etag"] == "e-3"
    assert d["retry_eligible"] is True


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

def test_validation_error_with_context():
    err = ValidationError("Bad enum value", allowed=["low", "medium", "high"])
    d = err.to_dict()
    assert d["error_code"] == "VALIDATION_ERROR"
    assert d["allowed"] == ["low", "medium", "high"]


# ---------------------------------------------------------------------------
# AuthorizationDeniedError
# ---------------------------------------------------------------------------

def test_authorization_denied_to_dict():
    err = AuthorizationDeniedError("Forbidden", user_id="u-1")
    d = err.to_dict()
    assert d["error_code"] == "AUTHORIZATION_DENIED"
    assert d["user_id"] == "u-1"


# ---------------------------------------------------------------------------
# InvalidTransitionError
# ---------------------------------------------------------------------------

def test_invalid_transition_to_dict():
    err = InvalidTransitionError(
        "Cannot go new→completed",
        current_status="new",
        target_status="completed",
    )
    d = err.to_dict()
    assert d["error_code"] == "INVALID_TRANSITION"
    assert d["current_status"] == "new"
    assert d["target_status"] == "completed"


# ---------------------------------------------------------------------------
# PreconditionFailedError
# ---------------------------------------------------------------------------

def test_precondition_failed_to_dict():
    err = PreconditionFailedError(
        "Blocking gaps remain",
        blocking_gaps=["gap-1", "gap-2"],
    )
    d = err.to_dict()
    assert d["error_code"] == "PRECONDITION_FAILED"
    assert d["blocking_gaps"] == ["gap-1", "gap-2"]


# ---------------------------------------------------------------------------
# TransientError / PermanentError
# ---------------------------------------------------------------------------

def test_transient_error_to_dict():
    err = TransientError("Cosmos unavailable")
    d = err.to_dict()
    assert d["error_code"] == "TRANSIENT_ERROR"
    assert d["retry_eligible"] is True


def test_permanent_error_to_dict():
    err = PermanentError("Corrupt data")
    d = err.to_dict()
    assert d["error_code"] == "PERMANENT_ERROR"
    assert d["retry_eligible"] is False


# ---------------------------------------------------------------------------
# All errors are subclasses of IntakeDomainError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [
    NotFoundError, ConflictError, ValidationError, AuthorizationDeniedError,
    InvalidTransitionError, PreconditionFailedError, IdempotencyKeyCollisionError,
    TransientError, PermanentError,
])
def test_all_errors_inherit_from_base(cls):
    assert issubclass(cls, IntakeDomainError)
    assert issubclass(cls, Exception)


# ---------------------------------------------------------------------------
# All errors are catchable as IntakeDomainError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [
    NotFoundError, ConflictError, ValidationError, AuthorizationDeniedError,
    InvalidTransitionError, PreconditionFailedError,
])
def test_errors_catchable_as_base(cls):
    with pytest.raises(IntakeDomainError):
        raise cls("test message")
