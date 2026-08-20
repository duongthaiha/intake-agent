# Intake Agent Foundry Prompt adapter

This package loads the checked-in requester and reviewer Prompt Agent
configuration and builds current `azure-ai-projects` `PromptAgentDefinition`
objects. Each immutable agent version points to a Foundry Toolbox consumer MCP
endpoint through an agent-identity project connection.

The caller owns `AIProjectClient` and its credential. This package imports no
credential implementation, application, domain, persistence, or Azure data SDK.
After testing a new version, `configure_endpoint` pins it and enables Responses
plus Activity protocols with the matching Bot Service authorization scheme.

The instructions are generated from `intake-agent-behavior`; therefore the
Prompt Agent must reload requester context every turn, show only
`allowedActions`, stop for OAuth consent, preserve the Foundry conversation on
resume, and reload rather than silently replay a stale mutation.
