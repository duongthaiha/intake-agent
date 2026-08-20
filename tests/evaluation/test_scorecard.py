from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from evaluation.scorecard import build_scorecard, load_json, load_jsonl

ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT / "evaluation" / "dataset" / "v1.0.0"
THRESHOLDS = ROOT / "evaluation" / "config" / "thresholds-v1.0.0.json"


def perfect_result(case: dict[str, Any], variant: str) -> dict[str, Any]:
    expected = case["expected"]
    return {
        "case_id": case["case_id"],
        "variant": variant,
        "fields": expected["fields"],
        "gaps": expected["gaps"],
        "contradictions": expected["contradictions"],
        "question_intents": expected["question_intents"],
        "repeated_question_count": 0,
        "outcome": expected["outcome"],
        "reviewer_accepted": expected["reviewer_accepted"],
        "critical_failures": [],
    }


class ScorecardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load_jsonl(DATASET_DIR / "cases.jsonl")
        self.manifest = load_json(DATASET_DIR / "manifest.json")
        self.thresholds = load_json(THRESHOLDS)
        self.results = {
            "run_id": "run-test-1",
            "run_status": "succeeded",
            "candidate": {
                "commit_sha": "a" * 40,
                "deployment_variant": "baseline",
            },
            "versions": {
                "hosted_agent": "1.0.0",
                "prompt_agent": "1.0.0",
                "model": "test-model",
                "instructions": "1.0.0",
                "shared_behavior": "1.0.0",
                "toolbox": "1.0.0",
                "mcp_contract": "1.0.0",
                "template": "1.0.0",
                "schema": "1.0.0",
                "policy": "1.0.0",
                "deterministic_packages": "1.0.0",
            },
            "results": [
                perfect_result(case, variant)
                for variant in ("hosted", "prompt")
                for case in self.cases
            ],
        }

    def approved_inputs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        manifest = copy.deepcopy(self.manifest)
        manifest["approval"]["status"] = "approved"
        thresholds = copy.deepcopy(self.thresholds)
        thresholds["baseline_status"] = "approved"
        return manifest, thresholds

    def test_perfect_results_pass_approved_gate(self) -> None:
        manifest, thresholds = self.approved_inputs()
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("pass", scorecard["release_decision"])
        self.assertTrue(scorecard["variants"]["hosted"]["passed"])
        self.assertTrue(scorecard["variants"]["prompt"]["passed"])
        self.assertTrue(scorecard["differential"]["passed"])

    def test_unapproved_baseline_and_dataset_fail_closed(self) -> None:
        scorecard = build_scorecard(
            self.cases, self.manifest, self.results, self.thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertIn("dataset_not_approved", scorecard["decision_reasons"])
        self.assertIn(
            "threshold_baseline_not_approved", scorecard["decision_reasons"]
        )

    def test_missing_variant_result_fails_closed(self) -> None:
        manifest, thresholds = self.approved_inputs()
        self.results["results"].pop()
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertTrue(
            any("prompt:missing_result:" in reason for reason in scorecard["decision_reasons"])
        )

    def test_timeout_status_fails_closed(self) -> None:
        manifest, thresholds = self.approved_inputs()
        self.results["run_status"] = "timed_out"
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertIn(
            "evaluation_run_status:timed_out", scorecard["decision_reasons"]
        )

    def test_critical_failure_always_blocks_release(self) -> None:
        manifest, thresholds = self.approved_inputs()
        self.results["results"][0]["critical_failures"] = ["unauthorized_approval"]
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertIn(
            "hosted:complete-en-001:unauthorized_approval",
            scorecard["critical_failures"],
        )

    def test_missing_critical_failure_report_blocks_release(self) -> None:
        manifest, thresholds = self.approved_inputs()
        del self.results["results"][0]["critical_failures"]
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertTrue(
            any(
                "missing_critical_failure_report" in reason
                for reason in scorecard["decision_reasons"]
            )
        )

    def test_partial_threshold_configuration_blocks_release(self) -> None:
        manifest, thresholds = self.approved_inputs()
        del thresholds["required_metrics"]["groundedness"]
        del thresholds["differential_metrics"]["question_intent_agreement"]
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertIn(
            "variant:groundedness:threshold_missing",
            scorecard["decision_reasons"],
        )
        self.assertIn(
            "differential:question_intent_agreement:threshold_missing",
            scorecard["decision_reasons"],
        )

    def test_omitted_clarification_questions_fail_relevance_gate(self) -> None:
        manifest, thresholds = self.approved_inputs()
        for result in self.results["results"]:
            result["question_intents"] = []
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertFalse(
            scorecard["variants"]["hosted"]["threshold_checks"][
                "clarification_relevance"
            ]["passed"]
        )

    def test_differential_regression_blocks_release(self) -> None:
        manifest, thresholds = self.approved_inputs()
        prompt = next(
            result
            for result in self.results["results"]
            if result["variant"] == "prompt"
            and result["case_id"] == "complete-en-001"
        )
        prompt["outcome"] = "clarification_required"
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertFalse(
            scorecard["differential"]["threshold_checks"]["outcome_agreement"]["passed"]
        )

    def test_unknown_result_blocks_release(self) -> None:
        manifest, thresholds = self.approved_inputs()
        self.results["results"].append(
            {
                "case_id": "unknown-case",
                "variant": "unknown-variant",
                "critical_failures": ["authorization_bypass"],
            }
        )
        scorecard = build_scorecard(
            self.cases, manifest, self.results, thresholds
        )
        self.assertEqual("fail", scorecard["release_decision"])
        self.assertIn(
            "unknown_result_variant:unknown-variant:unknown-case",
            scorecard["decision_reasons"],
        )
        self.assertIn(
            "unknown_result_case:unknown-variant:unknown-case",
            scorecard["decision_reasons"],
        )

    def test_calculation_is_deterministic(self) -> None:
        manifest, thresholds = self.approved_inputs()
        first = build_scorecard(self.cases, manifest, self.results, thresholds)
        second = build_scorecard(self.cases, manifest, self.results, thresholds)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
