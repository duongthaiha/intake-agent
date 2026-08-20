"""Conservative telemetry helpers for the production MCP boundary."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SAFE_EVENTS = frozenset(
    {
        "auth.rejected",
        "server.not_ready",
        "server.ready",
        "tool.complete",
        "tool.completed",
        "tool.started",
    }
)
_SAFE_FIELDS = frozenset(
    {
        "actor_id",
        "correlation_id",
        "duration_ms",
        "error_code",
        "outcome",
        "request_id",
        "revision",
        "role",
        "status_code",
        "tenant_id",
        "tool_name",
    }
)


def redacted_telemetry(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Retain a small metadata allowlist and redact every content-like value."""

    result: dict[str, Any] = {}
    for key, value in attributes.items():
        normalized = key.lower()
        if normalized in _SAFE_FIELDS and _safe_scalar(value):
            result[key] = value
        else:
            result[key] = REDACTED
    return result


def log_telemetry(
    logger: logging.Logger,
    event_name: str,
    attributes: Mapping[str, Any],
    *,
    level: int = logging.INFO,
) -> None:
    """Emit structured metadata without bearer tokens or request field content."""

    safe_event_name = event_name if event_name in _SAFE_EVENTS else "event.redacted"
    logger.log(level, "%s %s", safe_event_name, redacted_telemetry(attributes))


def _safe_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, (bool, int, float))
        or (
            isinstance(value, str)
            and "\r" not in value
            and "\n" not in value
            and not value.lower().startswith("bearer ")
            and value.count(".") != 2
        )
    )
