# Local development profile

The local profile composes the same deterministic application and domain
behavior used by future deployed adapters with an in-memory implementation of
the request store, idempotency records, audit stream, outbox, and delivery
status. It seeds the `software-request` template, a requester, an assigned
reviewer, a completion-worker identity, and a successful downstream contract
stub.

Run `uv run intake-local` and connect an MCP client to
`http://127.0.0.1:8000/mcp`. The endpoint uses the official MCP Python SDK 2.x
`MCPServer` API with the stateless streamable-HTTP transport. This is the
current SDK terminology for the ergonomic server surface called FastMCP in
earlier SDK releases and architecture discussions.

Requester tools never accept tenant, actor, role, authorization, or credential
arguments. Reviewer tools likewise execute as the server-configured local
reviewer. This keeps identity outside model control while providing a
credential-free development profile.

Restart the process or call `LocalProfile.reset()` in tests to clear all local
state deterministically. Features requiring Azure or Teams—including delegated
OAuth, managed identity, Cosmos DB durability, Service Bus delivery, native
Teams publishing, notifications, and private connectivity—are not simulated
and require a deployed profile in a later delivery layer.
