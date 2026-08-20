from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from agent_framework import AgentSession, SessionContext
from intake_agent_behavior import (
    build_turn_context,
    plan_oauth_resume,
    render_role_instructions,
    render_turn_instructions,
)
from intake_agent_contracts import (
    AgentRole,
    ConsentChallenge,
    ToolResponse,
    TurnProvenance,
)
from intake_foundry_hosted import ToolboxIntakeContextProvider
from intake_foundry_prompt import build_definition, load_variants

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "foundry"


class FakeToolbox:
    def __init__(self, contexts: list[dict[str, object]]) -> None:
        self.contexts = contexts
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.mutation_response: dict[str, object] | None = None

    async def call_tool(self, tool_name: str, **kwargs: object) -> str:
        request = cast(dict[str, object], kwargs["request"])
        self.calls.append((tool_name, request))
        if tool_name == "get_intake_context":
            payload = self.contexts.pop(0) if len(self.contexts) > 1 else self.contexts[0]
            return json.dumps({"contractVersion": "1.0", "ok": True, "data": payload})
        if self.mutation_response is None:
            raise AssertionError(f"Unexpected fake mutation: {tool_name}")
        return json.dumps(self.mutation_response)


def _provider(fake: FakeToolbox) -> ToolboxIntakeContextProvider:
    return ToolboxIntakeContextProvider(
        fake,
        role=AgentRole.REQUESTER,
        correlation_id_factory=lambda: "correlation-1",
    )


async def _prepare_turn(
    provider: ToolboxIntakeContextProvider,
) -> SessionContext:
    context = SessionContext(session_id="conversation-1", input_messages=[])
    await provider.before_run(
        agent=cast(Any, None),
        session=AgentSession(session_id="conversation-1"),
        context=context,
        state={},
    )
    return context


def _load_json(name: str) -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("scenario", _load_json("shared-contract-scenarios.json"))
async def test_hosted_variant_reloads_context_and_exposes_only_allowed_actions(
    scenario: dict[str, object],
) -> None:
    fake = FakeToolbox([scenario])
    context = await _prepare_turn(_provider(fake))

    assert [call[0] for call in fake.calls] == ["get_intake_context"]
    assert fake.calls[0][1] == {
        "conversationKey": "conversation-1",
        "templateId": "software-request",
    }
    assert {tool.__name__ for tool in context.tools} == set(scenario["allowedActions"])
    assert any('"allowedActions":' in instruction for instruction in context.instructions)


@pytest.mark.parametrize("scenario", _load_json("shared-contract-scenarios.json"))
def test_shared_context_scenario_is_semantically_identical_for_both_variants(
    scenario: dict[str, object],
) -> None:
    response = ToolResponse(ok=True, data=scenario)
    provenance = TurnProvenance(
        conversationKey="conversation-parity",
        correlationId="correlation-parity",
        sourceReference="foundry:conversation-parity:correlation-parity",
    )
    context = build_turn_context(
        response,
        role=AgentRole.REQUESTER,
        provenance=provenance,
    )
    hosted_instructions = render_turn_instructions(context)
    prompt_instructions = render_role_instructions(AgentRole.REQUESTER)

    for required_semantic in (
        "get_intake_context",
        "allowedActions",
        "OAuth consent",
        "concurrency_conflict",
        "correlation",
    ):
        assert required_semantic in f"{hosted_instructions}\n{prompt_instructions}"
    assert tuple(scenario["allowedActions"]) == context.allowed_actions


def test_prompt_variants_use_checked_in_toolboxes_and_shared_behavior() -> None:
    variants = load_variants()
    assert {variant.role for variant in variants} == {
        AgentRole.REQUESTER,
        AgentRole.REVIEWER,
    }
    for variant in variants:
        definition = build_definition(
            variant,
            project_endpoint="https://example.services.ai.azure.com/api/projects/example",
            model_deployment="gpt-4.1",
        )
        assert definition.instructions == render_role_instructions(variant.role)
        tool = definition.tools[0]
        assert tool.project_connection_id == variant.toolbox_connection_name
        assert tool.server_url.endswith(
            f"/toolboxes/{variant.toolbox_name}/mcp?api-version=v1"
        )
        assert tool.require_approval == "never"
        assert set(variant.required_gateway_capabilities) == {
            "reload-context-before-turn",
            "allowed-actions-gate",
            "trusted-provenance-and-correlation",
            "no-automatic-mutation-replay",
        }


@pytest.mark.parametrize("fixture", _load_json("cross-variant-resume.json"))
def test_cross_variant_oauth_resume_preserves_continuation(
    fixture: dict[str, object],
) -> None:
    challenge = ConsentChallenge(
        serverLabel=fixture["serverLabel"],
        consentUrl=fixture["consentUrl"],
    )
    directive = plan_oauth_resume(
        conversation_key=cast(str, fixture["conversationKey"]),
        correlation_id=cast(str, fixture["correlationId"]),
        challenges=(challenge,),
        previous_response_id=cast(str | None, fixture.get("previousResponseId")),
        conversation_id=cast(str | None, fixture.get("conversationId")),
    )

    assert directive.retry_original_turn
    assert directive.conversation_key == fixture["conversationKey"]
    assert directive.correlation_id == fixture["correlationId"]
    assert directive.consent_challenges == (challenge,)


async def test_stale_revision_reloads_once_without_replaying_mutation() -> None:
    revision_one = {
        "requestId": "request-stale",
        "requestRevision": 1,
        "allowedActions": ["update_intake_field"],
        "gaps": [],
    }
    revision_two = {
        "requestId": "request-stale",
        "requestRevision": 2,
        "allowedActions": ["update_intake_field"],
        "gaps": [],
    }
    fake = FakeToolbox([revision_one, revision_two])
    fake.mutation_response = {
        "contractVersion": "1.0",
        "ok": False,
        "error": {
            "code": "concurrency_conflict",
            "message": "The request changed.",
            "latestRevision": 2,
            "retryable": False,
        },
    }
    provider = _provider(fake)
    await _prepare_turn(provider)

    result = await provider.update_intake_field("title", "Updated title", 0.95)

    assert [call[0] for call in fake.calls] == [
        "get_intake_context",
        "update_intake_field",
        "get_intake_context",
    ]
    assert result["latestContext"]["requestRevision"] == 2
    assert "retry" in cast(str, result["agentRecovery"]).lower()


async def test_local_hosted_toolbox_smoke_needs_no_cloud_credential() -> None:
    fake = FakeToolbox(
        [
            {
                "requestId": "request-local",
                "requestRevision": 0,
                "allowedActions": ["list_my_intake_requests"],
                "gaps": [],
            }
        ]
    )
    fake.mutation_response = {
        "contractVersion": "1.0",
        "ok": True,
        "data": {"requests": []},
    }
    provider = _provider(fake)
    context = await _prepare_turn(provider)

    result = await provider.list_my_intake_requests()

    assert result["ok"] is True
    assert {tool.__name__ for tool in context.tools} == {"list_my_intake_requests"}
    assert all("Authorization" not in json.dumps(call) for call in fake.calls)


def test_teams_and_prompt_identity_scripts_use_supported_auth_paths() -> None:
    publish_script = (ROOT / "scripts" / "foundry" / "publish-teams.ps1").read_text(
        encoding="utf-8"
    )
    grant_script = (
        ROOT / "scripts" / "foundry" / "grant-prompt-agent-access.ps1"
    ).read_text(encoding="utf-8")

    assert 'Authorization = "Bearer $token"' in publish_script
    assert "/microsoft365/publish?api-version=v1" in publish_script
    assert '--role "Foundry User"' in grant_script
    assert "--assignee-principal-type ServicePrincipal" in grant_script
