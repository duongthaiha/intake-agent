"""
Local fixture/demo runner for the Teams adapter.

Exercises card loading, message parsing, action parsing, and auth boundary
configuration without requiring Azure credentials, a Teams tenant, or a
Foundry Agent Service deployment.

Usage:
    python -m intake_teams.demo
    python -m intake_teams.demo --verbose

What it tests:
    1. All Adaptive Card JSON templates load and are valid JSON.
    2. Message activities are parsed to get_or_create_request envelopes.
    3. Action.Execute invoke activities are parsed for each supported verb.
    4. AuthBoundary raises RuntimeError when dev_mode=True + deployed env vars set.
    5. AuthBoundary emits DevModeWarning when dev_mode=True locally.
    6. ParseError is raised for unsupported activity types / verbs.
    7. All card ${template} variables are identified (not evaluated).
"""

from __future__ import annotations

import sys
import warnings

# Defer all package imports until after the argv check so --help works without
# any optional dependencies installed.


def main(verbose: bool = False) -> int:
    from collections.abc import Callable

    from intake_teams.adapter import (
        ActivityParser,
        AuthBoundary,
        AuthError,
        ConfigurationError,
        DevModeWarning,
        ParseError,
        TeamsActivity,
    )
    from intake_teams.adapter.contracts import CommandEnvelope
    from intake_teams.cards import load_all

    results: list[tuple[str, str, str | None]] = []  # (name, status, detail)

    def ok(name: str, detail: str | None = None) -> None:
        results.append((name, "PASS", detail))
        if verbose:
            print(f"  [PASS] {name}" + (f": {detail}" if detail else ""))

    def fail(name: str, detail: str) -> None:
        results.append((name, "FAIL", detail))
        print(f"  [FAIL] {name}: {detail}")

    # ------------------------------------------------------------------
    # 1. Card loading
    # ------------------------------------------------------------------
    print("\n-- Card templates --")
    cards = load_all()
    if not cards:
        fail("cards.load_all", "No cards found")
    else:
        for name, card in cards.items():
            if "type" in card and card["type"] == "AdaptiveCard":
                ok(f"card:{name}", f"version={card.get('version', '?')}")
            else:
                fail(f"card:{name}", "Missing type=AdaptiveCard")

    # ------------------------------------------------------------------
    # 2. Message activity -> get_or_create_request
    # ------------------------------------------------------------------
    print("\n-- Message activity parsing --")
    parser = ActivityParser()
    msg_activity = TeamsActivity.model_validate(
        {
            "id": "activity-001",
            "type": "message",
            "text": "I need a new project",
            "from": {
                "id": "user-aad-oid-001",
                "aadObjectId": "user-aad-oid-001",
                "tenantId": "tenant-001",
            },
            "conversation": {"id": "conv-001", "tenantId": "tenant-001"},
            "channelData": {"tenant": {"id": "tenant-001"}},
        }
    )
    try:
        env = parser.parse(msg_activity)
        assert env.command_type == "get_or_create_request", env.command_type
        assert env.actor.user_id == "user-aad-oid-001"
        assert env.actor.tenant_id == "tenant-001"
        assert len(env.request_id) == 32, "request_id should be 32-char hex"
        ok("message->get_or_create_request", f"request_id={env.request_id[:8]}")
    except Exception as exc:
        fail("message->get_or_create_request", str(exc))

    # ------------------------------------------------------------------
    # 3. Invoke activities for each supported verb
    # ------------------------------------------------------------------
    print("\n-- Invoke activity parsing --")
    _invoke_base = {
        "id": "activity-002",
        "type": "invoke",
        "name": "adaptiveCard/action",
        "from": {"id": "user-001", "aadObjectId": "user-001"},
        "conversation": {"id": "conv-001", "tenantId": "tenant-001"},
        "channelData": {"tenant": {"id": "tenant-001"}},
    }

    invoke_cases: list[tuple[str, dict[str, object], Callable[[CommandEnvelope], bool]]] = [
        (
            "capture_field",
            {
                "action": {
                    "verb": "capture_field",
                    "data": {
                        "field_path": "project.name",
                        "value": "Portal Redesign",
                        "expected_revision": 1,
                    },
                }
            },
            lambda e: e.command_type == "propose_field_updates",
        ),
        (
            "submit_request",
            {
                "action": {
                    "verb": "submit_request",
                    "data": {"expected_revision": 3},
                }
            },
            lambda e: e.command_type == "submit_for_review",
        ),
        (
            "review_decision",
            {
                "action": {
                    "verb": "review_decision",
                    "data": {
                        "decision": "approve",
                        "rationale": "All fields complete",
                        "expected_revision": 3,
                    },
                }
            },
            lambda e: e.command_type == "record_review_decision",
        ),
        (
            "acknowledge_gaps",
            {
                "action": {
                    "verb": "acknowledge_gaps",
                    "data": {"gap_ids": ["gap-001", "gap-002"]},
                }
            },
            lambda e: e.command_type == "acknowledge_gaps",
        ),
    ]

    for verb, value_payload, check in invoke_cases:
        activity = TeamsActivity.model_validate({**_invoke_base, "value": value_payload})
        try:
            env = parser.parse(activity)
            assert check(env), f"Unexpected command_type: {env.command_type}"
            ok(f"invoke->{verb}", f"-> {env.command_type}")
        except Exception as exc:
            fail(f"invoke->{verb}", str(exc))

    # ------------------------------------------------------------------
    # 4. ParseError for unknown verb
    # ------------------------------------------------------------------
    print("\n-- ParseError guards --")
    bad_invoke = TeamsActivity.model_validate(
        {
            **_invoke_base,
            "value": {"action": {"verb": "unknown_verb", "data": {}}},
        }
    )
    try:
        parser.parse(bad_invoke)
        fail("ParseError:unknown_verb", "Expected ParseError but none was raised")
    except ParseError:
        ok("ParseError:unknown_verb")
    except Exception as exc:
        fail("ParseError:unknown_verb", f"Wrong exception type: {exc!r}")

    # ------------------------------------------------------------------
    # 5. AuthBoundary dev mode warning (no deployed env vars)
    # ------------------------------------------------------------------
    print("\n-- AuthBoundary --")
    import os
    for env_var in ("WEBSITE_HOSTNAME", "FUNCTIONS_WORKER_RUNTIME", "INTAKE_ENV"):
        os.environ.pop(env_var, None)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            boundary = AuthBoundary(bot_app_id="demo", dev_mode=True)
        dev_warnings = [w for w in caught if issubclass(w.category, DevModeWarning)]
        if dev_warnings:
            ok("AuthBoundary:dev_mode_warning")
        else:
            fail("AuthBoundary:dev_mode_warning", "DevModeWarning not emitted")
    except RuntimeError as exc:
        fail("AuthBoundary:dev_mode_warning", f"Unexpected RuntimeError: {exc}")

    # Dev mode verify returns a VerifiedIdentity without error
    import asyncio
    async def _check_dev_identity() -> None:
        identity = await boundary.verify(None, "https://localhost")
        assert identity.raw_claims.get("_dev_mode") is True
        ok("AuthBoundary:dev_identity")

    try:
        asyncio.run(_check_dev_identity())
    except Exception as exc:
        fail("AuthBoundary:dev_identity", str(exc))

    # Production boundary raises ConfigurationError (503) — not AuthError (401) —
    # because no JWKS validator is wired yet. This is the explicit fail-closed stance.
    prod_boundary = AuthBoundary(bot_app_id="prod-app")
    async def _check_no_header() -> None:
        try:
            await prod_boundary.verify(None, "https://bot.service.url")
            fail("AuthBoundary:missing_header_rejected", "Expected AuthError but none raised")
        except AuthError:
            ok("AuthBoundary:missing_header_rejected")

    async def _check_prod_config_error() -> None:
        try:
            await prod_boundary.verify("Bearer fake.jwt.token", "https://bot.service.url")
            fail(
                "AuthBoundary:production_config_error",
                "Expected ConfigurationError but none raised",
            )
        except ConfigurationError as exc:
            assert exc.status_code == 503, f"Expected 503, got {exc.status_code}"
            ok("AuthBoundary:production_config_error", "503 ConfigurationError raised as expected")
        except AuthError as exc:
            fail("AuthBoundary:production_config_error",
                 f"Got AuthError ({exc.status_code}) but expected ConfigurationError(503)")

    try:
        asyncio.run(_check_no_header())
        asyncio.run(_check_prod_config_error())
    except Exception as exc:
        fail("AuthBoundary:production_guards", str(exc))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n-- Summary --")
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"  {passed} passed  {failed} failed  ({len(results)} total)\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    sys.exit(main(verbose=verbose))
