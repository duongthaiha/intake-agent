"""Local HTTP/CLI adapter for testing the vertical slice without Teams/Foundry.

Demonstrates the full vertical flow:
  create → capture fields → validate → persist → resume → submit → review-ready

Uses in-memory persistence by default (no Azure credentials required).

SECURITY CONTRACT
-----------------
This adapter is a **development-only** channel adapter. It must NEVER be used
in deployed environments (dev/test/prod) because it cannot verify Entra claims.

Role resolution for review decisions:
* Only honoured when ``settings.environment == "local"``.
* The reviewer role is granted only to user IDs explicitly listed in
  ``settings.local_dev_reviewer_ids`` (default: ``reviewer-1,local-reviewer``).
* Any user ID not in that list receives the ``requester`` role and the domain
  handler will reject the review decision with ``AuthorizationDeniedError``.
* In any non-local environment this adapter raises ``AuthorizationDeniedError``
  immediately — no review decision can be recorded without verified Entra claims.

In production the ``FoundryAdapter`` constructs ``ActorContext`` from verified
JWT/OBO claims supplied by Azure Bot Service / Foundry Activity Protocol.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from intake_agent.application import IntakeApplication
from intake_agent.config import IntakeSettings, get_settings
from intake_domain.entities import ActorContext
from intake_domain.errors import AuthorizationDeniedError

logger = logging.getLogger(__name__)


def _resolve_local_dev_actor(user_id: str, settings: IntakeSettings) -> ActorContext:
    """Resolve an ActorContext for local-dev mode.

    SECURITY: Grants reviewer role only to IDs explicitly listed in
    ``settings.local_dev_reviewer_ids``.  Raises ``AuthorizationDeniedError``
    immediately if ``settings.environment != "local"`` so that review decisions
    fail closed in every deployed environment.
    """
    if settings.environment != "local":
        raise AuthorizationDeniedError(
            "Review decisions require verified Entra claims. "
            "LocalAdapter cannot be used for review decisions outside "
            f"local development (current environment: {settings.environment!r}).",
            user_id=user_id,
            environment=settings.environment,
        )

    reviewer_ids: frozenset[str] = frozenset(
        s.strip()
        for s in settings.local_dev_reviewer_ids.split(",")
        if s.strip()
    )
    roles = frozenset(["reviewer"]) if user_id in reviewer_ids else frozenset(["requester"])

    return ActorContext(
        user_id=user_id,
        tenant_id="local-tenant",
        roles=roles,
        conversation_id="local-dev",
        activity_id=str(uuid4()),
        correlation_id=str(uuid4()),
        agent_identity="local-agent",
    )


class LocalAdapter:
    """Development-only channel adapter for the full command pipeline.

    Do NOT deploy to any Azure environment.  The production channel adapter
    (``FoundryAdapter``) builds ``ActorContext`` from verified Entra/OBO claims.
    """

    def __init__(
        self,
        request_repo: Any,
        template_repo: Any,
        outbox_repo: Any,
        idempotency_store: Any,
        artifact_store: Any,
        template_id: str = "general-intake-v1",
        settings: IntakeSettings | None = None,
    ) -> None:
        # Settings are needed for secure local-dev role resolution.
        # Explicit injection is preferred; falls back to the process singleton.
        self._settings = settings if settings is not None else get_settings()
        self._application = IntakeApplication(
            request_repo=request_repo,
            template_repo=template_repo,
            outbox_repo=outbox_repo,
            idempotency_store=idempotency_store,
            artifact_store=artifact_store,
            template_id=template_id,
        )

    def _make_requester_actor(
        self,
        user_id: str = "local-user",
        conversation_id: str = "local-conv-1",
    ) -> ActorContext:
        """Build an actor with the default requester role (no privilege escalation)."""
        return ActorContext(
            user_id=user_id,
            tenant_id="local-tenant",
            roles=frozenset(["requester"]),
            conversation_id=conversation_id,
            activity_id=str(uuid4()),
            correlation_id=str(uuid4()),
            agent_identity="local-agent",
        )

    async def get_or_create_request(
        self,
        user_id: str = "local-user",
        conversation_id: str = "local-conv-1",
    ) -> dict[str, Any]:
        actor = self._make_requester_actor(user_id, conversation_id)
        return await self._application.get_or_create_request(actor)

    async def get_context(
        self,
        request_id: str,
        user_id: str = "local-user",
    ) -> dict[str, Any]:
        actor = self._make_requester_actor(user_id)
        return await self._application.get_context(request_id, actor)

    async def propose_updates(
        self,
        request_id: str,
        expected_revision: int,
        updates: list[dict[str, Any]],
        user_id: str = "local-user",
    ) -> dict[str, Any]:
        actor = self._make_requester_actor(user_id)
        return await self._application.propose_updates(
            request_id=request_id,
            expected_revision=expected_revision,
            updates=updates,
            actor=actor,
        )

    async def submit_for_review(
        self,
        request_id: str,
        expected_revision: int,
        user_id: str = "local-user",
    ) -> dict[str, Any]:
        actor = self._make_requester_actor(user_id)
        return await self._application.submit_for_review(
            request_id=request_id,
            expected_revision=expected_revision,
            actor=actor,
        )

    async def record_review_decision(
        self,
        request_id: str,
        expected_revision: int,
        decision: str,
        rationale: str,
        reviewer_id: str = "local-reviewer",
    ) -> dict[str, Any]:
        """Record a review decision.

        Role resolution is performed against ``settings.local_dev_reviewer_ids``.
        Raises ``AuthorizationDeniedError`` immediately in any non-local environment
        so the production HTTP path fails closed when Entra claims are unavailable.
        """
        actor = _resolve_local_dev_actor(reviewer_id, self._settings)
        return await self._application.record_review_decision(
            request_id=request_id,
            expected_revision=expected_revision,
            decision=decision,
            rationale=rationale,
            actor=actor,
        )

    async def list_requests(self, user_id: str = "local-user") -> list[dict[str, Any]]:
        actor = self._make_requester_actor(user_id)
        return await self._application.list_requests(actor)
