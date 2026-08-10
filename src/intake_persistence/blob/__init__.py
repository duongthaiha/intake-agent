"""Azure Blob artifact persistence using managed identity."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, NoReturn
from urllib.parse import quote, unquote, urlparse

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

from intake_domain.errors import ConflictError, NotFoundError, PermanentError, TransientError
from intake_domain.repositories import ArtifactMetadata, ArtifactStore

_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class BlobArtifactStore(ArtifactStore):
    """Versioned artifact store with create-only, checksum-idempotent writes."""

    def __init__(
        self,
        endpoint: str,
        container: str,
        *,
        managed_identity_client_id: str = "",
        client: Any | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._container = container
        if client is None:
            credential = DefaultAzureCredential(
                managed_identity_client_id=managed_identity_client_id or None
            )
            client = BlobServiceClient(account_url=endpoint, credential=credential)
        self._client = client

    async def store_artifact(
        self,
        request_id: str,
        revision: int,
        content: bytes,
        metadata: ArtifactMetadata,
    ) -> str:
        if revision < 1:
            raise PermanentError("Artifact revision must be positive", revision=revision)
        if metadata.request_id != request_id or metadata.revision != revision:
            raise PermanentError(
                "Artifact metadata does not match the storage key",
                request_id=request_id,
                revision=revision,
            )
        filename = _safe_filename(metadata.filename)
        blob_name = f"{quote(request_id, safe='')}/{revision}/{quote(filename, safe='._-')}"
        checksum = hashlib.sha256(content).hexdigest()
        blob = self._client.get_blob_client(
            container=self._container,
            blob=blob_name,
        )
        blob_metadata = {
            "request_id": request_id,
            "revision": str(revision),
            "artifact_type": metadata.artifact_type,
            "agent_version": metadata.agent_version,
            "sha256": checksum,
            "schema_version": "1.0",
        }
        try:
            await blob.upload_blob(
                content,
                overwrite=False,
                metadata=blob_metadata,
                content_settings=ContentSettings(content_type=metadata.content_type),
            )
        except ResourceExistsError:
            properties = await self._get_properties(blob, blob_name)
            existing_checksum = str(properties.metadata.get("sha256", ""))
            if existing_checksum == checksum:
                return str(blob.url)
            raise ConflictError(
                "Artifact already exists with different content",
                artifact_id=str(blob.url),
                current_etag=str(properties.etag or ""),
            ) from None
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise TransientError("Blob upload failed", blob_name=blob_name) from exc
        except HttpResponseError as exc:
            _raise_blob_error(exc, "upload artifact", blob_name)
        return str(blob.url)

    async def get_artifact_url(
        self,
        artifact_id: str,
        expiry_minutes: int = 15,
    ) -> str:
        if not 1 <= expiry_minutes <= 60:
            raise PermanentError(
                "Artifact URL expiry must be between 1 and 60 minutes",
                expiry_minutes=expiry_minutes,
            )
        blob_name = self._blob_name_from_artifact_id(artifact_id)
        blob = self._client.get_blob_client(
            container=self._container,
            blob=blob_name,
        )
        await self._get_properties(blob, blob_name)

        now = datetime.now(UTC)
        expiry = now + timedelta(minutes=expiry_minutes)
        try:
            delegation_key = await self._client.get_user_delegation_key(
                key_start_time=now - timedelta(minutes=5),
                key_expiry_time=expiry,
            )
            sas = generate_blob_sas(
                account_name=str(self._client.account_name),
                container_name=self._container,
                blob_name=blob_name,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(read=True),
                start=now - timedelta(minutes=5),
                expiry=expiry,
                protocol="https",
            )
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise TransientError("Blob delegated access generation failed") from exc
        except HttpResponseError as exc:
            _raise_blob_error(exc, "generate delegated artifact access", blob_name)
        return f"{blob.url}?{sas}"

    async def _get_properties(self, blob: Any, blob_name: str) -> Any:
        try:
            return await blob.get_blob_properties()
        except ResourceNotFoundError as exc:
            raise NotFoundError(
                "Artifact not found",
                artifact_id=f"{self._endpoint}/{self._container}/{blob_name}",
            ) from exc
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise TransientError("Blob properties read failed", blob_name=blob_name) from exc
        except HttpResponseError as exc:
            _raise_blob_error(exc, "read artifact properties", blob_name)

    def _blob_name_from_artifact_id(self, artifact_id: str) -> str:
        parsed_artifact = urlparse(artifact_id)
        parsed_endpoint = urlparse(self._endpoint)
        if (
            parsed_artifact.scheme != "https"
            or parsed_artifact.netloc.lower() != parsed_endpoint.netloc.lower()
        ):
            raise PermanentError("Artifact identifier is outside the configured storage account")
        path = unquote(parsed_artifact.path).lstrip("/")
        prefix = f"{self._container}/"
        if not path.startswith(prefix):
            raise PermanentError("Artifact identifier is outside the configured container")
        blob_name = path[len(prefix):]
        if not blob_name:
            raise PermanentError("Artifact identifier does not include a blob name")
        return blob_name


def _safe_filename(filename: str) -> str:
    path = PurePosixPath(filename.replace("\\", "/"))
    if path.name != filename or path.name in {"", ".", ".."}:
        raise PermanentError("Artifact filename must be a safe basename", filename=filename)
    return path.name


def _raise_blob_error(exc: HttpResponseError, operation: str, blob_name: str) -> NoReturn:
    status_code = int(getattr(exc, "status_code", 0) or 0)
    context = {
        "operation": operation,
        "blob_name": blob_name,
        "status_code": status_code,
    }
    if status_code in _TRANSIENT_STATUS_CODES:
        raise TransientError(f"Blob Storage failed to {operation}", **context) from exc
    raise PermanentError(f"Blob Storage failed to {operation}", **context) from exc


__all__ = ["BlobArtifactStore"]
