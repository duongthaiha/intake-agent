"""Worker host composition and Service Bus consumer wiring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from intake_application import IntakeService
from intake_domain import (
    ActorContext,
    ActorRole,
    AgentKind,
    Provenance,
    TemplateVersion,
)
from intake_persistence.composition import (
    AzurePersistenceRuntime,
    AzurePersistenceSettings,
    build_azure_persistence,
)
from intake_persistence.servicebus import (
    ConsumerPolicy,
    ServiceBusConsumer,
    ServiceBusDeadLetterReplayer,
)
from intake_persistence.servicebus import (
    ServiceBusClient as ServiceBusClientPort,
)

from intake_workers.ports import IntegrationPort, NotificationPort, RetentionPort
from intake_workers.services import (
    CompletionWorker,
    IntegrationWorker,
    NotificationWorker,
    OutboxWorker,
    RetentionWorker,
    ServiceCommandFacade,
)


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    persistence: AzurePersistenceSettings
    tenant_id: str
    default_reviewer_id: str
    integration_target: str
    notification_actor_id: str
    integration_actor_id: str
    completion_actor_id: str
    retention_actor_id: str
    maximum_delivery_count: int = 10
    maximum_message_bytes: int = 256 * 1024


@dataclass(slots=True)
class WorkerHosts:
    persistence: AzurePersistenceRuntime
    outbox: OutboxWorker
    notification: ServiceBusConsumer
    integration: ServiceBusConsumer
    completion: ServiceBusConsumer
    retention: ServiceBusConsumer
    replay: ServiceBusDeadLetterReplayer

    def close(self) -> None:
        self.persistence.close()


def build_worker_hosts(
    settings: WorkerSettings,
    templates: dict[str, TemplateVersion],
    *,
    notifications: NotificationPort,
    integration: IntegrationPort,
    retention: RetentionPort,
) -> WorkerHosts:
    """Build all worker processes and workload actors at the composition root."""
    persistence = build_azure_persistence(settings.persistence)
    service = IntakeService(
        persistence.request_store,
        templates,
        default_reviewer_id=settings.default_reviewer_id,
    )
    commands = ServiceCommandFacade(
        service,
        persistence.request_store,
        integration_actor=_service_actor(
            settings.tenant_id,
            settings.integration_actor_id,
            ActorRole.INTEGRATION_WORKER,
        ),
        notification_actor=_service_actor(
            settings.tenant_id,
            settings.notification_actor_id,
            ActorRole.NOTIFICATION_WORKER,
        ),
        completion_actor=_service_actor(
            settings.tenant_id,
            settings.completion_actor_id,
            ActorRole.COMPLETION_WORKER,
        ),
        retention_actor=_service_actor(
            settings.tenant_id,
            settings.retention_actor_id,
            ActorRole.RETENTION_WORKER,
        ),
    )
    notification_worker = NotificationWorker(notifications, commands)
    integration_worker = IntegrationWorker(
        persistence.request_store,
        integration,
        commands,
        target_name=settings.integration_target,
    )
    completion_worker = CompletionWorker(commands)
    retention_worker = RetentionWorker(retention, commands)
    return WorkerHosts(
        persistence=persistence,
        outbox=OutboxWorker(persistence.dispatcher),
        notification=_consumer(
            persistence,
            "notification-worker",
            notification_worker.handle,
            settings,
        ),
        integration=_consumer(
            persistence,
            "integration-worker",
            integration_worker.handle,
            settings,
        ),
        completion=_consumer(
            persistence,
            "completion-worker",
            completion_worker.handle,
            settings,
        ),
        retention=_consumer(
            persistence,
            "retention-worker",
            retention_worker.handle,
            settings,
        ),
        replay=ServiceBusDeadLetterReplayer(
            cast(ServiceBusClientPort, persistence.service_bus_client),
            settings.persistence.service_bus_queue,
            maximum_message_bytes=settings.maximum_message_bytes,
        ),
    )


def _consumer(
    persistence: AzurePersistenceRuntime,
    name: str,
    handler: Callable[[dict[str, Any]], None],
    settings: WorkerSettings,
) -> ServiceBusConsumer:
    return ServiceBusConsumer(
        persistence.deduplication,
        handler,
        ConsumerPolicy(
            consumer_name=name,
            maximum_delivery_count=settings.maximum_delivery_count,
            maximum_message_bytes=settings.maximum_message_bytes,
        ),
    )


def _service_actor(
    tenant_id: str,
    actor_id: str,
    role: ActorRole,
) -> ActorContext:
    if not tenant_id:
        raise ValueError("A worker tenant ID is required.")
    if not actor_id:
        raise ValueError(f"An actor ID is required for {role.value}.")
    return ActorContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        roles=frozenset({role}),
        provenance=Provenance(
            agent_kind=AgentKind.SERVICE,
            agent_version="worker-1.0",
            instructions_version="none",
            model_version="none",
            toolbox_version="none",
            mcp_contract_version="1.0",
            policy_version="1.0",
        ),
        correlation_id=f"service:{role.value}",
    )
