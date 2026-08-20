"""Strict loader for version-controlled Prompt Agent variants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import cast

from intake_agent_contracts import AgentRole


@dataclass(frozen=True)
class PromptAgentVariant:
    agent_name: str
    description: str
    role: AgentRole
    toolbox_name: str
    toolbox_connection_name: str
    server_label: str
    required_gateway_capabilities: tuple[str, ...]


def load_variants(path: Path | None = None) -> tuple[PromptAgentVariant, ...]:
    """Load checked-in Prompt Agent configuration without resolving credentials."""
    raw = (
        path.read_text(encoding="utf-8")
        if path is not None
        else files("intake_foundry_prompt")
        .joinpath("prompt-agents.json")
        .read_text(encoding="utf-8")
    )
    payload = cast(dict[str, object], json.loads(raw))
    if payload.get("schemaVersion") != "1.0":
        raise ValueError("Unsupported Prompt Agent configuration schema.")
    items = payload.get("agents")
    if not isinstance(items, list):
        raise ValueError("Prompt Agent configuration requires an agents list.")

    variants: list[PromptAgentVariant] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every Prompt Agent configuration must be an object.")
        variants.append(
            PromptAgentVariant(
                agent_name=_required_string(item, "agentName"),
                description=_required_string(item, "description"),
                role=AgentRole(_required_string(item, "role")),
                toolbox_name=_required_string(item, "toolboxName"),
                toolbox_connection_name=_required_string(item, "toolboxConnectionName"),
                server_label=_required_string(item, "serverLabel"),
                required_gateway_capabilities=_required_strings(
                    item,
                    "requiredGatewayCapabilities",
                ),
            )
        )
    return tuple(variants)


def _required_string(item: dict[object, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Prompt Agent configuration requires {key}.")
    return value


def _required_strings(item: dict[object, object], key: str) -> tuple[str, ...]:
    values = item.get(key)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise ValueError(f"Prompt Agent configuration requires non-empty {key}.")
    return tuple(values)
