"""Stable failure categories exposed by Azure adapter boundaries."""


class AzureAdapterError(RuntimeError):
    """Base error for failures translated at an Azure SDK boundary."""

    retryable = False


class TransientAzureError(AzureAdapterError):
    """A retryable Azure dependency failure."""

    retryable = True


class PermanentAzureError(AzureAdapterError):
    """A non-retryable Azure dependency or contract failure."""


class MessageContractError(PermanentAzureError):
    """A queue message failed the versioned event contract."""


class RetryableMessageError(TransientAzureError):
    """A consumer operation can be retried safely."""


class PermanentMessageError(PermanentAzureError):
    """A consumer operation must be dead-lettered."""
