"""Fail closed unless a signed evidence manifest and all artifact digests are valid."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.evidence import EvidenceError, load_and_validate_manifest
from evaluation.scorecard import load_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument(
        "--expected-deployment-variant",
        required=True,
        choices=("baseline", "hardened"),
    )
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-dataset-version", required=True)
    parser.add_argument("--expected-threshold-set-version", required=True)
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("evaluation/config/thresholds-v1.0.0.json"),
    )
    args = parser.parse_args()
    try:
        manifest = load_and_validate_manifest(
            args.manifest,
            expected_commit_sha=args.expected_commit_sha,
            expected_deployment_variant=args.expected_deployment_variant,
            expected_run_id=args.expected_run_id,
            expected_dataset_version=args.expected_dataset_version,
            expected_threshold_set_version=args.expected_threshold_set_version,
            threshold_config=load_json(args.thresholds),
        )
    except (OSError, json.JSONDecodeError, EvidenceError) as exc:
        print(f"release evidence failed closed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "release_id": manifest["release_id"],
                "release_decision": manifest["evaluation"]["release_decision"],
                "signature_key_id": manifest["signature"]["key_id"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
