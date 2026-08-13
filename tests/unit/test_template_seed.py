"""Azure template seed uses the canonical packaged JSON Schema."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit


def _load_seed_module() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "scripts"
        / "azure"
        / "seed-default-template.py"
    )
    spec = importlib.util.spec_from_file_location("seed_default_template", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the template seed module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_document_embeds_canonical_schema_version() -> None:
    module = _load_seed_module()

    document = module._template_document()

    assert document["id"] == "version:1.1.0"
    assert document["version"] == "1.1.0"
    assert document["jsonSchema"]["x-intake"]["version"] == "1.1.0"
    assert "fields" not in document
    assert module._matches_canonical_template(document)


def test_seed_match_rejects_conflicting_schema() -> None:
    module = _load_seed_module()
    document = module._template_document()
    document["jsonSchema"]["properties"]["priority"]["enum"].append("unknown")

    assert not module._matches_canonical_template(document)
