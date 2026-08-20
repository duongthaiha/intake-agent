"""External-effect ports owned by worker services."""

from __future__ import annotations

from typing import Protocol

from intake_agent_contracts import ApprovedRequestHandover, DownstreamAcceptance


class IntegrationPort(Protocol):
    def deliver(
        self,
        payload: ApprovedRequestHandover,
        *,
        idempotency_key: str,
    ) -> DownstreamAcceptance: ...


class NotificationPort(Protocol):
    def send(
        self,
        *,
        request_id: str,
        recipient_id: str,
        event_type: str,
        deep_link: str,
        idempotency_key: str,
    ) -> str: ...


class RetentionPort(Protocol):
    def apply(
        self,
        *,
        request_id: str,
        legal_hold: bool,
        idempotency_key: str,
    ) -> str: ...
