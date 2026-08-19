"""Strict Microsoft Entra bearer-token verification for the MCP resource server."""
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken

from intake_agent.config import IntakeSettings


class EntraTokenVerifier:
    """Validate delegated v2 access tokens and retain only verified claims."""

    def __init__(self, settings: IntakeSettings) -> None:
        self._tenant_id = settings.mcp_tenant_id.strip()
        self._audience = settings.mcp_audience.strip()
        self._scope = settings.mcp_required_scope.strip()
        self._issuer = settings.mcp_issuer.strip() or (
            f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"
        )
        self._jwk_client = PyJWKClient(
            f"https://login.microsoftonline.com/{self._tenant_id}/discovery/v2.0/keys",
            cache_keys=True,
            lifespan=3600,
            timeout=settings.mcp_jwks_timeout_seconds,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = await asyncio.to_thread(
                self._jwk_client.get_signing_key_from_jwt,
                token,
            )
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=0,
                options={
                    "require": ["exp", "iat", "iss", "aud", "tid", "oid", "scp"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
            return self._access_token(token, claims)
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return None

    def _access_token(self, token: str, claims: dict[str, Any]) -> AccessToken | None:
        tenant_id = claims.get("tid")
        object_id = claims.get("oid")
        scope_claim = claims.get("scp")
        if (
            not isinstance(tenant_id, str)
            or not secrets.compare_digest(tenant_id, self._tenant_id)
            or not isinstance(object_id, str)
            or not object_id
            or not isinstance(scope_claim, str)
        ):
            return None

        scopes = scope_claim.split()
        if self._scope not in scopes:
            return None
        expires_at = claims.get("exp")
        if not isinstance(expires_at, int) or expires_at <= int(time.time()):
            return None

        client_id = claims.get("azp") or claims.get("appid") or "delegated-client"
        if not isinstance(client_id, str):
            return None
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=expires_at,
            resource=self._audience,
            subject=object_id,
            claims={
                "tid": tenant_id,
                "oid": object_id,
                "scp": scope_claim,
            },
        )


class LocalTokenVerifier:
    """Fixed bearer verifier available only when configuration is explicitly local."""

    def __init__(self, settings: IntakeSettings) -> None:
        self._token = settings.mcp_local_dev_token
        self._scope = settings.mcp_required_scope

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self._token):
            return None
        return AccessToken(
            token=token,
            client_id="local-client",
            scopes=[self._scope],
            expires_at=int(time.time()) + 3600,
            resource="http://127.0.0.1",
            subject="local-user",
            claims={
                "tid": "local-tenant",
                "oid": "local-user",
                "scp": self._scope,
            },
        )
