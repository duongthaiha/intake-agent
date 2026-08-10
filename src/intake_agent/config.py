"""Runtime configuration for the intake agent.

Reads from environment variables. In-memory adapters are restricted to local
development; every hosted environment fails closed unless durable Azure
backends are explicitly configured. No secrets are accepted.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntakeConfigurationError(RuntimeError):
    """Raised when runtime configuration is unsafe or incomplete."""


class IntakeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTAKE_",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Persistence backend selection
    persistence_backend: Literal["inmemory", "cosmos"] = "inmemory"
    servicebus_backend: Literal["inmemory", "azure"] = "inmemory"
    blob_backend: Literal["inmemory", "azure"] = "inmemory"

    # Azure endpoints (required when backend != inmemory)
    cosmos_endpoint: str = ""
    cosmos_database: str = "intake"
    cosmos_requests_container: str = "requests"
    cosmos_templates_container: str = "templates"
    cosmos_idempotency_container: str = "idempotency"
    servicebus_namespace: str = ""
    servicebus_queue: str = "domain-events"
    blob_endpoint: str = ""
    blob_container_artifacts: str = "request-artifacts"
    appinsights_connection: str = ""

    # Agent runtime
    template_id: str = "general-intake-v1"
    environment: str = "local"
    hosted_tenant_id: str = ""
    hosted_agent_identity: str = "intake-agent"

    # Local-dev role configuration.
    # SECURITY: These settings are ONLY consulted when environment == "local".
    # In any deployed environment (dev/test/prod), review decisions must be
    # authorised via verified Entra claims constructed by the channel adapter
    # (FoundryAdapter / BotServiceAdapter). The LocalAdapter MUST NOT be used
    # outside local developer workstations.
    #
    # Comma-separated list of user IDs that receive the "reviewer" role in
    # local-dev mode.  Any user_id not in this list receives "requester".
    local_dev_reviewer_ids: str = "reviewer-1,local-reviewer"

    # Managed identity (set by Azure hosting)
    azure_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_CLIENT_ID", "INTAKE_AZURE_CLIENT_ID"),
    )


@lru_cache(maxsize=1)
def get_settings() -> IntakeSettings:
    return IntakeSettings()


def validate_hosted_settings(settings: IntakeSettings) -> None:
    """Validate the security-sensitive Hosted Agent configuration."""
    errors: list[str] = []
    environment = settings.environment.strip().lower()
    deployed = environment != "local"

    if deployed and not settings.hosted_tenant_id.strip():
        errors.append("INTAKE_HOSTED_TENANT_ID is required outside local development")
    if deployed and not settings.azure_client_id.strip():
        errors.append("AZURE_CLIENT_ID is required for the user-assigned managed identity")

    if deployed and settings.persistence_backend == "inmemory":
        errors.append(
            "INTAKE_PERSISTENCE_BACKEND=inmemory is restricted to local development"
        )
    if deployed and settings.blob_backend == "inmemory":
        errors.append("INTAKE_BLOB_BACKEND=inmemory is restricted to local development")
    if deployed and settings.servicebus_backend == "inmemory":
        errors.append(
            "INTAKE_SERVICEBUS_BACKEND=inmemory is restricted to local development"
        )

    if settings.persistence_backend == "cosmos":
        if not settings.cosmos_endpoint.strip():
            errors.append(
                "INTAKE_COSMOS_ENDPOINT is required when "
                "INTAKE_PERSISTENCE_BACKEND=cosmos"
            )
        if not settings.cosmos_database.strip():
            errors.append(
                "INTAKE_COSMOS_DATABASE is required when "
                "INTAKE_PERSISTENCE_BACKEND=cosmos"
            )
        for field_name, value in (
            ("INTAKE_COSMOS_REQUESTS_CONTAINER", settings.cosmos_requests_container),
            ("INTAKE_COSMOS_TEMPLATES_CONTAINER", settings.cosmos_templates_container),
            ("INTAKE_COSMOS_IDEMPOTENCY_CONTAINER", settings.cosmos_idempotency_container),
        ):
            if not value.strip():
                errors.append(
                    f"{field_name} is required when INTAKE_PERSISTENCE_BACKEND=cosmos"
                )

    if settings.blob_backend == "azure" and not settings.blob_endpoint.strip():
        errors.append(
            "INTAKE_BLOB_ENDPOINT is required when INTAKE_BLOB_BACKEND=azure"
        )

    if (
        settings.servicebus_backend == "azure"
        and not settings.servicebus_namespace.strip()
    ):
        errors.append(
            "INTAKE_SERVICEBUS_NAMESPACE is required when "
            "INTAKE_SERVICEBUS_BACKEND=azure"
        )

    if errors:
        raise IntakeConfigurationError("; ".join(errors))


# ---------------------------------------------------------------------------
# Dependency-injection composition root
# ---------------------------------------------------------------------------

def build_repositories(settings: IntakeSettings | None = None) -> dict[str, object]:
    """Return concrete repository implementations based on settings."""
    from intake_domain.repositories import (
        ArtifactStore,
        IdempotencyStore,
        OutboxRepository,
        RequestRepository,
        TemplateRepository,
    )
    from intake_persistence.inmemory import (
        InMemoryArtifactStore,
        InMemoryIdempotencyStore,
        InMemoryOutboxRepository,
        InMemoryRequestRepository,
        InMemoryTemplateRepository,
    )

    cfg = settings or get_settings()
    validate_hosted_settings(cfg)

    request_repo: RequestRepository
    template_repo: TemplateRepository
    outbox_repo: OutboxRepository
    idempotency_store: IdempotencyStore
    artifact_store: ArtifactStore

    if cfg.persistence_backend == "inmemory":
        request_repo = InMemoryRequestRepository()
        template_repo = InMemoryTemplateRepository()
        idempotency_store = InMemoryIdempotencyStore()

        # Seed a default template for local demo
        _seed_default_template(template_repo, cfg.template_id)

    else:
        # Cosmos adapters — require Azure endpoints
        from intake_persistence.cosmos import (
            CosmosIdempotencyStore,
            CosmosOutboxRepository,
            CosmosRepositoryContext,
            CosmosRequestRepository,
            CosmosTemplateRepository,
        )

        context = CosmosRepositoryContext(
            cfg.cosmos_endpoint,
            cfg.cosmos_database,
            requests_container=cfg.cosmos_requests_container,
            templates_container=cfg.cosmos_templates_container,
            idempotency_container=cfg.cosmos_idempotency_container,
            managed_identity_client_id=cfg.azure_client_id,
        )
        request_repo = CosmosRequestRepository(
            cfg.cosmos_endpoint,
            cfg.cosmos_database,
            context=context,
        )
        template_repo = CosmosTemplateRepository(
            cfg.cosmos_endpoint,
            cfg.cosmos_database,
            context=context,
        )
        idempotency_store = CosmosIdempotencyStore(
            cfg.cosmos_endpoint,
            cfg.cosmos_database,
            context=context,
        )
        outbox_repo = CosmosOutboxRepository(
            cfg.cosmos_endpoint,
            cfg.cosmos_database,
            context=context,
        )

    if cfg.persistence_backend == "inmemory":
        outbox_repo = InMemoryOutboxRepository()

    if cfg.blob_backend == "azure":
        from intake_persistence.blob import BlobArtifactStore

        artifact_store = BlobArtifactStore(
            cfg.blob_endpoint,
            cfg.blob_container_artifacts,
            managed_identity_client_id=cfg.azure_client_id,
        )
    else:
        artifact_store = InMemoryArtifactStore()

    return {
        "request_repo": request_repo,
        "template_repo": template_repo,
        "outbox_repo": outbox_repo,
        "idempotency_store": idempotency_store,
        "artifact_store": artifact_store,
    }


def _seed_default_template(repo: object, template_id: str) -> None:
    from intake_domain.entities import FieldSchema, TemplateVersion

    template = TemplateVersion(
        template_id=template_id,
        version="1.0.0",
        display_name="General Intake Form",
        fields=[
            FieldSchema(
                field_path="project.name",
                label="Project Name",
                field_type="string",
                required=True,
                description="Short name for the initiative or project",
            ),
            FieldSchema(
                field_path="project.description",
                label="Project Description",
                field_type="string",
                required=True,
                description="Brief description of what is needed and why",
            ),
            FieldSchema(
                field_path="requester.business_unit",
                label="Business Unit",
                field_type="string",
                required=True,
                description="The business unit sponsoring this request",
            ),
            FieldSchema(
                field_path="budget.amount",
                label="Budget (USD)",
                field_type="number",
                required=False,
                description="Estimated budget in USD",
            ),
            FieldSchema(
                field_path="timeline.target_date",
                label="Target Completion Date",
                field_type="string",
                required=False,
                description="Desired completion date (YYYY-MM-DD)",
            ),
            FieldSchema(
                field_path="priority",
                label="Priority",
                field_type="enum",
                required=True,
                enum_values=["low", "medium", "high", "critical"],
                description="Business priority of the request",
            ),
        ],
        quality_threshold=0.7,
        is_active=True,
    )
    repo.seed(template)  # type: ignore[attr-defined]
