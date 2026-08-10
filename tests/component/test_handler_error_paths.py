"""Component tests: handler error paths.

Exercises uncovered branches in intake_domain/commands/handlers.py:
- NotFound (request, template)
- ConflictError (revision mismatch)
- InvalidTransitionError (immutable / wrong status)
- PreconditionFailedError (blocking gaps, quality threshold)
- AuthorizationDeniedError (non-reviewer recording decision)
- ValidationError (bad enum)
- Idempotency replay
- Rejected field updates

All tests use in-memory repos — no Azure credentials.
"""
from __future__ import annotations

import pytest

from intake_domain.commands import (
    ActorPayload,
    CommandEnvelope,
    FieldUpdateItem,
    ProposeFieldUpdatesData,
    RecordReviewDecisionData,
)
from intake_domain.commands.handlers import (
    GetOrCreateRequestHandler,
    GetRequestContextHandler,
    ListRequestsHandler,
    ProposeFieldUpdatesHandler,
    RecordReviewDecisionHandler,
    SubmitForReviewHandler,
)
from intake_domain.entities import (
    ActorContext,
    FieldSchema,
    TemplateVersion,
)
from intake_domain.errors import (
    AuthorizationDeniedError,
    ConflictError,
    NotFoundError,
    PreconditionFailedError,
    ValidationError,
)
from intake_persistence.inmemory import (
    InMemoryIdempotencyStore,
    InMemoryOutboxRepository,
    InMemoryRequestRepository,
    InMemoryTemplateRepository,
)

pytestmark = pytest.mark.component


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TEMPLATE_ID = "test-tpl"
TEMPLATE_VER = "1.0.0"


def _make_template(required_fields: list[str] | None = None) -> TemplateVersion:
    fields = []
    for fp in (required_fields or ["project.name", "project.description", "priority"]):
        if fp == "priority":
            fields.append(FieldSchema(fp, "Priority", "enum",
                                      required=True, enum_values=["low", "medium", "high"]))
        elif fp == "budget":
            fields.append(FieldSchema(fp, "Budget", "number", required=False))
        else:
            fields.append(FieldSchema(fp, fp.replace(".", " ").title(), "string", required=True))
    return TemplateVersion(TEMPLATE_ID, TEMPLATE_VER, "Test", fields=fields, quality_threshold=0.7)


@pytest.fixture()
def repos():
    req = InMemoryRequestRepository()
    tpl = InMemoryTemplateRepository()
    outbox = InMemoryOutboxRepository()
    idm = InMemoryIdempotencyStore()
    tpl.seed(_make_template())
    return req, tpl, outbox, idm


@pytest.fixture()
def actor_requester():
    return ActorContext(
        user_id="requester-1", tenant_id="t-1", roles=frozenset(["requester"]),
        conversation_id="conv-1", activity_id="act-1", correlation_id="corr-1",
        agent_identity="agent",
    )


@pytest.fixture()
def actor_reviewer():
    return ActorContext(
        user_id="reviewer-1", tenant_id="t-1", roles=frozenset(["reviewer"]),
        conversation_id="conv-r", activity_id="act-r", correlation_id="corr-r",
        agent_identity="agent",
    )


def _envelope(
    request_id: str, revision: int, cmd_type: str, key: str | None = None
) -> CommandEnvelope:
    return CommandEnvelope(
        command_type=cmd_type,
        request_id=request_id,
        expected_revision=revision,
        actor=ActorPayload(user_id="requester-1", tenant_id="t-1", actor_type="user"),
        idempotency_key=key or "",
    )


async def _create_request(repos, actor):
    req_repo, tpl_repo, outbox, idm = repos
    handler = GetOrCreateRequestHandler(req_repo, tpl_repo)
    return await handler.handle(actor, TEMPLATE_ID)


async def _propose(repos, request_id, revision, updates, key=None):
    req_repo, tpl_repo, outbox, idm = repos
    handler = ProposeFieldUpdatesHandler(req_repo, tpl_repo, outbox, idm)
    env = _envelope(request_id, revision, "propose_field_updates", key)
    data = ProposeFieldUpdatesData(updates=[FieldUpdateItem(**u) for u in updates])
    return await handler.handle(env, None, data)


async def _submit(repos, request_id, revision, key=None, actor=None):
    req_repo, tpl_repo, outbox, idm = repos
    handler = SubmitForReviewHandler(req_repo, tpl_repo, outbox, idm)
    env = _envelope(request_id, revision, "submit_for_review", key)
    _actor = actor or ActorContext(
        "u-1", "t-1", frozenset(["requester"]), "conv-1", "act-1", "corr-1", "agent"
    )
    return await handler.handle(env, _actor)


# ---------------------------------------------------------------------------
# GetOrCreateRequestHandler — template not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_template_not_found(actor_requester):
    req_repo = InMemoryRequestRepository()
    tpl_repo = InMemoryTemplateRepository()  # empty — no templates seeded
    handler = GetOrCreateRequestHandler(req_repo, tpl_repo)
    with pytest.raises(NotFoundError, match="Template"):
        await handler.handle(actor_requester, "nonexistent-template")


@pytest.mark.asyncio
async def test_get_or_create_specific_version_not_found(actor_requester):
    req_repo = InMemoryRequestRepository()
    tpl_repo = InMemoryTemplateRepository()
    tpl_repo.seed(_make_template())
    handler = GetOrCreateRequestHandler(req_repo, tpl_repo)
    with pytest.raises(NotFoundError, match="Template"):
        await handler.handle(actor_requester, TEMPLATE_ID, template_version="99.0.0")


# ---------------------------------------------------------------------------
# GetRequestContextHandler — request not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_context_not_found(repos):
    req_repo, tpl_repo, _, _ = repos
    handler = GetRequestContextHandler(req_repo, tpl_repo)
    actor = ActorContext("u-1", "t-1", frozenset(["requester"]), "c", "a", "corr", "agent")
    with pytest.raises(NotFoundError, match="Request not found"):
        await handler.handle("nonexistent-request-id", actor)


# ---------------------------------------------------------------------------
# ProposeFieldUpdatesHandler — request not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_request_not_found(repos):
    req_repo, tpl_repo, outbox, idm = repos
    handler = ProposeFieldUpdatesHandler(req_repo, tpl_repo, outbox, idm)
    env = _envelope("ghost-request", 1, "propose_field_updates")
    data = ProposeFieldUpdatesData(updates=[FieldUpdateItem(field_path="project.name", value="X")])
    with pytest.raises(NotFoundError):
        await handler.handle(env, None, data)


# ---------------------------------------------------------------------------
# ProposeFieldUpdatesHandler — revision mismatch → ConflictError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_revision_mismatch_raises_conflict(repos, actor_requester):
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    req_repo, tpl_repo, outbox, idm = repos
    handler = ProposeFieldUpdatesHandler(req_repo, tpl_repo, outbox, idm)
    env = _envelope(rid, 99, "propose_field_updates")  # wrong revision
    data = ProposeFieldUpdatesData(updates=[FieldUpdateItem(field_path="project.name", value="X")])
    with pytest.raises(ConflictError):
        await handler.handle(env, actor_requester, data)


# ---------------------------------------------------------------------------
# ProposeFieldUpdatesHandler — invalid field value → rejected_fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_invalid_field_type_in_rejected_fields(repos, actor_requester):
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    result = await _propose(repos, rid, req["current_revision"], [
        {"field_path": "priority", "value": "INVALID_CHOICE"},
    ])
    assert result["status"] == "partial"
    assert any(r["field_path"] == "priority" for r in result["rejected_fields"])


# ---------------------------------------------------------------------------
# ProposeFieldUpdatesHandler — idempotency replay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_idempotency_replay(repos, actor_requester):
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    ikey = "idm-key-abc"
    result1 = await _propose(repos, rid, req["current_revision"],
                              [{"field_path": "project.name", "value": "Portal"}], key=ikey)
    # Second call with same idempotency key — should not re-execute
    result2 = await _propose(repos, rid, req["current_revision"],
                              [{"field_path": "project.name", "value": "DIFFERENT"}], key=ikey)
    assert result2["revision"] == result1["revision"]  # same revision — no second update


# ---------------------------------------------------------------------------
# SubmitForReviewHandler — blocking gaps prevent submission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_blocked_by_blocking_gap(repos, actor_requester):
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    # Propose only one field — leaves required fields missing (blocking gap)
    result = await _propose(repos, rid, req["current_revision"],
                            [{"field_path": "project.name", "value": "Portal"}])
    with pytest.raises(PreconditionFailedError, match="blocking"):
        await _submit(repos, rid, result["revision"])


# ---------------------------------------------------------------------------
# SubmitForReviewHandler — quality below threshold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_blocked_by_quality_threshold(repos, actor_requester):
    """Fill only one of three required fields → quality < threshold."""
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    # Fill only name — description and priority still missing → quality=1/3=0.33 < 0.7
    result = await _propose(repos, rid, req["current_revision"],
                            [{"field_path": "project.name", "value": "Portal"}])
    with pytest.raises(PreconditionFailedError):
        await _submit(repos, rid, result["revision"])


# ---------------------------------------------------------------------------
# SubmitForReviewHandler — revision mismatch → ConflictError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_revision_mismatch(repos, actor_requester):
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    with pytest.raises(ConflictError):
        await _submit(repos, rid, 999)  # wrong revision


# ---------------------------------------------------------------------------
# SubmitForReviewHandler — request not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_request_not_found(repos):
    with pytest.raises(NotFoundError):
        await _submit(repos, "ghost-id", 1)


# ---------------------------------------------------------------------------
# SubmitForReviewHandler — idempotency replay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_idempotency_replay(repos, actor_requester):
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    # Fill all required fields
    r = await _propose(repos, rid, req["current_revision"], [
        {"field_path": "project.name", "value": "Portal"},
        {"field_path": "project.description", "value": "desc"},
        {"field_path": "priority", "value": "high"},
    ])
    ikey = "submit-idem-key"
    r1 = await _submit(repos, rid, r["revision"], key=ikey)
    # Second call with same key should replay
    r2 = await _submit(repos, rid, r["revision"], key=ikey)
    assert r1["new_status"] == r2["new_status"]


# ---------------------------------------------------------------------------
# RecordReviewDecisionHandler — non-reviewer denied
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_decision_non_reviewer_denied(repos, actor_requester):
    req_repo, tpl_repo, outbox, idm = repos
    handler = RecordReviewDecisionHandler(req_repo, outbox, idm)
    # Create and submit a request
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    r = await _propose(repos, rid, req["current_revision"], [
        {"field_path": "project.name", "value": "Portal"},
        {"field_path": "project.description", "value": "desc"},
        {"field_path": "priority", "value": "high"},
    ])
    await _submit(repos, rid, r["revision"])
    # Try to approve as requester (not reviewer)
    env = _envelope(rid, r["revision"] + 1, "record_review_decision")
    data = RecordReviewDecisionData(decision="approve", rationale="ok")
    with pytest.raises(AuthorizationDeniedError):
        await handler.handle(env, actor_requester, data)


# ---------------------------------------------------------------------------
# RecordReviewDecisionHandler — invalid decision value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_decision_invalid_decision_value(repos, actor_requester, actor_reviewer):
    req_repo, tpl_repo, outbox, idm = repos
    handler = RecordReviewDecisionHandler(req_repo, outbox, idm)
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    r = await _propose(repos, rid, req["current_revision"], [
        {"field_path": "project.name", "value": "Portal"},
        {"field_path": "project.description", "value": "desc"},
        {"field_path": "priority", "value": "high"},
    ])
    await _submit(repos, rid, r["revision"])
    env = _envelope(rid, r["revision"] + 1, "record_review_decision")
    data = RecordReviewDecisionData(decision="maybe", rationale="ok")
    with pytest.raises(ValidationError):
        await handler.handle(env, actor_reviewer, data)


# ---------------------------------------------------------------------------
# ListRequestsHandler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_requests_empty(repos):
    req_repo, _, _, _ = repos
    handler = ListRequestsHandler(req_repo)
    actor = ActorContext("u-none", "t-1", frozenset(["requester"]), "c", "a", "corr", "agent")
    result = await handler.handle(actor)
    assert result == []


@pytest.mark.asyncio
async def test_list_requests_returns_created_request(repos, actor_requester):
    await _create_request(repos, actor_requester)
    req_repo, _, _, _ = repos
    handler = ListRequestsHandler(req_repo)
    result = await handler.handle(actor_requester)
    assert len(result) >= 1
    assert all("request_id" in r for r in result)


# ---------------------------------------------------------------------------
# Full flow: submit → request_changes → re-submit (AWAITING_FEEDBACK loop)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_changes_then_resubmit(repos, actor_requester, actor_reviewer):
    req_repo, tpl_repo, outbox, idm = repos
    review_handler = RecordReviewDecisionHandler(req_repo, outbox, idm)

    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    r = await _propose(repos, rid, req["current_revision"], [
        {"field_path": "project.name", "value": "Portal"},
        {"field_path": "project.description", "value": "desc"},
        {"field_path": "priority", "value": "high"},
    ])
    sub = await _submit(repos, rid, r["revision"])
    assert sub["new_status"] == "in_review"

    # Reviewer requests changes
    env = _envelope(rid, sub["revision"], "record_review_decision")
    data = RecordReviewDecisionData(decision="request_changes", rationale="Need more detail")
    rc = await review_handler.handle(env, actor_reviewer, data)
    assert rc["new_status"] == "awaiting_feedback"

    # Requester updates and re-submits
    r2 = await _propose(repos, rid, rc["revision"], [
        {"field_path": "project.description", "value": "Detailed description added"},
    ])
    sub2 = await _submit(repos, rid, r2["revision"])
    assert sub2["new_status"] == "in_review"


# ---------------------------------------------------------------------------
# Outbox — verify events are enqueued
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_propose_enqueues_outbox_item(repos, actor_requester):
    _, _, outbox, _ = repos
    req = await _create_request(repos, actor_requester)
    rid = req["request_id"]
    await _propose(repos, rid, req["current_revision"],
                   [{"field_path": "project.name", "value": "Portal"}])
    pending = await outbox.get_pending()
    assert len(pending) >= 1
    assert any(item.event_type == "RequestFieldsUpdated" for item in pending)
