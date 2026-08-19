"""Source-controlled deployment of the Foundry prompt intake agent."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel, ConfigDict

from intake_agent.config import IntakeConfigurationError


class McpToolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    server_label: str
    server_url_env: str
    connection_name_env: str
    require_approval: Literal["always", "never"]
    allowed_tools: list[str]


class PromptAgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    description: str
    model_env: str
    instructions_file: str
    tool: McpToolManifest


@dataclass(frozen=True)
class ResolvedPromptAgent:
    name: str
    description: str
    model: str
    instructions: str
    server_label: str
    server_url: str
    connection_name: str
    require_approval: Literal["always", "never"]
    allowed_tools: tuple[str, ...]
    connection_id: str | None = None

    @property
    def connection_reference(self) -> str:
        return self.connection_id or self.connection_name

    def definition_payload(self) -> dict[str, Any]:
        return {
            "kind": "prompt",
            "model": self.model,
            "instructions": self.instructions,
            "tools": [
                {
                    "type": "mcp",
                    "server_label": self.server_label,
                    "server_url": self.server_url,
                    "project_connection_id": self.connection_reference,
                    "require_approval": self.require_approval,
                    "allowed_tools": list(self.allowed_tools),
                }
            ],
        }

    @property
    def definition_hash(self) -> str:
        encoded = json.dumps(
            {
                "name": self.name,
                "description": self.description,
                "definition": self.definition_payload(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def sdk_definition(self) -> PromptAgentDefinition:
        return PromptAgentDefinition(
            model=self.model,
            instructions=self.instructions,
            tools=[
                MCPTool(
                    server_label=self.server_label,
                    server_url=self.server_url,
                    project_connection_id=self.connection_reference,
                    require_approval=self.require_approval,
                    allowed_tools=list(self.allowed_tools),
                )
            ],
        )


def load_resolved_agent(
    manifest_path: Path,
    environment: dict[str, str] | None = None,
) -> ResolvedPromptAgent:
    values = environment if environment is not None else dict(os.environ)
    manifest = PromptAgentManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.kind != "prompt":
        raise IntakeConfigurationError("Prompt agent manifest kind must be 'prompt'")
    if manifest.tool.type != "mcp":
        raise IntakeConfigurationError("Prompt agent tool type must be 'mcp'")

    required = {
        manifest.model_env: values.get(manifest.model_env, "").strip(),
        manifest.tool.server_url_env: values.get(
            manifest.tool.server_url_env, ""
        ).strip(),
        manifest.tool.connection_name_env: values.get(
            manifest.tool.connection_name_env, ""
        ).strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise IntakeConfigurationError(
            "Missing prompt agent deployment values: " + ", ".join(sorted(missing))
        )

    server_url = required[manifest.tool.server_url_env]
    if not server_url.startswith("https://"):
        raise IntakeConfigurationError("INTAKE_MCP_SERVER_URL must use HTTPS")

    instructions_path = manifest_path.parent / manifest.instructions_file
    instructions = instructions_path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise IntakeConfigurationError("Prompt agent instructions cannot be empty")

    return ResolvedPromptAgent(
        name=manifest.name,
        description=manifest.description,
        model=required[manifest.model_env],
        instructions=instructions,
        server_label=manifest.tool.server_label,
        server_url=server_url,
        connection_name=required[manifest.tool.connection_name_env],
        require_approval=manifest.tool.require_approval,
        allowed_tools=tuple(manifest.tool.allowed_tools),
    )


def deploy_prompt_agent(
    project_endpoint: str,
    agent: ResolvedPromptAgent,
) -> dict[str, Any]:
    project = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )
    connection = project.connections.get(agent.connection_name)
    if not connection.id:
        raise IntakeConfigurationError(
            f"Foundry connection {agent.connection_name!r} has no resource ID"
        )
    resolved = replace(agent, connection_id=connection.id)
    try:
        latest = next(
            iter(
                project.agents.list_versions(
                    resolved.name,
                    limit=1,
                    order="desc",
                )
            ),
            None,
        )
    except ResourceNotFoundError:
        latest = None
    if (
        latest is not None
        and latest.metadata.get("definition_hash") == resolved.definition_hash
    ):
        return {
            "name": latest.name,
            "version": latest.version,
            "definition_hash": resolved.definition_hash,
            "reused": True,
        }

    created = project.agents.create_version(
        agent_name=resolved.name,
        definition=resolved.sdk_definition(),
        description=resolved.description,
        metadata={
            "definition_hash": resolved.definition_hash,
            "managed_by": "intake-agent",
        },
    )
    return {
        "name": created.name,
        "version": created.version,
        "definition_hash": resolved.definition_hash,
        "reused": False,
    }


def verify_prompt_agent(
    project_endpoint: str,
    expected: ResolvedPromptAgent,
) -> dict[str, Any]:
    project = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )
    connection = project.connections.get(expected.connection_name)
    if not connection.id:
        raise IntakeConfigurationError(
            f"Foundry connection {expected.connection_name!r} has no resource ID"
        )
    resolved = replace(expected, connection_id=connection.id)
    agent = project.agents.get(resolved.name)
    latest = agent.versions.latest
    definition = latest.definition.as_dict()
    tools = definition.get("tools")
    if not isinstance(tools, list) or len(tools) != 1:
        raise IntakeConfigurationError(
            "Prompt intake agent must expose exactly one MCP server"
        )
    tool = tools[0]
    if not isinstance(tool, dict):
        raise IntakeConfigurationError("Prompt intake agent tool definition is invalid")

    actual_connection = str(tool.get("project_connection_id") or "")
    connection_matches = actual_connection == resolved.connection_reference
    checks = {
        "kind": definition.get("kind") == "prompt",
        "model": definition.get("model") == resolved.model,
        "instructions": definition.get("instructions") == resolved.instructions,
        "tool_type": tool.get("type") == "mcp",
        "server_url": tool.get("server_url") == resolved.server_url,
        "connection": connection_matches,
        "approval": tool.get("require_approval") == resolved.require_approval,
        "allowed_tools": tool.get("allowed_tools") == list(resolved.allowed_tools),
        "definition_hash": (
            latest.metadata.get("definition_hash") == resolved.definition_hash
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise IntakeConfigurationError(
            "Prompt intake agent verification failed: " + ", ".join(failed)
        )
    return {
        "name": latest.name,
        "version": latest.version,
        "kind": definition["kind"],
        "model": definition["model"],
        "server_url": tool["server_url"],
        "connection": actual_connection,
        "definition_hash": resolved.definition_hash,
    }


def render_eval_config(
    template_path: Path,
    output_path: Path,
    agent_version: str,
) -> None:
    template = template_path.read_text(encoding="utf-8")
    marker = "__AGENT_VERSION__"
    if marker not in template:
        raise IntakeConfigurationError(
            f"Evaluation template {template_path} is missing {marker}"
        )
    output_path.write_text(
        template.replace(marker, agent_version),
        encoding="utf-8",
    )


def run() -> None:
    repository_root = Path(__file__).parents[2]
    manifest_path = repository_root / "agents" / "prompt-intake-agent" / "agent.json"
    project_endpoint = (
        os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
        or os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    )
    if not project_endpoint:
        raise IntakeConfigurationError(
            "AZURE_AI_PROJECT_ENDPOINT or FOUNDRY_PROJECT_ENDPOINT is required"
        )

    result = deploy_prompt_agent(
        project_endpoint,
        load_resolved_agent(manifest_path),
    )
    eval_output = os.getenv("PROMPT_INTAKE_EVAL_OUT", "").strip()
    if eval_output:
        render_eval_config(
            manifest_path.parent / "eval.yaml.template",
            Path(eval_output),
            str(result["version"]),
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    run()
