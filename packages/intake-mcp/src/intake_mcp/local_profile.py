"""Ephemeral local composition root with seeded identities and handover stub."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from intake_agent_contracts import ErrorCode as ContractErrorCode
from intake_agent_contracts import ErrorDetail, ToolResponse
from intake_application import IntakeService, Outcome
from intake_domain import (
    ActorContext,
    ActorRole,
    AgentKind,
    ContradictionRule,
    ConversationEntry,
    FieldKind,
    Provenance,
    TemplateField,
    TemplateVersion,
)
from intake_persistence import InMemoryConversationHistory, InMemoryRequestStore

LOCAL_TENANT_ID = "local-tenant"
LOCAL_REQUESTER_ID = "requester-1"
LOCAL_REVIEWER_ID = "reviewer-1"


@dataclass(frozen=True, slots=True)
class HandoverRecord:
    request_id: str
    approved_revision: int
    target: str


class LocalProfile:
    """Fully in-memory profile with trusted, server-configured local principals."""

    def __init__(self) -> None:
        self.store = InMemoryRequestStore()
        self.conversation_history = InMemoryConversationHistory()
        self.service = IntakeService(
            self.store,
            {"software-request": default_template()},
            default_reviewer_id=LOCAL_REVIEWER_ID,
        )
        self.handovers: list[HandoverRecord] = []

    def record_conversation_message(
        self,
        conversation_key: str,
        role: str,
        content: str,
        *,
        actor_id: str = LOCAL_REQUESTER_ID,
    ) -> ConversationEntry:
        entries = self.conversation_history.list(conversation_key)
        entry = ConversationEntry(
            conversation_key=conversation_key,
            sequence=len(entries) + 1,
            role=role,
            actor_id=actor_id,
            content=content,
            occurred_at=datetime.now(UTC),
        )
        self.conversation_history.append(entry)
        return entry

    def requester(self, *, agent_kind: AgentKind = AgentKind.LOCAL) -> ActorContext:
        return _actor(LOCAL_REQUESTER_ID, ActorRole.REQUESTER, agent_kind)

    def reviewer(self) -> ActorContext:
        return _actor(LOCAL_REVIEWER_ID, ActorRole.REVIEWER, AgentKind.LOCAL)

    def worker(self) -> ActorContext:
        return _actor("completion-worker-1", ActorRole.COMPLETION_WORKER, AgentKind.SERVICE)

    def get_intake_context(
        self, conversation_key: str, template_id: str = "software-request"
    ) -> ToolResponse:
        return _response(
            self.service.get_intake_context(
                self.requester(), conversation_key, template_id
            )
        )

    def update_intake_field(
        self,
        request_id: str,
        expected_revision: int,
        command_id: str,
        field_path: str,
        value: str,
        source_reference: str,
        confidence: float,
    ) -> ToolResponse:
        return _response(
            self.service.update_intake_field(
                self.requester(),
                request_id,
                expected_revision,
                command_id,
                field_path,
                value,
                source_reference,
                confidence,
            )
        )

    def submit_intake_for_review(
        self,
        request_id: str,
        expected_revision: int,
        command_id: str,
        *,
        confirmed: bool,
    ) -> ToolResponse:
        return _response(
            self.service.submit_intake_for_review(
                self.requester(),
                request_id,
                expected_revision,
                command_id,
                confirmed=confirmed,
            )
        )

    def list_my_intake_requests(self, limit: int = 20) -> ToolResponse:
        return _response(
            self.service.list_my_intake_requests(self.requester(), limit)
        )

    def list_assigned_reviews(self, limit: int = 20) -> ToolResponse:
        return _response(
            self.service.list_assigned_reviews(self.reviewer(), limit)
        )

    def get_review_context(self, request_id: str) -> ToolResponse:
        return _response(
            self.service.get_review_context(self.reviewer(), request_id)
        )

    def add_review_comment(
        self,
        request_id: str,
        expected_revision: int,
        command_id: str,
        comment: str,
    ) -> ToolResponse:
        return _response(
            self.service.add_review_comment(
                self.reviewer(),
                request_id,
                expected_revision,
                command_id,
                comment,
            )
        )

    def request_intake_changes(
        self,
        request_id: str,
        expected_revision: int,
        command_id: str,
        rationale: str,
    ) -> ToolResponse:
        return _response(
            self.service.request_intake_changes(
                self.reviewer(),
                request_id,
                expected_revision,
                command_id,
                rationale,
            )
        )

    def decide_intake_review(
        self,
        request_id: str,
        expected_revision: int,
        command_id: str,
        decision: str,
        rationale: str,
    ) -> ToolResponse:
        outcome = self.service.decide_intake_review(
            self.reviewer(),
            request_id,
            expected_revision,
            command_id,
            decision,
            rationale,
        )
        if not outcome.ok or decision != "approve" or outcome.data is None:
            return _response(outcome)

        approved_revision = outcome.data["approvedRevision"]
        assert isinstance(approved_revision, int)
        request_version = outcome.data["requestRevision"]
        assert isinstance(request_version, int)
        handover = HandoverRecord(request_id, approved_revision, "local-contract-stub")
        if handover not in self.handovers:
            self.handovers.append(handover)
        delivery = self.service.record_delivery_success(
            self.worker(),
            request_id,
            request_version,
            f"handover:{command_id}",
            handover.target,
        )
        if not delivery.ok or delivery.data is None:
            return _response(delivery)
        delivered_version = delivery.data["requestRevision"]
        assert isinstance(delivered_version, int)
        completed = self.service.complete_request_if_ready(
            self.worker(),
            request_id,
            delivered_version,
            f"complete:{command_id}",
        )
        return _response(completed)

    def reset(self) -> None:
        self.store.reset()
        self.conversation_history.reset()
        self.handovers.clear()


def default_template() -> TemplateVersion:
    return TemplateVersion(
        template_id="software-request",
        version="1.0",
        schema_version="1.0",
        fields=(
            TemplateField(
                "title",
                "Request title",
                FieldKind.TEXT,
                required=True,
                minimum_length=3,
                maximum_length=120,
            ),
            TemplateField(
                "business_need",
                "Business need",
                FieldKind.TEXT,
                required=True,
                minimum_length=10,
                maximum_length=2000,
            ),
            TemplateField(
                "urgency",
                "Urgency",
                FieldKind.CHOICE,
                required=True,
                choices=("low", "medium", "high"),
            ),
            TemplateField(
                "budget",
                "Budget",
                FieldKind.NUMBER,
                required=True,
                minimum_number=0,
            ),
            TemplateField(
                "requested_date",
                "Requested date",
                FieldKind.DATE,
                required=False,
            ),
            TemplateField(
                "must_complete_by",
                "Must complete by",
                FieldKind.DATE,
                required=False,
            ),
        ),
        contradiction_rules=(
            ContradictionRule(
                "requested_date",
                "date_after",
                "must_complete_by",
                "Requested date cannot be after the must-complete-by date.",
            ),
        ),
        quality_threshold=1.0,
        confidence_threshold=0.7,
        maximum_clarification_attempts=3,
        mandatory_handover=True,
    )


def _actor(actor_id: str, role: ActorRole, agent_kind: AgentKind) -> ActorContext:
    return ActorContext(
        tenant_id=LOCAL_TENANT_ID,
        actor_id=actor_id,
        roles=frozenset({role}),
        provenance=Provenance(
            agent_kind=agent_kind,
            agent_version="local-1.0",
            instructions_version="1.0",
            model_version="none",
            toolbox_version="local-1.0",
            mcp_contract_version="1.0",
            policy_version="1.0",
        ),
        correlation_id=str(uuid4()),
    )


def _response(outcome: Outcome) -> ToolResponse:
    if outcome.error is not None:
        return ToolResponse(
            ok=False,
            replayed=outcome.replayed,
            error=ErrorDetail(
                code=ContractErrorCode(outcome.error.code.value),
                message=outcome.error.message,
                fieldPath=outcome.error.field_path,
                latestRevision=outcome.error.latest_revision,
                retryable=outcome.error.retryable,
            ),
        )
    return ToolResponse(ok=outcome.ok, replayed=outcome.replayed, data=outcome.data)
