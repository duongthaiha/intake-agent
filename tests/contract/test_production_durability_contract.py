"""Production composition contracts for durable Hosted Agent state."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from intake_agent.config import (
    IntakeConfigurationError,
    IntakeSettings,
    build_repositories,
    validate_hosted_settings,
)

pytestmark = pytest.mark.contract


def _production_settings(**overrides: object) -> IntakeSettings:
    values: dict[str, object] = {
        "environment": "production",
        "hosted_tenant_id": "tenant-1",
        "persistence_backend": "cosmos",
        "cosmos_endpoint": "https://cosmos.example/",
        "cosmos_database": "intake",
        "blob_backend": "azure",
        "blob_endpoint": "https://storage.example/",
        "servicebus_backend": "azure",
        "servicebus_namespace": "bus.example.servicebus.windows.net",
        "azure_client_id": "00000000-0000-0000-0000-000000000001",
    }
    values.update(overrides)
    return IntakeSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("setting", "unsafe_value", "expected_message"),
    [
        (
            "persistence_backend",
            "inmemory",
            "INTAKE_PERSISTENCE_BACKEND=inmemory",
        ),
        ("blob_backend", "inmemory", "INTAKE_BLOB_BACKEND=inmemory"),
        (
            "servicebus_backend",
            "inmemory",
            "INTAKE_SERVICEBUS_BACKEND=inmemory",
        ),
    ],
)
def test_production_rejects_every_ephemeral_backend(
    setting: str,
    unsafe_value: str,
    expected_message: str,
) -> None:
    settings = _production_settings(**{setting: unsafe_value})

    with pytest.raises(IntakeConfigurationError, match=expected_message):
        validate_hosted_settings(settings)


def test_production_defaults_do_not_silently_select_memory() -> None:
    settings = IntakeSettings(
        environment="production",
        hosted_tenant_id="tenant-1",
    )

    with pytest.raises(IntakeConfigurationError) as exc_info:
        build_repositories(settings)

    message = str(exc_info.value)
    assert "INTAKE_PERSISTENCE_BACKEND=inmemory" in message
    assert "INTAKE_BLOB_BACKEND=inmemory" in message
    assert "INTAKE_SERVICEBUS_BACKEND=inmemory" in message


def test_production_composition_contains_only_durable_adapters(
) -> None:
    repositories = build_repositories(_production_settings())

    assert type(repositories["request_repo"]).__name__ == "CosmosRequestRepository"
    assert type(repositories["template_repo"]).__name__ == "CosmosTemplateRepository"
    assert type(repositories["outbox_repo"]).__name__ == "CosmosOutboxRepository"
    assert type(repositories["idempotency_store"]).__name__ == "CosmosIdempotencyStore"
    assert type(repositories["artifact_store"]).__name__ == "BlobArtifactStore"
    assert all(
        not type(repository).__name__.startswith("InMemory")
        for repository in repositories.values()
    )


@pytest.fixture()
def protected_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    names = [
        "INTAKE_PERSISTENCE_BACKEND",
        "INTAKE_BLOB_BACKEND",
        "INTAKE_SERVICEBUS_BACKEND",
        "INTAKE_COSMOS_ENDPOINT",
        "INTAKE_BLOB_ENDPOINT",
        "INTAKE_SERVICEBUS_NAMESPACE",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    yield


def test_production_environment_without_durable_settings_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    protected_environment: None,
) -> None:
    monkeypatch.setenv("INTAKE_ENVIRONMENT", "production")
    monkeypatch.setenv("INTAKE_HOSTED_TENANT_ID", "tenant-1")

    with pytest.raises(IntakeConfigurationError):
        build_repositories(IntakeSettings())


def test_deployment_manifest_cannot_publish_ephemeral_hosted_state() -> None:
    manifest = (Path(__file__).parents[2] / "azure.yaml").read_text(encoding="utf-8")
    hosted_service = manifest.split("    intake-agent:", 1)[1].split("    workers:", 1)[0]

    assert "INTAKE_ALLOW_EPHEMERAL_HOSTED_STATE" not in hosted_service
    assert "INTAKE_PERSISTENCE_BACKEND: cosmos" in hosted_service
    assert "INTAKE_BLOB_BACKEND: azure" in hosted_service
    assert "INTAKE_SERVICEBUS_BACKEND: azure" in hosted_service
    assert any(
        selector in hosted_service
        for selector in (
            "AZURE_CLIENT_ID: ${AGENT_IDENTITY_CLIENT_ID}",
            "AZURE_CLIENT_ID: ${AGENT_RUNTIME_PRINCIPAL_ID}",
        )
    )
    assert "inmemory" not in hosted_service.lower()


def test_worker_deployment_supplies_durable_outbox_dispatch_configuration() -> None:
    manifest = (Path(__file__).parents[2] / "azure.yaml").read_text(encoding="utf-8")
    workers = manifest.split("    workers:", 1)[1].split("infra:", 1)[0]
    functions_bicep = (
        Path(__file__).parents[2] / "infra" / "modules" / "functions.bicep"
    ).read_text(encoding="utf-8")
    effective_configuration = f"{workers}\n{functions_bicep}"

    for setting in (
        "AZURE_CLIENT_ID",
        "INTAKE_COSMOS_ENDPOINT",
        "INTAKE_COSMOS_DATABASE",
        "INTAKE_COSMOS_REQUESTS_CONTAINER",
        "INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace",
        "INTAKE_SERVICEBUS_QUEUE",
    ):
        assert setting in effective_configuration


def test_cosmos_iac_exposes_partition_compatible_product_containers() -> None:
    cosmos = (
        Path(__file__).parents[2] / "infra" / "modules" / "cosmos.bicep"
    ).read_text(encoding="utf-8")

    request_state = cosmos.split("resource requestStateContainer", 1)[1].split(
        "resource templatesContainer",
        1,
    )[0]
    templates = cosmos.split("resource templatesContainer", 1)[1].split(
        "resource idempotencyContainer",
        1,
    )[0]
    idempotency = cosmos.split("resource idempotencyContainer", 1)[1].split(
        "resource revisionsContainer",
        1,
    )[0]

    assert "paths: ['/requestId']" in request_state
    assert "paths: ['/templateId']" in templates
    assert "paths: ['/scopeId']" in idempotency
    assert "output requestsContainerName string = requestStateContainer.name" in cosmos
    assert "output templatesContainerName string = templatesContainer.name" in cosmos
    assert "output idempotencyContainerName string = idempotencyContainer.name" in cosmos
