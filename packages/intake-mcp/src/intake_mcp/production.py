"""Authenticated production requester and reviewer MCP surfaces."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from intake_agent_contracts import (
    AddReviewCommentRequest,
    DecideReviewRequest,
    ErrorDetail,
    GetIntakeContextRequest,
    GetReviewContextRequest,
    ListAssignedReviewsRequest,
    ListMyRequestsRequest,
    RequestChangesRequest,
    SubmitIntakeRequest,
    ToolResponse,
    UpdateFieldRequest,
)
from intake_agent_contracts import (
    ErrorCode as ContractErrorCode,
)
from intake_application import IntakeService, Outcome
from intake_domain import ActorContext, ActorRole, AgentKind, Provenance
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from intake_mcp.auth import (
    DelegatedJWTSettings,
    DelegatedJWTVerifier,
    actor_from_access_token,
)

ReadinessCheck = Callable[[], bool | Awaitable[bool]]
CorrelationIdFactory = Callable[[], str]

DEFAULT_MAX_REQUEST_BODY_SIZE = 256 * 1024


@dataclass(frozen=True, slots=True)
class ProductionMCPSettings:
    jwt: DelegatedJWTSettings
    resource_server_url: str
    max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE
    provenance: Provenance = field(
        default_factory=lambda: Provenance(
            agent_kind=AgentKind.HOSTED,
            agent_version="production-1.0",
            instructions_version="1.0",
            model_version="server-configured",
            toolbox_version="production-1.0",
            mcp_contract_version="1.0",
            policy_version="1.0",
        )
    )

    def __post_init__(self) -> None:
        if not self.resource_server_url:
            raise ValueError("resource_server_url must not be empty")
        if self.max_request_body_size <= 0:
            raise ValueError("max_request_body_size must be positive")


class ProductionMCPServer(MCPServer[Any]):
    """MCPServer that always applies the configured HTTP request-size limit."""

    def __init__(self, *args: Any, max_request_body_size: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_request_body_size = max_request_body_size

    def streamable_http_app(self, **kwargs: Any) -> Starlette:
        kwargs.setdefault("max_request_body_size", self.max_request_body_size)
        return super().streamable_http_app(**kwargs)

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        **kwargs: Any,
    ) -> None:
        if transport == "streamable-http":
            kwargs.setdefault("max_request_body_size", self.max_request_body_size)
        super().run(transport=transport, **kwargs)


def create_requester_server(
    service: IntakeService,
    settings: ProductionMCPSettings,
    *,
    token_verifier: TokenVerifier | None = None,
    readiness_check: ReadinessCheck | None = None,
    correlation_id_factory: CorrelationIdFactory | None = None,
) -> ProductionMCPServer:
    """Create the production requester-only MCP resource server."""

    server = _create_server(
        "Intake Agent Requester",
        settings,
        token_verifier=token_verifier,
        readiness_check=readiness_check,
    )
    actor = _actor_factory(
        settings,
        ActorRole.REQUESTER,
        correlation_id_factory or (lambda: str(uuid4())),
    )

    @server.tool()
    def get_intake_context(request: GetIntakeContextRequest) -> ToolResponse:
        return _response(
            service.get_intake_context(actor(), request.conversation_key, request.template_id)
        )

    @server.tool()
    def update_intake_field(request: UpdateFieldRequest) -> ToolResponse:
        return _response(
            service.update_intake_field(
                actor(),
                request.request_id,
                request.expected_revision,
                request.command_id,
                request.field_path,
                request.value,
                request.source_reference,
                request.confidence,
            )
        )

    @server.tool()
    def submit_intake_for_review(request: SubmitIntakeRequest) -> ToolResponse:
        return _response(
            service.submit_intake_for_review(
                actor(),
                request.request_id,
                request.expected_revision,
                request.command_id,
                confirmed=request.confirmed,
            )
        )

    @server.tool()
    def list_my_intake_requests(request: ListMyRequestsRequest) -> ToolResponse:
        return _response(service.list_my_intake_requests(actor(), request.limit))

    return server


def create_reviewer_server(
    service: IntakeService,
    settings: ProductionMCPSettings,
    *,
    token_verifier: TokenVerifier | None = None,
    readiness_check: ReadinessCheck | None = None,
    correlation_id_factory: CorrelationIdFactory | None = None,
) -> ProductionMCPServer:
    """Create the production reviewer-only MCP resource server."""

    server = _create_server(
        "Intake Agent Reviewer",
        settings,
        token_verifier=token_verifier,
        readiness_check=readiness_check,
    )
    actor = _actor_factory(
        settings,
        ActorRole.REVIEWER,
        correlation_id_factory or (lambda: str(uuid4())),
    )

    @server.tool()
    def list_assigned_reviews(request: ListAssignedReviewsRequest) -> ToolResponse:
        return _response(service.list_assigned_reviews(actor(), request.limit))

    @server.tool()
    def get_review_context(request: GetReviewContextRequest) -> ToolResponse:
        return _response(service.get_review_context(actor(), request.request_id))

    @server.tool()
    def add_review_comment(request: AddReviewCommentRequest) -> ToolResponse:
        return _response(
            service.add_review_comment(
                actor(),
                request.request_id,
                request.expected_revision,
                request.command_id,
                request.comment,
            )
        )

    @server.tool()
    def request_intake_changes(request: RequestChangesRequest) -> ToolResponse:
        return _response(
            service.request_intake_changes(
                actor(),
                request.request_id,
                request.expected_revision,
                request.command_id,
                request.rationale,
            )
        )

    @server.tool()
    def decide_intake_review(request: DecideReviewRequest) -> ToolResponse:
        return _response(
            service.decide_intake_review(
                actor(),
                request.request_id,
                request.expected_revision,
                request.command_id,
                request.decision,
                request.rationale,
            )
        )

    return server


def _create_server(
    name: str,
    settings: ProductionMCPSettings,
    *,
    token_verifier: TokenVerifier | None,
    readiness_check: ReadinessCheck | None,
) -> ProductionMCPServer:
    verifier = token_verifier or DelegatedJWTVerifier(settings.jwt)
    auth = AuthSettings.model_validate(
        {
            "issuer_url": settings.jwt.issuer,
            "resource_server_url": settings.resource_server_url,
            "required_scopes": [settings.jwt.required_scope],
        }
    )
    server = ProductionMCPServer(
        name,
        version="1.0.0",
        token_verifier=verifier,
        auth=auth,
        max_request_body_size=settings.max_request_body_size,
    )
    check = readiness_check or (lambda: True)

    @server.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    @server.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    @server.custom_route("/readyz", methods=["GET"])  # type: ignore[untyped-decorator]
    @server.custom_route("/ready", methods=["GET"])  # type: ignore[untyped-decorator]
    async def ready(_: Request) -> Response:
        try:
            result = check()
            is_ready = await result if inspect.isawaitable(result) else result
        except (ConnectionError, OSError, TimeoutError):
            is_ready = False
        return JSONResponse(
            {"status": "ready" if is_ready else "not_ready"},
            status_code=200 if is_ready else 503,
        )

    return server


def _actor_factory(
    settings: ProductionMCPSettings,
    role: ActorRole,
    correlation_id_factory: CorrelationIdFactory,
) -> Callable[[], ActorContext]:
    def actor() -> ActorContext:
        return actor_from_access_token(
            get_access_token(),
            tenant_id=settings.jwt.tenant_id,
            role=role,
            provenance=settings.provenance,
            correlation_id_factory=correlation_id_factory,
        )

    return actor


def _response(outcome: Outcome) -> ToolResponse:
    if outcome.error is not None:
        return ToolResponse(
            ok=False,
            replayed=outcome.replayed,
            error=ErrorDetail(
                code=ContractErrorCode(outcome.error.code.value),
                message=outcome.error.message,
                fieldPath=outcome.error.field_path,
                latestRevision=outcome.error.latest_revision,
                retryable=outcome.error.retryable,
            ),
        )
    return ToolResponse(ok=outcome.ok, replayed=outcome.replayed, data=outcome.data)


create_production_requester_server = create_requester_server
create_production_reviewer_server = create_reviewer_server
