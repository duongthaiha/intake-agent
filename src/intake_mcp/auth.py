"""Microsoft Entra bearer-token validation for the private MCP endpoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from intake_agent.config import IntakeConfigurationError


class _SigningKey(Protocol):
    key: Any


class _JwkClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> _SigningKey: ...


class McpSettings(BaseSettings):
    """Authentication and endpoint settings for the prompt-agent MCP service."""

    model_config = SettingsConfigDict(
        env_prefix="INTAKE_MCP_",
        case_sensitive=False,
        populate_by_name=True,
    )

    tenant_id: str = ""
    audience: str = ""
    server_url: str = ""
    required_scope: str = "access_as_user"
    allowed_client_ids: str = ""

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def jwks_url(self) -> str:
        return (
            f"https://login.microsoftonline.com/{self.tenant_id}"
            "/discovery/v2.0/keys"
        )

    @property
    def allowed_clients(self) -> frozenset[str]:
        return frozenset(
            value.strip()
            for value in self.allowed_client_ids.split(",")
            if value.strip()
        )

    @property
    def accepted_audiences(self) -> tuple[str, ...]:
        values = [self.audience]
        if self.audience.startswith("api://"):
            client_id = self.audience.removeprefix("api://")
            if client_id:
                values.append(client_id)
        return tuple(values)

    def validate_required(self) -> None:
        errors: list[str] = []
        if not self.tenant_id.strip():
            errors.append("INTAKE_MCP_TENANT_ID is required")
        if not self.audience.strip():
            errors.append("INTAKE_MCP_AUDIENCE is required")
        if not self.server_url.strip():
            errors.append("INTAKE_MCP_SERVER_URL is required")
        elif not self.server_url.startswith(("https://", "http://127.0.0.1")):
            errors.append(
                "INTAKE_MCP_SERVER_URL must use HTTPS outside loopback development"
            )
        if not self.required_scope.strip():
            errors.append("INTAKE_MCP_REQUIRED_SCOPE is required")
        if errors:
            raise IntakeConfigurationError("; ".join(errors))

    def resource_url(self) -> AnyHttpUrl:
        self.validate_required()
        return AnyHttpUrl(self.server_url)

    def issuer_url(self) -> AnyHttpUrl:
        self.validate_required()
        return AnyHttpUrl(self.issuer)


@dataclass(frozen=True)
class McpIdentity:
    """Verified same-tenant user identity carried by the delegated access token."""

    object_id: str
    tenant_id: str


class EntraTokenVerifier(TokenVerifier):
    """Validate delegated Entra JWTs and expose only verified identity claims."""

    def __init__(
        self,
        settings: McpSettings,
        *,
        jwk_client: _JwkClient | None = None,
    ) -> None:
        settings.validate_required()
        self._settings = settings
        self._jwk_client: _JwkClient = jwk_client or jwt.PyJWKClient(
            settings.jwks_url,
            cache_keys=True,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(self._decode, token)
        except jwt.PyJWKClientConnectionError as exc:
            raise IntakeConfigurationError(
                "Unable to retrieve Microsoft Entra signing keys"
            ) from exc
        except (jwt.InvalidTokenError, jwt.PyJWKClientError):
            return None

        object_id = str(claims["oid"])
        tenant_id = str(claims["tid"])
        client_id = str(claims.get("azp") or claims.get("appid") or "")
        scopes = str(claims.get("scp") or "").split()
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=self._settings.audience,
            subject=str(claims.get("sub") or object_id),
            claims={
                "iss": claims["iss"],
                "oid": object_id,
                "tid": tenant_id,
            },
        )

    def _decode(self, token: str) -> dict[str, Any]:
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=list(self._settings.accepted_audiences),
            issuer=self._settings.issuer,
            options={
                "require": ["aud", "exp", "iat", "iss", "nbf", "oid", "tid"],
            },
        )

        if claims["tid"] != self._settings.tenant_id:
            raise jwt.InvalidTokenError("Token tenant is not allowed")

        client_id = str(claims.get("azp") or claims.get("appid") or "")
        if self._settings.allowed_clients and client_id not in self._settings.allowed_clients:
            raise jwt.InvalidTokenError("Calling client is not allowed")

        scopes = str(claims.get("scp") or "").split()
        if self._settings.required_scope not in scopes:
            raise jwt.InvalidTokenError("Required delegated scope is missing")
        return claims


def identity_from_access_token(access_token: AccessToken | None) -> McpIdentity:
    """Build an MCP identity only from claims emitted by the token verifier."""
    claims = access_token.claims if access_token is not None else None
    if not claims:
        raise IntakeConfigurationError("A verified delegated identity is required")
    object_id = str(claims.get("oid") or "")
    tenant_id = str(claims.get("tid") or "")
    if not object_id or not tenant_id:
        raise IntakeConfigurationError(
            "Verified delegated identity is missing oid or tid"
        )
    return McpIdentity(object_id=object_id, tenant_id=tenant_id)
