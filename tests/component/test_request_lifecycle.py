"""Component tests: request lifecycle with in-memory repositories.

Tests the full vertical flow from ADR-013 §Thin vertical flow:
  get_or_create_request → propose_field_updates → get_request_context
  → submit_for_review → record_review_decision (approve path)

No Azure credentials required.  Uses InMemoryRequestRepository.
"""
from __future__ import annotations

import uuid

import pytest
from reference_domain import (
    ActorType,
    FieldValue,
    Gap,
    GapSeverity,
    GapStatus,
    InMemoryRequestRepository,
    InvalidTransitionError,
    PreconditionFailedError,
    Request,
    RequestRevision,
    RequestStatus,
    ValidationStatus,
    WorkflowEvent,
    assert_valid_transition,
    derive_request_id,
    make_request,
    make_revision,
    now,
)

pytestmark = pytest.mark.component


# ---------------------------------------------------------------------------
# Helper: simulate the domain service operations using reference domain
# ---------------------------------------------------------------------------

async def get_or_create(
    repo: InMemoryRequestRepository, tenant_id: str, conversation_id: str, requester_id: str
) -> tuple[Request, bool]:
    request_id = derive_request_id(tenant_id, conversation_id)
    req, created = await repo.get_or_create(
        request_id,
        lambda: make_request(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            requester_id=requester_id,
        ),
    )
    if created:
        rev = make_revision(request_id)
        await repo.save(req, rev, [], req.etag)
    return req, created


async def propose_updates(
    repo: InMemoryRequestRepository,
    request: Request,
    updates: list[FieldValue],
    command_id: str | None = None,
) -> RequestRevision:
    rev = await repo.get_current_revision(request.request_id)
    assert rev is not None
    new_fields = dict(rev.fields)
    for fv in updates:
        new_fields[fv.field_path] = fv
    new_rev = make_revision(
        request.request_id,
        revision=rev.revision + 1,
        fields=new_fields,
        gaps=rev.gaps,
        quality_score=rev.quality_score,
    )
    evt = WorkflowEvent(
        event_id=str(uuid.uuid4()),
        request_id=request.request_id,
        revision=new_rev.revision,
        actor_id="user-1",
        actor_type=ActorType.USER,
        command_id=command_id or str(uuid.uuid4()),
        prior_state=request.status,
        new_state=request.status,
        occurred_at=now(),
    )
    request.current_revision = new_rev.revision
    await repo.save(request, new_rev, [evt], request.etag)
    return new_rev


async def submit_for_review(
    repo: InMemoryRequestRepository, request: Request
) -> None:
    rev = await repo.get_current_revision(request.request_id)
    assert rev is not None
    blocking = [
        g for g in rev.gaps
        if g.severity == GapSeverity.BLOCKING and g.status == GapStatus.OPEN
    ]
    if blocking:
        raise PreconditionFailedError(
            f"Blocking gaps must be resolved: {[g.gap_id for g in blocking]}"
        )
    assert_valid_transition(request.status, RequestStatus.IN_REVIEW)
    prior = request.status
    request.status = RequestStatus.IN_REVIEW
    rev.immutable = True
    evt = WorkflowEvent(
        event_id=str(uuid.uuid4()),
        request_id=request.request_id,
        revision=rev.revision,
        actor_id="user-1",
        actor_type=ActorType.USER,
        command_id=str(uuid.uuid4()),
        prior_state=prior,
        new_state=RequestStatus.IN_REVIEW,
        occurred_at=now(),
    )
    await repo.save(request, rev, [evt], request.etag)


async def record_approval(
    repo: InMemoryRequestRepository, request: Request, reviewer_id: str
) -> None:
    assert_valid_transition(request.status, RequestStatus.APPROVED)
    prior = request.status
    request.status = RequestStatus.APPROVED
    rev = await repo.get_current_revision(request.request_id)
    evt = WorkflowEvent(
        event_id=str(uuid.uuid4()),
        request_id=request.request_id,
        revision=rev.revision if rev else 1,
        actor_id=reviewer_id,
        actor_type=ActorType.USER,
        command_id=str(uuid.uuid4()),
        prior_state=prior,
        new_state=RequestStatus.APPROVED,
        occurred_at=now(),
    )
    await repo.save(request, rev, [evt], request.etag)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_new_request(repo: InMemoryRequestRepository):
    req, created = await get_or_create(repo, "t-1", "c-1", "user-1")
    assert created is True
    assert req.status == RequestStatus.NEW
    assert req.current_revision == 1


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(repo: InMemoryRequestRepository):
    req1, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    req2, created = await get_or_create(repo, "t-1", "c-1", "user-1")
    assert created is False
    assert req1.request_id == req2.request_id


@pytest.mark.asyncio
async def test_different_conversations_create_different_requests(repo: InMemoryRequestRepository):
    req1, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    req2, _ = await get_or_create(repo, "t-1", "c-2", "user-1")
    assert req1.request_id != req2.request_id


@pytest.mark.asyncio
async def test_propose_field_updates_saves_fields(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    fv = FieldValue("project.name", "My Project", validation_status=ValidationStatus.VALID)
    rev = await propose_updates(repo, req, [fv])
    assert "project.name" in rev.fields
    assert rev.fields["project.name"].value == "My Project"


@pytest.mark.asyncio
async def test_propose_multiple_fields(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    updates = [
        FieldValue("project.name", "Portal"),
        FieldValue("project.budget", 50000),
        FieldValue("project.owner", "Alice"),
    ]
    rev = await propose_updates(repo, req, updates)
    assert len(rev.fields) == 3


@pytest.mark.asyncio
async def test_resume_from_persisted_request(repo: InMemoryRequestRepository):
    """POC-02: interrupted session resumes from persisted request."""
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    fv = FieldValue("project.name", "My Project")
    await propose_updates(repo, req, [fv])

    # Simulate new session by re-loading from repo
    resumed = await repo.get(req.request_id)
    assert resumed is not None
    rev = await repo.get_current_revision(req.request_id)
    assert "project.name" in rev.fields
    assert rev.fields["project.name"].value == "My Project"


@pytest.mark.asyncio
async def test_submit_for_review_transitions_to_in_review(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    await submit_for_review(repo, req)
    loaded = await repo.get(req.request_id)
    assert loaded.status == RequestStatus.IN_REVIEW


@pytest.mark.asyncio
async def test_submit_freezes_revision(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    await submit_for_review(repo, req)
    rev = await repo.get_current_revision(req.request_id)
    assert rev.immutable is True


@pytest.mark.asyncio
async def test_submit_blocked_by_open_blocking_gap(
    repo: InMemoryRequestRepository, blocking_gap: Gap
):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    rev = await repo.get_current_revision(req.request_id)
    rev.gaps.append(blocking_gap)
    await repo.save(req, rev, [], req.etag)

    with pytest.raises(PreconditionFailedError):
        await submit_for_review(repo, req)


@pytest.mark.asyncio
async def test_submit_succeeds_when_blocking_gap_resolved(
    repo: InMemoryRequestRepository, blocking_gap: Gap
):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    rev = await repo.get_current_revision(req.request_id)
    blocking_gap.status = GapStatus.RESOLVED
    rev.gaps.append(blocking_gap)
    await repo.save(req, rev, [], req.etag)

    await submit_for_review(repo, req)
    loaded = await repo.get(req.request_id)
    assert loaded.status == RequestStatus.IN_REVIEW


@pytest.mark.asyncio
async def test_warning_gap_does_not_block_submission(
    repo: InMemoryRequestRepository, warning_gap: Gap
):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    rev = await repo.get_current_revision(req.request_id)
    rev.gaps.append(warning_gap)
    await repo.save(req, rev, [], req.etag)

    await submit_for_review(repo, req)
    loaded = await repo.get(req.request_id)
    assert loaded.status == RequestStatus.IN_REVIEW


@pytest.mark.asyncio
async def test_full_vertical_flow(repo: InMemoryRequestRepository):
    """Create → capture → submit → approve."""
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    await propose_updates(repo, req, [FieldValue("project.name", "Portal")])
    await submit_for_review(repo, req)
    await record_approval(repo, req, reviewer_id="reviewer-1")
    final = await repo.get(req.request_id)
    assert final.status == RequestStatus.APPROVED


@pytest.mark.asyncio
async def test_approved_revision_is_immutable(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    await submit_for_review(repo, req)
    await record_approval(repo, req, reviewer_id="reviewer-1")
    rev = await repo.get_current_revision(req.request_id)
    assert rev.immutable is True


@pytest.mark.asyncio
async def test_workflow_events_are_recorded(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    await propose_updates(repo, req, [FieldValue("project.name", "X")])
    await submit_for_review(repo, req)
    events = repo.all_events()
    assert len(events) >= 1
    request_events = [e for e in events if e.request_id == req.request_id]
    assert len(request_events) >= 1


@pytest.mark.asyncio
async def test_cannot_submit_twice(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    await submit_for_review(repo, req)
    with pytest.raises(InvalidTransitionError):
        await submit_for_review(repo, req)


@pytest.mark.asyncio
async def test_cannot_approve_from_new(repo: InMemoryRequestRepository):
    req, _ = await get_or_create(repo, "t-1", "c-1", "user-1")
    with pytest.raises(InvalidTransitionError):
        await record_approval(repo, req, "reviewer-1")
