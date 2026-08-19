"""Deterministic application adapter for requester tools."""
from __future__ import annotations

from intake_agent.application import IntakeApplication
from intake_agent.requester_tools.contracts import (
    GetIntakeContextRequest,
    ListMyIntakeRequestsRequest,
    OperationContext,
    SubmitIntakeForReviewRequest,
    ToolResult,
    UpdateIntakeFieldRequest,
)


class IntakeToolService:
    """Implements requester operations without depending on any transport SDK."""

    def __init__(self, application: IntakeApplication) -> None:
        self._application = application

    async def get_intake_context(
        self,
        request: GetIntakeContextRequest,
        context: OperationContext,
    ) -> ToolResult:
        _ = request
        actor = context.actor()
        intake = await self._application.get_or_create_request(actor)
        result = await self._application.get_context(str(intake["request_id"]), actor)
        return ToolResult(result)

    async def update_intake_field(
        self,
        request: UpdateIntakeFieldRequest,
        context: OperationContext,
    ) -> ToolResult:
        actor = context.actor()
        intake = await self._application.get_or_create_request(actor)
        result = await self._application.propose_updates(
            request_id=str(intake["request_id"]),
            expected_revision=request.expected_revision,
            updates=[
                {
                    "field_path": request.field_path,
                    "value": request.value,
                    "source_reference": request.source_reference,
                    "model_confidence": request.model_confidence,
                }
            ],
            actor=actor,
            idempotency_key=context.require_idempotency_key(),
        )
        return ToolResult(result)

    async def submit_intake_for_review(
        self,
        request: SubmitIntakeForReviewRequest,
        context: OperationContext,
    ) -> ToolResult:
        actor = context.actor()
        intake = await self._application.get_or_create_request(actor)
        result = await self._application.submit_for_review(
            request_id=str(intake["request_id"]),
            expected_revision=request.expected_revision,
            actor=actor,
            idempotency_key=context.require_idempotency_key(),
        )
        return ToolResult(result)

    async def list_my_intake_requests(
        self,
        request: ListMyIntakeRequestsRequest,
        context: OperationContext,
    ) -> ToolResult:
        _ = request
        return ToolResult(await self._application.list_requests(context.actor()))
