"""Tests for intake_teams.adapter.parser (ActivityParser).

Covers the full translation surface:
- message → get_or_create_request
- invoke/capture_field → propose_field_updates
- invoke/submit_request → submit_for_review
- invoke/review_decision → record_review_decision (approve/reject/request_changes)
- invoke/acknowledge_gaps → acknowledge_gaps
- ParseError paths: bad activity type, bad invoke name, bad verb,
  missing field_path, missing value, bad decision value, bad gap_ids type
- deterministic request_id derivation
- expected_revision coercion (_int_or_none)
- agent_identity propagation
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from intake_teams.adapter.parser import ActivityParser, ParseError, _int_or_none

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _base_activity(
    activity_type: str = "message",
    *,
    user_id: str = "user-aad-001",
    tenant_id: str = "tenant-001",
    conversation_id: str = "conv-001",
    activity_id: str | None = None,
) -> dict:
    base = {
        "id": activity_id or str(uuid.uuid4()),
        "type": activity_type,
        "from": {
            "id": user_id,
            "aadObjectId": user_id,
            "tenantId": tenant_id,
        },
        "conversation": {"id": conversation_id, "tenantId": tenant_id},
        "channelData": {"tenant": {"id": tenant_id}},
    }
    return base


def _message_activity(text: str = "Hello", **kwargs) -> dict:
    d = _base_activity("message", **kwargs)
    d["text"] = text
    return d


def _invoke_activity(verb: str, data: dict, **kwargs) -> dict:
    d = _base_activity("invoke", **kwargs)
    d["name"] = "adaptiveCard/action"
    d["value"] = {"action": {"verb": verb, "data": data}}
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parser() -> ActivityParser:
    return ActivityParser()


# ---------------------------------------------------------------------------
# message → get_or_create_request
# ---------------------------------------------------------------------------

def test_parse_message_returns_get_or_create():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_message_activity("I need a new project"))
    env = _parser().parse(activity)
    assert env.command_type == "get_or_create_request"


def test_parse_message_propagates_user_id():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _message_activity("Hello", user_id="uid-42", tenant_id="tid-99")
    )
    env = _parser().parse(activity)
    assert env.actor.user_id == "uid-42"
    assert env.actor.tenant_id == "tid-99"


def test_parse_message_includes_text_in_data():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_message_activity("Project Aurora"))
    env = _parser().parse(activity)
    assert env.data["message_text"] == "Project Aurora"


def test_parse_message_empty_text_raises_parse_error():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_message_activity("   "))
    with pytest.raises(ParseError, match="no text content"):
        _parser().parse(activity)


def test_parse_message_deterministic_request_id():
    from intake_teams.adapter.contracts import TeamsActivity

    d = _message_activity("X", tenant_id="t1", conversation_id="c1")
    a1 = TeamsActivity.model_validate(d)
    a2 = TeamsActivity.model_validate(d)
    env1 = _parser().parse(a1)
    env2 = _parser().parse(a2)
    assert env1.request_id == env2.request_id


def test_request_id_derivation_matches_sha256_spec():
    from intake_teams.adapter.contracts import TeamsActivity

    d = _message_activity("X", tenant_id="t1", conversation_id="c1")
    activity = TeamsActivity.model_validate(d)
    env = _parser().parse(activity)
    expected = hashlib.sha256(b"t1:c1").hexdigest()[:32]
    assert env.request_id == expected


def test_parse_message_custom_agent_identity():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_message_activity("Hi"))
    env = _parser().parse(activity, agent_identity="my-custom-agent")
    assert env.actor.agent_identity == "my-custom-agent"


def test_parse_message_command_id_is_uuid():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_message_activity("Hi"))
    env = _parser().parse(activity)
    # Should not raise
    uuid.UUID(env.command_id)


def test_parse_message_idempotency_key_equals_command_id():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_message_activity("Hi"))
    env = _parser().parse(activity)
    assert env.idempotency_key == env.command_id


# ---------------------------------------------------------------------------
# invoke / capture_field → propose_field_updates
# ---------------------------------------------------------------------------

def test_parse_capture_field_command_type():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity(
            "capture_field",
            {"field_path": "project.name", "value": "Portal", "expected_revision": 2},
        )
    )
    env = _parser().parse(activity)
    assert env.command_type == "propose_field_updates"


def test_parse_capture_field_data_shape():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity(
            "capture_field",
            {"field_path": "project.name", "value": "Portal", "expected_revision": 2},
        )
    )
    env = _parser().parse(activity)
    updates = env.data["updates"]
    assert len(updates) == 1
    assert updates[0]["field_path"] == "project.name"
    assert updates[0]["value"] == "Portal"


def test_parse_capture_field_expected_revision_coerced():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("capture_field", {"field_path": "priority", "value": "high",
                                            "expected_revision": "5"})
    )
    env = _parser().parse(activity)
    assert env.expected_revision == 5


def test_parse_capture_field_missing_field_path_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("capture_field", {"value": "X"})
    )
    with pytest.raises(ParseError, match="field_path"):
        _parser().parse(activity)


def test_parse_capture_field_missing_value_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("capture_field", {"field_path": "project.name"})
    )
    with pytest.raises(ParseError, match="'value'"):
        _parser().parse(activity)


# ---------------------------------------------------------------------------
# invoke / submit_request → submit_for_review
# ---------------------------------------------------------------------------

def test_parse_submit_request_command_type():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("submit_request", {"expected_revision": 3})
    )
    env = _parser().parse(activity)
    assert env.command_type == "submit_for_review"


def test_parse_submit_request_no_revision():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(_invoke_activity("submit_request", {}))
    env = _parser().parse(activity)
    assert env.expected_revision is None


# ---------------------------------------------------------------------------
# invoke / review_decision → record_review_decision
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decision", ["approve", "reject", "request_changes"])
def test_parse_review_decision_valid_decisions(decision: str):
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity(
            "review_decision",
            {"decision": decision, "rationale": "Looks good", "expected_revision": 4},
        )
    )
    env = _parser().parse(activity)
    assert env.command_type == "record_review_decision"
    assert env.data["decision"] == decision
    assert env.data["rationale"] == "Looks good"


def test_parse_review_decision_invalid_decision_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("review_decision", {"decision": "maybe", "rationale": "?"})
    )
    with pytest.raises(ParseError, match="invalid 'decision'"):
        _parser().parse(activity)


def test_parse_review_decision_missing_rationale_defaults_empty():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("review_decision", {"decision": "approve"})
    )
    env = _parser().parse(activity)
    assert env.data["rationale"] == ""


# ---------------------------------------------------------------------------
# invoke / acknowledge_gaps → acknowledge_gaps
# ---------------------------------------------------------------------------

def test_parse_acknowledge_gaps_command_type():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("acknowledge_gaps", {"gap_ids": ["g1", "g2"]})
    )
    env = _parser().parse(activity)
    assert env.command_type == "acknowledge_gaps"
    assert env.data["gap_ids"] == ["g1", "g2"]


def test_parse_acknowledge_gaps_bad_type_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("acknowledge_gaps", {"gap_ids": "not-a-list"})
    )
    with pytest.raises(ParseError, match="must be a list"):
        _parser().parse(activity)


def test_parse_acknowledge_gaps_empty_list_ok():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("acknowledge_gaps", {"gap_ids": []})
    )
    env = _parser().parse(activity)
    assert env.data["gap_ids"] == []


# ---------------------------------------------------------------------------
# ParseError paths
# ---------------------------------------------------------------------------

def test_unsupported_activity_type_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    d = _base_activity("conversationUpdate")
    activity = TeamsActivity.model_validate(d)
    with pytest.raises(ParseError, match="Unsupported activity type"):
        _parser().parse(activity)


def test_invoke_with_wrong_name_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    d = _base_activity("invoke")
    d["name"] = "task/fetch"
    d["value"] = {"action": {"verb": "submit_request", "data": {}}}
    activity = TeamsActivity.model_validate(d)
    with pytest.raises(ParseError, match="Unsupported invoke name"):
        _parser().parse(activity)


def test_invoke_with_unknown_verb_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    activity = TeamsActivity.model_validate(
        _invoke_activity("fly_to_the_moon", {})
    )
    with pytest.raises(ParseError, match="Unknown invoke verb"):
        _parser().parse(activity)


def test_invoke_with_no_value_raises():
    from intake_teams.adapter.contracts import TeamsActivity

    d = _base_activity("invoke")
    d["name"] = "adaptiveCard/action"
    # no 'value' key at all
    activity = TeamsActivity.model_validate(d)
    with pytest.raises(ParseError, match="no parseable value"):
        _parser().parse(activity)


# ---------------------------------------------------------------------------
# _int_or_none helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, None),
    (3, 3),
    ("5", 5),
    ("abc", None),
    ([], None),
])
def test_int_or_none(value, expected):
    assert _int_or_none(value) == expected
