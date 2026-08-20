"""Microsoft Agent Framework Responses host composition."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from agent_framework import Agent
from intake_agent_behavior import render_role_instructions
from intake_agent_contracts import AgentRole

from intake_foundry_hosted.adapter import ToolboxIntakeContextProvider

if TYPE_CHECKING:
    from agent_framework.foundry import ResponsesHostServer
    from azure.core.credentials import TokenCredential


@dataclass(frozen=True)
class HostedAgentSettings:
    project_endpoint: str
    model_deployment: str
    toolbox_endpoint: str
    toolbox_name: str
    role: AgentRole = AgentRole.REQUESTER
    template_id: str = "software-request"

    @classmethod
    def from_environment(cls) -> HostedAgentSettings:
        role = AgentRole(os.environ.get("INTAKE_AGENT_ROLE", AgentRole.REQUESTER.value))
        role_prefix = role.value.upper()
        return cls(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model_deployment=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            toolbox_endpoint=os.environ[f"INTAKE_{role_prefix}_TOOLBOX_ENDPOINT"],
            toolbox_name=os.environ.get(
                f"INTAKE_{role_prefix}_TOOLBOX_NAME", f"intake-{role.value}"
            ),
            role=role,
            template_id=os.environ.get("INTAKE_TEMPLATE_ID", "software-request"),
        )


def build_responses_host(
    credential: TokenCredential,
    settings: HostedAgentSettings,
    *,
    correlation_id_factory: Callable[[], str] | None = None,
) -> ResponsesHostServer:
    """Compose the current Foundry Responses 2.0 host without owning credentials."""
    from agent_framework.foundry import FoundryChatClient
    from agent_framework_foundry_hosting import (  # type: ignore[import-not-found]
        FoundryToolbox,
        ResponsesHostServer,
    )

    # The optional hosting extra supplies this lazy re-export only in the
    # mutually exclusive Hosted Agent environment.
    class GuardedFoundryToolbox(FoundryToolbox):  # type: ignore[misc]
        async def connect(self, *, reset: bool = False) -> None:
            await super().connect(reset=reset)
            # Discovery must happen during host initialization so the Responses
            # server can emit oauth_consent_request. The model receives only the
            # adapter functions added from authoritative allowedActions.
            self.functions.clear()

    toolbox = GuardedFoundryToolbox(
        credential,
        url=settings.toolbox_endpoint,
        name=settings.toolbox_name,
        load_tools=True,
    )
    provider = ToolboxIntakeContextProvider(
        toolbox,
        role=settings.role,
        template_id=settings.template_id,
        correlation_id_factory=correlation_id_factory or (lambda: str(uuid4())),
    )
    client = FoundryChatClient(
        project_endpoint=settings.project_endpoint,
        model=settings.model_deployment,
        credential=credential,
    )
    agent = Agent(
        client=client,
        name=f"intake-{settings.role.value}",
        instructions=render_role_instructions(settings.role),
        tools=toolbox,
        context_providers=[provider],
        default_options={"store": False},
    )
    return ResponsesHostServer(agent)
