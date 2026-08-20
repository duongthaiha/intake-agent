"""Invoke deployed Hosted Agent Responses endpoints from the private network."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests
from azure.ai.projects import AIProjectClient
from azure.identity import ManagedIdentityCredential
from openai import APIStatusError

SESSION_PATTERN = re.compile(r"Session '([^']+)'")


def _response_summary(response: Any) -> dict[str, Any]:
    return {
        "id": response.id,
        "status": str(response.status),
        "output_types": [str(item.type) for item in response.output],
        "text": response.output_text,
    }


def _print_session_logs(
    *,
    endpoint: str,
    agent_name: str,
    session_id: str,
    token: str,
) -> None:
    for kind in ("console", "system"):
        response = requests.get(
            f"{endpoint.rstrip('/')}/agents/{agent_name}/sessions/{session_id}:logstream",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "api-version": "v1",
                "kind": kind,
                "tail": 300,
                "follow": "false",
            },
            timeout=(10, 5),
            stream=True,
        )
        print(f"{kind}_logs_status={response.status_code}", flush=True)
        response.raise_for_status()
        try:
            for line in response.iter_lines():
                if line:
                    print(line.decode("utf-8"), flush=True)
        except (requests.ConnectionError, requests.ReadTimeout):
            print(f"{kind}_logs_stream_complete", flush=True)
        finally:
            response.close()


def main() -> int:
    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    credential = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
    project = AIProjectClient(
        endpoint=endpoint,
        credential=credential,
        allow_preview=True,
    )
    results: dict[str, dict[str, Any]] = {}
    try:
        for name in ("intake-requester-hosted", "intake-reviewer-hosted"):
            client = project.get_openai_client(agent_name=name)
            try:
                try:
                    response = client.responses.create(
                        input="Reply with exactly READY.",
                    )
                except APIStatusError as error:
                    match = SESSION_PATTERN.search(str(error))
                    if match is not None:
                        token = credential.get_token("https://ai.azure.com/.default").token
                        _print_session_logs(
                            endpoint=endpoint,
                            agent_name=name,
                            session_id=match.group(1),
                            token=token,
                        )
                    raise
                results[name] = _response_summary(response)
            finally:
                client.close()
    finally:
        project.close()
        credential.close()
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
