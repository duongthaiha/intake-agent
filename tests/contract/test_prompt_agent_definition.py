"""Contract tests for the declarative Foundry prompt agent."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import intake_mcp.deployment as deployment
from intake_agent.config import IntakeConfigurationError
from intake_mcp.deployment import (
    load_resolved_agent,
    render_eval_config,
    verify_prompt_agent,
)

pytestmark = pytest.mark.contract

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "agents" / "prompt-intake-agent" / "agent.json"


def _environment() -> dict[str, str]:
    return {
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5-nano",
        "INTAKE_MCP_SERVER_URL": "https://prompt-intake-mcp.internal/mcp",
        "INTAKE_MCP_CONNECTION_NAME": "prompt-intake-user",
    }


def test_prompt_agent_definition_is_side_by_side_prompt_agent():
    resolved = load_resolved_agent(MANIFEST, _environment())

    assert resolved.name == "prompt-intake-agent"
    assert resolved.model == "gpt-5-nano"
    assert resolved.definition_payload()["kind"] == "prompt"
    assert resolved.allowed_tools == (
        "get_intake_context",
        "update_intake_field",
        "submit_intake_for_review",
        "list_my_intake_requests",
    )


def test_prompt_agent_instructions_preserve_deterministic_boundaries():
    resolved = load_resolved_agent(MANIFEST, _environment())

    assert "persisted state returned by `get_intake_context`" in resolved.instructions
    assert "Never invent or silently correct field values" in resolved.instructions
    assert "start_new=true" in resolved.instructions
    assert "must not silently create a request" in resolved.instructions
    assert "Reviewer decisions are outside your tools" in resolved.instructions
    assert "Never reveal, repeat, store" in resolved.instructions


def test_prompt_agent_sdk_definition_contains_private_mcp_connection():
    resolved = load_resolved_agent(MANIFEST, _environment())

    definition = resolved.sdk_definition().as_dict()

    assert definition["kind"] == "prompt"
    assert definition["model"] == "gpt-5-nano"
    assert definition["tools"][0]["type"] == "mcp"
    assert definition["tools"][0]["server_url"].startswith("https://")
    assert definition["tools"][0]["project_connection_id"] == "prompt-intake-user"


def test_prompt_agent_definition_hash_is_stable():
    first = load_resolved_agent(MANIFEST, _environment())
    second = load_resolved_agent(MANIFEST, dict(reversed(list(_environment().items()))))

    assert first.definition_hash == second.definition_hash
    assert len(first.definition_hash) == 64


def test_prompt_agent_manifest_rejects_missing_environment():
    with pytest.raises(IntakeConfigurationError, match="Missing prompt agent"):
        load_resolved_agent(MANIFEST, {})


def test_prompt_agent_manifest_and_instructions_are_source_controlled():
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert raw["kind"] == "prompt"
    assert (MANIFEST.parent / raw["instructions_file"]).is_file()


def test_prompt_eval_template_pins_deployed_version(tmp_path: Path):
    output = tmp_path / "eval.prompt.yaml"

    render_eval_config(
        MANIFEST.parent / "eval.yaml.template",
        output,
        "42",
    )

    rendered = output.read_text(encoding="utf-8")
    assert "name: prompt-intake-agent" in rendered
    assert "kind: prompt" in rendered
    assert 'version: "42"' in rendered
    assert "__AGENT_VERSION__" not in rendered


def test_prompt_agent_verification_uses_foundry_data_plane(
    monkeypatch: pytest.MonkeyPatch,
):
    resolved = load_resolved_agent(MANIFEST, _environment())
    connection_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.CognitiveServices/accounts/account/projects/project/"
        "connections/prompt-intake-user"
    )
    deployed = replace(resolved, connection_id=connection_id)
    latest = SimpleNamespace(
        name=resolved.name,
        version="7",
        definition=deployed.sdk_definition(),
        metadata={"definition_hash": deployed.definition_hash},
    )
    fake_agents = SimpleNamespace(
        get=lambda name: SimpleNamespace(versions=SimpleNamespace(latest=latest))
    )
    monkeypatch.setattr(
        deployment,
        "AIProjectClient",
        lambda **kwargs: SimpleNamespace(
            agents=fake_agents,
            connections=SimpleNamespace(
                get=lambda name: SimpleNamespace(id=connection_id)
            ),
        ),
    )

    result = verify_prompt_agent("https://foundry.example/projects/p", resolved)

    assert result["name"] == "prompt-intake-agent"
    assert result["version"] == "7"
    assert result["kind"] == "prompt"
