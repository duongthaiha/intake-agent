"""Official MCP Python SDK streamable-HTTP surface for the local profile."""

from intake_agent_contracts import (
    AddReviewCommentRequest,
    DecideReviewRequest,
    GetIntakeContextRequest,
    GetReviewContextRequest,
    ListAssignedReviewsRequest,
    ListMyRequestsRequest,
    RequestChangesRequest,
    SubmitIntakeRequest,
    ToolResponse,
    UpdateFieldRequest,
)
from mcp.server import MCPServer

from intake_mcp.local_profile import LocalProfile

profile = LocalProfile()
mcp = MCPServer("Intake Agent Local", version="1.0.0")


@mcp.tool()
def get_intake_context(request: GetIntakeContextRequest) -> ToolResponse:
    """Create or resume the fixed local requester's authoritative intake context."""
    return profile.get_intake_context(
        request.conversation_key,
        request.template_id,
    )


@mcp.tool()
def update_intake_field(request: UpdateFieldRequest) -> ToolResponse:
    """Validate and atomically autosave one bounded candidate field update."""
    return profile.update_intake_field(
        request.request_id,
        request.expected_revision,
        request.command_id,
        request.field_path,
        request.value,
        request.source_reference,
        request.confidence,
    )


@mcp.tool()
def submit_intake_for_review(request: SubmitIntakeRequest) -> ToolResponse:
    """Submit an explicitly confirmed immutable revision for review."""
    return profile.submit_intake_for_review(
        request.request_id,
        request.expected_revision,
        request.command_id,
        confirmed=request.confirmed,
    )


@mcp.tool()
def list_my_intake_requests(request: ListMyRequestsRequest) -> ToolResponse:
    """List bounded, value-free summaries for the fixed local requester."""
    return profile.list_my_intake_requests(request.limit)


@mcp.tool()
def list_assigned_reviews(request: ListAssignedReviewsRequest) -> ToolResponse:
    """List reviews assigned to the fixed local reviewer."""
    return profile.list_assigned_reviews(request.limit)


@mcp.tool()
def get_review_context(request: GetReviewContextRequest) -> ToolResponse:
    """Load the assigned immutable revision and allowed reviewer actions."""
    return profile.get_review_context(request.request_id)


@mcp.tool()
def add_review_comment(request: AddReviewCommentRequest) -> ToolResponse:
    """Add traceable feedback without editing requester-owned content."""
    return profile.add_review_comment(
        request.request_id,
        request.expected_revision,
        request.command_id,
        request.comment,
    )


@mcp.tool()
def request_intake_changes(request: RequestChangesRequest) -> ToolResponse:
    """Request changes against the exact immutable revision."""
    return profile.request_intake_changes(
        request.request_id,
        request.expected_revision,
        request.command_id,
        request.rationale,
    )


@mcp.tool()
def decide_intake_review(request: DecideReviewRequest) -> ToolResponse:
    """Approve or reject; local approval completes through the handover stub."""
    return profile.decide_intake_review(
        request.request_id,
        request.expected_revision,
        request.command_id,
        request.decision,
        request.rationale,
    )


def main() -> None:
    """Run the local command surface using MCP streamable HTTP."""
    mcp.run(transport="streamable-http", stateless_http=True)


if __name__ == "__main__":
    main()
