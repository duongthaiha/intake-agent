"""Teams Adaptive Card static fixture tests.

These tests validate the JSON structure, required properties, and
accessibility attributes of Adaptive Card templates without requiring
Teams/Bot Service/Foundry.

Source: ADR-014 (Teams as adapter), Neo's spike scope.
Tests target the documented public interface:
  - Cards live in src/intake_teams/cards/ (Neo's package)
  - When that package is absent, tests validate fixture JSON directly.

All tests are static (no HTTP/Teams API calls).
"""
from __future__ import annotations

import importlib.util
import json

import pytest

pytestmark = [pytest.mark.accessibility, pytest.mark.contract]


# ---------------------------------------------------------------------------
# Reference Adaptive Card fixtures (embedded)
# These represent the expected card templates Neo will deliver.
# ---------------------------------------------------------------------------

def make_gap_notification_card() -> dict:
    """Reference fixture for a gap notification Adaptive Card."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Missing information detected",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "The following required fields need attention:",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Field", "value": "project.budget"},
                    {"title": "Issue", "value": "Required field is missing"},
                    {"title": "Severity", "value": "Blocking"},
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Provide Budget",
                "data": {"action": "provide_field", "field_path": "project.budget"},
            }
        ],
        "fallbackText": (
            "Adaptive Cards require a supported client. "
            "Please provide the missing budget field."
        ),
        "speak": "Missing information detected. Please provide the project budget.",
    }


def make_review_ready_card() -> dict:
    """Reference fixture for a review-ready notification card."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Request Ready for Review",
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    "All required fields have been captured. "
                    "Your request has been submitted for review."
                ),
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Request ID", "value": "req-12345"},
                    {"title": "Template", "value": "general-intake-v1"},
                    {"title": "Revision", "value": "3"},
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "View Request",
                "url": "https://teams.example.com/intake/req-12345",
            }
        ],
        "fallbackText": "Your intake request has been submitted for review.",
        "speak": "Request ready for review. All required fields have been captured.",
    }


def make_approval_decision_card() -> dict:
    """Reference fixture for a reviewer approval card."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Review Decision Required",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Please review the intake request and make a decision.",
                "wrap": True,
            },
            {
                "type": "Input.Text",
                "id": "rationale",
                "label": "Rationale (required for rejection)",
                "isMultiline": True,
                "placeholder": "Provide your rationale if rejecting or requesting changes...",
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "style": "positive",
                "data": {"action": "record_review_decision", "decision": "approve"},
            },
            {
                "type": "Action.Submit",
                "title": "Reject",
                "style": "destructive",
                "data": {"action": "record_review_decision", "decision": "reject"},
            },
            {
                "type": "Action.Submit",
                "title": "Request Changes",
                "data": {"action": "record_review_decision", "decision": "request_changes"},
            },
        ],
        "fallbackText": "Review request pending. Please use the Teams app to review this request.",
        "speak": "Review decision required. Please approve, reject, or request changes.",
    }


CARD_FIXTURES = {
    "gap_notification": make_gap_notification_card,
    "review_ready": make_review_ready_card,
    "approval_decision": make_approval_decision_card,
}


# ---------------------------------------------------------------------------
# Helper: walk card body recursively
# ---------------------------------------------------------------------------

def _flatten_body_elements(card: dict) -> list[dict]:
    """Recursively collect all body elements from a card."""
    elements = []
    def _walk(items):
        for item in items:
            elements.append(item)
            if "items" in item:
                _walk(item["items"])
            if "columns" in item:
                for col in item["columns"]:
                    _walk(col.get("items", []))
    _walk(card.get("body", []))
    return elements


# ---------------------------------------------------------------------------
# Structural compliance tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_has_type_adaptive_card(name: str, factory):
    card = factory()
    assert card["type"] == "AdaptiveCard", f"{name}: type must be AdaptiveCard"


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_has_schema(name: str, factory):
    card = factory()
    assert "$schema" in card, f"{name}: must have $schema"
    assert "adaptivecards.io" in card["$schema"]


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_has_version(name: str, factory):
    card = factory()
    assert "version" in card, f"{name}: must have version"
    major, minor = card["version"].split(".")
    assert int(major) >= 1


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_has_non_empty_body(name: str, factory):
    card = factory()
    assert "body" in card
    assert len(card["body"]) > 0


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_is_json_serializable(name: str, factory):
    card = factory()
    serialized = json.dumps(card)
    deserialized = json.loads(serialized)
    assert deserialized["type"] == "AdaptiveCard"


# ---------------------------------------------------------------------------
# Accessibility checks (WCAG 2.2 AA relevant properties)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_has_fallback_text(name: str, factory):
    """fallbackText must be present for screen reader fallback in unsupported clients."""
    card = factory()
    assert "fallbackText" in card, f"{name}: must have fallbackText for accessibility"
    assert len(card["fallbackText"]) > 0


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_card_has_speak_property(name: str, factory):
    """speak property provides text for voice/screen reader narration."""
    card = factory()
    assert "speak" in card, f"{name}: must have speak property for screen readers"
    assert len(card["speak"]) > 0


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_all_text_blocks_have_wrap_true(name: str, factory):
    """TextBlock wrap=True prevents text truncation on small screens."""
    card = factory()
    elements = _flatten_body_elements(card)
    for element in elements:
        if element.get("type") == "TextBlock":
            assert element.get("wrap") is True, (
                f"{name}: TextBlock text={element.get('text','')!r} must have wrap=True"
            )


def test_approval_card_input_has_label():
    """Input fields must have label for screen reader association."""
    card = make_approval_decision_card()
    elements = _flatten_body_elements(card)
    for element in elements:
        if element.get("type", "").startswith("Input."):
            assert "label" in element, (
                f"Input element id={element.get('id')!r} must have a label"
            )


def test_approval_card_actions_have_meaningful_titles():
    """Action buttons must have descriptive titles, not just 'OK' or 'Submit'."""
    card = make_approval_decision_card()
    generic_titles = {"ok", "submit", "button", "click here"}
    for action in card.get("actions", []):
        title = action.get("title", "").lower()
        assert title not in generic_titles, (
            f"Action title {title!r} is too generic; use a descriptive label"
        )
        assert len(action["title"]) >= 3


@pytest.mark.parametrize("name,factory", list(CARD_FIXTURES.items()))
def test_no_sensitive_data_in_card_payload(name: str, factory):
    """Card action data must not contain auth tokens or credentials."""
    import re
    card = factory()
    serialized = json.dumps(card)
    for pattern in [r"password", r"secret", r"token", r"apikey", r"api_key"]:
        assert not re.search(pattern, serialized, re.I), (
            f"{name}: card JSON contains potentially sensitive key: {pattern!r}"
        )


# ---------------------------------------------------------------------------
# Action data contract
# ---------------------------------------------------------------------------

def test_submit_actions_include_action_field():
    """All Action.Submit data must include an 'action' discriminator field."""
    card = make_approval_decision_card()
    for action in card.get("actions", []):
        if action.get("type") == "Action.Submit":
            assert "action" in action.get("data", {}), (
                f"Action.Submit {action.get('title')!r} missing 'action' discriminator in data"
            )


def test_approval_action_data_has_decision_field():
    """Approval card submit actions must include 'decision' in data."""
    card = make_approval_decision_card()
    for action in card.get("actions", []):
        if action.get("type") == "Action.Submit":
            assert "decision" in action.get("data", {}), (
                f"Approval action {action.get('title')!r} missing 'decision' field"
            )


def test_gap_card_action_has_field_path():
    """Gap notification submit action must carry field_path for routing."""
    card = make_gap_notification_card()
    for action in card.get("actions", []):
        if action.get("type") == "Action.Submit":
            assert "field_path" in action.get("data", {})


# ---------------------------------------------------------------------------
# Neo's package integration (guarded — skips if not yet delivered)
# ---------------------------------------------------------------------------

_intake_teams_spec = importlib.util.find_spec("intake_teams")

@pytest.mark.skipif(
    _intake_teams_spec is None,
    reason="intake_teams package not yet installed (Neo's spike in progress)."
)
def test_intake_teams_cards_directory_exists():
    from intake_teams import cards  # type: ignore[import]
    assert cards is not None
