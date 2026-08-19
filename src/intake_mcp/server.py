"""Private stateless streamable-HTTP MCP composition root."""
from __future__ import annotations

import asyncio
import json
import warnings
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import AnyHttpUrl
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from intake_agent.application import IntakeApplication
from intake_agent.config import (
    IntakeConfigurationError,
    IntakeSettings,
    build_repositories,
    get_settings,
    validate_mcp_settings,
)
from intake_agent.requester_tools import (
    GetIntakeContextRequest,
    ListMyIntakeRequestsRequest,
    OperationContext,
    SubmitIntakeForReviewRequest,
    ToolResult,
    UpdateIntakeFieldRequest,
)
from intake_agent.requester_tools.service import IntakeToolService
from intake_domain.errors import IntakeDomainError, TransientError
from intake_mcp.auth import EntraTokenVerifier, LocalTokenVerifier
from intake_mcp.context import operation_context

T = TypeVar("T")


def build_mcp_app(settings: IntakeSettings | None = None) -> Any:
    """Build an authenticated ASGI MCP application."""
    cfg = settings or get_settings()
    validate_mcp_settings(cfg)
    repositories = build_repositories(cfg)
    service = IntakeToolService(
        IntakeApplication(**repositories, template_id=cfg.template_id)
    )
    ready = True

    local = cfg.environment.strip().lower() == "local"
    issuer = (
        "http://127.0.0.1"
        if local
        else cfg.mcp_issuer.strip()
        or f"https://login.microsoftonline.com/{cfg.mcp_tenant_id.strip()}/v2.0"
    )
    resource_url = (
        "http://127.0.0.1"
        if local
        else cfg.mcp_resource_url.strip()
    )
    verifier = LocalTokenVerifier(cfg) if local else EntraTokenVerifier(cfg)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=IncompleteFieldDefinitionWarning)
        mcp = FastMCP(
            "intake-requester-tools",
            instructions=(
                "Deterministic requester intake operations. Reviewer tools are unavailable."
            ),
            stateless_http=True,
            json_response=True,
            host=cfg.mcp_host,
            port=cfg.mcp_port,
            token_verifier=verifier,
            auth=AuthSettings(
                issuer_url=AnyHttpUrl(issuer),
                resource_server_url=AnyHttpUrl(resource_url) if resource_url else None,
                required_scopes=[cfg.mcp_required_scope],
            ),
        )

    def trusted_context(
        context: Context[Any, Any, Any],
        *,
        mutation: bool,
    ) -> OperationContext:
        try:
            return operation_context(context, cfg, mutation=mutation)
        except IntakeConfigurationError as exc:
            raise ToolError(
                json.dumps(
                    {
                        "status": "error",
                        "error_code": "TRUSTED_CONTEXT_INVALID",
                        "message": str(exc),
                        "retry_eligible": False,
                    }
                )
            ) from exc

    async def invoke(
        operation: Callable[[], Awaitable[ToolResult]],
        *,
        retry_read: bool,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        attempts = 2 if retry_read else 1
        for attempt in range(attempts):
            try:
                async with asyncio.timeout(cfg.mcp_operation_timeout_seconds):
                    return (await operation()).root
            except TransientError:
                if attempt + 1 == attempts:
                    raise
                await asyncio.sleep(0.05)
            except TimeoutError as exc:
                raise ToolError(
                    json.dumps(
                        {
                            "status": "error",
                            "error_code": "OPERATION_TIMEOUT",
                            "retry_eligible": retry_read,
                        }
                    )
                ) from exc
            except IntakeDomainError as exc:
                raise ToolError(json.dumps(exc.to_dict(), default=str)) from exc
        raise RuntimeError("unreachable")

    @mcp.tool()
    async def get_intake_context(ctx: Context[Any, Any, Any]) -> dict[str, Any]:
        """Load authoritative persisted fields, gaps, revision, and allowed actions."""
        trusted = trusted_context(ctx, mutation=False)
        result = await invoke(
            lambda: service.get_intake_context(GetIntakeContextRequest(), trusted),
            retry_read=True,
        )
        if not isinstance(result, dict):
            raise ToolError("Invalid get_intake_context result")
        return result

    @mcp.tool()
    async def update_intake_field(
        field_path: str,
        value: str | int | float | bool,
        expected_revision: int,
        ctx: Context[Any, Any, Any],
        source_reference: str | None = None,
        model_confidence: float | None = None,
    ) -> dict[str, Any]:
        """Submit one candidate field update through deterministic validation."""
        trusted = trusted_context(ctx, mutation=True)
        request = UpdateIntakeFieldRequest(
            field_path=field_path,
            value=value,
            expected_revision=expected_revision,
            source_reference=source_reference,
            model_confidence=model_confidence,
        )
        result = await invoke(
            lambda: service.update_intake_field(request, trusted),
            retry_read=False,
        )
        if not isinstance(result, dict):
            raise ToolError("Invalid update_intake_field result")
        return result

    @mcp.tool()
    async def submit_intake_for_review(
        expected_revision: int,
        ctx: Context[Any, Any, Any],
    ) -> dict[str, Any]:
        """Submit the current request only after explicit user confirmation."""
        trusted = trusted_context(ctx, mutation=True)
        request = SubmitIntakeForReviewRequest(expected_revision=expected_revision)
        result = await invoke(
            lambda: service.submit_intake_for_review(request, trusted),
            retry_read=False,
        )
        if not isinstance(result, dict):
            raise ToolError("Invalid submit_intake_for_review result")
        return result

    @mcp.tool()
    async def list_my_intake_requests(
        ctx: Context[Any, Any, Any],
    ) -> list[dict[str, Any]]:
        """List requests scoped to the verified current Entra user."""
        trusted = trusted_context(ctx, mutation=False)
        result = await invoke(
            lambda: service.list_my_intake_requests(
                ListMyIntakeRequestsRequest(),
                trusted,
            ),
            retry_read=True,
        )
        if not isinstance(result, list):
            raise ToolError("Invalid list_my_intake_requests result")
        return result

    @mcp.custom_route(  # type: ignore[untyped-decorator]
        "/health", methods=["GET"], include_in_schema=False
    )
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route(  # type: ignore[untyped-decorator]
        "/readiness", methods=["GET"], include_in_schema=False
    )
    async def readiness(_: Request) -> Response:
        status = 200 if ready else 503
        return JSONResponse(
            {"status": "ready" if ready else "not_ready"},
            status_code=status,
        )

    return mcp.streamable_http_app()


app = build_mcp_app()
