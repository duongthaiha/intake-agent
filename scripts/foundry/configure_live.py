"""Configure private Foundry connections, toolboxes, and Prompt Agent versions."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import quote

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointProtocol,
    ContainerConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.identity import ManagedIdentityCredential
from intake_foundry_prompt import configure_endpoint, create_version, load_variants

ARM_API_VERSION = "2025-04-01-preview"
TOOLBOX_API_VERSION = "v1"
HOSTED_PROTOCOL_VERSION = "2.0.0"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    response = session.request(
        method,
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=60,
    )
    if response.status_code not in expected:
        detail = response.text[:1000]
        raise RuntimeError(
            f"Foundry request failed: {method} {url} returned {response.status_code}: {detail}"
        )
    if not response.content:
        return {}
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"Foundry request returned a non-object: {method} {url}")
    return value


def _connection_url(project_id: str, name: str) -> str:
    return (
        f"https://management.azure.com{project_id}/connections/{quote(name, safe='')}"
        f"?api-version={ARM_API_VERSION}"
    )


def _upsert_connection(
    session: requests.Session,
    arm_token: str,
    project_id: str,
    name: str,
    properties: dict[str, Any],
) -> dict[str, Any]:
    return _request_json(
        session,
        "PUT",
        _connection_url(project_id, name),
        arm_token,
        body={"properties": properties},
        expected=(200, 201),
    )


def _ensure_toolbox(
    session: requests.Session,
    ai_token: str,
    *,
    project_endpoint: str,
    name: str,
    description: str,
    connection_id: str,
    connection_name: str,
    server_url: str,
) -> str:
    toolbox_url = (
        f"{project_endpoint.rstrip('/')}/toolboxes/{quote(name, safe='')}"
        f"?api-version={TOOLBOX_API_VERSION}"
    )
    response = session.get(
        toolbox_url,
        headers={"Authorization": f"Bearer {ai_token}"},
        timeout=60,
    )
    if response.status_code == 200:
        value = response.json()
        version = str(value.get("default_version", ""))
        if not version:
            raise RuntimeError(f"Foundry toolbox {name} has no default version")
        return version
    if response.status_code != 404:
        raise RuntimeError(
            f"Foundry toolbox lookup failed for {name}: "
            f"{response.status_code}: {response.text[:1000]}"
        )

    created = _request_json(
        session,
        "POST",
        f"{project_endpoint.rstrip('/')}/toolboxes/{quote(name, safe='')}/versions"
        f"?api-version={TOOLBOX_API_VERSION}",
        ai_token,
        body={
            "description": description,
            "tools": [
                {
                    "type": "mcp",
                    "name": connection_name,
                    "server_label": name,
                    "server_url": server_url,
                    "project_connection_id": connection_id,
                }
            ],
        },
        expected=(200, 201),
    )
    version = str(created.get("version", ""))
    if not version:
        raise RuntimeError(f"Foundry toolbox {name} did not return a version")
    _request_json(
        session,
        "PATCH",
        toolbox_url,
        ai_token,
        body={"default_version": version},
    )
    return version


def _redirect_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if "redirect" in str(key).lower() and isinstance(item, str):
                values.append(item)
            else:
                values.extend(_redirect_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_redirect_values(item))
    return values


def _wait_for_hosted_agent(
    client: AIProjectClient,
    *,
    agent_name: str,
    agent_version: str,
    timeout_seconds: int = 600,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        details = client.agents.get_version(
            agent_name=agent_name,
            agent_version=agent_version,
        )
        status_value = (
            details.get("status") if isinstance(details, dict) else getattr(details, "status", "")
        )
        status = str(getattr(status_value, "value", status_value)).lower()
        if status == "active":
            return details
        if status == "failed":
            error = (
                details.get("error")
                if isinstance(details, dict)
                else getattr(details, "error", None)
            )
            raise RuntimeError(f"Hosted Agent {agent_name} version {agent_version} failed: {error}")
        time.sleep(10)
    raise TimeoutError(f"Hosted Agent {agent_name} version {agent_version} did not become active")


def run() -> dict[str, Any]:
    managed_identity_client_id = _required("AZURE_CLIENT_ID")
    tenant_id = _required("AZURE_TENANT_ID")
    project_endpoint = _required("FOUNDRY_PROJECT_ENDPOINT")
    project_id = _required("FOUNDRY_PROJECT_RESOURCE_ID")
    oauth_client_id = _required("FOUNDRY_OAUTH_CLIENT_ID")
    oauth_client_secret = _required("FOUNDRY_OAUTH_CLIENT_SECRET")
    audience = _required("MCP_AUDIENCE")
    scope = _required("MCP_REQUIRED_SCOPE")
    model_deployment = _required("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    hosted_agent_image = _required("HOSTED_AGENT_IMAGE")
    authorization_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
    arm_token = credential.get_token("https://management.azure.com/.default").token
    ai_token = credential.get_token("https://ai.azure.com/.default").token
    session = requests.Session()
    redirects: set[str] = set()
    try:
        for role in ("requester", "reviewer"):
            connection_name = f"intake-{role}-mcp"
            server_url = _required(f"INTAKE_{role.upper()}_MCP_URL")
            oauth_connection = _upsert_connection(
                session,
                arm_token,
                project_id,
                connection_name,
                {
                    "authType": "OAuth2",
                    "category": "RemoteTool",
                    "target": server_url,
                    "authorizationUrl": authorization_url,
                    "tokenUrl": token_url,
                    "refreshUrl": token_url,
                    "scopes": ["openid", "offline_access", f"{audience}/{scope}"],
                    "credentials": {
                        "clientId": oauth_client_id,
                        "clientSecret": oauth_client_secret,
                    },
                },
            )
            redirects.update(_redirect_values(oauth_connection))
            connection_id = f"{project_id}/connections/{connection_name}"
            _ensure_toolbox(
                session,
                ai_token,
                project_endpoint=project_endpoint,
                name=f"intake-{role}",
                description=f"Intake Agent {role} tools through private delegated MCP",
                connection_id=connection_id,
                connection_name=connection_name,
                server_url=server_url,
            )
            _upsert_connection(
                session,
                arm_token,
                project_id,
                f"intake-{role}-toolbox-agent-identity",
                {
                    "authType": "AgenticIdentityToken",
                    "category": "RemoteTool",
                    "target": (
                        f"{project_endpoint.rstrip('/')}/toolboxes/intake-{role}/mcp"
                        f"?api-version={TOOLBOX_API_VERSION}"
                    ),
                    "audience": "https://ai.azure.com",
                },
            )

        client = AIProjectClient(
            endpoint=project_endpoint,
            credential=credential,
            allow_preview=True,
        )
        agents: list[dict[str, Any]] = []
        try:
            for variant in load_variants():
                version = create_version(
                    client,
                    variant,
                    project_endpoint=project_endpoint,
                    model_deployment=model_deployment,
                )
                configure_endpoint(
                    client,
                    agent_name=variant.agent_name,
                    agent_version=version.version,
                )
                details = client.agents.get(agent_name=variant.agent_name)
                identity = getattr(details, "instance_identity", None)
                agents.append(
                    {
                        "name": variant.agent_name,
                        "version": version.version,
                        "principal_id": getattr(identity, "principal_id", None),
                    }
                )
            for role in ("requester", "reviewer"):
                agent_name = f"intake-{role}-hosted"
                version = client.agents.create_version(
                    agent_name=agent_name,
                    definition=HostedAgentDefinition(
                        protocol_versions=[
                            ProtocolVersionRecord(
                                protocol=AgentEndpointProtocol.RESPONSES,
                                version=HOSTED_PROTOCOL_VERSION,
                            )
                        ],
                        cpu="1",
                        memory="2Gi",
                        container_configuration=ContainerConfiguration(image=hosted_agent_image),
                        environment_variables={
                            "AZURE_AI_MODEL_DEPLOYMENT_NAME": model_deployment,
                            "INTAKE_AGENT_ROLE": role,
                            f"INTAKE_{role.upper()}_TOOLBOX_ENDPOINT": (
                                f"{project_endpoint.rstrip('/')}/toolboxes/"
                                f"intake-{role}/mcp?api-version={TOOLBOX_API_VERSION}"
                            ),
                            f"INTAKE_{role.upper()}_TOOLBOX_NAME": f"intake-{role}",
                        },
                    ),
                    description=(
                        f"Intake Agent {role} Hosted Agent with deterministic Toolbox boundary"
                    ),
                )
                details = _wait_for_hosted_agent(
                    client,
                    agent_name=agent_name,
                    agent_version=version.version,
                )
                configure_endpoint(
                    client,
                    agent_name=agent_name,
                    agent_version=version.version,
                )
                agent_details = client.agents.get(agent_name=agent_name)
                identity = getattr(agent_details, "instance_identity", None)
                agents.append(
                    {
                        "name": agent_name,
                        "version": version.version,
                        "principal_id": getattr(identity, "principal_id", None),
                    }
                )
        finally:
            client.close()
    finally:
        session.close()
        credential.close()

    return {"agents": agents, "oauth_redirect_uris": sorted(redirects)}


def main() -> int:
    print(json.dumps(run(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
