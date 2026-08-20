from __future__ import annotations

from conftest import fill_required_fields
from intake_domain import ActorContext, ActorRole, AgentKind, Provenance
from intake_mcp import LocalProfile
from intake_workers import (
    CompletionWorker,
    ContractTestDownstreamStub,
    ContractTestIntegrationPort,
    IntegrationWorker,
    ServiceCommandFacade,
)


def test_versioned_authenticated_handover_is_idempotent() -> None:
    profile = LocalProfile()
    request_id, revision = fill_required_fields(profile, "worker-handover")
    submitted = profile.service.submit_intake_for_review(
        profile.requester(),
        request_id,
        revision,
        "submit-worker",
        confirmed=True,
    )
    assert submitted.ok and submitted.data is not None
    approved = profile.service.decide_intake_review(
        profile.reviewer(),
        request_id,
        int(submitted.data["requestRevision"]),
        "approve-worker",
        "approve",
        "Ready for the contract test.",
    )
    assert approved.ok and approved.data is not None

    commands = ServiceCommandFacade(
        profile.service,
        profile.store,
        integration_actor=_service_actor(
            "integration-worker", ActorRole.INTEGRATION_WORKER
        ),
        notification_actor=_service_actor(
            "notification-worker", ActorRole.NOTIFICATION_WORKER
        ),
        completion_actor=_service_actor(
            "completion-worker", ActorRole.COMPLETION_WORKER
        ),
        retention_actor=_service_actor(
            "retention-worker", ActorRole.RETENTION_WORKER
        ),
    )
    stub = ContractTestDownstreamStub("test-token")
    integration = ContractTestIntegrationPort(stub, "test-token")
    event = {
        "eventId": "delivery-event-1",
        "eventType": "DeliveryRequested",
        "eventVersion": "1.0",
        "requestId": request_id,
        "revision": int(approved.data["requestRevision"]),
        "correlationId": "correlation-1",
        "data": {},
    }
    worker = IntegrationWorker(
        profile.store,
        integration,
        commands,
        target_name="contract-test-stub",
    )

    worker.handle(event)

    delivered = profile.store.get(request_id)
    assert delivered is not None
    assert delivered.delivery_status.value == "succeeded"
    assert len(stub.accepted) == 1
    payload = stub.accepted[0]
    assert payload.contract_version == "1.0"
    assert payload.approved_revision == 1
    assert payload.request_id == request_id
    assert payload.fields[0].source_reference

    duplicate = integration.deliver(
        payload,
        idempotency_key="direct-contract-replay",
    )
    replay = integration.deliver(
        payload,
        idempotency_key="direct-contract-replay",
    )
    assert duplicate.accepted
    assert replay.duplicate

    CompletionWorker(commands).handle(
        {
            **event,
            "eventId": "completion-event-1",
            "eventType": "DeliveryCompleted",
        }
    )
    completed = profile.store.get(request_id)
    assert completed is not None
    assert completed.status.value == "completed"


def test_service_only_delivery_command_rejects_requester_actor() -> None:
    profile = LocalProfile()
    context = profile.get_intake_context("service-only")
    assert context.data is not None

    denied = profile.service.record_delivery_result(
        profile.requester(),
        str(context.data["requestId"]),
        0,
        "forbidden-service-command",
        "target",
        "succeeded",
    )

    assert not denied.ok
    assert denied.error is not None
    assert denied.error.code.value == "authorization_denied"


def _service_actor(actor_id: str, role: ActorRole) -> ActorContext:
    return ActorContext(
        tenant_id="local-tenant",
        actor_id=actor_id,
        roles=frozenset({role}),
        provenance=Provenance(
            agent_kind=AgentKind.SERVICE,
            agent_version="1.0",
            instructions_version="none",
            model_version="none",
            toolbox_version="none",
            mcp_contract_version="1.0",
            policy_version="1.0",
        ),
        correlation_id=f"service:{actor_id}",
    )
