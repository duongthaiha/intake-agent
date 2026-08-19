"""End-to-end protocol coverage for the local private MCP service."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from intake_agent.config import IntakeSettings
from intake_mcp.server import build_mcp_app

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _session() -> AsyncIterator[ClientSession]:
    settings = IntakeSettings(environment="local", persistence_backend="inmemory")
    app = build_mcp_app(settings)
    headers = {"Authorization": f"Bearer {settings.mcp_local_dev_token}"}
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    ) as client, streamable_http_client(
        "http://test/mcp",
        http_client=client,
    ) as (read, write, _), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _meta(*, idempotency_key: str | None = None) -> dict[str, str]:
    values = {
        "intake.conversation_id": "mcp-integration-conversation",
        "intake.correlation_id": "mcp-integration-correlation",
        "intake.activity_id": "mcp-integration-activity",
    }
    if idempotency_key is not None:
        values["intake.idempotency_key"] = idempotency_key
    return values


def _structured(result: Any) -> Any:
    assert result.isError is False
    assert result.structuredContent is not None
    return result.structuredContent


@pytest.mark.asyncio
async def test_mcp_discovers_only_requester_tools_and_replays_mutation() -> None:
    async with _session() as session:
        tools = await session.list_tools()
        assert [item.name for item in tools.tools] == [
            "get_intake_context",
            "update_intake_field",
            "submit_intake_for_review",
            "list_my_intake_requests",
        ]

        context = _structured(
            await session.call_tool("get_intake_context", {}, meta=_meta())
        )
        update_arguments = {
            "field_path": "project.name",
            "value": "MCP Intake",
            "expected_revision": context["current_revision"],
            "source_reference": "integration test",
            "model_confidence": 0.99,
        }
        first = _structured(
            await session.call_tool(
                "update_intake_field",
                update_arguments,
                meta=_meta(idempotency_key="stable-operation-1"),
            )
        )
        replay = _structured(
            await session.call_tool(
                "update_intake_field",
                update_arguments,
                meta=_meta(idempotency_key="stable-operation-1"),
            )
        )

        assert first == replay
        assert first["accepted_fields"] == ["project.name"]
        refreshed = _structured(
            await session.call_tool("get_intake_context", {}, meta=_meta())
        )
        assert refreshed["fields"]["project.name"]["value"] == "MCP Intake"
        listed = _structured(
            await session.call_tool("list_my_intake_requests", {}, meta=_meta())
        )
        assert [item["request_id"] for item in listed["result"]] == [
            context["request_id"]
        ]


@pytest.mark.asyncio
async def test_mcp_rejects_missing_bearer_token() -> None:
    settings = IntakeSettings(environment="local", persistence_backend="inmemory")
    app = build_mcp_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )

        assert response.status_code == 401
