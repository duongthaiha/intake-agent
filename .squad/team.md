# Squad Team

> intake-agent — Python-hosted Azure intake agent published through Teams/Microsoft Foundry

## Coordinator

| Name | Role | Notes |
|------|------|-------|
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. |

## Members

| Name | Role | Charter | Status |
|------|------|---------|--------|
| Morpheus | Lead Architect | [charter](agents/morpheus/charter.md) | ✅ Active |
| Trinity | AI/Backend Engineer | [charter](agents/trinity/charter.md) | ✅ Active |
| Neo | Teams/Experience Engineer | [charter](agents/neo/charter.md) | ✅ Active |
| Tank | Azure Platform & Security Engineer | [charter](agents/tank/charter.md) | ✅ Active |
| Switch | Quality Engineer | [charter](agents/switch/charter.md) | ✅ Active |
| Scribe | Session Logger | [charter](agents/scribe/charter.md) | ✅ Active |
| Ralph | Work Monitor | [charter](agents/ralph/charter.md) | ✅ Active |
| Rai | RAI Reviewer | [charter](agents/Rai/charter.md) | ✅ Active |
| Fact Checker | Verification & Devil's Advocate | [charter](agents/fact-checker/charter.md) | ✅ Active |

## Coding Agent

<!-- copilot-auto-assign: false -->

| Name | Role | Charter | Status |
|------|------|---------|--------|
| @copilot | Coding Agent | — | 🤖 Coding Agent |

### Capabilities

**🟢 Good fit — auto-route when enabled:**
- Bug fixes with clear reproduction steps
- Test coverage (adding missing tests, fixing flaky tests)
- Lint/format fixes and code style cleanup
- Dependency updates and version bumps
- Small isolated features with clear specs
- Boilerplate/scaffolding generation
- Documentation fixes and README updates

**🟡 Needs review — route to @copilot but flag for squad member PR review:**
- Medium features with clear specs and acceptance criteria
- Refactoring with existing test coverage
- API endpoint additions following established patterns
- Migration scripts with well-defined schemas

**🔴 Not suitable — route to squad member instead:**
- Architecture decisions and system design
- Multi-system integration requiring coordination
- Ambiguous requirements needing clarification
- Security-critical changes (auth, encryption, access control)
- Performance-critical paths requiring benchmarking
- Changes requiring cross-team discussion

## Project Context

- **Project:** intake-agent
- **Description:** Python-hosted Azure intake agent published through Teams/Microsoft Foundry, with structured requirements capture, gap analysis, human review, Cosmos DB/blob persistence, downstream automation, evaluation, private networking, Bicep, azd, and deployment verification.
- **User:** Ha Duong
- **Created:** 2026-08-07
