"""Durable outbox dispatch to Azure Service Bus using managed identity."""
from __future__ import annotations

import json
from typing import Any, NoReturn

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
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

from intake_domain.entities import OutboxItem
from intake_domain.errors import PermanentError, TransientError
from intake_domain.repositories import OutboxRepository

_TRANSIENT_SERVICEBUS_ERRORS = (
    OperationTimeoutError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    ServiceBusQuotaExceededError,
    ServiceBusServerBusyError,
)
_PERMANENT_SERVICEBUS_ERRORS = (
    MessageSizeExceededError,
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
)


class ServiceBusOutboxDispatcher:
    """Publishes pending events and commits dispatch markers after acknowledgement."""

    def __init__(
        self,
        outbox_repo: OutboxRepository,
        namespace: str,
        queue_name: str,
        *,
        managed_identity_client_id: str = "",
        client: Any | None = None,
    ) -> None:
        self._outbox_repo = outbox_repo
        self._queue_name = queue_name
        self._credential: Any | None = None
        if client is None:
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=managed_identity_client_id or None
            )
            client = ServiceBusClient(
                fully_qualified_namespace=namespace,
                credential=self._credential,
            )
        self._client = client

    async def dispatch_pending(self, batch_size: int = 25) -> int:
        """Publish up to ``batch_size`` outbox records with at-least-once delivery."""
        pending = await self._outbox_repo.get_pending(batch_size)
        if not pending:
            return 0

        dispatched_ids: list[str] = []
        try:
            sender = self._client.get_queue_sender(queue_name=self._queue_name)
            async with sender:
                for item in pending:
                    await sender.send_messages(_to_servicebus_message(item))
                    dispatched_ids.append(item.item_id)
        except _TRANSIENT_SERVICEBUS_ERRORS as exc:
            await self._commit_successes(dispatched_ids)
            raise TransientError(
                "Service Bus outbox dispatch failed",
                dispatched_count=len(dispatched_ids),
            ) from exc
        except _PERMANENT_SERVICEBUS_ERRORS as exc:
            await self._commit_successes(dispatched_ids)
            raise PermanentError(
                "Service Bus outbox dispatch failed",
                dispatched_count=len(dispatched_ids),
            ) from exc
        except ServiceBusError as exc:
            await self._commit_successes(dispatched_ids)
            _raise_servicebus_error(exc, len(dispatched_ids))

        await self._commit_successes(dispatched_ids)
        return len(dispatched_ids)

    async def close(self) -> None:
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()
        close_outbox = getattr(self._outbox_repo, "close", None)
        if close_outbox is not None:
            await close_outbox()

    async def _commit_successes(self, item_ids: list[str]) -> None:
        if item_ids:
            await self._outbox_repo.mark_dispatched(item_ids)


def _to_servicebus_message(item: OutboxItem) -> ServiceBusMessage:
    correlation_id = item.payload.get("correlation_id")
    return ServiceBusMessage(
        json.dumps(item.payload, separators=(",", ":"), sort_keys=True),
        message_id=item.item_id,
        correlation_id=str(correlation_id) if correlation_id else None,
        subject=item.event_type,
        content_type="application/json",
        application_properties={
            "event_type": item.event_type,
            "request_id": item.request_id,
        },
    )


def _raise_servicebus_error(exc: ServiceBusError, dispatched_count: int) -> NoReturn:
    if bool(getattr(exc, "retryable", False)):
        raise TransientError(
            "Service Bus outbox dispatch failed",
            dispatched_count=dispatched_count,
        ) from exc
    raise PermanentError(
        "Service Bus outbox dispatch failed",
        dispatched_count=dispatched_count,
    ) from exc


__all__ = ["ServiceBusOutboxDispatcher"]
