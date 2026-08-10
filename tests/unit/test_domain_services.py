"""Unit tests for the real domain services.

Covers LifecycleService, ValidationService, and GapDetectionService
from src/intake_domain/services/__init__.py.
"""
from __future__ import annotations

import pytest

from intake_domain.entities import (
    ActorContext,
    FieldSchema,
    FieldValue,
    Gap,
    GapCategory,
    GapSeverity,
    GapStatus,
    RequestRevision,
    RequestStatus,
    TemplateVersion,
    ValidationStatus,
)
from intake_domain.errors import InvalidTransitionError
from intake_domain.services import (
    GapDetectionService,
    LifecycleService,
    ValidationService,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def lifecycle() -> LifecycleService:
    return LifecycleService()


@pytest.fixture()
def validation() -> ValidationService:
    return ValidationService()


@pytest.fixture()
def gap_svc() -> GapDetectionService:
    return GapDetectionService()


@pytest.fixture()
def actor() -> ActorContext:
    return ActorContext(
        user_id="u-1",
        tenant_id="t-1",
        roles=frozenset(["requester"]),
        conversation_id="conv-1",
        activity_id="act-1",
        correlation_id="corr-1",
        agent_identity="agent-1",
    )


@pytest.fixture()
def basic_template() -> TemplateVersion:
    return TemplateVersion(
        template_id="test-template",
        version="1.0.0",
        display_name="Test",
        fields=[
            FieldSchema("name", "Name", "string", required=True),
            FieldSchema("budget", "Budget", "number", required=False),
            FieldSchema("priority", "Priority", "enum", required=True,
                        enum_values=["low", "medium", "high"]),
        ],
        quality_threshold=0.7,
    )


@pytest.fixture()
def empty_revision() -> RequestRevision:
    return RequestRevision(
        request_id="req-1",
        revision=1,
        fields={},
        gaps=[],
    )


# ---------------------------------------------------------------------------
# LifecycleService — assert_transition
# ---------------------------------------------------------------------------

VALID_TRANSITIONS = [
    (RequestStatus.NEW, RequestStatus.IN_REVIEW),
    (RequestStatus.IN_REVIEW, RequestStatus.APPROVED),
    (RequestStatus.IN_REVIEW, RequestStatus.REJECTED),
    (RequestStatus.IN_REVIEW, RequestStatus.AWAITING_FEEDBACK),
    (RequestStatus.AWAITING_FEEDBACK, RequestStatus.IN_REVIEW),
    (RequestStatus.APPROVED, RequestStatus.COMPLETED),
]


@pytest.mark.parametrize("src,dst", VALID_TRANSITIONS)
def test_lifecycle_valid_transitions(lifecycle, actor, src, dst):
    lifecycle.assert_transition(src, dst, actor)  # must not raise


INVALID_TRANSITIONS = [
    (RequestStatus.NEW, RequestStatus.APPROVED),
    (RequestStatus.NEW, RequestStatus.COMPLETED),
    (RequestStatus.REJECTED, RequestStatus.NEW),
    (RequestStatus.COMPLETED, RequestStatus.NEW),
    (RequestStatus.APPROVED, RequestStatus.NEW),
]


@pytest.mark.parametrize("src,dst", INVALID_TRANSITIONS)
def test_lifecycle_invalid_transitions_raise(lifecycle, actor, src, dst):
    with pytest.raises(InvalidTransitionError):
        lifecycle.assert_transition(src, dst, actor)


def test_lifecycle_error_message_contains_statuses(lifecycle, actor):
    with pytest.raises(InvalidTransitionError, match="new"):
        lifecycle.assert_transition(RequestStatus.NEW, RequestStatus.COMPLETED, actor)


# ---------------------------------------------------------------------------
# LifecycleService — assert_mutable
# ---------------------------------------------------------------------------

def test_assert_mutable_new_does_not_raise(lifecycle):
    lifecycle.assert_mutable(RequestStatus.NEW)  # must not raise


def test_assert_mutable_awaiting_feedback_does_not_raise(lifecycle):
    lifecycle.assert_mutable(RequestStatus.AWAITING_FEEDBACK)


@pytest.mark.parametrize("status", [
    RequestStatus.IN_REVIEW,
    RequestStatus.APPROVED,
    RequestStatus.REJECTED,
    RequestStatus.COMPLETED,
])
def test_assert_mutable_raises_for_non_mutable(lifecycle, status):
    with pytest.raises(InvalidTransitionError):
        lifecycle.assert_mutable(status)


# ---------------------------------------------------------------------------
# LifecycleService — allowed_actions
# ---------------------------------------------------------------------------

def test_allowed_actions_new_requester(lifecycle):
    actions = lifecycle.allowed_actions(RequestStatus.NEW, frozenset(["requester"]))
    assert "propose_field_updates" in actions
    assert "submit_for_review" in actions


def test_allowed_actions_in_review_reviewer(lifecycle):
    actions = lifecycle.allowed_actions(RequestStatus.IN_REVIEW, frozenset(["reviewer"]))
    assert "record_review_decision" in actions


def test_allowed_actions_in_review_non_reviewer(lifecycle):
    actions = lifecycle.allowed_actions(RequestStatus.IN_REVIEW, frozenset(["requester"]))
    assert "record_review_decision" not in actions


def test_allowed_actions_completed_has_no_mutation(lifecycle):
    actions = lifecycle.allowed_actions(RequestStatus.COMPLETED, frozenset(["admin"]))
    assert "propose_field_updates" not in actions
    assert "submit_for_review" not in actions


# ---------------------------------------------------------------------------
# ValidationService — validate_field
# ---------------------------------------------------------------------------

def test_validate_valid_string(validation):
    schema = FieldSchema("f", "F", "string", required=True)
    status, msg = validation.validate_field(schema, "hello")
    assert status == ValidationStatus.VALID


def test_validate_missing_required_field(validation):
    schema = FieldSchema("f", "F", "string", required=True)
    status, msg = validation.validate_field(schema, None)
    assert status == ValidationStatus.INVALID
    assert "missing" in msg.lower() or "required" in msg.lower()


def test_validate_missing_optional_field_is_valid(validation):
    schema = FieldSchema("f", "F", "string", required=False)
    status, msg = validation.validate_field(schema, None)
    assert status == ValidationStatus.VALID


def test_validate_valid_number(validation):
    schema = FieldSchema("budget", "Budget", "number")
    status, _ = validation.validate_field(schema, 50000)
    assert status == ValidationStatus.VALID


def test_validate_invalid_number_type(validation):
    schema = FieldSchema("budget", "Budget", "number")
    status, msg = validation.validate_field(schema, "not-a-number")
    assert status == ValidationStatus.INVALID
    assert "number" in msg.lower()


def test_validate_valid_number_as_string(validation):
    schema = FieldSchema("budget", "Budget", "number")
    status, _ = validation.validate_field(schema, "50000")
    assert status == ValidationStatus.VALID


def test_validate_valid_enum(validation):
    schema = FieldSchema("priority", "Priority", "enum", enum_values=["low", "medium", "high"])
    status, _ = validation.validate_field(schema, "high")
    assert status == ValidationStatus.VALID


def test_validate_invalid_enum(validation):
    schema = FieldSchema("priority", "Priority", "enum", enum_values=["low", "medium", "high"])
    status, msg = validation.validate_field(schema, "critical")
    assert status == ValidationStatus.INVALID
    assert "critical" in msg


def test_validate_boolean_valid(validation):
    schema = FieldSchema("flag", "Flag", "boolean")
    status, _ = validation.validate_field(schema, True)
    assert status == ValidationStatus.VALID


def test_validate_boolean_string_true(validation):
    schema = FieldSchema("flag", "Flag", "boolean")
    status, _ = validation.validate_field(schema, "true")
    assert status == ValidationStatus.VALID


def test_validate_boolean_invalid(validation):
    schema = FieldSchema("flag", "Flag", "boolean")
    status, msg = validation.validate_field(schema, "maybe")
    assert status == ValidationStatus.INVALID


# ---------------------------------------------------------------------------
# ValidationService — validate_updates
# ---------------------------------------------------------------------------

def test_validate_updates_unknown_field(validation, basic_template):
    results = validation.validate_updates(basic_template, [("unknown.field", "x")])
    assert results["unknown.field"][0] == ValidationStatus.INVALID


def test_validate_updates_mixed(validation, basic_template):
    results = validation.validate_updates(
        basic_template,
        [("name", "Portal"), ("budget", "not-a-number")],
    )
    assert results["name"][0] == ValidationStatus.VALID
    assert results["budget"][0] == ValidationStatus.INVALID


# ---------------------------------------------------------------------------
# GapDetectionService — detect_gaps
# ---------------------------------------------------------------------------

def test_detect_no_gaps_when_all_required_fields_filled(
    gap_svc, basic_template, empty_revision
):
    empty_revision.fields["name"] = FieldValue("name", "Portal")
    empty_revision.fields["priority"] = FieldValue("priority", "high")
    gaps = gap_svc.detect_gaps(basic_template, empty_revision)
    assert not any(
        g.severity == GapSeverity.BLOCKING for g in gaps
    )


def test_detect_blocking_gap_for_missing_required_field(
    gap_svc, basic_template, empty_revision
):
    empty_revision.fields["priority"] = FieldValue("priority", "high")
    # name is missing
    gaps = gap_svc.detect_gaps(basic_template, empty_revision)
    blocking = [g for g in gaps if g.severity == GapSeverity.BLOCKING]
    assert len(blocking) >= 1
    assert any(g.field_path == "name" for g in blocking)


def test_detect_warning_gap_for_low_confidence(
    gap_svc, basic_template, empty_revision
):
    empty_revision.fields["name"] = FieldValue(
        "name", "Portal", model_confidence=0.3  # below min_confidence=0.7
    )
    empty_revision.fields["priority"] = FieldValue("priority", "high")
    gaps = gap_svc.detect_gaps(basic_template, empty_revision)
    warnings = [g for g in gaps if g.severity == GapSeverity.WARNING]
    assert any(g.field_path == "name" for g in warnings)


def test_optional_field_missing_does_not_create_blocking_gap(
    gap_svc, basic_template, empty_revision
):
    empty_revision.fields["name"] = FieldValue("name", "Portal")
    empty_revision.fields["priority"] = FieldValue("priority", "high")
    # budget is optional — absent
    gaps = gap_svc.detect_gaps(basic_template, empty_revision)
    blocking = [g for g in gaps if g.severity == GapSeverity.BLOCKING]
    assert not any(g.field_path == "budget" for g in blocking)


# ---------------------------------------------------------------------------
# GapDetectionService — has_blocking_gaps
# ---------------------------------------------------------------------------

def test_has_blocking_gaps_true(gap_svc):
    gaps = [Gap("g-1", "name", GapCategory.MISSING, GapSeverity.BLOCKING, GapStatus.OPEN)]
    assert gap_svc.has_blocking_gaps(gaps) is True


def test_has_blocking_gaps_false_when_empty(gap_svc):
    assert gap_svc.has_blocking_gaps([]) is False


def test_has_blocking_gaps_false_when_resolved(gap_svc):
    gaps = [Gap("g-1", "name", GapCategory.MISSING, GapSeverity.BLOCKING, GapStatus.RESOLVED)]
    assert gap_svc.has_blocking_gaps(gaps) is False


def test_has_blocking_gaps_false_when_only_warnings(gap_svc):
    gaps = [Gap("g-1", "name", GapCategory.LOW_CONFIDENCE, GapSeverity.WARNING, GapStatus.OPEN)]
    assert gap_svc.has_blocking_gaps(gaps) is False


# ---------------------------------------------------------------------------
# GapDetectionService — compute_quality_score
# ---------------------------------------------------------------------------

def test_quality_score_all_fields_filled(gap_svc, basic_template, empty_revision):
    for f in basic_template.fields:
        empty_revision.fields[f.field_path] = FieldValue(f.field_path, "value")
    score = gap_svc.compute_quality_score(basic_template, empty_revision)
    assert score == pytest.approx(1.0)


def test_quality_score_no_fields_filled(gap_svc, basic_template, empty_revision):
    score = gap_svc.compute_quality_score(basic_template, empty_revision)
    assert score == pytest.approx(0.0)


def test_quality_score_partial(gap_svc, basic_template, empty_revision):
    # 1 of 3 fields
    empty_revision.fields["name"] = FieldValue("name", "Portal")
    score = gap_svc.compute_quality_score(basic_template, empty_revision)
    assert score == pytest.approx(1 / 3)


def test_quality_score_empty_template(gap_svc, empty_revision):
    empty_template = TemplateVersion("t", "1.0", "T", fields=[])
    score = gap_svc.compute_quality_score(empty_template, empty_revision)
    assert score == pytest.approx(1.0)
