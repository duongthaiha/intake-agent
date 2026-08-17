"""Azure Cosmos DB repositories using managed identity and transactional batches."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, cast

from azure.core import MatchConditions
from azure.cosmos import exceptions
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

from intake_domain.entities import (
    OutboxItem,
    Request,
    RequestRevision,
    StoredResult,
    TemplateVersion,
    WorkflowEvent,
)
from intake_domain.errors import (
    ConflictError,
    IdempotencyKeyCollisionError,
    PermanentError,
    TransientError,
)
from intake_domain.repositories import (
    IdempotencyStore,
    OutboxRepository,
    RequestRepository,
    TemplateRepository,
)
from intake_persistence._serialization import (
    outbox_from_document,
    outbox_to_document,
    request_from_document,
    request_to_document,
    revision_from_document,
    revision_to_document,
    stored_result_from_document,
    stored_result_to_document,
    template_from_document,
    template_to_document,
    workflow_event_to_document,
    workflow_event_to_outbox,
)

_TRANSIENT_STATUS_CODES = frozenset({408, 429, 449, 500, 502, 503, 504})


class CosmosRepositoryContext:
    """Shared Cosmos clients for one database and its product containers."""

    def __init__(
        self,
        endpoint: str,
        database: str,
        *,
        requests_container: str = "requests",
        templates_container: str = "templates",
        idempotency_container: str = "idempotency",
        managed_identity_client_id: str = "",
        client: Any | None = None,
    ) -> None:
        self._credential: Any | None = None
        if client is None:
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=managed_identity_client_id or None
            )
            client = CosmosClient(url=endpoint, credential=self._credential)
        self.client = client
        self.database = client.get_database_client(database)
        self.requests = self.database.get_container_client(requests_container)
        self.templates = self.database.get_container_client(templates_container)
        self.idempotency = self.database.get_container_client(idempotency_container)

    async def close(self) -> None:
        await self.client.close()
        if self._credential is not None:
            await self._credential.close()


class CosmosRequestRepository(RequestRepository):
    """Request aggregate repository partitioned by ``/requestId``."""

    def __init__(
        self,
        endpoint: str,
        database: str,
        *,
        requests_container: str = "requests",
        templates_container: str = "templates",
        idempotency_container: str = "idempotency",
        managed_identity_client_id: str = "",
        context: CosmosRepositoryContext | None = None,
    ) -> None:
        self._context = context or CosmosRepositoryContext(
            endpoint,
            database,
            requests_container=requests_container,
            templates_container=templates_container,
            idempotency_container=idempotency_container,
            managed_identity_client_id=managed_identity_client_id,
        )
        self._container = self._context.requests

    async def get(self, request_id: str) -> Request | None:
        try:
            document = await self._container.read_item(
                item="request",
                partition_key=request_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read request")
        return request_from_document(cast(dict[str, Any], document))

    async def get_or_create(
        self,
        request_id: str,
        factory: Callable[[], Request],
    ) -> tuple[Request, bool]:
        existing = await self.get(request_id)
        if existing is not None:
            return existing, False

        request = factory()
        if request.request_id != request_id:
            raise PermanentError(
                "Request factory returned a different request_id",
                expected_request_id=request_id,
                actual_request_id=request.request_id,
            )
        revision = RequestRevision(
            request_id=request_id,
            revision=request.current_revision,
            template_version=request.template_version,
            created_at=request.created_at,
        )
        operations = [
            ("create", (request_to_document(request),)),
            ("create", (revision_to_document(revision),)),
        ]
        try:
            results = await self._container.execute_item_batch(
                batch_operations=operations,
                partition_key=request_id,
            )
        except exceptions.CosmosResourceExistsError as exc:
            winner = await self.get(request_id)
            if winner is not None:
                return winner, False
            _raise_cosmos_error(exc, "create request")
        except exceptions.CosmosBatchOperationError as exc:
            if _batch_status_code(exc) == 409:
                winner = await self.get(request_id)
                if winner is not None:
                    return winner, False
            _raise_cosmos_error(exc, "create request")
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "create request")

        request_document = cast(dict[str, Any], results[0])
        resource = request_document.get("resourceBody")
        if isinstance(resource, dict) and resource.get("_etag"):
            request.etag = str(resource["_etag"])
        else:
            request.etag = str(
                request_document.get("_etag") or request_document.get("eTag") or ""
            )
        return request, True

    async def save(
        self,
        request: Request,
        revision: RequestRevision,
        events: list[WorkflowEvent],
        expected_etag: str,
    ) -> str:
        operations: list[tuple[Any, ...]] = [
            (
                "replace",
                ("request", request_to_document(request)),
                {"if_match_etag": expected_etag},
            ),
            ("upsert", (revision_to_document(revision),)),
        ]
        for event in events:
            operations.append(("create", (workflow_event_to_document(event),)))
            operations.append(("create", (outbox_to_document(workflow_event_to_outbox(event)),)))

        try:
            results = await self._container.execute_item_batch(
                batch_operations=operations,
                partition_key=request.request_id,
            )
        except exceptions.CosmosAccessConditionFailedError:
            await self._raise_conflict(request.request_id, expected_etag)
        except exceptions.CosmosBatchOperationError as exc:
            if _batch_status_code(exc) in {409, 412}:
                await self._raise_conflict(request.request_id, expected_etag)
            _raise_cosmos_error(exc, "save request aggregate")
        except exceptions.CosmosHttpResponseError as exc:
            if exc.status_code == 412:
                await self._raise_conflict(request.request_id, expected_etag)
            _raise_cosmos_error(exc, "save request aggregate")

        saved = cast(dict[str, Any], results[0])
        resource = saved.get("resourceBody")
        if isinstance(resource, dict) and resource.get("_etag"):
            return str(resource["_etag"])
        return str(saved.get("_etag") or saved.get("eTag") or "")

    async def get_current_revision(self, request_id: str) -> RequestRevision | None:
        request = await self.get(request_id)
        if request is None:
            return None
        try:
            document = await self._container.read_item(
                item=f"revision:{request.current_revision}",
                partition_key=request_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read current revision")
        return revision_from_document(cast(dict[str, Any], document))

    async def list_by_user(self, user_id: str, tenant_id: str) -> list[Request]:
        query = (
            "SELECT * FROM c WHERE c.docType = 'request' "
            "AND c.requesterId = @userId AND c.tenantId = @tenantId "
            "ORDER BY c.updatedAt DESC"
        )
        parameters: list[dict[str, object]] = [
            {"name": "@userId", "value": user_id},
            {"name": "@tenantId", "value": tenant_id},
        ]
        try:
            iterator = self._container.query_items(
                query=query,
                parameters=parameters,
            )
            return [
                request_from_document(cast(dict[str, Any], document))
                async for document in iterator
            ]
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "list requests")

    async def _raise_conflict(self, request_id: str, expected_etag: str) -> NoReturn:
        current = await self.get(request_id)
        raise ConflictError(
            "Request was modified by another operation",
            current_revision=current.current_revision if current else -1,
            current_etag=current.etag if current else "",
            expected_etag=expected_etag,
        )


class CosmosOutboxRepository(OutboxRepository):
    """Durable outbox stored beside request data in the request partition."""

    def __init__(
        self,
        endpoint: str,
        database: str,
        *,
        requests_container: str = "requests",
        templates_container: str = "templates",
        idempotency_container: str = "idempotency",
        managed_identity_client_id: str = "",
        context: CosmosRepositoryContext | None = None,
    ) -> None:
        self._context = context or CosmosRepositoryContext(
            endpoint,
            database,
            requests_container=requests_container,
            templates_container=templates_container,
            idempotency_container=idempotency_container,
            managed_identity_client_id=managed_identity_client_id,
        )
        self._container = self._context.requests

    async def enqueue(self, item: OutboxItem) -> None:
        document = outbox_to_document(item)
        try:
            await self._container.create_item(document)
        except exceptions.CosmosResourceExistsError:
            existing = await self._read(item)
            if (
                existing.event_type == item.event_type
                and existing.request_id == item.request_id
                and existing.payload == item.payload
            ):
                return
            raise IdempotencyKeyCollisionError(
                "Outbox item_id already exists with different content",
                item_id=item.item_id,
            ) from None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "enqueue outbox item")

    async def get_pending(self, batch_size: int = 25) -> list[OutboxItem]:
        if batch_size < 1:
            return []
        query = (
            "SELECT TOP @batchSize * FROM c WHERE c.docType = 'outbox' "
            "AND c.dispatched = false ORDER BY c.createdAt ASC"
        )
        try:
            iterator = self._container.query_items(
                query=query,
                parameters=[{"name": "@batchSize", "value": batch_size}],
                max_item_count=batch_size,
            )
            return [
                outbox_from_document(cast(dict[str, Any], document))
                async for document in iterator
            ]
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read pending outbox")

    async def mark_dispatched(self, item_ids: list[str]) -> None:
        if not item_ids:
            return
        query = (
            "SELECT c.id, c.requestId, c._etag FROM c "
            "WHERE c.docType = 'outbox' AND ARRAY_CONTAINS(@itemIds, c.itemId)"
        )
        try:
            iterator = self._container.query_items(
                query=query,
                parameters=[{"name": "@itemIds", "value": item_ids}],
            )
            documents = [cast(dict[str, Any], document) async for document in iterator]
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            for document in documents:
                await self._container.patch_item(
                    item=str(document["id"]),
                    partition_key=str(document["requestId"]),
                    patch_operations=[
                        {"op": "set", "path": "/dispatched", "value": True},
                        {"op": "set", "path": "/dispatchedAt", "value": now},
                    ],
                    etag=str(document["_etag"]),
                    match_condition=MatchConditions.IfNotModified,
                )
        except exceptions.CosmosAccessConditionFailedError:
            return
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "mark outbox dispatched")

    async def _read(self, item: OutboxItem) -> OutboxItem:
        try:
            document = await self._container.read_item(
                item=f"outbox:{item.item_id}",
                partition_key=item.request_id,
            )
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read existing outbox item")
        return outbox_from_document(cast(dict[str, Any], document))

    async def close(self) -> None:
        await self._context.close()


class CosmosIdempotencyStore(IdempotencyStore):
    """TTL-enabled command result store partitioned by ``/scopeId``."""

    def __init__(
        self,
        endpoint: str,
        database: str,
        *,
        requests_container: str = "requests",
        templates_container: str = "templates",
        idempotency_container: str = "idempotency",
        managed_identity_client_id: str = "",
        context: CosmosRepositoryContext | None = None,
    ) -> None:
        self._context = context or CosmosRepositoryContext(
            endpoint,
            database,
            requests_container=requests_container,
            templates_container=templates_container,
            idempotency_container=idempotency_container,
            managed_identity_client_id=managed_identity_client_id,
        )
        self._container = self._context.idempotency

    async def check(self, scope_id: str, key: str) -> StoredResult | None:
        probe = StoredResult(
            scope_id=scope_id,
            key=key,
            result=None,
            stored_at=datetime.now(UTC),
            expires_at=datetime.now(UTC),
        )
        document_id = stored_result_to_document(probe, 1)["id"]
        try:
            document = await self._container.read_item(
                item=document_id,
                partition_key=scope_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read idempotency result")
        stored = stored_result_from_document(cast(dict[str, Any], document))
        if stored.expires_at <= datetime.now(UTC):
            try:
                await self._container.delete_item(
                    item=str(document["id"]),
                    partition_key=scope_id,
                    etag=str(document.get("_etag", "")),
                    match_condition=MatchConditions.IfNotModified,
                )
            except (
                exceptions.CosmosResourceNotFoundError,
                exceptions.CosmosAccessConditionFailedError,
            ):
                pass
            except exceptions.CosmosHttpResponseError as exc:
                _raise_cosmos_error(exc, "delete expired idempotency result")
            return None
        return stored

    async def store(
        self,
        scope_id: str,
        key: str,
        result: Any,
        ttl_days: int = 7,
    ) -> None:
        if ttl_days < 1:
            raise PermanentError("Idempotency TTL must be at least one day")
        now = datetime.now(UTC)
        stored = StoredResult(
            scope_id=scope_id,
            key=key,
            result=result,
            stored_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )
        document = stored_result_to_document(stored, ttl_days * 24 * 60 * 60)
        try:
            await self._container.create_item(document)
        except exceptions.CosmosResourceExistsError:
            existing = await self.check(scope_id, key)
            if existing is None:
                try:
                    await self._container.create_item(document)
                    return
                except exceptions.CosmosResourceExistsError:
                    existing = await self.check(scope_id, key)
                except exceptions.CosmosHttpResponseError as exc:
                    _raise_cosmos_error(exc, "store idempotency result")
            if existing is not None and existing.result == result:
                return
            raise IdempotencyKeyCollisionError(
                "Idempotency key already exists with a different result",
                scope_id=scope_id,
                key=key,
            ) from None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "store idempotency result")


class CosmosTemplateRepository(TemplateRepository):
    """Template repository partitioned by ``/templateId``."""

    def __init__(
        self,
        endpoint: str,
        database: str,
        *,
        requests_container: str = "requests",
        templates_container: str = "templates",
        idempotency_container: str = "idempotency",
        managed_identity_client_id: str = "",
        context: CosmosRepositoryContext | None = None,
    ) -> None:
        self._context = context or CosmosRepositoryContext(
            endpoint,
            database,
            requests_container=requests_container,
            templates_container=templates_container,
            idempotency_container=idempotency_container,
            managed_identity_client_id=managed_identity_client_id,
        )
        self._container = self._context.templates

    async def get_active(self, template_id: str) -> TemplateVersion | None:
        query = (
            "SELECT TOP 1 * FROM c WHERE c.docType = 'templateVersion' "
            "AND c.isActive = true AND IS_DEFINED(c.jsonSchema) "
            "ORDER BY c.createdAt DESC"
        )
        try:
            iterator = self._container.query_items(
                query=query,
                partition_key=template_id,
                max_item_count=1,
            )
            async for document in iterator:
                return template_from_document(cast(dict[str, Any], document))
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read active template")

        from intake_domain.template_schema import (
            TemplateSchemaError,
            load_packaged_json_schema,
            template_from_json_schema,
        )

        try:
            json_schema = load_packaged_json_schema(template_id)
            template = template_from_json_schema(json_schema)
        except TemplateSchemaError:
            return None

        try:
            await self._container.create_item(
                template_to_document(template, json_schema)
            )
            return template
        except exceptions.CosmosResourceExistsError as exc:
            winner = await self.get_version(template.template_id, template.version)
            if winner is not None:
                return winner
            raise PermanentError(
                "Template creation conflicted but the winning version was not readable",
                template_id=template.template_id,
                template_version=template.version,
            ) from exc
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "seed active template")

    async def get_version(self, template_id: str, version: str) -> TemplateVersion | None:
        try:
            document = await self._container.read_item(
                item=f"version:{version}",
                partition_key=template_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as exc:
            _raise_cosmos_error(exc, "read template version")
        return template_from_document(cast(dict[str, Any], document))


def _batch_status_code(exc: exceptions.CosmosBatchOperationError) -> int:
    try:
        response = exc.operation_responses[exc.error_index]
        return int(response.get("statusCode", response.get("status_code", 0)))
    except (AttributeError, IndexError, TypeError, ValueError):
        return int(getattr(exc, "status_code", 0) or 0)


def _raise_cosmos_error(
    exc: BaseException,
    operation: str,
) -> NoReturn:
    status_code = int(getattr(exc, "status_code", 0) or 0)
    context = {"operation": operation, "status_code": status_code}
    if status_code in _TRANSIENT_STATUS_CODES:
        raise TransientError(f"Cosmos DB failed to {operation}", **context) from exc
    raise PermanentError(f"Cosmos DB failed to {operation}", **context) from exc


__all__ = [
    "CosmosIdempotencyStore",
    "CosmosOutboxRepository",
    "CosmosRepositoryContext",
    "CosmosRequestRepository",
    "CosmosTemplateRepository",
]
