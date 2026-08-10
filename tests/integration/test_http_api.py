"""Integration tests: FastAPI HTTP API layer (intake_agent/main.py).

Uses Starlette TestClient (synchronous) — handles FastAPI lifespan correctly.
No real server started, no Azure credentials required (persistence_backend=inmemory).
"""
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# App fixture — overrides settings for in-memory backend
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Synchronous HTTP test client that triggers FastAPI lifespan."""
    os.environ["INTAKE_PERSISTENCE_BACKEND"] = "inmemory"
    from intake_agent.config import get_settings
    get_settings.cache_clear()

    from intake_agent.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /requests — create
# ---------------------------------------------------------------------------

def test_create_request_returns_200(client):
    resp = client.post("/requests", json={"user_id": "u-1", "conversation_id": "conv-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert "request_id" in body
    assert body["status"] == "new"
    assert "current_revision" in body


def test_create_request_idempotent(client):
    payload = {"user_id": "u-2", "conversation_id": "conv-idem"}
    r1 = client.post("/requests", json=payload)
    r2 = client.post("/requests", json=payload)
    assert r1.json()["request_id"] == r2.json()["request_id"]
    assert r2.json()["created"] is False


# ---------------------------------------------------------------------------
# GET /requests — list
# ---------------------------------------------------------------------------

def test_list_requests_empty_initially(client):
    resp = client.get("/requests?user_id=no-requests-user")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_requests_includes_created(client):
    client.post("/requests", json={"user_id": "list-user", "conversation_id": "c-list-1"})
    resp = client.get("/requests?user_id=list-user")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# ---------------------------------------------------------------------------
# GET /requests/{id} — context
# ---------------------------------------------------------------------------

def test_get_context_returns_request(client):
    create_resp = client.post("/requests", json={"user_id": "u-ctx", "conversation_id": "ctx-1"})
    rid = create_resp.json()["request_id"]
    resp = client.get(f"/requests/{rid}?user_id=u-ctx")
    assert resp.status_code == 200
    assert resp.json()["request_id"] == rid


def test_get_context_not_found_returns_404(client):
    resp = client.get("/requests/nonexistent-id?user_id=u-1")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# POST /requests/{id}/fields — propose updates
# ---------------------------------------------------------------------------

def test_propose_updates_accepted(client):
    create_resp = client.post("/requests", json={"user_id": "u-p", "conversation_id": "prop-1"})
    body = create_resp.json()
    rid, rev = body["request_id"], body["current_revision"]

    resp = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev,
        "user_id": "u-p",
        "updates": [{"field_path": "project.name", "value": "My Project"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("accepted", "partial")
    assert "project.name" in data["accepted_fields"]


def test_propose_invalid_enum_returns_partial(client):
    create_resp = client.post("/requests", json={"user_id": "u-inv", "conversation_id": "inv-1"})
    body = create_resp.json()
    rid, rev = body["request_id"], body["current_revision"]

    resp = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev,
        "user_id": "u-inv",
        "updates": [{"field_path": "priority", "value": "extreme"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert any(r["field_path"] == "priority" for r in data["rejected_fields"])


def test_propose_request_not_found_returns_404(client):
    resp = client.post("/requests/ghost-id/fields", json={
        "expected_revision": 1,
        "user_id": "u-1",
        "updates": [{"field_path": "project.name", "value": "X"}],
    })
    assert resp.status_code == 404


def test_propose_revision_mismatch_returns_409(client):
    create_resp = client.post("/requests", json={"user_id": "u-cf", "conversation_id": "cf-1"})
    rid = create_resp.json()["request_id"]

    resp = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": 999,
        "user_id": "u-cf",
        "updates": [{"field_path": "project.name", "value": "X"}],
    })
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# POST /requests/{id}/submit
# ---------------------------------------------------------------------------

def test_submit_with_missing_fields_returns_422(client):
    create_resp = client.post("/requests", json={"user_id": "u-s", "conversation_id": "sub-1"})
    body = create_resp.json()
    rid, rev = body["request_id"], body["current_revision"]
    # Propose just one field — leaves quality below threshold
    p = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev, "user_id": "u-s",
        "updates": [{"field_path": "project.name", "value": "X"}],
    })
    new_rev = p.json()["revision"]
    resp = client.post(f"/requests/{rid}/submit", json={
        "expected_revision": new_rev, "user_id": "u-s"
    })
    assert resp.status_code == 422


def test_submit_full_fields_transitions_to_in_review(client):
    create_resp = client.post(
        "/requests", json={"user_id": "u-full", "conversation_id": "full-sub"}
    )
    body = create_resp.json()
    rid, rev = body["request_id"], body["current_revision"]

    p = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev, "user_id": "u-full",
        "updates": [
            {"field_path": "project.name", "value": "Portal"},
            {"field_path": "project.description", "value": "desc"},
            {"field_path": "requester.business_unit", "value": "Eng"},
            {"field_path": "budget.amount", "value": "50000"},
            {"field_path": "priority", "value": "high"},
        ],
    })
    new_rev = p.json()["revision"]
    resp = client.post(f"/requests/{rid}/submit", json={
        "expected_revision": new_rev, "user_id": "u-full"
    })
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "in_review"


# ---------------------------------------------------------------------------
# POST /requests/{id}/review
# ---------------------------------------------------------------------------

def test_reviewer_approve_transitions_to_approved(client):
    create_resp = client.post("/requests", json={"user_id": "u-rev", "conversation_id": "rev-1"})
    body = create_resp.json()
    rid, rev = body["request_id"], body["current_revision"]

    p = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev, "user_id": "u-rev",
        "updates": [
            {"field_path": "project.name", "value": "Portal"},
            {"field_path": "project.description", "value": "desc"},
            {"field_path": "requester.business_unit", "value": "Eng"},
            {"field_path": "budget.amount", "value": "50000"},
            {"field_path": "priority", "value": "high"},
        ],
    })
    new_rev = p.json()["revision"]
    sub = client.post(f"/requests/{rid}/submit", json={
        "expected_revision": new_rev, "user_id": "u-rev"
    })
    sub_rev = sub.json()["revision"]

    resp = client.post(f"/requests/{rid}/review", json={
        "expected_revision": sub_rev,
        "decision": "approve",
        "rationale": "All good.",
        "reviewer_id": "reviewer-1",
    })
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "approved"


def test_non_reviewer_approve_returns_403(client):
    """Unlisted actor receives requester role; domain handler rejects with 403."""
    rid, sub_rev = _create_and_submit(client, uid="u-norev", conv="norev-1")

    resp = client.post(f"/requests/{rid}/review", json={
        "expected_revision": sub_rev,
        "decision": "approve",
        "rationale": "I should not be allowed.",
        "reviewer_id": "not-a-reviewer",
    })
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    detail = resp.json()["detail"]
    assert detail["error_code"] == "AUTHORIZATION_DENIED"
    assert detail["retry_eligible"] is False


def test_invalid_decision_value_returns_422(client):
    create_resp = client.post("/requests", json={"user_id": "u-inv-d", "conversation_id": "invd-1"})
    body = create_resp.json()
    rid, rev = body["request_id"], body["current_revision"]

    p = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev, "user_id": "u-inv-d",
        "updates": [
            {"field_path": "project.name", "value": "X"},
            {"field_path": "project.description", "value": "d"},
            {"field_path": "requester.business_unit", "value": "Eng"},
            {"field_path": "budget.amount", "value": "50000"},
            {"field_path": "priority", "value": "high"},
        ],
    })
    new_rev = p.json()["revision"]
    sub = client.post(f"/requests/{rid}/submit", json={
        "expected_revision": new_rev, "user_id": "u-inv-d"
    })
    sub_rev = sub.json()["revision"]

    resp = client.post(f"/requests/{rid}/review", json={
        "expected_revision": sub_rev,
        "decision": "maybe",  # invalid
        "rationale": "?",
        "reviewer_id": "reviewer-1",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Review authorisation — real assertions for all three scenarios
# ---------------------------------------------------------------------------

def _create_and_submit(client, uid: str, conv: str) -> tuple[str, int]:
    """Helper: create a request, fill ≥5 fields, submit. Returns (request_id, revision)."""
    body = client.post("/requests", json={"user_id": uid, "conversation_id": conv}).json()
    rid, rev = body["request_id"], body["current_revision"]

    p = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": rev, "user_id": uid,
        "updates": [
            {"field_path": "project.name",            "value": "Portal"},
            {"field_path": "project.description",     "value": "desc"},
            {"field_path": "requester.business_unit", "value": "Eng"},
            {"field_path": "budget.amount",           "value": "50000"},
            {"field_path": "priority",                "value": "high"},
        ],
    })
    new_rev = p.json()["revision"]
    sub = client.post(f"/requests/{rid}/submit",
                      json={"expected_revision": new_rev, "user_id": uid})
    assert sub.status_code == 200, f"submit failed: {sub.text}"
    return rid, sub.json()["revision"]



def test_404_response_has_contract_structure(client):
    resp = client.get("/requests/nonexistent?user_id=u")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "error_code" in detail
    assert "message" in detail
    assert "retry_eligible" in detail


def test_409_response_has_contract_structure(client):
    create_resp = client.post("/requests", json={"user_id": "u-409", "conversation_id": "c409"})
    rid = create_resp.json()["request_id"]
    resp = client.post(f"/requests/{rid}/fields", json={
        "expected_revision": 999,
        "user_id": "u-409",
        "updates": [{"field_path": "project.name", "value": "X"}],
    })
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "CONFLICT"
    assert detail["retry_eligible"] is True


# ---------------------------------------------------------------------------
# Documentation: LocalAdapter review_decision always assigns reviewer role
# ---------------------------------------------------------------------------

def test_document_review_actor_enforcement():
    """
    Confirms LocalAdapter._resolve_local_dev_actor() enforces roles
    correctly.  These are the same invariants exercised via HTTP above, but
    validated directly at the adapter layer so the contract is explicit.

    Scenario A — listed reviewer ID receives the reviewer role (200).
    Scenario B — unlisted ID receives requester role → domain 403.
    Scenario C — non-local environment rejects immediately, even for valid ID.

    See also: tests/security/test_local_adapter_authz.py for unit-level coverage.
    """
    # Scenario A already covered end-to-end by test_reviewer_approve_transitions_to_approved
    # Scenario B already covered end-to-end by test_non_reviewer_approve_returns_403
    # Scenario C: Directly probe _resolve_local_dev_actor with a non-local settings object.
    from intake_agent.adapter.local import _resolve_local_dev_actor
    from intake_agent.config import IntakeSettings
    from intake_domain.errors import AuthorizationDeniedError as AuthzError

    prod_settings = IntakeSettings(environment="prod",
                                   local_dev_reviewer_ids="reviewer-1,local-reviewer",
                                   persistence_backend="inmemory")
    with pytest.raises(AuthzError) as exc_info:
        _resolve_local_dev_actor("reviewer-1", prod_settings)
    assert "prod" in str(exc_info.value).lower() or "environment" in str(exc_info.value).lower()


def test_second_default_reviewer_id_also_succeeds(client):
    """'local-reviewer' (the second default entry) must also pass."""
    rid, sub_rev = _create_and_submit(client, uid="u-lr", conv="lr-1")
    resp = client.post(f"/requests/{rid}/review", json={
        "expected_revision": sub_rev,
        "decision": "approve",
        "rationale": "From local-reviewer.",
        "reviewer_id": "local-reviewer",
    })
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["new_status"] == "approved"


