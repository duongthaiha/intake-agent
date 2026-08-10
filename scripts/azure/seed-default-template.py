"""Idempotently seed the production intake template in private Cosmos DB."""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from azure.cosmos import exceptions
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

TEMPLATE_ID = "general-intake-v1"
VERSION = "1.0.0"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _template_document() -> dict[str, object]:
    return {
        "id": f"version:{VERSION}",
        "docType": "templateVersion",
        "templateId": TEMPLATE_ID,
        "version": VERSION,
        "displayName": "General Intake Form",
        "fields": [
            {
                "fieldPath": "project.name",
                "label": "Project Name",
                "fieldType": "string",
                "required": True,
                "description": "Short name for the initiative or project",
            },
            {
                "fieldPath": "project.description",
                "label": "Project Description",
                "fieldType": "string",
                "required": True,
                "description": "Brief description of what is needed and why",
            },
            {
                "fieldPath": "requester.business_unit",
                "label": "Business Unit",
                "fieldType": "string",
                "required": True,
                "description": "The business unit sponsoring this request",
            },
            {
                "fieldPath": "budget.amount",
                "label": "Budget (USD)",
                "fieldType": "number",
                "required": False,
                "description": "Estimated budget in USD",
            },
            {
                "fieldPath": "timeline.target_date",
                "label": "Target Completion Date",
                "fieldType": "string",
                "required": False,
                "description": "Desired completion date (YYYY-MM-DD)",
            },
            {
                "fieldPath": "priority",
                "label": "Priority",
                "fieldType": "enum",
                "required": True,
                "enumValues": ["low", "medium", "high", "critical"],
                "description": "Business priority of the request",
            },
        ],
        "qualityThreshold": 0.7,
        "isActive": True,
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


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
            if (
                existing.get("docType") != "templateVersion"
                or existing.get("templateId") != TEMPLATE_ID
                or existing.get("version") != VERSION
            ):
                raise RuntimeError("Existing template document does not match contract")
            print(f"template {TEMPLATE_ID}:{VERSION} already exists")
    finally:
        await client.close()
        await credential.close()


if __name__ == "__main__":
    asyncio.run(main())
