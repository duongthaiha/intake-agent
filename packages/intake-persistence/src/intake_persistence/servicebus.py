"""Service Bus outbox dispatch, consumer settlement, and dead-letter replay."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from azure.servicebus import ServiceBusMessage, ServiceBusSubQueue
from azure.servicebus.exceptions import (
    MessageSizeExceededError,
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    OperationTimeoutError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    ServiceBusError,
    ServiceBusQuotaExceededError,
    ServiceBusServerBusyError,
)
from intake_domain import OutboxEvent

from intake_persistence.azure_errors import (
    MessageContractError,
    PermanentAzureError,
    PermanentMessageError,
    RetryableMessageError,
    TransientAzureError,
)

_TRANSIENT_ERRORS = (
    OperationTimeoutError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    ServiceBusQuotaExceededError,
    ServiceBusServerBusyError,
)
_PERMANENT_ERRORS = (
    MessageSizeExceededError,
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
)


class OutboxRepository(Protocol):
    def get_pending(self, batch_size: int = 25) -> Sequence[OutboxEvent]: ...

    def mark_dispatched(self, events: Sequence[OutboxEvent]) -> None: ...


class ConsumerDeduplicationStore(Protocol):
    def has_processed(self, consumer: str, event_id: str) -> bool: ...

    def mark_processed(self, consumer: str, event_id: str) -> None: ...


class Sender(Protocol):
    def __enter__(self) -> Sender: ...

    def __exit__(self, *args: object) -> None: ...

    def send_messages(self, message: ServiceBusMessage) -> None: ...


class Receiver(Protocol):
    def complete_message(self, message: Any) -> None: ...

    def abandon_message(self, message: Any) -> None: ...

    def dead_letter_message(
        self, message: Any, *, reason: str, error_description: str
    ) -> None: ...

    def receive_messages(
        self, *, max_message_count: int, max_wait_time: float
    ) -> Sequence[Any]: ...


class ServiceBusClient(Protocol):
    def get_queue_sender(self, *, queue_name: str) -> Sender: ...

    def get_topic_sender(self, *, topic_name: str) -> Sender: ...

    def get_queue_receiver(self, **kwargs: Any) -> Receiver: ...


class ServiceBusOutboxDispatcher:
    """Publishes committed events and marks only acknowledged items dispatched."""

    def __init__(
        self,
        outbox: OutboxRepository,
        client: ServiceBusClient,
        queue_name: str | None = None,
        *,
        topic_name: str | None = None,
    ) -> None:
        if bool(queue_name) == bool(topic_name):
            raise ValueError("Exactly one Service Bus queue or topic is required.")
        self._outbox = outbox
        self._client = client
        self._queue_name = queue_name
        self._topic_name = topic_name

    def dispatch_pending(self, batch_size: int = 25) -> int:
        pending = self._outbox.get_pending(batch_size)
        dispatched: list[OutboxEvent] = []
        try:
            sender_context = (
                self._client.get_topic_sender(topic_name=self._topic_name)
                if self._topic_name
                else self._client.get_queue_sender(queue_name=self._queue_name or "")
            )
            with sender_context as sender:
                for event in pending:
                    sender.send_messages(_message_for_event(event))
                    dispatched.append(event)
        except _TRANSIENT_ERRORS as exc:
            self._outbox.mark_dispatched(dispatched)
            raise TransientAzureError("Service Bus outbox dispatch failed.") from exc
        except _PERMANENT_ERRORS as exc:
            self._outbox.mark_dispatched(dispatched)
            raise PermanentAzureError("Service Bus outbox dispatch failed.") from exc
        except ServiceBusError as exc:
            self._outbox.mark_dispatched(dispatched)
            if bool(getattr(exc, "retryable", False)):
                raise TransientAzureError(
                    "Service Bus outbox dispatch failed."
                ) from exc
            raise PermanentAzureError("Service Bus outbox dispatch failed.") from exc
        self._outbox.mark_dispatched(dispatched)
        return len(dispatched)


@dataclass(frozen=True, slots=True)
class ConsumerPolicy:
    consumer_name: str
    maximum_delivery_count: int = 10
    maximum_message_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if self.maximum_delivery_count < 1 or self.maximum_message_bytes < 1:
            raise ValueError("Consumer policy limits must be positive.")


class ServiceBusConsumer:
    """Settles at-least-once messages with durable deduplication."""

    def __init__(
        self,
        deduplication: ConsumerDeduplicationStore,
        handler: Callable[[dict[str, Any]], None],
        policy: ConsumerPolicy,
    ) -> None:
        self._deduplication = deduplication
        self._handler = handler
        self._policy = policy

    def process(self, message: Any, receiver: Receiver) -> str:
        try:
            event = _read_event(message, self._policy.maximum_message_bytes)
        except MessageContractError as exc:
            receiver.dead_letter_message(
                message,
                reason="InvalidEventContract",
                error_description=str(exc)[:500],
            )
            return "dead_lettered"

        return self._process_event(
            event,
            on_complete=lambda: receiver.complete_message(message),
            on_retry=lambda description: self._retry(
                message,
                receiver,
                description,
            ),
            on_permanent=lambda description: receiver.dead_letter_message(
                message,
                reason="PermanentConsumerFailure",
                error_description=description,
            ),
        )

    def process_auto_settled(self, event: dict[str, Any]) -> str:
        """Process an already decoded event when the host owns broker settlement."""
        validated = _read_event(
            json.dumps(event, separators=(",", ":")).encode(),
            self._policy.maximum_message_bytes,
        )
        return self._process_event(
            validated,
            on_complete=lambda: None,
            on_retry=lambda description: _raise_retry(description),
            on_permanent=lambda description: _raise_permanent(description),
        )

    def _process_event(
        self,
        event: dict[str, Any],
        *,
        on_complete: Callable[[], None],
        on_retry: Callable[[str], str],
        on_permanent: Callable[[str], None],
    ) -> str:
        event_id = str(event["eventId"])
        if self._deduplication.has_processed(
            self._policy.consumer_name, event_id
        ):
            on_complete()
            return "duplicate"
        try:
            self._handler(event)
        except PermanentMessageError as exc:
            on_permanent(str(exc)[:500])
            return "dead_lettered"
        except RetryableMessageError as exc:
            return on_retry(str(exc)[:500])

        self._deduplication.mark_processed(self._policy.consumer_name, event_id)
        on_complete()
        return "completed"

    def _retry(self, message: Any, receiver: Receiver, description: str) -> str:
        if int(getattr(message, "delivery_count", 0) or 0) >= (
            self._policy.maximum_delivery_count
        ):
            receiver.dead_letter_message(
                message,
                reason="RetriesExhausted",
                error_description=description,
            )
            return "dead_lettered"
        receiver.abandon_message(message)
        return "abandoned"


class ServiceBusDeadLetterReplayer:
    """Validates dead letters and resubmits them with a new broker message ID."""

    def __init__(
        self,
        client: ServiceBusClient,
        queue_name: str,
        *,
        maximum_message_bytes: int = 256 * 1024,
    ) -> None:
        self._client = client
        self._queue_name = queue_name
        self._maximum_message_bytes = maximum_message_bytes

    def replay(self, maximum_messages: int = 25, wait_seconds: float = 1.0) -> int:
        receiver = self._client.get_queue_receiver(
            queue_name=self._queue_name,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER,
        )
        messages = receiver.receive_messages(
            max_message_count=maximum_messages,
            max_wait_time=wait_seconds,
        )
        replayed = 0
        with self._client.get_queue_sender(queue_name=self._queue_name) as sender:
            for dead_letter in messages:
                event = _read_event(dead_letter, self._maximum_message_bytes)
                original_message_id = str(
                    getattr(dead_letter, "message_id", "") or event["eventId"]
                )
                sender.send_messages(
                    ServiceBusMessage(
                        json.dumps(event, separators=(",", ":"), sort_keys=True),
                        message_id=f"replay:{uuid4()}",
                        correlation_id=str(event.get("correlationId", "")) or None,
                        subject=str(event["eventType"]),
                        content_type="application/json",
                        application_properties={
                            "replayed": True,
                            "original_message_id": original_message_id,
                        },
                    )
                )
                receiver.complete_message(dead_letter)
                replayed += 1
        return replayed


def _message_for_event(event: OutboxEvent) -> ServiceBusMessage:
    payload = {
        "eventId": event.event_id,
        "eventType": event.event_type,
        "eventVersion": event.event_version,
        "requestId": event.request_id,
        "revision": event.revision,
        "correlationId": event.correlation_id,
        "causationId": event.causation_id,
        "occurredAt": event.occurred_at.isoformat(),
        "actorId": event.actor_id,
        "data": event.data,
    }
    return ServiceBusMessage(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        message_id=event.event_id,
        correlation_id=event.correlation_id,
        subject=event.event_type,
        content_type="application/json",
        application_properties={
            "event_type": event.event_type,
            "event_version": event.event_version,
            "request_id": event.request_id,
        },
    )


def _read_event(message: Any, maximum_message_bytes: int) -> dict[str, Any]:
    raw = _message_bytes(message)
    if len(raw) > maximum_message_bytes:
        raise MessageContractError("The event exceeds the configured size limit.")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MessageContractError("The event body is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise MessageContractError("The event body must be a JSON object.")
    event = {str(key): item for key, item in value.items()}
    required = {"eventId", "eventType", "eventVersion", "requestId", "revision"}
    if missing := sorted(required.difference(event)):
        raise MessageContractError(f"The event is missing: {', '.join(missing)}.")
    if str(event["eventVersion"]).split(".", 1)[0] != "1":
        raise MessageContractError("The event major version is unsupported.")
    return event


def _message_bytes(message: Any) -> bytes:
    body = getattr(message, "body", message)
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode()
    if isinstance(body, bytearray):
        return bytes(body)
    try:
        return b"".join(
            part if isinstance(part, bytes) else bytes(part) for part in body
        )
    except (TypeError, ValueError) as exc:
        raise MessageContractError("The event body cannot be decoded.") from exc


def _raise_retry(description: str) -> str:
    raise RetryableMessageError(description)


def _raise_permanent(description: str) -> None:
    raise PermanentMessageError(description)
