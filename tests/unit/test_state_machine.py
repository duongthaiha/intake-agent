"""Unit tests for the request state machine.

Covers every valid transition and every invalid transition that the domain
model must reject.  Source of truth: ADR-013 §Thin vertical flow and the
ALLOWED_TRANSITIONS table in reference_domain.
"""
from __future__ import annotations

import pytest
from reference_domain import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    RequestStatus,
    assert_valid_transition,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parametrised valid transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS = [
    (RequestStatus.NEW, RequestStatus.IN_REVIEW),
    (RequestStatus.IN_REVIEW, RequestStatus.APPROVED),
    (RequestStatus.IN_REVIEW, RequestStatus.REJECTED),
    (RequestStatus.IN_REVIEW, RequestStatus.AWAITING_FEEDBACK),
    (RequestStatus.AWAITING_FEEDBACK, RequestStatus.IN_REVIEW),
    (RequestStatus.APPROVED, RequestStatus.COMPLETED),
]


@pytest.mark.parametrize("src,dst", VALID_TRANSITIONS)
def test_valid_transition_accepted(src: RequestStatus, dst: RequestStatus):
    assert_valid_transition(src, dst)  # must not raise


# ---------------------------------------------------------------------------
# Parametrised invalid transitions
# ---------------------------------------------------------------------------

ALL_STATUSES = list(RequestStatus)

INVALID_TRANSITIONS = [
    (src, dst)
    for src in ALL_STATUSES
    for dst in ALL_STATUSES
    if dst not in ALLOWED_TRANSITIONS.get(src, set())
]


@pytest.mark.parametrize("src,dst", INVALID_TRANSITIONS)
def test_invalid_transition_raises(src: RequestStatus, dst: RequestStatus):
    with pytest.raises(InvalidTransitionError):
        assert_valid_transition(src, dst)


# ---------------------------------------------------------------------------
# Terminal state tests
# ---------------------------------------------------------------------------

def test_rejected_is_terminal():
    """Rejected requests cannot transition to any other state."""
    for target in RequestStatus:
        with pytest.raises(InvalidTransitionError):
            assert_valid_transition(RequestStatus.REJECTED, target)


def test_completed_is_terminal():
    """Completed requests cannot transition to any other state."""
    for target in RequestStatus:
        with pytest.raises(InvalidTransitionError):
            assert_valid_transition(RequestStatus.COMPLETED, target)


# ---------------------------------------------------------------------------
# Model-cannot-approve invariant  (POC-03)
# ---------------------------------------------------------------------------

def test_new_cannot_transition_directly_to_approved():
    """A new request cannot skip the IN_REVIEW stage and go straight to APPROVED.

    This prevents a model-generated command from approving its own output.
    """
    with pytest.raises(InvalidTransitionError):
        assert_valid_transition(RequestStatus.NEW, RequestStatus.APPROVED)


def test_new_cannot_transition_directly_to_completed():
    with pytest.raises(InvalidTransitionError):
        assert_valid_transition(RequestStatus.NEW, RequestStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Error message quality
# ---------------------------------------------------------------------------

def test_invalid_transition_error_contains_statuses():
    with pytest.raises(InvalidTransitionError, match="new"):
        assert_valid_transition(RequestStatus.NEW, RequestStatus.COMPLETED)


# ---------------------------------------------------------------------------
# ALLOWED_TRANSITIONS coverage check
# ---------------------------------------------------------------------------

def test_all_statuses_in_allowed_transitions_table():
    """Every status must appear as a key in the transition table."""
    for status in RequestStatus:
        assert status in ALLOWED_TRANSITIONS, (
            f"RequestStatus.{status.name} is missing from ALLOWED_TRANSITIONS"
        )
