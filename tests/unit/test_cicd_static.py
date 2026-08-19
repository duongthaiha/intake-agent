"""Static regression tests for the credential-free CI pipeline.

These tests validate .github/workflows/ci.yml and the pyproject.toml /
.coveragerc quality-gate configuration as plain text/TOML, without invoking
GitHub Actions or requiring network access. They exist to prevent
regressions of the false-pass behaviors this workflow was hardened against:
`continue-on-error`, "skip if tool missing" fallbacks, floating/mutable
Action refs, non-blocking security scans, and duplicate/dead coverage or
pytest configuration.

Switch owns tests/** and evaluation/** per ADR-012; this file does not
import or exercise deploy.yml, azure.yaml, infra/**, or scripts/azure/**
(Tank's ownership).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent.parent
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
COVERAGERC_PATH = REPO_ROOT / ".coveragerc"

REQUIRED_JOB_IDS = [
    "bicep-validate",
    "lint-and-types",
    "import-boundaries",
    "pr-tests",
    "integration-tests",
    "bandit-scan",
    "secret-scan",
    "iac-scan",
    "required-checks",
]

# Third-party Actions that must be pinned to an immutable 40-hex-char commit
# SHA (not a mutable tag such as @v4 or @master).
PINNED_ACTIONS = [
    "actions/checkout",
    "actions/setup-python",
    "actions/upload-artifact",
    "aquasecurity/trivy-action",
]


@pytest.fixture(scope="module")
def ci_workflow_text() -> str:
    assert CI_WORKFLOW_PATH.exists(), f"Expected {CI_WORKFLOW_PATH} to exist"
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pyproject_data() -> dict:
    with PYPROJECT_PATH.open("rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# No false-pass behavior
# ---------------------------------------------------------------------------


def test_ci_workflow_has_no_continue_on_error(ci_workflow_text: str) -> None:
    """A required gate must never be able to fail silently.

    Matches the YAML key form (``continue-on-error:``) rather than the bare
    substring, since the workflow's header comment legitimately documents
    the absence of this behavior by name.
    """
    assert "continue-on-error:" not in ci_workflow_text, (
        "ci.yml must not set continue-on-error: on any required gate; "
        "it hides failures from the check conclusion."
    )


def test_ci_workflow_has_no_skip_on_missing_tool_guards(ci_workflow_text: str) -> None:
    """CI must hard-fail if a tool or dependency is missing, not echo-and-skip."""
    forbidden_patterns = [
        "command -v",
        "|| echo",
        "2>/dev/null ||",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in ci_workflow_text, (
            f"ci.yml must not contain {pattern!r}; a missing tool or failed "
            "install must fail the job, not be silently skipped."
        )


def test_ci_workflow_does_not_reference_azure_credentials(ci_workflow_text: str) -> None:
    """This pipeline is credential-free; Azure auth belongs to deploy.yml."""
    forbidden = ["azure/login", "AZURE_CLIENT_ID", "AZURE_TENANT_ID", "id-token: write"]
    for token in forbidden:
        assert token not in ci_workflow_text, (
            f"ci.yml must stay credential-free; found {token!r}. "
            "Azure OIDC login belongs in deploy.yml, not this workflow."
        )


def test_ci_workflow_does_not_run_evaluation_marker(ci_workflow_text: str) -> None:
    """Live Azure/evaluation execution stays out of this dev-only pipeline."""
    assert "-m evaluation" not in ci_workflow_text
    assert "-m \"evaluation" not in ci_workflow_text
    assert "pytest -m azure" not in ci_workflow_text
    assert "eval.yaml" not in ci_workflow_text


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


def test_ci_triggers_target_main_only(ci_workflow_text: str) -> None:
    """There is no develop branch; push/pull_request must target main only."""
    trigger_block_match = re.search(
        r"^on:\n(.*?)^permissions:", ci_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert trigger_block_match is not None, "Could not find the 'on:' trigger block"
    trigger_block = trigger_block_match.group(1)

    assert "develop" not in trigger_block, (
        "ci.yml must not trigger on a 'develop' branch; this repo has none."
    )
    assert re.search(r"branches:\s*\[main\]", trigger_block), (
        "push/pull_request triggers must be scoped to branches: [main]"
    )


# ---------------------------------------------------------------------------
# Job structure
# ---------------------------------------------------------------------------


def test_all_required_job_ids_are_present(ci_workflow_text: str) -> None:
    for job_id in REQUIRED_JOB_IDS:
        assert re.search(rf"^  {re.escape(job_id)}:\s*$", ci_workflow_text, re.MULTILINE), (
            f"Expected job id '{job_id}:' at 2-space indent under jobs: in ci.yml"
        )


def test_aggregate_job_runs_unconditionally_and_depends_on_every_gate(
    ci_workflow_text: str,
) -> None:
    """The single required status check must always run and cover every gate."""
    match = re.search(
        r"^  required-checks:\n(.*)\Z", ci_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert match is not None, "required-checks job not found"
    block = match.group(1)

    assert "if: always()" in block, (
        "required-checks must run with `if: always()` so it can observe and "
        "fail on cancelled/failed dependencies rather than being skipped."
    )

    needs_match = re.search(r"needs:\n((?:\s+-\s+\S+\n)+)", block)
    assert needs_match is not None, "required-checks must declare a needs: list"
    needed_jobs = {line.strip("- ").strip() for line in needs_match.group(1).splitlines()}

    other_jobs = set(REQUIRED_JOB_IDS) - {"required-checks"}
    assert needed_jobs == other_jobs, (
        f"required-checks needs {needed_jobs} but must depend on exactly {other_jobs}"
    )


def test_aggregate_job_treats_non_success_as_failing(ci_workflow_text: str) -> None:
    """Any failed or cancelled dependency must make the aggregate job exit non-zero."""
    match = re.search(
        r"^  required-checks:\n(.*)\Z", ci_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert match is not None
    block = match.group(1)

    assert 'result" == "success"' in block
    assert "exit 1" in block
    # Only integration-tests (main-push only) may treat 'skipped' as OK.
    assert 'allow_skip == "yes"' in block or "allow_skip\" == \"yes\"" in block


def test_integration_skip_is_only_allowed_off_main_push(ci_workflow_text: str) -> None:
    """The aggregate must NOT unconditionally forgive a skipped integration run.

    On push to `refs/heads/main`, integration-tests is mandatory: an
    unexpected skip there proves nothing about deployment readiness and
    must fail `required-checks`. A skip is only acceptable off that event
    (e.g. on PRs), where integration-tests is intentionally not required.
    """
    match = re.search(
        r"^  required-checks:\n(.*)\Z", ci_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert match is not None, "required-checks job not found"
    block = match.group(1)

    # Regression guard: cycle-1 hard-coded `yes`, unconditionally forgiving
    # a skip regardless of event. That must be gone.
    assert not re.search(
        r'check\s+"integration-tests"\s+"\$\{\{\s*needs\.integration-tests\.result\s*\}\}"\s+yes',
        block,
    ), (
        "integration-tests must not be passed a hard-coded 'yes' allow_skip "
        "value — the aggregate must decide this based on the triggering event."
    )

    # The event check must gate on push-to-main specifically.
    assert "github.event_name == 'push'" in block
    assert "refs/heads/main" in block

    # A variable (not a literal) must be threaded into the integration check,
    # and that variable must only be "no" (skip forbidden) when the event is
    # a push to main, "yes" (skip forgiven) otherwise.
    assert re.search(
        r'check\s+"integration-tests"\s+"\$\{\{\s*needs\.integration-tests\.result\s*\}\}"\s+'
        r'"\$integration_allow_skip"',
        block,
    ), "integration-tests check must use a computed $integration_allow_skip variable"

    is_main_push_match = re.search(
        r'is_main_push=.*github\.event_name == \'push\'.*refs/heads/main.*"', block
    )
    assert is_main_push_match is not None, (
        "required-checks must compute an is_main_push flag from "
        "github.event_name and github.ref"
    )

    assign_match = re.search(
        r'if\s*\[\[\s*"\$is_main_push"\s*==\s*"true"\s*\]\];\s*then\s*'
        r"integration_allow_skip=no\s*"
        r"else\s*"
        r"integration_allow_skip=yes",
        block,
        re.DOTALL,
    )
    assert assign_match is not None, (
        "integration_allow_skip must be 'no' when is_main_push is true "
        "(mandatory success on main push) and 'yes' otherwise (PR-exempt)"
    )


def test_integration_tests_is_the_only_job_allowed_to_skip(ci_workflow_text: str) -> None:
    match = re.search(
        r"^  integration-tests:\n(.*?)\n  \w", ci_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert match is not None, "integration-tests job not found"
    block = match.group(1)
    assert "github.event_name == 'push'" in block
    assert "refs/heads/main" in block
    # Must exclude the azure marker: it requires a private-network runner.
    assert "integration and not azure" in block


# ---------------------------------------------------------------------------
# Action pinning
# ---------------------------------------------------------------------------


def test_third_party_actions_are_pinned_to_commit_shas(ci_workflow_text: str) -> None:
    uses_lines = re.findall(
        r"^\s*(?:-\s*)?uses:\s*(\S+)@([^\s#]+)",
        ci_workflow_text,
        re.MULTILINE,
    )
    seen: set[str] = set()
    for action, ref in uses_lines:
        seen.add(action)
        assert re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"{action}@{ref} must be pinned to a 40-character commit SHA, "
            "not a mutable tag such as 'v4' or 'master'"
        )

    for action in PINNED_ACTIONS:
        assert action in seen, f"Expected {action} to be used in ci.yml"


def test_no_action_is_pinned_to_a_floating_ref(ci_workflow_text: str) -> None:
    refs = re.findall(
        r"^\s*(?:-\s*)?uses:\s*\S+@([^\s#]+)",
        ci_workflow_text,
        re.MULTILINE,
    )
    assert refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs), (
        "Every uses: line must be pinned to a commit SHA, including lines with comments."
    )


# ---------------------------------------------------------------------------
# Security gate strictness
# ---------------------------------------------------------------------------


def test_bandit_blocks_only_on_high_severity(ci_workflow_text: str) -> None:
    match = re.search(r"bandit -r src/[^\n]*", ci_workflow_text)
    assert match is not None, "Expected a `bandit -r src/` invocation in ci.yml"
    assert "-lll" in match.group(0), (
        "Bandit must be invoked with -lll (severity >= HIGH) so only HIGH "
        "severity findings are blocking, per the approved gate."
    )


def test_trivy_secret_scan_is_blocking(ci_workflow_text: str) -> None:
    match = re.search(
        r"scanners: secret\n(?:.*\n){0,6}?\s*exit-code: '(\d)'", ci_workflow_text
    )
    assert match is not None, "Expected the Trivy secret scan step to set exit-code"
    assert match.group(1) == "1", "Trivy secret scan must be blocking (exit-code: '1')"


def test_trivy_iac_scan_blocks_high_and_critical(ci_workflow_text: str) -> None:
    match = re.search(
        r"scan-type: config\n(?:.*\n){0,8}?\s*severity: '([A-Z,]+)'", ci_workflow_text
    )
    assert match is not None, "Expected the Trivy IaC scan step to set severity"
    severities = set(match.group(1).split(","))
    assert {"HIGH", "CRITICAL"} <= severities

    exit_code_match = re.search(
        r"scan-type: config\n(?:.*\n){0,10}?\s*exit-code: '(\d)'", ci_workflow_text
    )
    assert exit_code_match is not None
    assert exit_code_match.group(1) == "1", "Trivy IaC scan must be blocking (exit-code: '1')"
    assert "Compile Bicep for security scanning" in ci_workflow_text
    assert "infra/bootstrap-runner.bicep" in ci_workflow_text
    assert "infra/modules/*.bicep" in ci_workflow_text
    assert "scan-ref: .trivy-iac/" in ci_workflow_text


# ---------------------------------------------------------------------------
# Coverage / pytest configuration — single source of truth
# ---------------------------------------------------------------------------


def test_pyproject_has_no_dead_coverage_table(pyproject_data: dict) -> None:
    """.coveragerc is authoritative; a [tool.coverage] table would be dead
    config since coverage.py resolves .coveragerc first and never merges
    the two, which is exactly the duplicate-config trap this test guards
    against re-introducing."""
    assert "coverage" not in pyproject_data.get("tool", {}), (
        "pyproject.toml must not declare [tool.coverage.*]; it would be "
        "silently ignored in favor of .coveragerc and would misrepresent "
        "the real coverage gate."
    )


def test_pyproject_has_no_dead_pytest_ini_options_table(pyproject_data: dict) -> None:
    """pytest.ini is authoritative for the same reason: a top-level
    pytest.ini always wins over [tool.pytest.ini_options]."""
    assert "ini_options" not in pyproject_data.get("tool", {}).get("pytest", {}), (
        "pyproject.toml must not declare [tool.pytest.ini_options]; "
        "pytest.ini at the repo root always takes precedence and this "
        "table would be silently ignored."
    )


def test_coveragerc_matches_documented_intake_domain_gate() -> None:
    assert COVERAGERC_PATH.exists()
    content = COVERAGERC_PATH.read_text(encoding="utf-8")
    assert "src/intake_domain" in content, (
        "The coverage gate must scope to src/intake_domain, matching "
        "docs/quality/test-strategy.md."
    )
    assert re.search(r"fail_under\s*=\s*80\b", content), (
        "The coverage gate must fail under 80%, matching the approved threshold."
    )


def test_bandit_is_a_declared_dev_dependency(pyproject_data: dict) -> None:
    dev_deps = pyproject_data["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("bandit") for dep in dev_deps), (
        "bandit must be declared in [project.optional-dependencies].dev "
        "since ci.yml's bandit-scan job depends on it being installed via "
        "`pip install -e \".[dev]\"`."
    )


def test_mypy_strict_mode_is_still_enabled(pyproject_data: dict) -> None:
    """ci.yml relies on [tool.mypy] strict=true; guard against silent drift."""
    assert pyproject_data["tool"]["mypy"]["strict"] is True
