"""Typed contracts for the four requester operations."""
from __future__ import annotations

import hashlib
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, RootModel

from intake_domain.entities import ActorContext


class OperationContext(BaseModel):
    """Trusted invocation state supplied by an authenticated transport."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=128)
    scopes: frozenset[str]
    conversation_id: str = Field(min_length=1, max_length=256)
    activity_id: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)
    agent_identity: str = Field(default="intake-mcp", min_length=1, max_length=128)

    def actor(self) -> ActorContext:
        """Build the domain actor exclusively from verified transport state."""
        opaque_user_id = hashlib.sha256(
            f"{self.tenant_id}:{self.actor_id}".encode()
        ).hexdigest()[:32]
        return ActorContext(
            user_id=f"entra-user-{opaque_user_id}",
            tenant_id=self.tenant_id,
            roles=frozenset(["requester"]),
            conversation_id=self.conversation_id,
            activity_id=self.activity_id,
            correlation_id=self.correlation_id,
            agent_identity=self.agent_identity,
        )

    def require_idempotency_key(self) -> str:
        if self.idempotency_key is None:
            raise ValueError("A trusted idempotency key is required for mutations")
        return self.idempotency_key


class GetIntakeContextRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class UpdateIntakeFieldRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    field_path: str = Field(min_length=1, max_length=256)
    value: str | int | float | bool
    expected_revision: int = Field(ge=1)
    source_reference: str | None = Field(default=None, max_length=512)
    model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SubmitIntakeForReviewRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    expected_revision: int = Field(ge=1)


class ListMyIntakeRequestsRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ToolResult(RootModel[dict[str, Any] | list[dict[str, Any]]]):
    """JSON-compatible deterministic application result."""


class IntakeToolPort(Protocol):
    async def get_intake_context(
        self,
        request: GetIntakeContextRequest,
        context: OperationContext,
    ) -> ToolResult: ...

    async def update_intake_field(
        self,
        request: UpdateIntakeFieldRequest,
        context: OperationContext,
    ) -> ToolResult: ...

    async def submit_intake_for_review(
        self,
        request: SubmitIntakeForReviewRequest,
        context: OperationContext,
    ) -> ToolResult: ...

    async def list_my_intake_requests(
        self,
        request: ListMyIntakeRequestsRequest,
        context: OperationContext,
    ) -> ToolResult: ...
