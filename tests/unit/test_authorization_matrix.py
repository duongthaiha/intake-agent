"""Unit tests for the authorization matrix.

Covers:
- Every role × command permission (positive and negative).
- Multi-role actors get the union of permissions.
- POC-03 invariant: only reviewers/admins can record_review_decision.
- Unauthenticated (empty roles) actor is denied everything.
"""
from __future__ import annotations

import pytest
from reference_domain import (
    AUTHORIZATION_MATRIX,
    ActorContext,
    AuthorizationDeniedError,
    assert_authorized,
    make_actor,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# All commands that appear anywhere in the matrix
# ---------------------------------------------------------------------------

ALL_COMMANDS = set().union(*AUTHORIZATION_MATRIX.values())


# ---------------------------------------------------------------------------
# Positive cases: each role can execute its allowed commands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", list(AUTHORIZATION_MATRIX.keys()))
@pytest.mark.parametrize("command", list(ALL_COMMANDS))
def test_role_allowed_commands(role: str, command: str):
    actor = make_actor(roles=frozenset([role]))
    if command in AUTHORIZATION_MATRIX[role]:
        assert_authorized(actor, command)  # must not raise
    else:
        with pytest.raises(AuthorizationDeniedError):
            assert_authorized(actor, command)


# ---------------------------------------------------------------------------
# Reviewer-only invariant  (POC-03)
# ---------------------------------------------------------------------------

def test_requester_cannot_record_review_decision(requester_actor: ActorContext):
    with pytest.raises(AuthorizationDeniedError):
        assert_authorized(requester_actor, "record_review_decision")


def test_reviewer_can_record_review_decision(reviewer_actor: ActorContext):
    assert_authorized(reviewer_actor, "record_review_decision")


def test_admin_can_record_review_decision(admin_actor: ActorContext):
    assert_authorized(admin_actor, "record_review_decision")


# ---------------------------------------------------------------------------
# Unauthenticated actor is denied all commands
# ---------------------------------------------------------------------------

def test_empty_roles_denied_all_commands():
    actor = make_actor(roles=frozenset())
    for cmd in ALL_COMMANDS:
        with pytest.raises(AuthorizationDeniedError):
            assert_authorized(actor, cmd)


# ---------------------------------------------------------------------------
# Multi-role union
# ---------------------------------------------------------------------------

def test_multi_role_actor_gets_union_of_permissions():
    """An actor with both requester + reviewer roles can do both sets of commands."""
    actor = make_actor(roles=frozenset(["requester", "reviewer"]))
    all_allowed = (
        AUTHORIZATION_MATRIX["requester"] | AUTHORIZATION_MATRIX["reviewer"]
    )
    for cmd in all_allowed:
        assert_authorized(actor, cmd)


# ---------------------------------------------------------------------------
# Error message quality
# ---------------------------------------------------------------------------

def test_authorization_error_mentions_command():
    actor = make_actor(roles=frozenset(["requester"]))
    with pytest.raises(AuthorizationDeniedError, match="record_review_decision"):
        assert_authorized(actor, "record_review_decision")


def test_authorization_error_mentions_actor_roles():
    actor = make_actor(user_id="u-1", roles=frozenset(["requester"]))
    with pytest.raises(AuthorizationDeniedError, match="requester"):
        assert_authorized(actor, "record_review_decision")


# ---------------------------------------------------------------------------
# Matrix completeness checks
# ---------------------------------------------------------------------------

def test_roles_cover_expected_set():
    expected_roles = {"requester", "reviewer", "admin"}
    assert set(AUTHORIZATION_MATRIX.keys()) == expected_roles


def test_submit_for_review_is_requester_command():
    assert "submit_for_review" in AUTHORIZATION_MATRIX["requester"]


def test_reviewer_cannot_create_requests():
    """Reviewers must not create or modify intake data."""
    actor = make_actor(roles=frozenset(["reviewer"]))
    with pytest.raises(AuthorizationDeniedError):
        assert_authorized(actor, "propose_field_updates")
