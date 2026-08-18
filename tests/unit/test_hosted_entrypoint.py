"""Targeted tests for the Microsoft Foundry Responses entry point."""
from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from intake_agent.config import (
    IntakeConfigurationError,
    IntakeSettings,
    get_settings,
    validate_hosted_settings,
)
from intake_agent.hosted import (
    AGENT_INSTRUCTIONS,
    HostedRuntime,
    _resolve_platform_isolation,
    build_hosted_runtime,
    build_responses_server,
    create_intake_tools,
    get_hosted_runtime,
    resolve_foundry_configuration,
)


@pytest.fixture(autouse=True)
def _reset_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTAKE_ENVIRONMENT", "local")
    monkeypatch.setenv("INTAKE_PERSISTENCE_BACKEND", "inmemory")
    monkeypatch.delenv("INTAKE_HOSTED_TENANT_ID", raising=False)
    get_settings.cache_clear()
    get_hosted_runtime.cache_clear()
    yield
    get_settings.cache_clear()
    get_hosted_runtime.cache_clear()


def _local_settings() -> IntakeSettings:
    return IntakeSettings(environment="local", persistence_backend="inmemory")


@pytest.mark.asyncio
async def test_runtime_reuses_domain_pipeline_with_platform_isolation() -> None:
    runtime = build_hosted_runtime(_local_settings())
    token = runtime.bind_actor(
        user_isolation_key="user-1",
        chat_isolation_key="chat-1",
        response_id="resp-1",
        conversation_id="conv-1",
    )
    try:
        initial = await runtime.get_context()
        updated = await runtime.update_field(
            expected_revision=initial["current_revision"],
            field_path="project.name",
            value="Hosted Intake",
            source_reference="user turn 1",
            model_confidence=0.95,
        )
        resumed = await runtime.get_context()
    finally:
        runtime.reset_actor(token)

    assert updated["accepted_fields"] == ["project.name"]
    assert resumed["fields"]["project.name"]["value"] == "Hosted Intake"


@pytest.mark.asyncio
async def test_chat_isolation_separates_requests() -> None:
    runtime = build_hosted_runtime(_local_settings())

    first_token = runtime.bind_actor(
        user_isolation_key="same-user",
        chat_isolation_key="chat-a",
        response_id="resp-a",
        conversation_id=None,
    )
    try:
        first = await runtime.get_context()
    finally:
        runtime.reset_actor(first_token)

    second_token = runtime.bind_actor(
        user_isolation_key="same-user",
        chat_isolation_key="chat-b",
        response_id="resp-b",
        conversation_id=None,
    )
    try:
        second = await runtime.get_context()
    finally:
        runtime.reset_actor(second_token)

    assert first["request_id"] != second["request_id"]


def test_deployed_runtime_requires_platform_isolation_keys() -> None:
    settings = IntakeSettings(
        environment="dev",
        persistence_backend="cosmos",
        blob_backend="azure",
        servicebus_backend="azure",
        cosmos_endpoint="https://cosmos.example",
        blob_endpoint="https://storage.example",
        servicebus_namespace="sb.example",
        hosted_tenant_id="tenant-1",
        azure_client_id="00000000-0000-0000-0000-000000000001",
    )
    runtime = HostedRuntime(SimpleNamespace(), settings)  # type: ignore[arg-type]

    with pytest.raises(IntakeConfigurationError, match="isolation keys"):
        runtime.bind_actor(
            user_isolation_key=None,
            chat_isolation_key=None,
            response_id="resp-1",
            conversation_id=None,
        )


def test_platform_isolation_supports_current_hosted_context() -> None:
    context = SimpleNamespace(
        platform_context=SimpleNamespace(
            user_id_key="hosted-user",
            call_id="hosted-call",
        ),
        conversation_id="hosted-conversation",
    )

    assert _resolve_platform_isolation(context) == (
        "hosted-user",
        "hosted-conversation",
    )


def test_platform_isolation_supports_legacy_hosted_context() -> None:
    context = SimpleNamespace(
        isolation=SimpleNamespace(user_key="legacy-user", chat_key="legacy-chat"),
    )

    assert _resolve_platform_isolation(context) == ("legacy-user", "legacy-chat")


def test_foundry_model_configuration_is_required() -> None:
    with pytest.raises(IntakeConfigurationError) as exc_info:
        resolve_foundry_configuration({})

    message = str(exc_info.value)
    assert "FOUNDRY_PROJECT_ENDPOINT" in message
    assert "AZURE_AI_MODEL_DEPLOYMENT_NAME" in message


def test_foundry_model_configuration_resolves() -> None:
    assert resolve_foundry_configuration(
        {
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/p",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
        }
    ) == (
        "https://example.services.ai.azure.com/api/projects/p",
        "gpt-4.1-mini",
    )


def test_responses_server_exposes_health_and_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/p",
    )
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    server = build_responses_server(_local_settings())
    client = TestClient(server)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/readiness").status_code == 200
    assert any(getattr(route, "path", "") == "/responses" for route in server.routes)


def test_deployed_configuration_fails_closed_without_tenant_or_durable_state() -> None:
    settings = IntakeSettings(
        environment="prod",
        persistence_backend="inmemory",
        hosted_tenant_id="",
    )

    with pytest.raises(IntakeConfigurationError) as exc_info:
        validate_hosted_settings(settings)

    message = str(exc_info.value)
    assert "INTAKE_HOSTED_TENANT_ID" in message
    assert "INTAKE_PERSISTENCE_BACKEND=inmemory" in message


def test_all_hosted_environments_reject_ephemeral_state() -> None:
    settings = IntakeSettings(
        environment="dev",
        persistence_backend="inmemory",
        hosted_tenant_id="tenant-1",
    )

    with pytest.raises(IntakeConfigurationError, match="restricted to local"):
        validate_hosted_settings(settings)


def test_agent_instructions_preserve_deterministic_boundary() -> None:
    assert "persisted state returned by get_intake_context as authoritative" in (
        AGENT_INSTRUCTIONS
    )
    assert "Never invent or silently correct field values" in AGENT_INSTRUCTIONS
    assert "reload the context before summarizing" in AGENT_INSTRUCTIONS
    assert "latest context reports can_submit=true" in AGENT_INSTRUCTIONS
    assert "Never reveal, repeat, store" in AGENT_INSTRUCTIONS
    assert "Reviewer decisions are outside" in AGENT_INSTRUCTIONS


@pytest.mark.asyncio
async def test_local_dev_tools_bind_fixed_development_identity() -> None:
    runtime = build_hosted_runtime(_local_settings())
    tools = {
        item.name: item
        for item in create_intake_tools(
            runtime,
            local_dev_identity=("devui-user", "devui-chat"),
        )
    }

    context = await tools["get_intake_context"].func()

    assert context["current_revision"] == 1
    assert context["status"] == "new"


def test_direct_code_packaging_contract() -> None:
    repository_root = Path(__file__).parents[2]

    assert (repository_root / "hosted_main.py").is_file()
    assert (repository_root / "requirements.txt").read_text().strip().endswith(".")
    pyproject = tomllib.loads((repository_root / "pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]
    devui_dependencies = pyproject["project"]["optional-dependencies"]["devui"]
    assert any("agent-framework-foundry-hosting" in item for item in dependencies)
    assert not any("agent-framework-devui" in item for item in dependencies)
    assert any("agent-framework-devui" in item for item in devui_dependencies)
    ignore = (repository_root / ".agentignore").read_text()
    assert ".env" in ignore
    assert "infra/" in ignore
    assert "tests/" in ignore
    assert "src/" not in ignore
