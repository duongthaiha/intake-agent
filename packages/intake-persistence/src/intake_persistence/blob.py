"""Create-only Blob Storage adapter for evaluation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.storage.blob import ContentSettings

from intake_persistence.azure_errors import PermanentAzureError, TransientAzureError

_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class BlobClient(Protocol):
    url: str

    def upload_blob(self, data: bytes, **kwargs: Any) -> Any: ...

    def get_blob_properties(self) -> Any: ...


class BlobContainer(Protocol):
    def get_blob_client(self, blob: str) -> BlobClient: ...


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    dataset_id: str
    dataset_version: str
    run_id: str
    filename: str
    content_type: str
    classification: str
    evaluator_version: str


class BlobEvaluationEvidenceStore:
    """Stores immutable, checksum-idempotent evaluation evidence blobs."""

    def __init__(self, container: BlobContainer) -> None:
        self._container = container

    def store(self, content: bytes, evidence: EvaluationEvidence) -> str:
        if not content:
            raise PermanentAzureError("Evaluation evidence must not be empty.")
        filename = _safe_filename(evidence.filename)
        blob_name = (
            f"{quote(evidence.dataset_id, safe='')}/"
            f"{quote(evidence.dataset_version, safe='._-')}/"
            f"{quote(evidence.run_id, safe='')}/"
            f"{quote(filename, safe='._-')}"
        )
        checksum = sha256(content).hexdigest()
        blob = self._container.get_blob_client(blob_name)
        metadata = {
            "dataset_id": evidence.dataset_id,
            "dataset_version": evidence.dataset_version,
            "run_id": evidence.run_id,
            "classification": evidence.classification,
            "evaluator_version": evidence.evaluator_version,
            "sha256": checksum,
            "schema_version": "1.0",
        }
        try:
            blob.upload_blob(
                content,
                overwrite=False,
                metadata=metadata,
                content_settings=ContentSettings(content_type=evidence.content_type),
            )
        except ResourceExistsError:
            properties = blob.get_blob_properties()
            existing = str(getattr(properties, "metadata", {}).get("sha256", ""))
            if existing == checksum:
                return blob.url
            raise PermanentAzureError(
                "Evaluation evidence already exists with different content."
            ) from None
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise TransientAzureError("Blob evidence upload failed.") from exc
        except HttpResponseError as exc:
            status = int(getattr(exc, "status_code", 0) or 0)
            if status in _TRANSIENT_STATUS_CODES:
                raise TransientAzureError("Blob evidence upload failed.") from exc
            raise PermanentAzureError("Blob evidence upload failed.") from exc
        return blob.url


def _safe_filename(filename: str) -> str:
    path = PurePosixPath(filename.replace("\\", "/"))
    if path.name != filename or path.name in {"", ".", ".."}:
        raise PermanentAzureError("Evidence filename must be a safe basename.")
    return path.name
