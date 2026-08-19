"""Static security contracts for the side-by-side prompt agent deployment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mcp_runtime_is_internal_and_uses_application_bearer_auth():
    bicep = _read("infra/modules/mcp-container-apps.bicep")
    server = _read("src/intake_mcp/server.py")

    assert "internal: true" in bicep
    assert "external: true" in bicep
    assert "allowInsecure: false" in bicep
    assert "containerApps/authConfigs" not in bicep
    assert "INTAKE_MCP_AUDIENCE" in bicep
    assert "INTAKE_MCP_TENANT_ID" in bicep
    assert "INTAKE_MCP_SERVER_URL" in bicep
    assert "minReplicas: 1" in bicep
    assert "secrets:" not in bicep
    assert "EntraTokenVerifier" in server
    assert "token_verifier=verifier" in server


def test_mcp_runtime_has_dedicated_subnet_identity_and_private_dns():
    network = _read("infra/modules/network.bicep")
    identity = _read("infra/modules/identity.bicep")
    dns = _read("infra/modules/mcp-private-dns.bicep")

    assert "snet-intake-mcp" in network
    assert "10.0.6.0/23" in network
    assert "Microsoft.App/environments" in network
    assert "id-intake-mcp-${environmentName}" in identity
    assert "privateDnsZones/A" in dns
    assert "name: '*'" in dns
    assert "virtualNetworkLinks" in dns


def test_mcp_identity_has_narrow_data_and_registry_roles():
    main = _read("infra/main.bicep")
    cosmos = _read("infra/modules/cosmos.bicep")
    storage = _read("infra/modules/storage.bicep")
    service_bus = _read("infra/modules/servicebus.bicep")

    assert "mcpAcrPull" in main
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in main
    assert "mcpCosmosRole" in cosmos
    assert "scope: '${cosmosAccount.id}/dbs/${intakeDatabase.name}'" in cosmos
    assert "mcpArtifactContributor" in storage
    assert "scope: artifactsContainer" in storage
    assert "mcpIdentity" not in service_bus


def test_prompt_deploy_workflow_builds_and_configures_both_surfaces():
    workflow = _read(".github/workflows/deploy.yml")
    for step_name in (
        "Build private prompt intake MCP image",
        "Configure delegated MCP connection",
        "Deploy prompt intake agent",
        "Post-deploy verification",
    ):
        assert f"- name: {step_name}" in workflow
    assert "az acr build" in workflow
    assert "trap restore_acr_public_access EXIT INT TERM" in workflow
    assert "--public-network-enabled false" in workflow
    assert 'DEPLOY_SHA="$(git rev-parse HEAD)"' in workflow
    assert "prompt-intake-mcp@${IMAGE_DIGEST}" in workflow
    assert "INTAKE_MCP_IMAGE: ${{ steps.mcp-image.outputs.image }}" in workflow
    assert "--auth-type user-entra-token" in workflow
    assert "--force" in workflow
    assert "python scripts/foundry/deploy_prompt_agent.py" in workflow
    assert "INTAKE_MCP_APP_CLIENT_ID: ${{ vars.INTAKE_MCP_APP_CLIENT_ID }}" in workflow
    assert "predates the prompt-agent deployment contract" in workflow
    assert "client-secret" not in workflow.lower()


def test_prompt_auth_bootstrap_creates_no_credentials():
    scripts = (
        _read("scripts/azure/bootstrap-prompt-intake-auth.sh")
        + _read("scripts/azure/bootstrap-prompt-intake-auth.ps1")
    ).lower()

    assert "access_as_user" in scripts
    assert "requestedaccesstokenversion" in scripts
    assert "credential reset" not in scripts
    assert "client-secret" not in scripts
    assert "password" not in scripts


def test_docker_context_is_allowlisted_and_excludes_environment_files():
    dockerignore = _read(".dockerignore").splitlines()

    assert dockerignore[0] == "**"
    assert "!pyproject.toml" in dockerignore
    assert "!src/**" in dockerignore
    assert not any(".env" in line for line in dockerignore if line.startswith("!"))


def test_prompt_infrastructure_parameters_are_explicit():
    parameters = json.loads(_read("infra/main.parameters.json"))["parameters"]

    assert parameters["intakeMcpAppClientId"]["value"] == "${INTAKE_MCP_APP_CLIENT_ID}"
    assert parameters["intakeMcpImage"]["value"] == "${INTAKE_MCP_IMAGE}"
