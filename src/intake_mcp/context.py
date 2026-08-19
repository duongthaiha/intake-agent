"""Derive trusted operation context from verified bearer claims and MCP metadata."""
from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import Context

from intake_agent.config import IntakeConfigurationError, IntakeSettings
from intake_agent.requester_tools import OperationContext

CONVERSATION_META_KEY = "intake.conversation_id"
CORRELATION_META_KEY = "intake.correlation_id"
IDEMPOTENCY_META_KEY = "intake.idempotency_key"
ACTIVITY_META_KEY = "intake.activity_id"


def operation_context(
    context: Context[Any, Any, Any],
    settings: IntakeSettings,
    *,
    mutation: bool,
) -> OperationContext:
    access_token = get_access_token()
    claims = access_token.claims if access_token is not None else None
    if not isinstance(claims, dict):
        raise IntakeConfigurationError("Verified bearer claims are unavailable")

    tenant_id = claims.get("tid")
    actor_id = claims.get("oid")
    scopes_value = claims.get("scp")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise IntakeConfigurationError("Verified tenant claim is unavailable")
    if not isinstance(actor_id, str) or not actor_id:
        raise IntakeConfigurationError("Verified actor claim is unavailable")
    if not isinstance(scopes_value, str) or not scopes_value:
        raise IntakeConfigurationError("Verified bearer claims are incomplete")

    meta = context.request_context.meta
    values = dict(meta.model_extra or {}) if meta is not None else {}
    local = settings.environment.strip().lower() == "local"
    conversation_id = _trusted_value(values, CONVERSATION_META_KEY)
    correlation_id = _trusted_value(values, CORRELATION_META_KEY)
    activity_id = _trusted_value(values, ACTIVITY_META_KEY)
    idempotency_key = _trusted_value(values, IDEMPOTENCY_META_KEY)

    if local:
        conversation_id = conversation_id or "local-conversation"
        correlation_id = correlation_id or str(context.request_id)
        activity_id = activity_id or str(context.request_id)
        if mutation:
            idempotency_key = idempotency_key or f"local-{context.request_id}"
    elif not conversation_id or not correlation_id or not activity_id:
        raise IntakeConfigurationError(
            "Trusted conversation, correlation, and activity metadata are required"
        )
    if mutation and not idempotency_key:
        raise IntakeConfigurationError("Trusted idempotency metadata is required")

    return OperationContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        scopes=frozenset(scopes_value.split()),
        conversation_id=conversation_id,
        activity_id=activity_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        agent_identity=settings.hosted_agent_identity,
    )


def _trusted_value(values: dict[str, Any], key: str) -> str | None:
    value = values.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None
