from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.evaluation

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "eval.yaml"


def test_eval_config_targets_local_hosted_agent_intent() -> None:
    config = CONFIG.read_text(encoding="utf-8")

    assert re.search(
        (
            r"(?m)^agent:\s*\n"
            r"\s+name: intake-agent\s*\n"
            r"\s+kind: hosted\s*\n"
            r'\s+version: "8"\s*\n'
            r"\s+model: gpt-5-nano$"
        ),
        config,
    )
    assert re.search(
        r"(?m)^dataset:\s*\n\s+local_uri: evaluation/dataset/foundry_smoke.jsonl$",
        config,
    )
    assert re.search(r"(?m)^options:\s*\n\s+eval_model: gpt-5-nano$", config)


def test_eval_config_uses_compact_acceptance_evaluator_set() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    evaluators = re.findall(r"(?m)^\s+- ([a-z0-9_.-]+)$", config)

    assert evaluators == [
        "builtin.task_adherence",
        "builtin.intent_resolution",
        "builtin.indirect_attack",
    ]


def test_eval_config_contains_no_unverified_remote_references() -> None:
    config = CONFIG.read_text(encoding="utf-8")

    for remote_only_key in (
        "project_endpoint:",
        "dataset.name:",
        "dataset.version:",
        "suiteName:",
        "suiteVersion:",
    ):
        assert remote_only_key not in config

    assert 'version: "8"' in config
    dataset_path = ROOT / "evaluation" / "dataset" / "foundry_smoke.jsonl"
    assert dataset_path.is_file()
