"""Unit tests for delegated Microsoft Entra validation at the MCP boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from intake_agent.config import IntakeConfigurationError
from intake_mcp.auth import (
    EntraTokenVerifier,
    McpSettings,
    identity_from_access_token,
)

pytestmark = pytest.mark.unit


class _StaticJwkClient:
    def __init__(self, public_key: Any) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        _ = token
        return SimpleNamespace(key=self._public_key)


@pytest.fixture()
def auth_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = McpSettings(
        tenant_id="11111111-1111-1111-1111-111111111111",
        audience="api://prompt-intake-mcp",
        server_url="https://prompt-intake-mcp.internal/mcp",
        required_scope="access_as_user",
        allowed_client_ids="foundry-client",
    )
    verifier = EntraTokenVerifier(
        settings,
        jwk_client=_StaticJwkClient(private_key.public_key()),
    )
    return private_key, settings, verifier


def _token(private_key: Any, settings: McpSettings, **overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "aud": settings.audience,
        "exp": now + timedelta(minutes=15),
        "iat": now,
        "iss": settings.issuer,
        "nbf": now - timedelta(seconds=5),
        "oid": "22222222-2222-2222-2222-222222222222",
        "scp": "access_as_user",
        "sub": "subject-1",
        "tid": settings.tenant_id,
        "azp": "foundry-client",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.mark.asyncio
async def test_valid_delegated_token_returns_filtered_access_token(auth_material):
    private_key, settings, verifier = auth_material

    access = await verifier.verify_token(_token(private_key, settings))

    assert access is not None
    assert access.client_id == "foundry-client"
    assert access.scopes == ["access_as_user"]
    assert access.claims == {
        "iss": settings.issuer,
        "oid": "22222222-2222-2222-2222-222222222222",
        "tid": settings.tenant_id,
    }


@pytest.mark.asyncio
async def test_v2_token_client_id_audience_is_accepted(auth_material):
    private_key, settings, verifier = auth_material
    client_id_audience = settings.audience.removeprefix("api://")

    access = await verifier.verify_token(
        _token(private_key, settings, aud=client_id_audience)
    )

    assert access is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("aud", "api://wrong-api"),
        ("iss", "https://login.microsoftonline.com/wrong/v2.0"),
        ("tid", "33333333-3333-3333-3333-333333333333"),
        ("scp", "other_scope"),
        ("azp", "unapproved-client"),
    ],
)
async def test_invalid_delegated_claims_are_rejected(
    auth_material, claim: str, value: str
):
    private_key, settings, verifier = auth_material

    access = await verifier.verify_token(
        _token(private_key, settings, **{claim: value})
    )

    assert access is None


@pytest.mark.asyncio
async def test_identity_uses_only_verified_access_token_claims(auth_material):
    private_key, settings, verifier = auth_material
    access = await verifier.verify_token(_token(private_key, settings))

    identity = identity_from_access_token(access)

    assert identity.object_id == "22222222-2222-2222-2222-222222222222"
    assert identity.tenant_id == settings.tenant_id


def test_identity_rejects_missing_verified_token():
    with pytest.raises(IntakeConfigurationError, match="verified delegated identity"):
        identity_from_access_token(None)


def test_mcp_settings_fail_closed_without_required_values():
    with pytest.raises(IntakeConfigurationError) as exc_info:
        McpSettings().validate_required()

    message = str(exc_info.value)
    assert "INTAKE_MCP_TENANT_ID" in message
    assert "INTAKE_MCP_AUDIENCE" in message
    assert "INTAKE_MCP_SERVER_URL" in message
