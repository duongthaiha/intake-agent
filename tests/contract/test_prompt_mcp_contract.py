"""Contract tests for the prompt intake MCP tool surface."""

from __future__ import annotations

import pytest
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from intake_agent.config import IntakeSettings
from intake_mcp.auth import McpIdentity, McpSettings
from intake_mcp.runtime import build_prompt_runtime
from intake_mcp.server import build_http_app, build_mcp_server

pytestmark = pytest.mark.contract


@pytest.mark.asyncio
async def test_prompt_mcp_exposes_only_bounded_requester_tools():
    runtime = build_prompt_runtime(
        IntakeSettings(
            environment="local",
            persistence_backend="inmemory",
            servicebus_backend="inmemory",
            blob_backend="inmemory",
        )
    )
    identity = McpIdentity(object_id="contract-user", tenant_id="contract-tenant")
    server = build_mcp_server(
        runtime_provider=lambda: runtime,
        identity_provider=lambda: identity,
    )

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == [
        "get_intake_context",
        "update_intake_field",
        "submit_intake_for_review",
        "list_my_intake_requests",
    ]
    assert all(
        "review" not in tool.name or tool.name == "submit_intake_for_review"
        for tool in tools
    )


@pytest.mark.asyncio
async def test_prompt_mcp_requires_explicit_request_creation():
    runtime = build_prompt_runtime(
        IntakeSettings(
            environment="local",
            persistence_backend="inmemory",
            servicebus_backend="inmemory",
            blob_backend="inmemory",
        )
    )
    server = build_mcp_server(
        runtime_provider=lambda: runtime,
        identity_provider=lambda: McpIdentity(
            object_id="contract-user",
            tenant_id="contract-tenant",
        ),
    )

    result = await server.call_tool(
        "get_intake_context",
        {"request_id": None, "start_new": True},
    )

    _, structured = result
    assert isinstance(structured, dict)
    assert "request_id" in structured


class _RejectAllTokens:
    async def verify_token(self, token: str) -> AccessToken | None:
        _ = token
        return None


def test_prompt_mcp_http_path_does_not_redirect():
    runtime = build_prompt_runtime(
        IntakeSettings(
            environment="local",
            persistence_backend="inmemory",
            servicebus_backend="inmemory",
            blob_backend="inmemory",
        )
    )
    app = build_http_app(
        runtime_provider=lambda: runtime,
        token_verifier=_RejectAllTokens(),
        settings=McpSettings(
            tenant_id="tenant-1",
            audience="api://prompt-intake-mcp",
            server_url="https://prompt-intake-mcp.internal/mcp",
        ),
    )

    with TestClient(app, follow_redirects=False) as client:
        response = client.post("/mcp", json={})
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 401
    assert metadata.status_code == 200
