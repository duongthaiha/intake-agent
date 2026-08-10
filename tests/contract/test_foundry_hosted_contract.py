from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from intake_agent.config import IntakeConfigurationError, IntakeSettings
from intake_agent.hosted import (
    AGENT_INSTRUCTIONS,
    build_hosted_runtime,
    build_responses_server,
    create_intake_tools,
    resolve_foundry_configuration,
)

pytestmark = pytest.mark.contract


def _local_settings() -> IntakeSettings:
    return IntakeSettings(
        environment="local",
        persistence_backend="inmemory",
        hosted_tenant_id="local-tenant",
    )


def test_responses_configuration_rejects_missing_model_or_project() -> None:
    with pytest.raises(IntakeConfigurationError) as exc_info:
        resolve_foundry_configuration({})

    message = str(exc_info.value)
    assert "FOUNDRY_PROJECT_ENDPOINT" in message
    assert "AZURE_AI_MODEL_DEPLOYMENT_NAME" in message


def test_agent_contract_keeps_identity_and_review_outside_model_control() -> None:
    assert "Never invent field values" in AGENT_INSTRUCTIONS
    assert "identities, roles, approvals" in AGENT_INSTRUCTIONS
    assert "Reviewer decisions are outside" in AGENT_INSTRUCTIONS


def test_tool_boundary_exposes_only_deterministic_requester_operations() -> None:
    tools = create_intake_tools(build_hosted_runtime(_local_settings()))

    assert [item.name for item in tools] == [
        "get_intake_context",
        "update_intake_field",
        "submit_intake_for_review",
        "list_my_intake_requests",
    ]
    assert all(item.approval_mode == "never_require" for item in tools)
    assert all("review_decision" not in item.name for item in tools)


def test_responses_server_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/p",
    )
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    server = build_responses_server(_local_settings())
    client = TestClient(server)

    assert client.get("/health").status_code == 200
    assert client.get("/readiness").status_code == 200
    assert any(getattr(route, "path", "") == "/responses" for route in server.routes)


@pytest.mark.asyncio
async def test_partial_update_uses_domain_rules_and_returns_blocking_gaps() -> None:
    runtime = build_hosted_runtime(_local_settings())
    token = runtime.bind_actor(
        user_isolation_key="contract-user",
        chat_isolation_key="contract-chat",
        response_id="contract-response",
        conversation_id="contract-conversation",
    )
    try:
        result = await runtime.update_field(
            expected_revision=1,
            field_path="project.name",
            value="Finance Reporting Upgrade",
            source_reference="contract-test",
            model_confidence=0.99,
        )
    finally:
        runtime.reset_actor(token)

    assert result["status"] == "accepted"
    assert result["revision"] == 2
    assert result["accepted_fields"] == ["project.name"]
    assert result["rejected_fields"] == []
    assert {
        (gap["field_path"], gap["category"], gap["severity"])
        for gap in result["new_gaps"]
    } == {
        ("project.description", "missing", "blocking"),
        ("requester.business_unit", "missing", "blocking"),
        ("priority", "missing", "blocking"),
    }


def test_deployed_runtime_rejects_missing_platform_isolation_keys() -> None:
    from types import SimpleNamespace

    from intake_agent.hosted import HostedRuntime

    runtime = HostedRuntime(
        SimpleNamespace(),  # type: ignore[arg-type]
        IntakeSettings(
            environment="dev",
            persistence_backend="cosmos",
            cosmos_endpoint="https://cosmos.example/",
            blob_backend="azure",
            blob_endpoint="https://storage.example/",
            servicebus_backend="azure",
            servicebus_namespace="bus.example.servicebus.windows.net",
            hosted_tenant_id="tenant-1",
            azure_client_id="00000000-0000-0000-0000-000000000001",
        ),
    )

    with pytest.raises(IntakeConfigurationError, match="isolation keys are required"):
        runtime.bind_actor(
            user_isolation_key=None,
            chat_isolation_key=None,
            response_id="response-1",
            conversation_id="conversation-1",
        )


def test_hosted_runtime_fails_closed_on_unsafe_deployed_configuration() -> None:
    settings = IntakeSettings(
        environment="dev",
        persistence_backend="inmemory",
        hosted_tenant_id="",
    )

    with pytest.raises(IntakeConfigurationError) as exc_info:
        build_hosted_runtime(settings)

    message = str(exc_info.value)
    assert "INTAKE_HOSTED_TENANT_ID" in message
    assert "INTAKE_PERSISTENCE_BACKEND=inmemory is restricted to local" in message
