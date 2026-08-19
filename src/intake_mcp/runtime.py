"""Deterministic application adapter used by the prompt-agent MCP tools."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any
from uuid import uuid4

from intake_agent.application import IntakeApplication
from intake_agent.config import IntakeSettings, build_repositories, get_settings
from intake_domain.entities import ActorContext
from intake_domain.errors import PreconditionFailedError
from intake_mcp.auth import McpIdentity


class PromptIntakeRuntime:
    """Bind verified delegated users to the shared deterministic application."""

    def __init__(
        self,
        application: IntakeApplication,
        settings: IntakeSettings,
    ) -> None:
        self._application = application
        self._settings = settings

    async def get_context(
        self,
        identity: McpIdentity,
        *,
        request_id: str | None,
        start_new: bool,
    ) -> dict[str, Any]:
        if request_id and start_new:
            raise PreconditionFailedError(
                "Choose either an existing request_id or start_new=true, not both"
            )
        if start_new:
            actor = self._actor(
                identity,
                conversation_id=f"prompt-{uuid4()}",
            )
            created = await self._application.get_or_create_request(actor)
            context = await self._application.get_context(
                str(created["request_id"]),
                actor,
            )
            return {**context, "created": bool(created["created"])}
        if not request_id:
            raise PreconditionFailedError(
                "request_id is required unless start_new=true; "
                "use list_my_intake_requests to select an owned request"
            )

        actor = self._actor(identity, conversation_id=f"request-{request_id}")
        return await self._application.get_context(request_id, actor)

    async def update_field(
        self,
        identity: McpIdentity,
        *,
        request_id: str,
        expected_revision: int,
        field_path: str,
        value: str | int | float | bool,
        source_reference: str | None,
        model_confidence: float | None,
    ) -> dict[str, Any]:
        actor = self._actor(identity, conversation_id=f"request-{request_id}")
        return await self._application.propose_updates(
            request_id=request_id,
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

    async def submit_for_review(
        self,
        identity: McpIdentity,
        *,
        request_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        actor = self._actor(identity, conversation_id=f"request-{request_id}")
        return await self._application.submit_for_review(
            request_id=request_id,
            expected_revision=expected_revision,
            actor=actor,
        )

    async def list_requests(self, identity: McpIdentity) -> list[dict[str, Any]]:
        return await self._application.list_requests(
            self._actor(identity, conversation_id="prompt-list")
        )

    def _actor(
        self,
        identity: McpIdentity,
        *,
        conversation_id: str,
    ) -> ActorContext:
        opaque_user_id = hashlib.sha256(
            f"{identity.tenant_id}:{identity.object_id}".encode()
        ).hexdigest()[:32]
        return ActorContext(
            user_id=f"prompt-user-{opaque_user_id}",
            tenant_id=identity.tenant_id,
            roles=frozenset(["requester"]),
            conversation_id=conversation_id,
            activity_id=str(uuid4()),
            correlation_id=str(uuid4()),
            agent_identity="prompt-intake-agent",
        )


def build_prompt_runtime(
    settings: IntakeSettings | None = None,
) -> PromptIntakeRuntime:
    cfg = settings or get_settings()
    repositories = build_repositories(cfg)
    return PromptIntakeRuntime(
        application=IntakeApplication(
            **repositories,
            template_id=cfg.template_id,
        ),
        settings=cfg,
    )


@lru_cache(maxsize=1)
def get_prompt_runtime() -> PromptIntakeRuntime:
    return build_prompt_runtime()
