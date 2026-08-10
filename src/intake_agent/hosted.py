"""Microsoft Foundry Hosted Agent entry point using the Responses protocol."""
from __future__ import annotations

import hashlib
import logging
import os
import warnings
from collections.abc import AsyncIterator, Sequence
from contextvars import ContextVar, Token
from functools import lru_cache
from typing import Annotated, Any, cast
from uuid import uuid4

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=Warning, module=r"agent_framework(\..*)?")
    from agent_framework import Agent, tool
    from agent_framework.foundry import FoundryChatClient
    from agent_framework_foundry_hosting import ResponsesHostServer  # type: ignore[import-untyped]
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from intake_agent.application import IntakeApplication
from intake_agent.config import (
    IntakeConfigurationError,
    IntakeSettings,
    build_repositories,
    get_settings,
    validate_hosted_settings,
)
from intake_domain.entities import ActorContext

logger = logging.getLogger(__name__)

AGENT_INSTRUCTIONS = """You are the Intake Agent.

Help the user capture a structured intake request. Before answering about the
request, call get_intake_context so persisted domain state is authoritative.
Use update_intake_field only for values the user supplied or explicitly
confirmed. Never invent field values, revisions, identities, roles, approvals,
or review decisions. Explain deterministic validation and gaps clearly. Call
submit_intake_for_review only after the context reports can_submit=true and the
user explicitly asks to submit. Reviewer decisions are outside this agent's
available tools.
"""

_current_actor: ContextVar[ActorContext | None] = ContextVar(
    "intake_hosted_actor",
    default=None,
)


class HostedRuntime:
    """Session-isolated adapter over the shared deterministic application."""

    def __init__(
        self,
        application: IntakeApplication,
        settings: IntakeSettings,
    ) -> None:
        validate_hosted_settings(settings)
        self._application = application
        self._settings = settings

    def bind_actor(
        self,
        *,
        user_isolation_key: str | None,
        chat_isolation_key: str | None,
        response_id: str,
        conversation_id: str | None,
    ) -> Token[ActorContext | None]:
        actor = self._actor_from_isolation(
            user_isolation_key=user_isolation_key,
            chat_isolation_key=chat_isolation_key,
            response_id=response_id,
            conversation_id=conversation_id,
        )
        return _current_actor.set(actor)

    @staticmethod
    def reset_actor(token: Token[ActorContext | None]) -> None:
        _current_actor.reset(token)

    async def get_context(self) -> dict[str, Any]:
        actor = _require_actor()
        request = await self._application.get_or_create_request(actor)
        return await self._application.get_context(str(request["request_id"]), actor)

    async def update_field(
        self,
        *,
        expected_revision: int,
        field_path: str,
        value: str | int | float | bool,
        source_reference: str | None,
        model_confidence: float | None,
    ) -> dict[str, Any]:
        actor = _require_actor()
        request = await self._application.get_or_create_request(actor)
        return await self._application.propose_updates(
            request_id=str(request["request_id"]),
            expected_revision=expected_revision,
            updates=[
                {
                    "field_path": field_path,
                    "value": value,
                    "source_reference": source_reference,
                    "model_confidence": model_confidence,
                }
            ],
            actor=actor,
        )

    async def submit_for_review(self, *, expected_revision: int) -> dict[str, Any]:
        actor = _require_actor()
        request = await self._application.get_or_create_request(actor)
        return await self._application.submit_for_review(
            request_id=str(request["request_id"]),
            expected_revision=expected_revision,
            actor=actor,
        )

    async def list_requests(self) -> list[dict[str, Any]]:
        return await self._application.list_requests(_require_actor())

    def _actor_from_isolation(
        self,
        *,
        user_isolation_key: str | None,
        chat_isolation_key: str | None,
        response_id: str,
        conversation_id: str | None,
    ) -> ActorContext:
        environment = self._settings.environment.strip().lower()
        if environment == "local":
            user_key = user_isolation_key or "local-user"
            chat_key = chat_isolation_key or conversation_id or response_id
            tenant_id = self._settings.hosted_tenant_id.strip() or "local-tenant"
        else:
            if not user_isolation_key or not chat_isolation_key:
                raise IntakeConfigurationError(
                    "Foundry user/chat isolation keys are required outside local "
                    "development; refusing an unscoped Responses request"
                )
            user_key = user_isolation_key
            chat_key = chat_isolation_key
            tenant_id = self._settings.hosted_tenant_id.strip()

        opaque_user_id = hashlib.sha256(
            f"{tenant_id}:{user_key}".encode()
        ).hexdigest()[:32]
        return ActorContext(
            user_id=f"foundry-user-{opaque_user_id}",
            tenant_id=tenant_id,
            roles=frozenset(["requester"]),
            conversation_id=chat_key,
            activity_id=response_id,
            correlation_id=str(uuid4()),
            agent_identity=self._settings.hosted_agent_identity,
        )


class IntakeResponsesHostServer(ResponsesHostServer):  # type: ignore[misc]
    """Binds Foundry isolation context before Agent Framework invokes tools."""

    def __init__(self, agent: Agent, runtime: HostedRuntime) -> None:
        super().__init__(agent)
        self._runtime = runtime
        self.add_route("/health", _health, methods=["GET"], name="health")

    async def _handle_inner_agent(
        self,
        request: Any,
        context: Any,
    ) -> AsyncIterator[Any]:
        user_key, chat_key = _resolve_platform_isolation(context)
        token = self._runtime.bind_actor(
            user_isolation_key=user_key,
            chat_isolation_key=chat_key,
            response_id=context.response_id,
            conversation_id=context.conversation_id,
        )
        try:
            async for item in super()._handle_inner_agent(request, context):
                yield item
        finally:
            self._runtime.reset_actor(token)


def build_hosted_runtime(settings: IntakeSettings | None = None) -> HostedRuntime:
    cfg = settings or get_settings()
    validate_hosted_settings(cfg)
    repositories = build_repositories(cfg)
    application = IntakeApplication(
        **repositories,
        template_id=cfg.template_id,
    )
    return HostedRuntime(application=application, settings=cfg)


@lru_cache(maxsize=1)
def get_hosted_runtime() -> HostedRuntime:
    return build_hosted_runtime()


def resolve_foundry_configuration(
    environment: dict[str, str] | None = None,
) -> tuple[str, str]:
    values = environment if environment is not None else cast(dict[str, str], os.environ)
    endpoint = values.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    model = values.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()

    errors: list[str] = []
    if not endpoint:
        errors.append("FOUNDRY_PROJECT_ENDPOINT is required")
    if not model:
        errors.append("AZURE_AI_MODEL_DEPLOYMENT_NAME is required")
    if errors:
        raise IntakeConfigurationError("; ".join(errors))
    return endpoint, model


def create_intake_tools(runtime: HostedRuntime) -> Sequence[Any]:
    @tool(approval_mode="never_require")
    async def get_intake_context() -> dict[str, Any]:
        """Load authoritative persisted fields, gaps, revision, and allowed actions."""
        return await runtime.get_context()

    @tool(approval_mode="never_require")
    async def update_intake_field(
        field_path: Annotated[
            str,
            Field(description="Exact template field path returned by get_intake_context."),
        ],
        value: Annotated[
            str | int | float | bool,
            Field(description="Value explicitly supplied or confirmed by the user."),
        ],
        expected_revision: Annotated[
            int,
            Field(description="Current revision returned by get_intake_context.", ge=1),
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
        """Submit one candidate field update through deterministic validation."""
        return await runtime.update_field(
            expected_revision=expected_revision,
            field_path=field_path,
            value=value,
            source_reference=source_reference,
            model_confidence=model_confidence,
        )

    @tool(approval_mode="never_require")
    async def submit_intake_for_review(
        expected_revision: Annotated[
            int,
            Field(description="Current revision returned by get_intake_context.", ge=1),
        ],
    ) -> dict[str, Any]:
        """Submit the current request only after explicit user confirmation."""
        return await runtime.submit_for_review(expected_revision=expected_revision)

    @tool(approval_mode="never_require")
    async def list_my_intake_requests() -> list[dict[str, Any]]:
        """List requests scoped to the platform-isolated current user."""
        return await runtime.list_requests()

    return [
        get_intake_context,
        update_intake_field,
        submit_intake_for_review,
        list_my_intake_requests,
    ]


def build_responses_server(
    settings: IntakeSettings | None = None,
) -> IntakeResponsesHostServer:
    load_dotenv(override=False)
    endpoint, model = resolve_foundry_configuration()
    runtime = build_hosted_runtime(settings)
    credential = DefaultAzureCredential()
    client = FoundryChatClient(
        project_endpoint=endpoint,
        model=model,
        credential=credential,
    )
    agent = Agent(
        client=client,
        name="intake-agent",
        description="Captures and validates structured enterprise intake requests.",
        instructions=AGENT_INSTRUCTIONS,
        tools=create_intake_tools(runtime),
        default_options={"store": True, "include": []},
    )
    return IntakeResponsesHostServer(agent, runtime)


async def _health(_: Request) -> Response:
    """Liveness; the SDK-provided /readiness route covers startup readiness."""
    return JSONResponse({"status": "ok"})


def _require_actor() -> ActorContext:
    actor = _current_actor.get()
    if actor is None:
        raise IntakeConfigurationError(
            "No Foundry isolation context is bound to the current tool invocation"
        )
    return actor


def _resolve_platform_isolation(context: Any) -> tuple[str | None, str | None]:
    isolation = getattr(context, "isolation", None)
    if isolation is not None:
        return (
            getattr(isolation, "user_key", None),
            getattr(isolation, "chat_key", None),
        )

    platform_context = getattr(context, "platform_context", None)
    user_key = getattr(platform_context, "user_id_key", None)
    chat_key = getattr(context, "conversation_id", None)
    if not chat_key:
        chat_key = getattr(platform_context, "call_id", None)
    return user_key, chat_key


def run() -> None:
    """Start the Responses protocol host on PORT or 8088."""
    build_responses_server().run()


if __name__ == "__main__":
    run()
