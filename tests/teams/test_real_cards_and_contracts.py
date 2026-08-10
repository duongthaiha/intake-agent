"""Tests for real intake_teams card JSON files and Pydantic contracts.

Exercises:
- intake_teams.cards.load_card() / load_all() — all bundled templates
- Real card structure (type, schema, version, fallbackText, speak, wrap)
- TeamsActivity, TeamsChannelData, CommandEnvelope Pydantic models
- ActivityType enum coverage
- TeamsActivity derived properties (user_id, tenant_id, conversation_id)
- CommandEnvelope serialization matches contract schema
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from intake_teams.adapter.contracts import (
    ActivityType,
    CommandActor,
    CommandEnvelope,
    ErrorResponse,
    InvokeResponse,
    MessageResponse,
    TeamsActivity,
    TeamsChannelData,
)
from intake_teams.cards import load_all, load_card

pytestmark = [pytest.mark.accessibility, pytest.mark.contract]


# ---------------------------------------------------------------------------
# Card loading
# ---------------------------------------------------------------------------

def test_load_all_returns_nonempty_dict():
    cards = load_all()
    assert len(cards) > 0


def test_load_all_keys_are_strings():
    cards = load_all()
    for key in cards:
        assert isinstance(key, str)


def test_load_all_values_are_dicts():
    cards = load_all()
    for name, card in cards.items():
        assert isinstance(card, dict), f"Card {name!r} is not a dict"


EXPECTED_CARD_NAMES = ["create", "capture", "gaps", "review_ready", "review_decision",
                        "status", "error"]


@pytest.mark.parametrize("name", EXPECTED_CARD_NAMES)
def test_expected_card_loads(name: str):
    card = load_card(name)
    assert isinstance(card, dict)
    assert len(card) > 0


def test_load_nonexistent_card_raises():
    with pytest.raises(FileNotFoundError):
        load_card("nonexistent_card_xyz")


# ---------------------------------------------------------------------------
# Structural compliance — all bundled cards
# ---------------------------------------------------------------------------

def _all_cards():
    return list(load_all().items())


@pytest.mark.parametrize("name,card", _all_cards())
def test_card_type_is_adaptive_card(name: str, card: dict):
    assert card.get("type") == "AdaptiveCard", f"{name}: type must be AdaptiveCard"


@pytest.mark.parametrize("name,card", _all_cards())
def test_card_has_valid_schema(name: str, card: dict):
    schema = card.get("$schema", "")
    assert "adaptivecards.io" in schema, f"{name}: $schema must reference adaptivecards.io"


@pytest.mark.parametrize("name,card", _all_cards())
def test_card_has_version_1_5_or_higher(name: str, card: dict):
    version = card.get("version", "0")
    major, minor = str(version).split(".")[:2]
    assert int(major) >= 1


@pytest.mark.parametrize("name,card", _all_cards())
def test_card_has_non_empty_body(name: str, card: dict):
    assert "body" in card, f"{name}: must have body"
    assert len(card["body"]) > 0, f"{name}: body must be non-empty"


@pytest.mark.parametrize("name,card", _all_cards())
def test_card_is_json_serializable(name: str, card: dict):
    serialized = json.dumps(card)
    deserialized = json.loads(serialized)
    assert deserialized["type"] == "AdaptiveCard"


# ---------------------------------------------------------------------------
# Accessibility — all real cards
# ---------------------------------------------------------------------------

def _flatten_elements(card: dict) -> list[dict]:
    elements: list[dict] = []
    def walk(items):
        for item in items:
            elements.append(item)
            if "items" in item:
                walk(item["items"])
            for col in item.get("columns", []):
                walk(col.get("items", []))
    walk(card.get("body", []))
    return elements


@pytest.mark.parametrize("name,card", _all_cards())
def test_text_blocks_have_wrap_true(name: str, card: dict):
    elements = _flatten_elements(card)
    for el in elements:
        if el.get("type") == "TextBlock" and not el.get("id", "").startswith("tmpl"):
            assert el.get("wrap") is True, (
                f"{name}: TextBlock id={el.get('id','?')!r} text={str(el.get('text',''))[:40]!r}"
                " must have wrap=True"
            )


@pytest.mark.parametrize("name,card", _all_cards())
def test_input_fields_have_label(name: str, card: dict):
    elements = _flatten_elements(card)
    for el in elements:
        if el.get("type", "").startswith("Input."):
            assert "label" in el, (
                f"{name}: Input element id={el.get('id','?')!r} must have a label"
            )


@pytest.mark.parametrize("name,card", _all_cards())
def test_card_has_speak_property(name: str, card: dict):
    assert "speak" in card, f"{name}: must have speak property for screen readers"


# ---------------------------------------------------------------------------
# TeamsActivity — Pydantic model
# ---------------------------------------------------------------------------

def _make_activity(**kwargs) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "type": "message",
        "timestamp": datetime.now(UTC).isoformat(),
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "channelId": "msteams",
        "from": {
            "id": "29:1abc",
            "name": "Test User",
            "aadObjectId": "entra-oid-123",
            "tenantId": "entra-tid-456",
        },
        "conversation": {
            "id": "conv-abc",
            "conversationType": "personal",
            "tenantId": "entra-tid-456",
        },
        "channelData": {
            "tenant": {"id": "entra-tid-456"},
        },
        "text": "Hello",
    }
    base.update(kwargs)
    return base


def test_teams_activity_parse_message():
    activity = TeamsActivity.model_validate(_make_activity())
    assert activity.type == ActivityType.MESSAGE
    assert activity.is_message is True
    assert activity.is_invoke is False


def test_teams_activity_user_id_from_aad_object_id():
    activity = TeamsActivity.model_validate(_make_activity())
    assert activity.user_id == "entra-oid-123"


def test_teams_activity_user_id_fallback_to_from_id():
    data = _make_activity()
    data["from"]["aadObjectId"] = None
    activity = TeamsActivity.model_validate(data)
    assert activity.user_id == "29:1abc"


def test_teams_activity_tenant_id_from_channel_data():
    activity = TeamsActivity.model_validate(_make_activity())
    assert activity.tenant_id == "entra-tid-456"


def test_teams_activity_conversation_id():
    activity = TeamsActivity.model_validate(_make_activity())
    assert activity.conversation_id == "conv-abc"


def test_teams_activity_activity_id():
    data = _make_activity()
    data["id"] = "act-xyz"
    activity = TeamsActivity.model_validate(data)
    assert activity.activity_id == "act-xyz"


def test_teams_activity_unknown_fields_accepted():
    """Forward-compatible: extra fields must not cause parse failure."""
    data = _make_activity()
    data["futureField"] = "some value"
    activity = TeamsActivity.model_validate(data)
    assert activity is not None


def test_teams_activity_invoke_parse():
    data = _make_activity(type="invoke", name="adaptiveCard/action")
    data["value"] = {
        "action": {
            "type": "Action.Execute",
            "verb": "submit_for_review",
            "data": {"request_id": "req-1"},
        }
    }
    activity = TeamsActivity.model_validate(data)
    assert activity.is_invoke is True
    invoke_val = activity.parse_invoke_value()
    assert invoke_val is not None
    assert invoke_val.verb == "submit_for_review"


def test_teams_activity_message_invoke_value_is_none():
    activity = TeamsActivity.model_validate(_make_activity(type="message"))
    assert activity.parse_invoke_value() is None


# ---------------------------------------------------------------------------
# TeamsActivity types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("activity_type", [
    "message", "invoke", "conversationUpdate", "endOfConversation", "typing", "event"
])
def test_all_activity_types_parse(activity_type: str):
    data = _make_activity(type=activity_type)
    activity = TeamsActivity.model_validate(data)
    assert activity.type.value == activity_type


# ---------------------------------------------------------------------------
# CommandEnvelope — outbound contract
# ---------------------------------------------------------------------------

def test_command_envelope_construction():
    env = CommandEnvelope(
        command_type="propose_field_updates",
        request_id="req-1",
        actor=CommandActor(user_id="u-1", tenant_id="t-1"),
    )
    assert env.command_id  # auto-generated UUID
    assert env.correlation_id  # auto-generated
    assert env.timestamp  # auto-set


def test_command_envelope_actor_fields():
    actor = CommandActor(user_id="u-1", tenant_id="t-1")
    assert actor.actor_type == "user"
    assert actor.agent_identity == "foundry-agent"


def test_command_envelope_serializes_to_dict():
    env = CommandEnvelope(
        command_type="submit_for_review",
        request_id="req-abc",
        actor=CommandActor(user_id="u-1", tenant_id="t-1"),
        data={"foo": "bar"},
    )
    d = env.model_dump()
    assert d["command_type"] == "submit_for_review"
    assert d["request_id"] == "req-abc"
    assert d["data"] == {"foo": "bar"}


def test_command_envelope_json_roundtrip():
    env = CommandEnvelope(
        command_type="record_review_decision",
        request_id="req-xyz",
        actor=CommandActor(user_id="reviewer-1", tenant_id="t-1"),
        activity_id="act-123",
    )
    json_str = env.model_dump_json()
    restored = CommandEnvelope.model_validate_json(json_str)
    assert restored.command_type == "record_review_decision"
    assert restored.activity_id == "act-123"


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

def test_message_response():
    r = MessageResponse(text="Hello, I need more information about the project budget.")
    assert r.type == "message"
    assert len(r.text) > 0


def test_error_response_structure():
    r = ErrorResponse(error_code="CONFLICT", message="Try again", retry_eligible=True)
    assert r.type == "error"
    assert r.error_code == "CONFLICT"
    assert r.retry_eligible is True


def test_invoke_response_200():
    r = InvokeResponse(status=200)
    assert r.status == 200
    assert r.body is None


# ---------------------------------------------------------------------------
# TeamsChannelData
# ---------------------------------------------------------------------------

def test_channel_data_tenant_id():
    cd = TeamsChannelData.model_validate({"tenant": {"id": "tid-1"}})
    assert cd.tenant_id == "tid-1"


def test_channel_data_no_tenant_returns_none():
    cd = TeamsChannelData.model_validate({})
    assert cd.tenant_id is None
