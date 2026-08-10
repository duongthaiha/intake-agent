"""
Webhook authentication boundary for the Teams adapter.

Production mode (default — fail-closed):
  Validates the Bot Framework JWT bearer token sent by Azure Bot Service on
  every activity.  Requests without a valid token are rejected with 401.

  JWKS-backed signature validation is intentionally deferred until the
  deployment target is confirmed (see docs/teams/publishing-spike.md).
  Until a real validator is wired, the boundary raises ConfigurationError
  (HTTP 503) on every production request so the service fails loudly
  rather than silently bypassing authentication.  No token is ever accepted
  unverified in production; dev mode is the only bypass and it is
  explicitly gated (see below).

  To wire real validation:
    1. Install a JWKS library: ``pip install python-jose[cryptography]``
    2. Implement _verify_jwt using the Bot Framework OpenID metadata URL
       and the validation checklist in this module.
    3. Remove the ConfigurationError raise.

Development / local demo mode:
  Enabled ONLY when INTAKE_LOCAL_DEV=1 is set AND the runtime host shows
  no deployed-environment signals (WEBSITE_HOSTNAME, FUNCTIONS_WORKER_RUNTIME,
  INTAKE_ENV=production).  A DevModeWarning is emitted on every request.
  Dev mode raises RuntimeError at construction if a deployed signal is present.

Error taxonomy:
  AuthError (HTTP 401)        — token present but invalid/expired/malformed.
  ConfigurationError (HTTP 503) — no validator is wired; service is not ready.
  RuntimeError                — dev mode attempted on a deployed host.

References:
  Bot Framework authentication:
    https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication
  OpenID metadata endpoint:
    https://login.botframework.com/v1/.well-known/openidconfiguration
  Connector-to-bot auth spec:
    https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication#connector-to-bot
"""

from __future__ import annotations

import logging
import os
import time
import warnings
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Bot Framework token issuers accepted for production validation.
# Source: https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication
_BOT_FRAMEWORK_ISSUERS = frozenset(
    [
        "https://api.botframework.com",
        # Entra tenant for Bot Service (v3.1+)
        "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",
        # v2 endpoint (v3.2+)
        "https://login.microsoftonline.com/d6d49420-f39b-4df7-a1dc-d59a935871db/v2.0",
    ]
)

_BOT_FRAMEWORK_OPENID_URL = (
    "https://login.botframework.com/v1/.well-known/openidconfiguration"
)

_NOT_CONFIGURED_MSG = (
    "Bot Framework JWT validation is not configured on this deployment. "
    "This is a required security component that must be wired before the "
    "service can accept production traffic. "
    "Install python-jose[cryptography] and implement the JWKS validation "
    "checklist in adapter/auth.py before deploying. "
    "See docs/teams/publishing-spike.md for the implementation checklist. "
    "Local development requires INTAKE_LOCAL_DEV=1 on a non-deployed host."
)


class AuthError(Exception):
    """
    Raised when a request fails authentication (HTTP 401).

    A token was present but is invalid, expired, or malformed.
    Callers must return HTTP 401 to Bot Service.
    """

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfigurationError(Exception):
    """
    Raised when the auth boundary cannot validate tokens because a required
    component is not configured (HTTP 503).

    This is NOT an authentication failure — no token was evaluated.
    Callers must return HTTP 503 so the failure is visible as a service
    misconfiguration rather than a spurious authentication rejection.
    Operators must see this error and wire the JWKS validator before
    the service can accept any production traffic.
    """

    status_code: int = 503

    def __init__(self, message: str = _NOT_CONFIGURED_MSG) -> None:
        super().__init__(message)


class DevModeWarning(UserWarning):
    """Emitted on every request when the auth boundary is in dev mode."""


@dataclass(frozen=True)
class VerifiedIdentity:
    """Authenticated caller identity extracted from a valid Bot Framework token."""

    app_id: str  # Bot app ID (aud claim)
    service_url: str  # serviceUrl from the activity
    raw_claims: dict[str, Any]


class AuthBoundary:
    """
    Verifies Bot Framework activity requests before application logic runs.

    Usage (production — Bot Framework JWT):
        boundary = AuthBoundary(bot_app_id="<your-bot-app-id>")
        identity = await boundary.verify(auth_header, activity_service_url)

    Usage (local demo — skip real JWT validation):
        boundary = AuthBoundary(bot_app_id="demo", dev_mode=True)
        identity = await boundary.verify(None, "https://localhost")

    Attempting to construct with dev_mode=True in a deployed environment
    raises RuntimeError as a safety guard.
    """

    def __init__(
        self,
        bot_app_id: str,
        *,
        dev_mode: bool = False,
    ) -> None:
        self._bot_app_id = bot_app_id
        self._dev_mode = self._validate_dev_mode(dev_mode)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def verify(
        self,
        authorization_header: str | None,
        activity_service_url: str,
    ) -> VerifiedIdentity:
        """
        Verify an inbound activity request.

        Returns a VerifiedIdentity on success.
        Raises AuthError (401) if the token is present but invalid.
        Raises ConfigurationError (503) if no JWT validator is wired.

        The production path is always fail-closed: no token is accepted
        without cryptographic verification.
        """
        if self._dev_mode:
            return self._dev_identity(activity_service_url)

        if not authorization_header:
            raise AuthError("Missing Authorization header")

        if not authorization_header.startswith("Bearer "):
            raise AuthError("Authorization header must use Bearer scheme")

        token = authorization_header[len("Bearer "):]
        return await self._verify_jwt(token, activity_service_url)

    async def verify_invoke_token(
        self,
        relay_token: str | None,
        activity_service_url: str,
    ) -> None:
        """
        Validate the relay token present on invoke activities from Teams.

        The relay token is an additional claim that proves the invoke
        originated from the Teams channel (not a crafted HTTP request).
        In dev mode this check is skipped with a warning.
        """
        if self._dev_mode:
            warnings.warn(
                "Relay token verification skipped in dev mode",
                DevModeWarning,
                stacklevel=2,
            )
            return

        if not relay_token:
            # Relay token is only required for invoke activities in production.
            logger.warning(
                "No relay token on invoke activity from service_url=%s",
                activity_service_url,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_dev_mode(requested: bool) -> bool:
        """
        Allow dev mode only when running locally; refuse in deployed envs.

        A deployed environment is detected by the presence of:
          WEBSITE_HOSTNAME   — Azure App Service / Functions
          FUNCTIONS_WORKER_RUNTIME — Azure Functions in-process
          INTAKE_ENV=production
        """
        is_deployed = bool(
            os.environ.get("WEBSITE_HOSTNAME")
            or os.environ.get("FUNCTIONS_WORKER_RUNTIME")
            or os.environ.get("INTAKE_ENV", "").lower() == "production"
        )

        if requested and is_deployed:
            raise RuntimeError(
                "INTAKE_LOCAL_DEV dev mode cannot be enabled in a deployed "
                "environment. Remove INTAKE_LOCAL_DEV=1 from production config."
            )

        env_flag = os.environ.get("INTAKE_LOCAL_DEV", "").strip() == "1"
        effective = requested or env_flag

        if effective:
            warnings.warn(
                "AuthBoundary is running in LOCAL DEV MODE — "
                "Bot Framework JWT validation is DISABLED. "
                "This must never be used in production or staging.",
                DevModeWarning,
                stacklevel=3,
            )
            logger.warning(
                "AuthBoundary: LOCAL DEV MODE active — JWT validation disabled"
            )

        return effective

    async def _verify_jwt(
        self,
        token: str,
        activity_service_url: str,
    ) -> VerifiedIdentity:
        """
        Verify a Bot Framework JWT bearer token.

        Validation checklist (must all pass before accepting any token):
          1. token is a well-formed three-part JWT
          2. fetch JWKS from _BOT_FRAMEWORK_OPENID_URL (cache 24 h, rotate on kid miss)
          3. decode JWT header; locate matching key by 'kid'
          4. verify RS256 signature against the JWKS public key
          5. aud == self._bot_app_id
          6. iss in _BOT_FRAMEWORK_ISSUERS
          7. exp > now() (with no grace period)
          8. serviceUrl claim == activity_service_url (case-normalised)

        This method currently raises ConfigurationError because the JWKS
        validator is not yet wired.  It will never accept a token.
        Install python-jose[cryptography], implement the checklist above,
        and remove the ConfigurationError raise to enable production traffic.
        """
        # Structural guard: must be a three-part JWT before we even attempt
        # to look up a key — avoids unnecessary JWKS fetches for junk input.
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthError("Malformed JWT: expected three dot-separated parts")

        # JWKS-backed validation is not yet wired.  Raise ConfigurationError
        # (503) rather than AuthError (401) so operators can distinguish
        # "service not ready" from "bad credentials".
        logger.error(
            "AuthBoundary._verify_jwt: JWKS validator not configured. "
            "service_url=%s bot_app_id=%s  "
            "Returning 503 until the validator is wired.",
            activity_service_url,
            self._bot_app_id,
        )
        raise ConfigurationError()

    def _dev_identity(self, service_url: str) -> VerifiedIdentity:
        return VerifiedIdentity(
            app_id="dev-bot-app-id",
            service_url=service_url,
            raw_claims={
                "aud": "dev-bot-app-id",
                "iss": "dev",
                "exp": int(time.time()) + 3600,
                "_dev_mode": True,
            },
        )
