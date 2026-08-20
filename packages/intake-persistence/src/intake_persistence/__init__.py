"""Persistence adapters for the Intake Agent."""

from intake_persistence.azure_errors import (
    AzureAdapterError,
    MessageContractError,
    PermanentAzureError,
    PermanentMessageError,
    RetryableMessageError,
    TransientAzureError,
)
from intake_persistence.blob import BlobEvaluationEvidenceStore, EvaluationEvidence
from intake_persistence.cosmos import (
    ASYNC_IDEMPOTENCY_TTL_SECONDS,
    INTERACTIVE_IDEMPOTENCY_TTL_SECONDS,
    CosmosConsumerDeduplicationStore,
    CosmosOutboxRepository,
    CosmosRequestStore,
)
from intake_persistence.memory import InMemoryConversationHistory, InMemoryRequestStore
from intake_persistence.servicebus import (
    ConsumerPolicy,
    ServiceBusConsumer,
    ServiceBusDeadLetterReplayer,
    ServiceBusOutboxDispatcher,
)

__all__ = [
    "ASYNC_IDEMPOTENCY_TTL_SECONDS",
    "INTERACTIVE_IDEMPOTENCY_TTL_SECONDS",
    "AzureAdapterError",
    "BlobEvaluationEvidenceStore",
    "ConsumerPolicy",
    "CosmosConsumerDeduplicationStore",
    "CosmosOutboxRepository",
    "CosmosRequestStore",
    "EvaluationEvidence",
    "InMemoryConversationHistory",
    "InMemoryRequestStore",
    "MessageContractError",
    "PermanentAzureError",
    "PermanentMessageError",
    "RetryableMessageError",
    "ServiceBusConsumer",
    "ServiceBusDeadLetterReplayer",
    "ServiceBusOutboxDispatcher",
    "TransientAzureError",
]
