"""Azure Container Apps composition root for production MCP surfaces."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from intake_application import IntakeService
from intake_domain import default_template
from intake_persistence.composition import (
    AzurePersistenceSettings,
    build_azure_persistence,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from intake_mcp.auth import DelegatedJWTSettings
from intake_mcp.production import (
    ProductionMCPSettings,
    create_requester_server,
    create_reviewer_server,
)


def create_application() -> Starlette:
    """Build both role-bounded MCP applications from process configuration."""

    persistence = build_azure_persistence(_persistence_settings())
    service = IntakeService(
        persistence.request_store,
        {"software-request": default_template()},
        default_reviewer_id=_required("DEFAULT_REVIEWER_ID"),
    )
    base_url = _required("MCP_RESOURCE_SERVER_URL").rstrip("/")
    jwt = _jwt_settings()
    requester = create_requester_server(
        service,
        ProductionMCPSettings(jwt=jwt, resource_server_url=f"{base_url}/requester/mcp"),
    ).streamable_http_app(stateless_http=True)
    reviewer = create_reviewer_server(
        service,
        ProductionMCPSettings(jwt=jwt, resource_server_url=f"{base_url}/reviewer/mcp"),
    ).streamable_http_app(stateless_http=True)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(requester.router.lifespan_context(requester))
                await stack.enter_async_context(reviewer.router.lifespan_context(reviewer))
                yield
        finally:
            persistence.close()

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/healthz", health),
            Mount("/requester", requester),
            Mount("/reviewer", reviewer),
        ],
        lifespan=lifespan,
    )


def _persistence_settings() -> AzurePersistenceSettings:
    return AzurePersistenceSettings(
        cosmos_endpoint=_required("COSMOS_ENDPOINT"),
        cosmos_database=_required("COSMOS_DATABASE"),
        service_bus_namespace=_required("SERVICE_BUS_NAMESPACE"),
        service_bus_queue=_required("SERVICE_BUS_TOPIC"),
        blob_endpoint=_required("STORAGE_BLOB_ENDPOINT"),
        evidence_container=os.environ.get("EVIDENCE_CONTAINER", "evaluation-evidence"),
        managed_identity_client_id=_required("AZURE_CLIENT_ID"),
        service_bus_uses_topic=True,
    )


def _jwt_settings() -> DelegatedJWTSettings:
    tenant_id = _required("ENTRA_TENANT_ID")
    authorized_clients = frozenset(
        value.strip()
        for value in _required("MCP_AUTHORIZED_CLIENT_IDS").split(",")
        if value.strip()
    )
    return DelegatedJWTSettings(
        issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        tenant_id=tenant_id,
        audience=_required("MCP_AUDIENCE"),
        authorized_client_ids=authorized_clients,
        required_scope=_required("MCP_REQUIRED_SCOPE"),
        jwks_url=f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value
