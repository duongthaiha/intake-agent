"""JSON document mapping for Azure persistence adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from intake_domain import (
    AgentKind,
    ContradictionRule,
    DeliveryStatus,
    FieldKind,
    FieldValue,
    IntakeRequest,
    Provenance,
    RequestRevision,
    RequestStatus,
    ReviewComment,
    ReviewDecision,
    TemplateField,
    TemplateVersion,
    ValidationStatus,
)


def request_to_document(request: IntakeRequest) -> dict[str, Any]:
    return {
        "id": "request",
        "docType": "request",
        "requestId": request.request_id,
        "tenantId": request.tenant_id,
        "requesterId": request.requester_id,
        "conversationKey": request.conversation_key,
        "template": _template_to_document(request.template),
        "assignedReviewerId": request.assigned_reviewer_id,
        "status": request.status.value,
        "version": request.version,
        "fields": {
            path: _field_to_document(value) for path, value in request.fields.items()
        },
        "clarificationAttempts": dict(request.clarification_attempts),
        "revisions": [_revision_to_document(item) for item in request.revisions],
        "reviewComments": [_comment_to_document(item) for item in request.review_comments],
        "reviewDecisions": [
            _decision_to_document(item) for item in request.review_decisions
        ],
        "approvedRevisionNumber": request.approved_revision_number,
        "deliveryStatus": request.delivery_status.value,
        "deliveryFailureReason": request.delivery_failure_reason,
        "notificationResults": dict(request.notification_results),
        "retentionStatus": request.retention_status,
        "createdAt": _datetime_to_wire(request.created_at),
        "updatedAt": _datetime_to_wire(request.updated_at),
    }


def request_from_document(document: dict[str, Any]) -> IntakeRequest:
    return IntakeRequest(
        request_id=str(document["requestId"]),
        tenant_id=str(document["tenantId"]),
        requester_id=str(document["requesterId"]),
        conversation_key=str(document["conversationKey"]),
        template=_template_from_document(_mapping(document["template"])),
        assigned_reviewer_id=str(document["assignedReviewerId"]),
        status=RequestStatus(str(document["status"])),
        version=int(document["version"]),
        fields={
            str(path): _field_from_document(_mapping(value))
            for path, value in _mapping(document.get("fields", {})).items()
        },
        clarification_attempts={
            str(path): int(value)
            for path, value in _mapping(
                document.get("clarificationAttempts", {})
            ).items()
        },
        revisions=[
            _revision_from_document(_mapping(item))
            for item in _sequence(document.get("revisions", []))
        ],
        review_comments=[
            _comment_from_document(_mapping(item))
            for item in _sequence(document.get("reviewComments", []))
        ],
        review_decisions=[
            _decision_from_document(_mapping(item))
            for item in _sequence(document.get("reviewDecisions", []))
        ],
        approved_revision_number=_optional_int(
            document.get("approvedRevisionNumber")
        ),
        delivery_status=DeliveryStatus(
            str(document.get("deliveryStatus", DeliveryStatus.NOT_REQUIRED.value))
        ),
        delivery_failure_reason=(
            str(document["deliveryFailureReason"])
            if document.get("deliveryFailureReason") is not None
            else None
        ),
        notification_results={
            str(key): str(value)
            for key, value in _mapping(
                document.get("notificationResults", {})
            ).items()
        },
        retention_status=str(document.get("retentionStatus", "active")),
        created_at=_datetime_from_wire(document.get("createdAt")),
        updated_at=_datetime_from_wire(document.get("updatedAt")),
    )


def _template_to_document(template: TemplateVersion) -> dict[str, Any]:
    return {
        "templateId": template.template_id,
        "version": template.version,
        "schemaVersion": template.schema_version,
        "fields": [
            {
                "path": item.path,
                "title": item.title,
                "kind": item.kind.value,
                "required": item.required,
                "minimumLength": item.minimum_length,
                "maximumLength": item.maximum_length,
                "choices": list(item.choices),
                "minimumNumber": item.minimum_number,
            }
            for item in template.fields
        ],
        "contradictionRules": [
            {
                "leftPath": item.left_path,
                "operator": item.operator,
                "rightPath": item.right_path,
                "message": item.message,
            }
            for item in template.contradiction_rules
        ],
        "qualityThreshold": template.quality_threshold,
        "confidenceThreshold": template.confidence_threshold,
        "maximumClarificationAttempts": template.maximum_clarification_attempts,
        "mandatoryHandover": template.mandatory_handover,
    }


def _template_from_document(document: dict[str, Any]) -> TemplateVersion:
    return TemplateVersion(
        template_id=str(document["templateId"]),
        version=str(document["version"]),
        schema_version=str(document["schemaVersion"]),
        fields=tuple(
            TemplateField(
                path=str(item["path"]),
                title=str(item["title"]),
                kind=FieldKind(str(item["kind"])),
                required=bool(item["required"]),
                minimum_length=int(item.get("minimumLength", 0)),
                maximum_length=int(item.get("maximumLength", 4000)),
                choices=tuple(str(value) for value in _sequence(item.get("choices", []))),
                minimum_number=(
                    float(item["minimumNumber"])
                    if item.get("minimumNumber") is not None
                    else None
                ),
            )
            for raw in _sequence(document.get("fields", []))
            for item in [_mapping(raw)]
        ),
        contradiction_rules=tuple(
            ContradictionRule(
                left_path=str(item["leftPath"]),
                operator=str(item["operator"]),
                right_path=str(item["rightPath"]),
                message=str(item["message"]),
            )
            for raw in _sequence(document.get("contradictionRules", []))
            for item in [_mapping(raw)]
        ),
        quality_threshold=float(document["qualityThreshold"]),
        confidence_threshold=float(document["confidenceThreshold"]),
        maximum_clarification_attempts=int(
            document["maximumClarificationAttempts"]
        ),
        mandatory_handover=bool(document["mandatoryHandover"]),
    )


def _field_to_document(value: FieldValue) -> dict[str, Any]:
    return {
        "fieldPath": value.field_path,
        "value": value.value,
        "sourceReference": value.source_reference,
        "confidence": value.confidence,
        "validationStatus": value.validation_status.value,
        "updatedBy": value.updated_by,
        "updatedAt": _datetime_to_wire(value.updated_at),
    }


def _field_from_document(document: dict[str, Any]) -> FieldValue:
    return FieldValue(
        field_path=str(document["fieldPath"]),
        value=str(document["value"]),
        source_reference=str(document["sourceReference"]),
        confidence=float(document["confidence"]),
        validation_status=ValidationStatus(str(document["validationStatus"])),
        updated_by=str(document["updatedBy"]),
        updated_at=_required_datetime(document["updatedAt"]),
    )


def _revision_to_document(revision: RequestRevision) -> dict[str, Any]:
    return {
        "revisionNumber": revision.revision_number,
        "fields": [_field_to_document(item) for item in revision.fields],
        "qualityScore": revision.quality_score,
        "provenance": _provenance_to_document(revision.provenance),
        "templateVersion": revision.template_version,
        "schemaVersion": revision.schema_version,
        "submittedBy": revision.submitted_by,
        "submittedAt": _datetime_to_wire(revision.submitted_at),
    }


def _revision_from_document(document: dict[str, Any]) -> RequestRevision:
    return RequestRevision(
        revision_number=int(document["revisionNumber"]),
        fields=tuple(
            _field_from_document(_mapping(item))
            for item in _sequence(document.get("fields", []))
        ),
        quality_score=float(document["qualityScore"]),
        provenance=_provenance_from_document(_mapping(document["provenance"])),
        template_version=str(document["templateVersion"]),
        schema_version=str(document["schemaVersion"]),
        submitted_by=str(document["submittedBy"]),
        submitted_at=_required_datetime(document["submittedAt"]),
    )


def _provenance_to_document(provenance: Provenance) -> dict[str, Any]:
    return {
        "agentKind": provenance.agent_kind.value,
        "agentVersion": provenance.agent_version,
        "instructionsVersion": provenance.instructions_version,
        "modelVersion": provenance.model_version,
        "toolboxVersion": provenance.toolbox_version,
        "mcpContractVersion": provenance.mcp_contract_version,
        "policyVersion": provenance.policy_version,
    }


def _provenance_from_document(document: dict[str, Any]) -> Provenance:
    return Provenance(
        agent_kind=AgentKind(str(document["agentKind"])),
        agent_version=str(document["agentVersion"]),
        instructions_version=str(document["instructionsVersion"]),
        model_version=str(document["modelVersion"]),
        toolbox_version=str(document["toolboxVersion"]),
        mcp_contract_version=str(document["mcpContractVersion"]),
        policy_version=str(document["policyVersion"]),
    )


def _comment_to_document(comment: ReviewComment) -> dict[str, Any]:
    return {
        "commentId": comment.comment_id,
        "reviewerId": comment.reviewer_id,
        "revisionNumber": comment.revision_number,
        "comment": comment.comment,
        "createdAt": _datetime_to_wire(comment.created_at),
    }


def _comment_from_document(document: dict[str, Any]) -> ReviewComment:
    return ReviewComment(
        comment_id=str(document["commentId"]),
        reviewer_id=str(document["reviewerId"]),
        revision_number=int(document["revisionNumber"]),
        comment=str(document["comment"]),
        created_at=_required_datetime(document["createdAt"]),
    )


def _decision_to_document(decision: ReviewDecision) -> dict[str, Any]:
    return {
        "reviewId": decision.review_id,
        "reviewerId": decision.reviewer_id,
        "revisionNumber": decision.revision_number,
        "decision": decision.decision,
        "rationale": decision.rationale,
        "decidedAt": _datetime_to_wire(decision.decided_at),
    }


def _decision_from_document(document: dict[str, Any]) -> ReviewDecision:
    return ReviewDecision(
        review_id=str(document["reviewId"]),
        reviewer_id=str(document["reviewerId"]),
        revision_number=int(document["revisionNumber"]),
        decision=str(document["decision"]),
        rationale=str(document["rationale"]),
        decided_at=_required_datetime(document["decidedAt"]),
    )


def _datetime_to_wire(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_from_wire(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _required_datetime(value: object) -> datetime:
    parsed = _datetime_from_wire(value)
    if parsed is None:
        raise ValueError("A persisted datetime is required.")
    return parsed


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("A persisted object must be a JSON mapping.")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("A persisted collection must be a JSON array.")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (int, str, bytes, bytearray)):
        raise ValueError("A persisted optional integer has an invalid type.")
    return int(value)
