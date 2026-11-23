# Spec: MCP server

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-23 by thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md
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


## Tool calls

- **MCP-12** — When a tool hook raises a store fault, `tools/call` answers
  HTTP 200 with a result whose `isError` is true and whose text is fixed by
  the fault's class (retryable, stored, permanent, conflict); the fault's
  text is never in the response. A token-store fault and a single-use
  consume that could not be confirmed take the retryable text. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_a_failing_tool_is_a_tool_result` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-1 to AC-4, AC-25)
- **MCP-13** — When a tool hook raises any other exception, the result is
  `isError: true` with a fixed text; the exception's text goes to the log.
  [plan+test] `tests/test_mcp_tool_failure_results.py::test_a_failing_tool_is_a_tool_result` (ids `other`, `other_base`, `newer_format`) (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-5, AC-25)
- **MCP-14** — When a tool hook raises `ToolError`, its message is the text
  of the `isError` result. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_a_tool_error_reaches_the_model_as_written` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-23)
- **MCP-15** — When an action hook raises `ToolError` on the REST
  `/actions` route, the answer is 400 with `{"error": "<message>"}` and no
  later hook runs for the call. [plan+test]
  `tests/test_tool_error_on_actions_route.py::test_the_actions_route_answers_400_with_the_message`, `::test_a_tool_error_leaves_the_hook_runner` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-30)
- **MCP-16** — A `ToolError` raised for a store fault is sent as written and
  still logs the fault, on the MCP and the REST route, in a line that starts
  `Tool '<name>' failed with a store fault` or `Action '<name>' failed with
  a store fault`: ERROR for an outage, WARNING for a deletion wait or a
  creator conflict. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_a_tool_error_raised_for_a_store_fault_still_alarms`, `::test_a_tool_error_over_an_expected_fault_does_not_alarm`, `tests/test_tool_error_on_actions_route.py::test_a_tool_error_for_a_store_fault_still_alarms_over_rest` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-31)
- **MCP-17** — Each tool failure writes one log line that names the tool
  and what was raised, and no HTTP status. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_each_failure_is_logged_once_with_its_cause` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-8)
- **MCP-18** — A tool result that cannot be formatted answers JSON-RPC
  `-32603` `Internal error`, not a tool failure. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_a_result_that_cannot_be_formatted_is_not_a_tool_failure` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-32)
- **MCP-19** — A failing `prompts/get` or `resources/read` hook, and an
  unexpected handler error, answer JSON-RPC `-32603` with a fixed message
  and no exception text; a hook that wrapped a store fault answers the
  fault's status. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_a_failing_prompt_or_resource_hook_answers_fixed_text` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-24)
- **MCP-20** — A store fault outside the hook call (authentication, the
  permission evaluation, every other method) answers a JSON-RPC error with
  the HTTP status of the shared fault mapping. [plan+test]
  `tests/test_mcp_tool_failure_results.py::test_a_fault_in_the_permission_check_keeps_the_protocol_error`, `::test_a_fault_in_another_method_keeps_the_protocol_error` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-6)

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
- **MCP-21** — `actingweb.mcp.is_token_cached(token, config)` answers
  whether this process holds a fresh cache entry for the token under this
  `Config`; it reads no store, changes no entry and grants nothing.
  [plan+test] `tests/test_mcp_token_cache_query.py` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-19, AC-20)
- **MCP-22** — `actingweb.mcp.cached_token_actor_id(token, config)` answers
  by the same rule the actor a fresh entry belongs to, or `None` for a miss
  or an entry with no usable actor id; it reads no store and changes no
  entry. [plan+test]
  `tests/test_mcp_token_cache_query.py::TestCachedTokenActorId` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, iteration 14)

## Decisions in force

- **MCP-D4** — The fixed tool-failure texts are read by models and by
  consumers' instructions to them; changing one is a consumer-visible
  change. (plans/2026-11-23-emm-4-0-rc2-production-observations.md)
- **MCP-D5** — The token and trust caches stay internal; the two queries
  are the only supported view of them, and the actor id is the only field
  of an entry they answer. (plans/2026-11-23-emm-4-0-rc2-production-observations.md)

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
