from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.evidence import EvidenceError, sha256_file, validate_manifest
from evaluation.scorecard import load_json

ROOT = Path(__file__).resolve().parents[2]
THRESHOLD_PATH = ROOT / "evaluation" / "config" / "thresholds-v1.0.0.json"


def approved_thresholds() -> dict[str, object]:
    thresholds = copy.deepcopy(load_json(THRESHOLD_PATH))
    thresholds["baseline_status"] = "approved"
    return thresholds


def component_versions() -> dict[str, str]:
    return {
        "hosted_agent": "1.0.0",
        "prompt_agent": "1.0.0",
        "model": "test-model",
        "instructions": "1.0.0",
        "shared_behavior": "1.0.0",
        "toolbox": "1.0.0",
        "mcp_contract": "1.0.0",
        "policy": "1.0.0",
        "template": "1.0.0",
        "schema": "1.0.0",
        "deterministic_packages": "1.0.0",
    }


class EvidenceTests(unittest.TestCase):
    def build_manifest(self, directory: Path) -> dict[str, object]:
        artifact = directory / "scorecard.json"
        artifact.write_text(
            json.dumps(
                {
                    "run_id": "run-test-1",
                    "release_decision": "pass",
                    "critical_failures": [],
                    "candidate": {
                        "commit_sha": "a" * 40,
                        "deployment_variant": "baseline",
                    },
                    "versions": component_versions(),
                    "dataset": {"dataset_version": "1.0.0"},
                    "threshold_set_version": "1.0.0",
                    "variants": {
                        variant: {
                            "passed": True,
                            "missing_results": [],
                            "metrics": {
                                name: {
                                    "value": (
                                        0.0
                                        if name
                                        in {
                                            "false_positive_gap_rate",
                                            "clarification_repetition_rate",
                                        }
                                        else 1.0
                                    )
                                }
                                for name in (
                                    "field_capture_accuracy",
                                    "required_gap_recall",
                                    "false_positive_gap_rate",
                                    "contradiction_precision",
                                    "contradiction_recall",
                                    "clarification_relevance",
                                    "clarification_repetition_rate",
                                    "groundedness",
                                    "completion_rate",
                                    "reviewer_acceptance",
                                )
                            },
                        }
                        for variant in ("hosted", "prompt")
                    },
                    "differential": {
                        "passed": True,
                        "metrics": {
                            name: {"value": 1.0}
                            for name in (
                                "field_agreement",
                                "gap_agreement",
                                "contradiction_agreement",
                                "question_intent_agreement",
                                "outcome_agreement",
                            )
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        human_review = directory / "human-review.json"
        human_review.write_text(
            json.dumps(
                {
                    "rubric_version": "1.0.0",
                    "decision": "pass",
                    "sample_count": 10,
                    "reviewer_count": 2,
                    "variants": {
                        variant: {
                            "passed": True,
                            "dimension_scores": {
                                "capture_fidelity": 4.5,
                                "gap_contradiction_quality": 4.5,
                                "clarification_quality": 4.5,
                                "groundedness": 4.5,
                                "workflow_correctness": 4.5,
                                "security_privacy": 4.5,
                                "helpfulness_accessibility": 4.5,
                            },
                            "critical_failures": [],
                        }
                        for variant in ("hosted", "prompt")
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "schema_version": "1.0.0",
            "release_id": "release-test-1",
            "candidate": {
                "commit_sha": "a" * 40,
                "deployment_variant": "baseline",
                "components": component_versions(),
            },
            "evaluation": {
                "run_id": "run-test-1",
                "dataset_version": "1.0.0",
                "threshold_set_version": "1.0.0",
                "release_decision": "pass",
                "variants": ["hosted", "prompt"],
            },
            "artifacts": [
                {
                    "name": "scorecard",
                    "path": "scorecard.json",
                    "sha256": sha256_file(artifact),
                    "media_type": "application/json",
                },
                {
                    "name": "human-review",
                    "path": "human-review.json",
                    "sha256": sha256_file(human_review),
                    "media_type": "application/json",
                }
            ],
            "approvals": [
                {
                    "role": "release-owner",
                    "subject": "test-owner",
                    "decision": "approved",
                    "decided_at": "2026-08-20T00:00:00Z",
                }
            ],
            "signature": {
                "algorithm": "RS256",
                "key_id": "https://example.invalid/keys/release",
                "certificate_thumbprint": "TEST-THUMBPRINT",
                "signed_at": "2026-08-20T00:00:00Z",
                "value": "synthetic-test-signature",
            },
        }

    def test_complete_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            validate_manifest(
                self.build_manifest(directory),
                directory,
                expected_commit_sha="a" * 40,
                expected_deployment_variant="baseline",
                expected_run_id="run-test-1",
                expected_dataset_version="1.0.0",
                expected_threshold_set_version="1.0.0",
                threshold_config=approved_thresholds(),
            )

    def test_unsigned_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest = self.build_manifest(directory)
            manifest["signature"] = {}
            with self.assertRaises(EvidenceError):
                validate_manifest(
                    manifest,
                    directory,
                    threshold_config=approved_thresholds(),
                )

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest = self.build_manifest(directory)
            manifest["artifacts"][0]["sha256"] = "0" * 64  # type: ignore[index]
            with self.assertRaises(EvidenceError):
                validate_manifest(
                    manifest,
                    directory,
                    threshold_config=approved_thresholds(),
                )

    def test_replayed_manifest_fails_release_binding(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest = self.build_manifest(directory)
            with self.assertRaises(EvidenceError):
                validate_manifest(
                    manifest,
                    directory,
                    expected_commit_sha="b" * 40,
                    expected_deployment_variant="baseline",
                    expected_run_id="run-test-1",
                    expected_dataset_version="1.0.0",
                    expected_threshold_set_version="1.0.0",
                    threshold_config=approved_thresholds(),
                )

    def test_non_passing_human_review_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest = self.build_manifest(directory)
            review_path = directory / "human-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["decision"] = "fail"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            manifest["artifacts"][1]["sha256"] = sha256_file(review_path)  # type: ignore[index]
            with self.assertRaises(EvidenceError):
                validate_manifest(
                    manifest,
                    directory,
                    threshold_config=approved_thresholds(),
                )

    def test_malformed_human_critical_failure_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest = self.build_manifest(directory)
            review_path = directory / "human-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["variants"]["hosted"]["critical_failures"] = {}
            review_path.write_text(json.dumps(review), encoding="utf-8")
            manifest["artifacts"][1]["sha256"] = sha256_file(review_path)  # type: ignore[index]
            with self.assertRaises(EvidenceError):
                validate_manifest(
                    manifest,
                    directory,
                    threshold_config=approved_thresholds(),
                )

    def test_incomplete_component_provenance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest = self.build_manifest(directory)
            manifest["candidate"]["components"] = {}  # type: ignore[index]
            with self.assertRaises(EvidenceError):
                validate_manifest(
                    manifest,
                    directory,
                    threshold_config=approved_thresholds(),
                )


if __name__ == "__main__":
    unittest.main()
