"""Azure Functions trigger host for configured worker services."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import azure.functions as func

from intake_workers.hosts import WorkerHosts

app = func.FunctionApp()
_hosts_provider: Callable[[], WorkerHosts] | None = None


def configure_hosts(provider: Callable[[], WorkerHosts]) -> None:
    """Register the process composition root during Function App startup."""
    global _hosts_provider
    if _hosts_provider is not None:
        raise RuntimeError("Worker hosts are already configured.")
    _hosts_provider = provider


@app.timer_trigger(
    arg_name="timer",
    schedule="0 */5 * * * *",
    run_on_startup=False,
)
def outbox_dispatcher(timer: func.TimerRequest) -> None:
    del timer
    _hosts().outbox.run()


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="%INTAKE_NOTIFICATION_QUEUE%",
    connection="INTAKE_SERVICEBUS_NAMESPACE",
)
def notification_worker(message: func.ServiceBusMessage) -> None:
    _invoke_auto_settled(_hosts().notification, message)


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="%INTAKE_INTEGRATION_QUEUE%",
    connection="INTAKE_SERVICEBUS_NAMESPACE",
)
def integration_worker(message: func.ServiceBusMessage) -> None:
    _invoke_auto_settled(_hosts().integration, message)


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="%INTAKE_COMPLETION_QUEUE%",
    connection="INTAKE_SERVICEBUS_NAMESPACE",
)
def completion_worker(message: func.ServiceBusMessage) -> None:
    _invoke_auto_settled(_hosts().completion, message)


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="%INTAKE_RETENTION_QUEUE%",
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
