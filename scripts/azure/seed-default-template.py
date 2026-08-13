"""Idempotently seed the production intake template in private Cosmos DB."""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from azure.cosmos import exceptions
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

from intake_domain.template_schema import load_packaged_json_schema, template_from_json_schema

TEMPLATE_ID = "general-intake-v1"
VERSION = "1.1.0"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _template_document() -> dict[str, object]:
    schema = load_packaged_json_schema(TEMPLATE_ID)
    template = template_from_json_schema(schema)
    if template.version != VERSION:
        raise RuntimeError(
            f"Packaged template version {template.version!r} does not match seed version {VERSION!r}"
        )
    return {
        "id": f"version:{VERSION}",
        "docType": "templateVersion",
        "templateId": template.template_id,
        "version": template.version,
        "displayName": template.display_name,
        "jsonSchema": schema,
        "qualityThreshold": template.quality_threshold,
        "isActive": template.is_active,
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _matches_canonical_template(document: dict[str, object]) -> bool:
    expected = _template_document()
    keys = (
        "id",
        "docType",
        "templateId",
        "version",
        "displayName",
        "jsonSchema",
        "qualityThreshold",
        "isActive",
    )
    return all(document.get(key) == expected[key] for key in keys)


async def main() -> None:
    endpoint = _required("INTAKE_COSMOS_ENDPOINT")
    database_name = os.getenv("INTAKE_COSMOS_DATABASE", "intake").strip()
    container_name = os.getenv(
        "INTAKE_COSMOS_TEMPLATES_CONTAINER", "templates"
    ).strip()
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()

    credential = DefaultAzureCredential(
        managed_identity_client_id=client_id or None
    )
    client = CosmosClient(endpoint, credential=credential)
    try:
        container = client.get_database_client(database_name).get_container_client(
            container_name
        )
        try:
            existing = await container.read_item(
                item=f"version:{VERSION}",
                partition_key=TEMPLATE_ID,
            )
        except exceptions.CosmosResourceNotFoundError:
            await container.create_item(_template_document())
            print(f"created template {TEMPLATE_ID}:{VERSION}")
        else:
            if not _matches_canonical_template(existing):
                raise RuntimeError(
                    "Existing template document conflicts with the canonical schema"
                )
            print(f"template {TEMPLATE_ID}:{VERSION} already exists")
    finally:
        await client.close()
        await credential.close()


if __name__ == "__main__":
    asyncio.run(main())
