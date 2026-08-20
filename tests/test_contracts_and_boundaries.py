import ast
from pathlib import Path

import pytest
from intake_agent_behavior import load_specification
from intake_agent_contracts import CONTRACT_VERSION, UpdateFieldRequest
from pydantic import ValidationError

ROOT = Path(__file__).parents[1]


def test_contracts_are_versioned_strict_and_agent_neutral() -> None:
    assert CONTRACT_VERSION == "1.0"
    model = UpdateFieldRequest(
        requestId="request-1",
        expectedRevision=0,
        commandId="command-1",
        fieldPath="title",
        value="A valid title",
        sourceReference="message:1",
        confidence=0.9,
    )
    assert model.field_path == "title"
    with pytest.raises(ValidationError):
        UpdateFieldRequest(
            requestId="request-1",
            expectedRevision=0,
            commandId="command-1",
            fieldPath="title",
            value="A valid title",
            sourceReference="message:1",
            confidence=0.9,
            tenantId="model-controlled-tenant",
        )


def test_shared_behavior_declares_bounded_surfaces() -> None:
    behavior = load_specification()
    assert behavior["version"] == "1.0"
    assert behavior["requesterTools"] == [
        "get_intake_context",
        "update_intake_field",
        "submit_intake_for_review",
        "list_my_intake_requests",
    ]
    assert "decide_intake_review" in behavior["reviewerTools"]
    assert any("identity" in rule for rule in behavior["safetyRules"])


def test_internal_import_boundaries() -> None:
    allowed = {
        "intake_agent_contracts": set(),
        "intake_agent_behavior": set(),
        "intake_domain": set(),
        "intake_application": {"intake_domain"},
        "intake_persistence": {"intake_domain"},
        "intake_mcp": {
            "intake_agent_contracts",
            "intake_application",
            "intake_domain",
            "intake_persistence",
        },
    }
    package_roots = {
        path.name.replace("-", "_"): next((path / "src").iterdir())
        for path in (ROOT / "packages").iterdir()
    }
    violations: list[str] = []
    for package, package_root in package_roots.items():
        for source in package_root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported: str | None = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported = alias.name.split(".")[0]
                        _check_import(package, source, imported, allowed, violations)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = node.module.split(".")[0]
                    _check_import(package, source, imported, allowed, violations)
    assert violations == []


def _check_import(
    package: str,
    source: Path,
    imported: str,
    allowed: dict[str, set[str]],
    violations: list[str],
) -> None:
    if imported in allowed and imported != package and imported not in allowed[package]:
        violations.append(f"{source.relative_to(ROOT)} imports forbidden {imported}")

