"""No-credential local composition smoke for the hosted runtime."""

from __future__ import annotations

import os

from azure.core.credentials import AccessToken
from intake_agent_contracts import AgentRole

from intake_foundry_hosted.host import HostedAgentSettings, build_responses_host


class _FakeCredential:
    def get_token(self, *scopes: str, **kwargs: object) -> AccessToken:
        del scopes, kwargs
        return AccessToken("local-smoke-token", 4_102_444_800)


def main() -> None:
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    settings = HostedAgentSettings(
        project_endpoint="https://example.services.ai.azure.com/api/projects/local-smoke",
        model_deployment="local-smoke-model",
        toolbox_endpoint=(
            "https://example.services.ai.azure.com/api/projects/local-smoke/"
            "toolboxes/intake-requester/mcp?api-version=v1"
        ),
        toolbox_name="intake-requester",
        role=AgentRole.REQUESTER,
    )
    server = build_responses_host(_FakeCredential(), settings)
    if server is None:
        raise RuntimeError("Hosted Responses server composition failed.")
    print(
        "Hosted Responses 2.0 and Foundry Toolbox composition succeeded "
        "without cloud credentials."
    )
