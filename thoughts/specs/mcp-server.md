# Spec: MCP server

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-18 by thoughts/plans/2026-11-15-3-16-release-validation.md
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

## Transport and tool listing

- **MCP-3** — When an authenticated client sends `GET /mcp` with `Accept:
  text/event-stream`, the server answers 405 with `Allow: POST` (it offers
  no server-to-client stream); a plain authenticated `GET /mcp` still gets
  the server's document. [plan+test]
  `tests/integration/test_oauth2_flows.py::TestMCPWithIssuedToken::test_an_authenticated_stream_opener_gets_405` (plans/2026-11-15-3-16-release-validation.md)
- **MCP-4** — When a tool is declared without `input_schema`, `tools/list`
  lists it with `inputSchema: {"type": "object", "properties": {}}`; a
  declared schema is listed as declared. [plan+test]
  `tests/test_mcp_permissions.py::TestEveryToolHasAnInputSchema` (plans/2026-11-15-3-16-release-validation.md)

## Untested

- None of the above.
