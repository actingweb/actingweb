# Specs

How each capability of the library behaves today, for this repository's
developers and maintainers. Format and rules:
`~/.claude/shared/conventions.md` ("Living specs"). This repository's
sources: `.claude/workflow/create_spec.md`.

Ten capabilities have a `partial` spec, created from the Spec Deltas of
`plans/2026-11-17-3-16-pre-rc1-fixes.md`,
`plans/2026-11-19-emm-4-0-adoption-findings.md` and
`plans/2026-11-21-trust-request-answer-secret.md`; the capability map has not been
proposed. `/create_spec` with no argument proposes the map and fills the
table below; `/create_spec <capability>` then writes or completes one spec at
a time. `/create_plan`
offers it when a plan touches a capability with no spec.

| Capability | File | Prefix | Status | Reviewed |
| --- | --- | --- | --- | --- |
| Trust permissions | [trust-permissions.md](trust-permissions.md) | TPM | partial | 2026-11-17 |
| OAuth client registration | [oauth-client-registration.md](oauth-client-registration.md) | OCR | partial | 2026-11-17 |
| MCP server | [mcp-server.md](mcp-server.md) | MCP | partial | 2026-11-17 |
| Subscriptions | [subscriptions.md](subscriptions.md) | SUB | partial | 2026-11-17 |
| Web UI | [web-ui.md](web-ui.md) | WUI | partial | 2026-11-17 |
| Operator commands | [operator-commands.md](operator-commands.md) | OPC | partial | 2026-11-19 |
| Start-up readiness | [startup-readiness.md](startup-readiness.md) | SRD | partial | 2026-11-19 |
| Actor creation | [actor-creation.md](actor-creation.md) | ACR | partial | 2026-11-19 |
| Property lists | [property-lists.md](property-lists.md) | PLS | partial | 2026-11-19 |
| Trust establishment | [trust-establishment.md](trust-establishment.md) | TES | partial | 2026-11-21 |

Until a capability has a spec, its behaviour is recorded where it was before:
`docs/` (what a consumer is told), `docs/protocol/actingweb-spec.rst` (the
protocol), the wire recordings under `tests/integration/wire/` (what two
applications exchange), and the plans and verifications that changed it.
Plans written up to and including `2026-11-16-3-16-pre-validation-fixes`
carry no mergeable Spec Delta.
