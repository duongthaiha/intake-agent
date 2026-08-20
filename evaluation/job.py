"""Managed-identity entry point for the private evaluation Container Apps job."""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from intake_persistence.blob import (
    BlobContainer,
    BlobEvaluationEvidenceStore,
    EvaluationEvidence,
)

from evaluation.scorecard import build_scorecard, load_json, load_jsonl

ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "1.0.0"
THRESHOLD_SET_VERSION = "1.0.0"
VERSION_FIELDS = (
    "hosted_agent",
    "prompt_agent",
    "model",
    "instructions",
    "shared_behavior",
    "toolbox",
    "mcp_contract",
    "template",
    "schema",
    "policy",
    "deterministic_packages",
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _fallback_results(run_id: str) -> dict[str, Any]:
    commit_sha = os.environ.get("EVALUATION_COMMIT_SHA", "")
    return {
        "run_id": run_id,
        "run_status": "missing_results",
        "candidate": {
            "commit_sha": commit_sha,
            "deployment_variant": "hardened",
        },
        "versions": {
            name: os.environ.get(f"EVALUATION_VERSION_{name.upper()}", "unconfigured")
            for name in VERSION_FIELDS
        },
        "results": [],
    }


def _load_results(
    service: BlobServiceClient,
    *,
    container_name: str,
    blob_name: str,
    run_id: str,
) -> Mapping[str, Any]:
    if not blob_name:
        return _fallback_results(run_id)
    content = (
        service.get_blob_client(container=container_name, blob=blob_name)
        .download_blob()
        .readall()
    )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("evaluation result document must be a JSON object")
    return value


def run() -> tuple[dict[str, Any], str]:
    run_id = os.environ.get("EVALUATION_RUN_ID", "").strip() or f"run-{uuid.uuid4()}"
    client_id = _required_environment("AZURE_CLIENT_ID")
    blob_endpoint = _required_environment("STORAGE_BLOB_ENDPOINT")
    credential = DefaultAzureCredential(managed_identity_client_id=client_id)
    service = BlobServiceClient(account_url=blob_endpoint, credential=credential)

    dataset_dir = ROOT / "evaluation" / "dataset" / f"v{DATASET_VERSION}"
    manifest = load_json(dataset_dir / "manifest.json")
    cases = load_jsonl(dataset_dir / str(manifest.get("case_file", "")))
    thresholds = load_json(
        ROOT / "evaluation" / "config" / f"thresholds-v{THRESHOLD_SET_VERSION}.json"
    )
    results = _load_results(
        service,
        container_name=os.environ.get(
            "EVALUATION_RESULTS_CONTAINER", "evaluation-datasets"
        ),
        blob_name=os.environ.get("EVALUATION_RESULTS_BLOB", "").strip(),
        run_id=run_id,
    )
    scorecard = build_scorecard(cases, manifest, results, thresholds)
    content = (json.dumps(scorecard, indent=2, sort_keys=True) + "\n").encode()
    evidence_container = cast(
        BlobContainer,
        service.get_container_client(
            os.environ.get("EVALUATION_EVIDENCE_CONTAINER", "evaluation-evidence")
        ),
    )
    url = BlobEvaluationEvidenceStore(evidence_container).store(
        content,
        EvaluationEvidence(
            dataset_id=str(manifest["dataset_id"]),
            dataset_version=str(manifest["dataset_version"]),
            run_id=run_id,
            filename="scorecard.json",
            content_type="application/json",
            classification=str(manifest["classification"]),
            evaluator_version="1.0.0",
        ),
    )
    return scorecard, url


def main() -> int:
    try:
        scorecard, evidence_url = run()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"release_decision": "fail", "error": str(exc)}),
            file=sys.stderr,
        )
        return 2
    decision = str(scorecard["release_decision"])
    print(
        json.dumps(
            {
                "release_decision": decision,
                "run_id": scorecard["run_id"],
                "decision_reasons": scorecard["decision_reasons"],
                "evidence_url": evidence_url,
            },
            sort_keys=True,
        )
    )
    return 0 if decision == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
