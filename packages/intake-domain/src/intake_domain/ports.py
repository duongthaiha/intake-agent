"""Persistence port owned by the deterministic domain boundary."""

from collections.abc import Callable, Sequence
from typing import Protocol

from intake_domain.models import (
    ActorContext,
    ConversationEntry,
    IntakeRequest,
    Mutation,
    MutationReceipt,
)


class ConversationHistory(Protocol):
    def append(self, entry: ConversationEntry) -> None: ...

    def list(self, conversation_key: str) -> Sequence[ConversationEntry]: ...

    def reset(self) -> None: ...


class RequestStore(Protocol):
    def get(self, request_id: str) -> IntakeRequest | None: ...

    def list_by_owner(
        self, tenant_id: str, owner_id: str, limit: int
    ) -> Sequence[IntakeRequest]: ...

    def list_assigned(
        self, tenant_id: str, reviewer_id: str, limit: int
    ) -> Sequence[IntakeRequest]: ...

    def create_if_absent(
        self,
        request: IntakeRequest,
        actor: ActorContext,
        command_id: str,
        fingerprint: str,
    ) -> MutationReceipt: ...

    def mutate(
        self,
        request_id: str,
        expected_version: int,
        actor: ActorContext,
        command_id: str,
        fingerprint: str,
        operation: Callable[[IntakeRequest], Mutation],
    ) -> MutationReceipt: ...
