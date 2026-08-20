from __future__ import annotations

import json
import unittest
from pathlib import Path

from evaluation.scorecard import load_json, load_jsonl, validate_dataset

ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT / "evaluation" / "dataset" / "v1.0.0"


class DatasetTests(unittest.TestCase):
    def test_dataset_is_valid_and_complete(self) -> None:
        manifest = load_json(DATASET_DIR / "manifest.json")
        cases = load_jsonl(DATASET_DIR / "cases.jsonl")
        validate_dataset(cases, manifest)
        self.assertEqual(manifest["case_count"], len(cases))

    def test_required_case_categories_exist(self) -> None:
        cases = load_jsonl(DATASET_DIR / "cases.jsonl")
        categories = {
            category
            for case in cases
            for category in case.get("categories", [])
        }
        required = {
            "complete",
            "incomplete",
            "contradictory",
            "ambiguous",
            "sensitive",
            "prompt-injection",
            "multilingual",
            "service-failure",
            "cross-variant",
            "authorization",
        }
        self.assertTrue(required <= categories)

    def test_dataset_contains_no_approved_production_data(self) -> None:
        manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["production_data"])
        self.assertTrue(manifest["development_use_prohibited"])
        self.assertEqual("synthetic-confidential", manifest["classification"])


if __name__ == "__main__":
    unittest.main()
