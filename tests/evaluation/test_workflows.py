from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(
    encoding="utf-8"
)


class WorkflowContractTests(unittest.TestCase):
    def test_ci_contains_required_gate_surfaces(self) -> None:
        for job in (
            "lint-and-types:",
            "evaluation-tests:",
            "security:",
            "iac:",
            "required-checks:",
        ):
            self.assertIn(job, CI)
        self.assertNotIn("continue-on-error", CI)

    def test_release_uses_federation_and_no_github_secrets(self) -> None:
        self.assertIn("id-token: write", RELEASE)
        self.assertIn("azure/login@", RELEASE)
        self.assertIn("federated-credential-provider github", RELEASE)
        self.assertNotIn("secrets.", RELEASE)

    def test_production_depends_on_passing_test_evaluation(self) -> None:
        production = RELEASE.index("promote-production:")
        dependency = RELEASE.index("needs: evaluate-candidate", production)
        self.assertGreater(dependency, production)
        self.assertIn("environment: production", RELEASE[production:])
        self.assertIn("environment: test", RELEASE[:production])
        self.assertIn("group: release-test-evaluation", RELEASE)
        self.assertNotIn("group: release-${{ inputs.target_environment }}", RELEASE)

    def test_deployment_is_only_through_azd(self) -> None:
        self.assertGreaterEqual(RELEASE.count("azd up --no-prompt"), 2)
        self.assertNotIn("az deployment", RELEASE)
        self.assertNotIn("az containerapp update", RELEASE)
        self.assertNotIn("az functionapp deployment", RELEASE)

    def test_evaluation_is_bounded_and_evidence_bound(self) -> None:
        self.assertIn("--timeout-seconds 3600", RELEASE)
        self.assertIn("--expected-commit-sha", RELEASE)
        self.assertIn("--expected-deployment-variant", RELEASE)
        self.assertIn("--expected-run-id", RELEASE)
        self.assertIn("--expected-dataset-version", RELEASE)
        self.assertIn("--expected-threshold-set-version", RELEASE)


if __name__ == "__main__":
    unittest.main()
