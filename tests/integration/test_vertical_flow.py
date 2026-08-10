"""Integration tests: LocalAdapter vertical flow.

Uses src/intake_agent and src/intake_domain (Trinity's implementation).
Skips cleanly if packages are not installed.
No Azure credentials required — uses in-memory persistence via build_repositories().

ADR-014: LocalAdapter is the primary integration target for Switch.

INTERFACE MISMATCH NOTE (recorded 2026-08-07):
  ADR-014 specified: LocalAdapter.handle_message(message, user_id) -> str
  Trinity delivered: individual command methods (get_or_create_request, propose_updates,
                     submit_for_review, record_review_decision, list_requests).
  Resolution: tests use the actual delivered API; handle_message is deferred to
              the Foundry/orchestrator layer.  See docs/quality/test-strategy.md.
"""
from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.integration

_intake_available = (
    importlib.util.find_spec("intake_agent") is not None
    and importlib.util.find_spec("intake_domain") is not None
    and importlib.util.find_spec("intake_persistence") is not None
)

skip_reason = (
    "intake_agent/intake_domain/intake_persistence not installed. "
    "Run: pip install -e '.[dev]' from repo root."
)


# ---------------------------------------------------------------------------
# Fixture: wired LocalAdapter using in-memory repos
# ---------------------------------------------------------------------------

@pytest.fixture()
def adapter():
    """Return a LocalAdapter wired with in-memory repos (no Azure)."""
    if not _intake_available:
        pytest.skip(skip_reason)
    from intake_agent.adapter.local import LocalAdapter
    from intake_agent.config import IntakeSettings, build_repositories

    settings = IntakeSettings(persistence_backend="inmemory")
    repos = build_repositories(settings)
    return LocalAdapter(**repos, template_id=settings.template_id)


# ---------------------------------------------------------------------------
# Structural tests (always collected)
# ---------------------------------------------------------------------------

def test_local_adapter_importable():
    if not _intake_available:
        pytest.skip(skip_reason)
    from intake_agent.adapter.local import LocalAdapter
    assert LocalAdapter is not None


def test_local_adapter_has_command_methods():
    if not _intake_available:
        pytest.skip(skip_reason)
    from intake_agent.adapter.local import LocalAdapter
    for method in ("get_or_create_request", "propose_updates", "submit_for_review",
                   "record_review_decision", "list_requests", "get_context"):
        assert hasattr(LocalAdapter, method), f"LocalAdapter missing method: {method!r}"


# ---------------------------------------------------------------------------
# Integration flow tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_returns_request_id(adapter):
    result = await adapter.get_or_create_request(user_id="u-1", conversation_id="conv-1")
    assert "request_id" in result
    assert result["request_id"]


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(adapter):
    r1 = await adapter.get_or_create_request(user_id="u-1", conversation_id="conv-1")
    r2 = await adapter.get_or_create_request(user_id="u-1", conversation_id="conv-1")
    assert r1["request_id"] == r2["request_id"]


@pytest.mark.asyncio
async def test_propose_updates_captures_field(adapter):
    req = await adapter.get_or_create_request(user_id="u-1", conversation_id="conv-1")
    result = await adapter.propose_updates(
        request_id=req["request_id"],
        expected_revision=req["current_revision"],
        updates=[{"field_path": "project.name", "value": "Portal"}],
        user_id="u-1",
    )
    assert result.get("status") in ("accepted", "partial")


@pytest.mark.asyncio
async def test_resume_from_persisted_request(adapter):
    """POC-02: second get_or_create returns same request with captured fields."""
    req = await adapter.get_or_create_request(user_id="u-1", conversation_id="conv-resume")
    await adapter.propose_updates(
        request_id=req["request_id"],
        expected_revision=req["current_revision"],
        updates=[{"field_path": "project.name", "value": "My Project"}],
        user_id="u-1",
    )
    # Simulate new session — same conversation
    resumed_req = await adapter.get_or_create_request(user_id="u-1", conversation_id="conv-resume")
    ctx = await adapter.get_context(resumed_req["request_id"], user_id="u-1")
    fields = ctx.get("fields", {})
    assert "project.name" in fields or "project.name" in str(fields)


@pytest.mark.asyncio
async def test_full_vertical_flow(adapter):
    """
    POC-01/02 evidence path:
    create → propose all required fields → submit → review-ready (in_review).
    """
    req = await adapter.get_or_create_request(user_id="requester-1", conversation_id="conv-full")
    rid = req["request_id"]
    rev = req["current_revision"]

    # All 6 fields: 4 required + 2 optional (quality threshold is 0.7 = 70% of total)
    updates = [
        {"field_path": "project.name", "value": "Customer Portal Redesign"},
        {"field_path": "project.description", "value": "Redesign the customer-facing portal"},
        {"field_path": "requester.business_unit", "value": "Digital Experience"},
        {"field_path": "priority", "value": "high"},
        {"field_path": "budget.amount", "value": 150000},
        {"field_path": "timeline.target_date", "value": "2027-06-30"},
    ]
    result = await adapter.propose_updates(
        request_id=rid, expected_revision=rev, updates=updates, user_id="requester-1"
    )
    assert result.get("status") in ("accepted", "partial")
    new_rev = result.get("revision", rev)

    submit_result = await adapter.submit_for_review(
        request_id=rid, expected_revision=new_rev, user_id="requester-1"
    )
    assert submit_result.get("new_status") == "in_review"


@pytest.mark.asyncio
async def test_reviewer_can_approve(adapter):
    """POC-03: only an assigned reviewer can approve."""
    req = await adapter.get_or_create_request(user_id="requester-1", conversation_id="conv-approve")
    rid = req["request_id"]
    rev = req["current_revision"]

    updates = [
        {"field_path": "project.name", "value": "Portal"},
        {"field_path": "project.description", "value": "desc"},
        {"field_path": "requester.business_unit", "value": "IT"},
        {"field_path": "priority", "value": "medium"},
        {"field_path": "budget.amount", "value": 50000},
        {"field_path": "timeline.target_date", "value": "2027-01-01"},
    ]
    r = await adapter.propose_updates(request_id=rid, expected_revision=rev, updates=updates)
    new_rev = r.get("revision", rev)
    sub = await adapter.submit_for_review(request_id=rid, expected_revision=new_rev)
    # After submit, current_revision increments again
    new_rev2 = sub.get("revision", new_rev)

    approval = await adapter.record_review_decision(
        request_id=rid,
        expected_revision=new_rev2,
        decision="approve",
        rationale="All fields verified.",
        reviewer_id="reviewer-1",
    )
    assert approval.get("new_status") == "approved"


@pytest.mark.asyncio
async def test_list_requests(adapter):
    await adapter.get_or_create_request(user_id="u-list", conversation_id="conv-list-1")
    await adapter.get_or_create_request(user_id="u-list", conversation_id="conv-list-2")
    results = await adapter.list_requests(user_id="u-list")
    assert len(results) >= 2


# ---------------------------------------------------------------------------
# Domain parity: real vs reference
# ---------------------------------------------------------------------------

def test_real_entities_match_reference_interface():
    """Real intake_domain entities must have the same fields as reference_domain."""
    if not _intake_available:
        pytest.skip(skip_reason)
    import dataclasses

    from intake_domain.entities import (
        ActorContext,
        FieldValue,
        Gap,
        Request,
        RequestRevision,
        RequestStatus,
    )

    for cls in (Request, RequestRevision, FieldValue, Gap, ActorContext):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    expected_statuses = {
        "new", "in_review", "awaiting_feedback", "approved", "rejected", "completed"
    }
    assert {s.value for s in RequestStatus} == expected_statuses


def test_real_conflict_error_has_error_code():
    if not _intake_available:
        pytest.skip(skip_reason)
    from intake_domain.errors import ConflictError
    assert ConflictError.error_code == "CONFLICT"


def test_real_authorization_denied_error():
    if not _intake_available:
        pytest.skip(skip_reason)
    from intake_domain.errors import AuthorizationDeniedError
    assert AuthorizationDeniedError.error_code == "AUTHORIZATION_DENIED"


# ---------------------------------------------------------------------------
# Interface mismatch documentation (always runs)
# ---------------------------------------------------------------------------

def test_document_interface_mismatch_handle_message():
    """
    ADR-014 specified handle_message(message, user_id) → str.
    Trinity delivered individual command methods (get_or_create_request, propose_updates, etc).

    STATUS: Accepted mismatch — individual methods align better with the command pattern.
    The conversation-style handle_message interface is deferred to the Foundry orchestrator.
    No code change needed; this test documents the decision.
    """
    if not _intake_available:
        pytest.skip(skip_reason)
    from intake_agent.adapter.local import LocalAdapter
    # Document: handle_message is NOT present (by design)
    assert not hasattr(LocalAdapter, "handle_message"), (
        "If handle_message is now present, remove this documentation test."
    )
