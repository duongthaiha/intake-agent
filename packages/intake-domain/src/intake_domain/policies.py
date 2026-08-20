"""Deterministic validation, lifecycle, authorization, and quality policies."""

from datetime import date, datetime
from hashlib import sha256
from math import isfinite

from intake_domain.errors import DomainError, ErrorCode
from intake_domain.models import (
    ActorContext,
    ActorRole,
    FieldKind,
    FieldValue,
    Gap,
    IntakeRequest,
    RequestRevision,
    RequestStatus,
    TemplateVersion,
    ValidationStatus,
)

_TRANSITIONS = {
    (RequestStatus.NEW, RequestStatus.IN_REVIEW),
    (RequestStatus.IN_REVIEW, RequestStatus.AWAITING_USER_FEEDBACK),
    (RequestStatus.AWAITING_USER_FEEDBACK, RequestStatus.IN_REVIEW),
    (RequestStatus.IN_REVIEW, RequestStatus.APPROVED),
    (RequestStatus.IN_REVIEW, RequestStatus.REJECTED),
    (RequestStatus.APPROVED, RequestStatus.COMPLETED),
}


def validate_transition(current: RequestStatus, target: RequestStatus) -> None:
    if (current, target) not in _TRANSITIONS:
        raise DomainError(
            ErrorCode.INVALID_TRANSITION,
            f"Transition from {current.value} to {target.value} is not allowed.",
        )


def authorize_owner(actor: ActorContext, request: IntakeRequest) -> None:
    is_admin = ActorRole.ADMINISTRATOR in actor.roles
    if actor.tenant_id != request.tenant_id or (
        actor.actor_id != request.requester_id and not is_admin
    ):
        raise DomainError(
            ErrorCode.AUTHORIZATION_DENIED,
            "The represented user is not allowed to modify this request.",
        )


def authorize_reviewer(actor: ActorContext, request: IntakeRequest) -> None:
    is_admin = ActorRole.ADMINISTRATOR in actor.roles
    is_assigned = (
        ActorRole.REVIEWER in actor.roles and actor.actor_id == request.assigned_reviewer_id
    )
    if actor.tenant_id != request.tenant_id or (not is_assigned and not is_admin):
        raise DomainError(
            ErrorCode.AUTHORIZATION_DENIED,
            "The represented user is not assigned to review this request.",
        )


def validate_candidate(
    template: TemplateVersion,
    field_path: str,
    value: str,
    source_reference: str,
    confidence: float,
    actor_id: str,
    now: datetime,
) -> FieldValue:
    rule = template.field(field_path)
    if rule is None:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "The field is not declared by the active template.",
            field_path=field_path,
        )
    normalized = value.strip()
    if len(normalized) < rule.minimum_length or len(normalized) > rule.maximum_length:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"The value must contain {rule.minimum_length} to {rule.maximum_length} characters.",
            field_path=field_path,
        )
    if rule.kind is FieldKind.CHOICE and normalized not in rule.choices:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"The value must be one of: {', '.join(rule.choices)}.",
            field_path=field_path,
        )
    if rule.kind is FieldKind.NUMBER:
        try:
            numeric_value = float(normalized)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "The value must be a number.",
                field_path=field_path,
            ) from exc
        if not isfinite(numeric_value):
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "The value must be a finite number.",
                field_path=field_path,
            )
        if rule.minimum_number is not None and numeric_value < rule.minimum_number:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                f"The value must be at least {rule.minimum_number:g}.",
                field_path=field_path,
            )
    if rule.kind is FieldKind.DATE:
        try:
            date.fromisoformat(normalized)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "The value must be an ISO date in YYYY-MM-DD format.",
                field_path=field_path,
            ) from exc
    validation_status = (
        ValidationStatus.VALID
        if confidence >= template.confidence_threshold
        else ValidationStatus.NEEDS_CLARIFICATION
    )
    return FieldValue(
        field_path=field_path,
        value=normalized,
        source_reference=source_reference,
        confidence=confidence,
        validation_status=validation_status,
        updated_by=actor_id,
        updated_at=now,
    )


def evaluate_request(request: IntakeRequest) -> tuple[tuple[Gap, ...], float]:
    gaps: list[Gap] = []
    valid_required = 0
    required_count = 0
    for rule in request.template.fields:
        field_value = request.fields.get(rule.path)
        attempts = request.clarification_attempts.get(rule.path, 0)
        limit_reached = attempts >= request.template.maximum_clarification_attempts
        if rule.required:
            required_count += 1
        if field_value is None:
            if rule.required:
                gaps.append(
                    _gap(
                        rule.path,
                        "missing",
                        "Required information is missing.",
                        attempts,
                        limit_reached,
                    )
                )
            continue
        if field_value.validation_status is ValidationStatus.NEEDS_CLARIFICATION:
            gaps.append(
                _gap(
                    rule.path,
                    "low_confidence",
                    "The captured value requires user confirmation.",
                    attempts,
                    limit_reached,
                )
            )
            continue
        if rule.required:
            valid_required += 1

    for contradiction in request.template.contradiction_rules:
        left = request.fields.get(contradiction.left_path)
        right = request.fields.get(contradiction.right_path)
        if left is None or right is None:
            continue
        contradictory = False
        if contradiction.operator == "date_after":
            contradictory = date.fromisoformat(left.value) > date.fromisoformat(right.value)
        elif contradiction.operator == "equals":
            contradictory = left.value == right.value
        if contradictory:
            path = f"{contradiction.left_path}|{contradiction.right_path}"
            attempts = max(
                request.clarification_attempts.get(contradiction.left_path, 0),
                request.clarification_attempts.get(contradiction.right_path, 0),
            )
            gaps.append(
                _gap(
                    path,
                    "contradiction",
                    contradiction.message,
                    attempts,
                    attempts >= request.template.maximum_clarification_attempts,
                )
            )

    quality = 1.0 if required_count == 0 else valid_required / required_count
    return tuple(gaps), round(quality, 4)


def build_revision(request: IntakeRequest, actor: ActorContext, now: datetime) -> RequestRevision:
    gaps, quality = evaluate_request(request)
    if gaps or quality < request.template.quality_threshold:
        if any(gap.clarification_limit_reached for gap in gaps):
            raise DomainError(
                ErrorCode.CLARIFICATION_LIMIT_REACHED,
                "The clarification limit was reached; an authorised human must resolve the gaps.",
            )
        raise DomainError(
            ErrorCode.INCOMPLETE_REQUEST,
            "The request has unresolved required gaps or contradictions.",
        )
    return RequestRevision(
        revision_number=request.latest_revision_number + 1,
        fields=tuple(request.fields[path] for path in sorted(request.fields)),
        quality_score=quality,
        provenance=actor.provenance,
        template_version=request.template.version,
        schema_version=request.template.schema_version,
        submitted_by=actor.actor_id,
        submitted_at=now,
    )


def allowed_actions(actor: ActorContext, request: IntakeRequest) -> tuple[str, ...]:
    actions: list[str] = []
    is_owner = actor.tenant_id == request.tenant_id and actor.actor_id == request.requester_id
    is_admin = ActorRole.ADMINISTRATOR in actor.roles and actor.tenant_id == request.tenant_id
    is_reviewer = (
        actor.tenant_id == request.tenant_id
        and ActorRole.REVIEWER in actor.roles
        and actor.actor_id == request.assigned_reviewer_id
    )
    if (is_owner or is_admin) and request.status in {
        RequestStatus.NEW,
        RequestStatus.AWAITING_USER_FEEDBACK,
    }:
        actions.extend(("update_intake_field", "submit_intake_for_review"))
    if (is_reviewer or is_admin) and request.status is RequestStatus.IN_REVIEW:
        actions.extend(
            ("add_review_comment", "request_intake_changes", "decide_intake_review")
        )
    return tuple(actions)


def _gap(
    field_path: str,
    category: str,
    message: str,
    attempts: int,
    limit_reached: bool,
) -> Gap:
    digest = sha256(f"{field_path}:{category}".encode()).hexdigest()[:16]
    return Gap(
        gap_id=f"gap-{digest}",
        field_path=field_path,
        category=category,
        severity="blocking",
        message=message,
        clarification_attempts=attempts,
        clarification_limit_reached=limit_reached,
    )
