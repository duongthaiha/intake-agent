# Repository Interfaces

All repository protocols live in `src/intake_domain/repositories/`. They define abstract interfaces with no Azure SDK dependency.

## RequestRepository

```python
from abc import ABC, abstractmethod
from intake_domain.entities import Request, RequestRevision, WorkflowEvent, FieldValue, Gap

class RequestRepository(ABC):
    """Persistence interface for intake requests."""

    @abstractmethod
    async def get(self, request_id: str) -> Request | None:
        """Load a request by ID. Returns None if not found."""
        ...

    @abstractmethod
    async def get_or_create(
        self, request_id: str, factory: Callable[[], Request]
    ) -> tuple[Request, bool]:
        """Atomic get-or-create. Returns (request, created_flag).
        Uses conditional create to prevent duplicates."""
        ...

    @abstractmethod
    async def save(
        self, request: Request, revision: RequestRevision,
        events: list[WorkflowEvent], expected_etag: str
    ) -> str:
        """Persist request + revision + audit events + outbox in one transaction.
        Returns new ETag. Raises ConflictError on ETag mismatch."""
        ...

    @abstractmethod
    async def get_current_revision(self, request_id: str) -> RequestRevision | None:
        """Load the latest revision for a request."""
        ...
```

## TemplateRepository

```python
class TemplateRepository(ABC):
    @abstractmethod
    async def get_active(self, template_id: str) -> TemplateVersion | None:
        """Load the currently active version of a template."""
        ...

    @abstractmethod
    async def get_version(self, template_id: str, version: str) -> TemplateVersion | None:
        """Load a specific template version."""
        ...
```

## OutboxRepository

```python
class OutboxRepository(ABC):
    @abstractmethod
    async def get_pending(self, batch_size: int = 25) -> list[OutboxItem]:
        """Load uncommitted outbox items for dispatch."""
        ...

    @abstractmethod
    async def mark_dispatched(self, item_ids: list[str]) -> None:
        """Mark items as successfully published to Service Bus."""
        ...
```

## IdempotencyStore

```python
class IdempotencyStore(ABC):
    @abstractmethod
    async def check(self, scope_id: str, key: str) -> StoredResult | None:
        """Check if a command was already processed. Returns stored result or None."""
        ...

    @abstractmethod
    async def store(self, scope_id: str, key: str, result: Any, ttl_days: int = 7) -> None:
        """Store a command result for replay."""
        ...
```

## ArtifactStore

```python
class ArtifactStore(ABC):
    @abstractmethod
    async def store_artifact(
        self, request_id: str, revision: int,
        content: bytes, metadata: ArtifactMetadata
    ) -> str:
        """Store an artifact blob. Returns the blob URI."""
        ...

    @abstractmethod
    async def get_artifact_url(
        self, artifact_id: str, expiry_minutes: int = 15
    ) -> str:
        """Generate a time-limited access URL."""
        ...
```

## Implementation mapping

| Protocol | In-memory (tests) | Azure adapter |
|----------|-------------------|---------------|
| `RequestRepository` | `InMemoryRequestRepository` | `CosmosRequestRepository` |
| `TemplateRepository` | `InMemoryTemplateRepository` | `CosmosTemplateRepository` |
| `OutboxRepository` | `InMemoryOutboxRepository` | `CosmosOutboxRepository` |
| `IdempotencyStore` | `InMemoryIdempotencyStore` | `CosmosIdempotencyStore` |
| `ArtifactStore` | `InMemoryArtifactStore` | `BlobArtifactStore` |

### In-memory implementations

Located in `src/intake_persistence/inmemory/`. These are production-quality implementations used in unit and component tests. They enforce the same concurrency semantics (ETag checks, conditional creates) using Python dicts and locks.

### Cosmos/Blob adapters

Located in `src/intake_persistence/cosmos/` and `src/intake_persistence/blob/`:

- `CosmosRequestRepository` stores the request projection, revisions, workflow
  events, and outbox records in the configured request-state container
  (`request-state` in production) partitioned by `/requestId`. A state change,
  audit event, and its outbox record are committed in one transactional batch
  guarded by the request projection ETag. Physical container names are supplied
  through configuration; the retained legacy `requests` container is not used.
- `CosmosOutboxRepository` queries committed outbox records and marks only
  Service Bus-acknowledged records dispatched. Durable request repositories own
  the atomic outbox write, so handlers do not perform a second fallible enqueue.
  Explicit enqueue remains exact-payload idempotent by event ID and rejects
  differing payloads as a collision.
- `CosmosTemplateRepository` reads immutable template versions from `templates`.
  Every template document carries a canonical Draft 2020-12 `jsonSchema` that
  is adapted to `TemplateVersion`. Documents without `jsonSchema` are rejected.
  partitioned by `/templateId`.
- `CosmosIdempotencyStore` uses item-level TTL documents in `idempotency`
  partitioned by `/scopeId`.
- `BlobArtifactStore` uses deterministic versioned names, conditional create,
  SHA-256 replay detection, and managed-identity user-delegation SAS URLs.
- `ServiceBusOutboxDispatcher` publishes to the configured queue
  (`domain-events-durable` in production) with `message_id=event_id` and marks
  an outbox record dispatched only after Service Bus acknowledges the send.

### Dependency injection

All command handlers receive repository protocols via constructor injection. The composition root (in `intake_agent/config.py` or Functions entry point) selects concrete implementations based on environment configuration.
