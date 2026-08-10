"""Component tests: optimistic concurrency.

Verifies that the in-memory repository enforces ETag-based concurrency
controls identical to what CosmosRequestRepository will enforce.
(ADR-013 / contracts §Optimistic concurrency / POC-03)
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from reference_domain import (
    ActorType,
    ConflictError,
    InMemoryRequestRepository,
    WorkflowEvent,
    make_request,
    make_revision,
    now,
)

pytestmark = pytest.mark.component


async def _save(
    repo: InMemoryRequestRepository,
    etag: str,
    extra_field: str = "f",
) -> str:
    req = make_request()
    rev = make_revision(req.request_id)
    req.etag = etag
    repo._requests[req.request_id] = req
    repo._revisions[req.request_id] = rev
    return req.request_id, req


@pytest.mark.asyncio
async def test_save_with_correct_etag_succeeds(repo: InMemoryRequestRepository):
    req = make_request()
    rev = make_revision(req.request_id)
    initial_etag = req.etag
    repo._requests[req.request_id] = req
    repo._revisions[req.request_id] = rev

    new_etag = await repo.save(req, rev, [], initial_etag)
    assert new_etag != initial_etag  # ETag rotates on save


@pytest.mark.asyncio
async def test_save_with_stale_etag_raises_conflict(repo: InMemoryRequestRepository):
    req = make_request()
    rev = make_revision(req.request_id)
    repo._requests[req.request_id] = req
    repo._revisions[req.request_id] = rev
    correct_etag = req.etag

    # First save succeeds, rotating ETag
    await repo.save(req, rev, [], correct_etag)

    # Second save with old ETag should fail
    with pytest.raises(ConflictError):
        await repo.save(req, rev, [], correct_etag)  # stale


@pytest.mark.asyncio
async def test_conflict_error_carries_revision_info(repo: InMemoryRequestRepository):
    req = make_request()
    rev = make_revision(req.request_id)
    repo._requests[req.request_id] = req
    repo._revisions[req.request_id] = rev
    stale_etag = "stale-etag-value"

    with pytest.raises(ConflictError) as exc_info:
        await repo.save(req, rev, [], stale_etag)

    err = exc_info.value
    assert err.expected == stale_etag
    assert err.current == req.etag


@pytest.mark.asyncio
async def test_concurrent_saves_only_one_wins(repo: InMemoryRequestRepository):
    """Simulate two concurrent saves for the same request — one must fail."""
    req = make_request()
    rev = make_revision(req.request_id)
    repo._requests[req.request_id] = req
    repo._revisions[req.request_id] = rev
    original_etag = req.etag

    results = {"success": 0, "conflict": 0}

    async def save_task():
        try:
            import copy
            req_copy = copy.copy(req)
            rev_copy = make_revision(req.request_id, revision=2)
            await repo.save(req_copy, rev_copy, [], original_etag)
            results["success"] += 1
        except ConflictError:
            results["conflict"] += 1

    await asyncio.gather(save_task(), save_task())

    # Exactly one succeeds
    assert results["success"] == 1
    assert results["conflict"] == 1


@pytest.mark.asyncio
async def test_new_request_save_does_not_require_existing_etag(repo: InMemoryRequestRepository):
    """get_or_create uses factory pattern; the first save should succeed."""
    req = make_request()
    rev = make_revision(req.request_id)
    new_etag = await repo.save(req, rev, [], req.etag)
    assert new_etag


@pytest.mark.asyncio
async def test_events_stored_in_same_transaction(repo: InMemoryRequestRepository):
    """Events must be persisted in the same call as the state update."""
    req = make_request()
    rev = make_revision(req.request_id)
    repo._requests[req.request_id] = req

    evt = WorkflowEvent(
        event_id=str(uuid.uuid4()),
        request_id=req.request_id,
        revision=1,
        actor_id="user-1",
        actor_type=ActorType.USER,
        command_id=str(uuid.uuid4()),
        prior_state=None,
        new_state=None,
        occurred_at=now(),
    )
    await repo.save(req, rev, [evt], req.etag)
    assert any(e.event_id == evt.event_id for e in repo.all_events())
