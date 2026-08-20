from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from intake_application import IntakeService
from intake_domain import ActorRole, AgentKind, Provenance
from intake_mcp.auth import (
    DelegatedJWTSettings,
    DelegatedJWTVerifier,
    actor_from_access_token,
)
from intake_mcp.production import (
    ProductionMCPSettings,
    create_requester_server,
    create_reviewer_server,
)
from intake_mcp.telemetry import REDACTED, log_telemetry, redacted_telemetry
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

ISSUER = "https://login.example.test/tenant/v2.0"
TENANT = "00000000-0000-0000-0000-000000000001"
AUDIENCE = "api://intake"
CLIENT = "00000000-0000-0000-0000-000000000002"
SCOPE = "intake.delegated"


class StaticJwksClient:
    def __init__(self, key: object) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _: str) -> object:
        return self.key


class StaticTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(
            token=token,
            client_id=CLIENT,
            scopes=[SCOPE],
            subject="user-oid",
            claims={"iss": ISSUER, "tid": TENANT, "oid": "user-oid"},
        )


@pytest.fixture
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwt_settings() -> DelegatedJWTSettings:
    return DelegatedJWTSettings(
        issuer=ISSUER,
        tenant_id=TENANT,
        audience=AUDIENCE,
        authorized_client_ids=frozenset({CLIENT}),
        required_scope=SCOPE,
        jwks_url="https://login.example.test/keys",
    )


def make_token(private_key: object, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "tid": TENANT,
        "aud": AUDIENCE,
        "azp": CLIENT,
        "oid": "user-oid",
        "scp": f"openid {SCOPE}",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.mark.asyncio
async def test_delegated_verifier_validates_signature_and_all_security_claims(
    private_key: rsa.RSAPrivateKey,
    jwt_settings: DelegatedJWTSettings,
) -> None:
    verifier = DelegatedJWTVerifier(
        jwt_settings, jwks_client=StaticJwksClient(private_key.public_key())
    )
    valid = await verifier.verify_token(make_token(private_key))
    assert valid is not None
    assert valid.client_id == CLIENT
    assert valid.subject == "user-oid"
    assert valid.claims == {"iss": ISSUER, "tid": TENANT, "oid": "user-oid"}
    appid_token = make_token(private_key, azp=None, appid=CLIENT)
    assert await verifier.verify_token(appid_token) is not None

    invalid_overrides = (
        {"iss": f"{ISSUER}/"},
        {"tid": "other-tenant"},
        {"aud": f"{AUDIENCE}/other"},
        {"azp": "unapproved-client"},
        {"scp": "openid profile"},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
    )
    for overrides in invalid_overrides:
        assert await verifier.verify_token(make_token(private_key, **overrides)) is None

    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert await verifier.verify_token(make_token(attacker_key)) is None


def test_actor_uses_only_verified_identity_and_server_configuration(
    private_key: rsa.RSAPrivateKey,
    jwt_settings: DelegatedJWTSettings,
) -> None:
    provenance = Provenance(
        agent_kind=AgentKind.HOSTED,
        agent_version="server",
        instructions_version="server",
        model_version="server",
        toolbox_version="server",
        mcp_contract_version="server",
        policy_version="server",
    )
    token = jwt.decode(
        make_token(private_key),
        private_key.public_key(),
        algorithms=["RS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
    )
    access_token = AccessToken(
        token="not-used-as-identity",
        client_id=CLIENT,
        scopes=[SCOPE],
        subject="user-oid",
        claims={"tid": token["tid"], "oid": token["oid"], "role": "administrator"},
    )
    actor = actor_from_access_token(
        access_token,
        tenant_id=TENANT,
        role=ActorRole.REQUESTER,
        provenance=provenance,
        correlation_id_factory=lambda: "server-correlation",
    )
    assert actor.tenant_id == TENANT
    assert actor.actor_id == "user-oid"
    assert actor.roles == frozenset({ActorRole.REQUESTER})
    assert actor.provenance is provenance
    assert actor.correlation_id == "server-correlation"


@pytest.mark.asyncio
async def test_production_factories_expose_separate_surfaces_and_http_policy(
    jwt_settings: DelegatedJWTSettings,
) -> None:
    settings = ProductionMCPSettings(
        jwt=jwt_settings,
        resource_server_url="https://requester.example.test/mcp",
        max_request_body_size=8192,
    )
    requester = create_requester_server(
        cast(IntakeService, object()),
        settings,
        token_verifier=StaticTokenVerifier(),
    )
    reviewer = create_reviewer_server(
        cast(IntakeService, object()),
        settings,
        token_verifier=StaticTokenVerifier(),
    )
    assert {tool.name for tool in await requester.list_tools()} == {
        "get_intake_context",
        "update_intake_field",
        "submit_intake_for_review",
        "list_my_intake_requests",
    }
    assert {tool.name for tool in await reviewer.list_tools()} == {
        "list_assigned_reviews",
        "get_review_context",
        "add_review_comment",
        "request_intake_changes",
        "decide_intake_review",
    }
    assert requester.max_request_body_size == 8192
    assert requester.settings.auth.required_scopes == [SCOPE]
    with TestClient(requester.streamable_http_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}
        assert (
            client.post(
                "/mcp",
                content=b"x" * 8193,
                headers={"Authorization": "Bearer test-token"},
            ).status_code
            == 413
        )

    unavailable = create_reviewer_server(
        cast(IntakeService, object()),
        settings,
        token_verifier=StaticTokenVerifier(),
        readiness_check=lambda: False,
    )
    with TestClient(unavailable.streamable_http_app()) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}


def test_telemetry_redacts_bearers_and_all_field_content(caplog: pytest.LogCaptureFixture) -> None:
    attributes = {
        "tool_name": "update_intake_field",
        "status_code": 200,
        "authorization": "Bearer super-secret",
        "field_value": "private request content",
        "comment": "private review content",
    }
    safe = redacted_telemetry(attributes)
    assert safe["tool_name"] == "update_intake_field"
    assert safe["authorization"] == REDACTED
    assert safe["field_value"] == REDACTED
    assert safe["comment"] == REDACTED

    with caplog.at_level(logging.INFO):
        log_telemetry(logging.getLogger("test"), "tool.complete", attributes)
        log_telemetry(
            logging.getLogger("test"), "Bearer event-secret", {"unknown": "field content"}
        )
    assert "super-secret" not in caplog.text
    assert "event-secret" not in caplog.text
    assert "private request content" not in caplog.text
    assert "private review content" not in caplog.text
    assert "field content" not in caplog.text
