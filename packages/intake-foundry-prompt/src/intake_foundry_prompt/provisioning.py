"""Supported Azure AI Projects operations for Prompt Agent versions."""

from __future__ import annotations

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    ActivityProtocolConfiguration,
    AgentEndpointConfig,
    AgentVersionDetails,
    BotServiceRbacAuthorizationScheme,
    BotServiceTenantAuthorizationScheme,
    EntraAuthorizationScheme,
    FixedRatioVersionSelectionRule,
    MCPTool,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from intake_agent_behavior import render_role_instructions

from intake_foundry_prompt.configuration import PromptAgentVariant


def build_definition(
    variant: PromptAgentVariant,
    *,
    project_endpoint: str,
    model_deployment: str,
) -> PromptAgentDefinition:
    """Build a Prompt Agent against a deterministic agent-safe Toolbox gateway."""
    toolbox_url = (
        f"{project_endpoint.rstrip('/')}/toolboxes/{variant.toolbox_name}/mcp?api-version=v1"
    )
    return PromptAgentDefinition(
        model=model_deployment,
        instructions=render_role_instructions(variant.role),
        temperature=0,
        tools=[
            MCPTool(
                server_label=variant.server_label,
                server_url=toolbox_url,
                require_approval="never",
                project_connection_id=variant.toolbox_connection_name,
            )
        ],
    )


def create_version(
    project_client: AIProjectClient,
    variant: PromptAgentVariant,
    *,
    project_endpoint: str,
    model_deployment: str,
) -> AgentVersionDetails:
    """Create an immutable Prompt Agent version; credential ownership stays with the caller."""
    return project_client.agents.create_version(
        agent_name=variant.agent_name,
        definition=build_definition(
            variant,
            project_endpoint=project_endpoint,
            model_deployment=model_deployment,
        ),
        description=variant.description,
        metadata={
            "intakeBehaviorVersion": "1.0",
            "intakeContractVersion": "1.0",
            "intakeRole": variant.role.value,
            "requiredGatewayCapabilities": ",".join(
                variant.required_gateway_capabilities
            ),
        },
    )


def configure_endpoint(
    project_client: AIProjectClient,
    *,
    agent_name: str,
    agent_version: str,
    tenant_wide: bool = False,
) -> None:
    """Pin a tested version and enable Responses plus Teams Activity protocols."""
    bot_scheme = (
        BotServiceTenantAuthorizationScheme()
        if tenant_wide
        else BotServiceRbacAuthorizationScheme()
    )
    project_client.agents.update_details(
        agent_name=agent_name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(
                        agent_version=agent_version,
                        traffic_percentage=100,
                    )
                ]
            ),
            protocol_configuration=ProtocolConfiguration(
                responses=ResponsesProtocolConfiguration(),
                activity=ActivityProtocolConfiguration(),
            ),
            authorization_schemes=[EntraAuthorizationScheme(), bot_scheme],
        ),
    )
