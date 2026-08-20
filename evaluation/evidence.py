"""Structural and digest validation for signed release evidence manifests."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evaluation.scorecard import REQUIRED_VERSION_FIELDS, validate_passing_scorecard

JsonObject = dict[str, Any]

HUMAN_REVIEW_DIMENSIONS = {
    "capture_fidelity",
    "gap_contradiction_quality",
    "clarification_quality",
    "groundedness",
    "workflow_correctness",
    "security_privacy",
    "helpfulness_accessibility",
}


class EvidenceError(ValueError):
    """Raised when release evidence is incomplete or inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{label} must be an object")
    return value


def _required(mapping: Mapping[str, Any], names: set[str], label: str) -> None:
    missing = sorted(name for name in names if mapping.get(name) in (None, ""))
    if missing:
        raise EvidenceError(f"{label} missing required values: {missing}")


def validate_human_review(value: Mapping[str, Any]) -> None:
    _required(
        value,
        {"rubric_version", "decision", "sample_count", "reviewer_count", "variants"},
        "human_review",
    )
    if value["rubric_version"] != "1.0.0" or value["decision"] != "pass":
        raise EvidenceError("human review rubric or decision is non-passing")
    if not isinstance(value["sample_count"], int) or value["sample_count"] < 1:
        raise EvidenceError("human review sample_count must be positive")
    if not isinstance(value["reviewer_count"], int) or value["reviewer_count"] < 2:
        raise EvidenceError("human review requires at least two reviewers")
    variants = _mapping(value["variants"], "human_review.variants")
    if set(variants) != {"hosted", "prompt"}:
        raise EvidenceError("human review must include hosted and prompt variants")
    scores: dict[str, Mapping[str, Any]] = {}
    for variant_name in ("hosted", "prompt"):
        variant = _mapping(variants[variant_name], f"human_review.{variant_name}")
        _required(
            variant,
            {"passed", "dimension_scores", "critical_failures"},
            f"human_review.{variant_name}",
        )
        if variant["passed"] is not True or variant["critical_failures"]:
            raise EvidenceError(f"human review {variant_name} is non-passing")
        if not isinstance(variant["critical_failures"], list):
            raise EvidenceError(
                f"human review {variant_name}.critical_failures must be an array"
            )
        dimensions = _mapping(
            variant["dimension_scores"],
            f"human_review.{variant_name}.dimension_scores",
        )
        if set(dimensions) != HUMAN_REVIEW_DIMENSIONS:
            raise EvidenceError(
                f"human review {variant_name} dimensions are incomplete"
            )
        for dimension, score in dimensions.items():
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 1.0 <= score <= 5.0
                or score < 4.0
            ):
                raise EvidenceError(
                    f"human review {variant_name}.{dimension} is below 4.0"
                )
        scores[variant_name] = dimensions
    for dimension in HUMAN_REVIEW_DIMENSIONS:
        delta = abs(
            float(scores["hosted"][dimension]) - float(scores["prompt"][dimension])
        )
        if delta > 0.5:
            raise EvidenceError(
                f"human review differential exceeds 0.5 for {dimension}"
            )


def validate_manifest(
    manifest: Mapping[str, Any],
    base_dir: Path,
    *,
    expected_commit_sha: str | None = None,
    expected_deployment_variant: str | None = None,
    expected_run_id: str | None = None,
    expected_dataset_version: str | None = None,
    expected_threshold_set_version: str | None = None,
    threshold_config: Mapping[str, Any],
) -> None:
    _required(
        manifest,
        {
            "schema_version",
            "release_id",
            "candidate",
            "evaluation",
            "artifacts",
            "approvals",
            "signature",
        },
        "manifest",
    )
    if manifest.get("schema_version") != "1.0.0":
        raise EvidenceError("unsupported evidence manifest schema_version")

    candidate = _mapping(manifest["candidate"], "candidate")
    _required(candidate, {"commit_sha", "deployment_variant", "components"}, "candidate")
    components = _mapping(candidate["components"], "candidate.components")
    missing_components = sorted(
        name for name in REQUIRED_VERSION_FIELDS if not components.get(name)
    )
    if missing_components:
        raise EvidenceError(
            f"candidate.components missing required values: {missing_components}"
        )
    commit_sha = str(candidate["commit_sha"])
    if len(commit_sha) != 40 or any(
        character not in "0123456789abcdef" for character in commit_sha
    ):
        raise EvidenceError("candidate.commit_sha must be a lowercase 40-character SHA")
    if candidate["deployment_variant"] not in {"baseline", "hardened"}:
        raise EvidenceError("candidate.deployment_variant is invalid")
    if expected_commit_sha is not None and commit_sha != expected_commit_sha:
        raise EvidenceError("candidate.commit_sha does not match the release")
    if (
        expected_deployment_variant is not None
        and candidate["deployment_variant"] != expected_deployment_variant
    ):
        raise EvidenceError("candidate.deployment_variant does not match the release")

    evaluation = _mapping(manifest["evaluation"], "evaluation")
    _required(
        evaluation,
        {
            "run_id",
            "dataset_version",
            "threshold_set_version",
            "release_decision",
            "variants",
        },
        "evaluation",
    )
    if evaluation["release_decision"] != "pass":
        raise EvidenceError("evaluation.release_decision must be pass")
    if set(evaluation["variants"]) != {"hosted", "prompt"}:
        raise EvidenceError("evaluation must include hosted and prompt variants")
    expected_evaluation_values = {
        "run_id": expected_run_id,
        "dataset_version": expected_dataset_version,
        "threshold_set_version": expected_threshold_set_version,
    }
    for name, expected_value in expected_evaluation_values.items():
        if expected_value is not None and evaluation[name] != expected_value:
            raise EvidenceError(f"evaluation.{name} does not match the release")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise EvidenceError("artifacts must be a non-empty array")
    artifact_names: set[str] = set()
    for position, raw_artifact in enumerate(artifacts):
        artifact = _mapping(raw_artifact, f"artifacts[{position}]")
        _required(
            artifact,
            {"name", "path", "sha256", "media_type"},
            f"artifacts[{position}]",
        )
        artifact_path = (base_dir / str(artifact["path"])).resolve()
        try:
            artifact_path.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise EvidenceError(
                f"artifact path escapes evidence directory: {artifact_path}"
            ) from exc
        if not artifact_path.is_file():
            raise EvidenceError(f"artifact is missing: {artifact_path}")
        actual_digest = sha256_file(artifact_path)
        if actual_digest != artifact["sha256"]:
            raise EvidenceError(f"artifact digest mismatch: {artifact['name']}")
        name = str(artifact["name"])
        if name in artifact_names:
            raise EvidenceError(f"duplicate artifact name: {name}")
        artifact_names.add(name)
        if name == "scorecard":
            scorecard = json.loads(artifact_path.read_text(encoding="utf-8"))
            scorecard_mapping = _mapping(scorecard, "scorecard")
            try:
                validate_passing_scorecard(scorecard_mapping, threshold_config)
            except ValueError as exc:
                raise EvidenceError(str(exc)) from exc
            scorecard_candidate = _mapping(
                scorecard_mapping.get("candidate"), "scorecard.candidate"
            )
            scorecard_versions = _mapping(
                scorecard_mapping.get("versions"), "scorecard.versions"
            )
            for component_name in REQUIRED_VERSION_FIELDS:
                if scorecard_versions.get(component_name) != components.get(
                    component_name
                ):
                    raise EvidenceError(
                        f"scorecard version does not match candidate component: {component_name}"
                    )
            if (
                expected_commit_sha is not None
                and scorecard_candidate.get("commit_sha") != expected_commit_sha
            ):
                raise EvidenceError("scorecard candidate SHA does not match the release")
            if (
                expected_deployment_variant is not None
                and scorecard_candidate.get("deployment_variant")
                != expected_deployment_variant
            ):
                raise EvidenceError(
                    "scorecard deployment variant does not match the release"
                )
            if expected_run_id is not None and scorecard_mapping.get("run_id") != expected_run_id:
                raise EvidenceError("scorecard.run_id does not match the release")
            dataset = _mapping(scorecard_mapping.get("dataset"), "scorecard.dataset")
            if (
                expected_dataset_version is not None
                and dataset.get("dataset_version") != expected_dataset_version
            ):
                raise EvidenceError("scorecard dataset version does not match the release")
            if (
                expected_threshold_set_version is not None
                and scorecard_mapping.get("threshold_set_version")
                != expected_threshold_set_version
            ):
                raise EvidenceError("scorecard threshold version does not match the release")
        elif name == "human-review":
            human_review = json.loads(artifact_path.read_text(encoding="utf-8"))
            validate_human_review(_mapping(human_review, "human_review"))
    missing_artifacts = {"scorecard", "human-review"} - artifact_names
    if missing_artifacts:
        raise EvidenceError(
            f"manifest missing required artifacts: {sorted(missing_artifacts)}"
        )

    approvals = manifest["approvals"]
    if not isinstance(approvals, list) or not approvals:
        raise EvidenceError("approvals must be a non-empty array")
    for position, raw_approval in enumerate(approvals):
        approval = _mapping(raw_approval, f"approvals[{position}]")
        _required(
            approval,
            {"role", "subject", "decision", "decided_at"},
            f"approvals[{position}]",
        )
        if approval["decision"] != "approved":
            raise EvidenceError(f"approvals[{position}] is not approved")

    signature = _mapping(manifest["signature"], "signature")
    _required(
        signature,
        {
            "algorithm",
            "key_id",
            "certificate_thumbprint",
            "signed_at",
            "value",
        },
        "signature",
    )
    if signature["algorithm"] not in {"RS256", "ES256"}:
        raise EvidenceError("signature.algorithm is not supported")


def load_and_validate_manifest(
    path: Path,
    *,
    expected_commit_sha: str | None = None,
    expected_deployment_variant: str | None = None,
    expected_run_id: str | None = None,
    expected_dataset_version: str | None = None,
    expected_threshold_set_version: str | None = None,
    threshold_config: Mapping[str, Any],
) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceError("evidence manifest must contain a JSON object")
    validate_manifest(
        value,
        path.parent,
        expected_commit_sha=expected_commit_sha,
        expected_deployment_variant=expected_deployment_variant,
        expected_run_id=expected_run_id,
        expected_dataset_version=expected_dataset_version,
        expected_threshold_set_version=expected_threshold_set_version,
        threshold_config=threshold_config,
    )
    return value
