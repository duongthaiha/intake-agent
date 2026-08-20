"""Azure Functions trigger host for configured worker services."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import azure.functions as func

from intake_workers.hosts import WorkerHosts

app = func.FunctionApp()
_hosts_provider: Callable[[], WorkerHosts] | None = None
_worker_kind = os.environ.get("WORKER_KIND", "all")


def configure_hosts(provider: Callable[[], WorkerHosts]) -> None:
    """Register the process composition root during Function App startup."""
    global _hosts_provider
    if _hosts_provider is not None:
        raise RuntimeError("Worker hosts are already configured.")
    _hosts_provider = provider


if _worker_kind in {"all", "outbox"}:

    @app.timer_trigger(
        arg_name="timer",
        schedule="0 */5 * * * *",
        run_on_startup=False,
    )
    def outbox_dispatcher(timer: func.TimerRequest) -> None:
        del timer
        _hosts().outbox.run()


if _worker_kind in {"all", "notification"}:

    @app.service_bus_topic_trigger(
        arg_name="message",
        topic_name="%SERVICE_BUS_TOPIC%",
        subscription_name="%SERVICE_BUS_SUBSCRIPTION%",
        connection="INTAKE_SERVICEBUS_NAMESPACE",
    )
    def notification_worker(message: func.ServiceBusMessage) -> None:
        _invoke_auto_settled(_hosts().notification, message)


if _worker_kind in {"all", "integration"}:

    @app.service_bus_topic_trigger(
        arg_name="message",
        topic_name="%SERVICE_BUS_TOPIC%",
        subscription_name="%SERVICE_BUS_SUBSCRIPTION%",
        connection="INTAKE_SERVICEBUS_NAMESPACE",
    )
    def integration_worker(message: func.ServiceBusMessage) -> None:
        _invoke_auto_settled(_hosts().integration, message)


if _worker_kind in {"all", "completion"}:

    @app.service_bus_topic_trigger(
        arg_name="message",
        topic_name="%SERVICE_BUS_TOPIC%",
        subscription_name="%SERVICE_BUS_SUBSCRIPTION%",
        connection="INTAKE_SERVICEBUS_NAMESPACE",
    )
    def completion_worker(message: func.ServiceBusMessage) -> None:
        _invoke_auto_settled(_hosts().completion, message)


if _worker_kind in {"all", "retention"}:

    @app.service_bus_topic_trigger(
        arg_name="message",
        topic_name="%SERVICE_BUS_TOPIC%",
        subscription_name="%SERVICE_BUS_SUBSCRIPTION%",
        connection="INTAKE_SERVICEBUS_NAMESPACE",
    )
    def retention_worker(message: func.ServiceBusMessage) -> None:
        _invoke_auto_settled(_hosts().retention, message)


def _hosts() -> WorkerHosts:
    if _hosts_provider is None:
        raise RuntimeError("Worker hosts have not been configured.")
    return _hosts_provider()


def _invoke_auto_settled(consumer: Any, message: func.ServiceBusMessage) -> None:
    """Use the same validation/handler path while Functions owns settlement."""
    event = _decode_message(message)
    consumer.process_auto_settled(event)


def _decode_message(message: func.ServiceBusMessage) -> dict[str, Any]:
    value = json.loads(message.get_body())
    if not isinstance(value, dict):
        raise ValueError("Worker event body must be a JSON object.")
    return {str(key): item for key, item in value.items()}
