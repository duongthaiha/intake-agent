from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from azure.core.exceptions import ResourceExistsError
from azure.cosmos import exceptions
from intake_domain import (
    ActorContext,
    ActorRole,
    AgentKind,
    DomainError,
    IntakeRequest,
    Mutation,
    OutboxEvent,
    PendingEvent,
    Provenance,
)
from intake_mcp.local_profile import default_template
from intake_persistence import (
    ASYNC_IDEMPOTENCY_TTL_SECONDS,
    INTERACTIVE_IDEMPOTENCY_TTL_SECONDS,
    BlobEvaluationEvidenceStore,
    ConsumerPolicy,
    CosmosConsumerDeduplicationStore,
    CosmosRequestStore,
    EvaluationEvidence,
    PermanentAzureError,
    PermanentMessageError,
    RetryableMessageError,
    ServiceBusConsumer,
    ServiceBusDeadLetterReplayer,
    ServiceBusOutboxDispatcher,
    TransientAzureError,
)
from intake_persistence.serialization import request_from_document, request_to_document


class FakeCosmosContainer:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}
        self.batches: list[tuple[str, list[tuple[Any, ...]]]] = []
        self.patches: list[dict[str, Any]] = []
        self.batch_error: Exception | None = None

    def read_item(self, *, item: str, partition_key: str) -> dict[str, Any]:
        try:
            return dict(self.documents[(partition_key, item)])
        except KeyError as exc:
            raise exceptions.CosmosResourceNotFoundError(
                status_code=404, message="missing"
            ) from exc

    def query_items(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        del kwargs
        return iter(dict(value) for value in self.documents.values())

    def execute_item_batch(
        self, *, batch_operations: list[tuple[Any, ...]], partition_key: str
    ) -> list[dict[str, Any]]:
        if self.batch_error is not None:
            raise self.batch_error
        self.batches.append((partition_key, batch_operations))
        for operation in batch_operations:
            action = str(operation[0])
            document = (
                dict(operation[1][1])
                if action == "replace"
                else dict(operation[1][0])
            )
            document["_etag"] = f"etag-{len(self.documents) + 1}"
            self.documents[(partition_key, str(document["id"]))] = document
        return [{"statusCode": 200, "eTag": "etag-new"}]

    def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        key = (str(body["scopeId"]), str(body["id"]))
        if key in self.documents:
            raise exceptions.CosmosResourceExistsError(
                status_code=409, message="exists"
            )
        self.documents[key] = dict(body)
        return dict(body)

    def patch_item(self, **kwargs: Any) -> dict[str, Any]:
        self.patches.append(kwargs)
        return {}

    def delete_item(self, **kwargs: Any) -> None:
        self.documents.pop((str(kwargs["partition_key"]), str(kwargs["item"])), None)


class FakeOutbox:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events
        self.dispatched: list[OutboxEvent] = []

    def get_pending(self, batch_size: int = 25) -> tuple[OutboxEvent, ...]:
        return tuple(self.events[:batch_size])

    def mark_dispatched(self, events: Sequence[OutboxEvent]) -> None:
        self.dispatched.extend(events)


class FakeSender:
    def __init__(self, fail_after: int | None = None) -> None:
        self.messages: list[Any] = []
        self.fail_after = fail_after

    def __enter__(self) -> FakeSender:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def send_messages(self, message: Any) -> None:
        if self.fail_after is not None and len(self.messages) >= self.fail_after:
            from azure.servicebus.exceptions import ServiceBusConnectionError

            raise ServiceBusConnectionError()
        self.messages.append(message)


class FakeReceiver:
    def __init__(self, messages: list[Any] | None = None) -> None:
        self.messages = messages or []
        self.completed: list[Any] = []
        self.abandoned: list[Any] = []
        self.dead_lettered: list[tuple[Any, str, str]] = []

    def complete_message(self, message: Any) -> None:
        self.completed.append(message)

    def abandon_message(self, message: Any) -> None:
        self.abandoned.append(message)

    def dead_letter_message(
        self, message: Any, *, reason: str, error_description: str
    ) -> None:
        self.dead_lettered.append((message, reason, error_description))

    def receive_messages(
        self, *, max_message_count: int, max_wait_time: float
    ) -> list[Any]:
        del max_wait_time
        return self.messages[:max_message_count]


class FakeBusClient:
    def __init__(self, sender: FakeSender, receiver: FakeReceiver | None = None) -> None:
        self.sender = sender
        self.receiver = receiver or FakeReceiver()

    def get_queue_sender(self, *, queue_name: str) -> FakeSender:
        assert queue_name
        return self.sender

    def get_queue_receiver(self, **kwargs: Any) -> FakeReceiver:
        assert kwargs["queue_name"]
        return self.receiver


class MemoryDedupe:
    def __init__(self) -> None:
        self.processed: set[tuple[str, str]] = set()

    def has_processed(self, consumer: str, event_id: str) -> bool:
        return (consumer, event_id) in self.processed

    def mark_processed(self, consumer: str, event_id: str) -> None:
        self.processed.add((consumer, event_id))


class FakeBlob:
    def __init__(self, url: str) -> None:
        self.url = url
        self.metadata: dict[str, str] | None = None
        self.content: bytes | None = None

    def upload_blob(self, data: bytes, **kwargs: Any) -> None:
        if self.content is not None:
            raise ResourceExistsError("exists")
        self.content = data
        self.metadata = dict(kwargs["metadata"])

    def get_blob_properties(self) -> Any:
        return SimpleNamespace(metadata=self.metadata or {})


class FakeBlobContainer:
    def __init__(self) -> None:
        self.blobs: dict[str, FakeBlob] = {}

    def get_blob_client(self, blob: str) -> FakeBlob:
        return self.blobs.setdefault(blob, FakeBlob(f"https://storage/{blob}"))


def _request() -> IntakeRequest:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return IntakeRequest(
        request_id="request-1",
        tenant_id="tenant-1",
        requester_id="requester-1",
        conversation_key="conversation-1",
        template=default_template(),
        assigned_reviewer_id="reviewer-1",
        created_at=now,
        updated_at=now,
    )


def _actor() -> ActorContext:
    return ActorContext(
        tenant_id="tenant-1",
        actor_id="requester-1",
        roles=frozenset({ActorRole.REQUESTER}),
        provenance=Provenance(
            agent_kind=AgentKind.HOSTED,
            agent_version="1",
            instructions_version="1",
            model_version="1",
            toolbox_version="1",
            mcp_contract_version="1.0",
            policy_version="1",
        ),
        correlation_id="correlation-1",
    )


def _event(index: int = 1) -> OutboxEvent:
    return OutboxEvent(
        event_id=f"event-{index}",
        event_type="RequestSubmitted",
        event_version="1.0",
        request_id="request-1",
        revision=1,
        correlation_id="correlation-1",
        causation_id="command-1",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        actor_id="requester-1",
        data={},
    )


def _wire_event(event_id: str = "event-1") -> dict[str, Any]:
    return {
        "eventId": event_id,
        "eventType": "DeliveryRequested",
        "eventVersion": "1.0",
        "requestId": "request-1",
        "revision": 1,
        "correlationId": "correlation-1",
        "data": {},
    }


def test_request_serialization_round_trips_extended_projection() -> None:
    request = _request()
    request.delivery_failure_reason = "safe diagnostic"
    request.notification_results["notification-1"] = "succeeded"
    request.retention_status = "held"

    restored = request_from_document(request_to_document(request))

    assert restored == request


def test_cosmos_mutation_batches_projection_audit_and_outbox_with_etag() -> None:
    requests = FakeCosmosContainer()
    idempotency = FakeCosmosContainer()
    request = _request()
    document = request_to_document(request)
    document["_etag"] = "etag-current"
    requests.documents[(request.request_id, "request")] = document
    store = CosmosRequestStore(requests, idempotency)

    result = store.mutate(
        request.request_id,
        0,
        _actor(),
        "command-1",
        "fingerprint-1",
        lambda candidate: Mutation(
            data={"changed": True},
            events=(PendingEvent("RequestFieldsUpdated", {"fieldPaths": ["title"]}),),
        ),
    )

    assert result.data["requestRevision"] == 1
    partition_key, operations = requests.batches[0]
    assert partition_key == request.request_id
    documents = [
        operation[1][1] if operation[0] == "replace" else operation[1][0]
        for operation in operations
    ]
    assert {item["docType"] for item in documents} == {
        "request",
        "audit",
        "outbox",
    }
    assert operations[0][2]["if_match_etag"] == "etag-current"
    idempotency_document = next(iter(idempotency.documents.values()))
    assert idempotency_document["ttl"] == INTERACTIVE_IDEMPOTENCY_TTL_SECONDS


def test_cosmos_etag_conflict_returns_latest_revision() -> None:
    requests = FakeCosmosContainer()
    idempotency = FakeCosmosContainer()
    request = _request()
    current = request_to_document(request)
    current["_etag"] = "etag-current"
    requests.documents[(request.request_id, "request")] = current
    requests.batch_error = exceptions.CosmosAccessConditionFailedError(
        status_code=412,
        message="precondition failed",
    )
    store = CosmosRequestStore(requests, idempotency)

    with pytest.raises(DomainError) as caught:
        store.mutate(
            request.request_id,
            0,
            _actor(),
            "command-1",
            "fingerprint-1",
            lambda candidate: Mutation(data={}, events=()),
        )

    assert getattr(caught.value, "latest_revision", None) == 0


def test_consumer_deduplication_uses_async_ttl() -> None:
    container = FakeCosmosContainer()
    store = CosmosConsumerDeduplicationStore(container)

    store.mark_processed("integration", "event-1")

    document = next(iter(container.documents.values()))
    assert document["ttl"] == ASYNC_IDEMPOTENCY_TTL_SECONDS
    assert store.has_processed("integration", "event-1")


def test_dispatcher_marks_only_messages_sent_before_transient_failure() -> None:
    outbox = FakeOutbox([_event(1), _event(2)])
    sender = FakeSender(fail_after=1)
    dispatcher = ServiceBusOutboxDispatcher(
        outbox,
        FakeBusClient(sender),
        "domain-events",
    )

    with pytest.raises(TransientAzureError) as caught:
        dispatcher.dispatch_pending()

    assert getattr(caught.value, "retryable", False)
    assert [event.event_id for event in outbox.dispatched] == ["event-1"]


def test_consumer_completes_duplicates_retries_and_dead_letters() -> None:
    dedupe = MemoryDedupe()
    event = _wire_event()
    message = SimpleNamespace(
        body=json.dumps(event).encode(),
        delivery_count=1,
        message_id="message-1",
    )
    receiver = FakeReceiver()
    completed = ServiceBusConsumer(
        dedupe,
        lambda value: None,
        ConsumerPolicy("integration"),
    )
    assert completed.process(message, receiver) == "completed"
    assert completed.process(message, receiver) == "duplicate"

    retry = ServiceBusConsumer(
        MemoryDedupe(),
        lambda value: _raise_retry(),
        ConsumerPolicy("integration", maximum_delivery_count=2),
    )
    assert retry.process(message, receiver) == "abandoned"
    message.delivery_count = 2
    assert retry.process(message, receiver) == "dead_lettered"

    permanent = ServiceBusConsumer(
        MemoryDedupe(),
        lambda value: _raise_permanent(),
        ConsumerPolicy("integration"),
    )
    assert permanent.process(message, receiver) == "dead_lettered"


def test_dead_letter_replay_validates_and_resubmits() -> None:
    dead_letter = SimpleNamespace(
        body=json.dumps(_wire_event()).encode(),
        message_id="dead-letter-1",
    )
    receiver = FakeReceiver([dead_letter])
    sender = FakeSender()
    replayer = ServiceBusDeadLetterReplayer(
        FakeBusClient(sender, receiver),
        "domain-events",
    )

    assert replayer.replay() == 1
    assert receiver.completed == [dead_letter]
    assert len(sender.messages) == 1


def test_blob_evidence_is_create_only_and_checksum_idempotent() -> None:
    container = FakeBlobContainer()
    store = BlobEvaluationEvidenceStore(container)
    evidence = EvaluationEvidence(
        dataset_id="dataset",
        dataset_version="1.0",
        run_id="run-1",
        filename="scorecard.json",
        content_type="application/json",
        classification="internal",
        evaluator_version="1.0",
    )

    first = store.store(b"{}", evidence)
    replay = store.store(b"{}", evidence)

    assert first == replay
    with pytest.raises(PermanentAzureError):
        store.store(b'{"changed":true}', evidence)


def _raise_retry() -> None:
    raise RetryableMessageError("try again")


def _raise_permanent() -> None:
    raise PermanentMessageError("do not retry")
