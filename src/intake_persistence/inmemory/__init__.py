"""In-memory repository implementations.

Production-quality: enforce the same ETag/concurrency semantics as the Cosmos
adapters, using Python dicts and asyncio locks. Used in tests and local demo mode.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from intake_domain.entities import (
    OutboxItem,
    Request,
    RequestRevision,
    StoredResult,
    TemplateVersion,
    WorkflowEvent,
)
from intake_domain.errors import ConflictError, NotFoundError
from intake_domain.repositories import (
    ArtifactMetadata,
    ArtifactStore,
    IdempotencyStore,
    OutboxRepository,
    RequestRepository,
    TemplateRepository,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _make_etag(request_id: str, revision: int, ts: datetime) -> str:
    raw = f"{request_id}:{revision}:{ts.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# InMemoryRequestRepository
# ---------------------------------------------------------------------------

class InMemoryRequestRepository(RequestRepository):
    persists_outbox_atomically = False

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._requests: dict[str, Request] = {}
        self._revisions: dict[str, RequestRevision] = {}
        self._events: dict[str, list[WorkflowEvent]] = {}

    async def get(self, request_id: str) -> Request | None:
        return copy.deepcopy(self._requests.get(request_id))

    async def get_or_create(
        self,
        request_id: str,
        factory: Callable[[], Request],
    ) -> tuple[Request, bool]:
        async with self._lock:
            if request_id in self._requests:
                return copy.deepcopy(self._requests[request_id]), False
            new_req = factory()
            new_req.etag = _make_etag(request_id, new_req.current_revision, new_req.created_at)
            self._requests[request_id] = copy.deepcopy(new_req)
            # Create empty initial revision
            initial_rev = RequestRevision(
                request_id=request_id,
                revision=new_req.current_revision,
                template_version=new_req.template_version,
                created_at=new_req.created_at,
            )
            self._revisions[request_id] = copy.deepcopy(initial_rev)
            self._events[request_id] = []
            return copy.deepcopy(new_req), True

    async def save(
        self,
        request: Request,
        revision: RequestRevision,
        events: list[WorkflowEvent],
        expected_etag: str,
    ) -> str:
        async with self._lock:
            existing = self._requests.get(request.request_id)
            if existing is not None and existing.etag != expected_etag:
                raise ConflictError(
                    f"ETag mismatch: expected {expected_etag!r}, got {existing.etag!r}",
                    current_revision=existing.current_revision,
                    current_etag=existing.etag,
                )
            new_etag = _make_etag(
                request.request_id, request.current_revision, _now()
            )
            req_copy = copy.deepcopy(request)
            req_copy.etag = new_etag
            self._requests[request.request_id] = req_copy
            self._revisions[request.request_id] = copy.deepcopy(revision)
            self._events.setdefault(request.request_id, []).extend(
                copy.deepcopy(e) for e in events
            )
            return new_etag

    async def get_current_revision(self, request_id: str) -> RequestRevision | None:
        rev = self._revisions.get(request_id)
        return copy.deepcopy(rev) if rev is not None else None

    async def list_by_user(self, user_id: str, tenant_id: str) -> list[Request]:
        return [
            copy.deepcopy(r)
            for r in self._requests.values()
            if r.requester_id == user_id and r.tenant_id == tenant_id
        ]


# ---------------------------------------------------------------------------
# InMemoryTemplateRepository
# ---------------------------------------------------------------------------

class InMemoryTemplateRepository(TemplateRepository):
    def __init__(self) -> None:
        self._templates: dict[str, dict[str, TemplateVersion]] = {}

    def seed(self, template: TemplateVersion) -> None:
        """Seed a template into the store (for tests and local demo)."""
        if template.template_id not in self._templates:
            self._templates[template.template_id] = {}
        self._templates[template.template_id][template.version] = copy.deepcopy(template)

    async def get_active(self, template_id: str) -> TemplateVersion | None:
        versions = self._templates.get(template_id, {})
        active = [t for t in versions.values() if t.is_active]
        if not active:
            return None
        return copy.deepcopy(max(active, key=lambda t: t.version))

    async def get_version(self, template_id: str, version: str) -> TemplateVersion | None:
        t = self._templates.get(template_id, {}).get(version)
        return copy.deepcopy(t) if t else None


# ---------------------------------------------------------------------------
# InMemoryOutboxRepository
# ---------------------------------------------------------------------------

class InMemoryOutboxRepository(OutboxRepository):
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[str, OutboxItem] = {}

    async def enqueue(self, item: OutboxItem) -> None:
        async with self._lock:
            self._items[item.item_id] = copy.deepcopy(item)

    async def get_pending(self, batch_size: int = 25) -> list[OutboxItem]:
        pending = [i for i in self._items.values() if not i.dispatched]
        return [copy.deepcopy(i) for i in pending[:batch_size]]

    async def mark_dispatched(self, item_ids: list[str]) -> None:
        async with self._lock:
            for iid in item_ids:
                if iid in self._items:
                    self._items[iid].dispatched = True


# ---------------------------------------------------------------------------
# InMemoryIdempotencyStore
# ---------------------------------------------------------------------------

class InMemoryIdempotencyStore(IdempotencyStore):
    def __init__(self) -> None:
        self._store: dict[str, StoredResult] = {}

    def _key(self, scope_id: str, key: str) -> str:
        return f"{scope_id}:{key}"

    async def check(self, scope_id: str, key: str) -> StoredResult | None:
        k = self._key(scope_id, key)
        result = self._store.get(k)
        if result is None:
            return None
        if result.expires_at < _now():
            del self._store[k]
            return None
        return result

    async def store(
        self, scope_id: str, key: str, result: Any, ttl_days: int = 7
    ) -> None:
        now = _now()
        self._store[self._key(scope_id, key)] = StoredResult(
            scope_id=scope_id,
            key=key,
            result=result,
            stored_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )


# ---------------------------------------------------------------------------
# InMemoryArtifactStore
# ---------------------------------------------------------------------------

class InMemoryArtifactStore(ArtifactStore):
    def __init__(self) -> None:
        self._artifacts: dict[str, bytes] = {}
        self._metadata: dict[str, ArtifactMetadata] = {}

    async def store_artifact(
        self,
        request_id: str,
        revision: int,
        content: bytes,
        metadata: ArtifactMetadata,
    ) -> str:
        artifact_id = f"artifact://{request_id}/{revision}/{metadata.filename}"
        self._artifacts[artifact_id] = content
        self._metadata[artifact_id] = metadata
        return artifact_id

    async def get_artifact_url(
        self, artifact_id: str, expiry_minutes: int = 15
    ) -> str:
        if artifact_id not in self._artifacts:
            raise NotFoundError("Artifact not found", artifact_id=artifact_id)
        return f"http://localhost/artifacts/{artifact_id}?expires_in={expiry_minutes}m"
