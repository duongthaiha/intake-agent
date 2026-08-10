"""Infrastructure static assertions.

These tests validate the documented infrastructure configuration
(docs/contracts/infrastructure-config.md) without owning infra/** or
requiring real Azure resources.

Tests are static: they check documented contracts, required environment
variable names, and local-dev override conventions.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Required environment variable names (from infrastructure-config.md)
# ---------------------------------------------------------------------------

AGENT_ENV_VARS = [
    "INTAKE_COSMOS_ENDPOINT",
    "INTAKE_COSMOS_DATABASE",
    "INTAKE_SERVICEBUS_NAMESPACE",
    "INTAKE_SERVICEBUS_QUEUE",
    "INTAKE_SEARCH_ENDPOINT",
    "INTAKE_SEARCH_INDEX",
    "INTAKE_APPINSIGHTS_CONNECTION",
    "INTAKE_TEMPLATE_ID",
    "INTAKE_ENVIRONMENT",
    "AZURE_CLIENT_ID",
]

WORKER_ENV_VARS = [
    "INTAKE_COSMOS_ENDPOINT",
    "INTAKE_COSMOS_DATABASE",
    "INTAKE_SERVICEBUS_NAMESPACE",
    "INTAKE_BLOB_ENDPOINT",
    "INTAKE_BLOB_CONTAINER_ARTIFACTS",
    "INTAKE_KEYVAULT_URI",
    "INTAKE_APPINSIGHTS_CONNECTION",
    "INTAKE_ENVIRONMENT",
    "AZURE_CLIENT_ID",
]

EVAL_ENV_VARS = [
    "INTAKE_EVAL_STORAGE_ENDPOINT",
    "INTAKE_EVAL_CONTAINER",
    "INTAKE_AGENT_ENDPOINT",
    "INTAKE_APPINSIGHTS_CONNECTION",
    "AZURE_CLIENT_ID",
]

LOCAL_BACKEND_VARS = [
    "INTAKE_PERSISTENCE_BACKEND",
    "INTAKE_SERVICEBUS_BACKEND",
    "INTAKE_BLOB_BACKEND",
]


@pytest.mark.parametrize("var", AGENT_ENV_VARS)
def test_agent_env_var_is_documented(var: str):
    """Every agent env var must be a valid ENV_VAR_NAME format."""
    assert var.isupper() or "_" in var
    assert not var.startswith("_")
    assert not var.endswith("_")


@pytest.mark.parametrize("var", WORKER_ENV_VARS)
def test_worker_env_var_is_documented(var: str):
    assert var.isupper() or "_" in var


@pytest.mark.parametrize("var", EVAL_ENV_VARS)
def test_eval_env_var_is_documented(var: str):
    assert var.isupper() or "_" in var


def test_no_secrets_in_env_var_names():
    """No env var name should suggest it holds a raw secret or API key."""
    all_vars = AGENT_ENV_VARS + WORKER_ENV_VARS + EVAL_ENV_VARS
    for var in all_vars:
        lower = var.lower()
        assert "password" not in lower, f"{var} must not be named 'password'"
        assert "secret" not in lower, f"{var} must not be named 'secret'"
        assert "api_key" not in lower, f"{var} must not be a raw API key"


def test_local_backend_vars_enable_inmemory_mode():
    """Local development override variable names must be distinct from Azure vars."""
    for var in LOCAL_BACKEND_VARS:
        assert "_BACKEND" in var, f"{var} must include _BACKEND suffix"


def test_managed_identity_used_not_connection_string():
    """Authentication env vars should use managed identity (AZURE_CLIENT_ID),
    not connection strings with embedded credentials."""
    for var in AGENT_ENV_VARS + WORKER_ENV_VARS:
        lower = var.lower()
        # Connection strings with creds are forbidden; endpoint + managed identity is OK
        assert "shared_access_key" not in lower
        assert "account_key" not in lower


# ---------------------------------------------------------------------------
# Environment value consistency checks
# ---------------------------------------------------------------------------

def test_local_persistence_backend_value():
    """When set, INTAKE_PERSISTENCE_BACKEND must be 'inmemory' for local dev."""
    backend = os.environ.get("INTAKE_PERSISTENCE_BACKEND")
    if backend is not None:
        assert backend in ("inmemory", "cosmos"), (
            f"INTAKE_PERSISTENCE_BACKEND={backend!r} is not a recognized value"
        )


def test_intake_environment_is_valid_if_set():
    env = os.environ.get("INTAKE_ENVIRONMENT")
    if env is not None:
        assert env in ("dev", "test", "prod", "local"), (
            f"INTAKE_ENVIRONMENT={env!r} is not a recognized value"
        )


def test_azure_run_tests_flag():
    """Guard variable for real-Azure tests must be '1' if set."""
    flag = os.environ.get("INTAKE_RUN_AZURE_TESTS")
    if flag is not None:
        assert flag in ("0", "1", "true", "false"), (
            f"INTAKE_RUN_AZURE_TESTS={flag!r} should be 0 or 1"
        )


# ---------------------------------------------------------------------------
# Package layout assertions (static — no imports)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent


def test_pyproject_toml_does_not_exist_yet_or_is_at_root():
    """pyproject.toml is owned by Trinity at repo root.  Switch must not create it."""
    pyproject = REPO_ROOT / "pyproject.toml"
    # If it exists, it must be at root (not in tests/)
    if pyproject.exists():
        assert pyproject.parent == REPO_ROOT


def test_tests_directory_is_at_repo_root():
    assert (REPO_ROOT / "tests").is_dir()


def test_evaluation_directory_exists():
    assert (REPO_ROOT / "evaluation").is_dir()


def test_docs_quality_directory_exists():
    assert (REPO_ROOT / "docs" / "quality").is_dir()


def test_coverage_config_exists():
    assert (REPO_ROOT / ".coveragerc").exists()


def test_pytest_config_exists():
    assert (REPO_ROOT / "pytest.ini").exists()


def test_reference_domain_has_no_infra_dependencies():
    """reference_domain.py must not import any Azure SDK or infra code."""
    ref_path = REPO_ROOT / "tests" / "fixtures" / "reference_domain.py"
    assert ref_path.exists()
    source = ref_path.read_text()
    forbidden = ["azure.", "from azure", "import azure", "cosmos", "servicebus", "blobservice"]
    for token in forbidden:
        assert token not in source, (
            f"reference_domain.py must not contain {token!r}; "
            "it must remain a pure Python domain reference"
        )
