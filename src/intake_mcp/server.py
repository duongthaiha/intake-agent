"""Streamable HTTP MCP server exposing the bounded intake requester tools."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from intake_mcp.auth import (
    EntraTokenVerifier,
    McpIdentity,
    McpSettings,
    identity_from_access_token,
)
from intake_mcp.runtime import PromptIntakeRuntime, get_prompt_runtime

# MCP 1.29 needs an explicit rebuild with pydantic-settings 2.15+.
FastMCPSettings.model_rebuild()

RuntimeProvider = Callable[[], PromptIntakeRuntime]
IdentityProvider = Callable[[], McpIdentity]


def build_mcp_server(
    *,
    runtime_provider: RuntimeProvider = get_prompt_runtime,
    identity_provider: IdentityProvider | None = None,
    token_verifier: TokenVerifier | None = None,
    settings: McpSettings | None = None,
) -> FastMCP[Any]:
    """Create the MCP server with injectable identity/runtime boundaries."""
    identity = identity_provider or (
        lambda: identity_from_access_token(get_access_token())
    )
    auth: AuthSettings | None = None
    if token_verifier is not None:
        cfg = settings or McpSettings()
        auth = AuthSettings(
            issuer_url=cfg.issuer_url(),
            resource_server_url=cfg.resource_url(),
            required_scopes=[cfg.required_scope],
        )

    server = FastMCP(
        "prompt-intake-tools",
        token_verifier=token_verifier,
        auth=auth,
        host="0.0.0.0",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @server.tool()
    async def get_intake_context(
        request_id: Annotated[
            str | None,
            Field(
                description=(
                    "Owned request identifier returned by this service. Omit only "
                    "when start_new=true."
                )
            ),
        ] = None,
        start_new: Annotated[
            bool,
            Field(
                description=(
                    "Set true only when the user explicitly asks to start a new intake."
                )
            ),
        ] = False,
    ) -> dict[str, Any]:
        """Load an owned request or explicitly start a new intake request."""
        return await runtime_provider().get_context(
            identity(),
            request_id=request_id,
            start_new=start_new,
        )

    @server.tool()
    async def update_intake_field(
        request_id: Annotated[
            str,
            Field(description="Owned request_id returned by get_intake_context."),
        ],
        field_path: Annotated[
            str,
            Field(description="Exact template field path from the latest context."),
        ],
        value: Annotated[
            str | int | float | bool,
            Field(description="Value explicitly supplied or confirmed by the user."),
        ],
        expected_revision: Annotated[
            int,
            Field(description="Current revision from the latest context.", ge=1),
        ],
        source_reference: Annotated[
            str | None,
            Field(description="Brief source-turn reference; never include credentials."),
        ] = None,
        model_confidence: Annotated[
            float | None,
            Field(description="Extraction confidence from 0.0 to 1.0.", ge=0.0, le=1.0),
        ] = None,
    ) -> dict[str, Any]:
        """Persist one candidate field through deterministic validation."""
        return await runtime_provider().update_field(
            identity(),
            request_id=request_id,
            expected_revision=expected_revision,
            field_path=field_path,
            value=value,
            source_reference=source_reference,
            model_confidence=model_confidence,
        )

    @server.tool()
    async def submit_intake_for_review(
        request_id: Annotated[
            str,
            Field(description="Owned request_id returned by get_intake_context."),
        ],
        expected_revision: Annotated[
            int,
            Field(description="Current revision from the latest context.", ge=1),
        ],
    ) -> dict[str, Any]:
        """Submit an owned complete request after explicit user confirmation."""
        return await runtime_provider().submit_for_review(
            identity(),
            request_id=request_id,
            expected_revision=expected_revision,
        )

    @server.tool()
    async def list_my_intake_requests() -> list[dict[str, Any]]:
        """List durable requests owned by the verified delegated user."""
        return await runtime_provider().list_requests(identity())

    return server


def build_http_app(
    *,
    runtime_provider: RuntimeProvider = get_prompt_runtime,
    identity_provider: IdentityProvider | None = None,
    token_verifier: TokenVerifier | None = None,
    settings: McpSettings | None = None,
) -> Starlette:
    """Build the authenticated MCP ASGI app plus unauthenticated probe routes."""
    cfg = settings or McpSettings()
    verifier = token_verifier or EntraTokenVerifier(cfg)
    server = build_mcp_server(
        runtime_provider=runtime_provider,
        identity_provider=identity_provider,
        token_verifier=verifier,
        settings=cfg,
    )
    mcp_app = server.streamable_http_app()

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def readiness(_: Request) -> Response:
        runtime_provider()
        return JSONResponse({"status": "ready"})

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/readiness", readiness, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )
