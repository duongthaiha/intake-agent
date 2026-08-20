"""Thread-safe ephemeral adapter with atomic audit, outbox, and idempotency."""

from collections.abc import Callable, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from intake_domain import (
    ActorContext,
    AuditEvent,
    ConversationEntry,
    DomainError,
    ErrorCode,
    IntakeRequest,
    Mutation,
    MutationReceipt,
    OutboxEvent,
    PendingEvent,
)


class InMemoryConversationHistory:
    """Thread-safe local conversation history substitute."""

    def __init__(self) -> None:
        self._entries: dict[str, list[ConversationEntry]] = {}
        self._lock = RLock()

    def append(self, entry: ConversationEntry) -> None:
        with self._lock:
            entries = self._entries.setdefault(entry.conversation_key, [])
            if entry.sequence != len(entries) + 1:
                raise DomainError(
                    ErrorCode.CONCURRENCY_CONFLICT,
                    "Conversation sequence does not match the latest persisted turn.",
                    latest_revision=len(entries),
                )
            entries.append(deepcopy(entry))

    def list(self, conversation_key: str) -> Sequence[ConversationEntry]:
        with self._lock:
            return tuple(deepcopy(self._entries.get(conversation_key, [])))

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


class InMemoryRequestStore:
    """Local-only RequestStore implementation; never production durability evidence."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._requests: dict[str, IntakeRequest] = {}
        self._idempotency: dict[
            tuple[str, str], tuple[str, tuple[str, str], MutationReceipt]
        ] = {}
        self._audit_events: list[AuditEvent] = []
        self._outbox_events: list[OutboxEvent] = []
        self._lock = RLock()

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(deepcopy(self._audit_events))

    @property
    def outbox_events(self) -> tuple[OutboxEvent, ...]:
        with self._lock:
            return tuple(deepcopy(self._outbox_events))

    def get(self, request_id: str) -> IntakeRequest | None:
        with self._lock:
            request = self._requests.get(request_id)
            return deepcopy(request) if request is not None else None

    def list_by_owner(
        self, tenant_id: str, owner_id: str, limit: int
    ) -> Sequence[IntakeRequest]:
        with self._lock:
            requests = [
                deepcopy(request)
                for request in self._requests.values()
                if request.tenant_id == tenant_id and request.requester_id == owner_id
            ]
        return sorted(
            requests,
            key=lambda request: request.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[:limit]

    def list_assigned(
        self, tenant_id: str, reviewer_id: str, limit: int
    ) -> Sequence[IntakeRequest]:
        with self._lock:
            requests = [
                deepcopy(request)
                for request in self._requests.values()
                if request.tenant_id == tenant_id
                and request.assigned_reviewer_id == reviewer_id
                and request.status.value == "in_review"
            ]
        return sorted(
            requests,
            key=lambda request: request.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[:limit]

    def create_if_absent(
        self,
        request: IntakeRequest,
        actor: ActorContext,
        command_id: str,
        fingerprint: str,
    ) -> MutationReceipt:
        with self._lock:
            replay = self._replay(request.request_id, command_id, fingerprint, actor)
            if replay is not None:
                return replay
            existing = self._requests.get(request.request_id)
            if existing is not None:
                receipt = MutationReceipt(
                    data={
                        "requestId": existing.request_id,
                        "requestRevision": existing.version,
                        "status": existing.status.value,
                        "created": False,
                    },
                    replayed=True,
                )
                self._idempotency[(request.request_id, command_id)] = (
                    fingerprint,
                    (actor.tenant_id, actor.actor_id),
                    receipt,
                )
                return deepcopy(receipt)
            stored = deepcopy(request)
            self._requests[stored.request_id] = stored
            self._record_events(
                stored,
                actor,
                command_id,
                prior_state=None,
                events=(PendingEvent("RequestCreated", {}),),
            )
            receipt = MutationReceipt(
                data={
                    "requestId": stored.request_id,
                    "requestRevision": stored.version,
                    "status": stored.status.value,
                    "created": True,
                },
                replayed=False,
            )
            self._idempotency[(stored.request_id, command_id)] = (
                fingerprint,
                (actor.tenant_id, actor.actor_id),
                receipt,
            )
            return deepcopy(receipt)

    def mutate(
        self,
        request_id: str,
        expected_version: int,
        actor: ActorContext,
        command_id: str,
        fingerprint: str,
        operation: Callable[[IntakeRequest], Mutation],
    ) -> MutationReceipt:
        with self._lock:
            replay = self._replay(request_id, command_id, fingerprint, actor)
            if replay is not None:
                return replay
            current = self._requests.get(request_id)
            if current is None:
                raise DomainError(ErrorCode.NOT_FOUND, "The request was not found.")
            if current.version != expected_version:
                raise DomainError(
                    ErrorCode.CONCURRENCY_CONFLICT,
                    "The request changed; reload the latest context before retrying.",
                    latest_revision=current.version,
                )
            candidate = deepcopy(current)
            prior_state = candidate.status.value
            mutation = operation(candidate)
            candidate.version += 1
            candidate.updated_at = self._clock()
            data = deepcopy(mutation.data)
            data.update(
                {
                    "requestId": candidate.request_id,
                    "requestRevision": candidate.version,
                    "status": candidate.status.value,
                }
            )
            receipt = MutationReceipt(data=data, replayed=False)
            self._requests[request_id] = candidate
            self._record_events(
                candidate,
                actor,
                command_id,
                prior_state=prior_state,
                events=mutation.events,
            )
            self._idempotency[(request_id, command_id)] = (
                fingerprint,
                (actor.tenant_id, actor.actor_id),
                receipt,
            )
            return deepcopy(receipt)

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._idempotency.clear()
            self._audit_events.clear()
            self._outbox_events.clear()

    def _replay(
        self,
        request_id: str,
        command_id: str,
        fingerprint: str,
        actor: ActorContext,
    ) -> MutationReceipt | None:
        stored = self._idempotency.get((request_id, command_id))
        if stored is None:
            return None
        stored_fingerprint, stored_actor, receipt = stored
        if stored_actor != (actor.tenant_id, actor.actor_id):
            raise DomainError(
                ErrorCode.AUTHORIZATION_DENIED,
                "The command belongs to a different represented user.",
            )
        if stored_fingerprint != fingerprint:
            raise DomainError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "The command ID was already used with a different payload.",
            )
        replay_data = deepcopy(receipt.data)
        return MutationReceipt(data=replay_data, replayed=True)

    def _record_events(
        self,
        request: IntakeRequest,
        actor: ActorContext,
        command_id: str,
        prior_state: str | None,
        events: tuple[PendingEvent, ...],
    ) -> None:
        now = self._clock()
        audit_type = events[0].event_type if events else "RequestChanged"
        self._audit_events.append(
            AuditEvent(
                event_id=str(uuid4()),
                event_type=audit_type,
                request_id=request.request_id,
                revision=request.version,
                actor_id=actor.actor_id,
                actor_roles=tuple(sorted(role.value for role in actor.roles)),
                correlation_id=actor.correlation_id,
                command_id=command_id,
                prior_state=prior_state,
                new_state=request.status.value,
                occurred_at=now,
            )
        )
        for event in events:
            self._outbox_events.append(
                OutboxEvent(
                    event_id=str(uuid4()),
                    event_type=event.event_type,
                    event_version="1.0",
                    request_id=request.request_id,
                    revision=request.version,
                    correlation_id=actor.correlation_id,
                    causation_id=command_id,
                    occurred_at=now,
                    actor_id=actor.actor_id,
                    data=deepcopy(event.data),
                )
            )
