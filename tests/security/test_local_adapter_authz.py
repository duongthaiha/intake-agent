"""Unit tests for LocalAdapter role-resolution and fail-closed security contract.

Covers three scenarios mandated by the SECURITY CONTRACT in local.py:

  A. Configured reviewer ID → receives frozenset(["reviewer"]) → domain approves.
  B. Unlisted ID → receives frozenset(["requester"]) → domain hides the request.
  C. Non-local environment (dev/test/prod) → raises AuthorizationDeniedError *immediately*,
     before any domain logic, even for a valid reviewer ID.

These tests run without any Azure credentials and without starting a server.
"""
from __future__ import annotations

import pytest

from intake_agent.adapter.local import LocalAdapter, _resolve_local_dev_actor
from intake_agent.config import IntakeSettings, build_repositories
from intake_domain.errors import AuthorizationDeniedError, NotFoundError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _settings(**overrides) -> IntakeSettings:
    base = {"persistence_backend": "inmemory", "environment": "local",
                "local_dev_reviewer_ids": "reviewer-1,local-reviewer"}
    base.update(overrides)
    return IntakeSettings(**base)


def _adapter(settings: IntakeSettings) -> LocalAdapter:
    repository_settings = settings
    if settings.environment != "local":
        repository_settings = _settings()
    repos = build_repositories(repository_settings)
    return LocalAdapter(
        request_repo=repos["request_repo"],
        template_repo=repos["template_repo"],
        outbox_repo=repos["outbox_repo"],
        idempotency_store=repos["idempotency_store"],
        artifact_store=repos["artifact_store"],
        settings=settings,
    )


async def _submit_request(adapter: LocalAdapter, uid: str = "u-test") -> tuple[str, int]:
    """Create and submit a request. Returns (request_id, post-submit revision)."""
    r = await adapter.get_or_create_request(user_id=uid)
    rid, rev = r["request_id"], r["current_revision"]

    p = await adapter.propose_updates(rid, rev, [
        {"field_path": "project.name",            "value": "Portal"},
        {"field_path": "project.description",     "value": "desc"},
        {"field_path": "requester.business_unit", "value": "Eng"},
        {"field_path": "budget.amount",           "value": "50000"},
        {"field_path": "priority",                "value": "high"},
    ], user_id=uid)

    sub = await adapter.submit_for_review(rid, p["revision"], user_id=uid)
    return rid, sub["revision"]


# ---------------------------------------------------------------------------
# Scenario A — listed reviewer IDs succeed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reviewer_id", ["reviewer-1", "local-reviewer"])
def test_listed_reviewer_id_resolves_reviewer_role(reviewer_id: str):
    """_resolve_local_dev_actor grants reviewer role to every configured ID."""
    settings = _settings()
    actor = _resolve_local_dev_actor(reviewer_id, settings)
    assert "reviewer" in actor.roles
    assert "requester" not in actor.roles


@pytest.mark.parametrize("reviewer_id", ["reviewer-1", "local-reviewer"])
@pytest.mark.asyncio
async def test_listed_reviewer_id_can_approve_via_adapter(reviewer_id: str):
    """Listed reviewer ID completes the full approve flow without error."""
    settings = _settings()
    adapter = _adapter(settings)

    rid, rev = await _submit_request(adapter)
    result = await adapter.record_review_decision(
        rid, rev, "approve", "LGTM", reviewer_id=reviewer_id
    )
    assert result["new_status"] == "approved"


@pytest.mark.asyncio
async def test_custom_reviewer_id_in_list_succeeds():
    """A custom reviewer ID explicitly added to the allow-list is accepted."""
    settings = _settings(local_dev_reviewer_ids="custom-user,reviewer-1,local-reviewer")
    adapter = _adapter(settings)

    rid, rev = await _submit_request(adapter)
    result = await adapter.record_review_decision(
        rid, rev, "approve", "Custom OK", reviewer_id="custom-user"
    )
    assert result["new_status"] == "approved"


def test_empty_reviewer_list_denies_all():
    """An empty allow-list means no user receives the reviewer role in local mode."""
    settings = _settings(local_dev_reviewer_ids="")
    # No raise at _resolve_local_dev_actor — it just grants requester role.
    actor = _resolve_local_dev_actor("reviewer-1", settings)
    assert "requester" in actor.roles
    assert "reviewer" not in actor.roles


# ---------------------------------------------------------------------------
# Scenario B — unlisted ID receives requester role → domain denies
# ---------------------------------------------------------------------------

def test_unlisted_id_resolves_requester_role():
    """_resolve_local_dev_actor assigns requester role to IDs not in the list."""
    settings = _settings()
    actor = _resolve_local_dev_actor("not-a-reviewer", settings)
    assert "requester" in actor.roles
    assert "reviewer" not in actor.roles


@pytest.mark.asyncio
async def test_unlisted_id_cannot_discover_request_on_review():
    """An unlisted requester receives NotFound rather than request disclosure."""
    settings = _settings()
    adapter = _adapter(settings)

    rid, rev = await _submit_request(adapter)

    with pytest.raises(NotFoundError) as exc_info:
        await adapter.record_review_decision(
            rid, rev, "approve", "I should be denied.", reviewer_id="intruder"
        )
    err = exc_info.value
    assert err.error_code == "NOT_FOUND"
    assert err.retry_eligible is False


@pytest.mark.asyncio
async def test_unlisted_id_cannot_reject_either():
    """Reject is also a privileged action — unlisted ID must be denied."""
    settings = _settings()
    adapter = _adapter(settings)

    rid, rev = await _submit_request(adapter)

    with pytest.raises(NotFoundError):
        await adapter.record_review_decision(
            rid, rev, "reject", "Sneaky reject.", reviewer_id="intruder"
        )


def test_whitespace_trimmed_in_reviewer_ids():
    """Leading/trailing spaces in the CSV list must not prevent matching."""
    settings = _settings(local_dev_reviewer_ids=" reviewer-1 ,  local-reviewer  ")
    actor = _resolve_local_dev_actor("reviewer-1", settings)
    assert "reviewer" in actor.roles


def test_id_that_is_prefix_of_listed_id_is_denied():
    """'reviewer' must not match 'reviewer-1' — IDs are exact, not prefix matches."""
    settings = _settings(local_dev_reviewer_ids="reviewer-1,local-reviewer")
    actor = _resolve_local_dev_actor("reviewer", settings)
    assert "requester" in actor.roles
    assert "reviewer" not in actor.roles


# ---------------------------------------------------------------------------
# Scenario C — non-local environment fails closed immediately
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("environment", ["dev", "test", "prod", "staging"])
def test_non_local_environment_raises_before_domain(environment: str):
    """In any deployed environment, _resolve_local_dev_actor raises AuthorizationDeniedError
    immediately — even for an ID that appears in the local allow-list."""
    settings = _settings(environment=environment)
    with pytest.raises(AuthorizationDeniedError) as exc_info:
        _resolve_local_dev_actor("reviewer-1", settings)
    err_msg = str(exc_info.value).lower()
    assert environment in err_msg or "environment" in err_msg


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_non_local_environment_error_is_not_retry_eligible(environment: str):
    """Fail-closed errors must not be retryable — callers must not loop."""
    settings = _settings(environment=environment)
    with pytest.raises(AuthorizationDeniedError) as exc_info:
        _resolve_local_dev_actor("reviewer-1", settings)
    assert exc_info.value.retry_eligible is False


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["dev", "prod"])
async def test_non_local_adapter_raises_on_record_review_decision(environment: str):
    """Full adapter.record_review_decision() path raises in any deployed environment."""
    # Set up a submitted request using a local adapter (the only way without Azure)
    local_settings = _settings()
    local_adapter = _adapter(local_settings)
    rid, rev = await _submit_request(local_adapter)

    # Now attempt to review via an adapter configured for a deployed environment
    deployed_settings = _settings(environment=environment)
    deployed_adapter = _adapter(deployed_settings)

    with pytest.raises(AuthorizationDeniedError) as exc_info:
        await deployed_adapter.record_review_decision(
            rid, rev, "approve", "Should not reach domain.", reviewer_id="reviewer-1"
        )
    assert exc_info.value.error_code == "AUTHORIZATION_DENIED"
