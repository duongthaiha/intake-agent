"""Contract tests: command and event schemas.

Validates the JSON envelope structure documented in
docs/contracts/command-event-schemas.md using pure Python.
No Azure credentials required; no production code imported.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Schema validation helpers (no external schema library required)
# ---------------------------------------------------------------------------

def _uuid_str() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_command_envelope(
    command_type: str,
    request_id: str | None = None,
    data: dict | None = None,
    expected_revision: int = 1,
) -> dict:
    return {
        "command_id": _uuid_str(),
        "command_type": command_type,
        "request_id": request_id or _uuid_str(),
        "expected_revision": expected_revision,
        "correlation_id": _uuid_str(),
        "idempotency_key": _uuid_str(),
        "actor": {
            "user_id": "entra-oid-abc",
            "tenant_id": "entra-tid-abc",
            "actor_type": "user",
            "agent_identity": "foundry-agent-msi-id",
        },
        "timestamp": _now_iso(),
        "data": data or {},
    }


def make_event_envelope(
    event_type: str,
    request_id: str | None = None,
    data: dict | None = None,
) -> dict:
    return {
        "event_id": _uuid_str(),
        "event_type": event_type,
        "event_version": "1.0",
        "request_id": request_id or _uuid_str(),
        "revision": 1,
        "correlation_id": _uuid_str(),
        "causation_id": _uuid_str(),
        "occurred_at": _now_iso(),
        "actor": {
            "user_id": "entra-oid-abc",
            "actor_type": "user",
        },
        "data": data or {},
    }


# ---------------------------------------------------------------------------
# Required command envelope fields
# ---------------------------------------------------------------------------

REQUIRED_COMMAND_FIELDS = [
    "command_id",
    "command_type",
    "request_id",
    "expected_revision",
    "correlation_id",
    "idempotency_key",
    "actor",
    "timestamp",
    "data",
]


@pytest.mark.parametrize("field", REQUIRED_COMMAND_FIELDS)
def test_command_envelope_has_required_field(field: str):
    envelope = make_command_envelope("propose_field_updates")
    assert field in envelope, f"Missing field: {field!r}"


def test_command_envelope_actor_has_required_fields():
    envelope = make_command_envelope("propose_field_updates")
    actor = envelope["actor"]
    for f in ("user_id", "tenant_id", "actor_type", "agent_identity"):
        assert f in actor, f"actor missing field {f!r}"


def test_command_id_is_uuid_string():
    envelope = make_command_envelope("propose_field_updates")
    parsed = uuid.UUID(envelope["command_id"])  # must not raise
    assert str(parsed) == envelope["command_id"]


def test_expected_revision_is_integer():
    envelope = make_command_envelope("propose_field_updates", expected_revision=3)
    assert isinstance(envelope["expected_revision"], int)


def test_timestamp_is_iso8601():
    envelope = make_command_envelope("propose_field_updates")
    dt = datetime.fromisoformat(envelope["timestamp"])  # must not raise
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# propose_field_updates command data
# ---------------------------------------------------------------------------

def test_propose_field_updates_data_has_updates_array():
    data = {
        "updates": [
            {
                "field_path": "project.name",
                "value": "Customer Portal Redesign",
                "source_reference": "user message turn 3",
                "model_confidence": 0.95,
            }
        ]
    }
    envelope = make_command_envelope("propose_field_updates", data=data)
    assert "updates" in envelope["data"]
    assert isinstance(envelope["data"]["updates"], list)


def test_propose_field_updates_field_entry_structure():
    entry = {
        "field_path": "project.name",
        "value": "Portal",
        "source_reference": "turn 3",
        "model_confidence": 0.95,
    }
    for key in ("field_path", "value", "source_reference", "model_confidence"):
        assert key in entry


# ---------------------------------------------------------------------------
# Success/partial result shapes
# ---------------------------------------------------------------------------

def make_success_result() -> dict:
    return {
        "status": "accepted",
        "revision": 4,
        "accepted_fields": ["project.name"],
        "rejected_fields": [],
        "new_gaps": [],
        "resolved_gaps": ["gap-001"],
    }


def make_partial_result() -> dict:
    return {
        "status": "partial",
        "revision": 4,
        "accepted_fields": ["project.name"],
        "rejected_fields": [
            {
                "field_path": "budget.amount",
                "error_code": "INVALID_TYPE",
                "message": "Expected number",
            }
        ],
        "new_gaps": [
            {
                "gap_id": "gap-005",
                "field_path": "timeline.end_date",
                "category": "missing",
                "severity": "blocking",
            }
        ],
    }


def test_success_result_has_required_fields():
    r = make_success_result()
    for f in ("status", "revision", "accepted_fields", "rejected_fields", "new_gaps"):
        assert f in r


def test_partial_result_has_rejected_fields():
    r = make_partial_result()
    assert r["status"] == "partial"
    assert len(r["rejected_fields"]) > 0
    assert "error_code" in r["rejected_fields"][0]


def test_new_gap_in_partial_result_has_required_fields():
    r = make_partial_result()
    gap = r["new_gaps"][0]
    for f in ("gap_id", "field_path", "category", "severity"):
        assert f in gap


# ---------------------------------------------------------------------------
# Error response shape
# ---------------------------------------------------------------------------

KNOWN_ERROR_CODES = [
    "VALIDATION_ERROR",
    "AUTHORIZATION_DENIED",
    "CONFLICT",
    "NOT_FOUND",
    "INVALID_TRANSITION",
    "PRECONDITION_FAILED",
    "TRANSIENT_ERROR",
    "PERMANENT_ERROR",
]


def make_error_response(error_code: str) -> dict:
    return {
        "status": "error",
        "error_code": error_code,
        "message": "A human-readable error message.",
        "retry_eligible": error_code == "TRANSIENT_ERROR",
    }


@pytest.mark.parametrize("code", KNOWN_ERROR_CODES)
def test_error_response_structure(code: str):
    err = make_error_response(code)
    assert err["status"] == "error"
    assert err["error_code"] == code
    assert isinstance(err["message"], str)
    assert "retry_eligible" in err


# ---------------------------------------------------------------------------
# Event envelope required fields
# ---------------------------------------------------------------------------

REQUIRED_EVENT_FIELDS = [
    "event_id",
    "event_type",
    "event_version",
    "request_id",
    "revision",
    "correlation_id",
    "causation_id",
    "occurred_at",
    "actor",
    "data",
]


@pytest.mark.parametrize("field", REQUIRED_EVENT_FIELDS)
def test_event_envelope_has_required_field(field: str):
    evt = make_event_envelope("RequestCreated")
    assert field in evt, f"Event missing field: {field!r}"


def test_event_version_format():
    evt = make_event_envelope("RequestCreated")
    major, minor = evt["event_version"].split(".")
    assert int(major) >= 1


def test_event_id_is_uuid():
    evt = make_event_envelope("RequestCreated")
    uuid.UUID(evt["event_id"])  # must not raise


def test_event_occurred_at_is_iso8601():
    evt = make_event_envelope("RequestCreated")
    dt = datetime.fromisoformat(evt["occurred_at"])
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# All documented event types
# ---------------------------------------------------------------------------

DOCUMENTED_EVENT_TYPES = [
    "RequestCreated",
    "RequestFieldsUpdated",
    "RequestSubmitted",
    "ChangesRequested",
    "RequestApproved",
    "RequestRejected",
    "DocumentGenerationRequested",
    "DocumentGenerated",
    "DeliveryRequested",
    "DeliveryCompleted",
    "DeliveryFailed",
    "RequestCompleted",
]


@pytest.mark.parametrize("event_type", DOCUMENTED_EVENT_TYPES)
def test_event_envelope_per_type(event_type: str):
    evt = make_event_envelope(event_type)
    assert evt["event_type"] == event_type
    assert "data" in evt


# ---------------------------------------------------------------------------
# Correlation identifier tests
# ---------------------------------------------------------------------------

def test_correlation_id_propagated_from_command_to_event():
    correlation_id = _uuid_str()
    command = make_command_envelope("propose_field_updates")
    command["correlation_id"] = correlation_id
    event = make_event_envelope("RequestFieldsUpdated")
    event["correlation_id"] = correlation_id
    event["causation_id"] = command["command_id"]
    assert event["correlation_id"] == command["correlation_id"]
    assert event["causation_id"] == command["command_id"]


def test_event_deduplication_by_event_id():
    evt1 = make_event_envelope("RequestCreated")
    evt2 = dict(evt1)  # same content
    # Consumers should deduplicate by event_id — two events with same id are duplicates
    assert evt1["event_id"] == evt2["event_id"]


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

def test_command_envelope_json_roundtrip():
    envelope = make_command_envelope("submit_for_review")
    serialized = json.dumps(envelope)
    deserialized = json.loads(serialized)
    assert deserialized["command_type"] == "submit_for_review"
    assert deserialized["correlation_id"] == envelope["correlation_id"]


def test_event_envelope_json_roundtrip():
    evt = make_event_envelope(
        "RequestApproved",
        data={"reviewer_id": "r-1", "revision": 3, "rationale": "OK"},
    )
    serialized = json.dumps(evt)
    deserialized = json.loads(serialized)
    assert deserialized["event_type"] == "RequestApproved"
    assert deserialized["data"]["reviewer_id"] == "r-1"
