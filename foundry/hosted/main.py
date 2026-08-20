"""Foundry Hosted Agent Responses 2.0 composition root."""

import asyncio

from azure.identity import DefaultAzureCredential
from intake_foundry_hosted import HostedAgentSettings, build_responses_host


async def _run() -> None:
    credential = DefaultAzureCredential()
    server = build_responses_host(credential, HostedAgentSettings.from_environment())
    try:
        await server.run_async()
    finally:
        credential.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
