"""Static regression tests for the approved dev deployment contract.

These tests validate .github/workflows/deploy.yml, azure.yaml, infra/**, and
scripts/azure/** as plain text, without invoking GitHub Actions, `az`/`azd`,
or Bicep tooling. They exist to prevent regressions of the exact flaws found
in the first Azure revision, which passed Bicep syntax checks while still:

  * triggering the deploy job on unvetted events,
  * allowing an unrestricted manual redeploy off `main`,
  * granting the ephemeral runner identity Azure deployment RBAC and access
    to the application Key Vault,
  * storing the GitHub runner PAT as a Key Vault secret reference (requiring
    the runner UAMI to read Key Vault) instead of a direct, secure ACA Job
    secret,
  * leaking the runner UAMI's client ID to the job container as
    `AZURE_CLIENT_ID` and leaving a blanket NOPASSWD sudo rule in the image,
  * relying on `unset GITHUB_PAT` for runner credential isolation, which
    leaves the PAT readable in /proc/1/environ for every workflow step,
  * accepting any job the GitHub queue hands the private runner, with no
    runner-side check that it is the trusted deploy workflow on main,
  * offering a `deployPrivateEndpoints=false` steady state that the
    deny-by-default data-plane ACLs make internally contradictory,
  * mixing runner bootstrap resources (ACR, job) into the steady-state
    subscription-scoped `main.bicep` instead of a dedicated bootstrap
    template, and
  * running full post-deploy verification from `azd`'s `postprovision` hook,
    before application code was even deployed.

Assertions here are deliberately structural. The behavioural counterparts —
which actually execute entrypoint.sh and the job-started hook — live in the
same file (see "runner credential isolation — behavioural") and, at
container/PID-1 level, in scripts/azure/runner/verify-pat-isolation.sh.

This file owns none of the files it reads — it is a read-only contract
check colocated with the other static CI/CD regression tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent.parent

DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
AZURE_YAML_PATH = REPO_ROOT / "azure.yaml"

MAIN_BICEP_PATH = REPO_ROOT / "infra" / "main.bicep"
MAIN_JSON_PATH = REPO_ROOT / "infra" / "main.json"
MAIN_PARAMETERS_PATH = REPO_ROOT / "infra" / "main.parameters.json"
BOOTSTRAP_BICEP_PATH = REPO_ROOT / "infra" / "bootstrap-runner.bicep"
IDENTITY_BICEP_PATH = REPO_ROOT / "infra" / "modules" / "identity.bicep"
KEYVAULT_BICEP_PATH = REPO_ROOT / "infra" / "modules" / "keyvault.bicep"
STORAGE_BICEP_PATH = REPO_ROOT / "infra" / "modules" / "storage.bicep"
RUNNER_JOB_BICEP_PATH = REPO_ROOT / "infra" / "modules" / "runner-job.bicep"
RUNNER_IDENTITY_BICEP_PATH = REPO_ROOT / "infra" / "modules" / "runner-identity.bicep"

BOOTSTRAP_SCRIPT_PATH = REPO_ROOT / "scripts" / "azure" / "bootstrap-runner.sh"
WHAT_IF_SCRIPT_PATH = REPO_ROOT / "scripts" / "azure" / "what-if.sh"
RUNNER_DIR_PATH = REPO_ROOT / "scripts" / "azure" / "runner"
ENTRYPOINT_SCRIPT_PATH = RUNNER_DIR_PATH / "entrypoint.sh"
JOB_STAGE_SCRIPT_PATH = RUNNER_DIR_PATH / "job-stage.sh"
JOB_STARTED_HOOK_PATH = RUNNER_DIR_PATH / "hooks" / "job-started.sh"
PAT_ISOLATION_VERIFY_PATH = RUNNER_DIR_PATH / "verify-pat-isolation.sh"
DOCKERFILE_PATH = RUNNER_DIR_PATH / "Dockerfile"
POSTPROVISION_SH_PATH = REPO_ROOT / "scripts" / "azure" / "postprovision.sh"
POSTPROVISION_PS1_PATH = REPO_ROOT / "scripts" / "azure" / "postprovision.ps1"

# Well-known Azure built-in role definition GUIDs that must never be
# assignable to the ephemeral runner identity anywhere in infra/**.
FORBIDDEN_RUNNER_ROLE_IDS = {
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
    "25fbc0a9-bd7c-42ce-9a12-9d123802e6a4": "Cognitive Services Contributor",
    "68e0f677-1727-4a3c-9dc1-9e9f2b6d1f0e": "Azure AI Owner (placeholder guard)",
}


def _read(path: Path) -> str:
    assert path.exists(), f"Expected {path} to exist"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deploy_workflow_text() -> str:
    return _read(DEPLOY_WORKFLOW_PATH)


@pytest.fixture(scope="module")
def azure_yaml_text() -> str:
    return _read(AZURE_YAML_PATH)


@pytest.fixture(scope="module")
def main_bicep_text() -> str:
    return _read(MAIN_BICEP_PATH)


@pytest.fixture(scope="module")
def all_infra_bicep_texts() -> dict[str, str]:
    """Every .bicep file under infra/, keyed by repo-relative path."""
    infra_dir = REPO_ROOT / "infra"
    return {
        str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
        for p in sorted(infra_dir.rglob("*.bicep"))
    }


# ---------------------------------------------------------------------------
# deploy.yml — triggers
# ---------------------------------------------------------------------------


def test_deploy_workflow_has_no_pull_request_or_push_trigger(deploy_workflow_text: str) -> None:
    """This is a public repo; fork-controlled pull_request/push content must
    never be able to reach the private, VNet-connected self-hosted runner."""
    on_match = re.search(
        r"^on:\n(.*?)^permissions:", deploy_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert on_match is not None, "Could not find the 'on:' trigger block in deploy.yml"
    trigger_block = on_match.group(1)

    assert not re.search(r"^\s*pull_request\s*:", trigger_block, re.MULTILINE), (
        "deploy.yml must not trigger on pull_request — fork PRs must never "
        "reach the private self-hosted runner."
    )
    assert not re.search(r"^\s*push\s*:", trigger_block, re.MULTILINE), (
        "deploy.yml must not trigger on push directly; it must only run "
        "after a workflow_run of a successful CI run, or workflow_dispatch."
    )
    assert re.search(r"^\s*workflow_run\s*:", trigger_block, re.MULTILINE)
    assert re.search(r"^\s*workflow_dispatch\s*:", trigger_block, re.MULTILINE)


def test_deploy_workflow_run_trigger_requires_ci_workflow(deploy_workflow_text: str) -> None:
    on_match = re.search(
        r"^on:\n(.*?)^permissions:", deploy_workflow_text, re.MULTILINE | re.DOTALL
    )
    assert on_match is not None
    trigger_block = on_match.group(1)
    workflow_run_match = re.search(
        r"workflow_run:\n(.*?)(?:\n  \w|\Z)", trigger_block, re.DOTALL
    )
    assert workflow_run_match is not None, "Expected a workflow_run: trigger block"
    block = workflow_run_match.group(1)
    assert re.search(r'workflows:\s*\["CI"\]', block), (
        "workflow_run trigger must be scoped to the 'CI' workflow only"
    )
    assert "completed" in block


def test_deploy_job_requires_successful_main_push_ci_for_automatic_trigger(
    deploy_workflow_text: str,
) -> None:
    """A workflow_run event alone proves nothing; the job-level `if:` guard
    is the second, load-bearing layer that keeps a failed run, a PR branch,
    or a fork from ever reaching the private runner."""
    if_match = re.search(r"if:\s*>\n(.*?)\n    runs-on:", deploy_workflow_text, re.DOTALL)
    assert if_match is not None, "Expected the deploy job's multi-line `if:` guard"
    condition = if_match.group(1)

    workflow_run_clause_match = re.search(
        r"github\.event_name == 'workflow_run'.*?\)", condition, re.DOTALL
    )
    assert workflow_run_clause_match is not None
    clause = workflow_run_clause_match.group(0)

    assert "github.event.workflow_run.conclusion == 'success'" in clause, (
        "Automatic redeploy must require a genuinely successful CI conclusion."
    )
    assert "github.event.workflow_run.head_branch == 'main'" in clause, (
        "Automatic redeploy must require the CI run to have been on main."
    )
    # Regression guard: an earlier draft only excluded event == 'pull_request'
    # (double negative, easy to bypass); the fix requires the CI run's own
    # triggering event to have been a 'push' (i.e. main branch protection was
    # already enforced upstream), not merely "not a pull_request".
    assert "github.event.workflow_run.event == 'push'" in clause, (
        "Automatic redeploy must require the upstream CI run to have been "
        "triggered by a push (to main), not just any non-pull_request event."
    )


def test_manual_dispatch_is_explicitly_restricted_to_main(deploy_workflow_text: str) -> None:
    """workflow_dispatch is reachable from any branch by default; the job
    guard must explicitly pin it to refs/heads/main so an operator cannot
    accidentally (or a compromised branch cannot) redeploy from a non-main
    ref onto the approved dev Environment."""
    if_match = re.search(r"if:\s*>\n(.*?)\n    runs-on:", deploy_workflow_text, re.DOTALL)
    assert if_match is not None
    condition = if_match.group(1)

    dispatch_clause_match = re.search(
        r"\(\s*github\.event_name == 'workflow_dispatch'.*?\)", condition, re.DOTALL
    )
    assert dispatch_clause_match is not None, (
        "workflow_dispatch must be checked inside its own parenthesized "
        "clause of the job `if:` condition, alongside a branch restriction."
    )
    clause = dispatch_clause_match.group(0)
    assert "refs/heads/main" in clause, (
        "The workflow_dispatch clause must require github.ref == "
        "'refs/heads/main'; an unrestricted manual dispatch can redeploy "
        "from any branch."
    )


def test_manual_recovery_sha_requires_successful_main_ci(
    deploy_workflow_text: str,
) -> None:
    """An old main ancestor is deployable only with successful CI evidence."""
    assert "actions: read" in deploy_workflow_text
    assert "/actions/workflows/ci.yml/runs?" in deploy_workflow_text
    assert "head_sha == $sha" in deploy_workflow_text
    assert 'head_branch == "main"' in deploy_workflow_text
    assert 'conclusion == "success"' in deploy_workflow_text


def test_deploy_environment_is_dev(deploy_workflow_text: str) -> None:
    assert re.search(r"^\s*environment:\s*dev\s*$", deploy_workflow_text, re.MULTILINE), (
        "The deploy job must target the 'dev' GitHub Environment so the "
        "required-reviewer approval gate applies."
    )


def test_deploy_runs_on_requires_self_hosted_and_dev_runner_label(
    deploy_workflow_text: str,
) -> None:
    match = re.search(r"^\s*runs-on:\s*\[([^\]]+)\]", deploy_workflow_text, re.MULTILINE)
    assert match is not None, "Expected a runs-on: [...] list in deploy.yml"
    labels = {label.strip() for label in match.group(1).split(",")}
    assert "self-hosted" in labels, "deploy.yml must never run on a GitHub-hosted runner"
    assert "aca-intake-dev" in labels, (
        "deploy.yml must be pinned to the aca-intake-dev label; this label "
        "must never be referenced by any pull_request-triggered workflow."
    )


# ---------------------------------------------------------------------------
# deploy.yml — tooling, identity, and blocking gates
# ---------------------------------------------------------------------------


def test_setup_azd_is_pinned_to_v2_commit_sha(deploy_workflow_text: str) -> None:
    match = re.search(r"uses:\s*Azure/setup-azd@(\S+)\s*#\s*(v\d+\.\d+\.\d+)", deploy_workflow_text)
    assert match is not None, "Expected a pinned Azure/setup-azd@<sha> # v2.x.x line"
    sha, version_comment = match.groups()
    assert re.fullmatch(r"[0-9a-f]{40}", sha), (
        f"Azure/setup-azd must be pinned to a 40-char commit SHA, got {sha!r}"
    )
    assert version_comment.startswith("v2"), (
        "Azure/setup-azd must be pinned to a v2.x release — v1 does not "
        "exist and was the confirmed root cause of every prior failed run."
    )


def test_microsoft_foundry_azd_extension_is_installed(deploy_workflow_text: str) -> None:
    assert "azd ext install microsoft.foundry" in deploy_workflow_text, (
        "azd has no built-in knowledge of Foundry resources without this "
        "extension; its installation must be explicit and auditable."
    )


def test_azure_login_uses_oidc_with_no_client_secret(deploy_workflow_text: str) -> None:
    login_match = re.search(
        r"uses:\s*azure/login@[^\n]*\n(.*?)(?=\n      - name:|\Z)",
        deploy_workflow_text,
        re.DOTALL,
    )
    assert login_match is not None, "Expected an azure/login step"
    block = login_match.group(0)
    assert "client-id:" in block
    assert "tenant-id:" in block
    assert "subscription-id:" in block
    assert "client-secret" not in block

    assert "client-secret" not in deploy_workflow_text, (
        "No client secret may appear anywhere in deploy.yml; OIDC federation "
        "removes the need for a stored Azure credential."
    )
    assert re.search(r"^\s*id-token:\s*write\b", deploy_workflow_text, re.MULTILINE), (
        "id-token: write permission is required for OIDC token exchange."
    )


def test_post_deploy_verification_step_is_blocking(deploy_workflow_text: str) -> None:
    step_match = re.search(
        r"- name: Post-deploy verification\n(.*?)(?=\n      - name:|\Z)",
        deploy_workflow_text,
        re.DOTALL,
    )
    assert step_match is not None, "Expected a 'Post-deploy verification' step"
    block = step_match.group(0)
    assert "continue-on-error" not in block, (
        "Post-deploy verification must be blocking: a failed smoke check "
        "means the deployment did not work and the run must fail, not be "
        "marked green."
    )
    assert "post-deploy-verify.sh" in block


def test_what_if_artifact_upload_runs_even_on_failure(deploy_workflow_text: str) -> None:
    """The what-if evidence is most valuable exactly when what-if fails; an
    unconditional (default) step would be skipped after a prior failure."""
    step_match = re.search(
        r"- name: Upload what-if evidence\n(.*?)(?=\n      - name:|\Z)",
        deploy_workflow_text,
        re.DOTALL,
    )
    assert step_match is not None, "Expected an 'Upload what-if evidence' step"
    block = step_match.group(0)
    assert re.search(r"if:\s*(\$\{\{\s*)?always\(\)", block), (
        "Upload what-if evidence must run with `if: always()` so evidence "
        "is captured even when the preceding what-if step fails."
    )


def test_deploy_workflow_has_no_continue_on_error_anywhere(deploy_workflow_text: str) -> None:
    """No required deploy check may be silently masked. Matches the YAML key
    form so the explanatory comment about *removing* continue-on-error does
    not itself trip this guard."""
    assert "continue-on-error:" not in deploy_workflow_text


# ---------------------------------------------------------------------------
# infra/main.bicep — steady-state scope and runner isolation
# ---------------------------------------------------------------------------


def test_main_bicep_is_resource_group_scoped(main_bicep_text: str) -> None:
    """Steady-state provisioning must be scoped to the existing dev resource
    group, not the subscription — the OIDC deployer should need permissions
    only on rg-intake-dev, never subscription-wide Contributor/UAA."""
    scope_match = re.search(r"^targetScope\s*=\s*'([^']+)'", main_bicep_text, re.MULTILINE)
    assert scope_match is not None, "Expected a targetScope declaration in main.bicep"
    assert scope_match.group(1) == "resourceGroup", (
        f"main.bicep targetScope must be 'resourceGroup', found "
        f"{scope_match.group(1)!r}. Subscription scope lets the deploy "
        "identity create/delete resource groups it should never touch."
    )


def test_main_bicep_contains_no_runner_acr_or_job_modules(main_bicep_text: str) -> None:
    """The one-time/rotation runner bootstrap (ACR + job + its identity)
    must live in a dedicated bootstrap Bicep template, never in the
    steady-state template that `azd provision` runs on every deploy —
    otherwise a routine redeploy could recreate/mutate the Container Apps
    Job that is the very runner currently executing it."""
    for forbidden_module in (
        "modules/runner-acr.bicep",
        "modules/runner-job.bicep",
        "modules/runner-identity.bicep",
        "modules/runner-acr-private-endpoint.bicep",
    ):
        assert forbidden_module not in main_bicep_text, (
            f"main.bicep must not reference {forbidden_module}; runner "
            "bootstrap resources belong only in the dedicated bootstrap "
            "Bicep template."
        )
    assert not re.search(r"\brunner\w*", main_bicep_text, re.IGNORECASE), (
        "main.bicep must contain no runner-related identifiers at all — "
        "the runner topology is fully isolated to the bootstrap template."
    )


def test_dedicated_bootstrap_bicep_owns_the_runner_resources() -> None:
    text = _read(BOOTSTRAP_BICEP_PATH)
    assert re.search(r"^targetScope\s*=\s*'resourceGroup'", text, re.MULTILINE)
    for expected_module in (
        "modules/runner-identity.bicep",
        "modules/runner-acr.bicep",
        "modules/runner-job.bicep",
    ):
        assert expected_module in text, (
            f"{BOOTSTRAP_BICEP_PATH.name} must reference {expected_module}; "
            "it is the dedicated home for all runner bootstrap resources."
        )


def test_bootstrap_bicep_is_never_invoked_by_azd_provision(azure_yaml_text: str) -> None:
    """azd provision must only ever run main.bicep; the bootstrap template
    is deliberately out-of-band (human-triggered via bootstrap-runner.sh),
    since azd re-running it on every deploy would race the very runner
    executing that deploy."""
    infra_match = re.search(r"^infra:\n(.*?)(?:\n\w|\Z)", azure_yaml_text, re.MULTILINE | re.DOTALL)
    assert infra_match is not None, "Expected an infra: block in azure.yaml"
    block = infra_match.group(1)
    assert re.search(r"module:\s*main\b", block), "azd must provision module: main only"
    assert "bootstrap-runner" not in azure_yaml_text


# ---------------------------------------------------------------------------
# Runner identity — least privilege
# ---------------------------------------------------------------------------


def test_runner_identity_module_grants_no_deploy_scoped_roles() -> None:
    """runner-identity.bicep itself must declare only the identity resource
    — no role assignment belongs alongside the identity's own definition."""
    text = _read(RUNNER_IDENTITY_BICEP_PATH)
    assert "roleAssignments" not in text, (
        "runner-identity.bicep must only declare the managed identity "
        "resource; RBAC grants (AcrPull, etc.) belong in the resource "
        "module they apply to (e.g. runner-acr.bicep), scoped narrowly."
    )


def test_no_infra_module_grants_the_runner_identity_a_forbidden_role(
    all_infra_bicep_texts: dict[str, str],
) -> None:
    """Scan every .bicep file under infra/ for a role assignment whose
    principalId is the runner identity's output and whose role definition
    is one of the high-privilege built-ins the runner must never hold.
    Only AcrPull (to pull its own container image) is legitimate."""
    for path, text in all_infra_bicep_texts.items():
        references_runner = (
            "runnerIdentityPrincipalId" in text
            or "runnerIdentity.outputs.principalId" in text
        )
        if not references_runner:
            continue
        for role_id, role_name in FORBIDDEN_RUNNER_ROLE_IDS.items():
            assert role_id not in text, (
                f"{path} must not assign the {role_name} role ({role_id}) "
                "anywhere near the runner identity; GitHub OIDC must remain "
                "the sole Azure deployment identity."
            )


def test_runner_identity_has_no_access_to_the_application_key_vault() -> None:
    """The application Key Vault (holding worker/agent secrets) must never
    be readable by the ephemeral runner identity — the runner PAT is a
    direct ACA Job secret, not a Key Vault reference, precisely so this
    identity needs zero Key Vault RBAC."""
    text = _read(KEYVAULT_BICEP_PATH)
    assert not re.search(r"runner", text, re.IGNORECASE), (
        f"{KEYVAULT_BICEP_PATH.name} must not reference the runner identity "
        "in any way (parameter, role assignment, or comment-adjacent code) "
        "— it must have zero Key Vault access."
    )


def test_identity_module_does_not_declare_a_runner_identity() -> None:
    """The shared application identity module (agent/worker/eval/notify)
    must not also mint the runner identity — that lives in its own
    dedicated module referenced only from the bootstrap template."""
    text = _read(IDENTITY_BICEP_PATH)
    assert not re.search(r"runner", text, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Runner PAT handling
# ---------------------------------------------------------------------------


_LITERAL_PAT_PATTERN = re.compile(r"gh[ps]_[A-Za-z0-9]{20,}")


def test_runner_job_bicep_takes_pat_as_a_secure_direct_aca_secret() -> None:
    text = _read(RUNNER_JOB_BICEP_PATH)
    pat_param_match = re.search(
        r"@secure\(\)[^\n]*\n(?:@\w[^\n]*\n)*param\s+githubPat\s+string", text
    )
    assert pat_param_match is not None, (
        "runner-job.bicep's githubPat parameter must be decorated @secure()."
    )

    secret_block_match = re.search(r"secrets:\s*\[\s*\{(.*?)\}\s*\]", text, re.DOTALL)
    assert secret_block_match is not None, "Expected a secrets: [...] block"
    secret_block = secret_block_match.group(1)
    assert "value: githubPat" in secret_block, (
        "The GitHub PAT must be wired as a direct ACA Job secret value "
        "(the secure bootstrap parameter), not a keyVaultUrl reference — "
        "the runner identity must not need Key Vault access at all."
    )
    assert "keyVaultUrl" not in secret_block, (
        "runner-job.bicep must not source the PAT secret from Key Vault."
    )
    assert not _LITERAL_PAT_PATTERN.search(text), "No literal PAT value may appear in Bicep."


def test_bootstrap_bicep_pat_parameter_is_secure_and_never_literal() -> None:
    text = _read(BOOTSTRAP_BICEP_PATH)
    assert re.search(r"@secure\(\)[^\n]*\n(?:@\w[^\n]*\n)*param\s+githubPat\s+string", text), (
        "bootstrap-runner.bicep's githubPat parameter must be @secure()."
    )
    assert not _LITERAL_PAT_PATTERN.search(text)


def test_bootstrap_script_never_logs_or_persists_the_pat_literal() -> None:
    text = _read(BOOTSTRAP_SCRIPT_PATH)
    assert "GITHUB_RUNNER_PAT" in text, (
        "bootstrap-runner.sh must source the PAT from the "
        "GITHUB_RUNNER_PAT environment variable, never a literal."
    )
    assert not _LITERAL_PAT_PATTERN.search(text)
    assert "unset GITHUB_RUNNER_PAT" in text, (
        "The PAT must be unset from the bootstrap shell's environment once "
        "it has been handed to the deployment, limiting its exposure window."
    )


def test_entrypoint_confines_the_pat_to_a_bootstrap_stage_that_execs_away() -> None:
    """`unset GITHUB_PAT` was the rejected design: a process's initial
    environment block stays readable through /proc/<pid>/environ no matter
    what the shell later unsets, and workflow steps run as the same UID as
    PID 1. Isolation must therefore come from replacing PID 1's environment
    with execve, not from editing the shell's variable table."""
    text = _read(ENTRYPOINT_SCRIPT_PATH)
    assert not _LITERAL_PAT_PATTERN.search(text)

    assert re.search(r"^\s*unset\s+GITHUB_PAT\s*$", text, re.MULTILINE) is None, (
        "entrypoint.sh must not rely on `unset GITHUB_PAT` — it leaves the PAT "
        "in /proc/1/environ for every workflow step to read."
    )

    exec_match = re.search(
        r'^exec\s+/usr/bin/env\s+-i\s+"\$\{clean_env\[@\]\}"\s+"\$JOB_STAGE"\s*$',
        text,
        re.MULTILINE,
    )
    assert exec_match is not None, (
        "The bootstrap stage must hand over with `exec /usr/bin/env -i` so the "
        "kernel builds PID 1 a brand-new environment block."
    )

    clean_env_match = re.search(r"clean_env=\(\s*(.*?)\)\n", text, re.DOTALL)
    assert clean_env_match is not None, "Expected an explicit clean_env allow-list"
    clean_env = clean_env_match.group(1)
    assert "GITHUB_PAT" not in clean_env, "The PAT must never be in the clean environment"

    # The bootstrap stage must not be able to start a job itself.
    assert re.search(r"^\s*\./run\.sh", text, re.MULTILINE) is None, (
        "entrypoint.sh (the stage that holds the PAT) must never run ./run.sh"
    )
    assert re.search(r"^\s*\./config\.sh", text, re.MULTILINE) is None, (
        "entrypoint.sh (the stage that holds the PAT) must never run ./config.sh"
    )


def test_entrypoint_passes_the_registration_token_through_a_tmpfs_file() -> None:
    """The short-lived registration token must cross the exec boundary on
    tmpfs, never in the environment (which is exactly what is being wiped)."""
    text = _read(ENTRYPOINT_SCRIPT_PATH)
    assert "/dev/shm" in text, "tmpfs (/dev/shm) must be the preferred token location"
    assert re.search(r'mktemp\s+-d\s+"\$\{TOKEN_ROOT\}/', text), (
        "The token must live in a private, per-execution directory"
    )
    assert "umask 077" in text
    assert re.search(r"chmod 600 \"\$TOKEN_FILE\"", text)
    # The token is piped straight to disk — it is never a shell variable in the
    # stage that still holds the PAT, so it cannot be exported by accident.
    assert re.search(r"jq -er '\.token' >\"\$TOKEN_FILE\"", text)
    assert "INTAKE_RUNNER_TOKEN_FILE=${TOKEN_FILE}" in text


def test_entrypoint_drops_managed_identity_credentials_too() -> None:
    """Container Apps injects IDENTITY_ENDPOINT/IDENTITY_HEADER for any job
    with a managed identity. An allow-list — not a deny-list of known-bad
    names — is what keeps those out of the job environment."""
    text = _read(ENTRYPOINT_SCRIPT_PATH)
    assert "IDENTITY_ENDPOINT" in text and "IDENTITY_HEADER" in text, (
        "The rationale for allow-listing must name the ACA identity endpoints "
        "so the next editor does not 'simplify' them back in."
    )
    clean_env_match = re.search(r"clean_env=\(\s*(.*?)\)\n", text, re.DOTALL)
    assert clean_env_match is not None
    forbidden = ("IDENTITY_ENDPOINT", "IDENTITY_HEADER", "MSI_SECRET", "AZURE_CLIENT_ID")
    for name in forbidden:
        assert name not in clean_env_match.group(1), (
            f"{name} must not be forwarded into the job stage environment"
        )


def test_job_stage_destroys_the_token_before_the_runner_can_accept_a_job() -> None:
    text = _read(JOB_STAGE_SCRIPT_PATH)
    assert not _LITERAL_PAT_PATTERN.search(text)

    def position(pattern: str) -> int:
        """Index of a real command, never a mention of one in a comment."""
        match = re.search(pattern, text, re.MULTILINE)
        assert match is not None, f"Expected {pattern!r} as an executed command"
        return match.start()

    read_pos = position(r'^REG_TOKEN="\$\(cat "\$INTAKE_RUNNER_TOKEN_FILE"\)"$')
    delete_pos = position(r'^rm -f "\$INTAKE_RUNNER_TOKEN_FILE"$')
    config_pos = position(r"^\./config\.sh")
    unset_pos = position(r"^unset REG_TOKEN$")
    run_pos = position(r"^exec \./run\.sh$")

    assert read_pos < delete_pos < config_pos < unset_pos < run_pos, (
        "Order must be: read token → delete file → configure → unset → run.sh"
    )
    assert re.search(r'\[\[ ! -e "\$INTAKE_RUNNER_TOKEN_FILE" \]\]', text), (
        "The job stage must verify the token file is actually gone, not assume it"
    )
    assert "export REG_TOKEN" not in text, "The token must stay a non-exported variable"
    assert "--ephemeral" in text


def test_job_stage_fails_closed_if_a_credential_survived_the_exec() -> None:
    """A regression in the allow-list must stop the container, not silently
    hand a live credential to an untrusted workflow job."""
    text = _read(JOB_STAGE_SCRIPT_PATH)
    for name in ("GITHUB_PAT", "IDENTITY_HEADER", "MSI_SECRET", "AZURE_CLIENT_ID"):
        assert name in text, f"{name} must be part of the survivor check"
    assert "/proc/1/environ" in text, (
        "The job stage must check the kernel's copy of PID 1's environment — "
        "the exact thing a malicious step would read — not just shell state."
    )
    assert "refusing to register a runner" in text


def test_no_long_lived_removal_token_is_retained_anywhere() -> None:
    """A removal token held for the duration of the job would reintroduce the
    leak the two-stage design removes; `--ephemeral` deregistration replaces
    it."""
    for path in (ENTRYPOINT_SCRIPT_PATH, JOB_STAGE_SCRIPT_PATH):
        text = _read(path)
        assert "remove-token" not in text, f"{path.name} must not mint a removal token"
        assert "config.sh remove" not in text, (
            f"{path.name} must not keep a token around to deregister the runner"
        )


# ---------------------------------------------------------------------------
# Trusted-workflow admission hook
# ---------------------------------------------------------------------------

HOOK_ENV_VAR = "ACTIONS_RUNNER_HOOK_JOB_STARTED"
HOOK_INSTALL_PATH = "/opt/runner-hooks/job-started.sh"


def test_runner_job_bicep_wires_the_job_started_hook() -> None:
    """Official runner semantics: a job-started hook exits non-zero → the job
    fails before any step runs, and continue-on-error cannot suppress it."""
    text = _read(RUNNER_JOB_BICEP_PATH)
    env_match = re.search(
        r"\{\s*name:\s*'ACTIONS_RUNNER_HOOK_JOB_STARTED'\s*value:\s*(\w+)\s*\}",
        text,
    )
    assert env_match is not None, (
        "runner-job.bicep must set ACTIONS_RUNNER_HOOK_JOB_STARTED as a container env var"
    )
    param_default = re.search(
        r"param\s+" + env_match.group(1) + r"\s+string\s*=\s*'([^']+)'", text
    )
    assert param_default is not None, "The hook path must have an explicit default"
    assert param_default.group(1) == HOOK_INSTALL_PATH


def test_runner_dockerfile_installs_the_hook_root_owned_and_read_only() -> None:
    """The hook and both entrypoint stages must be untouchable by the
    workflow job, which runs as `runner`."""
    text = _read(DOCKERFILE_PATH)
    assert "COPY hooks/job-started.sh /opt/runner-hooks/" in text
    assert "COPY entrypoint.sh job-stage.sh /opt/runner-bin/" in text
    assert "--chown=runner:runner entrypoint.sh" not in text, (
        "The entrypoint must not be owned (and therefore rewritable) by the runner user"
    )
    assert re.search(r"chmod 0555 /opt/runner-bin/entrypoint\.sh", text)
    assert re.search(r"/opt/runner-hooks/job-started\.sh", text)
    assert 'ENTRYPOINT ["/opt/runner-bin/entrypoint.sh"]' in text
    # GitHub's guidance: hooks must not live in the runner application dir,
    # which a job can write to (_work, _diag and .credentials all live there).
    assert "/home/runner/actions-runner/job-started.sh" not in text


def test_entrypoint_refuses_to_start_without_an_immutable_hook() -> None:
    text = _read(ENTRYPOINT_SCRIPT_PATH)
    assert f': "${{{HOOK_ENV_VAR}:?' in text, "The hook must be mandatory (fail closed)"
    assert re.search(r'\[\[ ! -w "\$HOOK_PATH" \]\]', text), (
        "A hook the runner user can rewrite is no control at all"
    )
    assert re.search(r'\[\[ ! -w "\$HOOK_DIR" \]\]', text)
    assert re.search(r'\[\[ -x "\$HOOK_PATH" \]\]', text)
    assert "$ACTIONS_RUNNER_HOOK_JOB_STARTED" in text
    assert "ACTIONS_RUNNER_HOOK_JOB_STARTED=${HOOK_PATH}" in text, (
        "The hook path must survive into the clean job-stage environment, "
        "otherwise the runner silently skips it."
    )


# ---------------------------------------------------------------------------
# Runner credential isolation — behavioural
#
# The structural checks above cannot prove that the PAT is gone; only running
# the scripts can. These execute the real entrypoint.sh and job-stage.sh with
# GitHub's API, config.sh and run.sh stubbed, and assert on the environment
# the runner would actually have been started with. The PID-1 / on-disk
# version of the same proof runs in a container:
#     bash scripts/azure/runner/verify-pat-isolation.sh
# ---------------------------------------------------------------------------

_SENTINEL_PAT = "ghp_" + "SENTINELPATVALUEDONOTUSE0000"
_SENTINEL_REG_TOKEN = "SENTINELREGISTRATIONTOKEN0000"

_needs_posix_shell = pytest.mark.skipif(
    sys.platform.startswith("win") or shutil.which("bash") is None,
    reason="requires a POSIX bash",
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def isolation_harness(tmp_path: Path):
    """Stubs GitHub's API (curl/jq) and the runner's own config.sh/run.sh so
    the real two-stage entrypoint can be executed end to end."""
    bin_dir = tmp_path / "bin"
    runner_dir = tmp_path / "actions-runner"
    hooks_dir = tmp_path / "hooks"
    shm_dir = tmp_path / "shm"
    evidence = tmp_path / "evidence"
    for directory in (bin_dir, runner_dir, hooks_dir, shm_dir, evidence):
        directory.mkdir()

    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'printf "%s" "${{GITHUB_PAT:-}}" > "{evidence}/curl-saw-pat"\n'
        f'printf \'{{"token":"{_SENTINEL_REG_TOKEN}"}}\\n\'\n',
    )
    # `jq -er '.token'` over the stub response.
    _write_executable(
        bin_dir / "jq",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "value=\"$(sed -n 's/.*\"token\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p')\"\n"
        '[[ -n "$value" ]] || exit 1\n'
        'printf "%s\\n" "$value"\n',
    )
    _write_executable(
        runner_dir / "config.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'printf "%s\\n" "$@" > "{evidence}/config-args"\n'
        f'env > "{evidence}/config-env"\n'
        f'if [[ -e "${{INTAKE_RUNNER_TOKEN_FILE}}" ]]; then\n'
        f'  echo present > "{evidence}/token-file-still-there"\n'
        "fi\n",
    )
    _write_executable(
        runner_dir / "run.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'env > "{evidence}/run-env"\n'
        f'ls -A "{shm_dir}" > "{evidence}/shm-listing"\n',
    )
    hook = hooks_dir / "job-started.sh"
    hook.write_text(JOB_STARTED_HOOK_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    hook.chmod(0o555)
    hooks_dir.chmod(0o555)  # entrypoint refuses a hook dir the runner can write

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
        "GITHUB_PAT": _SENTINEL_PAT,
        "GITHUB_OWNER": "intake-owner",
        "GITHUB_REPOSITORY": "intake-agent",
        "RUNNER_LABELS": "aca-intake-dev",
        "INTAKE_ENVIRONMENT": "dev",
        "ACTIONS_RUNNER_HOOK_JOB_STARTED": str(hook),
        "INTAKE_RUNNER_DIR": str(runner_dir),
        "INTAKE_RUNNER_JOB_STAGE": str(JOB_STAGE_SCRIPT_PATH),
        "INTAKE_RUNNER_TOKEN_DIR": str(shm_dir),
        # Deliberately present: Container Apps injects these for any job with a
        # managed identity, and they must not survive the exec either.
        "IDENTITY_ENDPOINT": "http://169.254.169.254/metadata/identity/oauth2/token",
        "IDENTITY_HEADER": "sentinel-managed-identity-header",
    }
    try:
        yield env, evidence, shm_dir
    finally:
        hooks_dir.chmod(0o755)  # let pytest clean the tmp dir up


@_needs_posix_shell
def test_entrypoint_starts_run_sh_with_no_pat_in_its_environment(
    isolation_harness,
) -> None:
    env, evidence, shm_dir = isolation_harness
    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"entrypoint failed:\n{result.stdout}\n{result.stderr}"

    # Positive control: the bootstrap stage really did hold the sentinel PAT,
    # so "absent later" is a meaningful result rather than a broken detector.
    assert (evidence / "curl-saw-pat").read_text() == _SENTINEL_PAT

    run_env = (evidence / "run-env").read_text()
    assert "GITHUB_PAT" not in run_env, (
        "run.sh — the process that accepts the untrusted job — must start with "
        "no PAT in its environment"
    )
    assert _SENTINEL_PAT not in run_env
    assert _SENTINEL_REG_TOKEN not in run_env, (
        "The registration token must not be exported into the runner environment"
    )
    for leaked in ("IDENTITY_HEADER", "IDENTITY_ENDPOINT"):
        assert leaked not in run_env, (
            f"{leaked} would let a workflow step mint tokens for the runner's "
            "own managed identity"
        )
    assert "ACTIONS_RUNNER_HOOK_JOB_STARTED=" in run_env, (
        "The admission hook must still be configured in the clean environment"
    )


@_needs_posix_shell
def test_registration_token_reaches_config_then_is_deleted(isolation_harness) -> None:
    env, evidence, shm_dir = isolation_harness
    result = subprocess.run(
        ["bash", str(ENTRYPOINT_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    config_args = (evidence / "config-args").read_text().splitlines()
    assert "--token" in config_args
    assert config_args[config_args.index("--token") + 1] == _SENTINEL_REG_TOKEN
    assert "--ephemeral" in config_args

    config_env = (evidence / "config-env").read_text()
    assert _SENTINEL_REG_TOKEN not in config_env, (
        "The token must be a non-exported shell variable during config"
    )
    assert _SENTINEL_PAT not in config_env

    assert not (evidence / "token-file-still-there").exists(), (
        "The token file must be deleted before config.sh runs"
    )
    assert (evidence / "shm-listing").read_text().strip() == "", (
        "No token material may remain on tmpfs when run.sh starts"
    )
    assert not any(shm_dir.iterdir())


# ---------------------------------------------------------------------------
# Trusted-workflow hook — behavioural
# ---------------------------------------------------------------------------

_TRUSTED_HOOK_ENV = {
    "INTAKE_TRUSTED_REPOSITORY": "intake-owner/intake-agent",
    "GITHUB_REPOSITORY": "intake-owner/intake-agent",
    "GITHUB_WORKFLOW_REF": (
        "intake-owner/intake-agent/.github/workflows/deploy.yml@refs/heads/main"
    ),
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_EVENT_NAME": "workflow_run",
}


def _run_hook(
    overrides: dict[str, str],
    *,
    drop: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **_TRUSTED_HOOK_ENV}
    env.update(overrides)
    for key in drop:
        env.pop(key, None)
    # The runner invokes .sh hooks as `bash -e <path>`.
    return subprocess.run(
        ["bash", "-e", str(JOB_STARTED_HOOK_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@_needs_posix_shell
@pytest.mark.parametrize("event", ["workflow_run", "workflow_dispatch"])
def test_hook_admits_the_trusted_deploy_workflow_on_main(event: str) -> None:
    result = _run_hook({"GITHUB_EVENT_NAME": event})
    assert result.returncode == 0, f"hook rejected a trusted job:\n{result.stderr}"
    assert "ALLOWED" in result.stdout


@_needs_posix_shell
@pytest.mark.parametrize(
    ("overrides", "drop", "reason"),
    [
        ({"GITHUB_REF": "refs/heads/feature"}, (), "non-main ref"),
        ({"GITHUB_REF": "refs/pull/7/merge"}, (), "pull request merge ref"),
        (
            {
                "GITHUB_WORKFLOW_REF": (
                    "intake-owner/intake-agent/.github/workflows/attacker.yml@refs/heads/main"
                )
            },
            (),
            "another workflow file",
        ),
        (
            {
                "GITHUB_WORKFLOW_REF": (
                    "intake-owner/intake-agent/.github/workflows/deploy.yml@refs/heads/dev"
                )
            },
            (),
            "deploy.yml from an unprotected branch",
        ),
        (
            {
                "GITHUB_REPOSITORY": "attacker/intake-agent",
                "GITHUB_WORKFLOW_REF": (
                    "attacker/intake-agent/.github/workflows/deploy.yml@refs/heads/main"
                ),
            },
            (),
            "a different repository",
        ),
        ({"GITHUB_EVENT_NAME": "pull_request"}, (), "fork-controlled event"),
        ({"GITHUB_EVENT_NAME": "push"}, (), "unvetted push event"),
        ({}, ("GITHUB_WORKFLOW_REF",), "missing workflow ref"),
        ({}, ("GITHUB_REPOSITORY",), "missing repository"),
        ({}, ("GITHUB_EVENT_NAME",), "missing event name"),
        ({}, ("INTAKE_TRUSTED_REPOSITORY",), "runner started without a trusted repo"),
    ],
)
def test_hook_fails_the_job_before_any_step_runs(
    overrides: dict[str, str], drop: tuple[str, ...], reason: str
) -> None:
    result = _run_hook(overrides, drop=drop)
    assert result.returncode != 0, f"hook admitted a job it must reject ({reason})"
    assert "::error::" in result.stdout, (
        "The rejection must be annotated on the failed job so it is diagnosable"
    )


def test_pat_isolation_reproduction_script_is_available_and_documented() -> None:
    """The PID-1 level proof cannot run in the PR unit suite (no daemon
    guarantee), so it must exist as a runnable, discoverable command."""
    text = _read(PAT_ISOLATION_VERIFY_PATH)
    assert os.access(PAT_ISOLATION_VERIFY_PATH, os.X_OK), (
        f"{PAT_ISOLATION_VERIFY_PATH.name} must be executable"
    )
    assert "/proc/1/environ" in text
    assert "POSITIVE CONTROL" in text, (
        "A leak test with no positive control cannot distinguish 'secure' from "
        "'detector broken'"
    )
    assert "docker" in text
    # It must exercise the real scripts, not a paraphrase of them.
    for name in ("entrypoint.sh", "job-stage.sh", "hooks/job-started.sh"):
        assert name in text
    assert ENTRYPOINT_SCRIPT_PATH.parent.name == "runner"


# ---------------------------------------------------------------------------
# Private-only architecture — the non-private fallback must be unreachable
# ---------------------------------------------------------------------------


def test_main_bicep_exposes_no_private_endpoint_toggle(main_bicep_text: str) -> None:
    """Every data service is publicNetworkAccess:Disabled with deny-by-default
    ACLs and the deploy pipeline runs on a VNet-injected runner, so
    `deployPrivateEndpoints=false` is not a supported steady state — it is a
    resource group that denies everyone. The parameter is removed rather than
    defaulted, so ARM rejects the deployment if a caller still passes it."""
    assert not re.search(r"^param\s+deployPrivateEndpoints\b", main_bicep_text, re.MULTILINE), (
        "deployPrivateEndpoints must not be a selectable parameter of main.bicep"
    )
    assert not re.search(
        r"^param\s+deployStoragePrivateEndpoint\b", main_bicep_text, re.MULTILINE
    ), "The storage-only private endpoint escape hatch is stale once PEs are mandatory"
    assert re.search(r"^var\s+deployPrivateEndpoints\s*=\s*true\s*$", main_bicep_text, re.MULTILINE)
    assert "deployPrivateEndpoints: deployPrivateEndpoints" in main_bicep_text
    assert not re.search(
        r"deployPrivateEndpoints\s*:\s*false|deployStoragePrivateEndpoint\s*:\s*false",
        main_bicep_text,
    ), "No module may be handed a false private-endpoint flag"


def test_compiled_main_json_cannot_be_deployed_without_private_endpoints() -> None:
    """infra/main.json is the compiled artifact CI scans and an operator could
    deploy directly; it must not reintroduce the toggle."""
    compiled = json.loads(_read(MAIN_JSON_PATH))
    assert "deployPrivateEndpoints" not in compiled["parameters"]
    assert "deployStoragePrivateEndpoint" not in compiled["parameters"]
    assert compiled["variables"]["deployPrivateEndpoints"] is True


def test_main_parameters_file_carries_no_removed_flags() -> None:
    parameters = json.loads(_read(MAIN_PARAMETERS_PATH))["parameters"]
    for removed in ("deployPrivateEndpoints", "deployStoragePrivateEndpoint"):
        assert removed not in parameters, (
            f"{removed} no longer exists in main.bicep; ARM fails the whole "
            "deployment when a parameters file supplies an unknown parameter."
        )


def test_what_if_passes_no_removed_parameters() -> None:
    text = _read(WHAT_IF_SCRIPT_PATH)
    # Only executed lines matter; the header comment deliberately records the
    # history of this drift.
    executable = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "deployPrivateEndpoints=" not in executable, (
        "what-if must not pass a parameter main.bicep no longer declares — ARM "
        "fails the whole what-if with InvalidTemplate."
    )
    assert "deployStoragePrivateEndpoint=" not in executable
    assert "--parameters infra/main.parameters.json" in executable, (
        "what-if must keep mirroring the real provision parameter file"
    )


def test_bootstrap_bicep_always_creates_the_private_runner_registry() -> None:
    text = _read(BOOTSTRAP_BICEP_PATH)
    assert not re.search(r"^param\s+deployPrivateEndpoints\b", text, re.MULTILINE), (
        "The runner ACR is private-only; there is no supported public fallback"
    )
    assert re.search(
        r"module runnerAcrPrivateEndpoint 'modules/runner-acr-private-endpoint\.bicep' = \{",
        text,
    ), "The ACR private endpoint must be unconditional"
    assert "deployPrivateEndpoints: true" in text
    assert "acrAllowPublicNetworkAccessForBootstrap: false" in text


def test_data_plane_acls_stay_deny_by_default() -> None:
    """Removing the toggle must not have been done by relaxing the ACLs."""
    keyvault = _read(KEYVAULT_BICEP_PATH)
    storage = _read(STORAGE_BICEP_PATH)
    assert "defaultAction: 'Deny'" in keyvault
    assert "defaultAction: 'Deny'" in storage
    assert "publicNetworkAccess: 'Disabled'" in keyvault
    assert "publicNetworkAccess: 'Disabled'" in storage
    assert "param deployPrivateEndpoints" not in keyvault
    assert "param deployPrivateEndpoints" not in storage
    assert "allowBlobPublicAccess: false" in storage
    assert "allowSharedKeyAccess: false" in storage


def test_dev_resource_names_are_unchanged(main_bicep_text: str) -> None:
    """The private-only cleanup must not rename anything already deployed."""
    for name in (
        "'vnet-intake-${environmentName}'",
        "'cae-intake-${environmentName}'",
        "'func-intake-${environmentName}'",
        "'kv-${take(resourceToken, 16)}'",
        "'st${take(resourceToken, 10)}'",
        "'cosmos-${take(resourceToken, 10)}'",
        "'srch-${take(resourceToken, 12)}'",
        "'ais-intake-${take(resourceToken, 8)}'",
        "'aiproj-intake-${environmentName}'",
    ):
        assert name in main_bicep_text, f"Resource name {name} must not change"


# ---------------------------------------------------------------------------
# Runner container hardening
# ---------------------------------------------------------------------------


def test_runner_job_does_not_expose_its_identity_as_azure_client_id() -> None:
    """The runner UAMI must not be selectable by anything running inside the
    job payload — GitHub OIDC (obtained fresh by azure/login in deploy.yml)
    must remain the sole Azure deployment identity available to the job."""
    text = _read(RUNNER_JOB_BICEP_PATH)
    assert "AZURE_CLIENT_ID" not in text, (
        "runner-job.bicep must not set an AZURE_CLIENT_ID container env var "
        "wired to the runner identity's client ID."
    )


def test_runner_dockerfile_grants_no_runtime_nopasswd_sudo() -> None:
    text = _read(DOCKERFILE_PATH)
    assert "NOPASSWD" not in text, (
        "The runner image must not leave a blanket NOPASSWD sudo rule "
        "active at runtime; any elevated access needed only at build time "
        "must not persist into the running container."
    )
    # The final stage must run as the unprivileged user, not root.
    user_directives = re.findall(r"^USER\s+(\S+)\s*$", text, re.MULTILINE)
    assert user_directives, "Expected at least one USER directive"
    assert user_directives[-1] != "root", (
        "The final USER directive must not be root."
    )


# ---------------------------------------------------------------------------
# azure.yaml — hook ordering and Foundry endpoint
# ---------------------------------------------------------------------------


def test_postprovision_hooks_do_not_run_post_deploy_verification(azure_yaml_text: str) -> None:
    """postprovision runs immediately after `azd provision`, before `azd
    deploy` has pushed any application code — running the full smoke suite
    there produces false failures (or false confidence) about code that
    does not exist yet. Full verification must only run after `azd deploy`
    (already wired as an explicit deploy.yml step)."""
    hooks_match = re.search(r"^hooks:\n(.*)\Z", azure_yaml_text, re.MULTILINE | re.DOTALL)
    assert hooks_match is not None, "Expected a hooks: block in azure.yaml"
    postprovision_match = re.search(
        r"postprovision:\n(.*?)(?=\n {4}\w|\Z)", hooks_match.group(1), re.DOTALL
    )
    assert postprovision_match is not None, "Expected a postprovision: hook"
    block = postprovision_match.group(1)
    assert "postprovision.sh" in block
    assert "postprovision.ps1" in block

    for script_path in (POSTPROVISION_SH_PATH, POSTPROVISION_PS1_PATH):
        script_text = _read(script_path)
        assert "post-deploy-verify" not in script_text, (
            f"{script_path.name} (invoked from azd's postprovision hook) "
            "must not call post-deploy-verify — full verification belongs "
            "only after `azd deploy`."
        )


def test_full_post_deploy_verification_runs_only_after_azd_deploy(
    deploy_workflow_text: str,
) -> None:
    deploy_step_match = re.search(r"- name: azd deploy\n", deploy_workflow_text)
    verify_step_match = re.search(r"- name: Post-deploy verification\n", deploy_workflow_text)
    assert deploy_step_match is not None
    assert verify_step_match is not None
    assert deploy_step_match.start() < verify_step_match.start(), (
        "Post-deploy verification must be sequenced strictly after the "
        "'azd deploy' step in deploy.yml."
    )


def test_foundry_deployment_is_unconditional(main_bicep_text: str) -> None:
    """A previously ineffective deployFoundry toggle always hardcoded true
    in main.parameters.json, so the parameter never changed behavior — it
    must be gone, and the module itself must have no `if (...)` guard."""
    assert "deployFoundry" not in main_bicep_text, (
        "The dead deployFoundry parameter must not exist; Foundry is "
        "unconditional in this template."
    )
    foundry_module_match = re.search(
        r"module\s+foundry\s+'modules/foundry\.bicep'\s*=\s*(\S+)",
        main_bicep_text,
    )
    assert foundry_module_match is not None, "Expected a `module foundry ...` declaration"
    assert foundry_module_match.group(1) == "{", (
        "The foundry module must not be gated behind an `if (...)` "
        f"condition; found {foundry_module_match.group(1)!r} instead of "
        "the opening '{' of an unconditional module body."
    )


def test_azure_yaml_ai_project_endpoint_comes_from_the_bicep_output(
    azure_yaml_text: str, main_bicep_text: str
) -> None:
    """The ai-project service endpoint must be wired from azd's environment
    (ultimately the Bicep AZURE_AI_PROJECT_ENDPOINT output), never a
    hardcoded literal URL."""
    endpoint_match = re.search(
        r"ai-project:\n(?:.*\n){0,4}?\s*endpoint:\s*(\S+)", azure_yaml_text
    )
    assert endpoint_match is not None, "Expected the ai-project service's endpoint: field"
    assert endpoint_match.group(1) == "${AZURE_AI_PROJECT_ENDPOINT}", (
        f"ai-project endpoint must reference ${{AZURE_AI_PROJECT_ENDPOINT}}, "
        f"found {endpoint_match.group(1)!r}."
    )
    assert not re.search(r"endpoint:\s*https?://", azure_yaml_text), (
        "azure.yaml must not hardcode a literal https:// endpoint for any "
        "Foundry-backed service."
    )
    assert re.search(
        r"output\s+AZURE_AI_PROJECT_ENDPOINT\s+string\s*=\s*foundry\.outputs\.projectEndpoint",
        main_bicep_text,
    ), "main.bicep must output AZURE_AI_PROJECT_ENDPOINT from the foundry module."


# ---------------------------------------------------------------------------
# Cross-cutting: no continue-on-error/continueOnError anywhere in this
# deployment surface
# ---------------------------------------------------------------------------


def test_no_continue_on_error_masks_any_required_deploy_check(
    deploy_workflow_text: str, azure_yaml_text: str, all_infra_bicep_texts: dict[str, str]
) -> None:
    assert "continue-on-error:" not in deploy_workflow_text
    assert "continue-on-error:" not in azure_yaml_text
    assert "continueOnError" not in azure_yaml_text
    for path, text in all_infra_bicep_texts.items():
        assert "continueOnError" not in text, f"{path} must not set continueOnError"

    for script_path in (
        BOOTSTRAP_SCRIPT_PATH,
        ENTRYPOINT_SCRIPT_PATH,
        POSTPROVISION_SH_PATH,
    ):
        text = _read(script_path)
        # A required step masked with `|| true`/`|| echo ...` right after a
        # blocking command is the shell equivalent of continue-on-error.
        assert not re.search(r"post-deploy-verify\.sh.*\|\|", text), (
            f"{script_path.name} must not swallow a post-deploy-verify.sh "
            "failure with `||`."
        )
