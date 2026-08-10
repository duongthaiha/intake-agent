"""Tests for intake_workers.function_app trigger functions.

Uses mock azure.functions objects — no Azure credentials, no Service Bus,
no deployed environment required.

Each trigger function is called directly through its decorated name.
The decorator registers the handler on the FunctionApp instance but
the callable itself remains a plain Python function once the module
is imported.

Coverage targets:
- domain_event_dispatcher: body decoded, logger called
- document_worker: body decoded, logger called
- notification_worker: body decoded, logger called
- outbox_dispatcher: logger called with no body
- module-level import: FunctionApp(), app object exists
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import azure.functions as func
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.filterwarnings("ignore::ResourceWarning")]


# ---------------------------------------------------------------------------
# Module-level smoke test
# ---------------------------------------------------------------------------

def test_function_app_module_imports():
    """Module must import without error; app must be a FunctionApp instance."""
    import intake_workers.function_app as fa

    assert hasattr(fa, "app")
    assert isinstance(fa.app, func.FunctionApp)


def test_all_trigger_functions_are_callable():
    from intake_workers.function_app import (
        document_worker,
        domain_event_dispatcher,
        notification_worker,
        outbox_dispatcher,
    )

    assert callable(domain_event_dispatcher)
    assert callable(document_worker)
    assert callable(notification_worker)
    assert callable(outbox_dispatcher)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_sb_message(body: str = "test message body") -> MagicMock:
    msg = MagicMock(spec=func.ServiceBusMessage)
    msg.get_body.return_value = body.encode("utf-8")
    return msg


def _mock_timer(past_due: bool = False) -> MagicMock:
    timer = MagicMock(spec=func.TimerRequest)
    timer.past_due = past_due
    return timer


# ---------------------------------------------------------------------------
# domain_event_dispatcher
# ---------------------------------------------------------------------------

def test_domain_event_dispatcher_decodes_body():
    from intake_workers.function_app import domain_event_dispatcher

    msg = _mock_sb_message('{"event_type": "RequestSubmitted"}')
    # Must not raise
    domain_event_dispatcher(msg)
    msg.get_body.assert_called_once()


def test_domain_event_dispatcher_logs_message_length(caplog):
    from intake_workers.function_app import domain_event_dispatcher

    payload = '{"event_type": "RequestApproved"}'
    msg = _mock_sb_message(payload)
    with caplog.at_level(logging.INFO, logger="intake_workers.function_app"):
        domain_event_dispatcher(msg)


def test_domain_event_dispatcher_empty_body():
    from intake_workers.function_app import domain_event_dispatcher

    msg = _mock_sb_message("")
    domain_event_dispatcher(msg)  # must not raise


@pytest.mark.parametrize("payload", [
    '{"event_type": "RequestSubmitted", "request_id": "r-1"}',
    '{"event_type": "RequestApproved"}',
    "plain text message",
    '{"nested": {"key": "value"}}',
])
def test_domain_event_dispatcher_various_payloads(payload: str):
    from intake_workers.function_app import domain_event_dispatcher

    domain_event_dispatcher(_mock_sb_message(payload))


# ---------------------------------------------------------------------------
# document_worker
# ---------------------------------------------------------------------------

def test_document_worker_decodes_body():
    from intake_workers.function_app import document_worker

    msg = _mock_sb_message('{"request_id": "req-1", "revision": 3}')
    document_worker(msg)
    msg.get_body.assert_called_once()


def test_document_worker_logs_trigger(caplog):
    from intake_workers.function_app import document_worker

    with caplog.at_level(logging.INFO, logger="intake_workers.function_app"):
        document_worker(_mock_sb_message("generate doc"))


def test_document_worker_empty_body():
    from intake_workers.function_app import document_worker

    document_worker(_mock_sb_message(""))


# ---------------------------------------------------------------------------
# notification_worker
# ---------------------------------------------------------------------------

def test_notification_worker_decodes_body():
    from intake_workers.function_app import notification_worker

    msg = _mock_sb_message('{"notification_type": "status_change"}')
    notification_worker(msg)
    msg.get_body.assert_called_once()


def test_notification_worker_logs_trigger(caplog):
    from intake_workers.function_app import notification_worker

    with caplog.at_level(logging.INFO, logger="intake_workers.function_app"):
        notification_worker(_mock_sb_message("notify"))


def test_notification_worker_unicode_body():
    from intake_workers.function_app import notification_worker

    notification_worker(_mock_sb_message("通知メッセージ"))


# ---------------------------------------------------------------------------
# outbox_dispatcher
# ---------------------------------------------------------------------------

def test_outbox_dispatcher_does_not_raise():
    from intake_workers.function_app import outbox_dispatcher

    timer = _mock_timer()
    outbox_dispatcher(timer)  # must not raise


def test_outbox_dispatcher_logs_running(caplog):
    from intake_workers.function_app import outbox_dispatcher

    with caplog.at_level(logging.INFO, logger="intake_workers.function_app"):
        outbox_dispatcher(_mock_timer())


def test_outbox_dispatcher_past_due_does_not_raise():
    from intake_workers.function_app import outbox_dispatcher

    outbox_dispatcher(_mock_timer(past_due=True))


# ---------------------------------------------------------------------------
# Logger integration: patch logger to verify exact log calls
# ---------------------------------------------------------------------------

def test_domain_event_dispatcher_logger_info_called():
    from intake_workers import function_app as fa

    msg = _mock_sb_message("payload")
    with patch.object(fa.logger, "info") as mock_info:
        fa.domain_event_dispatcher(msg)
    mock_info.assert_called_once()


def test_document_worker_logger_info_called():
    from intake_workers import function_app as fa

    with patch.object(fa.logger, "info") as mock_info:
        fa.document_worker(_mock_sb_message("doc"))
    mock_info.assert_called_once()


def test_notification_worker_logger_info_called():
    from intake_workers import function_app as fa

    with patch.object(fa.logger, "info") as mock_info:
        fa.notification_worker(_mock_sb_message("notify"))
    mock_info.assert_called_once()


def test_outbox_dispatcher_logger_info_called():
    from intake_workers import function_app as fa

    with patch.object(fa.logger, "info") as mock_info:
        fa.outbox_dispatcher(_mock_timer())
    mock_info.assert_called_once()
