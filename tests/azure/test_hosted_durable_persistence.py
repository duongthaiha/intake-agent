"""Live durability gate for an approved VNet-connected Foundry runner."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.azure, pytest.mark.integration]


def _invoke(
    endpoint: str,
    *,
    user_key: str,
    chat_key: str | None,
    prompt: str,
    new_session: bool,
) -> str:
    command = [
        "azd",
        "ai",
        "agent",
        "invoke",
        "--agent-endpoint",
        endpoint,
        "--user-identity",
        user_key,
        "--timeout",
        "300",
    ]
    if chat_key is not None:
        command.extend(["--conversation-id", chat_key])
    if new_session:
        command.append("--new-session")
    command.append(prompt)

    result = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        timeout=360,
    )
    evidence = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if "403" in evidence or "Forbidden" in evidence:
        pytest.fail(
            "Foundry invocation was blocked by private networking. A public-shell "
            "403 is expected security evidence, but is not functional persistence proof.\n"
            f"{evidence}"
        )
    assert result.returncode == 0, evidence
    return evidence


def _conversation_id(evidence: str) -> str:
    match = re.search(r"\bconv_[A-Za-z0-9]+\b", evidence)
    assert match is not None, f"Foundry did not return a conversation ID:\n{evidence}"
    return match.group(0)


def test_two_turn_and_fresh_session_resume_from_durable_state() -> None:
    if shutil.which("azd") is None:
        pytest.skip("azd is required on the approved VNet-connected runner")

    endpoint = os.environ.get("INTAKE_AGENT_ENDPOINT", "").strip()
    if not endpoint:
        pytest.skip("Set INTAKE_AGENT_ENDPOINT to the approved deployed version URL")

    unique = uuid4().hex[:12]
    project_name = f"Durable Verification {unique}"
    user_key = f"switch-user-{unique}"

    first = _invoke(
        endpoint,
        user_key=user_key,
        chat_key=None,
        new_session=True,
        prompt=(
            f"Set project.name to '{project_name}'. Save it, then repeat the exact "
            "persisted project name."
        ),
    )
    print(f"FIRST_SESSION_CREATE\n{first}")
    assert project_name in first
    conversation_id = _conversation_id(first)

    second = _invoke(
        endpoint,
        user_key=user_key,
        chat_key=conversation_id,
        new_session=False,
        prompt="Load the authoritative intake context and repeat the exact project.name.",
    )
    print(f"FIRST_SESSION_RESUME\n{second}")
    assert project_name in second

    resumed = _invoke(
        endpoint,
        user_key=user_key,
        chat_key=conversation_id,
        new_session=True,
        prompt=(
            "This is a fresh Foundry session. Load persisted intake state and repeat "
            "the exact project.name."
        ),
    )
    print(f"FRESH_SESSION_RESUME\n{resumed}")
    assert project_name in resumed
