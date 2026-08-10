"""Static verification: Service Bus identity settings for Flex Consumption cold-scale.

The FC1 external scale controller monitors Service Bus queue depth to spin up
instances from zero. It authenticates independently using the app settings under
the connection prefix. Without explicit __credential and __clientId, the
controller cannot use the user-assigned managed identity and messages stall.

Required settings for connection prefix INTAKE_SERVICEBUS_NAMESPACE:
  - __fullyQualifiedNamespace  (the FQDN)
  - __credential               (must be 'managedidentity')
  - __clientId                 (the worker UAI client ID)

Reference:
  https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-service-bus-trigger
"""

import re
from pathlib import Path

BICEP_PATH = Path(__file__).resolve().parents[3] / "infra" / "modules" / "functions.bicep"
PREFIX = "INTAKE_SERVICEBUS_NAMESPACE"


def _read_bicep() -> str:
    assert BICEP_PATH.exists(), f"Expected {BICEP_PATH}"
    return BICEP_PATH.read_text(encoding="utf-8")


def test_credential_setting_present():
    content = _read_bicep()
    assert f"{PREFIX}__credential" in content, (
        f"Missing '{PREFIX}__credential' — scale controller cannot authenticate."
    )


def test_credential_value_is_managedidentity():
    content = _read_bicep()
    pattern = re.compile(
        rf"name:\s*'{re.escape(PREFIX)}__credential'.*?value:\s*'managedidentity'",
        re.DOTALL,
    )
    assert pattern.search(content), (
        f"'{PREFIX}__credential' must have value 'managedidentity'."
    )


def test_clientid_setting_present():
    content = _read_bicep()
    assert f"{PREFIX}__clientId" in content, (
        f"Missing '{PREFIX}__clientId' — scale controller will fall back to "
        "system-assigned identity (which doesn't exist on this app)."
    )


def test_clientid_references_worker_identity_param():
    content = _read_bicep()
    pattern = re.compile(
        rf"name:\s*'{re.escape(PREFIX)}__clientId'.*?value:\s*workerIdentityClientId",
        re.DOTALL,
    )
    assert pattern.search(content), (
        f"'{PREFIX}__clientId' must reference workerIdentityClientId param."
    )


def test_instance_memory_is_512():
    content = _read_bicep()
    assert "instanceMemoryMB: 512" in content, "instanceMemoryMB must remain 512."


def test_no_always_ready():
    content = _read_bicep()
    assert "alwaysReady" not in content.lower(), "alwaysReady must not be configured."
