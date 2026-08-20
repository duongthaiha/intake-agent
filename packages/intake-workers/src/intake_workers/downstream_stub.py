"""Authenticated and idempotent contract-test downstream implementation."""

from __future__ import annotations

import json
from hashlib import sha256
from secrets import compare_digest
from typing import Any

from intake_agent_contracts import ApprovedRequestHandover, DownstreamAcceptance
from intake_persistence import PermanentMessageError


class ContractTestDownstreamStub:
    """Validates the v1 handover exactly as a downstream HTTP API would."""

    def __init__(self, expected_bearer_token: str) -> None:
        if not expected_bearer_token:
            raise ValueError("A contract-test bearer token is required.")
        self._expected_authorization = f"Bearer {expected_bearer_token}"
        self._accepted: dict[str, tuple[str, DownstreamAcceptance]] = {}

    @property
    def accepted(self) -> tuple[ApprovedRequestHandover, ...]:
        return tuple(
            ApprovedRequestHandover.model_validate_json(fingerprint_payload)
            for fingerprint_payload, _ in self._accepted.values()
        )

    def accept(
        self,
        body: dict[str, Any],
        *,
        idempotency_key: str,
        authorization: str,
    ) -> DownstreamAcceptance:
        if not compare_digest(authorization, self._expected_authorization):
            raise PermanentMessageError("Downstream authentication failed.")
        if not idempotency_key or len(idempotency_key) > 200:
            raise PermanentMessageError("A bounded downstream idempotency key is required.")
        payload = ApprovedRequestHandover.model_validate(body)
        canonical = payload.model_dump_json(by_alias=True)
        fingerprint = sha256(canonical.encode()).hexdigest()
        existing = self._accepted.get(idempotency_key)
        if existing is not None:
            existing_payload, acceptance = existing
            if sha256(existing_payload.encode()).hexdigest() != fingerprint:
                raise PermanentMessageError(
                    "The downstream idempotency key was reused with different content."
                )
            return acceptance.model_copy(update={"duplicate": True})
        acceptance = DownstreamAcceptance(
            accepted=True,
            duplicate=False,
            downstreamId=f"contract-stub:{payload.request_id}:{payload.approved_revision}",
        )
        self._accepted[idempotency_key] = (canonical, acceptance)
        return acceptance


class ContractTestIntegrationPort:
    """Integration port adapter that authenticates to the contract-test stub."""

    def __init__(
        self,
        stub: ContractTestDownstreamStub,
        bearer_token: str,
    ) -> None:
        self._stub = stub
        self._authorization = f"Bearer {bearer_token}"

    def deliver(
        self,
        payload: ApprovedRequestHandover,
        *,
        idempotency_key: str,
    ) -> DownstreamAcceptance:
        body = json.loads(payload.model_dump_json(by_alias=True))
        if not isinstance(body, dict):
            raise PermanentMessageError("The handover payload is not a JSON object.")
        return self._stub.accept(
            body,
            idempotency_key=idempotency_key,
            authorization=self._authorization,
        )
