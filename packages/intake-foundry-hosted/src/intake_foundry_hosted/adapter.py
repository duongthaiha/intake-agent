"""Deterministic Toolbox boundary for the Microsoft Agent Framework host."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from agent_framework import (
    AgentSession,
    Content,
    ContextProvider,
    SessionContext,
    SupportsAgentRun,
)
from intake_agent_behavior import (
    build_turn_context,
    conflict_recovery_message,
    render_role_instructions,
    render_turn_instructions,
)
from intake_agent_contracts import (
    AddReviewCommentRequest,
    AgentRole,
    AuthoritativeTurnContext,
    DecideReviewRequest,
    ErrorCode,
    ErrorDetail,
    GetIntakeContextRequest,
    GetReviewContextRequest,
    ListAssignedReviewsRequest,
    ListMyRequestsRequest,
    RequestChangesRequest,
    SubmitIntakeRequest,
    ToolResponse,
    TurnProvenance,
    UpdateFieldRequest,
)


@dataclass(frozen=True)
class _TurnScope:
    conversation_key: str
    correlation_id: str
    source_reference: str
    request_id: str | None
    request_revision: int | None
    allowed_actions: frozenset[str]


class ToolboxClient(Protocol):
    async def call_tool(
        self, tool_name: str, **kwargs: object
    ) -> str | list[Content]: ...


class ToolboxIntakeContextProvider(ContextProvider):
    """Reload authoritative context and expose only guarded role actions per turn."""

    def __init__(
        self,
        toolbox: ToolboxClient,
        *,
        role: AgentRole,
        correlation_id_factory: Callable[[], str],
        template_id: str = "software-request",
    ) -> None:
        super().__init__(source_id=f"intake-{role.value}-context")
        self._toolbox = toolbox
        self._role = role
        self._correlation_id_factory = correlation_id_factory
        self._template_id = template_id
        self._scope: ContextVar[_TurnScope | None] = ContextVar(
            f"intake_{role.value}_turn_scope", default=None
        )

    async def before_run(
        self,
        *,
        agent: SupportsAgentRun,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, object],
    ) -> None:
        del agent, state
        conversation_key = str(
            context.service_session_id or context.session_id or session.session_id
        )
        correlation_id = self._correlation_id_factory()
        provenance = TurnProvenance(
            conversationKey=conversation_key,
            correlationId=correlation_id,
            sourceReference=f"foundry:{conversation_key}:{correlation_id}",
        )

        if self._role is AgentRole.REQUESTER:
            turn = await self._load_requester_context(provenance)
            self._scope.set(
                _TurnScope(
                    conversation_key=conversation_key,
                    correlation_id=correlation_id,
                    source_reference=provenance.source_reference,
                    request_id=turn.request_id,
                    request_revision=turn.request_revision,
                    allowed_actions=frozenset(turn.allowed_actions),
                )
            )
            context.extend_instructions(self.source_id, render_turn_instructions(turn))
            context.extend_tools(
                self.source_id,
                [
                    tool
                    for action, tool in self._requester_tools().items()
                    if action in turn.allowed_actions
                ],
            )
            return

        assigned = await self._call(
            "list_assigned_reviews",
            ListAssignedReviewsRequest().model_dump(mode="json", by_alias=True),
        )
        self._scope.set(
            _TurnScope(
                conversation_key=conversation_key,
                correlation_id=correlation_id,
                source_reference=provenance.source_reference,
                request_id=None,
                request_revision=None,
                allowed_actions=frozenset({"get_review_context"}),
            )
        )
        context.extend_instructions(
            self.source_id,
            "\n".join(
                [
                    render_role_instructions(AgentRole.REVIEWER),
                    "The following assigned-review list is authoritative tool output:",
                    json.dumps(
                        assigned.model_dump(mode="json", by_alias=True),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "Do not present a review action until get_review_context returns it in "
                    "allowedActions.",
                ]
            ),
        )
        context.extend_tools(self.source_id, list(self._reviewer_tools().values()))

    async def update_intake_field(
        self,
        field_path: str,
        value: str,
        confidence: float,
    ) -> dict[str, object]:
        scope = self._require_scope("update_intake_field")
        request = UpdateFieldRequest(
            requestId=self._require_request_id(scope),
            expectedRevision=self._require_revision(scope),
            commandId=self._command_id(
                scope,
                "update_intake_field",
                field_path,
                value,
                str(confidence),
            ),
            fieldPath=field_path,
            value=value,
            sourceReference=scope.source_reference,
            confidence=confidence,
        )
        return await self._mutate("update_intake_field", request.model_dump(by_alias=True))

    async def submit_intake_for_review(self, confirmed: bool) -> dict[str, object]:
        if not confirmed:
            return self._validation_failure("Explicit requester confirmation is required.")
        scope = self._require_scope("submit_intake_for_review")
        request = SubmitIntakeRequest(
            requestId=self._require_request_id(scope),
            expectedRevision=self._require_revision(scope),
            commandId=self._command_id(scope, "submit_intake_for_review", "confirmed"),
            confirmed=True,
        )
        return await self._mutate("submit_intake_for_review", request.model_dump(by_alias=True))

    async def list_my_intake_requests(self, limit: int = 20) -> dict[str, object]:
        self._require_scope("list_my_intake_requests")
        response = await self._call(
            "list_my_intake_requests",
            ListMyRequestsRequest(limit=limit).model_dump(by_alias=True),
        )
        return response.model_dump(mode="json", by_alias=True)

    async def get_review_context(self, request_id: str) -> dict[str, object]:
        scope = self._require_scope("get_review_context")
        response = await self._call(
            "get_review_context",
            GetReviewContextRequest(requestId=request_id).model_dump(by_alias=True),
        )
        provenance = TurnProvenance(
            conversationKey=scope.conversation_key,
            correlationId=scope.correlation_id,
            sourceReference=scope.source_reference,
        )
        turn = build_turn_context(response, role=AgentRole.REVIEWER, provenance=provenance)
        self._scope.set(
            replace(
                scope,
                request_id=turn.request_id,
                request_revision=turn.request_revision,
                allowed_actions=frozenset(turn.allowed_actions) | {"get_review_context"},
            )
        )
        result = response.model_dump(mode="json", by_alias=True)
        result["agentInstructions"] = render_turn_instructions(turn)
        return result

    async def add_review_comment(self, comment: str) -> dict[str, object]:
        scope = self._require_scope("add_review_comment")
        request = AddReviewCommentRequest(
            requestId=self._require_request_id(scope),
            expectedRevision=self._require_revision(scope),
            commandId=self._command_id(scope, "add_review_comment", comment),
            comment=comment,
        )
        return await self._mutate("add_review_comment", request.model_dump(by_alias=True))

    async def request_intake_changes(self, rationale: str) -> dict[str, object]:
        scope = self._require_scope("request_intake_changes")
        request = RequestChangesRequest(
            requestId=self._require_request_id(scope),
            expectedRevision=self._require_revision(scope),
            commandId=self._command_id(scope, "request_intake_changes", rationale),
            rationale=rationale,
        )
        return await self._mutate("request_intake_changes", request.model_dump(by_alias=True))

    async def decide_intake_review(
        self,
        decision: Literal["approve", "reject"],
        rationale: str,
    ) -> dict[str, object]:
        scope = self._require_scope("decide_intake_review")
        request = DecideReviewRequest(
            requestId=self._require_request_id(scope),
            expectedRevision=self._require_revision(scope),
            commandId=self._command_id(scope, "decide_intake_review", decision, rationale),
            decision=decision,
            rationale=rationale,
        )
        return await self._mutate("decide_intake_review", request.model_dump(by_alias=True))

    async def _load_requester_context(
        self, provenance: TurnProvenance
    ) -> AuthoritativeTurnContext:
        response = await self._call(
            "get_intake_context",
            GetIntakeContextRequest(
                conversationKey=provenance.conversation_key,
                templateId=self._template_id,
            ).model_dump(by_alias=True),
        )
        return build_turn_context(response, role=AgentRole.REQUESTER, provenance=provenance)

    async def _mutate(self, action: str, request: dict[str, object]) -> dict[str, object]:
        scope = self._require_scope(action)
        response = await self._call(action, request)
        recovery = conflict_recovery_message(response)
        if recovery is not None:
            latest = await self._reload_scope(scope)
            result = response.model_dump(mode="json", by_alias=True)
            result["agentRecovery"] = recovery
            result["latestContext"] = latest.model_dump(mode="json", by_alias=True)
            return result

        if response.ok and response.data is not None:
            self._refresh_scope_from_data(scope, response)
        return response.model_dump(mode="json", by_alias=True)

    async def _reload_scope(self, scope: _TurnScope) -> AuthoritativeTurnContext:
        provenance = TurnProvenance(
            conversationKey=scope.conversation_key,
            correlationId=scope.correlation_id,
            sourceReference=scope.source_reference,
        )
        if self._role is AgentRole.REQUESTER:
            turn = await self._load_requester_context(provenance)
        else:
            response = await self._call(
                "get_review_context",
                GetReviewContextRequest(
                    requestId=self._require_request_id(scope)
                ).model_dump(by_alias=True),
            )
            turn = build_turn_context(response, role=AgentRole.REVIEWER, provenance=provenance)
        self._scope.set(
            replace(
                scope,
                request_id=turn.request_id,
                request_revision=turn.request_revision,
                allowed_actions=frozenset(turn.allowed_actions),
            )
        )
        return turn

    def _refresh_scope_from_data(self, scope: _TurnScope, response: ToolResponse) -> None:
        data = response.data
        if data is None:
            return
        if all(key in data for key in ("requestId", "requestRevision", "allowedActions")):
            turn = build_turn_context(
                response,
                role=self._role,
                provenance=TurnProvenance(
                    conversationKey=scope.conversation_key,
                    correlationId=scope.correlation_id,
                    sourceReference=scope.source_reference,
                ),
            )
            self._scope.set(
                replace(
                    scope,
                    request_id=turn.request_id,
                    request_revision=turn.request_revision,
                    allowed_actions=frozenset(turn.allowed_actions),
                )
            )

    async def _call(self, tool_name: str, request: dict[str, object]) -> ToolResponse:
        result = await self._toolbox.call_tool(tool_name, request=request)
        return _parse_tool_response(result)

    def _requester_tools(self) -> dict[str, object]:
        return {
            "update_intake_field": self.update_intake_field,
            "submit_intake_for_review": self.submit_intake_for_review,
            "list_my_intake_requests": self.list_my_intake_requests,
        }

    def _reviewer_tools(self) -> dict[str, object]:
        return {
            "get_review_context": self.get_review_context,
            "add_review_comment": self.add_review_comment,
            "request_intake_changes": self.request_intake_changes,
            "decide_intake_review": self.decide_intake_review,
        }

    def _require_scope(self, action: str) -> _TurnScope:
        scope = self._scope.get()
        if scope is None:
            raise RuntimeError("No authoritative Intake Agent turn context is active.")
        if action not in scope.allowed_actions:
            raise RuntimeError(f"Action {action!r} is not allowed by the latest context.")
        return scope

    @staticmethod
    def _require_request_id(scope: _TurnScope) -> str:
        if scope.request_id is None:
            raise RuntimeError("Load authoritative request context before taking this action.")
        return scope.request_id

    @staticmethod
    def _require_revision(scope: _TurnScope) -> int:
        if scope.request_revision is None:
            raise RuntimeError("Load authoritative request context before taking this action.")
        return scope.request_revision

    @staticmethod
    def _command_id(scope: _TurnScope, action: str, *values: str) -> str:
        payload = json.dumps(
            [scope.correlation_id, action, *values],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:40]

    @staticmethod
    def _validation_failure(message: str) -> dict[str, object]:
        return ToolResponse(
            ok=False,
            error=ErrorDetail(
                code=ErrorCode.VALIDATION_FAILED,
                message=message,
            ),
        ).model_dump(mode="json", by_alias=True)


def _parse_tool_response(result: str | list[Content]) -> ToolResponse:
    candidates: list[str] = [result] if isinstance(result, str) else []
    if not isinstance(result, str):
        candidates.extend(content.text for content in result if content.text is not None)
    for candidate in reversed(candidates):
        try:
            return ToolResponse.model_validate_json(candidate)
        except ValueError:
            continue
    raise ValueError("Toolbox returned no valid Intake Agent ToolResponse.")
