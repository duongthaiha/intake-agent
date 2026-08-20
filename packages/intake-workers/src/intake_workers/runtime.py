"""Azure Functions composition root for asynchronous worker services."""

from __future__ import annotations

import os
from functools import lru_cache
from hashlib import sha256

from intake_domain import default_template
from intake_persistence.composition import AzurePersistenceSettings

from intake_workers.downstream_stub import (
    ContractTestDownstreamStub,
    ContractTestIntegrationPort,
)
from intake_workers.hosts import WorkerHosts, WorkerSettings, build_worker_hosts


class StubNotificationPort:
    """Deterministic notification adapter until the governed Teams adapter is enabled."""

    def send(
        self,
        *,
        request_id: str,
        recipient_id: str,
        event_type: str,
        deep_link: str,
        idempotency_key: str,
    ) -> str:
        value = "|".join(
            (request_id, recipient_id, event_type, deep_link, idempotency_key)
        )
        return f"stub-notification:{sha256(value.encode()).hexdigest()[:24]}"


class StubRetentionPort:
    """Deterministic retention adapter for the MVP downstream boundary."""

    def apply(
        self,
        *,
        request_id: str,
        legal_hold: bool,
        idempotency_key: str,
    ) -> str:
        del request_id, idempotency_key
        return "held" if legal_hold else "deleted"


@lru_cache(maxsize=1)
def worker_hosts_from_environment() -> WorkerHosts:
    token = "contract-test-downstream"
    persistence = AzurePersistenceSettings(
        cosmos_endpoint=_required("COSMOS_ENDPOINT"),
        cosmos_database=_required("COSMOS_DATABASE"),
        service_bus_namespace=_required("SERVICE_BUS_NAMESPACE"),
        service_bus_queue=_required("SERVICE_BUS_TOPIC"),
        blob_endpoint=_required("STORAGE_BLOB_ENDPOINT"),
        evidence_container=os.environ.get("EVIDENCE_CONTAINER", "evaluation-evidence"),
        managed_identity_client_id=_required("AZURE_CLIENT_ID"),
        service_bus_uses_topic=True,
    )
    settings = WorkerSettings(
        persistence=persistence,
        tenant_id=_required("ENTRA_TENANT_ID"),
        default_reviewer_id=_required("DEFAULT_REVIEWER_ID"),
        integration_target=os.environ.get("INTEGRATION_TARGET", "contract-test-stub"),
        notification_actor_id="notification-worker",
        integration_actor_id="integration-worker",
        completion_actor_id="completion-worker",
        retention_actor_id="retention-worker",
    )
    downstream = ContractTestDownstreamStub(token)
    return build_worker_hosts(
        settings,
        {"software-request": default_template()},
        notifications=StubNotificationPort(),
        integration=ContractTestIntegrationPort(downstream, token),
        retention=StubRetentionPort(),
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value
