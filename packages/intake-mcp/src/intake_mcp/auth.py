"""Delegated bearer-token validation for production MCP resource servers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from intake_domain import ActorContext, ActorRole, Provenance
from mcp.server.auth.provider import AccessToken, TokenVerifier


class SigningKeyResolver(Protocol):
    """The subset of ``PyJWKClient`` used by the verifier."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class DelegatedJWTSettings:
    issuer: str
    tenant_id: str
    audience: str
    authorized_client_ids: frozenset[str]
    required_scope: str
    jwks_url: str
    algorithms: tuple[str, ...] = ("RS256",)

    def __post_init__(self) -> None:
        values = (
            self.issuer,
            self.tenant_id,
            self.audience,
            self.required_scope,
            self.jwks_url,
        )
        if any(not value for value in values):
            raise ValueError("delegated JWT settings must not be empty")
        if not self.authorized_client_ids:
            raise ValueError("at least one authorized delegated client is required")
        if not self.algorithms:
            raise ValueError("at least one signing algorithm is required")


class DelegatedJWTVerifier(TokenVerifier):
    """Validate signed delegated JWTs and expose only identity-bearing claims."""

    def __init__(
        self,
        settings: DelegatedJWTSettings,
        *,
        jwks_client: SigningKeyResolver | None = None,
        decoder: Callable[..., dict[str, Any]] = jwt.decode,
    ) -> None:
        self.settings = settings
        self._jwks_client = jwks_client or jwt.PyJWKClient(settings.jwks_url)
        self._decoder = decoder

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        try:
            signing_key = await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)
            key = getattr(signing_key, "key", signing_key)
            claims = self._decoder(
                token,
                key,
                algorithms=list(self.settings.algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                leeway=0,
                options={
                    "require": ["exp", "nbf", "iat", "iss", "aud", "tid", "oid"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
            if claims.get("iss") != self.settings.issuer:
                return None
            if claims.get("tid") != self.settings.tenant_id:
                return None
            if not _has_exact_audience(claims.get("aud"), self.settings.audience):
                return None

            client_id = claims.get("azp") or claims.get("appid")
            if (
                not isinstance(client_id, str)
                or client_id not in self.settings.authorized_client_ids
            ):
                return None
            scopes = _delegated_scopes(claims.get("scp"))
            if self.settings.required_scope not in scopes:
                return None
            oid = claims.get("oid")
            tid = claims.get("tid")
            expires_at = claims.get("exp")
            if (
                not isinstance(oid, str)
                or not oid
                or not isinstance(tid, str)
                or not isinstance(expires_at, int)
            ):
                return None

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=sorted(scopes),
                expires_at=expires_at,
                resource=self.settings.audience,
                subject=oid,
                claims={"iss": self.settings.issuer, "tid": tid, "oid": oid},
            )
        except jwt.PyJWTError:
            # Authentication failures are intentionally indistinguishable and the
            # bearer token is never included in logs or error messages.
            return None


def actor_from_access_token(
    token: AccessToken | None,
    *,
    tenant_id: str,
    role: ActorRole,
    provenance: Provenance,
    correlation_id_factory: Callable[[], str],
) -> ActorContext:
    """Build an immutable actor solely from verified claims and server policy."""

    claims = token.claims if token is not None else None
    claim_tid = claims.get("tid") if claims else None
    claim_oid = claims.get("oid") if claims else None
    if (
        token is None
        or claim_tid != tenant_id
        or not isinstance(claim_oid, str)
        or not claim_oid
        or token.subject != claim_oid
    ):
        raise PermissionError("validated delegated identity is required")
    correlation_id = correlation_id_factory()
    if not correlation_id:
        raise RuntimeError("correlation id factory returned an empty value")
    return ActorContext(
        tenant_id=claim_tid,
        actor_id=claim_oid,
        roles=frozenset({role}),
        provenance=provenance,
        correlation_id=correlation_id,
    )


def _delegated_scopes(value: Any) -> frozenset[str]:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(scope for scope in value.split(" ") if scope)


def _has_exact_audience(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value) == 1 and value[0] == expected
    return False
