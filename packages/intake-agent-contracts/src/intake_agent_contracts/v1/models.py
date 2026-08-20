"""Strict wire models for requester and reviewer MCP tools."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base model that rejects undeclared model-controlled input."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    AUTHORIZATION_DENIED = "authorization_denied"
    CONCURRENCY_CONFLICT = "concurrency_conflict"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INVALID_TRANSITION = "invalid_transition"
    NOT_FOUND = "not_found"
    INCOMPLETE_REQUEST = "incomplete_request"
    CLARIFICATION_LIMIT_REACHED = "clarification_limit_reached"
    RATIONALE_REQUIRED = "rationale_required"
    SEPARATION_OF_DUTIES = "separation_of_duties"
    UNSUPPORTED_CONTRACT_VERSION = "unsupported_contract_version"


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: str = Field(max_length=500)
    field_path: str | None = Field(default=None, alias="fieldPath", max_length=200)
    latest_revision: int | None = Field(default=None, alias="latestRevision", ge=0)
    retryable: bool = False


class ToolResponse(ContractModel):
    contract_version: Literal["1.0"] = Field(default="1.0", alias="contractVersion")
    ok: bool
    replayed: bool = False
    data: dict[str, Any] | None = None
    error: ErrorDetail | None = None


class GetIntakeContextRequest(ContractModel):
    conversation_key: str = Field(alias="conversationKey", min_length=1, max_length=200)
    template_id: str = Field(
        default="software-request", alias="templateId", min_length=1, max_length=100
    )


class UpdateFieldRequest(ContractModel):
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    command_id: str = Field(alias="commandId", min_length=1, max_length=100)
    field_path: str = Field(alias="fieldPath", min_length=1, max_length=200)
    value: str = Field(max_length=4000)
    source_reference: str = Field(alias="sourceReference", min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)


class SubmitIntakeRequest(ContractModel):
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    command_id: str = Field(alias="commandId", min_length=1, max_length=100)
    confirmed: Literal[True]


class ListMyRequestsRequest(ContractModel):
    limit: int = Field(default=20, ge=1, le=50)


class ListAssignedReviewsRequest(ContractModel):
    limit: int = Field(default=20, ge=1, le=50)


class GetReviewContextRequest(ContractModel):
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)


class AddReviewCommentRequest(ContractModel):
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    command_id: str = Field(alias="commandId", min_length=1, max_length=100)
    comment: str = Field(min_length=1, max_length=2000)


class RequestChangesRequest(ContractModel):
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    command_id: str = Field(alias="commandId", min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=2000)


class DecideReviewRequest(ContractModel):
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    command_id: str = Field(alias="commandId", min_length=1, max_length=100)
    decision: Literal["approve", "reject"]
    rationale: str = Field(min_length=1, max_length=2000)


class ApprovedField(ContractModel):
    field_path: str = Field(alias="fieldPath", min_length=1, max_length=200)
    value: str = Field(max_length=4000)
    source_reference: str = Field(
        alias="sourceReference", min_length=1, max_length=500
    )


class ApprovedRequestHandover(ContractModel):
    """Version 1 immutable approved-request downstream payload."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
    )

    contract_version: Literal["1.0"] = Field(
        default="1.0", alias="contractVersion"
    )
    request_id: str = Field(alias="requestId", min_length=1, max_length=100)
    tenant_id: str = Field(alias="tenantId", min_length=1, max_length=100)
    approved_revision: int = Field(alias="approvedRevision", ge=1)
    template_id: str = Field(alias="templateId", min_length=1, max_length=100)
    template_version: str = Field(
        alias="templateVersion", min_length=1, max_length=50
    )
    schema_version: str = Field(
        alias="schemaVersion", min_length=1, max_length=50
    )
    approved_at: str = Field(alias="approvedAt", min_length=1, max_length=50)
    fields: tuple[ApprovedField, ...]


class DownstreamAcceptance(ContractModel):
    contract_version: Literal["1.0"] = Field(
        default="1.0", alias="contractVersion"
    )
    accepted: bool
    duplicate: bool = False
    downstream_id: str = Field(
        alias="downstreamId", min_length=1, max_length=200
    )
