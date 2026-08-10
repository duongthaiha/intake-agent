# Teams Publishing Spike — Foundry Agent → Teams

**Owner:** Neo (Teams/Experience Engineer)  
**Status:** Draft — spike findings; publishing NOT yet completed  
**Date:** 2026-08-07  
**Related:** ADR-014, architecture.md §1, productbacklog.md POC-01

---

## Purpose

This document records the spike investigation for publishing the Intake Agent
(a Foundry-hosted Python agent) to Microsoft Teams via Foundry Agent Service
and Azure Bot Service. It covers the required path, tenant/admin/licensing
prerequisites, known blockers, and the safe fallback if publishing is delayed.

**This spike does not claim publishing has succeeded.**

---

## 1. Supported publishing path

```
Python Hosted Agent (Foundry Agent Service)
  └─► Azure Bot Service channel configuration
        └─► Microsoft Teams channel enabled on Bot Service
              └─► Teams app manifest (manifest.json) sideloaded or published
                    └─► User installs app in personal / team / group chat scope
```

### 1.1 Foundry Agent Service → Teams

Microsoft Foundry Agent Service supports publishing agents directly to Teams
through the standard Azure Bot Service Teams channel integration.

Reference:
- [Publish a Foundry Agent to Microsoft Teams](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/agents/publish-teams)
- [Bot Framework Teams channel overview](https://learn.microsoft.com/en-us/azure/bot-service/channel-connect-teams)

**Key steps:**

1. Deploy the Foundry Hosted Agent in Azure (Bicep / `azd up`).
2. In Azure Bot Service resource, enable the **Microsoft Teams** channel.
3. Accept the Terms of Service for the Teams channel.
4. Note the **Bot App ID** (Entra app registration) for the manifest.
5. Substitute `{{BOT_APP_ID}}` and other template variables in
   `src/intake_teams/manifest/manifest.json`.
6. Package the manifest with `color.png` (192×192) and `outline.png` (32×32)
   icons into a `.zip` archive.
7. Sideload (dev) or publish (production) the app.

---

## 2. Tenant, admin, and licensing prerequisites

### 2.1 Microsoft 365 tenant requirements

| Requirement | Detail | Status |
|---|---|---|
| Microsoft 365 tenant with Teams enabled | Enterprise M365 E3/E5 or Teams Essentials | Must be confirmed by tenant admin |
| Custom app sideloading enabled | Teams Admin Center → Teams apps → Setup policies → Allow sideloading | Required for dev/POC; may be restricted |
| Bot registration (Entra app) | App registration with `https://<bot-domain>/api/messages` reply URL | Created during Bicep deployment |
| Teams channel in Bot Service | Teams channel enabled in Azure Bot Service resource | Part of Foundry Agent deployment |
| Foundry Agent Service quota | Azure subscription quota for Foundry Agent Service SKU | Must be checked per region |

### 2.2 Admin approval path

Production publishing to the tenant's Teams app catalog requires:

1. **Teams admin approval** via Teams Admin Center →
   [Manage apps](https://admin.teams.microsoft.com/policies/manage-apps).
2. The app must pass Microsoft's validation if published to the public
   marketplace (not applicable for internal enterprise apps).
3. For internal distribution, the tenant admin publishes the app to the
   [organization app catalog](https://learn.microsoft.com/en-us/microsoftteams/teams-custom-app-policies-and-settings).

### 2.3 Licensing notes

- **Azure Bot Service:** Free tier (F0) supports dev/test (message rate limited
  to 10K messages/month). Production requires Standard tier (S1 — pay-per-use).
- **Foundry Agent Service:** Charged per agent session and model token consumption.
  Confirm available quota in the target Azure subscription and region before
  deploying.
- **Microsoft 365:** Users accessing the agent via Teams must have an active
  Microsoft 365 license that includes Teams.

---

## 3. Sideloading (developer / POC path)

Sideloading allows testing without admin approval and without publishing to the
organization catalog.

**Prerequisites:**
- The Teams Admin Center policy **"Allow users to upload custom apps"** is
  enabled for the user's group or globally.
- The Bot Service is deployed and accessible on a public HTTPS endpoint (or
  tunnelled via dev tools such as `devtunnel` or `ngrok` for local testing).

**Steps:**
1. Build the app package:
   ```
   # From repo root
   cd src/intake_teams/manifest
   # Substitute {{BOT_APP_ID}}, {{BOT_DOMAIN}}, etc. in manifest.json
   # Add color.png and outline.png to this directory
   Compress-Archive -Path manifest.json,color.png,outline.png -DestinationPath intake-agent.zip
   ```
2. In Teams desktop client: **Apps → Manage your apps → Upload an app →
   Upload a custom app** → select `intake-agent.zip`.
3. Install the app in a personal or team scope.

**Blocker check:** If the "Upload a custom app" option is absent, the tenant
admin has not enabled sideloading. Escalate to the tenant administrator.

---

## 4. Known blockers and risk register

| ID | Blocker | Severity | Mitigation |
|---|---|---|---|
| BLK-01 | Tenant sideloading policy disabled | High | Request admin to enable policy for dev group; use Foundry portal web chat as fallback |
| BLK-02 | Foundry Agent Service quota not allocated in target region | High | Raise Azure quota request before deployment |
| BLK-03 | Bot Service Terms of Service not accepted by a Teams admin | Medium | Coordinate with Teams admin to accept via Admin Center |
| BLK-04 | Entra app registration reply URL not set | Medium | Bicep module must include reply URL; confirmed in Tank's infra scope |
| BLK-05 | `devtunnel` / `ngrok` not permitted on corporate network | Low | Use Azure App Service or Container Apps for dev deployment instead of local tunnel |
| BLK-06 | Icon assets (color.png, outline.png) not yet created | Low | Placeholder PNGs required before app package can be built |

---

## 5. Safe fallback (POC demonstration without publishing)

Per **ADR-014**, the POC vertical slice is demonstrable without Teams
publishing. The fallback order is:

1. **Foundry portal web chat** — the agent runs in the Foundry portal and all
   card rendering/action parsing logic is exercised.
2. **Local HTTP adapter** — `intake_teams/demo` exercises all card loading and
   activity parsing logic with no Azure credentials.

The architecture does not change if publishing is delayed. The
`FoundryAdapter` in `src/intake_agent/adapter/foundry.py` becomes the
production channel when publishing succeeds; no other code changes.

---

## 6. Post-publishing validation checklist

Complete these checks after successfully sideloading or publishing the app:

- [ ] Bot responds to `start` command in personal chat scope.
- [ ] Adaptive Card (create.json) renders correctly in Teams desktop client.
- [ ] Adaptive Card (create.json) renders correctly in Teams mobile client.
- [ ] Action.Execute button triggers invoke activity (verb=capture_field).
- [ ] Auth header present on all Bot Service → agent requests (check logs).
- [ ] Keyboard navigation: all card inputs and buttons reachable via Tab.
- [ ] Screen reader (Narrator / JAWS): `label` and `speak` properties read correctly.
- [ ] Error card renders for a simulated VALIDATION_ERROR response.
- [ ] Status card renders after a successful field save.

---

## 7. Accessibility notes

All Adaptive Card templates in `src/intake_teams/cards/` include:

- `label` on every `Input.*` element (screen-reader announcement).
- `speak` property on each card (Cortana / voice narration).
- `errorMessage` on required inputs.
- `tooltip` on all action buttons.
- `isSubtle` / `spacing` for visual hierarchy without relying on color alone.
- `color: "Attention"` / `"Warning"` / `"Good"` paired with icon prefixes
  (❌ 🟡 ✅) so status is not conveyed by color alone (WCAG 1.4.1).

Teams Adaptive Card host config enforces a minimum contrast ratio of 4.5:1
(WCAG 1.4.3 AA) for the `default` theme. Verify high-contrast theme rendering
manually after first deployment.

---

## 8. References

- [Microsoft Foundry Agent Service documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/overview)
- [Bot Framework Teams channel](https://learn.microsoft.com/en-us/azure/bot-service/channel-connect-teams)
- [Teams app manifest schema v1.17](https://learn.microsoft.com/en-us/microsoftteams/platform/resources/schema/manifest-schema)
- [Adaptive Cards for Teams](https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/design-effective-cards)
- [Adaptive Cards schema explorer](https://adaptivecards.io/explorer/)
- [Action.Execute (Universal Actions)](https://learn.microsoft.com/en-us/adaptive-cards/authoring-cards/universal-action-model)
- [Bot Framework authentication](https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication)
- [WCAG 2.2 AA quick reference](https://www.w3.org/WAI/WCAG22/quickref/)
