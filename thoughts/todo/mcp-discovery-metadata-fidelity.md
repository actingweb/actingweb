# MCP discovery metadata reports hardcoded and inconsistent values

Found during review of the v3.14.2 OAuth2 discovery fixes (PR #138). None of
these caused the reported failure — that was the missing `resource_metadata`
pointer and the `GET /mcp` 200, both fixed in 3.14.2 — but all four are in the
metadata surface those fixes made load-bearing, and a client that reads it now
reads these too.

Verified at `6285a3e`.

## 1. `/mcp/info` reports hardcoded demo values

`_create_mcp_info_response()` is duplicated in both integrations
(`actingweb/interface/integrations/fastapi_integration.py:2656`,
`actingweb/interface/integrations/flask_integration.py:1790`) and returns, for
every application:

```python
"supported_features": ["tools", "prompts"],
"tools_count": 4,
"prompts_count": 3,
"actor_lookup": "email_based",
"description": "ActingWeb MCP Demo - AI can interact with actors through MCP protocol using OAuth2",
```

The counts and the description are literals — they do not consult the hook
registry, so an app with 40 tools advertises 4, and every ActingWeb deployment
describes itself as the demo.

This is not an obscure endpoint: it is what `resource_documentation` points at
in **both** protected-resource documents
(`actingweb/handlers/oauth2_endpoints.py:763,788`) and what
`service_documentation` points at in the authorization-server metadata
(`actingweb/oauth2_server/oauth2_server.py:638`), so a conformant client
following the discovery chain lands on it.

Fix is either to derive the counts from the registry or to drop the fields —
dropping is probably right, since nothing in the MCP spec asks for them and a
count is stale the moment a hook is registered conditionally. The duplication
between the two integrations should collapse into one shared builder either
way; see the same pattern in [[ai-agent-discoverability-followups]].

## 2. The same server reports two different names

- `MCPHandler._handle_initialize` → `serverInfo.name` uses
  `config.mcp_server_name` (`actingweb/handlers/mcp.py:847`), which
  `with_mcp(server_name=...)` sets.
- `MCPHandler.get()` → `server_name` is the literal `"actingweb-mcp"`
  (`actingweb/handlers/mcp.py:642`), ignoring the config.

So an app configured `with_mcp(server_name="emm")` announces `emm` in the
handshake and `actingweb-mcp` on `GET /mcp`. Only reachable by an
authenticated GET since 3.14.2, which is why it is not urgent — but it is a
one-line fix and the two should not disagree.

## 3. Dead authorization-server metadata with a divergent scope list

`BaseActingWebIntegration.get_oauth_discovery_metadata()`
(`actingweb/interface/integrations/base_integration.py:255`) advertises
`scopes_supported: ["openid", "profile", "email", "mcp"]` — neither the live
list (`["mcp", "offline_access"]`, `oauth2_server.py:625`) nor a subset of it.

It is genuinely dead: both integrations route
`/.well-known/oauth-authorization-server` through `OAuth2EndpointsHandler`, and
the only callers are `tests/test_base_integration.py:259` and
`tests/test_flask_integration.py:52`. Delete it and its two tests. Left out of
3.14.2 deliberately — deleting a public-looking static method is not a patch
release change.

## 4. `fqdn` is interpolated unquoted into `WWW-Authenticate`

`mcp_www_authenticate()` (`actingweb/handlers/mcp.py:412`) builds
`resource_metadata="{base_url}/..."` and `authorization_uri="{base_url}/..."`
with no escaping. `base_url` comes from `config.proto`/`config.fqdn`, which is
operator configuration rather than request input, so this is not exploitable —
but an `fqdn` containing a `"` would produce a header no client can parse, and
the failure would look like the discovery bug 3.14.2 just fixed. Raised in the
PR #138 review as non-blocking; pre-dates that PR (the old hand-rolled
`authorization_uri` had the same property).

Cheapest fix is to reject a `"` in `fqdn` at `Config` construction rather than
to escape at every use site.

## Not worth doing

The `try`/`except` around the challenge in `MCPHandler.error_response()`
(`actingweb/handlers/mcp.py:2675`) is close to dead — `mcp_www_authenticate()`
is a pure f-string builder and cannot raise. It is not *quite* dead
(`self.config.proto`/`.fqdn` access and the `self.response` write are inside
it), and it guards a 401 path where degrading to a plain challenge beats
raising. Leave it.
