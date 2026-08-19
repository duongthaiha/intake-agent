"""Command handlers for the intake domain.

Each handler:
- Receives typed command data + ActorContext
- Checks idempotency (replay if already processed)
- Validates preconditions
- Applies domain logic
- Persists via repository protocols
- Emits domain events to the outbox
"""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from intake_domain.commands import (
    CommandEnvelope,
    ProposeFieldUpdatesData,
    RecordReviewDecisionData,
)
from intake_domain.entities import (
    ActorContext,
    ActorType,
    FieldValue,
    Gap,
    GapStatus,
    OutboxItem,
    Request,
    RequestRevision,
    RequestStatus,
    ReviewDecision,
    TemplateVersion,
    ValidationStatus,
    WorkflowEvent,
)
from intake_domain.errors import (
    AuthorizationDeniedError,
    NotFoundError,
    PreconditionFailedError,
    ValidationError,
)
from intake_domain.events import EventActorPayload, EventEnvelope
from intake_domain.repositories import (
    IdempotencyStore,
    OutboxRepository,
    RequestRepository,
    TemplateRepository,
)
from intake_domain.services import GapDetectionService, LifecycleService, ValidationService

logger = logging.getLogger(__name__)


def _derive_request_id(tenant_id: str, conversation_id: str) -> str:
    raw = f"{tenant_id}:{conversation_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _now() -> datetime:
    return datetime.now(UTC)


_SYSTEM_ACTOR = ActorContext(
    user_id="system",
    tenant_id="system",
    roles=frozenset(),
    conversation_id="system",
    activity_id="system",
    correlation_id="system",
    agent_identity="system",
)


def _resolve_actor(actor: ActorContext | None) -> ActorContext:
    return actor if actor is not None else _SYSTEM_ACTOR


def _assert_request_access(
    request: Request,
    actor: ActorContext,
    *,
    allow_reviewer: bool = False,
) -> None:
    """Hide requests outside the caller's tenant and authorization scope."""
    same_tenant = request.tenant_id == actor.tenant_id
    owns_request = request.requester_id == actor.user_id
    can_review = allow_reviewer and bool({"reviewer", "admin"} & actor.roles)
    if not same_tenant or not (owns_request or can_review):
        raise NotFoundError("Request not found", request_id=request.request_id)


def _make_event(
    event_type: str,
    envelope: CommandEnvelope,
    revision: int,
    actor: ActorContext,
    prior_state: RequestStatus | None,
    new_state: RequestStatus | None,
    data: dict[str, Any],
) -> tuple[EventEnvelope, WorkflowEvent]:
    event_id = str(uuid4())
    now = _now()
    ev = EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        request_id=envelope.request_id,
        revision=revision,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.command_id,
        occurred_at=now,
        actor=EventActorPayload(
            user_id=actor.user_id,
            actor_type="agent" if "agent" in actor.roles else "user",
        ),
        data=data,
    )
    wf = WorkflowEvent(
        event_id=event_id,
        request_id=envelope.request_id,
        revision=revision,
        actor_id=actor.user_id,
        actor_type=ActorType.AGENT if "agent" in actor.roles else ActorType.USER,
        command_id=envelope.command_id,
        prior_state=prior_state,
        new_state=new_state,
        occurred_at=now,
        event_type=event_type,
        correlation_id=envelope.correlation_id,
        data=data,
    )
    return ev, wf


# ---------------------------------------------------------------------------
# GetOrCreateRequestHandler
# ---------------------------------------------------------------------------

class GetOrCreateRequestHandler:
    def __init__(
        self,
        request_repo: RequestRepository,
        template_repo: TemplateRepository,
    ) -> None:
        self._request_repo = request_repo
        self._template_repo = template_repo

    async def handle(
        self,
        actor: ActorContext,
        template_id: str,
        template_version: str | None = None,
    ) -> dict[str, Any]:
        request_id = _derive_request_id(actor.tenant_id, actor.conversation_id)

        # Load template
        template: TemplateVersion | None
        if template_version:
            template = await self._template_repo.get_version(template_id, template_version)
        else:
            template = await self._template_repo.get_active(template_id)
        if template is None:
            raise NotFoundError(
                f"Template {template_id!r} not found",
                template_id=template_id,
            )

        now = _now()

        def factory() -> Request:
            return Request(
                request_id=request_id,
                tenant_id=actor.tenant_id,
                conversation_id=actor.conversation_id,
                requester_id=actor.user_id,
                status=RequestStatus.NEW,
                current_revision=1,
                template_id=template_id,
                template_version=template.version,
                created_at=now,
                updated_at=now,
                etag="",
            )

        request, created = await self._request_repo.get_or_create(request_id, factory)
        _assert_request_access(request, actor)

        revision = await self._request_repo.get_current_revision(request_id)
        if revision is None:
            revision = RequestRevision(
                request_id=request_id,
                revision=request.current_revision,
                template_version=template.version,
                created_at=now,
            )

        logger.info(
            "get_or_create_request %s created=%s status=%s",
            request_id, created, request.status.value,
            extra={"correlation_id": actor.correlation_id},
        )
        return {
            "request_id": request_id,
            "created": created,
            "status": request.status.value,
            "current_revision": request.current_revision,
            "template_id": template_id,
            "template_version": template.version,
        }


# ---------------------------------------------------------------------------
# GetRequestContextHandler
# ---------------------------------------------------------------------------

class GetRequestContextHandler:
    def __init__(
        self,
        request_repo: RequestRepository,
        template_repo: TemplateRepository,
    ) -> None:
        self._request_repo = request_repo
        self._template_repo = template_repo
        self._lifecycle = LifecycleService()
        self._gap_svc = GapDetectionService()

    async def handle(self, request_id: str, actor: ActorContext) -> dict[str, Any]:
        request = await self._request_repo.get(request_id)
        if request is None:
            raise NotFoundError("Request not found", request_id=request_id)
        _assert_request_access(request, actor, allow_reviewer=True)

        revision = await self._request_repo.get_current_revision(request_id)
        template = await self._template_repo.get_version(
            request.template_id, request.template_version
        )

        gaps = revision.gaps if revision else []
        quality_score = (
            self._gap_svc.compute_quality_score(template, revision)
            if template and revision
            else None
        )

        allowed_actions = self._lifecycle.allowed_actions(request.status, actor.roles)
        blocking_gaps = [
            g for g in gaps if g.severity.value == "blocking" and g.status.value == "open"
        ]

        return {
            "request_id": request_id,
            "status": request.status.value,
            "current_revision": request.current_revision,
            "template_id": request.template_id,
            "fields": {
                k: {
                    "value": v.value,
                    "validation_status": v.validation_status.value,
                    "model_confidence": v.model_confidence,
                }
                for k, v in (revision.fields.items() if revision else {})
            },
            "gaps": [
                {
                    "gap_id": g.gap_id,
                    "field_path": g.field_path,
                    "category": g.category.value,
                    "severity": g.severity.value,
                    "status": g.status.value,
                    "message": g.message,
                }
                for g in gaps
            ],
            "blocking_gaps_count": len(blocking_gaps),
            "quality_score": quality_score,
            "allowed_actions": allowed_actions,
            "can_submit": (
                len(blocking_gaps) == 0
                and request.status in {RequestStatus.NEW, RequestStatus.AWAITING_FEEDBACK}
                and quality_score is not None
                and (template is None or quality_score >= template.quality_threshold)
            ),
        }


# ---------------------------------------------------------------------------
# ProposeFieldUpdatesHandler
# ---------------------------------------------------------------------------

class ProposeFieldUpdatesHandler:
    def __init__(
        self,
        request_repo: RequestRepository,
        template_repo: TemplateRepository,
        outbox_repo: OutboxRepository,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._request_repo = request_repo
        self._template_repo = template_repo
        self._outbox_repo = outbox_repo
        self._idempotency_store = idempotency_store
        self._lifecycle = LifecycleService()
        self._validation = ValidationService()
        self._gap_svc = GapDetectionService()

    async def handle(
        self,
        envelope: CommandEnvelope,
        actor: ActorContext | None,
        data: ProposeFieldUpdatesData,
    ) -> dict[str, Any]:
        actor = _resolve_actor(actor)
        request = await self._request_repo.get(envelope.request_id)
        if request is None:
            raise NotFoundError("Request not found", request_id=envelope.request_id)
        _assert_request_access(request, actor)

        # Authorization precedes replay lookup so stored results cannot leak.
        stored = await self._idempotency_store.check(
            envelope.request_id, envelope.idempotency_key
        )
        if stored is not None:
            logger.info("idempotent replay %s", envelope.command_id)
            return cast(dict[str, Any], stored.result)

        # Optimistic concurrency
        if request.current_revision != envelope.expected_revision:
            from intake_domain.errors import ConflictError
            raise ConflictError(
                (f"Revision mismatch: expected {envelope.expected_revision}"
                 f" got {request.current_revision}"),
                current_revision=request.current_revision,
                current_etag=request.etag,
            )

        self._lifecycle.assert_mutable(request.status)

        template = await self._template_repo.get_version(
            request.template_id, request.template_version
        )
        if template is None:
            raise NotFoundError("Template version not found")

        revision = await self._request_repo.get_current_revision(envelope.request_id)
        if revision is None:
            revision = RequestRevision(
                request_id=envelope.request_id,
                revision=request.current_revision,
                template_version=request.template_version,
            )

        # Validate
        validation_results = self._validation.validate_updates(
            template, [(u.field_path, u.value) for u in data.updates]
        )

        accepted_fields: list[str] = []
        rejected_fields: list[dict[str, str]] = []

        for update in data.updates:
            status, msg = validation_results[update.field_path]
            if status == ValidationStatus.INVALID:
                rejected_fields.append(
                    {
                        "field_path": update.field_path,
                        "error_code": "INVALID_TYPE",
                        "message": msg,
                    }
                )
            else:
                revision.fields[update.field_path] = FieldValue(
                    field_path=update.field_path,
                    value=update.value,
                    source_reference=update.source_reference,
                    model_confidence=update.model_confidence,
                    validation_status=ValidationStatus.VALID,
                )
                accepted_fields.append(update.field_path)

        # Re-detect gaps
        new_gaps_all = self._gap_svc.detect_gaps(template, revision)
        existing_gap_ids = {g.gap_id for g in revision.gaps}

        resolved_gap_ids: list[str] = []
        # Mark gaps resolved for accepted fields
        for g in revision.gaps:
            if g.field_path in accepted_fields and g.status == GapStatus.OPEN:
                g.status = GapStatus.RESOLVED
                resolved_gap_ids.append(g.gap_id)

        # Add genuinely new gaps
        new_gap_objects: list[Gap] = []
        for ng in new_gaps_all:
            if ng.gap_id not in existing_gap_ids:
                revision.gaps.append(ng)
                new_gap_objects.append(ng)

        # Update request
        new_revision_num = request.current_revision + 1
        revision.revision = new_revision_num
        revision.created_at = _now()
        request.current_revision = new_revision_num
        request.updated_at = _now()

        # Build audit event
        event, wf_event = _make_event(
            "RequestFieldsUpdated",
            envelope,
            new_revision_num,
            actor,
            request.status,
            request.status,
            {
                "accepted_fields": accepted_fields,
                "resolved_gaps": resolved_gap_ids,
                "new_gaps": [g.gap_id for g in new_gap_objects],
            },
        )

        new_etag = await self._request_repo.save(
            request, revision, [wf_event], request.etag
        )
        request.etag = new_etag

        if not getattr(self._request_repo, "persists_outbox_atomically", True):
            await self._outbox_repo.enqueue(
                OutboxItem(
                    item_id=event.event_id,
                    request_id=envelope.request_id,
                    event_type="RequestFieldsUpdated",
                    payload=event.model_dump(mode="json"),
                    created_at=_now(),
                )
            )

        result: dict[str, Any] = {
            "status": "accepted" if not rejected_fields else "partial",
            "revision": new_revision_num,
            "accepted_fields": accepted_fields,
            "rejected_fields": rejected_fields,
            "new_gaps": [
                {
                    "gap_id": g.gap_id,
                    "field_path": g.field_path,
                    "category": g.category.value,
                    "severity": g.severity.value,
                }
                for g in new_gap_objects
            ],
            "resolved_gaps": resolved_gap_ids,
        }

        await self._idempotency_store.store(
            envelope.request_id, envelope.idempotency_key, result
        )

        logger.info(
            "propose_field_updates %s rev=%s accepted=%d rejected=%d",
            envelope.request_id, new_revision_num,
            len(accepted_fields), len(rejected_fields),
            extra={"correlation_id": envelope.correlation_id},
        )
        return result


# ---------------------------------------------------------------------------
# SubmitForReviewHandler
# ---------------------------------------------------------------------------

class SubmitForReviewHandler:
    def __init__(
        self,
        request_repo: RequestRepository,
        template_repo: TemplateRepository,
        outbox_repo: OutboxRepository,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._request_repo = request_repo
        self._template_repo = template_repo
        self._outbox_repo = outbox_repo
        self._idempotency_store = idempotency_store
        self._lifecycle = LifecycleService()
        self._gap_svc = GapDetectionService()

    async def handle(
        self,
        envelope: CommandEnvelope,
        actor: ActorContext | None,
    ) -> dict[str, Any]:
        actor = _resolve_actor(actor)
        request = await self._request_repo.get(envelope.request_id)
        if request is None:
            raise NotFoundError("Request not found", request_id=envelope.request_id)
        _assert_request_access(request, actor)

        stored = await self._idempotency_store.check(
            envelope.request_id, envelope.idempotency_key
        )
        if stored is not None:
            return cast(dict[str, Any], stored.result)

        if request.current_revision != envelope.expected_revision:
            from intake_domain.errors import ConflictError
            raise ConflictError(
                (f"Revision mismatch: expected {envelope.expected_revision}"
                 f" got {request.current_revision}"),
                current_revision=request.current_revision,
                current_etag=request.etag,
            )

        self._lifecycle.assert_transition(
            request.status, RequestStatus.IN_REVIEW, actor
        )

        revision = await self._request_repo.get_current_revision(envelope.request_id)
        template = await self._template_repo.get_version(
            request.template_id, request.template_version
        )

        if revision and template:
            if self._gap_svc.has_blocking_gaps(revision.gaps):
                raise PreconditionFailedError(
                    "Cannot submit: blocking gaps remain open",
                    blocking_gaps=[
                        g.gap_id
                        for g in revision.gaps
                        if g.severity.value == "blocking" and g.status.value == "open"
                    ],
                )
            quality = self._gap_svc.compute_quality_score(template, revision)
            if quality < template.quality_threshold:
                raise PreconditionFailedError(
                    f"Quality score {quality:.2f} below threshold {template.quality_threshold}",
                    quality_score=quality,
                    threshold=template.quality_threshold,
                )

        prior_status = request.status
        request.status = RequestStatus.IN_REVIEW
        request.updated_at = _now()

        if revision:
            revision.immutable = True

        quality_score = (
            self._gap_svc.compute_quality_score(template, revision)
            if template and revision
            else None
        )

        event, wf_event = _make_event(
            "RequestSubmitted",
            envelope,
            request.current_revision,
            actor,
            prior_status,
            RequestStatus.IN_REVIEW,
            {"revision": request.current_revision, "quality_score": quality_score},
        )

        new_etag = await self._request_repo.save(
            request,
            revision or RequestRevision(
                request_id=envelope.request_id,
                revision=request.current_revision,
            ),
            [wf_event],
            request.etag,
        )
        request.etag = new_etag

        if not getattr(self._request_repo, "persists_outbox_atomically", True):
            await self._outbox_repo.enqueue(
                OutboxItem(
                    item_id=event.event_id,
                    request_id=envelope.request_id,
                    event_type="RequestSubmitted",
                    payload=event.model_dump(mode="json"),
                    created_at=_now(),
                )
            )

        result: dict[str, Any] = {
            "status": "submitted",
            "revision": request.current_revision,
            "new_status": request.status.value,
        }

        await self._idempotency_store.store(
            envelope.request_id, envelope.idempotency_key, result
        )

        logger.info(
            "submit_for_review %s rev=%s",
            envelope.request_id, request.current_revision,
            extra={"correlation_id": envelope.correlation_id},
        )
        return result


# ---------------------------------------------------------------------------
# RecordReviewDecisionHandler
# ---------------------------------------------------------------------------

class RecordReviewDecisionHandler:
    def __init__(
        self,
        request_repo: RequestRepository,
        outbox_repo: OutboxRepository,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._request_repo = request_repo
        self._outbox_repo = outbox_repo
        self._idempotency_store = idempotency_store
        self._lifecycle = LifecycleService()

    async def handle(
        self,
        envelope: CommandEnvelope,
        actor: ActorContext | None,
        data: RecordReviewDecisionData,
    ) -> dict[str, Any]:
        actor = _resolve_actor(actor)
        request = await self._request_repo.get(envelope.request_id)
        if request is None:
            raise NotFoundError("Request not found", request_id=envelope.request_id)
        _assert_request_access(request, actor, allow_reviewer=True)

        if "reviewer" not in actor.roles and "admin" not in actor.roles:
            raise AuthorizationDeniedError(
                "Only reviewers or admins can record review decisions",
                user_id=actor.user_id,
            )

        stored = await self._idempotency_store.check(
            envelope.request_id, envelope.idempotency_key
        )
        if stored is not None:
            return cast(dict[str, Any], stored.result)

        try:
            decision = ReviewDecision(data.decision)
        except ValueError as exc:
            raise ValidationError(
                f"Unknown decision {data.decision!r}",
                allowed=list(ReviewDecision),
            ) from exc

        target_map = {
            ReviewDecision.APPROVE: RequestStatus.APPROVED,
            ReviewDecision.REJECT: RequestStatus.REJECTED,
            ReviewDecision.REQUEST_CHANGES: RequestStatus.AWAITING_FEEDBACK,
        }
        target_status = target_map[decision]
        self._lifecycle.assert_transition(request.status, target_status, actor)

        prior_status = request.status
        request.status = target_status
        request.updated_at = _now()

        event_type_map = {
            ReviewDecision.APPROVE: "RequestApproved",
            ReviewDecision.REJECT: "RequestRejected",
            ReviewDecision.REQUEST_CHANGES: "ChangesRequested",
        }

        revision = await self._request_repo.get_current_revision(envelope.request_id)

        event, wf_event = _make_event(
            event_type_map[decision],
            envelope,
            request.current_revision,
            actor,
            prior_status,
            target_status,
            {"reviewer_id": actor.user_id, "rationale": data.rationale},
        )

        new_etag = await self._request_repo.save(
            request,
            revision or RequestRevision(
                request_id=envelope.request_id,
                revision=request.current_revision,
            ),
            [wf_event],
            request.etag,
        )
        request.etag = new_etag

        if not getattr(self._request_repo, "persists_outbox_atomically", True):
            await self._outbox_repo.enqueue(
                OutboxItem(
                    item_id=event.event_id,
                    request_id=envelope.request_id,
                    event_type=event_type_map[decision],
                    payload=event.model_dump(mode="json"),
                    created_at=_now(),
                )
            )

        result: dict[str, Any] = {
            "status": "recorded",
            "decision": data.decision,
            "new_status": request.status.value,
            "revision": request.current_revision,
        }

        await self._idempotency_store.store(
            envelope.request_id, envelope.idempotency_key, result
        )

        logger.info(
            "record_review_decision %s decision=%s new_status=%s",
            envelope.request_id, data.decision, request.status.value,
            extra={"correlation_id": envelope.correlation_id},
        )
        return result


# ---------------------------------------------------------------------------
# ListRequestsHandler
# ---------------------------------------------------------------------------

class ListRequestsHandler:
    def __init__(self, request_repo: RequestRepository) -> None:
        self._request_repo = request_repo

    async def handle(self, actor: ActorContext) -> list[dict[str, Any]]:
        requests = await self._request_repo.list_by_user(actor.user_id, actor.tenant_id)
        return [
            {
                "request_id": r.request_id,
                "status": r.status.value,
                "current_revision": r.current_revision,
                "template_id": r.template_id,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in requests
        ]
