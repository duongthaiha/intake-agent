"""Unit tests for domain entity construction, fields, and validation.

These tests use the reference implementations from tests/fixtures and will
also pass once Trinity delivers src/intake_domain.
"""
from __future__ import annotations

import uuid
from datetime import UTC

import pytest
from reference_domain import (
    ActorType,
    FieldValue,
    Gap,
    GapCategory,
    GapSeverity,
    GapStatus,
    Request,
    RequestRevision,
    RequestStatus,
    Review,
    ReviewDecision,
    ValidationStatus,
    WorkflowEvent,
    derive_request_id,
    make_request,
    make_revision,
    now,
)

pytestmark = pytest.mark.unit


class TestRequestEntity:
    def test_request_has_required_fields(self, new_request: Request):
        assert new_request.request_id
        assert new_request.tenant_id
        assert new_request.conversation_id
        assert new_request.requester_id
        assert new_request.status == RequestStatus.NEW
        assert new_request.current_revision == 1
        assert new_request.template_id
        assert new_request.template_version
        assert new_request.created_at.tzinfo is not None
        assert new_request.updated_at.tzinfo is not None
        assert new_request.etag

    def test_request_id_is_string(self, new_request: Request):
        assert isinstance(new_request.request_id, str)

    def test_request_created_at_is_utc(self, new_request: Request):
        assert new_request.created_at.tzinfo == UTC

    def test_request_initial_status_is_new(self):
        req = make_request()
        assert req.status == RequestStatus.NEW

    def test_request_etag_is_nonempty(self, new_request: Request):
        assert len(new_request.etag) > 0


class TestRequestRevision:
    def test_revision_has_required_fields(self, new_revision: RequestRevision):
        assert new_revision.request_id
        assert new_revision.revision == 1
        assert isinstance(new_revision.fields, dict)
        assert isinstance(new_revision.gaps, list)
        assert new_revision.agent_version
        assert new_revision.template_version
        assert new_revision.created_at is not None

    def test_revision_not_immutable_by_default(self, new_revision: RequestRevision):
        assert new_revision.immutable is False

    def test_revision_can_be_frozen(self, new_request: Request):
        rev = make_revision(new_request.request_id, immutable=True)
        assert rev.immutable is True

    def test_revision_quality_score_optional(self, new_request: Request):
        rev = make_revision(new_request.request_id, quality_score=None)
        assert rev.quality_score is None

    def test_revision_quality_score_set(self, new_request: Request):
        rev = make_revision(new_request.request_id, quality_score=0.87)
        assert rev.quality_score == pytest.approx(0.87)


class TestFieldValue:
    def test_field_value_construction(self, field_value: FieldValue):
        assert field_value.field_path == "project.name"
        assert field_value.value == "Customer Portal Redesign"
        assert field_value.source_reference is not None
        assert field_value.model_confidence == pytest.approx(0.95)
        assert field_value.validation_status == ValidationStatus.VALID

    def test_field_value_optional_fields(self):
        fv = FieldValue(field_path="project.name", value="X")
        assert fv.source_reference is None
        assert fv.model_confidence is None
        assert fv.validation_status == ValidationStatus.PENDING

    def test_field_value_confidence_range(self):
        for confidence in [0.0, 0.5, 1.0]:
            fv = FieldValue("f", "v", model_confidence=confidence)
            assert 0.0 <= fv.model_confidence <= 1.0


class TestGap:
    def test_gap_construction(self, blocking_gap: Gap):
        assert blocking_gap.gap_id
        assert blocking_gap.field_path
        assert blocking_gap.category == GapCategory.MISSING
        assert blocking_gap.severity == GapSeverity.BLOCKING
        assert blocking_gap.status == GapStatus.OPEN

    def test_gap_default_status_is_open(self):
        g = Gap("g-1", "f.path", GapCategory.AMBIGUOUS, GapSeverity.WARNING)
        assert g.status == GapStatus.OPEN

    def test_gap_categories(self):
        for cat in GapCategory:
            g = Gap("g", "f", cat, GapSeverity.WARNING)
            assert g.category == cat

    def test_gap_severities(self):
        for sev in GapSeverity:
            g = Gap("g", "f", GapCategory.MISSING, sev)
            assert g.severity == sev

    def test_gap_status_transitions(self):
        g = Gap("g", "f", GapCategory.MISSING, GapSeverity.BLOCKING)
        g.status = GapStatus.RESOLVED
        assert g.status == GapStatus.RESOLVED
        g.status = GapStatus.ACCEPTED
        assert g.status == GapStatus.ACCEPTED


class TestRequestStatus:
    def test_all_status_values_exist(self):
        expected = {"new", "in_review", "awaiting_feedback", "approved", "rejected", "completed"}
        actual = {s.value for s in RequestStatus}
        assert actual == expected

    def test_status_is_string_enum(self):
        assert isinstance(RequestStatus.NEW, str)
        assert RequestStatus.NEW == "new"


class TestDeterministicRequestId:
    def test_same_inputs_produce_same_id(self):
        id1 = derive_request_id("tenant-1", "conv-1")
        id2 = derive_request_id("tenant-1", "conv-1")
        assert id1 == id2

    def test_different_tenant_produces_different_id(self):
        id1 = derive_request_id("tenant-1", "conv-1")
        id2 = derive_request_id("tenant-2", "conv-1")
        assert id1 != id2

    def test_different_conversation_produces_different_id(self):
        id1 = derive_request_id("tenant-1", "conv-1")
        id2 = derive_request_id("tenant-1", "conv-2")
        assert id1 != id2

    def test_id_is_nonempty_string(self):
        rid = derive_request_id("t", "c")
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_request_factory_uses_derive(self):
        req = make_request(tenant_id="t-abc", conversation_id="c-xyz")
        expected = derive_request_id("t-abc", "c-xyz")
        assert req.request_id == expected


class TestReview:
    def test_review_construction(self):
        r = Review(
            review_id=str(uuid.uuid4()),
            reviewer_id="reviewer-1",
            decision=ReviewDecision.APPROVE,
            rationale="All fields verified.",
            decided_at=now(),
        )
        assert r.decision == ReviewDecision.APPROVE

    def test_review_pending_has_no_decision(self):
        r = Review(
            review_id=str(uuid.uuid4()),
            reviewer_id="reviewer-1",
            decision=None,
            rationale="",
            decided_at=None,
        )
        assert r.decision is None
        assert r.decided_at is None


class TestWorkflowEvent:
    def test_workflow_event_construction(self, new_request: Request):
        evt = WorkflowEvent(
            event_id=str(uuid.uuid4()),
            request_id=new_request.request_id,
            revision=1,
            actor_id="user-1",
            actor_type=ActorType.USER,
            command_id=str(uuid.uuid4()),
            prior_state=None,
            new_state=RequestStatus.NEW,
            occurred_at=now(),
        )
        assert evt.request_id == new_request.request_id
        assert evt.new_state == RequestStatus.NEW
