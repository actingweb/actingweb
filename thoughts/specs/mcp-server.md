# Spec: MCP server

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-21 by thoughts/plans/2026-11-21-trust-request-answer-secret.md
**ID prefix:** MCP

## Summary

The library serves an actor's tools, resources and prompts over MCP at
`/mcp`, with OAuth2 discovery documents. This partial spec covers only the
capabilities it advertises.

## Capabilities

- **MCP-1** — When `initialize` advertises tools, resources or prompts, each
  says `listChanged: false`: the server sends no list-change notification.
  [plan+test] `tests/test_mcp_server_name.py::test_initialize_advertises_no_list_change_notifications`; wire rows `WG16`, `WG17` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-9)

- **MCP-5** — When `resources/templates/list` is called, it returns the
  templated resources under the permissions `resources/list` applies;
  `resources/list` still lists them too. [plan+test]
  `tests/test_mcp_resource_templates.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-33)
- **MCP-6** — When a trust row has a client name from an authenticated
  request, a later name does not replace it. [plan+test]
  `tests/test_mcp_client_info_cache.py` (`test_a_second_name_does_not_replace_the_first`, `test_an_unauthenticated_seed_is_not_a_first_name`) (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-34; iteration 8)

## Discovery

- **MCP-2** — When the protected-resource document for `/mcp` is read, its
  `tools`, `prompts` and `resources` flags are true exactly for what the
  application registered. [plan+test] `tests/test_mcp_auth_challenge.py::test_the_protected_resource_document_reports_what_is_registered` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-10)

- **MCP-7** — When `/.well-known/openid-configuration` is requested, the
  authorisation-server document is served, on both integrations.
  [plan+test] `tests/test_flask_well_known.py::test_openid_configuration`,
  `tests/integration/test_oauth2_flows.py::test_openid_configuration_serves_the_server_document` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-32)

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

- **MCP-8** — When `require_auth_for_initialize` is on, an unauthenticated
  `initialize` is challenged with 401 (503 on a token-store fault); off, it
  is answered. [plan+test] `tests/test_mcp_auth_challenge.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-30, AC-31)


## Handshake

- **MCP-9** — `initialize` announces `serverInfo.version` from
  `with_mcp(server_version=…)`, or the library's version when it is not set;
  `with_app_version()` does not change it. An empty or non-string value
  raises `ValueError` at configuration. [plan+test]
  `tests/test_mcp_server_name.py::TestServerVersionInInitialize` (plans/2026-11-21-trust-request-answer-secret.md, AC-16, AC-17, AC-33)

## Authorization

- **MCP-10** — A client whose connection was deleted gets a new code only
  after the user acts on an ActingWeb page, and the reconnect starts from a
  fresh grant (the level chosen then, no override from before). [plan+test]
  `tests/integration/test_oauth2_trust_binding.py::test_a_disconnected_client_needs_the_user_again`,
  `::test_a_reconnect_starts_from_a_fresh_grant` (AC-18, AC-19)
- **MCP-11** — A disconnect removes the actor's unexchanged authorization
  codes for the client with its tokens, each removal confirmed (a fault
  fails the disconnect and keeps the trust row); a code from before the
  disconnect answers `invalid_grant`, also after a reconnect; an exchange in
  flight during the disconnect leaves no working token; a refresh token from
  before the disconnect stays dead after a reconnect. [plan+test]
  `tests/integration/test_oauth2_trust_binding.py::test_a_code_from_before_the_disconnect_is_refused`,
  `::test_a_code_from_before_the_disconnect_is_refused_after_a_reconnect`,
  `::test_an_old_refresh_token_stays_dead_after_a_reconnect`,
  `::test_a_code_that_cannot_be_removed_keeps_the_row`,
  `tests/test_oauth2_disconnect_sweeps_codes.py` (AC-20, AC-22, AC-34, AC-35, AC-36)
## Decisions in force

- **MCP-D1** — Templated resources stay in `resources/list` until the
  connectors are seen calling `resources/templates/list`. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **MCP-D2** — Calling `with_mcp()` again changes only the options it names.
  [test] `tests/test_actingweb_app.py::test_a_second_with_mcp_keeps_earlier_options` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-51)
- **MCP-D3** — The disconnect sweeps codes; the code exchange and the
  refresh grant do not look up a trust. (plans/2026-11-21-trust-request-answer-secret.md, owner 2026-11-21)

## Untested

- MCP-11: a code an authorization issues after the sweep's code snapshot and
  before the trust row goes is not swept; the user acted on an ActingWeb page
  for it.
