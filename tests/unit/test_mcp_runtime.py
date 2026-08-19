"""Unit tests for the prompt-agent MCP application adapter."""

from __future__ import annotations

import pytest

from intake_agent.config import IntakeSettings
from intake_domain.errors import NotFoundError, PreconditionFailedError
from intake_mcp.auth import McpIdentity
from intake_mcp.runtime import build_prompt_runtime

pytestmark = pytest.mark.unit


def _settings() -> IntakeSettings:
    return IntakeSettings(
        environment="local",
        persistence_backend="inmemory",
        servicebus_backend="inmemory",
        blob_backend="inmemory",
    )


def _identity(suffix: str = "1", tenant: str = "tenant-1") -> McpIdentity:
    return McpIdentity(object_id=f"user-{suffix}", tenant_id=tenant)


@pytest.mark.asyncio
async def test_context_requires_explicit_create_or_owned_request_id():
    runtime = build_prompt_runtime(_settings())

    with pytest.raises(PreconditionFailedError, match="request_id is required"):
        await runtime.get_context(_identity(), request_id=None, start_new=False)


@pytest.mark.asyncio
async def test_context_rejects_create_and_select_together():
    runtime = build_prompt_runtime(_settings())

    with pytest.raises(PreconditionFailedError, match="either"):
        await runtime.get_context(
            _identity(),
            request_id="existing",
            start_new=True,
        )


@pytest.mark.asyncio
async def test_prompt_runtime_creates_updates_and_resumes_owned_request():
    runtime = build_prompt_runtime(_settings())
    identity = _identity()

    created = await runtime.get_context(identity, request_id=None, start_new=True)
    updated = await runtime.update_field(
        identity,
        request_id=created["request_id"],
        expected_revision=created["current_revision"],
        field_path="project.name",
        value="Prompt Intake",
        source_reference="turn-1",
        model_confidence=0.98,
    )
    resumed = await runtime.get_context(
        identity,
        request_id=created["request_id"],
        start_new=False,
    )

    assert created["created"] is True
    assert updated["accepted_fields"] == ["project.name"]
    assert resumed["fields"]["project.name"]["value"] == "Prompt Intake"


@pytest.mark.asyncio
async def test_prompt_runtime_enforces_cross_user_and_cross_tenant_isolation():
    runtime = build_prompt_runtime(_settings())
    created = await runtime.get_context(
        _identity("owner"),
        request_id=None,
        start_new=True,
    )

    for identity in (_identity("other"), _identity("owner", tenant="tenant-2")):
        with pytest.raises(NotFoundError, match="Request not found"):
            await runtime.get_context(
                identity,
                request_id=created["request_id"],
                start_new=False,
            )


@pytest.mark.asyncio
async def test_prompt_runtime_lists_only_verified_users_requests():
    runtime = build_prompt_runtime(_settings())
    owner = _identity("owner")
    other = _identity("other")
    created = await runtime.get_context(owner, request_id=None, start_new=True)
    await runtime.get_context(other, request_id=None, start_new=True)

    owner_requests = await runtime.list_requests(owner)

    assert [item["request_id"] for item in owner_requests] == [created["request_id"]]
