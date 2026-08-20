"""Cosmos DB adapters with request partitioning and optimistic concurrency."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, NoReturn, Protocol
from uuid import uuid4

from azure.cosmos import exceptions
from intake_domain import (
    ActorContext,
    AuditEvent,
    DomainError,
    ErrorCode,
    IntakeRequest,
    Mutation,
    MutationReceipt,
    OutboxEvent,
    PendingEvent,
)

from intake_persistence.azure_errors import PermanentAzureError, TransientAzureError
from intake_persistence.serialization import request_from_document, request_to_document

INTERACTIVE_IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 60 * 60
ASYNC_IDEMPOTENCY_TTL_SECONDS = 30 * 24 * 60 * 60
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 449, 500, 502, 503, 504})


class CosmosContainer(Protocol):
    def read_item(self, *, item: str, partition_key: str) -> dict[str, Any]: ...

    def query_items(self, **kwargs: Any) -> Iterable[dict[str, Any]]: ...

    def execute_item_batch(
        self, *, batch_operations: list[tuple[Any, ...]], partition_key: str
    ) -> list[dict[str, Any]]: ...

    def create_item(self, body: dict[str, Any]) -> dict[str, Any]: ...

    def patch_item(self, **kwargs: Any) -> dict[str, Any]: ...

    def delete_item(self, **kwargs: Any) -> None: ...


class CosmosRequestStore:
    """RequestStore implementation using one transactional request partition."""

    def __init__(
        self,
        requests: CosmosContainer,
        idempotency: CosmosContainer,
        *,
        clock: Callable[[], datetime] | None = None,
        idempotency_ttl_seconds: int = INTERACTIVE_IDEMPOTENCY_TTL_SECONDS,
    ) -> None:
        if idempotency_ttl_seconds < 1:
            raise ValueError("idempotency_ttl_seconds must be positive")
        self._requests = requests
        self._idempotency = idempotency
        self._clock = clock or (lambda: datetime.now(UTC))
        self._idempotency_ttl_seconds = idempotency_ttl_seconds

    def get(self, request_id: str) -> IntakeRequest | None:
        try:
            document = self._requests.read_item(
                item="request",
                partition_key=request_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read request")
        return request_from_document(document)

    def list_by_owner(
        self, tenant_id: str, owner_id: str, limit: int
    ) -> Sequence[IntakeRequest]:
        return self._list(
            (
                "SELECT TOP @limit * FROM c WHERE c.docType = 'request' "
                "AND c.tenantId = @tenantId AND c.requesterId = @actorId "
                "ORDER BY c.updatedAt DESC"
            ),
            tenant_id,
            owner_id,
            limit,
        )

    def list_assigned(
        self, tenant_id: str, reviewer_id: str, limit: int
    ) -> Sequence[IntakeRequest]:
        return self._list(
            (
                "SELECT TOP @limit * FROM c WHERE c.docType = 'request' "
                "AND c.tenantId = @tenantId AND c.assignedReviewerId = @actorId "
                "AND c.status = 'in_review' ORDER BY c.updatedAt DESC"
            ),
            tenant_id,
            reviewer_id,
            limit,
        )

    def create_if_absent(
        self,
        request: IntakeRequest,
        actor: ActorContext,
        command_id: str,
        fingerprint: str,
    ) -> MutationReceipt:
        replay = self._replay(request.request_id, command_id, fingerprint, actor)
        if replay is not None:
            return replay
        existing = self.get(request.request_id)
        if existing is not None:
            receipt = _creation_receipt(existing, created=False, replayed=True)
            self._store_idempotency(
                request.request_id, command_id, fingerprint, actor, receipt
            )
            return receipt

        audit, outbox = _event_documents(
            request,
            actor,
            command_id,
            prior_state=None,
            events=(PendingEvent("RequestCreated", {}),),
            now=self._clock(),
        )
        operations: list[tuple[Any, ...]] = [
            ("create", (request_to_document(request),)),
            ("create", (audit,)),
            ("create", (outbox[0],)),
        ]
        try:
            self._requests.execute_item_batch(
                batch_operations=operations,
                partition_key=request.request_id,
            )
        except (exceptions.CosmosResourceExistsError, exceptions.CosmosBatchOperationError):
            winner = self.get(request.request_id)
            if winner is None:
                raise
            receipt = _creation_receipt(winner, created=False, replayed=True)
            self._store_idempotency(
                request.request_id, command_id, fingerprint, actor, receipt
            )
            return receipt
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "create request")

        receipt = _creation_receipt(request, created=True, replayed=False)
        self._store_idempotency(
            request.request_id, command_id, fingerprint, actor, receipt
        )
        return receipt

    def mutate(
        self,
        request_id: str,
        expected_version: int,
        actor: ActorContext,
        command_id: str,
        fingerprint: str,
        operation: Callable[[IntakeRequest], Mutation],
    ) -> MutationReceipt:
        replay = self._replay(request_id, command_id, fingerprint, actor)
        if replay is not None:
            return replay
        try:
            current_document = self._requests.read_item(
                item="request", partition_key=request_id
            )
        except exceptions.CosmosResourceNotFoundError as exc:
            raise DomainError(ErrorCode.NOT_FOUND, "The request was not found.") from exc
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read request for mutation")

        current = request_from_document(current_document)
        if current.version != expected_version:
            raise DomainError(
                ErrorCode.CONCURRENCY_CONFLICT,
                "The request changed; reload the latest context before retrying.",
                latest_revision=current.version,
            )
        candidate = deepcopy(current)
        prior_state = candidate.status.value
        mutation = operation(candidate)
        candidate.version += 1
        candidate.updated_at = self._clock()
        data = deepcopy(mutation.data)
        data.update(
            {
                "requestId": candidate.request_id,
                "requestRevision": candidate.version,
                "status": candidate.status.value,
            }
        )
        receipt = MutationReceipt(data=data, replayed=False)
        audit, outbox = _event_documents(
            candidate,
            actor,
            command_id,
            prior_state=prior_state,
            events=mutation.events,
            now=self._clock(),
        )
        operations = [
            (
                "replace",
                ("request", request_to_document(candidate)),
                {"if_match_etag": str(current_document.get("_etag", ""))},
            ),
            ("create", (audit,)),
            *(("create", (document,)) for document in outbox),
        ]
        try:
            self._requests.execute_item_batch(
                batch_operations=operations,
                partition_key=request_id,
            )
        except exceptions.CosmosAccessConditionFailedError:
            self._raise_concurrency(request_id)
        except exceptions.CosmosBatchOperationError as exc:
            if _batch_status_code(exc) in {409, 412}:
                self._raise_concurrency(request_id)
            _raise_cosmos_error(exc, "save request aggregate")
        except exceptions.CosmosHttpResponseError as exc:
            if int(exc.status_code or 0) == 412:
                self._raise_concurrency(request_id)
            _raise_cosmos_error(exc, "save request aggregate")

        self._store_idempotency(request_id, command_id, fingerprint, actor, receipt)
        return receipt

    def _list(
        self, query: str, tenant_id: str, actor_id: str, limit: int
    ) -> Sequence[IntakeRequest]:
        if limit < 1:
            return ()
        try:
            documents = self._requests.query_items(
                query=query,
                parameters=[
                    {"name": "@tenantId", "value": tenant_id},
                    {"name": "@actorId", "value": actor_id},
                    {"name": "@limit", "value": limit},
                ],
                enable_cross_partition_query=True,
                max_item_count=limit,
            )
            return tuple(request_from_document(document) for document in documents)
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "list requests")

    def _replay(
        self,
        request_id: str,
        command_id: str,
        fingerprint: str,
        actor: ActorContext,
    ) -> MutationReceipt | None:
        document_id = _idempotency_id(request_id, command_id)
        try:
            document = self._idempotency.read_item(
                item=document_id,
                partition_key=request_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read idempotency record")

        expires_at = _parse_datetime(document["expiresAt"])
        if expires_at <= self._clock():
            try:
                self._idempotency.delete_item(
                    item=document_id,
                    partition_key=request_id,
                )
            except exceptions.CosmosResourceNotFoundError:
                pass
            except exceptions.CosmosHttpResponseError as exc:
                _raise_cosmos_error(exc, "delete expired idempotency record")
            return None
        if (
            str(document["tenantId"]),
            str(document["actorId"]),
        ) != (actor.tenant_id, actor.actor_id):
            raise DomainError(
                ErrorCode.AUTHORIZATION_DENIED,
                "The command belongs to a different represented user.",
            )
        if str(document["fingerprint"]) != fingerprint:
            raise DomainError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "The command ID was already used with a different payload.",
            )
        return MutationReceipt(
            data=deepcopy(_json_mapping(document["result"])),
            replayed=True,
        )

    def _store_idempotency(
        self,
        request_id: str,
        command_id: str,
        fingerprint: str,
        actor: ActorContext,
        receipt: MutationReceipt,
    ) -> None:
        now = self._clock()
        document = {
            "id": _idempotency_id(request_id, command_id),
            "docType": "idempotency",
            "scopeId": request_id,
            "requestId": request_id,
            "commandId": command_id,
            "fingerprint": fingerprint,
            "tenantId": actor.tenant_id,
            "actorId": actor.actor_id,
            "result": deepcopy(receipt.data),
            "storedAt": _wire_datetime(now),
            "expiresAt": _wire_datetime(
                now + timedelta(seconds=self._idempotency_ttl_seconds)
            ),
            "ttl": self._idempotency_ttl_seconds,
        }
        try:
            self._idempotency.create_item(body=document)
        except exceptions.CosmosResourceExistsError:
            replay = self._replay(request_id, command_id, fingerprint, actor)
            if replay is None or replay.data != receipt.data:
                raise DomainError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "The command ID was already used with a different result.",
                ) from None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "store idempotency record")

    def _raise_concurrency(self, request_id: str) -> NoReturn:
        current = self.get(request_id)
        raise DomainError(
            ErrorCode.CONCURRENCY_CONFLICT,
            "The request changed; reload the latest context before retrying.",
            latest_revision=current.version if current is not None else None,
        )


class CosmosOutboxRepository:
    """Queries and settles durable outbox items after Service Bus acknowledgement."""

    def __init__(self, requests: CosmosContainer) -> None:
        self._requests = requests

    def get_pending(self, batch_size: int = 25) -> Sequence[OutboxEvent]:
        if batch_size < 1:
            return ()
        try:
            documents = self._requests.query_items(
                query=(
                    "SELECT TOP @batchSize * FROM c WHERE c.docType = 'outbox' "
                    "AND c.dispatched = false ORDER BY c.occurredAt ASC"
                ),
                parameters=[{"name": "@batchSize", "value": batch_size}],
                enable_cross_partition_query=True,
                max_item_count=batch_size,
            )
            return tuple(_outbox_from_document(document) for document in documents)
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read pending outbox")

    def mark_dispatched(self, events: Sequence[OutboxEvent]) -> None:
        now = _wire_datetime(datetime.now(UTC))
        for event in events:
            try:
                self._requests.patch_item(
                    item=f"outbox:{event.event_id}",
                    partition_key=event.request_id,
                    patch_operations=[
                        {"op": "set", "path": "/dispatched", "value": True},
                        {"op": "set", "path": "/dispatchedAt", "value": now},
                    ],
                )
            except exceptions.CosmosResourceNotFoundError:
                continue
            except exceptions.CosmosHttpResponseError as exc:
                _raise_cosmos_error(exc, "mark outbox dispatched")


class CosmosConsumerDeduplicationStore:
    """TTL-backed event receipt store for at-least-once consumers."""

    def __init__(
        self,
        container: CosmosContainer,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = ASYNC_IDEMPOTENCY_TTL_SECONDS,
    ) -> None:
        self._container = container
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl_seconds = ttl_seconds

    def has_processed(self, consumer: str, event_id: str) -> bool:
        document_id = _consumer_receipt_id(consumer, event_id)
        try:
            document = self._container.read_item(
                item=document_id,
                partition_key=consumer,
            )
        except exceptions.CosmosResourceNotFoundError:
            return False
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read consumer receipt")
        return _parse_datetime(document["expiresAt"]) > self._clock()

    def mark_processed(self, consumer: str, event_id: str) -> None:
        now = self._clock()
        document = {
            "id": _consumer_receipt_id(consumer, event_id),
            "docType": "consumerReceipt",
            "scopeId": consumer,
            "consumer": consumer,
            "eventId": event_id,
            "processedAt": _wire_datetime(now),
            "expiresAt": _wire_datetime(
                now + timedelta(seconds=self._ttl_seconds)
            ),
            "ttl": self._ttl_seconds,
        }
        try:
            self._container.create_item(body=document)
        except exceptions.CosmosResourceExistsError:
            return
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "store consumer receipt")


def _creation_receipt(
    request: IntakeRequest, *, created: bool, replayed: bool
) -> MutationReceipt:
    return MutationReceipt(
        data={
            "requestId": request.request_id,
            "requestRevision": request.version,
            "status": request.status.value,
            "created": created,
        },
        replayed=replayed,
    )


def _event_documents(
    request: IntakeRequest,
    actor: ActorContext,
    command_id: str,
    *,
    prior_state: str | None,
    events: tuple[PendingEvent, ...],
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    audit_type = events[0].event_type if events else "RequestChanged"
    audit = AuditEvent(
        event_id=str(uuid4()),
        event_type=audit_type,
        request_id=request.request_id,
        revision=request.version,
        actor_id=actor.actor_id,
        actor_roles=tuple(sorted(role.value for role in actor.roles)),
        correlation_id=actor.correlation_id,
        command_id=command_id,
        prior_state=prior_state,
        new_state=request.status.value,
        occurred_at=now,
    )
    audit_document = {
        "id": f"audit:{audit.event_id}",
        "docType": "audit",
        "requestId": audit.request_id,
        "eventId": audit.event_id,
        "eventType": audit.event_type,
        "revision": audit.revision,
        "actorId": audit.actor_id,
        "actorRoles": list(audit.actor_roles),
        "correlationId": audit.correlation_id,
        "commandId": audit.command_id,
        "priorState": audit.prior_state,
        "newState": audit.new_state,
        "occurredAt": _wire_datetime(audit.occurred_at),
    }
    outbox_documents: list[dict[str, Any]] = []
    for pending in events:
        outbox = OutboxEvent(
            event_id=str(uuid4()),
            event_type=pending.event_type,
            event_version="1.0",
            request_id=request.request_id,
            revision=request.version,
            correlation_id=actor.correlation_id,
            causation_id=command_id,
            occurred_at=now,
            actor_id=actor.actor_id,
            data=deepcopy(pending.data),
        )
        outbox_documents.append(_outbox_to_document(outbox))
    return audit_document, outbox_documents


def _outbox_to_document(event: OutboxEvent) -> dict[str, Any]:
    return {
        "id": f"outbox:{event.event_id}",
        "docType": "outbox",
        "requestId": event.request_id,
        "eventId": event.event_id,
        "eventType": event.event_type,
        "eventVersion": event.event_version,
        "revision": event.revision,
        "correlationId": event.correlation_id,
        "causationId": event.causation_id,
        "occurredAt": _wire_datetime(event.occurred_at),
        "actorId": event.actor_id,
        "data": deepcopy(event.data),
        "dispatched": False,
    }


def _outbox_from_document(document: dict[str, Any]) -> OutboxEvent:
    return OutboxEvent(
        event_id=str(document["eventId"]),
        event_type=str(document["eventType"]),
        event_version=str(document["eventVersion"]),
        request_id=str(document["requestId"]),
        revision=int(document["revision"]),
        correlation_id=str(document["correlationId"]),
        causation_id=str(document["causationId"]),
        occurred_at=_parse_datetime(document["occurredAt"]),
        actor_id=str(document["actorId"]),
        data=deepcopy(_json_mapping(document.get("data", {}))),
    )


def _idempotency_id(request_id: str, command_id: str) -> str:
    digest = sha256(f"{request_id}:{command_id}".encode()).hexdigest()
    return f"command:{digest}"


def _consumer_receipt_id(consumer: str, event_id: str) -> str:
    digest = sha256(f"{consumer}:{event_id}".encode()).hexdigest()
    return f"consumer:{digest}"


def _batch_status_code(exc: exceptions.CosmosBatchOperationError) -> int:
    try:
        response = exc.operation_responses[exc.error_index]
        return int(response.get("statusCode", response.get("status_code", 0)))
    except (AttributeError, IndexError, TypeError, ValueError):
        return int(getattr(exc, "status_code", 0) or 0)


def _raise_cosmos_error(exc: BaseException, operation: str) -> NoReturn:
    status_code = int(getattr(exc, "status_code", 0) or 0)
    message = f"Cosmos DB failed to {operation} (status={status_code})"
    if status_code in _TRANSIENT_STATUS_CODES:
        raise TransientAzureError(message) from exc
    raise PermanentAzureError(message) from exc


def _wire_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _json_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PermanentAzureError("Persisted JSON object has an invalid shape.")
    return {str(key): item for key, item in value.items()}
