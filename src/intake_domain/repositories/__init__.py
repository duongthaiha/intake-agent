"""Abstract repository protocols (ABCs) — no Azure SDK dependency."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from intake_domain.entities import (
    OutboxItem,
    Request,
    RequestRevision,
    StoredResult,
    TemplateVersion,
    WorkflowEvent,
)


class RequestRepository(ABC):
    """Persistence interface for intake requests."""

    persists_outbox_atomically: bool = True

    @abstractmethod
    async def get(self, request_id: str) -> Request | None: ...

    @abstractmethod
    async def get_or_create(
        self,
        request_id: str,
        factory: Callable[[], Request],
    ) -> tuple[Request, bool]:
        """Atomic get-or-create. Returns (request, created_flag)."""
        ...

    @abstractmethod
    async def save(
        self,
        request: Request,
        revision: RequestRevision,
        events: list[WorkflowEvent],
        expected_etag: str,
    ) -> str:
        """Persist request + revision + audit events + outbox atomically.
        Returns new ETag. Raises ConflictError on ETag mismatch."""
        ...

    @abstractmethod
    async def get_current_revision(self, request_id: str) -> RequestRevision | None: ...

    @abstractmethod
    async def list_by_user(self, user_id: str, tenant_id: str) -> list[Request]: ...


class TemplateRepository(ABC):
    @abstractmethod
    async def get_active(self, template_id: str) -> TemplateVersion | None: ...

    @abstractmethod
    async def get_version(self, template_id: str, version: str) -> TemplateVersion | None: ...


class OutboxRepository(ABC):
    @abstractmethod
    async def get_pending(self, batch_size: int = 25) -> list[OutboxItem]: ...

    @abstractmethod
    async def mark_dispatched(self, item_ids: list[str]) -> None: ...

    @abstractmethod
    async def enqueue(self, item: OutboxItem) -> None: ...


class IdempotencyStore(ABC):
    @abstractmethod
    async def check(self, scope_id: str, key: str) -> StoredResult | None: ...

    @abstractmethod
    async def store(
        self, scope_id: str, key: str, result: Any, ttl_days: int = 7
    ) -> None: ...


class ArtifactMetadata:
    def __init__(
        self,
        artifact_type: str,
        content_type: str,
        filename: str,
        request_id: str,
        revision: int,
        agent_version: str = "",
    ) -> None:
        self.artifact_type = artifact_type
        self.content_type = content_type
        self.filename = filename
        self.request_id = request_id
        self.revision = revision
        self.agent_version = agent_version


class ArtifactStore(ABC):
    @abstractmethod
    async def store_artifact(
        self,
        request_id: str,
        revision: int,
        content: bytes,
        metadata: ArtifactMetadata,
    ) -> str:
        """Store an artifact blob. Returns the blob URI."""
        ...

    @abstractmethod
    async def get_artifact_url(
        self, artifact_id: str, expiry_minutes: int = 15
    ) -> str:
        """Generate a time-limited access URL."""
        ...
