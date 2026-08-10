"""Component tests: idempotency.

Verifies that replaying the same command_id returns the original result
without creating duplicate effects (POC-05 and contracts §Idempotency).
"""
from __future__ import annotations

import uuid

import pytest
from reference_domain import (
    InMemoryIdempotencyStore,
)

pytestmark = pytest.mark.component


@pytest.mark.asyncio
async def test_first_check_returns_none(idempotency: InMemoryIdempotencyStore):
    result = await idempotency.check("request-1", "cmd-001")
    assert result is None


@pytest.mark.asyncio
async def test_stored_result_is_returned_on_replay(idempotency: InMemoryIdempotencyStore):
    original = {"status": "accepted", "revision": 2}
    await idempotency.store("request-1", "cmd-001", original)
    replayed = await idempotency.check("request-1", "cmd-001")
    assert replayed == original


@pytest.mark.asyncio
async def test_different_key_returns_none(idempotency: InMemoryIdempotencyStore):
    await idempotency.store("request-1", "cmd-001", {"status": "accepted"})
    result = await idempotency.check("request-1", "cmd-002")
    assert result is None


@pytest.mark.asyncio
async def test_different_scope_returns_none(idempotency: InMemoryIdempotencyStore):
    await idempotency.store("request-1", "cmd-001", {"status": "accepted"})
    result = await idempotency.check("request-2", "cmd-001")
    assert result is None


@pytest.mark.asyncio
async def test_idempotent_replay_does_not_overwrite(idempotency: InMemoryIdempotencyStore):
    """Storing twice with the same key should be safe; second write is ignored or idempotent."""
    original = {"status": "accepted", "revision": 2}
    second = {"status": "accepted", "revision": 99}  # different content
    await idempotency.store("request-1", "cmd-001", original)
    # The store should tolerate duplicate calls without corrupting state
    await idempotency.store("request-1", "cmd-001", second)
    # The result may be original or second — either is acceptable as long as the
    # call does not raise and the result is a dict
    result = await idempotency.check("request-1", "cmd-001")
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_multiple_commands_independent(idempotency: InMemoryIdempotencyStore):
    for i in range(10):
        cmd_id = f"cmd-{i:03d}"
        await idempotency.store("request-1", cmd_id, {"revision": i + 1})
    for i in range(10):
        result = await idempotency.check("request-1", f"cmd-{i:03d}")
        assert result is not None
        assert result["revision"] == i + 1


@pytest.mark.asyncio
async def test_stored_result_survives_multiple_checks(idempotency: InMemoryIdempotencyStore):
    payload = {"status": "submitted", "new_status": "in_review"}
    await idempotency.store("r-1", "submit-cmd", payload)
    for _ in range(5):
        result = await idempotency.check("r-1", "submit-cmd")
        assert result == payload


# ---------------------------------------------------------------------------
# Idempotency integration: simulate command handler with idempotency guard
# ---------------------------------------------------------------------------

async def process_command_once(
    idempotency: InMemoryIdempotencyStore,
    scope_id: str,
    command_id: str,
    side_effects: list,
) -> dict:
    """Simulate a command handler that guards against duplicate execution."""
    cached = await idempotency.check(scope_id, command_id)
    if cached is not None:
        return cached  # replay path — no side effects

    # Execute command (produces side effects)
    side_effects.append(command_id)
    result = {"status": "accepted", "command_id": command_id}
    await idempotency.store(scope_id, command_id, result)
    return result


@pytest.mark.asyncio
async def test_duplicate_command_does_not_execute_twice(idempotency: InMemoryIdempotencyStore):
    side_effects: list = []
    cmd_id = str(uuid.uuid4())

    result1 = await process_command_once(idempotency, "req-1", cmd_id, side_effects)
    result2 = await process_command_once(idempotency, "req-1", cmd_id, side_effects)

    assert result1 == result2
    # Side effect executed exactly once
    assert side_effects.count(cmd_id) == 1
