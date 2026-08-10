from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.evaluation

DATASET = Path(__file__).parent / "dataset" / "foundry_smoke.jsonl"


def _rows() -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_foundry_smoke_dataset_has_compact_supported_shape() -> None:
    rows = _rows()

    assert 4 <= len(rows) <= 10
    assert all(set(row) == {"query", "expected_behavior"} for row in rows)
    assert all(row["query"].strip() and row["expected_behavior"].strip() for row in rows)


def test_foundry_smoke_dataset_covers_acceptance_behaviors() -> None:
    expected_behaviors = "\n".join(row["expected_behavior"].lower() for row in _rows())

    for required_signal in (
        "project.name",
        "project.description",
        "requester.business_unit",
        "priority",
        "blocking missing",
        "fail closed",
        "persisted domain",
        "reviewer",
    ):
        assert required_signal in expected_behaviors


def test_foundry_smoke_dataset_uses_runtime_template_field_paths() -> None:
    content = DATASET.read_text(encoding="utf-8")

    assert "budget.amount" in content
    assert "timeline.target_date" in content
    assert "project.budget" not in content
    assert "project.owner" not in content
    assert "project.timeline" not in content


def test_foundry_smoke_queries_use_responses_natural_language_contract() -> None:
    rows = _rows()

    assert all(not row["query"].lstrip().startswith("{") for row in rows)
    assert any("start" in row["query"].lower() for row in rows)
    assert any("submit" in row["query"].lower() for row in rows)
