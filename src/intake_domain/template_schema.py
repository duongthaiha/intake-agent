"""Load canonical JSON Schema intake templates into domain entities."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from intake_domain.entities import FieldSchema, TemplateVersion

_PACKAGED_TEMPLATES = {
    "general-intake-v1": "general-intake-v1.schema.json",
}
_UNSUPPORTED_KEYWORDS = frozenset(
    {"$ref", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "dependentSchemas"}
)
_SUPPORTED_LEAF_TYPES = frozenset({"string", "number", "integer", "boolean"})
_ROOT_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "additionalProperties",
        "x-intake",
        "required",
        "properties",
    }
)
_OBJECT_KEYWORDS = frozenset(
    {"title", "description", "type", "additionalProperties", "required", "properties"}
)
_LEAF_KEYWORDS = frozenset(
    {"title", "description", "type", "enum", "format", "default", "x-intake"}
)


class TemplateSchemaError(ValueError):
    """Raised when an intake template is not a supported JSON Schema."""


def load_packaged_json_schema(template_id: str) -> dict[str, Any]:
    """Load a canonical schema bundled with the domain package."""
    filename = _PACKAGED_TEMPLATES.get(template_id)
    if filename is None:
        raise TemplateSchemaError(f"No packaged JSON Schema for template {template_id!r}")

    resource = files("intake_domain.template_schemas").joinpath(filename)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateSchemaError(
            f"Unable to load JSON Schema for template {template_id!r}"
        ) from exc
    if not isinstance(value, dict):
        raise TemplateSchemaError("Template JSON Schema must be an object")
    return value


def load_packaged_template(template_id: str) -> TemplateVersion:
    """Load and adapt a packaged canonical template."""
    schema = load_packaged_json_schema(template_id)
    template = template_from_json_schema(schema)
    if template.template_id != template_id:
        raise TemplateSchemaError(
            f"Template ID mismatch: requested {template_id!r}, "
            f"schema declares {template.template_id!r}"
        )
    return template


def template_from_json_schema(
    schema: dict[str, Any],
    *,
    created_at: datetime | None = None,
) -> TemplateVersion:
    """Validate and flatten a supported intake JSON Schema."""
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise TemplateSchemaError(f"Invalid Draft 2020-12 JSON Schema: {exc.message}") from exc

    _reject_unsupported_keywords(schema)
    _validate_keywords(schema, _ROOT_KEYWORDS, "<root>")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise TemplateSchemaError("Template must declare JSON Schema Draft 2020-12")
    if schema.get("type") != "object":
        raise TemplateSchemaError("Template root must have type 'object'")
    if schema.get("additionalProperties") is not False:
        raise TemplateSchemaError("Template root must set additionalProperties to false")

    metadata = schema.get("x-intake")
    if not isinstance(metadata, dict):
        raise TemplateSchemaError("Template root must define an x-intake object")

    template_id = _required_string(metadata, "templateId")
    version = _required_string(metadata, "version")
    display_name = schema.get("title")
    if not isinstance(display_name, str) or not display_name.strip():
        raise TemplateSchemaError("Template root must define a non-empty title")

    quality_threshold = metadata.get("qualityThreshold", 0.8)
    if (
        isinstance(quality_threshold, bool)
        or not isinstance(quality_threshold, (int, float))
        or not 0 <= float(quality_threshold) <= 1
    ):
        raise TemplateSchemaError("x-intake.qualityThreshold must be between 0 and 1")

    is_active = metadata.get("isActive", True)
    if not isinstance(is_active, bool):
        raise TemplateSchemaError("x-intake.isActive must be a boolean")

    field_schemas: list[FieldSchema] = []
    _flatten_properties(schema, "", True, field_schemas)
    if not field_schemas:
        raise TemplateSchemaError("Template must define at least one leaf field")

    return TemplateVersion(
        template_id=template_id,
        version=version,
        display_name=display_name,
        fields=field_schemas,
        quality_threshold=float(quality_threshold),
        is_active=is_active,
        created_at=created_at or datetime.now(UTC),
    )


def _flatten_properties(
    node: dict[str, Any],
    prefix: str,
    parent_required: bool,
    output: list[FieldSchema],
) -> None:
    allowed_keywords = _ROOT_KEYWORDS if not prefix else _OBJECT_KEYWORDS
    _validate_keywords(node, allowed_keywords, prefix or "<root>")
    if node.get("additionalProperties") is not False:
        raise TemplateSchemaError(
            f"Object {prefix or '<root>'!r} must set additionalProperties to false"
        )
    properties = node.get("properties")
    if not isinstance(properties, dict) or not properties:
        location = prefix or "<root>"
        raise TemplateSchemaError(f"Object {location!r} must define properties")

    required_value = node.get("required", [])
    if not isinstance(required_value, list) or not all(
        isinstance(item, str) for item in required_value
    ):
        raise TemplateSchemaError(f"required at {prefix or '<root>'!r} must be a string array")
    required_names = set(required_value)
    unknown_required = required_names.difference(properties)
    if unknown_required:
        raise TemplateSchemaError(
            f"required at {prefix or '<root>'!r} references unknown properties: "
            f"{sorted(unknown_required)}"
        )

    for name, raw_property in properties.items():
        if not isinstance(name, str) or not name or "." in name:
            raise TemplateSchemaError(f"Invalid property name {name!r}")
        if not isinstance(raw_property, dict):
            raise TemplateSchemaError(f"Property {name!r} must be a schema object")

        field_path = f"{prefix}.{name}" if prefix else name
        is_required = parent_required and name in required_names
        property_type = raw_property.get("type")
        if property_type == "object":
            _flatten_properties(raw_property, field_path, is_required, output)
            continue
        _validate_keywords(raw_property, _LEAF_KEYWORDS, field_path)
        if property_type == "array":
            raise TemplateSchemaError(f"Arrays are not supported at {field_path!r}")
        if not isinstance(property_type, str) or property_type not in _SUPPORTED_LEAF_TYPES:
            raise TemplateSchemaError(
                f"Unsupported type {property_type!r} at {field_path!r}"
            )

        enum_value = raw_property.get("enum", [])
        if not isinstance(enum_value, list) or not all(
            isinstance(item, str) for item in enum_value
        ):
            raise TemplateSchemaError(f"enum at {field_path!r} must be a string array")
        field_type = "enum" if enum_value else (
            "number" if property_type == "integer" else property_type
        )

        title = raw_property.get("title")
        if not isinstance(title, str) or not title.strip():
            raise TemplateSchemaError(f"Leaf field {field_path!r} must define a title")
        description = raw_property.get("description", "")
        if not isinstance(description, str):
            raise TemplateSchemaError(f"description at {field_path!r} must be a string")

        field_metadata = raw_property.get("x-intake", {})
        if not isinstance(field_metadata, dict):
            raise TemplateSchemaError(f"x-intake at {field_path!r} must be an object")
        min_confidence = field_metadata.get("minConfidence", 0.7)
        if (
            isinstance(min_confidence, bool)
            or not isinstance(min_confidence, (int, float))
            or not 0 <= float(min_confidence) <= 1
        ):
            raise TemplateSchemaError(
                f"x-intake.minConfidence at {field_path!r} must be between 0 and 1"
            )

        output.append(
            FieldSchema(
                field_path=field_path,
                label=title,
                field_type=field_type,
                required=is_required,
                enum_values=list(enum_value),
                min_confidence=float(min_confidence),
                description=description,
            )
        )


def _reject_unsupported_keywords(value: Any, path: str = "<root>") -> None:
    if isinstance(value, dict):
        unsupported = _UNSUPPORTED_KEYWORDS.intersection(value)
        if unsupported:
            raise TemplateSchemaError(
                f"Unsupported JSON Schema keyword(s) at {path}: {sorted(unsupported)}"
            )
        for key, child in value.items():
            _reject_unsupported_keywords(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_unsupported_keywords(child, f"{path}[{index}]")


def _validate_keywords(
    value: dict[str, Any],
    allowed: frozenset[str],
    path: str,
) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise TemplateSchemaError(
            f"Unsupported JSON Schema keyword(s) at {path}: {sorted(unknown)}"
        )


def _required_string(value: dict[str, Any], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate.strip():
        raise TemplateSchemaError(f"x-intake.{key} must be a non-empty string")
    return candidate


__all__ = [
    "TemplateSchemaError",
    "load_packaged_json_schema",
    "load_packaged_template",
    "template_from_json_schema",
]
