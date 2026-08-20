from conftest import fill_required_fields
from intake_domain import ActorContext, ActorRole, AgentKind
from intake_mcp import LocalProfile


def test_capture_autosave_resume_and_cross_variant_state(profile: LocalProfile) -> None:
    profile.record_conversation_message(
        "conversation-resume", "user", "I need a finance portal."
    )
    profile.record_conversation_message(
        "conversation-resume", "assistant", "I will capture the request."
    )
    history = profile.conversation_history.list("conversation-resume")
    assert [entry.sequence for entry in history] == [1, 2]
    assert history[0].content == "I need a finance portal."

    hosted = profile.service.get_intake_context(
        profile.requester(agent_kind=AgentKind.HOSTED), "conversation-resume"
    )
    assert hosted.ok and hosted.data is not None
    request_id = str(hosted.data["requestId"])
    assert hosted.data["requestRevision"] == 0
    assert len(hosted.data["gaps"]) == 4

    saved = profile.update_intake_field(
        request_id,
        0,
        "save-title",
        "title",
        "Finance portal",
        "message:1:0-14",
        0.93,
    )
    assert saved.ok and saved.data is not None
    assert saved.data["requestRevision"] == 1
    assert saved.data["acceptedField"]["sourceReference"] == "message:1:0-14"

    prompt = profile.service.get_intake_context(
        profile.requester(agent_kind=AgentKind.PROMPT), "conversation-resume"
    )
    assert prompt.ok and prompt.data is not None
    assert prompt.data["requestId"] == request_id
    assert prompt.data["requestRevision"] == 1
    assert prompt.data["fields"][0]["value"] == "Finance portal"

    listed = profile.list_my_intake_requests()
    assert listed.ok and listed.data is not None
    assert listed.data["requests"] == [
        {
            "requestId": request_id,
            "requestRevision": 1,
            "immutableRevision": None,
            "status": "new",
            "templateId": "software-request",
            "updatedAt": listed.data["requests"][0]["updatedAt"],
        }
    ]
    assert "fields" not in listed.data["requests"][0]

    profile.reset()
    assert profile.conversation_history.list("conversation-resume") == ()


def test_low_confidence_limit_and_contradiction_block_submission(
    profile: LocalProfile,
) -> None:
    request_id, revision = fill_required_fields(profile, "quality")
    for index in range(3):
        low = profile.update_intake_field(
            request_id,
            revision,
            f"low-{index}",
            "title",
            "Uncertain title",
            f"message:{index}",
            0.4,
        )
        assert low.ok and low.data is not None
        revision = int(low.data["requestRevision"])

    blocked = profile.submit_intake_for_review(
        request_id, revision, "submit-low", confirmed=True
    )
    assert not blocked.ok
    assert blocked.error is not None
    assert blocked.error.code.value == "clarification_limit_reached"

    confirmed = profile.update_intake_field(
        request_id,
        revision,
        "confirm-title",
        "title",
        "Confirmed title",
        "message:confirmation",
        1.0,
    )
    assert confirmed.ok and confirmed.data is not None
    revision = int(confirmed.data["requestRevision"])
    first_date = profile.update_intake_field(
        request_id,
        revision,
        "date-1",
        "requested_date",
        "2027-06-20",
        "message:date",
        1.0,
    )
    assert first_date.ok and first_date.data is not None
    revision = int(first_date.data["requestRevision"])
    contradiction = profile.update_intake_field(
        request_id,
        revision,
        "date-2",
        "must_complete_by",
        "2027-06-01",
        "message:date",
        1.0,
    )
    assert contradiction.ok and contradiction.data is not None
    revision = int(contradiction.data["requestRevision"])
    assert contradiction.data["gaps"][0]["category"] == "contradiction"

    blocked_contradiction = profile.submit_intake_for_review(
        request_id, revision, "submit-contradiction", confirmed=True
    )
    assert not blocked_contradiction.ok
    assert blocked_contradiction.error is not None
    assert blocked_contradiction.error.code.value == "incomplete_request"


def test_optional_low_confidence_and_non_finite_numbers_are_rejected(
    profile: LocalProfile,
) -> None:
    request_id, revision = fill_required_fields(profile, "edge-validation")
    non_finite = profile.update_intake_field(
        request_id,
        revision,
        "nan-budget",
        "budget",
        "NaN",
        "message:nan",
        1.0,
    )
    assert not non_finite.ok
    assert non_finite.error is not None
    assert non_finite.error.code.value == "validation_failed"

    optional = profile.update_intake_field(
        request_id,
        revision,
        "uncertain-date",
        "requested_date",
        "2027-01-01",
        "message:date",
        0.1,
    )
    assert optional.ok and optional.data is not None
    assert optional.data["gaps"][0]["fieldPath"] == "requested_date"
    blocked = profile.submit_intake_for_review(
        request_id,
        int(optional.data["requestRevision"]),
        "submit-uncertain-optional",
        confirmed=True,
    )
    assert not blocked.ok
    assert blocked.error is not None
    assert blocked.error.code.value == "incomplete_request"


def test_stale_revision_replay_and_idempotency_conflict(profile: LocalProfile) -> None:
    context = profile.get_intake_context("replay")
    assert context.data is not None
    request_id = str(context.data["requestId"])
    arguments = (
        request_id,
        0,
        "command-1",
        "title",
        "Replay-safe title",
        "message:1",
        0.9,
    )
    first = profile.update_intake_field(*arguments)
    audit_count = len(profile.store.audit_events)
    outbox_count = len(profile.store.outbox_events)
    replay = profile.update_intake_field(*arguments)
    assert first.ok and replay.ok
    assert replay.replayed
    assert replay.data == first.data
    assert len(profile.store.audit_events) == audit_count
    assert len(profile.store.outbox_events) == outbox_count

    conflicting_key = profile.update_intake_field(
        request_id,
        0,
        "command-1",
        "title",
        "Different title",
        "message:1",
        0.9,
    )
    assert not conflicting_key.ok
    assert conflicting_key.error is not None
    assert conflicting_key.error.code.value == "idempotency_conflict"

    stale = profile.update_intake_field(
        request_id,
        0,
        "command-2",
        "business_need",
        "This edit was based on an old context.",
        "message:2",
        0.9,
    )
    assert not stale.ok
    assert stale.error is not None
    assert stale.error.code.value == "concurrency_conflict"
    assert stale.error.latest_revision == 1


def test_replay_cannot_cross_actor_boundary(profile: LocalProfile) -> None:
    context = profile.get_intake_context("cross-actor-replay")
    assert context.data is not None
    request_id = str(context.data["requestId"])
    first = profile.service.update_intake_field(
        profile.requester(),
        request_id,
        0,
        "shared-command-id",
        "title",
        "Protected response",
        "message:1",
        1.0,
    )
    assert first.ok
    requester = profile.requester()
    attacker = ActorContext(
        tenant_id=requester.tenant_id,
        actor_id="requester-2",
        roles=frozenset({ActorRole.REQUESTER}),
        provenance=requester.provenance,
        correlation_id="attacker",
    )
    replay = profile.service.update_intake_field(
        attacker,
        request_id,
        0,
        "shared-command-id",
        "title",
        "Protected response",
        "message:1",
        1.0,
    )
    assert not replay.ok
    assert replay.data is None
    assert replay.error is not None
    assert replay.error.code.value == "authorization_denied"
