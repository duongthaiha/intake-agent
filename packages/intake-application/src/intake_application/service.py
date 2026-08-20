"""Application commands and queries composed over domain policies and ports."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from intake_domain import (
    ActorContext,
    ActorRole,
    DeliveryStatus,
    DomainError,
    ErrorCode,
    IntakeRequest,
    Mutation,
    PendingEvent,
    RequestStatus,
    RequestStore,
    ReviewComment,
    ReviewDecision,
    TemplateVersion,
    allowed_actions,
    authorize_owner,
    authorize_reviewer,
    build_revision,
    evaluate_request,
    validate_candidate,
    validate_transition,
)


@dataclass(frozen=True, slots=True)
class Outcome:
    ok: bool
    data: dict[str, Any] | None = None
    error: DomainError | None = None
    replayed: bool = False


class IntakeService:
    """Coordinates deterministic policies and atomic persistence operations."""

    def __init__(
        self,
        store: RequestStore,
        templates: Mapping[str, TemplateVersion],
        default_reviewer_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._templates = dict(templates)
        self._default_reviewer_id = default_reviewer_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_intake_context(
        self,
        actor: ActorContext,
        conversation_key: str,
        template_id: str = "software-request",
    ) -> Outcome:
        return self._capture(
            lambda: self._get_intake_context(actor, conversation_key, template_id)
        )

    def update_intake_field(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        field_path: str,
        value: str,
        source_reference: str,
        confidence: float,
    ) -> Outcome:
        def execute() -> Outcome:
            authorize_owner(actor, self._required(request_id))
            fingerprint = _fingerprint(
                "update",
                request_id,
                expected_revision,
                field_path,
                value,
                source_reference,
                confidence,
            )

            def operation(request: IntakeRequest) -> Mutation:
                authorize_owner(actor, request)
                if request.status not in {
                    RequestStatus.NEW,
                    RequestStatus.AWAITING_USER_FEEDBACK,
                }:
                    raise DomainError(
                        ErrorCode.INVALID_TRANSITION,
                        "Fields can only be edited in a draft or feedback revision.",
                    )
                field_value = validate_candidate(
                    request.template,
                    field_path,
                    value,
                    source_reference,
                    confidence,
                    actor.actor_id,
                    self._clock(),
                )
                request.fields[field_path] = field_value
                if field_value.validation_status.value == "needs_clarification":
                    request.clarification_attempts[field_path] = (
                        request.clarification_attempts.get(field_path, 0) + 1
                    )
                gaps, quality = evaluate_request(request)
                return Mutation(
                    data={
                        "acceptedField": _field_data(field_value),
                        "gaps": [_gap_data(gap) for gap in gaps],
                        "qualityScore": quality,
                    },
                    events=(
                        PendingEvent(
                            "RequestFieldsUpdated",
                            {"fieldPaths": [field_path], "qualityScore": quality},
                        ),
                    ),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                fingerprint,
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def submit_intake_for_review(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        *,
        confirmed: bool,
    ) -> Outcome:
        def execute() -> Outcome:
            authorize_owner(actor, self._required(request_id))
            if not confirmed:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "Explicit requester confirmation is required before submission.",
                )

            def operation(request: IntakeRequest) -> Mutation:
                authorize_owner(actor, request)
                if request.status not in {
                    RequestStatus.NEW,
                    RequestStatus.AWAITING_USER_FEEDBACK,
                }:
                    raise DomainError(
                        ErrorCode.INVALID_TRANSITION,
                        "Only an editable request can be submitted.",
                    )
                validate_transition(request.status, RequestStatus.IN_REVIEW)
                revision = build_revision(request, actor, self._clock())
                request.revisions.append(revision)
                request.status = RequestStatus.IN_REVIEW
                return Mutation(
                    data={
                        "status": request.status.value,
                        "immutableRevision": revision.revision_number,
                        "qualityScore": revision.quality_score,
                    },
                    events=(
                        PendingEvent(
                            "RequestSubmitted",
                            {"immutableRevision": revision.revision_number},
                        ),
                    ),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint("submit", request_id, expected_revision, confirmed),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def list_my_intake_requests(self, actor: ActorContext, limit: int = 20) -> Outcome:
        return self._capture(
            lambda: Outcome(
                True,
                {
                    "requests": [
                        _summary(request)
                        for request in self._store.list_by_owner(
                            actor.tenant_id, actor.actor_id, limit
                        )
                    ]
                },
            )
        )

    def list_assigned_reviews(self, actor: ActorContext, limit: int = 20) -> Outcome:
        def execute() -> Outcome:
            if ActorRole.REVIEWER not in actor.roles and ActorRole.ADMINISTRATOR not in actor.roles:
                raise DomainError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "Reviewer or administrator role is required.",
                )
            return Outcome(
                True,
                {
                    "requests": [
                        _summary(request)
                        for request in self._store.list_assigned(
                            actor.tenant_id, actor.actor_id, limit
                        )
                    ]
                },
            )

        return self._capture(execute)

    def get_review_context(self, actor: ActorContext, request_id: str) -> Outcome:
        def execute() -> Outcome:
            request = self._required(request_id)
            authorize_reviewer(actor, request)
            if not request.revisions:
                raise DomainError(
                    ErrorCode.NOT_FOUND,
                    "No immutable submitted revision exists for this request.",
                )
            revision = request.revisions[-1]
            return Outcome(
                True,
                {
                    "requestId": request.request_id,
                    "requestRevision": request.version,
                    "status": request.status.value,
                    "immutableRevision": revision.revision_number,
                    "fields": [_field_data(item) for item in revision.fields],
                    "qualityScore": revision.quality_score,
                    "priorFeedback": [
                        _comment_data(comment) for comment in request.review_comments
                    ],
                    "allowedActions": list(allowed_actions(actor, request)),
                },
            )

        return self._capture(execute)

    def add_review_comment(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        comment: str,
    ) -> Outcome:
        def execute() -> Outcome:
            authorize_reviewer(actor, self._required(request_id))
            rationale = _require_rationale(comment)

            def operation(request: IntakeRequest) -> Mutation:
                authorize_reviewer(actor, request)
                if request.status is not RequestStatus.IN_REVIEW:
                    raise DomainError(
                        ErrorCode.INVALID_TRANSITION,
                        "Review comments can only be added while a request is in review.",
                    )
                item = ReviewComment(
                    comment_id=str(uuid4()),
                    reviewer_id=actor.actor_id,
                    revision_number=request.latest_revision_number,
                    comment=rationale,
                    created_at=self._clock(),
                )
                request.review_comments.append(item)
                return Mutation(
                    data={"comment": _comment_data(item)},
                    events=(
                        PendingEvent(
                            "ReviewFeedbackAdded",
                            {"immutableRevision": item.revision_number},
                        ),
                    ),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint("comment", request_id, expected_revision, rationale),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def request_intake_changes(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        rationale: str,
    ) -> Outcome:
        def execute() -> Outcome:
            authorize_reviewer(actor, self._required(request_id))
            reason = _require_rationale(rationale)

            def operation(request: IntakeRequest) -> Mutation:
                authorize_reviewer(actor, request)
                validate_transition(request.status, RequestStatus.AWAITING_USER_FEEDBACK)
                item = ReviewComment(
                    comment_id=str(uuid4()),
                    reviewer_id=actor.actor_id,
                    revision_number=request.latest_revision_number,
                    comment=reason,
                    created_at=self._clock(),
                )
                request.review_comments.append(item)
                request.status = RequestStatus.AWAITING_USER_FEEDBACK
                return Mutation(
                    data={
                        "status": request.status.value,
                        "feedback": _comment_data(item),
                    },
                    events=(
                        PendingEvent(
                            "ReviewFeedbackAdded",
                            {"immutableRevision": item.revision_number, "changesRequired": True},
                        ),
                    ),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint("changes", request_id, expected_revision, reason),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def decide_intake_review(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        decision: str,
        rationale: str,
    ) -> Outcome:
        def execute() -> Outcome:
            authorize_reviewer(actor, self._required(request_id))
            reason = _require_rationale(rationale)
            if decision not in {"approve", "reject"}:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "Decision must be approve or reject.",
                )

            def operation(request: IntakeRequest) -> Mutation:
                authorize_reviewer(actor, request)
                if actor.actor_id == request.requester_id:
                    raise DomainError(
                        ErrorCode.SEPARATION_OF_DUTIES,
                        "A requester cannot decide their own review.",
                    )
                target = (
                    RequestStatus.APPROVED if decision == "approve" else RequestStatus.REJECTED
                )
                validate_transition(request.status, target)
                revision_number = request.latest_revision_number
                review = ReviewDecision(
                    review_id=str(uuid4()),
                    reviewer_id=actor.actor_id,
                    revision_number=revision_number,
                    decision=decision,
                    rationale=reason,
                    decided_at=self._clock(),
                )
                request.review_decisions.append(review)
                request.status = target
                events = [
                    PendingEvent(
                        "RequestApproved" if decision == "approve" else "RequestRejected",
                        {
                            "immutableRevision": revision_number,
                            "rationale": reason,
                        },
                    )
                ]
                if decision == "approve":
                    request.approved_revision_number = revision_number
                    if request.template.mandatory_handover:
                        request.delivery_status = DeliveryStatus.PENDING
                        events.append(
                            PendingEvent(
                                "DeliveryRequested",
                                {
                                    "immutableRevision": revision_number,
                                    "schemaVersion": request.template.schema_version,
                                },
                            )
                        )
                    else:
                        validate_transition(request.status, RequestStatus.COMPLETED)
                        request.status = RequestStatus.COMPLETED
                        events.append(PendingEvent("RequestCompleted", {}))
                return Mutation(
                    data={
                        "status": request.status.value,
                        "decision": _decision_data(review),
                        "approvedRevision": request.approved_revision_number,
                        "deliveryStatus": request.delivery_status.value,
                    },
                    events=tuple(events),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint(
                    "decision", request_id, expected_revision, decision, reason
                ),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def record_delivery_success(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        target: str,
    ) -> Outcome:
        def execute() -> Outcome:
            if ActorRole.COMPLETION_WORKER not in actor.roles:
                raise DomainError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "Completion worker role is required.",
                )

            def operation(request: IntakeRequest) -> Mutation:
                if actor.tenant_id != request.tenant_id:
                    raise DomainError(
                        ErrorCode.AUTHORIZATION_DENIED,
                        "The completion worker cannot access a request in another tenant.",
                    )
                if request.status is not RequestStatus.APPROVED:
                    raise DomainError(
                        ErrorCode.INVALID_TRANSITION,
                        "Only an approved request can record handover success.",
                    )
                request.delivery_status = DeliveryStatus.SUCCEEDED
                return Mutation(
                    data={"deliveryStatus": request.delivery_status.value, "target": target},
                    events=(PendingEvent("DeliveryCompleted", {"target": target}),),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint("delivery", request_id, expected_revision, target),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def record_delivery_result(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        target: str,
        status: str,
        reason: str | None = None,
    ) -> Outcome:
        """Record an integration result through a service-only command."""

        def execute() -> Outcome:
            if ActorRole.INTEGRATION_WORKER not in actor.roles:
                raise DomainError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "Integration worker role is required.",
                )
            if status not in {"succeeded", "retryable_failure", "permanent_failure"}:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "Delivery status is not supported.",
                )
            normalized_reason = reason.strip()[:500] if reason else None

            def operation(request: IntakeRequest) -> Mutation:
                if actor.tenant_id != request.tenant_id:
                    raise DomainError(
                        ErrorCode.AUTHORIZATION_DENIED,
                        "The integration worker cannot access a request in another tenant.",
                    )
                if request.status is not RequestStatus.APPROVED:
                    raise DomainError(
                        ErrorCode.INVALID_TRANSITION,
                        "Only an approved request can record a delivery result.",
                    )
                if status == "succeeded":
                    request.delivery_status = DeliveryStatus.SUCCEEDED
                    request.delivery_failure_reason = None
                    event = PendingEvent("DeliveryCompleted", {"target": target})
                else:
                    request.delivery_status = (
                        DeliveryStatus.PENDING
                        if status == "retryable_failure"
                        else DeliveryStatus.FAILED
                    )
                    request.delivery_failure_reason = normalized_reason
                    event = PendingEvent(
                        "DeliveryFailed",
                        {
                            "target": target,
                            "retryable": status == "retryable_failure",
                            "reason": normalized_reason,
                        },
                    )
                return Mutation(
                    data={
                        "deliveryStatus": request.delivery_status.value,
                        "target": target,
                    },
                    events=(event,),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint(
                    "delivery-result",
                    request_id,
                    expected_revision,
                    target,
                    status,
                    normalized_reason,
                ),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def record_notification_result(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        notification_id: str,
        status: str,
    ) -> Outcome:
        """Record notification delivery without exposing the command to MCP."""

        def execute() -> Outcome:
            if ActorRole.NOTIFICATION_WORKER not in actor.roles:
                raise DomainError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "Notification worker role is required.",
                )
            if status not in {"succeeded", "exhausted"}:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "Notification status is not supported.",
                )

            def operation(request: IntakeRequest) -> Mutation:
                if actor.tenant_id != request.tenant_id:
                    raise DomainError(
                        ErrorCode.AUTHORIZATION_DENIED,
                        "The notification worker cannot access a request in another tenant.",
                    )
                request.notification_results[notification_id] = status
                return Mutation(
                    data={
                        "notificationId": notification_id,
                        "notificationStatus": status,
                    },
                    events=(
                        PendingEvent(
                            "NotificationResultRecorded",
                            {
                                "notificationId": notification_id,
                                "status": status,
                            },
                        ),
                    ),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint(
                    "notification-result",
                    request_id,
                    expected_revision,
                    notification_id,
                    status,
                ),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def record_retention_result(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
        status: str,
    ) -> Outcome:
        """Record an applied retention action or legal-hold outcome."""

        def execute() -> Outcome:
            if ActorRole.RETENTION_WORKER not in actor.roles:
                raise DomainError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "Retention worker role is required.",
                )
            if status not in {"deleted", "held", "failed"}:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "Retention status is not supported.",
                )

            def operation(request: IntakeRequest) -> Mutation:
                if actor.tenant_id != request.tenant_id:
                    raise DomainError(
                        ErrorCode.AUTHORIZATION_DENIED,
                        "The retention worker cannot access a request in another tenant.",
                    )
                request.retention_status = status
                return Mutation(
                    data={"retentionStatus": status},
                    events=(PendingEvent("RetentionResultRecorded", {"status": status}),),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint(
                    "retention-result",
                    request_id,
                    expected_revision,
                    status,
                ),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def complete_request_if_ready(
        self,
        actor: ActorContext,
        request_id: str,
        expected_revision: int,
        command_id: str,
    ) -> Outcome:
        def execute() -> Outcome:
            if ActorRole.COMPLETION_WORKER not in actor.roles:
                raise DomainError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "Completion worker role is required.",
                )

            def operation(request: IntakeRequest) -> Mutation:
                if actor.tenant_id != request.tenant_id:
                    raise DomainError(
                        ErrorCode.AUTHORIZATION_DENIED,
                        "The completion worker cannot access a request in another tenant.",
                    )
                if request.delivery_status not in {
                    DeliveryStatus.SUCCEEDED,
                    DeliveryStatus.NOT_REQUIRED,
                }:
                    raise DomainError(
                        ErrorCode.INVALID_TRANSITION,
                        "Mandatory handover has not completed.",
                    )
                validate_transition(request.status, RequestStatus.COMPLETED)
                request.status = RequestStatus.COMPLETED
                return Mutation(
                    data={
                        "status": request.status.value,
                        "approvedRevision": request.approved_revision_number,
                    },
                    events=(PendingEvent("RequestCompleted", {}),),
                )

            receipt = self._store.mutate(
                request_id,
                expected_revision,
                actor,
                command_id,
                _fingerprint("complete", request_id, expected_revision),
                operation,
            )
            return Outcome(True, receipt.data, replayed=receipt.replayed)

        return self._capture(execute)

    def _get_intake_context(
        self,
        actor: ActorContext,
        conversation_key: str,
        template_id: str,
    ) -> Outcome:
        if ActorRole.REQUESTER not in actor.roles and ActorRole.ADMINISTRATOR not in actor.roles:
            raise DomainError(
                ErrorCode.AUTHORIZATION_DENIED,
                "Requester or administrator role is required.",
            )
        template = self._templates.get(template_id)
        if template is None:
            raise DomainError(ErrorCode.NOT_FOUND, "The requested template was not found.")
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"intake:{actor.tenant_id}:{actor.actor_id}:{conversation_key}:{template_id}",
            )
        )
        now = self._clock()
        candidate = IntakeRequest(
            request_id=request_id,
            tenant_id=actor.tenant_id,
            requester_id=actor.actor_id,
            conversation_key=conversation_key,
            template=template,
            assigned_reviewer_id=self._default_reviewer_id,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            created_at=now,
            updated_at=now,
        )
        receipt = self._store.create_if_absent(
            candidate,
            actor,
            f"create:{request_id}",
            _fingerprint("create", request_id),
        )
        request = self._required(request_id)
        authorize_owner(actor, request)
        return Outcome(
            True,
            _context_data(actor, request),
            replayed=receipt.replayed,
        )

    def _required(self, request_id: str) -> IntakeRequest:
        request = self._store.get(request_id)
        if request is None:
            raise DomainError(ErrorCode.NOT_FOUND, "The request was not found.")
        return request

    @staticmethod
    def _capture(operation: Callable[[], Outcome]) -> Outcome:
        try:
            return operation()
        except DomainError as error:
            return Outcome(False, error=error)


def _context_data(actor: ActorContext, request: IntakeRequest) -> dict[str, Any]:
    gaps, quality = evaluate_request(request)
    return {
        "requestId": request.request_id,
        "requestRevision": request.version,
        "immutableRevision": request.latest_revision_number or None,
        "status": request.status.value,
        "template": {
            "templateId": request.template.template_id,
            "templateVersion": request.template.version,
            "schemaVersion": request.template.schema_version,
            "qualityThreshold": request.template.quality_threshold,
            "confidenceThreshold": request.template.confidence_threshold,
            "maximumClarificationAttempts": request.template.maximum_clarification_attempts,
            "fields": [
                {
                    "fieldPath": item.path,
                    "title": item.title,
                    "kind": item.kind.value,
                    "required": item.required,
                    "choices": list(item.choices),
                }
                for item in request.template.fields
            ],
        },
        "fields": [_field_data(request.fields[path]) for path in sorted(request.fields)],
        "gaps": [_gap_data(gap) for gap in gaps],
        "qualityScore": quality,
        "reviewFeedback": [_comment_data(item) for item in request.review_comments],
        "allowedActions": list(allowed_actions(actor, request)),
    }


def _summary(request: IntakeRequest) -> dict[str, Any]:
    return {
        "requestId": request.request_id,
        "requestRevision": request.version,
        "immutableRevision": request.latest_revision_number or None,
        "status": request.status.value,
        "templateId": request.template.template_id,
        "updatedAt": request.updated_at.isoformat() if request.updated_at else None,
    }


def _field_data(item: Any) -> dict[str, Any]:
    return {
        "fieldPath": item.field_path,
        "value": item.value,
        "sourceReference": item.source_reference,
        "confidence": item.confidence,
        "validationStatus": item.validation_status.value,
        "updatedBy": item.updated_by,
        "updatedAt": item.updated_at.isoformat(),
    }


def _gap_data(item: Any) -> dict[str, Any]:
    return {
        "gapId": item.gap_id,
        "fieldPath": item.field_path,
        "category": item.category,
        "severity": item.severity,
        "message": item.message,
        "clarificationAttempts": item.clarification_attempts,
        "clarificationLimitReached": item.clarification_limit_reached,
    }


def _comment_data(item: ReviewComment) -> dict[str, Any]:
    return {
        "commentId": item.comment_id,
        "reviewerId": item.reviewer_id,
        "immutableRevision": item.revision_number,
        "comment": item.comment,
        "createdAt": item.created_at.isoformat(),
    }


def _decision_data(item: ReviewDecision) -> dict[str, Any]:
    return {
        "reviewId": item.review_id,
        "reviewerId": item.reviewer_id,
        "immutableRevision": item.revision_number,
        "decision": item.decision,
        "rationale": item.rationale,
        "decidedAt": item.decided_at.isoformat(),
    }


def _require_rationale(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(ErrorCode.RATIONALE_REQUIRED, "A rationale is required.")
    if len(normalized) > 2000:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "The rationale must not exceed 2000 characters.",
        )
    return normalized


def _fingerprint(*parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode()).hexdigest()
