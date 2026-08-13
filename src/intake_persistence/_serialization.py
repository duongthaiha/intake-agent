"""Serialization helpers shared by durable persistence adapters."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from intake_domain.entities import (
    FieldValue,
    Gap,
    GapCategory,
    GapSeverity,
    GapStatus,
    OutboxItem,
    Request,
    RequestRevision,
    RequestStatus,
    StoredResult,
    TemplateVersion,
    ValidationStatus,
    WorkflowEvent,
)


def datetime_to_json(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def datetime_from_json(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def request_to_document(request: Request) -> dict[str, Any]:
    return {
        "id": "request",
        "docType": "request",
        "requestId": request.request_id,
        "tenantId": request.tenant_id,
        "conversationId": request.conversation_id,
        "requesterId": request.requester_id,
        "status": request.status.value,
        "currentRevision": request.current_revision,
        "templateId": request.template_id,
        "templateVersion": request.template_version,
        "createdAt": datetime_to_json(request.created_at),
        "updatedAt": datetime_to_json(request.updated_at),
    }


def request_from_document(document: dict[str, Any]) -> Request:
    return Request(
        request_id=str(document["requestId"]),
        tenant_id=str(document["tenantId"]),
        conversation_id=str(document["conversationId"]),
        requester_id=str(document["requesterId"]),
        status=RequestStatus(str(document["status"])),
        current_revision=int(document["currentRevision"]),
        template_id=str(document["templateId"]),
        template_version=str(document["templateVersion"]),
        created_at=datetime_from_json(str(document["createdAt"])),
        updated_at=datetime_from_json(str(document["updatedAt"])),
        etag=str(document.get("_etag", "")),
    )


def revision_to_document(revision: RequestRevision) -> dict[str, Any]:
    return {
        "id": f"revision:{revision.revision}",
        "docType": "revision",
        "requestId": revision.request_id,
        "revision": revision.revision,
        "fields": {
            key: {
                "fieldPath": value.field_path,
                "value": value.value,
                "sourceReference": value.source_reference,
                "modelConfidence": value.model_confidence,
                "validationStatus": value.validation_status.value,
            }
            for key, value in revision.fields.items()
        },
        "gaps": [
            {
                "gapId": gap.gap_id,
                "fieldPath": gap.field_path,
                "category": gap.category.value,
                "severity": gap.severity.value,
                "status": gap.status.value,
                "message": gap.message,
            }
            for gap in revision.gaps
        ],
        "qualityScore": revision.quality_score,
        "agentVersion": revision.agent_version,
        "promptVersion": revision.prompt_version,
        "modelVersion": revision.model_version,
        "templateVersion": revision.template_version,
        "createdAt": datetime_to_json(revision.created_at),
        "immutable": revision.immutable,
    }


def revision_from_document(document: dict[str, Any]) -> RequestRevision:
    fields = {
        str(key): FieldValue(
            field_path=str(value["fieldPath"]),
            value=value.get("value"),
            source_reference=_optional_str(value.get("sourceReference")),
            model_confidence=_optional_float(value.get("modelConfidence")),
            validation_status=ValidationStatus(str(value["validationStatus"])),
        )
        for key, value in _dict(document.get("fields")).items()
    }
    gaps = [
        Gap(
            gap_id=str(value["gapId"]),
            field_path=str(value["fieldPath"]),
            category=GapCategory(str(value["category"])),
            severity=GapSeverity(str(value["severity"])),
            status=GapStatus(str(value["status"])),
            message=str(value.get("message", "")),
        )
        for value in _list_of_dicts(document.get("gaps"))
    ]
    return RequestRevision(
        request_id=str(document["requestId"]),
        revision=int(document["revision"]),
        fields=fields,
        gaps=gaps,
        quality_score=_optional_float(document.get("qualityScore")),
        agent_version=str(document.get("agentVersion", "")),
        prompt_version=str(document.get("promptVersion", "")),
        model_version=str(document.get("modelVersion", "")),
        template_version=str(document.get("templateVersion", "")),
        created_at=datetime_from_json(str(document["createdAt"])),
        immutable=bool(document.get("immutable", False)),
    )


def workflow_event_to_document(event: WorkflowEvent) -> dict[str, Any]:
    return {
        "id": f"event:{event.event_id}",
        "docType": "workflowEvent",
        "requestId": event.request_id,
        "eventId": event.event_id,
        "eventType": event.event_type,
        "eventVersion": event.event_version,
        "revision": event.revision,
        "actorId": event.actor_id,
        "actorType": event.actor_type.value,
        "commandId": event.command_id,
        "correlationId": event.correlation_id,
        "priorState": event.prior_state.value if event.prior_state else None,
        "newState": event.new_state.value if event.new_state else None,
        "occurredAt": datetime_to_json(event.occurred_at),
        "data": event.data,
    }


def workflow_event_to_outbox(event: WorkflowEvent) -> OutboxItem:
    return OutboxItem(
        item_id=event.event_id,
        request_id=event.request_id,
        event_type=event.event_type,
        payload={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "event_version": event.event_version,
            "request_id": event.request_id,
            "revision": event.revision,
            "correlation_id": event.correlation_id,
            "causation_id": event.command_id,
            "occurred_at": datetime_to_json(event.occurred_at),
            "actor": {
                "user_id": event.actor_id,
                "actor_type": event.actor_type.value,
            },
            "data": event.data,
        },
        created_at=event.occurred_at,
    )


def outbox_to_document(item: OutboxItem) -> dict[str, Any]:
    return {
        "id": f"outbox:{item.item_id}",
        "docType": "outbox",
        "requestId": item.request_id,
        "itemId": item.item_id,
        "eventType": item.event_type,
        "payload": item.payload,
        "createdAt": datetime_to_json(item.created_at),
        "dispatched": item.dispatched,
        "dispatchedAt": None,
    }


def outbox_from_document(document: dict[str, Any]) -> OutboxItem:
    return OutboxItem(
        item_id=str(document["itemId"]),
        request_id=str(document["requestId"]),
        event_type=str(document["eventType"]),
        payload=_dict(document.get("payload")),
        created_at=datetime_from_json(str(document["createdAt"])),
        dispatched=bool(document.get("dispatched", False)),
    )


def template_from_document(document: dict[str, Any]) -> TemplateVersion:
    json_schema = document.get("jsonSchema")
    if not isinstance(json_schema, dict):
        raise ValueError("Template document must define a jsonSchema object")
    from intake_domain.template_schema import TemplateSchemaError, template_from_json_schema

    try:
        template = template_from_json_schema(
            json_schema,
            created_at=datetime_from_json(str(document["createdAt"])),
        )
    except TemplateSchemaError as exc:
        raise ValueError(f"Invalid template jsonSchema: {exc}") from exc
    envelope_values = {
        "templateId": template.template_id,
        "version": template.version,
        "displayName": template.display_name,
        "qualityThreshold": template.quality_threshold,
        "isActive": template.is_active,
    }
    for key, expected in envelope_values.items():
        if document.get(key) != expected:
            raise ValueError(
                f"Template envelope {key} does not match jsonSchema metadata"
            )
    return template


def stored_result_to_document(result: StoredResult, ttl_seconds: int) -> dict[str, Any]:
    import hashlib

    item_id = hashlib.sha256(result.key.encode("utf-8")).hexdigest()
    return {
        "id": item_id,
        "docType": "idempotency",
        "scopeId": result.scope_id,
        "key": result.key,
        "result": result.result,
        "storedAt": datetime_to_json(result.stored_at),
        "expiresAt": datetime_to_json(result.expires_at),
        "ttl": ttl_seconds,
    }


def stored_result_from_document(document: dict[str, Any]) -> StoredResult:
    return StoredResult(
        scope_id=str(document["scopeId"]),
        key=str(document["key"]),
        result=document.get("result"),
        stored_at=datetime_from_json(str(document["storedAt"])),
        expires_at=datetime_from_json(str(document["expiresAt"])),
    )


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_dict(item) for item in value if isinstance(item, dict)]


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(cast(str | int | float, value))
