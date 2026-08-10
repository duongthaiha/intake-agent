"""Component gates for Cosmos and Blob durability behavior."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.cosmos import exceptions
from azure.servicebus import ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusConnectionError

from intake_domain.commands import (
    ActorPayload,
    CommandEnvelope,
    FieldUpdateItem,
    ProposeFieldUpdatesData,
)
from intake_domain.commands.handlers import ProposeFieldUpdatesHandler
from intake_domain.entities import (
    ActorContext,
    ActorType,
    FieldSchema,
    OutboxItem,
    Request,
    RequestRevision,
    RequestStatus,
    TemplateVersion,
    WorkflowEvent,
)
from intake_domain.errors import (
    ConflictError,
    IdempotencyKeyCollisionError,
    PermanentError,
    TransientError,
)
from intake_domain.repositories import ArtifactMetadata
from intake_persistence.blob import BlobArtifactStore
from intake_persistence.cosmos import (
    CosmosIdempotencyStore,
    CosmosOutboxRepository,
    CosmosRepositoryContext,
    CosmosRequestRepository,
)
from intake_persistence.inmemory import (
    InMemoryIdempotencyStore,
    InMemoryRequestRepository,
)
from intake_persistence.servicebus import ServiceBusOutboxDispatcher

pytestmark = pytest.mark.component


class AsyncDocuments:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self._documents = documents

    def __aiter__(self):  # type: ignore[no-untyped-def]
        async def iterate():  # type: ignore[no-untyped-def]
            for document in self._documents:
                yield document

        return iterate()


def _request(*, revision: int = 2, etag: str = "etag-old") -> Request:
    now = datetime.now(UTC)
    return Request(
        request_id="request-1",
        tenant_id="tenant-1",
        conversation_id="chat-1",
        requester_id="user-1",
        status=RequestStatus.NEW,
        current_revision=revision,
        template_id="general-intake-v1",
        template_version="1.0.0",
        created_at=now,
        updated_at=now,
        etag=etag,
    )


def _request_document(request: Request, *, etag: str | None = None) -> dict[str, object]:
    return {
        "id": "request",
        "docType": "request",
        "requestId": request.request_id,
        "tenantId": request.tenant_id,
        "conversationId": request.conversation_id,
        "requesterId": request.requester_id,
        "status": request.status.value,
        "currentRevision": request.current_revision,
        "templateId": request.template_id,
        "templateVersion": request.template_version,
        "createdAt": request.created_at.isoformat().replace("+00:00", "Z"),
        "updatedAt": request.updated_at.isoformat().replace("+00:00", "Z"),
        "_etag": etag if etag is not None else request.etag,
    }


def _event(request: Request) -> WorkflowEvent:
    return WorkflowEvent(
        event_id="event-1",
        request_id=request.request_id,
        revision=request.current_revision,
        actor_id="user-1",
        actor_type=ActorType.USER,
        command_id="command-1",
        prior_state=RequestStatus.NEW,
        new_state=RequestStatus.NEW,
        occurred_at=datetime.now(UTC),
        event_type="RequestFieldsUpdated",
        correlation_id="correlation-1",
        data={"accepted_fields": ["project.name"]},
    )


def _cosmos_context(container: object) -> SimpleNamespace:
    return SimpleNamespace(
        requests=container,
        templates=MagicMock(),
        idempotency=container,
    )


def test_workflow_event_extensions_preserve_existing_constructor_contract() -> None:
    request = _request()
    first = WorkflowEvent(
        event_id="event-1",
        request_id=request.request_id,
        revision=request.current_revision,
        actor_id="user-1",
        actor_type=ActorType.USER,
        command_id="command-1",
        prior_state=RequestStatus.NEW,
        new_state=RequestStatus.NEW,
        occurred_at=datetime.now(UTC),
    )
    second = WorkflowEvent(
        event_id="event-2",
        request_id=request.request_id,
        revision=request.current_revision,
        actor_id="user-1",
        actor_type=ActorType.USER,
        command_id="command-2",
        prior_state=RequestStatus.NEW,
        new_state=RequestStatus.NEW,
        occurred_at=datetime.now(UTC),
    )

    first.data["field"] = "value"

    assert first.event_type == ""
    assert first.event_version == "1.0"
    assert first.correlation_id == ""
    assert second.data == {}


def test_cosmos_context_uses_managed_identity_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intake_persistence import cosmos

    credential = object()
    client = MagicMock()
    monkeypatch.setattr(cosmos, "DefaultAzureCredential", MagicMock(return_value=credential))
    cosmos_client = MagicMock(return_value=client)
    monkeypatch.setattr(cosmos, "CosmosClient", cosmos_client)

    CosmosRepositoryContext(
        "https://cosmos.example/",
        "intake",
        managed_identity_client_id="managed-client-id",
    )

    cosmos.DefaultAzureCredential.assert_called_once_with(  # type: ignore[attr-defined]
        managed_identity_client_id="managed-client-id"
    )
    cosmos_client.assert_called_once_with(
        url="https://cosmos.example/",
        credential=credential,
    )


def test_request_repository_capability_distinguishes_atomic_outbox_ownership() -> None:
    cosmos_repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(MagicMock()),  # type: ignore[arg-type]
    )

    assert cosmos_repository.persists_outbox_atomically is True
    assert InMemoryRequestRepository().persists_outbox_atomically is False


@pytest.mark.asyncio
async def test_request_reads_use_request_id_partition() -> None:
    request = _request()
    container = MagicMock()
    container.read_item = AsyncMock(return_value=_request_document(request))
    repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    loaded = await repository.get(request.request_id)

    assert loaded is not None
    assert loaded.request_id == request.request_id
    container.read_item.assert_awaited_once_with(
        item="request",
        partition_key=request.request_id,
    )


@pytest.mark.asyncio
async def test_get_or_create_uses_conditional_batch_and_returns_created_etag() -> None:
    request = _request(revision=1, etag="")
    container = MagicMock()
    container.read_item = AsyncMock(
        side_effect=exceptions.CosmosResourceNotFoundError(
            status_code=404,
            message="missing",
        )
    )
    container.execute_item_batch = AsyncMock(
        return_value=[
            {
                "statusCode": 201,
                "eTag": "etag-created",
                "resourceBody": _request_document(request, etag="etag-created"),
            },
            {"statusCode": 201, "eTag": "revision-etag"},
        ]
    )
    repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    created_request, created = await repository.get_or_create(
        request.request_id,
        lambda: request,
    )

    assert created is True
    assert created_request.etag == "etag-created"
    call = container.execute_item_batch.await_args.kwargs
    assert call["partition_key"] == request.request_id
    assert [operation[0] for operation in call["batch_operations"]] == [
        "create",
        "create",
    ]


@pytest.mark.asyncio
async def test_get_or_create_maps_throttled_batch_to_transient_error() -> None:
    request = _request(revision=1, etag="")
    container = MagicMock()
    container.read_item = AsyncMock(
        side_effect=exceptions.CosmosResourceNotFoundError(
            status_code=404,
            message="missing",
        )
    )
    container.execute_item_batch = AsyncMock(
        side_effect=exceptions.CosmosBatchOperationError(
            error_index=0,
            headers={},
            status_code=429,
            message="throttled",
            operation_responses=[{"statusCode": 429}],
        )
    )
    repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    with pytest.raises(TransientError):
        await repository.get_or_create(request.request_id, lambda: request)


@pytest.mark.asyncio
async def test_save_batches_projection_revision_event_and_outbox_in_one_partition() -> None:
    request = _request()
    revision = RequestRevision(
        request_id=request.request_id,
        revision=request.current_revision,
        template_version=request.template_version,
    )
    container = MagicMock()
    container.execute_item_batch = AsyncMock(
        return_value=[
            {
                "statusCode": 200,
                "eTag": "etag-new",
                "resourceBody": _request_document(request, etag="etag-new"),
            }
        ]
    )
    repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    etag = await repository.save(request, revision, [_event(request)], request.etag)

    assert etag == "etag-new"
    call = container.execute_item_batch.await_args
    assert call.kwargs["partition_key"] == request.request_id
    operations = call.kwargs["batch_operations"]
    documents = [
        operation[1][1] if operation[0] == "replace" else operation[1][0]
        for operation in operations
        if operation[0] in {"create", "upsert", "replace"}
    ]
    assert {document["docType"] for document in documents} == {
        "request",
        "revision",
        "workflowEvent",
        "outbox",
    }
    assert all(document["requestId"] == request.request_id for document in documents)
    assert operations[0][2]["if_match_etag"] == request.etag


@pytest.mark.asyncio
async def test_etag_precondition_maps_to_domain_conflict_with_current_state() -> None:
    request = _request()
    current = _request(revision=3, etag="etag-current")
    container = MagicMock()
    container.execute_item_batch = AsyncMock(
        side_effect=exceptions.CosmosAccessConditionFailedError(
            status_code=412,
            message="precondition failed",
        )
    )
    container.read_item = AsyncMock(return_value=_request_document(current))
    repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    with pytest.raises(ConflictError) as exc_info:
        await repository.save(
            request,
            RequestRevision(request_id=request.request_id, revision=2),
            [],
            request.etag,
        )

    assert exc_info.value.current_revision == 3
    assert exc_info.value.current_etag == "etag-current"
    assert exc_info.value.context["expected_etag"] == "etag-old"


@pytest.mark.asyncio
async def test_cosmos_error_mapping_distinguishes_retryable_failures() -> None:
    container = MagicMock()
    repository = CosmosRequestRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )
    container.read_item = AsyncMock(
        side_effect=exceptions.CosmosHttpResponseError(
            status_code=429,
            message="throttled",
        )
    )
    with pytest.raises(TransientError):
        await repository.get("request-1")

    container.read_item = AsyncMock(
        side_effect=exceptions.CosmosHttpResponseError(
            status_code=400,
            message="bad request",
        )
    )
    with pytest.raises(PermanentError):
        await repository.get("request-1")


@pytest.mark.asyncio
async def test_idempotency_document_uses_scope_partition_and_seven_day_ttl() -> None:
    container = MagicMock()
    container.create_item = AsyncMock()
    store = CosmosIdempotencyStore(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    await store.store("request-1", "command-1", {"status": "accepted"})

    document = container.create_item.await_args.args[0]
    assert document["scopeId"] == "request-1"
    assert document["key"] == "command-1"
    assert document["ttl"] == 7 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_expired_idempotency_record_does_not_block_a_new_result() -> None:
    expired = datetime.now(UTC) - timedelta(minutes=1)
    container = MagicMock()
    container.create_item = AsyncMock(
        side_effect=[
            exceptions.CosmosResourceExistsError(
                status_code=409,
                message="expired item awaits TTL cleanup",
            ),
            None,
        ]
    )
    container.read_item = AsyncMock(
        return_value={
            "id": "idempotency-id",
            "docType": "idempotency",
            "scopeId": "request-1",
            "key": "command-1",
            "result": {"status": "old"},
            "storedAt": (expired - timedelta(days=7))
            .isoformat()
            .replace("+00:00", "Z"),
            "expiresAt": expired.isoformat().replace("+00:00", "Z"),
            "ttl": 1,
            "_etag": "etag-expired",
        }
    )
    container.delete_item = AsyncMock()
    container.replace_item = AsyncMock()
    container.upsert_item = AsyncMock()
    store = CosmosIdempotencyStore(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    await store.store("request-1", "command-1", {"status": "new"})

    container.delete_item.assert_awaited_once()
    delete = container.delete_item.await_args.kwargs
    assert delete["partition_key"] == "request-1"
    assert delete["etag"] == "etag-expired"
    assert container.create_item.await_count == 2


@pytest.mark.asyncio
async def test_outbox_dispatch_markers_use_each_requests_partition_and_etag() -> None:
    container = MagicMock()
    container.query_items.return_value = AsyncDocuments(
        [
            {"id": "outbox:event-1", "requestId": "request-1", "_etag": "etag-1"},
            {"id": "outbox:event-2", "requestId": "request-2", "_etag": "etag-2"},
        ]
    )
    container.patch_item = AsyncMock()
    repository = CosmosOutboxRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    await repository.mark_dispatched(["event-1", "event-2"])

    assert container.patch_item.await_count == 2
    assert [
        call.kwargs["partition_key"]
        for call in container.patch_item.await_args_list
    ] == ["request-1", "request-2"]
    assert [
        call.kwargs["etag"]
        for call in container.patch_item.await_args_list
    ] == ["etag-1", "etag-2"]
    assert all(
        call.kwargs["patch_operations"][0]
        == {"op": "set", "path": "/dispatched", "value": True}
        for call in container.patch_item.await_args_list
    )


@pytest.mark.asyncio
async def test_outbox_idempotency_rejects_same_id_with_different_payload() -> None:
    existing = _outbox_item(1)
    existing.payload = {"event_id": "event-1", "value": "original"}
    container = MagicMock()
    container.create_item = AsyncMock(
        side_effect=exceptions.CosmosResourceExistsError(
            status_code=409,
            message="exists",
        )
    )
    container.read_item = AsyncMock(
        return_value={
            "id": "outbox:event-1",
            "docType": "outbox",
            "requestId": existing.request_id,
            "itemId": existing.item_id,
            "eventType": existing.event_type,
            "payload": existing.payload,
            "createdAt": existing.created_at.isoformat().replace("+00:00", "Z"),
            "dispatched": False,
        }
    )
    repository = CosmosOutboxRepository(
        "",
        "",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )
    conflicting = _outbox_item(1)
    conflicting.payload = {"event_id": "event-1", "value": "changed"}

    with pytest.raises(IdempotencyKeyCollisionError):
        await repository.enqueue(conflicting)


def test_blob_store_uses_managed_identity_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intake_persistence import blob

    credential = object()
    monkeypatch.setattr(blob, "DefaultAzureCredential", MagicMock(return_value=credential))
    blob_client = MagicMock()
    service_client = MagicMock(return_value=blob_client)
    monkeypatch.setattr(blob, "BlobServiceClient", service_client)

    BlobArtifactStore(
        "https://storage.example/",
        "request-artifacts",
        managed_identity_client_id="managed-client-id",
    )

    blob.DefaultAzureCredential.assert_called_once_with(  # type: ignore[attr-defined]
        managed_identity_client_id="managed-client-id"
    )
    service_client.assert_called_once_with(
        account_url="https://storage.example/",
        credential=credential,
    )


def _artifact_metadata() -> ArtifactMetadata:
    return ArtifactMetadata(
        artifact_type="pdf",
        content_type="application/pdf",
        filename="approved.pdf",
        request_id="request-1",
        revision=2,
        agent_version="7",
    )


@pytest.mark.asyncio
async def test_blob_write_is_create_only_and_checksum_versioned() -> None:
    blob = SimpleNamespace(
        url="https://storage.example/request-artifacts/request-1/2/approved.pdf",
        upload_blob=AsyncMock(),
    )
    client = MagicMock()
    client.get_blob_client.return_value = blob
    store = BlobArtifactStore(
        "https://storage.example/",
        "request-artifacts",
        client=client,
    )

    artifact_id = await store.store_artifact(
        "request-1",
        2,
        b"approved content",
        _artifact_metadata(),
    )

    assert artifact_id == blob.url
    upload = blob.upload_blob.await_args
    assert upload.kwargs["overwrite"] is False
    assert upload.kwargs["metadata"]["request_id"] == "request-1"
    assert upload.kwargs["metadata"]["revision"] == "2"
    assert len(upload.kwargs["metadata"]["sha256"]) == 64


@pytest.mark.asyncio
async def test_blob_duplicate_is_idempotent_only_for_matching_checksum() -> None:
    properties = SimpleNamespace(
        metadata={
            "sha256": "3b1698580da742407583708ba40ccc0484d44f8848d62ddccc6940023aa1f13c"
        },
        etag="etag-1",
    )
    blob = SimpleNamespace(
        url="https://storage.example/request-artifacts/request-1/2/approved.pdf",
        upload_blob=AsyncMock(side_effect=ResourceExistsError("exists")),
        get_blob_properties=AsyncMock(return_value=properties),
    )
    client = MagicMock()
    client.get_blob_client.return_value = blob
    store = BlobArtifactStore(
        "https://storage.example/",
        "request-artifacts",
        client=client,
    )

    artifact_id = await store.store_artifact(
        "request-1",
        2,
        b"approved content",
        _artifact_metadata(),
    )
    assert artifact_id == blob.url

    properties.metadata["sha256"] = "different"
    with pytest.raises(ConflictError):
        await store.store_artifact(
            "request-1",
            2,
            b"approved content",
            _artifact_metadata(),
        )


@pytest.mark.asyncio
async def test_blob_rejects_unsafe_names_and_maps_service_errors() -> None:
    metadata = _artifact_metadata()
    metadata.filename = "../approved.pdf"
    store = BlobArtifactStore(
        "https://storage.example/",
        "request-artifacts",
        client=MagicMock(),
    )
    with pytest.raises(PermanentError):
        await store.store_artifact("request-1", 2, b"content", metadata)

    unavailable = HttpResponseError(message="unavailable")
    unavailable.status_code = 503
    blob = SimpleNamespace(
        url="https://storage.example/request-artifacts/request-1/2/approved.pdf",
        upload_blob=AsyncMock(side_effect=unavailable),
    )
    client = MagicMock()
    client.get_blob_client.return_value = blob
    store = BlobArtifactStore(
        "https://storage.example/",
        "request-artifacts",
        client=client,
    )
    with pytest.raises(TransientError):
        await store.store_artifact(
            "request-1",
            2,
            b"approved content",
            _artifact_metadata(),
        )


class AsyncContext:
    async def __aenter__(self) -> AsyncContext:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class RecordingSender(AsyncContext):
    def __init__(self, fail_at: int | None = None) -> None:
        self.messages: list[ServiceBusMessage] = []
        self._fail_at = fail_at

    async def send_messages(self, message: ServiceBusMessage) -> None:
        if self._fail_at is not None and len(self.messages) == self._fail_at:
            raise ServiceBusConnectionError(reason="connection lost")
        self.messages.append(message)


class RecordingServiceBusClient(AsyncContext):
    def __init__(self, sender: RecordingSender) -> None:
        self.sender = sender

    def get_queue_sender(self, *, queue_name: str) -> RecordingSender:
        assert queue_name == "domain-events"
        return self.sender


def test_servicebus_dispatcher_uses_managed_identity_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intake_persistence import servicebus

    credential = object()
    monkeypatch.setattr(
        servicebus,
        "DefaultAzureCredential",
        MagicMock(return_value=credential),
    )
    client = MagicMock()
    servicebus_client = MagicMock(return_value=client)
    monkeypatch.setattr(servicebus, "ServiceBusClient", servicebus_client)

    ServiceBusOutboxDispatcher(
        MagicMock(),
        "bus.example.servicebus.windows.net",
        "domain-events",
        managed_identity_client_id="managed-client-id",
    )

    servicebus.DefaultAzureCredential.assert_called_once_with(  # type: ignore[attr-defined]
        managed_identity_client_id="managed-client-id"
    )
    servicebus_client.assert_called_once_with(
        fully_qualified_namespace="bus.example.servicebus.windows.net",
        credential=credential,
    )


def _outbox_item(number: int) -> OutboxItem:
    return OutboxItem(
        item_id=f"event-{number}",
        request_id="request-1",
        event_type="RequestSubmitted",
        payload={
            "event_id": f"event-{number}",
            "correlation_id": "correlation-1",
            "request_id": "request-1",
        },
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_dispatch_failure_commits_only_acknowledged_outbox_items() -> None:
    items = [_outbox_item(1), _outbox_item(2)]
    outbox = SimpleNamespace(
        get_pending=AsyncMock(return_value=items),
        mark_dispatched=AsyncMock(),
    )
    sender = RecordingSender(fail_at=1)
    dispatcher = ServiceBusOutboxDispatcher(
        outbox,  # type: ignore[arg-type]
        "bus.example.servicebus.windows.net",
        "domain-events",
        client=RecordingServiceBusClient(sender),
    )

    with pytest.raises(TransientError):
        await dispatcher.dispatch_pending()

    assert [message.message_id for message in sender.messages] == ["event-1"]
    outbox.mark_dispatched.assert_awaited_once_with(["event-1"])


@pytest.mark.asyncio
async def test_atomic_save_is_not_followed_by_a_second_fallible_outbox_write() -> None:
    request = _request(revision=1)
    revision = RequestRevision(
        request_id=request.request_id,
        revision=1,
        template_version=request.template_version,
    )
    template = TemplateVersion(
        template_id=request.template_id,
        version=request.template_version,
        display_name="General Intake",
        fields=[
            FieldSchema(
                field_path="project.name",
                label="Project name",
                field_type="string",
            )
        ],
    )
    atomic_repository = SimpleNamespace(
        get=AsyncMock(return_value=request),
        get_current_revision=AsyncMock(return_value=revision),
        save=AsyncMock(return_value="etag-new"),
    )
    template_repository = SimpleNamespace(
        get_version=AsyncMock(return_value=template),
    )
    outbox_repository = SimpleNamespace(
        enqueue=AsyncMock(
            side_effect=AssertionError(
                "outbox was already committed by RequestRepository.save"
            )
        )
    )
    actor = ActorContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=frozenset(["requester"]),
        conversation_id="chat-1",
        activity_id="activity-1",
        correlation_id="correlation-1",
        agent_identity="intake-agent",
    )
    envelope = CommandEnvelope(
        command_type="propose_field_updates",
        request_id=request.request_id,
        expected_revision=1,
        actor=ActorPayload(
            user_id=actor.user_id,
            tenant_id=actor.tenant_id,
            agent_identity=actor.agent_identity,
        ),
    )
    handler = ProposeFieldUpdatesHandler(
        atomic_repository,  # type: ignore[arg-type]
        template_repository,  # type: ignore[arg-type]
        outbox_repository,  # type: ignore[arg-type]
        InMemoryIdempotencyStore(),
    )

    result = await handler.handle(
        envelope,
        actor,
        ProposeFieldUpdatesData(
            updates=[FieldUpdateItem(field_path="project.name", value="Durable")]
        ),
    )

    assert result["status"] == "accepted"
    atomic_repository.save.assert_awaited_once()
    outbox_repository.enqueue.assert_not_awaited()


def test_worker_timer_dispatches_the_durable_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intake_workers import function_app

    dispatcher = SimpleNamespace(dispatch_pending=AsyncMock(return_value=2))
    monkeypatch.setenv("INTAKE_ENVIRONMENT", "production")
    monkeypatch.setattr(function_app, "_get_outbox_dispatcher", lambda: dispatcher)

    function_app.outbox_dispatcher(MagicMock())

    dispatcher.dispatch_pending.assert_awaited_once_with()


def test_deployed_worker_does_not_silently_skip_missing_durable_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intake_workers import function_app

    function_app._get_outbox_dispatcher.cache_clear()
    monkeypatch.setenv("INTAKE_ENVIRONMENT", "production")
    monkeypatch.delenv("INTAKE_COSMOS_ENDPOINT", raising=False)

    with pytest.raises(RuntimeError, match="INTAKE_COSMOS_ENDPOINT is required"):
        function_app.outbox_dispatcher(MagicMock())

    function_app._get_outbox_dispatcher.cache_clear()
