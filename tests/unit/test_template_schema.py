"""Canonical intake JSON Schema contract and adaptation tests."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from jsonschema import Draft202012Validator

from intake_agent.config import (
    IntakeConfigurationError,
    IntakeSettings,
    build_repositories,
)
from intake_domain.template_schema import (
    TemplateSchemaError,
    load_packaged_json_schema,
    load_packaged_template,
    template_from_json_schema,
)
from intake_persistence._serialization import template_from_document
from intake_persistence.cosmos import CosmosTemplateRepository

pytestmark = pytest.mark.unit


class _AsyncDocuments:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def __aiter__(self):  # type: ignore[no-untyped-def]
        async def iterate():  # type: ignore[no-untyped-def]
            for document in self._documents:
                yield document

        return iterate()


def test_packaged_schema_is_valid_and_preserves_intake_contract() -> None:
    schema = load_packaged_json_schema("general-intake-v1")
    Draft202012Validator.check_schema(schema)

    template = load_packaged_template("general-intake-v1")
    assert template.version == "1.1.0"
    assert template.display_name == "General Intake Form"
    assert template.quality_threshold == 0.7
    assert [
        (field.field_path, field.field_type, field.required)
        for field in template.fields
    ] == [
        ("project.name", "string", True),
        ("project.description", "string", True),
        ("requester.business_unit", "string", True),
        ("budget.amount", "number", False),
        ("timeline.target_date", "string", False),
        ("priority", "enum", True),
    ]
    priority = next(field for field in template.fields if field.field_path == "priority")
    assert priority.enum_values == ["low", "medium", "high", "critical"]


def test_optional_parent_makes_nested_required_leaf_optional() -> None:
    schema = load_packaged_json_schema("general-intake-v1")
    schema["properties"]["budget"]["required"] = ["amount"]

    template = template_from_json_schema(schema)

    budget = next(field for field in template.fields if field.field_path == "budget.amount")
    assert budget.required is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda schema: schema.update({"$ref": "#/$defs/template"}), "Unsupported"),
        (
            lambda schema: schema["properties"].update(
                {"attachments": {"title": "Attachments", "type": "array"}}
            ),
            "Arrays are not supported",
        ),
        (
            lambda schema: schema["properties"]["project"]["properties"]["name"].pop(
                "title"
            ),
            "must define a title",
        ),
        (
            lambda schema: schema["x-intake"].update({"qualityThreshold": 2}),
            "must be between 0 and 1",
        ),
        (
            lambda schema: schema["properties"]["project"]["properties"]["name"].update(
                {"minLength": 3}
            ),
            "Unsupported JSON Schema keyword",
        ),
        (
            lambda schema: schema["properties"]["project"].update(
                {"additionalProperties": True}
            ),
            "must set additionalProperties to false",
        ),
    ],
)
def test_unsupported_or_invalid_intake_schemas_fail_explicitly(
    mutation: Callable[[dict[str, Any]], Any],
    message: str,
) -> None:
    schema = deepcopy(load_packaged_json_schema("general-intake-v1"))
    mutation(schema)

    with pytest.raises(TemplateSchemaError, match=message):
        template_from_json_schema(schema)


def test_unknown_packaged_template_fails_explicitly() -> None:
    with pytest.raises(TemplateSchemaError, match="No packaged JSON Schema"):
        load_packaged_template("unknown")


def test_local_composition_reports_unknown_template_as_configuration_error() -> None:
    settings = IntakeSettings(template_id="unknown")

    with pytest.raises(IntakeConfigurationError, match="Unable to load intake template"):
        build_repositories(settings)


def test_schema_backed_cosmos_document_is_adapted() -> None:
    schema = load_packaged_json_schema("general-intake-v1")
    created_at = datetime(2026, 8, 13, tzinfo=UTC)
    document = {
        "templateId": "general-intake-v1",
        "version": "1.1.0",
        "displayName": "General Intake Form",
        "jsonSchema": schema,
        "qualityThreshold": 0.7,
        "isActive": True,
        "createdAt": created_at.isoformat().replace("+00:00", "Z"),
    }

    template = template_from_document(document)

    assert template.version == "1.1.0"
    assert template.created_at == created_at
    assert len(template.fields) == 6


def test_schema_backed_cosmos_document_rejects_envelope_mismatch() -> None:
    schema = load_packaged_json_schema("general-intake-v1")
    document = {
        "templateId": "different-template",
        "version": "1.1.0",
        "displayName": "General Intake Form",
        "jsonSchema": schema,
        "qualityThreshold": 0.7,
        "isActive": True,
        "createdAt": "2026-08-13T00:00:00Z",
    }

    with pytest.raises(ValueError, match="templateId does not match"):
        template_from_document(document)
def test_fields_array_template_document_is_rejected() -> None:
    with pytest.raises(ValueError, match="must define a jsonSchema object"):
        template_from_document(
            {
                "templateId": "general-intake-v1",
                "version": "1.0.0",
                "fields": [],
                "createdAt": "2026-08-07T00:00:00Z",
            }
        )


@pytest.mark.asyncio
async def test_cosmos_repository_seeds_packaged_schema_when_none_exists() -> None:
    container = SimpleNamespace(
        query_items=MagicMock(return_value=_AsyncDocuments([])),
        create_item=AsyncMock(),
    )
    repository = CosmosTemplateRepository(
        "",
        "",
        context=SimpleNamespace(templates=container),  # type: ignore[arg-type]
    )

    template = await repository.get_active("general-intake-v1")

    assert template is not None
    assert template.version == "1.1.0"
    seeded_document = container.create_item.await_args.args[0]
    assert seeded_document["jsonSchema"]["x-intake"]["version"] == "1.1.0"
    assert "fields" not in seeded_document


@pytest.mark.asyncio
async def test_cosmos_repository_does_not_seed_unknown_template() -> None:
    container = SimpleNamespace(
        query_items=MagicMock(return_value=_AsyncDocuments([])),
        create_item=AsyncMock(),
    )
    repository = CosmosTemplateRepository(
        "",
        "",
        context=SimpleNamespace(templates=container),  # type: ignore[arg-type]
    )

    assert await repository.get_active("unknown") is None
    container.create_item.assert_not_awaited()
