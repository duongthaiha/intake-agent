# Intake Agent

Intake Agent captures an enterprise request through conversation, validates the
required information, persists progress, and prepares the request for human
review and downstream automation.

The solution combines a Microsoft Foundry Hosted Agent with deterministic
Python domain logic, durable Azure storage, event-driven Azure Functions, and
Microsoft Teams integration assets.

## Choose your path

| Goal | Start here |
|---|---|
| Use the deployed agent | [Use the deployed solution](#use-the-deployed-solution) |
| Run the solution without Azure | [Run locally](#run-locally) |
| Test the Teams cards and activity parser | [Run the Teams demo](#run-the-teams-demo) |
| Validate a change | [Validate the solution](#validate-the-solution) |
| Deploy or update Azure | [Deploy to Azure](#deploy-to-azure) |
| Understand the design | [Architecture](#architecture) |

## What the solution does

The agent supports this lifecycle:

1. Create or resume an intake request for the current user and conversation.
2. Capture structured fields such as project name, description, priority,
   budget, and target date.
3. Report missing or invalid information using deterministic domain rules.
4. Persist every accepted revision to Cosmos DB.
5. Resume the same request in the current or a fresh Foundry session.
6. Submit a complete request for human review.
7. Publish committed domain events through a durable outbox to Service Bus.
8. Run document, notification, integration, and outbox workers in Azure
   Functions.

Validation, lifecycle transitions, authorization boundaries, concurrency, and
idempotency live in Python code rather than in the model prompt.

## Use the deployed solution

### Access requirement

The deployed Foundry account uses private networking and has public access
disabled. Invoke it only from an approved VNet-connected runner, workstation,
or development environment with the required private DNS and Azure RBAC.

An HTTP 403 response containing `Public access is disabled` from a normal
workstation or public Cloud Shell is expected. Do not enable public access to
work around it.

### Sign in and select the environment

Run these commands from the repository root on a network path that can reach
the private Foundry endpoint.

PowerShell:

```powershell
az login
az account set --subscription "<subscription-id>"
azd auth login
azd env select dev
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
azd env get-values
```

Bash:

```bash
az login
az account set --subscription "<subscription-id>"
azd auth login
azd env select dev
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env get-values
```

Do not save `AZURE_DEV_USER_AGENT` in `azure.yaml`, an azd environment, or a
committed configuration file. Set it only for the current shell or command.

### Start or resume an intake

The Hosted Agent uses the OpenAI-compatible Responses protocol. `azd` manages
the remote session and conversation identifiers.

PowerShell:

```powershell
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
azd ai agent invoke --new-session --new-conversation `
  "Start an intake request for a customer portal redesign."
```

Bash:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill \
  azd ai agent invoke --new-session --new-conversation \
  "Start an intake request for a customer portal redesign."
```

Useful follow-up prompts include:

```text
Set project.name to "Customer Portal Redesign".
Set project.description to "Replace the legacy customer self-service portal".
Set priority to high and budget.amount to 50000.
Set timeline.target_date to 2026-12-31.
Show the authoritative intake context and list every remaining gap.
Submit this intake for review.
```

The agent scopes state using Foundry's platform-provided user and conversation
isolation. It does not accept caller identity, request IDs, or roles as model
tool arguments.

To start a new Foundry session while retaining durable intake state:

```powershell
azd ai agent invoke --new-session `
  "Load my persisted intake request and repeat the exact project name."
```

### Current dev deployment

These values describe the validated `dev` deployment as of the latest
deployment evidence. Use `azd env get-values` and Azure queries as the
authoritative source if the environment has since changed.

| Component | Current value |
|---|---|
| Resource group | `rg-intake-dev` |
| Azure region | `eastus2` |
| Foundry account | `ais-intake-2k2osaev` |
| Foundry project | `aiproj-intake-dev` |
| Model deployment | `gpt-5-nano` |
| Hosted Agent | `intake-agent`, active version `8` |
| Function App | `func-intake-dev` |
| Durable stores | Cosmos DB, Blob Storage, Service Bus |
| Network posture | Private endpoints; public access disabled |
| Authentication | User-assigned managed identities; no application keys |

The Function App has no HTTP trigger by design. Its four functions process
Service Bus messages and outbox dispatch work.

## Run locally

Local mode uses in-memory repositories and requires no Azure subscription.
No environment variables or Azure credentials are required.

### Local prerequisites

- Python 3.11 or newer
- Git
- PowerShell, Bash, or another terminal

### Quick start

Bash (Linux, macOS, or this dev container):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
intake-demo
```

PowerShell (Windows):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
intake-demo
```

The API starts at `http://127.0.0.1:8000`. Open
`http://127.0.0.1:8000/docs` for the interactive API documentation.

To use auto-reload while changing Python files, run this instead of
`intake-demo`:

```bash
python -m uvicorn intake_agent.main:app --reload --port 8000
```

### Test the agent in a browser

The Agent Framework DevUI provides a local chat interface for the hosted agent.
It uses the same instructions and deterministic tools as the Foundry Responses
host, with a fixed local-only development identity.

```bash
python -m pip install -e ".[devui]"
az login
cp .env.example .env
# Fill in the Foundry project endpoint and model deployment in .env.
intake-devui
```

Open `http://127.0.0.1:8080` and use the authentication token printed by
DevUI. Set `INTAKE_DEVUI_PORT` to choose another port. Local requests use
in-memory persistence and are reset when the process stops.

DevUI is intentionally isolated from production:

- `agent-framework-devui` is installed only through the optional `devui` extra.
- `intake-devui` binds to `127.0.0.1` and refuses to run unless
  `INTAKE_ENVIRONMENT=local`.
- Foundry direct-code builds install `requirements.txt`, which installs only
  the base project (`.`) and does not include the DevUI dependency.

### Try the local API

In a second terminal, check the service:

Bash:

```bash
curl --fail http://127.0.0.1:8000/health
```

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Create or resume a request:

Bash:

```bash
curl --fail --request POST http://127.0.0.1:8000/requests \
  --header "Content-Type: application/json" \
  --data '{"user_id":"alice","conversation_id":"local-conversation-1"}'
```

PowerShell:

```powershell
$body = @{
    user_id = "alice"
    conversation_id = "local-conversation-1"
} | ConvertTo-Json

$request = Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/requests `
    -ContentType "application/json" `
    -Body $body

$request
```

Local state is stored in memory and resets whenever the API process stops. Do
not configure Azure backends for this path; the local defaults select in-memory
persistence, blob storage, and event publishing.

The request fields are authored as JSON Schema in
`src/intake_domain/template_schemas/general-intake-v1.schema.json`. Edit that
schema—not Python seed code—to change a future template version. The runtime
flattens nested leaf properties such as `project.name` into the domain field
paths used by the API and agent tools.

The local API exposes:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Check liveness |
| `POST` | `/requests` | Create or resume a request |
| `GET` | `/requests` | List a user's requests |
| `GET` | `/requests/{request_id}` | Get context, gaps, and allowed actions |
| `POST` | `/requests/{request_id}/fields` | Propose field updates |
| `POST` | `/requests/{request_id}/submit` | Submit for review |
| `POST` | `/requests/{request_id}/review` | Record a local review decision |

See [the Python backend guide](src/intake_agent/README.md) for complete HTTP
examples and the detailed environment-variable reference.

## Run the Teams demo

The repository contains accessible Adaptive Cards, Teams activity contracts,
parsing, and a fail-closed authentication boundary. The local demo validates
those assets without Azure credentials or a Teams tenant.

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m intake_teams.demo --verbose
```

Bash:

```bash
PYTHONPATH=src python -m intake_teams.demo --verbose
```

The demo does not publish an app to Teams. Tenant publication still requires
Bot Service configuration, tenant policy approval, admin consent, and a
production token-validation configuration. Follow
[the Teams publishing spike](docs/teams/publishing-spike.md) before attempting
tenant publication.

## Validate the solution

Install the development dependencies first:

```powershell
python -m pip install -e ".[dev]"
```

Run the complete local suite:

```powershell
python -m pytest tests evaluation -q
```

Run the individual quality gates:

```powershell
python -m ruff check src tests evaluation
python -m mypy src
lint-imports
az bicep build --file infra/main.bicep --stdout | Out-Null
```

The Azure-marked durability test is intentionally skipped unless explicitly
enabled on an approved VNet-connected runner:

```powershell
$env:INTAKE_RUN_AZURE_TESTS = "1"
$env:INTAKE_AGENT_ENDPOINT = "<private-responses-endpoint>"
python -m pytest tests\azure\test_hosted_durable_persistence.py -m azure -q -s
```

That test verifies create, same-conversation resume, and fresh-session recovery
against durable Azure state. A public-network 403 is security evidence, not a
functional test pass.

See [the test strategy](docs/quality/test-strategy.md) and `eval.yaml` for the
quality and Foundry evaluation configuration.

## Deploy to Azure

### Azure prerequisites

- Azure CLI (`az`)
- Azure Developer CLI (`azd`)
- Bicep CLI through Azure CLI
- `microsoft.foundry`/`azure.ai.agents` azd extension satisfying
  `azure.yaml`
- Permission to deploy resources and assign the required managed-identity
  roles
- Access to the target private network for Hosted Agent code deployment and
  live verification

Check the installed Foundry tooling:

```powershell
azd version
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
azd extension list
```

If the `microsoft.foundry` extension is missing, install it with
`azd extension install microsoft.foundry`. Resolve any extension version
conflict before provisioning; `azure.yaml` declares the required
`azure.ai.agents` version.

### Authenticate and configure azd

```powershell
az login
az account set --subscription "<subscription-id>"
azd auth login
azd env select dev
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
azd env get-values
```

For a new environment, create it and set its subscription and location before
provisioning:

```powershell
azd env new "<environment-name>"
azd env set AZURE_SUBSCRIPTION_ID "<subscription-id>"
azd env set AZURE_LOCATION "<azure-region>"
```

### Preflight and preview

```powershell
.\scripts\azure\preflight.ps1 `
  -SubscriptionId "<subscription-id>" `
  -Location "<azure-region>" `
  -EnvName "<environment-name>"

$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
azd provision --preview --no-prompt
```

Review the preview before applying it. Do not recreate the retained legacy
Cosmos `requests` container or legacy Service Bus `domain-events` queue:
their immutable settings differ from the durable production resources.

### Provision and deploy

Run these commands from an approved private-network path:

```powershell
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"
azd provision --no-prompt
azd deploy --no-prompt
azd ai agent show --output json
azd ai agent invoke --new-session --new-conversation "Are you ready?"
.\scripts\azure\post-deploy-verify.ps1
```

The deployment uses:

- `hosted_main.py` for Foundry direct-code deployment.
- Python 3.13 for the Hosted Agent.
- Python 3.11 for Azure Functions.
- Managed identity for Cosmos DB, Blob Storage, Service Bus, and Foundry.
- Cosmos transactional batches for request projection, revision, audit event,
  and outbox persistence.
- The `request-state`, `templates`, and `idempotency` containers with partition
  keys `/requestId`, `/templateId`, and `/scopeId`.
- The `domain-events-durable` Service Bus queue with duplicate detection.

On first use, the Hosted Agent idempotently publishes its packaged canonical
JSON Schema template through its VNet-connected managed identity. This avoids
an external data-plane seed step against the private Cosmos endpoint.

Detailed runtime variables, resource shape, RBAC, and worker package
requirements are documented in
[infrastructure configuration](docs/contracts/infrastructure-config.md).

### GitHub Actions

`.github/workflows/ci.yml` performs Bicep and Python checks.
`.github/workflows/deploy.yml` uses workload identity federation and stores no
Azure password or client secret.

Configure the repository/environment variables documented at the top of
`deploy.yml`. A GitHub-hosted runner cannot invoke a private Foundry endpoint
unless it has an approved private-network path; use a VNet-connected
self-hosted runner or equivalent approved deployment runner for those steps.

## Architecture

```text
User / approved channel
          |
          v
Microsoft Foundry Hosted Agent (Responses protocol)
          |
          v
Deterministic intake domain and application services
          |
          +--> Cosmos DB: request state, templates, idempotency, atomic outbox
          +--> Blob Storage: generated request artifacts
          +--> Service Bus: durable domain events
                            |
                            v
                  Azure Functions workers
```

Repository packages:

| Package | Responsibility |
|---|---|
| `intake_domain` | Entities, validation, lifecycle, commands, events, protocols |
| `intake_persistence` | In-memory and managed-identity Azure adapters |
| `intake_agent` | Local API and Foundry Hosted Agent composition |
| `intake_workers` | Outbox, document, notification, and integration workers |
| `intake_teams` | Teams contracts, cards, parsing, auth boundary, and demo |

Read more:

- [Architecture](architecture.md)
- [Product backlog](productbacklog.md)
- [Package boundaries](docs/adr/ADR-012-package-module-boundaries.md)
- [Domain lifecycle](docs/adr/ADR-013-domain-entities-and-vertical-flow.md)
- [Teams integration boundary](docs/adr/ADR-014-teams-integration-boundary.md)
- [Repository interfaces](docs/contracts/repository-interfaces.md)
- [Deployment evidence](.azure/deployment-plan.md)

## Security and operational notes

- Public network access remains disabled for the deployed data and Foundry
  services.
- Runtime services use user-assigned managed identities; do not add account
  keys, connection strings, or Service Bus SAS policies.
- Deployed environments fail startup if any persistence backend is configured
  as `inmemory`.
- The Hosted Agent trusts Foundry isolation context, not model-supplied
  identity or authorization fields.
- Every mutation uses optimistic concurrency and idempotency controls.
- Teams production authentication fails closed until the real tenant token
  validation and publishing configuration is complete.
- Do not commit `.env` files, azd environment values, credentials, generated
  deployment packages, or temporary runner artifacts.

## Troubleshooting

### Foundry returns HTTP 403: public access is disabled

The caller is outside the approved private network or private DNS is not
resolving correctly. Move the invocation to a VNet-connected runner. Do not
enable public access.

### Hosted Agent fails during startup

Check:

- `AZURE_CLIENT_ID` selects the Hosted Agent user-assigned identity.
- All `INTAKE_COSMOS_*`, `INTAKE_BLOB_*`, and `INTAKE_SERVICEBUS_*` values were
  populated by azd.
- The identity has Cosmos DB Built-in Data Contributor, Storage Blob Data
  Contributor/Delegator as required, and Service Bus Sender permissions.
- `INTAKE_HOSTED_TENANT_ID` is set.

### Cosmos writes fail or transactional batches are rejected

Verify the configured request container uses partition key `/requestId`.
Cosmos partition keys are immutable; use `request-state` rather than trying to
convert the retained legacy `requests` container.

### Functions import modules locally but fail after deployment

The worker package must contain `intake_domain/` and `intake_persistence/`
beside `function_app.py`. Use the `azure.yaml` prepackage hook; do not zip only
`src/intake_workers`.

### Service Bus messages are not consumed from zero instances

Confirm the Functions identity connection settings include
`fullyQualifiedNamespace`, `credential=managedidentity`, and the user-assigned
identity `clientId`. The Flex Consumption scale controller also needs the
documented queue runtime-property permissions.

### A request cannot be submitted

Ask the agent to show the authoritative intake context and remaining gaps.
Submission is rejected until deterministic validation marks the request
complete, and a stale `expected_revision` is rejected to prevent overwrites.
