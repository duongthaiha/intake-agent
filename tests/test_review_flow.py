from dataclasses import replace

from conftest import fill_required_fields
from intake_domain import ActorContext, ActorRole
from intake_mcp import LocalProfile, default_template


def test_feedback_resubmit_approval_completion_and_handover(
    profile: LocalProfile,
) -> None:
    request_id, revision = fill_required_fields(profile, "approval")
    submitted = profile.submit_intake_for_review(
        request_id, revision, "submit-1", confirmed=True
    )
    assert submitted.ok and submitted.data is not None
    assert submitted.data["immutableRevision"] == 1
    revision = int(submitted.data["requestRevision"])

    assigned = profile.list_assigned_reviews()
    assert assigned.ok and assigned.data is not None
    assert assigned.data["requests"][0]["requestId"] == request_id
    review = profile.get_review_context(request_id)
    assert review.ok and review.data is not None
    assert review.data["immutableRevision"] == 1
    assert "decide_intake_review" in review.data["allowedActions"]

    comment = profile.add_review_comment(
        request_id,
        revision,
        "review-comment",
        "Please make the measurable outcome explicit.",
    )
    assert comment.ok and comment.data is not None
    revision = int(comment.data["requestRevision"])
    changes = profile.request_intake_changes(
        request_id,
        revision,
        "request-changes",
        "Add a measurable outcome before approval.",
    )
    assert changes.ok and changes.data is not None
    assert changes.data["status"] == "awaiting_user_feedback"
    revision = int(changes.data["requestRevision"])

    corrected = profile.update_intake_field(
        request_id,
        revision,
        "correct-need",
        "business_need",
        "Replace the unsupported workflow and reduce handling time by 30 percent.",
        "message:correction",
        0.99,
    )
    assert corrected.ok and corrected.data is not None
    revision = int(corrected.data["requestRevision"])
    resubmitted = profile.submit_intake_for_review(
        request_id, revision, "submit-2", confirmed=True
    )
    assert resubmitted.ok and resubmitted.data is not None
    assert resubmitted.data["immutableRevision"] == 2
    revision = int(resubmitted.data["requestRevision"])

    completed = profile.decide_intake_review(
        request_id,
        revision,
        "approve-2",
        "approve",
        "The revised request is complete and measurable.",
    )
    assert completed.ok and completed.data is not None
    assert completed.data["status"] == "completed"
    assert completed.data["approvedRevision"] == 2
    assert profile.handovers[0].approved_revision == 2
    request = profile.store.get(request_id)
    assert request is not None
    assert request.revisions[0].fields != request.revisions[1].fields
    assert request.approved_revision == request.revisions[1]
    assert request.revisions[0].fields[1].value == (
        "Replace the unsupported finance request workflow."
    )
    event_types = [event.event_type for event in profile.store.outbox_events]
    assert "RequestApproved" in event_types
    assert "DeliveryRequested" in event_types
    assert "DeliveryCompleted" in event_types
    assert event_types[-1] == "RequestCompleted"


def test_rejection_preserves_exact_revision(profile: LocalProfile) -> None:
    request_id, revision = fill_required_fields(profile, "rejection", command_prefix="reject")
    submitted = profile.submit_intake_for_review(
        request_id, revision, "reject-submit", confirmed=True
    )
    assert submitted.ok and submitted.data is not None
    rejected = profile.decide_intake_review(
        request_id,
        int(submitted.data["requestRevision"]),
        "reject-decision",
        "reject",
        "The requested outcome duplicates an existing service.",
    )
    assert rejected.ok and rejected.data is not None
    assert rejected.data["status"] == "rejected"
    assert rejected.data["approvedRevision"] is None
    assert profile.handovers == []
    request = profile.store.get(request_id)
    assert request is not None
    assert request.review_decisions[0].revision_number == 1


def test_approval_without_mandatory_handover_completes_without_delivery() -> None:
    profile = LocalProfile(
        template=replace(default_template(), mandatory_handover=False)
    )
    request_id, revision = fill_required_fields(profile, "no-handover")
    submitted = profile.submit_intake_for_review(
        request_id, revision, "submit-no-handover", confirmed=True
    )
    assert submitted.ok and submitted.data is not None

    completed = profile.decide_intake_review(
        request_id,
        int(submitted.data["requestRevision"]),
        "approve-no-handover",
        "approve",
        "The request is complete.",
    )

    assert completed.ok and completed.data is not None
    assert completed.data["status"] == "completed"
    assert completed.data["deliveryStatus"] == "not_required"
    assert profile.handovers == []


def test_authorization_assignment_and_separation_of_duties(
    profile: LocalProfile,
) -> None:
    request_id, revision = fill_required_fields(profile, "authorization", command_prefix="auth")
    requester = profile.requester()
    other_requester = ActorContext(
        tenant_id=requester.tenant_id,
        actor_id="requester-2",
        roles=frozenset({ActorRole.REQUESTER}),
        provenance=requester.provenance,
        correlation_id="other-requester",
    )
    denied_edit = profile.service.update_intake_field(
        other_requester,
        request_id,
        revision,
        "unauthorized-edit",
        "title",
        "Unauthorized title",
        "message:bad",
        1.0,
    )
    assert not denied_edit.ok
    assert denied_edit.error is not None
    assert denied_edit.error.code.value == "authorization_denied"

    submitted = profile.submit_intake_for_review(
        request_id, revision, "auth-submit", confirmed=True
    )
    assert submitted.ok and submitted.data is not None
    revision = int(submitted.data["requestRevision"])
    reviewer = profile.reviewer()
    unassigned = ActorContext(
        tenant_id=reviewer.tenant_id,
        actor_id="reviewer-2",
        roles=frozenset({ActorRole.REVIEWER}),
        provenance=reviewer.provenance,
        correlation_id="unassigned-reviewer",
    )
    denied_review = profile.service.get_review_context(unassigned, request_id)
    assert not denied_review.ok
    assert denied_review.error is not None
    assert denied_review.error.code.value == "authorization_denied"

    self_admin = ActorContext(
        tenant_id=requester.tenant_id,
        actor_id=requester.actor_id,
        roles=frozenset({ActorRole.ADMINISTRATOR, ActorRole.REVIEWER}),
        provenance=requester.provenance,
        correlation_id="self-admin",
    )
    separation = profile.service.decide_intake_review(
        self_admin,
        request_id,
        revision,
        "self-approve",
        "approve",
        "Attempted self approval.",
    )
    assert not separation.ok
    assert separation.error is not None
    assert separation.error.code.value == "separation_of_duties"


def test_completion_worker_cannot_cross_tenant_boundary(profile: LocalProfile) -> None:
    request_id, revision = fill_required_fields(
        profile, "worker-tenant", command_prefix="worker"
    )
    submitted = profile.submit_intake_for_review(
        request_id, revision, "worker-submit", confirmed=True
    )
    assert submitted.ok and submitted.data is not None
    approved = profile.service.decide_intake_review(
        profile.reviewer(),
        request_id,
        int(submitted.data["requestRevision"]),
        "worker-approve",
        "approve",
        "The request is ready for handover.",
    )
    assert approved.ok and approved.data is not None
    request_revision = int(approved.data["requestRevision"])
    worker = profile.worker()
    other_tenant_worker = ActorContext(
        tenant_id="other-tenant",
        actor_id=worker.actor_id,
        roles=worker.roles,
        provenance=worker.provenance,
        correlation_id="cross-tenant-worker",
    )

    delivery = profile.service.record_delivery_success(
        other_tenant_worker,
        request_id,
        request_revision,
        "cross-tenant-delivery",
        "target",
    )
    completion = profile.service.complete_request_if_ready(
        other_tenant_worker,
        request_id,
        request_revision,
        "cross-tenant-completion",
    )

    for outcome in (delivery, completion):
        assert not outcome.ok
        assert outcome.error is not None
        assert outcome.error.code.value == "authorization_denied"
