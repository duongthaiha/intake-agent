"""Contract tests: repository protocol compliance.

Verifies that the reference InMemory implementations fulfil every method
in the repository protocol definitions from docs/contracts/repository-interfaces.md.

When Trinity delivers src/intake_persistence/inmemory/, these tests will
switch to importing from there.  Any missing method surfaces as an
AttributeError/TypeError during collection — that is the intended behavior.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest
from reference_domain import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryRequestRepository,
    Request,
    RequestRepository,
    make_request,
    make_revision,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Protocol structural compliance
# ---------------------------------------------------------------------------

REQUIRED_REQUEST_REPO_METHODS = [
    "get",
    "get_or_create",
    "save",
    "get_current_revision",
]


@pytest.mark.parametrize("method", REQUIRED_REQUEST_REPO_METHODS)
def test_in_memory_request_repo_exposes_required_method(method: str):
    repo = InMemoryRequestRepository()
    assert hasattr(repo, method), f"InMemoryRequestRepository missing method: {method!r}"
    assert callable(getattr(repo, method))


REQUIRED_IDEMPOTENCY_STORE_METHODS = ["check", "store"]


@pytest.mark.parametrize("method", REQUIRED_IDEMPOTENCY_STORE_METHODS)
def test_in_memory_idempotency_store_exposes_required_method(method: str):
    store = InMemoryIdempotencyStore()
    assert hasattr(store, method)
    assert callable(getattr(store, method))


def test_request_repository_is_abstract_base():
    """RequestRepository must not be directly instantiatable."""
    with pytest.raises(TypeError):
        RequestRepository()  # type: ignore[abstract]


def test_idempotency_store_is_abstract_base():
    with pytest.raises(TypeError):
        IdempotencyStore()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# All protocol methods are coroutines (async)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", REQUIRED_REQUEST_REPO_METHODS)
def test_request_repo_methods_are_coroutines(method: str):
    repo = InMemoryRequestRepository()
    fn = getattr(repo, method)
    assert asyncio.iscoroutinefunction(fn), (
        f"InMemoryRequestRepository.{method} must be a coroutine"
    )


@pytest.mark.parametrize("method", REQUIRED_IDEMPOTENCY_STORE_METHODS)
def test_idempotency_store_methods_are_coroutines(method: str):
    store = InMemoryIdempotencyStore()
    fn = getattr(store, method)
    assert asyncio.iscoroutinefunction(fn)


# ---------------------------------------------------------------------------
# get returns None for unknown request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_unknown_returns_none(repo: InMemoryRequestRepository):
    result = await repo.get("nonexistent-request-id")
    assert result is None


# ---------------------------------------------------------------------------
# get_or_create atomicity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_returns_request_and_flag(repo: InMemoryRequestRepository):
    req, created = await repo.get_or_create(
        "req-001",
        lambda: make_request(),
    )
    assert isinstance(req, Request)
    assert created is True


@pytest.mark.asyncio
async def test_get_or_create_second_call_returns_false(repo: InMemoryRequestRepository):
    req1, _ = await repo.get_or_create("req-001", lambda: make_request())
    req2, created = await repo.get_or_create("req-001", lambda: make_request())
    assert created is False
    assert req1.request_id == req2.request_id


# ---------------------------------------------------------------------------
# save returns new ETag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_returns_nonempty_etag(repo: InMemoryRequestRepository):
    req = make_request()
    rev = make_revision(req.request_id)
    etag = await repo.save(req, rev, [], req.etag)
    assert isinstance(etag, str)
    assert len(etag) > 0


# ---------------------------------------------------------------------------
# get_current_revision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_revision_returns_none_before_save(repo: InMemoryRequestRepository):
    result = await repo.get_current_revision("unknown-req")
    assert result is None


@pytest.mark.asyncio
async def test_get_current_revision_returns_saved_revision(repo: InMemoryRequestRepository):
    req = make_request()
    rev = make_revision(req.request_id, revision=1)
    await repo.save(req, rev, [], req.etag)
    loaded = await repo.get_current_revision(req.request_id)
    assert loaded is not None
    assert loaded.revision == 1


@pytest.mark.asyncio
async def test_get_current_revision_reflects_latest_save(repo: InMemoryRequestRepository):
    req = make_request()
    rev1 = make_revision(req.request_id, revision=1)
    await repo.save(req, rev1, [], req.etag)

    rev2 = make_revision(req.request_id, revision=2)
    await repo.save(req, rev2, [], req.etag)

    latest = await repo.get_current_revision(req.request_id)
    assert latest.revision == 2


# ---------------------------------------------------------------------------
# Idempotency store protocol
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_missing_key_returns_none(idempotency: InMemoryIdempotencyStore):
    assert await idempotency.check("s-1", "k-1") is None


@pytest.mark.asyncio
async def test_store_then_check(idempotency: InMemoryIdempotencyStore):
    payload = {"status": "accepted"}
    await idempotency.store("s-1", "k-1", payload)
    result = await idempotency.check("s-1", "k-1")
    assert result == payload


# ---------------------------------------------------------------------------
# Check that protocol method signatures match the contract
# ---------------------------------------------------------------------------

def test_request_repo_get_signature():
    sig = inspect.signature(RequestRepository.get)
    params = list(sig.parameters.keys())
    assert "request_id" in params


def test_request_repo_save_signature():
    sig = inspect.signature(RequestRepository.save)
    params = list(sig.parameters.keys())
    for p in ("request", "revision", "events", "expected_etag"):
        assert p in params, f"save() missing parameter: {p!r}"


def test_idempotency_check_signature():
    sig = inspect.signature(IdempotencyStore.check)
    params = list(sig.parameters.keys())
    assert "scope_id" in params
    assert "key" in params


# ---------------------------------------------------------------------------
# Implementation mapping documentation check
# ---------------------------------------------------------------------------

EXPECTED_IMPLEMENTATIONS = {
    "RequestRepository": "InMemoryRequestRepository",
    "IdempotencyStore": "InMemoryIdempotencyStore",
}


@pytest.mark.parametrize("protocol,impl", EXPECTED_IMPLEMENTATIONS.items())
def test_implementation_is_subclass_of_protocol(protocol: str, impl: str):
    from reference_domain import (
        IdempotencyStore,
        InMemoryIdempotencyStore,
        InMemoryRequestRepository,
        RequestRepository,
    )
    proto_map = {
        "RequestRepository": RequestRepository,
        "IdempotencyStore": IdempotencyStore,
    }
    impl_map = {
        "InMemoryRequestRepository": InMemoryRequestRepository,
        "InMemoryIdempotencyStore": InMemoryIdempotencyStore,
    }
    assert issubclass(impl_map[impl], proto_map[protocol])
