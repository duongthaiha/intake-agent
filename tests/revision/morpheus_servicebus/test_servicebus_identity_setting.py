"""Static verification: functions.bicep uses identity-based Service Bus connection setting.

The Python Functions triggers use connection="INTAKE_SERVICEBUS_NAMESPACE", so
the app setting MUST be named 'INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace'
(double underscore) per the Azure Functions identity-based connection convention.

Reference: https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-service-bus-trigger
"""

import re
from pathlib import Path

BICEP_PATH = Path(__file__).resolve().parents[3] / "infra" / "modules" / "functions.bicep"

EXPECTED_SETTING = "INTAKE_SERVICEBUS_NAMESPACE__fullyQualifiedNamespace"
WRONG_SETTING_PATTERN = re.compile(
    r"name:\s*'INTAKE_SERVICEBUS_NAMESPACE'\s*$", re.MULTILINE
)


def test_bicep_file_exists():
    assert BICEP_PATH.exists(), f"Expected {BICEP_PATH} to exist"


def test_identity_based_setting_present():
    content = BICEP_PATH.read_text(encoding="utf-8")
    assert EXPECTED_SETTING in content, (
        f"functions.bicep must contain '{EXPECTED_SETTING}' for identity-based "
        "Service Bus trigger binding resolution."
    )


def test_bare_namespace_setting_absent():
    content = BICEP_PATH.read_text(encoding="utf-8")
    match = WRONG_SETTING_PATTERN.search(content)
    assert match is None, (
        "functions.bicep must NOT contain a bare 'INTAKE_SERVICEBUS_NAMESPACE' "
        "app setting (without __fullyQualifiedNamespace suffix). "
        "Identity-based connections require the double-underscore suffix."
    )
