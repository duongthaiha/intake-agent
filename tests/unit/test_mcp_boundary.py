"""Unit coverage for the private requester MCP trust boundary."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from intake_agent.config import (
    IntakeConfigurationError,
    IntakeSettings,
    validate_mcp_settings,
    validate_toolbox_settings,
)
from intake_agent.hosted import (
    _qualified_requester_tool_names,
    create_intake_agent,
    resolve_toolbox_endpoint,
)
from intake_agent.requester_tools import OperationContext
from intake_mcp.auth import EntraTokenVerifier
from intake_mcp.context import operation_context
from intake_mcp.server import build_mcp_app

pytestmark = pytest.mark.unit


def _deployed_settings(**overrides: object) -> IntakeSettings:
    values: dict[str, object] = {
        "environment": "dev",
        "persistence_backend": "cosmos",
        "blob_backend": "azure",
        "servicebus_backend": "azure",
        "cosmos_endpoint": "https://cosmos.example",
        "blob_endpoint": "https://storage.example",
        "servicebus_namespace": "bus.example.servicebus.windows.net",
        "hosted_tenant_id": "tenant-1",
        "azure_client_id": "00000000-0000-0000-0000-000000000001",
        "mcp_tenant_id": "tenant-1",
        "mcp_audience": "00000000-0000-0000-0000-000000000002",
        "mcp_required_scope": "Intake.Tools.ReadWrite",
        "mcp_issuer": "https://login.microsoftonline.com/tenant-1/v2.0",
        "mcp_resource_url": "https://mcp.internal.example/mcp",
        "mcp_toolbox_name": "intake-mcp-v1-dev",
    }
    values.update(overrides)
    return IntakeSettings(**values)


def test_operation_context_derives_tenant_namespaced_opaque_user() -> None:
    first = OperationContext(
        tenant_id="tenant-a",
        actor_id="same-object-id",
        scopes=frozenset(["Intake.Tools.ReadWrite"]),
        conversation_id="conversation",
        activity_id="activity",
        correlation_id="correlation",
    ).actor()
    second = OperationContext(
        tenant_id="tenant-b",
        actor_id="same-object-id",
        scopes=frozenset(["Intake.Tools.ReadWrite"]),
        conversation_id="conversation",
        activity_id="activity",
        correlation_id="correlation",
    ).actor()

    assert first.user_id.startswith("entra-user-")
    assert first.user_id != second.user_id
    assert "same-object-id" not in first.user_id


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"mcp_tenant_id": ""}, "INTAKE_MCP_TENANT_ID"),
        ({"mcp_audience": ""}, "INTAKE_MCP_AUDIENCE"),
        ({"mcp_required_scope": ""}, "INTAKE_MCP_REQUIRED_SCOPE"),
        (
            {"mcp_issuer": "https://login.microsoftonline.com/other/v2.0"},
            "INTAKE_MCP_ISSUER",
        ),
        ({"mcp_resource_url": "http://mcp.example/mcp"}, "INTAKE_MCP_RESOURCE_URL"),
    ],
)
def test_deployed_mcp_configuration_fails_closed(
    overrides: dict[str, object],
    expected: str,
) -> None:
    with pytest.raises(IntakeConfigurationError, match=expected):
        validate_mcp_settings(_deployed_settings(**overrides))


def test_deployed_toolbox_configuration_requires_https_or_name() -> None:
    with pytest.raises(IntakeConfigurationError, match="must use HTTPS"):
        validate_toolbox_settings(
            _deployed_settings(
                mcp_toolbox_name="",
                toolbox_endpoint="http://toolbox.example/mcp",
            )
        )
    with pytest.raises(IntakeConfigurationError, match="TOOLBOX"):
        validate_toolbox_settings(
            _deployed_settings(mcp_toolbox_name="", toolbox_endpoint="")
        )
    with pytest.raises(IntakeConfigurationError, match="SERVER_LABEL"):
        validate_toolbox_settings(_deployed_settings(mcp_toolbox_server_label=""))


def test_toolbox_allowlist_uses_foundry_namespaced_tool_names() -> None:
    assert _qualified_requester_tool_names("intake_requester_tools") == {
        "intake_requester_tools.get_intake_context",
        "intake_requester_tools.update_intake_field",
        "intake_requester_tools.submit_intake_for_review",
        "intake_requester_tools.list_my_intake_requests",
    }


def test_toolbox_endpoint_resolves_versioned_consumer_url() -> None:
    endpoint = resolve_toolbox_endpoint(
        _deployed_settings(),
        "https://account.services.ai.azure.com/api/projects/project",
    )
    assert endpoint == (
        "https://account.services.ai.azure.com/api/projects/project/"
        "toolboxes/intake-mcp-v1-dev/mcp?api-version=v1"
    )


def test_deployed_agent_cannot_use_in_process_requester_tools() -> None:
    runtime = SimpleNamespace(_settings=_deployed_settings())
    with pytest.raises(IntakeConfigurationError, match="restricted to local"):
        create_intake_agent(SimpleNamespace(), runtime)  # type: ignore[arg-type]


def test_token_claim_policy_rejects_wrong_tenant_scope_and_expiry() -> None:
    verifier = EntraTokenVerifier(_deployed_settings())
    valid = {
        "tid": "tenant-1",
        "oid": "object-1",
        "scp": "openid Intake.Tools.ReadWrite",
        "exp": int(time.time()) + 300,
        "azp": "foundry-client",
    }

    assert verifier._access_token("token", valid) is not None
    assert verifier._access_token("token", {**valid, "tid": "other"}) is None
    assert verifier._access_token("token", {**valid, "scp": "openid"}) is None
    assert verifier._access_token("token", {**valid, "exp": int(time.time()) - 1}) is None
    assert verifier._access_token("token", {**valid, "oid": ""}) is None


def test_operation_context_requires_verified_claims_and_mutation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_token = SimpleNamespace(
        claims={
            "tid": "tenant-1",
            "oid": "object-1",
            "scp": "Intake.Tools.ReadWrite",
        }
    )
    monkeypatch.setattr("intake_mcp.context.get_access_token", lambda: access_token)
    context = SimpleNamespace(
        request_id="request-1",
        request_context=SimpleNamespace(
            meta=SimpleNamespace(
                model_extra={
                    "intake.conversation_id": "conversation-1",
                    "intake.correlation_id": "correlation-1",
                    "intake.activity_id": "activity-1",
                }
            )
        ),
    )

    with pytest.raises(IntakeConfigurationError, match="idempotency"):
        operation_context(context, _deployed_settings(), mutation=True)

    context.request_context.meta.model_extra["intake.idempotency_key"] = "operation-1"
    trusted = operation_context(context, _deployed_settings(), mutation=True)
    assert trusted.tenant_id == "tenant-1"
    assert trusted.actor_id == "object-1"
    assert trusted.idempotency_key == "operation-1"


def test_operation_context_rejects_missing_verified_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("intake_mcp.context.get_access_token", lambda: None)
    context = SimpleNamespace(
        request_id="request-1",
        request_context=SimpleNamespace(meta=None),
    )

    with pytest.raises(IntakeConfigurationError, match="claims"):
        operation_context(context, _deployed_settings(), mutation=False)


def test_mcp_health_and_readiness_are_available_without_authentication() -> None:
    settings = IntakeSettings(environment="local", persistence_backend="inmemory")

    with TestClient(build_mcp_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/readiness").json() == {"status": "ready"}
