import pytest
from intake_mcp.server import mcp, profile
from mcp.server.mcpserver.exceptions import ToolError


@pytest.mark.asyncio
async def test_mcp_v2_surface_exposes_only_versioned_user_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "get_intake_context",
        "update_intake_field",
        "submit_intake_for_review",
        "list_my_intake_requests",
        "list_assigned_reviews",
        "get_review_context",
        "add_review_comment",
        "request_intake_changes",
        "decide_intake_review",
    }
    for tool in tools:
        request_schema = tool.input_schema["properties"]["request"]
        definition_name = request_schema["$ref"].rsplit("/", 1)[-1]
        properties = tool.input_schema["$defs"][definition_name]["properties"]
        assert "actor_id" not in properties
        assert "tenant_id" not in properties
        assert "roles" not in properties
        assert "credential" not in properties

    result = await mcp.call_tool(
        "get_intake_context",
        {
            "request": {
                "conversationKey": "mcp-contract",
                "templateId": "software-request",
            }
        },
    )
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["ok"] is True

    with pytest.raises(ToolError, match="Extra inputs are not permitted"):
        await mcp.call_tool(
            "get_intake_context",
            {
                "request": {
                    "conversationKey": "mcp-contract",
                    "tenantId": "model-controlled",
                }
            },
        )
    profile.reset()
