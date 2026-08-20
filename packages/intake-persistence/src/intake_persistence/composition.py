"""Azure SDK composition root for persistence adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient
from azure.storage.blob import BlobServiceClient

from intake_persistence.blob import BlobContainer as BlobContainerPort
from intake_persistence.blob import BlobEvaluationEvidenceStore
from intake_persistence.cosmos import (
    CosmosConsumerDeduplicationStore,
    CosmosContainer,
    CosmosOutboxRepository,
    CosmosRequestStore,
)
from intake_persistence.servicebus import ServiceBusClient as ServiceBusClientPort
from intake_persistence.servicebus import ServiceBusOutboxDispatcher


@dataclass(frozen=True, slots=True)
class AzurePersistenceSettings:
    cosmos_endpoint: str
    cosmos_database: str
    service_bus_namespace: str
    service_bus_queue: str
    blob_endpoint: str
    evidence_container: str
    requests_container: str = "requests"
    idempotency_container: str = "idempotency"
    managed_identity_client_id: str | None = None


@dataclass(slots=True)
class AzurePersistenceRuntime:
    credential: DefaultAzureCredential
    cosmos_client: CosmosClient
    blob_service_client: BlobServiceClient
    request_store: CosmosRequestStore
    outbox: CosmosOutboxRepository
    deduplication: CosmosConsumerDeduplicationStore
    dispatcher: ServiceBusOutboxDispatcher
    evidence: BlobEvaluationEvidenceStore
    service_bus_client: ServiceBusClient

    def close(self) -> None:
        self.service_bus_client.close()
        self.blob_service_client.close()
        self.cosmos_client.close()
        self.credential.close()


def build_azure_persistence(
    settings: AzurePersistenceSettings,
) -> AzurePersistenceRuntime:
    """Create Azure clients with one workload credential at the process root."""
    credential = DefaultAzureCredential(
        managed_identity_client_id=settings.managed_identity_client_id
    )
    cosmos = CosmosClient(settings.cosmos_endpoint, credential=credential)
    database = cosmos.get_database_client(settings.cosmos_database)
    requests = database.get_container_client(settings.requests_container)
    idempotency = database.get_container_client(settings.idempotency_container)
    requests_port = cast(CosmosContainer, requests)
    idempotency_port = cast(CosmosContainer, idempotency)
    request_store = CosmosRequestStore(requests_port, idempotency_port)
    outbox = CosmosOutboxRepository(requests_port)
    deduplication = CosmosConsumerDeduplicationStore(idempotency_port)
    service_bus_client = ServiceBusClient(
        fully_qualified_namespace=settings.service_bus_namespace,
        credential=credential,
    )
    dispatcher = ServiceBusOutboxDispatcher(
        outbox,
        cast(ServiceBusClientPort, service_bus_client),
        settings.service_bus_queue,
    )
    blob_service = BlobServiceClient(
        account_url=settings.blob_endpoint,
        credential=credential,
    )
    evidence = BlobEvaluationEvidenceStore(
        cast(
            BlobContainerPort,
            blob_service.get_container_client(settings.evidence_container),
        )
    )
    return AzurePersistenceRuntime(
        credential=credential,
        cosmos_client=cosmos,
        blob_service_client=blob_service,
        request_store=request_store,
        outbox=outbox,
        deduplication=deduplication,
        dispatcher=dispatcher,
        evidence=evidence,
        service_bus_client=service_bus_client,
    )
