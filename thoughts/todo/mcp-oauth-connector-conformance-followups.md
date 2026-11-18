# MCP OAuth connector conformance follow-ups

Items from the consumer's audit of the MCP endpoint against Anthropic's
connector requirements that are real but have no live failure behind them.
Each was checked against the tree at `2d5eaa4`, and again against `master`
at `ccc64b8` on 2026-11-17 (all still open). Anchors are function names,
not line numbers, which had drifted. None is scheduled. The items
with a live failure (public clients, PKCE binding, refresh rotation, error
codes) went into `thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`.

## OAuth server

- **Redirect URIs are exact-match only.** `validate_redirect_uri` is
  `redirect_uri in registered_uris` (`actingweb/oauth2_server/client_registry.py`).
  RFC 8252 §7.3 asks that native clients registering a loopback URI
  (`http://127.0.0.1:<port>/...`, `http://[::1]:<port>/...`) be matched
  ignoring the port. Decide whether to apply that only to loopback hosts
  (the RFC's scope) and never to `localhost` by name.
- **No RFC 8707 `resource` / audience binding.** Neither the authorize params
  (`handlers/oauth2_endpoints.py`, `_handle_authorization_request`) nor the
  token params (`_handle_token_request`)
  read `resource`, and no token record carries an audience
  (`oauth2_server/token_manager.py`, `_create_access_token`). Every ActingWeb access token is
  already bound to one actor and one client; the missing piece is refusing a
  token minted for one resource server at another, which only matters once a
  deployment fronts more than one resource with one authorization server.
- **No Client ID Metadata Document support.**
  `client_id_metadata_document_supported` is not advertised; Claude prefers
  CIMD over DCR for high-traffic servers. Needs an HTTPS fetch of the
  client's metadata URL with caching, and interacts with the DCR retention
  todo (`dcr-registrations-and-client-trust-rows-never-expire.md`), since
  CIMD clients would not create registrations at all.
  **2026-09-28, rc1 live pass (consumer):** claude.ai's new "Add custom
  connector" dialog now preselects "Use Claude's published identity" (CIMD)
  as the recommended OAuth-client option. Against rc1, which does not
  advertise CIMD, it fell back to DCR and worked (confidential,
  `client_secret_post`), so nothing is broken; supporting CIMD would put
  claude.ai on its recommended path and stop it adding a registration per
  connect.
- **A confidential client that sends no PKCE challenge gets an unbound
  code.** Since 3.15 the built-in authorize pages bind a challenge when one
  is sent and require one from a public client, but a confidential client
  may still omit it (`oauth2_server/oauth2_server.py`, the PKCE block in
  `handle_authorization_request`). Its code is guarded by its client secret,
  as before. Requiring PKCE for every client (OAuth 2.1) would break any
  confidential client that does not send one; check the connectors first.
- **`/.well-known/openid-configuration` answers 404.** The integrations
  register `oauth-authorization-server` and `oauth-protected-resource[/mcp]`
  only (the `.well-known` routes in `interface/integrations/flask_integration.py`
  and `fastapi_integration.py`). ChatGPT probes it several times per
  connect and moves on. Either serve the same document there or leave it and
  say so in `docs/guides/oauth2-setup.rst`.

## MCP handler

- **`resources/templates/list` is method-not-found** (`handlers/mcp.py`, the method dispatch in `post`)
  while `resources/list` returns a templated URI
  (`actingweb://activity/recent?days={days}` in the consumer). Either
  implement the method or return templates only from it.
- **Shared registrations flip the Connections card name.** claude.ai and
  Claude Code on one account use one client id, and the ChatGPT desktop
  app's Codex uses the Codex CLI's. `_update_trust_with_client_info`
  (`handlers/mcp.py`) skips the write only when nothing changed,
  so two clients alternating on one trust row rewrite `client_name` each
  time. Keep the first name seen, or record every name seen. (3.15 closed
  the cross-user variant, where an unauthenticated `initialize` named
  another user's row, and sanitises the name; last-writer-wins within one
  user's row is what remains.)
- **No post-authentication hook carries the actor to app code.** The
  consumer's middleware validates the bearer a second time
  (`handlers/mcp.py`, `authenticate_and_get_actor_cached`, is where the
  library does it) because nothing
  hands the resolved actor to the app before dispatch. A hook there would
  also let `actingweb_mcp` drop its `require_mcp_auth_for_init` sniffing
  (see `mcp-2026-07-28-dual-era-support.md`, "Downstream consumers to
  notify").

## Not follow-ups

Two audit observations are recorded here so they are not re-filed:

- `tools/list` fails open when the permission evaluator itself raises
  (`handlers/mcp.py`, the `tools/list` handler). Deliberate and documented
  (`CHANGELOG.rst`, v3.13.0, "Missing trust is now fail-closed"): a permission-subsystem outage must not lock out
  every client; per-call checks are fail-closed since 3.14.4, so a listed
  tool is still refused at call time.
- `MCP-Protocol-Version: 2026-07-28` is rejected with 400 once per connect.
  That is the legacy-server handshake dual-era clients rely on; the dual-era
  todo's "Trap" section says why the `-32600` must stay.

**Provenance.** Filed 2026-09-25 from
`thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`
(report 3, items 6–8 and the context list). Reported by the `actingweb_mcp`
project on 2026-09-21 out of its
`thoughts/plans/2026-09-17-claude-connector-directory-submission.md`, from
live sessions with claude.ai, Claude Code, Codex and ChatGPT against
`https://ai.actingweb.io` and a local server on 3.14.7.
