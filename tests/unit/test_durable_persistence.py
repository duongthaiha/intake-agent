"""Targeted tests for the durable Azure persistence adapters."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosResourceExistsError
from azure.servicebus import ServiceBusMessage

from intake_domain.entities import (
    ActorType,
    OutboxItem,
    Request,
    RequestRevision,
    RequestStatus,
    WorkflowEvent,
)
from intake_domain.errors import ConflictError
from intake_domain.repositories import ArtifactMetadata
from intake_persistence.blob import BlobArtifactStore
from intake_persistence.cosmos import (
    CosmosOutboxRepository,
    CosmosRequestRepository,
)
from intake_persistence.servicebus import ServiceBusOutboxDispatcher


def _request() -> Request:
    now = datetime.now(UTC)
    return Request(
        request_id="request-1",
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        requester_id="user-1",
        status=RequestStatus.NEW,
        current_revision=2,
        template_id="general",
        template_version="1.0.0",
        created_at=now,
        updated_at=now,
        etag="etag-1",
    )


def _event() -> WorkflowEvent:
    return WorkflowEvent(
        event_id="event-1",
        request_id="request-1",
        revision=2,
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
    return SimpleNamespace(requests=container)


@pytest.mark.asyncio
async def test_cosmos_save_uses_one_partition_transaction_for_state_event_and_outbox() -> None:
    container = SimpleNamespace(
        execute_item_batch=AsyncMock(return_value=[{"_etag": "etag-2"}])
    )
    repo = CosmosRequestRepository(
        "https://cosmos.example",
        "intake",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )
    request = _request()
    revision = RequestRevision(
        request_id=request.request_id,
        revision=request.current_revision,
        template_version=request.template_version,
    )

    etag = await repo.save(request, revision, [_event()], request.etag)

    assert etag == "etag-2"
    call = container.execute_item_batch.await_args.kwargs
    assert call["partition_key"] == request.request_id
    operations = call["batch_operations"]
    assert [operation[0] for operation in operations] == [
        "replace",
        "upsert",
        "create",
        "create",
    ]
    assert operations[0][2]["if_match_etag"] == "etag-1"
    assert operations[3][1][0]["id"] == "outbox:event-1"


@pytest.mark.asyncio
async def test_cosmos_outbox_enqueue_is_idempotent_for_exact_replay() -> None:
    existing_document = {
        "id": "outbox:event-1",
        "docType": "outbox",
        "requestId": "request-1",
        "itemId": "event-1",
        "eventType": "RequestFieldsUpdated",
        "payload": {"canonical": True},
        "createdAt": "2026-08-08T12:00:00Z",
        "dispatched": False,
    }
    container = SimpleNamespace(
        create_item=AsyncMock(side_effect=CosmosResourceExistsError(status_code=409)),
        read_item=AsyncMock(return_value=existing_document),
    )
    repo = CosmosOutboxRepository(
        "https://cosmos.example",
        "intake",
        context=_cosmos_context(container),  # type: ignore[arg-type]
    )

    await repo.enqueue(
        OutboxItem(
            item_id="event-1",
            request_id="request-1",
            event_type="RequestFieldsUpdated",
            payload={"canonical": True},
            created_at=datetime.now(UTC),
        )
    )

    container.read_item.assert_awaited_once_with(
        item="outbox:event-1",
        partition_key="request-1",
    )


def _blob_client() -> tuple[SimpleNamespace, SimpleNamespace]:
    blob = SimpleNamespace(
        url="https://storage.example/request-artifacts/request-1/2/file.pdf",
        upload_blob=AsyncMock(),
        get_blob_properties=AsyncMock(),
    )
    service = SimpleNamespace(
        account_name="storage",
        get_blob_client=Mock(return_value=blob),
        get_user_delegation_key=AsyncMock(return_value=object()),
    )
    return service, blob


def _artifact_metadata() -> ArtifactMetadata:
    return ArtifactMetadata(
        artifact_type="pdf",
        content_type="application/pdf",
        filename="file.pdf",
        request_id="request-1",
        revision=2,
        agent_version="1.0",
    )


@pytest.mark.asyncio
async def test_blob_store_is_create_only_and_checksum_idempotent() -> None:
    service, blob = _blob_client()
    store = BlobArtifactStore(
        "https://storage.example",
        "request-artifacts",
        client=service,
    )

    first = await store.store_artifact(
        "request-1",
        2,
        b"content",
        _artifact_metadata(),
    )
    assert first == blob.url
    assert blob.upload_blob.await_args.kwargs["overwrite"] is False

    checksum = blob.upload_blob.await_args.kwargs["metadata"]["sha256"]
    blob.upload_blob.side_effect = ResourceExistsError("exists")
    blob.get_blob_properties.return_value = SimpleNamespace(
        metadata={"sha256": checksum},
        etag="etag-1",
    )
    replay = await store.store_artifact(
        "request-1",
        2,
        b"content",
        _artifact_metadata(),
    )
    assert replay == blob.url


@pytest.mark.asyncio
async def test_blob_store_rejects_different_content_at_same_versioned_name() -> None:
    service, blob = _blob_client()
    blob.upload_blob.side_effect = ResourceExistsError("exists")
    blob.get_blob_properties.return_value = SimpleNamespace(
        metadata={"sha256": "different"},
        etag="etag-current",
    )
    store = BlobArtifactStore(
        "https://storage.example",
        "request-artifacts",
        client=service,
    )

    with pytest.raises(ConflictError, match="different content"):
        await store.store_artifact(
            "request-1",
            2,
            b"new content",
            _artifact_metadata(),
        )


class _AsyncContext:
    async def __aenter__(self) -> _AsyncContext:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Sender(_AsyncContext):
    def __init__(self) -> None:
        self.messages: list[ServiceBusMessage] = []

    async def send_messages(self, message: ServiceBusMessage) -> None:
        self.messages.append(message)


class _ServiceBusClient(_AsyncContext):
    def __init__(self, sender: _Sender) -> None:
        self.sender = sender

    def get_queue_sender(self, queue_name: str) -> _Sender:
        assert queue_name == "domain-events"
        return self.sender


@pytest.mark.asyncio
async def test_dispatcher_publishes_with_event_id_and_marks_only_acknowledged_items() -> None:
    item = OutboxItem(
        item_id="event-1",
        request_id="request-1",
        event_type="RequestSubmitted",
        payload={"correlation_id": "correlation-1", "request_id": "request-1"},
        created_at=datetime.now(UTC),
    )
    outbox = SimpleNamespace(
        get_pending=AsyncMock(return_value=[item]),
        mark_dispatched=AsyncMock(),
    )
    sender = _Sender()
    dispatcher = ServiceBusOutboxDispatcher(
        outbox,  # type: ignore[arg-type]
        "sb.example",
        "domain-events",
        client=_ServiceBusClient(sender),
    )

    assert await dispatcher.dispatch_pending() == 1
    assert len(sender.messages) == 1
    assert sender.messages[0].message_id == "event-1"
    assert sender.messages[0].subject == "RequestSubmitted"
    outbox.mark_dispatched.assert_awaited_once_with(["event-1"])


@pytest.mark.asyncio
async def test_blob_delegated_url_is_scoped_to_configured_account_and_container() -> None:
    service, blob = _blob_client()
    blob.get_blob_properties.return_value = SimpleNamespace(metadata={}, etag="etag")
    store = BlobArtifactStore(
        "https://storage.example",
        "request-artifacts",
        client=service,
    )

    with patch("intake_persistence.blob.generate_blob_sas", return_value="sig=delegated"):
        url = await store.get_artifact_url(blob.url)

    assert url == f"{blob.url}?sig=delegated"
