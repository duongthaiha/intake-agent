# Intake Agent Foundry Hosted adapter

This package composes the current Microsoft Agent Framework
`ResponsesHostServer` and `FoundryToolbox` APIs. The host uses Responses
protocol `2.0.0`, reloads authoritative context before every turn, and exposes
only guarded actions from `allowedActions`.

The package intentionally accepts an `azure.core.credentials.TokenCredential`
from the deployment composition root. It never creates or imports a credential
implementation and never imports application, domain, persistence, Azure data,
or mutable identity code.

```python
settings = HostedAgentSettings.from_environment()
server = build_responses_host(deployment_owned_credential, settings)
server.run()
```

`ResponsesHostServer` natively emits `oauth_consent_request` output items when a
Foundry Toolbox connection requires user consent. Clients must complete consent
and retry the original turn with the same `previous_response_id` or
`conversation` identifier. A state-changing tool call is never replayed by the
adapter after a consent or stale-revision response.
