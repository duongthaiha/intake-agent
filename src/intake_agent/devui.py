"""Loopback-only browser UI for local Intake Agent development."""
from __future__ import annotations

import os
import secrets

from agent_framework import Agent
from agent_framework.devui import serve
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from intake_agent.config import IntakeConfigurationError, IntakeSettings, get_settings
from intake_agent.hosted import (
    build_hosted_runtime,
    create_intake_agent,
    resolve_foundry_configuration,
)


def build_devui_agent(settings: IntakeSettings | None = None) -> Agent:
    """Build a local-only agent that uses a fixed development identity."""
    load_dotenv(override=False)
    cfg = settings or get_settings()
    if cfg.environment.strip().lower() != "local":
        raise IntakeConfigurationError(
            "Intake DevUI is restricted to INTAKE_ENVIRONMENT=local"
        )

    endpoint, model = resolve_foundry_configuration()
    runtime = build_hosted_runtime(cfg)
    client = FoundryChatClient(
        project_endpoint=endpoint,
        model=model,
        credential=DefaultAzureCredential(),
    )
    return create_intake_agent(
        client,
        runtime,
        local_dev_identity=("devui-user", "devui-chat"),
    )


def run() -> None:
    """Start authenticated Agent Framework DevUI on the loopback interface."""
    port = int(os.getenv("INTAKE_DEVUI_PORT", "8080"))
    auth_token = secrets.token_urlsafe(32)
    print(
        "\nIntake Agent DevUI authentication token:\n"
        f"  {auth_token}\n"
        f"Open http://127.0.0.1:{port} and enter this token when prompted.\n",
        flush=True,
    )
    serve(
        entities=[build_devui_agent()],
        host="127.0.0.1",
        port=port,
        auto_open=False,
        auth_enabled=True,
        auth_token=auth_token,
    )


if __name__ == "__main__":
    run()
