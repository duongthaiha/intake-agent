"""Application service composition shared by channel adapters."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from intake_domain.commands import (
    ActorPayload,
    CommandEnvelope,
    FieldUpdateItem,
    ProposeFieldUpdatesData,
    RecordReviewDecisionData,
)
from intake_domain.commands.handlers import (
    GetOrCreateRequestHandler,
    GetRequestContextHandler,
    ListRequestsHandler,
    ProposeFieldUpdatesHandler,
    RecordReviewDecisionHandler,
    SubmitForReviewHandler,
)
from intake_domain.entities import ActorContext


class IntakeApplication:
    """Routes authenticated actor commands through the deterministic domain layer."""

    def __init__(
        self,
        request_repo: Any,
        template_repo: Any,
        outbox_repo: Any,
        idempotency_store: Any,
        artifact_store: Any,
        template_id: str = "general-intake-v1",
    ) -> None:
        self._template_id = template_id
        _ = artifact_store
        self._get_or_create = GetOrCreateRequestHandler(request_repo, template_repo)
        self._get_context = GetRequestContextHandler(request_repo, template_repo)
        self._propose_updates = ProposeFieldUpdatesHandler(
            request_repo, template_repo, outbox_repo, idempotency_store
        )
        self._submit = SubmitForReviewHandler(
            request_repo, template_repo, outbox_repo, idempotency_store
        )
        self._review = RecordReviewDecisionHandler(
            request_repo, outbox_repo, idempotency_store
        )
        self._list = ListRequestsHandler(request_repo)

    async def get_or_create_request(self, actor: ActorContext) -> dict[str, Any]:
        return await self._get_or_create.handle(actor, self._template_id)

    async def get_context(
        self,
        request_id: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return await self._get_context.handle(request_id, actor)

    async def propose_updates(
        self,
        request_id: str,
        expected_revision: int,
        updates: list[dict[str, Any]],
        actor: ActorContext,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        envelope = self._envelope(
            command_type="propose_field_updates",
            request_id=request_id,
            expected_revision=expected_revision,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        data = ProposeFieldUpdatesData(
            updates=[FieldUpdateItem(**update) for update in updates]
        )
        return await self._propose_updates.handle(envelope, actor, data)

    async def submit_for_review(
        self,
        request_id: str,
        expected_revision: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        envelope = self._envelope(
            command_type="submit_for_review",
            request_id=request_id,
            expected_revision=expected_revision,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return await self._submit.handle(envelope, actor)

    async def record_review_decision(
        self,
        request_id: str,
        expected_revision: int,
        decision: str,
        rationale: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        envelope = self._envelope(
            command_type="record_review_decision",
            request_id=request_id,
            expected_revision=expected_revision,
            actor=actor,
        )
        data = RecordReviewDecisionData(decision=decision, rationale=rationale)
        return await self._review.handle(envelope, actor, data)

    async def list_requests(self, actor: ActorContext) -> list[dict[str, Any]]:
        return await self._list.handle(actor)

    @staticmethod
    def _envelope(
        *,
        command_type: str,
        request_id: str,
        expected_revision: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
    ) -> CommandEnvelope:
        return CommandEnvelope(
            command_type=command_type,
            request_id=request_id,
            expected_revision=expected_revision,
            correlation_id=actor.correlation_id,
            actor=ActorPayload(
                user_id=actor.user_id,
                tenant_id=actor.tenant_id,
                actor_type="user",
                agent_identity=actor.agent_identity,
            ),
            idempotency_key=idempotency_key or str(uuid4()),
        )
