"""Deterministic worker services over application and integration ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intake_agent_contracts import ApprovedField, ApprovedRequestHandover
from intake_application import IntakeService, Outcome
from intake_domain import (
    ActorContext,
    ErrorCode,
    IntakeRequest,
    RequestStore,
)
from intake_persistence import (
    PermanentMessageError,
    RetryableMessageError,
    ServiceBusOutboxDispatcher,
)

from intake_workers.ports import IntegrationPort, NotificationPort, RetentionPort


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    event_id: str
    event_type: str
    request_id: str
    revision: int
    correlation_id: str
    data: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> WorkerEvent:
        try:
            return cls(
                event_id=str(value["eventId"]),
                event_type=str(value["eventType"]),
                request_id=str(value["requestId"]),
                revision=int(value["revision"]),
                correlation_id=str(value.get("correlationId", "")),
                data=_mapping(value.get("data", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentMessageError("The worker event is invalid.") from exc


class ServiceCommandFacade:
    """Private commands callable only by immutable service actors."""

    def __init__(
        self,
        service: IntakeService,
        store: RequestStore,
        *,
        integration_actor: ActorContext,
        notification_actor: ActorContext,
        completion_actor: ActorContext,
        retention_actor: ActorContext,
    ) -> None:
        self._service = service
        self._store = store
        self._integration_actor = integration_actor
        self._notification_actor = notification_actor
        self._completion_actor = completion_actor
        self._retention_actor = retention_actor

    def delivery_result(
        self,
        event: WorkerEvent,
        target: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        request = self._required(event.request_id)
        self._require_success(
            self._service.record_delivery_result(
                self._integration_actor,
                request.request_id,
                request.version,
                f"delivery-result:{event.event_id}:{status}",
                target,
                status,
                reason,
            )
        )

    def notification_result(
        self,
        event: WorkerEvent,
        notification_id: str,
        status: str,
    ) -> None:
        request = self._required(event.request_id)
        self._require_success(
            self._service.record_notification_result(
                self._notification_actor,
                request.request_id,
                request.version,
                f"notification-result:{event.event_id}:{status}",
                notification_id,
                status,
            )
        )

    def complete(self, event: WorkerEvent) -> None:
        request = self._required(event.request_id)
        self._require_success(
            self._service.complete_request_if_ready(
                self._completion_actor,
                request.request_id,
                request.version,
                f"complete:{event.event_id}",
            )
        )

    def retention_result(self, event: WorkerEvent, status: str) -> None:
        request = self._required(event.request_id)
        self._require_success(
            self._service.record_retention_result(
                self._retention_actor,
                request.request_id,
                request.version,
                f"retention-result:{event.event_id}:{status}",
                status,
            )
        )

    def _required(self, request_id: str) -> IntakeRequest:
        request = self._store.get(request_id)
        if request is None:
            raise PermanentMessageError("The request no longer exists.")
        return request

    @staticmethod
    def _require_success(outcome: Outcome) -> None:
        if outcome.ok:
            return
        error = outcome.error
        if error is not None and error.code is ErrorCode.CONCURRENCY_CONFLICT:
            raise RetryableMessageError(error.message)
        raise PermanentMessageError(
            error.message if error is not None else "A service command failed."
        )


class OutboxWorker:
    def __init__(self, dispatcher: ServiceBusOutboxDispatcher) -> None:
        self._dispatcher = dispatcher

    def run(self, batch_size: int = 25) -> int:
        return self._dispatcher.dispatch_pending(batch_size)


class NotificationWorker:
    def __init__(
        self,
        notifications: NotificationPort,
        commands: ServiceCommandFacade,
    ) -> None:
        self._notifications = notifications
        self._commands = commands

    def handle(self, value: dict[str, Any]) -> None:
        event = WorkerEvent.from_mapping(value)
        recipient_id = str(event.data.get("recipientId", ""))
        deep_link = str(event.data.get("deepLink", ""))
        if not recipient_id or not deep_link:
            raise PermanentMessageError(
                "Notification events require recipientId and deepLink."
            )
        notification_id = self._notifications.send(
            request_id=event.request_id,
            recipient_id=recipient_id,
            event_type=event.event_type,
            deep_link=deep_link,
            idempotency_key=f"notification:{event.event_id}",
        )
        self._commands.notification_result(event, notification_id, "succeeded")


class IntegrationWorker:
    def __init__(
        self,
        store: RequestStore,
        integration: IntegrationPort,
        commands: ServiceCommandFacade,
        *,
        target_name: str,
    ) -> None:
        self._store = store
        self._integration = integration
        self._commands = commands
        self._target_name = target_name

    def handle(self, value: dict[str, Any]) -> None:
        event = WorkerEvent.from_mapping(value)
        request = self._store.get(event.request_id)
        if request is None or request.approved_revision is None:
            raise PermanentMessageError(
                "Delivery requires an immutable approved revision."
            )
        payload = _handover(request)
        try:
            self._integration.deliver(
                payload,
                idempotency_key=f"handover:{event.event_id}",
            )
        except RetryableMessageError as exc:
            self._commands.delivery_result(
                event,
                self._target_name,
                "retryable_failure",
                str(exc),
            )
            raise
        except PermanentMessageError as exc:
            self._commands.delivery_result(
                event,
                self._target_name,
                "permanent_failure",
                str(exc),
            )
            raise
        self._commands.delivery_result(event, self._target_name, "succeeded")


class CompletionWorker:
    def __init__(self, commands: ServiceCommandFacade) -> None:
        self._commands = commands

    def handle(self, value: dict[str, Any]) -> None:
        self._commands.complete(WorkerEvent.from_mapping(value))


class RetentionWorker:
    def __init__(
        self,
        retention: RetentionPort,
        commands: ServiceCommandFacade,
    ) -> None:
        self._retention = retention
        self._commands = commands

    def handle(self, value: dict[str, Any]) -> None:
        event = WorkerEvent.from_mapping(value)
        legal_hold = bool(event.data.get("legalHold", False))
        status = self._retention.apply(
            request_id=event.request_id,
            legal_hold=legal_hold,
            idempotency_key=f"retention:{event.event_id}",
        )
        if status not in {"deleted", "held", "failed"}:
            raise PermanentMessageError("The retention adapter returned an invalid status.")
        self._commands.retention_result(event, status)


def _handover(request: IntakeRequest) -> ApprovedRequestHandover:
    revision = request.approved_revision
    if revision is None:
        raise PermanentMessageError("The approved revision cannot be loaded.")
    return ApprovedRequestHandover(
        requestId=request.request_id,
        tenantId=request.tenant_id,
        approvedRevision=revision.revision_number,
        templateId=request.template.template_id,
        templateVersion=revision.template_version,
        schemaVersion=revision.schema_version,
        approvedAt=revision.submitted_at.isoformat(),
        fields=tuple(
            ApprovedField(
                fieldPath=field.field_path,
                value=field.value,
                sourceReference=field.source_reference,
            )
            for field in revision.fields
        ),
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PermanentMessageError("Worker event data must be an object.")
    return {str(key): item for key, item in value.items()}
