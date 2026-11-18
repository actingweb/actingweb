# Spec: MCP server

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-17 by thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.md
**ID prefix:** MCP

## Summary

The library serves an actor's tools, resources and prompts over MCP at
`/mcp`, with OAuth2 discovery documents. This partial spec covers only the
capabilities it advertises.

## Capabilities

- **MCP-1** — When `initialize` advertises tools, resources or prompts, each
  says `listChanged: false`: the server sends no list-change notification.
  [plan+test] `tests/test_mcp_server_name.py::test_initialize_advertises_no_list_change_notifications`; wire rows `WG16`, `WG17` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-9)

## Discovery

- **MCP-2** — When the protected-resource document for `/mcp` is read, its
  `tools`, `prompts` and `resources` flags are true exactly for what the
  application registered. [plan+test] `tests/test_mcp_auth_challenge.py::test_the_protected_resource_document_reports_what_is_registered` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-10)

## Untested

- None of the above.
