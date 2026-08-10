"""Azure Functions entry point for intake workers.

Each function trigger is defined here.
Workers use intake_domain and intake_persistence only — never intake_agent.
"""
from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

import azure.functions as func

from intake_persistence.cosmos import CosmosOutboxRepository, CosmosRepositoryContext
from intake_persistence.servicebus import ServiceBusOutboxDispatcher

logger = logging.getLogger(__name__)

app = func.FunctionApp()


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%INTAKE_SERVICEBUS_QUEUE%",
    connection="INTAKE_SERVICEBUS_NAMESPACE",
)
def domain_event_dispatcher(msg: func.ServiceBusMessage) -> None:
    """Routes incoming domain events to the appropriate worker."""
    body = msg.get_body().decode("utf-8")
    logger.info("domain_event_dispatcher received message", extra={"msg_length": len(body)})
    # Routing to specific workers is deferred to full implementation


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="document-generation",
    connection="INTAKE_SERVICEBUS_NAMESPACE",
)
def document_worker(msg: func.ServiceBusMessage) -> None:
    """Generates Word/PDF artifacts from the approved revision."""
    body = msg.get_body().decode("utf-8")
    logger.info("document_worker triggered", extra={"msg_length": len(body)})


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="notification-queue",
    connection="INTAKE_SERVICEBUS_NAMESPACE",
)
def notification_worker(msg: func.ServiceBusMessage) -> None:
    """Sends notifications on state transitions."""
    body = msg.get_body().decode("utf-8")
    logger.info("notification_worker triggered", extra={"msg_length": len(body)})


@app.timer_trigger(
    arg_name="timer",
    schedule="*/5 * * * *",
    run_on_startup=False,
)
def outbox_dispatcher(timer: func.TimerRequest) -> None:
    """Polls the outbox and dispatches pending domain events."""
    if _is_unconfigured_local_worker():
        logger.info("outbox_dispatcher skipped for unconfigured local worker")
        return
    dispatcher = _get_outbox_dispatcher()
    try:
        count = asyncio.run(_dispatch_and_close(dispatcher))
    finally:
        cache_clear = getattr(_get_outbox_dispatcher, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()
    logger.info("outbox_dispatcher completed", extra={"dispatched_count": count})


async def _dispatch_and_close(dispatcher: ServiceBusOutboxDispatcher) -> int:
    try:
        return await dispatcher.dispatch_pending()
    finally:
        close = getattr(dispatcher, "close", None)
        if close is not None:
            await close()


@lru_cache(maxsize=1)
def _get_outbox_dispatcher() -> ServiceBusOutboxDispatcher:
    endpoint = _required_environment("INTAKE_COSMOS_ENDPOINT")
    database = os.getenv("INTAKE_COSMOS_DATABASE", "intake").strip()
    namespace = (
        os.getenv("INTAKE_SERVICEBUS_NAMESPACE", "").strip()
        or os.getenv(
            "INTAKE_SERVICEBUS_NAMESPACE__" + "fullyQualifiedNamespace",
            "",
        ).strip()
    )
    if not namespace:
        raise RuntimeError(
            "INTAKE_SERVICEBUS_NAMESPACE or "
            "INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace is required"
        )
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    context = CosmosRepositoryContext(
        endpoint,
        database,
        requests_container=os.getenv(
            "INTAKE_COSMOS_REQUESTS_CONTAINER",
            "requests",
        ).strip(),
        templates_container=os.getenv(
            "INTAKE_COSMOS_TEMPLATES_CONTAINER",
            "templates",
        ).strip(),
        idempotency_container=os.getenv(
            "INTAKE_COSMOS_IDEMPOTENCY_CONTAINER",
            "idempotency",
        ).strip(),
        managed_identity_client_id=client_id,
    )
    outbox = CosmosOutboxRepository(endpoint, database, context=context)
    return ServiceBusOutboxDispatcher(
        outbox,
        namespace,
        os.getenv("INTAKE_SERVICEBUS_QUEUE", "domain-events").strip(),
        managed_identity_client_id=client_id,
    )


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _is_unconfigured_local_worker() -> bool:
    environment = os.getenv("INTAKE_ENVIRONMENT", "local").strip().lower()
    return environment == "local" and not os.getenv("INTAKE_COSMOS_ENDPOINT", "").strip()
