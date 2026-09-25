# Research: three inbound reports — MCP OAuth connector gaps, `AwProxy` DEBUG bodies, trust-list credentials

**Date:** 2026-09-25
**Branch:** master
**Commit:** 2d5eaa4 (the merge of PR #146; tag `v3.14.7` is on 45b2cf6, the release commit inside that PR, and the code paths cited here are identical at both)

## Research Question

Triage of three reports, all filed from the Emm AI consumer project
(`actingweb_mcp`) and all read against tag `v3.14.7`:

1. `thoughts/inbound/aw-proxy-debug-logging.md`, filed 2026-09-23 out of a
   logging-privacy fix in that repo's `execute_method` tool wrapper. Claim:
   `AwProxy.create_resource` and `create_resource_async` log the full
   JSON-serialised remote-method params at DEBUG.
2. `thoughts/inbound/mcp-oauth-claude-connector-gaps.md`, filed 2026-09-21 out
   of that repo's connector-alignment work
   (`thoughts/plans/2026-09-17-claude-connector-directory-submission.md`),
   which audited the MCP endpoint against Anthropic's connector requirements
   and ran live sessions against `https://ai.actingweb.io` and a local server
   with claude.ai, Claude Code, Codex and ChatGPT. Eight numbered items plus
   a list of context observations.
3. `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md`, found
   2026-09-15 by actingweb_mcp todo #59 (its persisted bootstrap snapshot
   carried trust secrets). Filed straight into `todo/` but not yet checked
   against the tree, so treated here as inbound. Claim: `GET /{actor_id}/trust`
   returns each relationship's `secret` and `verification_token`.

Does each claim hold against the tree? What did checking change — cause,
blast radius, or the fix the codebase already supports? What ships in the
next minor, and what is filed as a todo?

## Summary

**Every code-level claim holds.** Checking the tree changed the framing of
five of them, in each case towards a larger or differently-shaped fix:

- The `AwProxy` leak is **four** log sites, not two: create and change, sync
  and async.
- The trust-list strip is a **protocol-spec example change**, not only a
  response-shape change, and it must be **list-only at the handler**: the
  peer verification flow reads `verification_token` from the per-relationship
  GET, and the spec says the shared secret SHOULD be readable there.
- Honouring `token_endpoint_auth_method: none` at registration alone would
  **not** fix the Codex refresh failure: the token handler turns a missing
  `client_secret` into an empty string, so the registry always takes the
  confidential branch, and the refresh grant has no public-client fallback
  (the authorization-code grant has one).
- PKCE is **never bound on any library path** of the MCP authorization-code
  flow, not only the provider sign-in path. The "password path" the report
  saw binding it is the consumer's own `api/oauth_password.py`.
- The library **already has** the refresh-token rotation design the MCP token
  manager lacks: `oauth_session.py`'s chain ids, atomic consume and reuse
  detection, shipped for SPA tokens in 3.11. The MCP `TokenManager` predates
  it and also logs a WARNING on every refresh from a no-op revoke helper.

One context item is a documented deliberate decision rather than a finding
(`tools/list` fails open on evaluator error, `CHANGELOG.rst:1102`). One is a
live sighting that belongs on an existing todo's trigger list (Claude Code CLI
2.1.280 retrying `MCP-Protocol-Version: 2026-07-28`).

Owner decisions taken during the review on 2026-09-25: strip credentials from
the list route only; MCP refresh-token rotation ships in this release; the
`plain` PKCE method stays accepted at exchange. Release: **3.15.0**, a minor,
because a documented response field and a token-endpoint contract change.

Plan: `thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`.

## Report 1: `AwProxy` logs full request bodies at DEBUG

### Claim

`create_resource` (`aw_proxy.py:247`) and `create_resource_async` (`:540`) log
`"...with data(" + str(data) + ")"` where `data` is `json.dumps(params)`.

### Verified

Both lines exist as described. Two more do the same thing:

| Site | Method | Line |
| --- | --- | --- |
| `actingweb/aw_proxy.py:247` | `create_resource` (POST) | `"Creating trust peer resource at (" + url + ") with data(" + str(data) + ")"` |
| `actingweb/aw_proxy.py:306` | `change_resource` (PUT) | `"Changing trust peer resource at (" + url + ") with data(" + str(data) + ")"` |
| `actingweb/aw_proxy.py:542` | `create_resource_async` | same text, async |
| `actingweb/aw_proxy.py:646` | `change_resource_async` | same text, async |

`data` is the serialised body of whatever remote method, property write or
action the caller invokes on a peer, so it carries user- and agent-supplied
values verbatim. The consumer's own key-only logging around its call into this
library does not help because the leak is one layer below it.

The library's only existing redaction machinery is `_redact_token_response`
in `actingweb/oauth2.py`, with tests in `tests/test_logging_redaction.py`
(`SENSITIVE = ["client_assertion", "assertion", "id_token",
"client_secret"]`). Nothing covers `aw_proxy`. `docs/reference/security.rst`
does not warn about DEBUG in production for this logger; `CLAUDE.md` lists
`actingweb.aw_proxy` among "performance-critical loggers (use WARNING+ in
production)", which is a performance note, not a privacy one.

### Delta

Four sites, not two. Fix shape: replace the value with a summary (key names
and serialised byte length), no opt-in. A consumer that wants bodies in a log
can log them at its own call site, where it also knows what to redact.

## Report 2: `GET /{actor_id}/trust` returns peer credentials

### Claim

The list `get` returns `json.dumps(myself.get_trust_relationships(...))`,
and each row is the db layer's full trust dict including `secret` and
`verification_token`.

### Verified

- `actingweb/handlers/trust.py:68-74`: `TrustHandler.get` serialises the rows
  from `Actor.get_trust_relationships()` unchanged.
- Both backends return `secret` and `verification_token` in every row:
  `actingweb/db/dynamodb/trust.py:455,460` (`fetch`) and
  `actingweb/db/postgresql/trust.py:718` (`fetch`, the same SELECT list as
  `get`).
- The www trust page (`handlers/www.py:462-586`) passes the same rows to
  `aw-actor-www-trust.html`, which renders neither field (grep is empty).
- `interface/trust_manager.py:129` `TrustRelationship.to_dict()` returns the
  raw row, in-process, to SDK code. Not a wire exposure.

### What the check changed

**The protocol spec documents the secret in the list response.**
`docs/protocol/actingweb-spec.rst:1499-1520` is the `GET .../trust/friend`
example, and both rows carry `"secret"`. The normative text for the list
(`:1486-1493`) only says creator and admin MUST be able to retrieve the
relationships as JSON; it does not name the fields. The normative text for
the **per-relationship** GET (`:1754-1758`) says the shared secret SHOULD be
readable to creator and admin "to support versioning/migration of actors".
So the list can drop the fields and stay within the spec; the per-relationship
route cannot.

**The strip must be list-only, at the handler, not at the db layer.**

- Peer verification reads `verification_token` from the per-relationship GET:
  `actingweb/actor.py:1236-1266` GETs `<peer>/trust/<type>/<me>` with the
  shared secret as Bearer and compares `data.get("verification_token")`.
- `auth.py:277,601` and every `aw_proxy.py` call site read `trust["secret"]`
  from the same row dicts.
- `tests/integration/test_trust_lifecycle.py:98` asserts the creator sees
  `"secret"` on the per-relationship GET; `test_trust_flow.py:111-130` reads
  `secret` from the POST-create response. Neither reads it from the list.
- `tests/integration/test_trust_reciprocal_approval.py:23` reads the list and
  uses only `peerid` and the approval flags.
- The consumer's bootstrap aggregate already drops both fields
  (`actingweb_mcp/api/bootstrap.py:85-100`) and its SPA never reads them; its
  `useTrust.ts` still calls the framework list route, which is the remaining
  exposure.

**Both routes are behind the same authorisation** (creator, admin, or the
peer for its own row), so this is an at-rest exposure in the owner's browser,
not a cross-actor leak. What it buys: a browser session or SPA cache no longer
holds every peer's bearer credential.

### Delta

List-only strip of `secret` and `verification_token`, the spec example
updated, a sentence added to the spec's "Relationships and their data" saying
the list omits credentials and the per-relationship GET carries them. A
documented response field changes, which is why this is a minor.

## Report 3: MCP OAuth gaps from the connector audit

Line references below were re-checked at `2d5eaa4`; the report's are at the
same tag and match.

### 1. DCR ignores `token_endpoint_auth_method: none` — confirmed, fix is wider

- `actingweb/oauth2_server/client_registry.py:68` hardcodes
  `"token_endpoint_auth_method": "client_secret_post"` and `:92` always
  returns a `client_secret`. The metadata document advertises `none`
  (`oauth2_server/oauth2_server.py:632-636`).
- The registration handler (`handlers/oauth2_endpoints.py:146-192`) passes
  the parsed body through; the registry reads `client_name`, `redirect_uris`
  and `trust_type` only.

What the check changed:

- `handlers/oauth2_endpoints.py:332` sets
  `params["client_secret"] = form_data.get("client_secret", [""])[0]`: a
  request that omits the secret yields `""`, not `None`.
  `MCPClientRegistry.validate_client` (`client_registry.py:127-131`) branches
  on `client_secret is not None`, so `""` is compared against the stored
  secret and fails.
- The authorization-code grant recovers from that: on failure it re-validates
  without a secret and accepts the client if its method is `none`
  (`oauth2_server.py:489-500`). That is why Codex's code exchange works today
  even though it was issued a secret it did not ask for.
- The refresh grant has **no** such fallback (`oauth2_server.py:537-540`):
  `validate_client(client_id, "")` fails and the grant answers
  `invalid_client`. That is the Codex refresh failure the report saw live.
- So the fix is three parts: honour `none` at registration (and do not issue a
  secret), normalise an absent secret to `None` in the token handler, and give
  the refresh grant the public-client branch the auth-code grant already has.
  A public client must still present a refresh token bound to its `client_id`
  (`token_manager.py:277-279` already checks the match), and PKCE is then the
  only proof on the authorization-code path, which is why this ships with
  item 3.
- Live claims (Codex sends the secret as an `Authorization` header on the
  code exchange and omits it on refresh; ChatGPT sends it on both) are
  consistent with the code but were not reproduced here.

### 2. `/oauth/token` collapses `invalid_grant` to `invalid_request` — confirmed

`_handle_token_request` maps the server's error to a status
(`handlers/oauth2_endpoints.py:363-388`) and then calls
`self.error_response(status, f"{error}: {description}")`, and
`error_response` (`:1022-1035`) rebuilds the body from the status alone:
400 → `invalid_request`, 401 → `invalid_client`, else `server_error`. So
`invalid_grant`, `unsupported_grant_type` and `unsupported_response_type`
all reach the client as `invalid_request` with the real code in the
description string. RFC 6749 §5.2 requires `invalid_grant` for a dead
refresh token. One-line fix: return the server's code, keep the status map.

### 3. PKCE not bound on the provider sign-in path — confirmed, worse than filed

- GET and POST `/oauth/authorize` build `params` without `code_challenge` or
  `code_challenge_method` (`handlers/oauth2_endpoints.py:212-246`).
- `ActingWebOAuth2Server.handle_authorization_request` reads them from
  `params` (`oauth2_server.py:135-136`) and, on POST, passes them into
  `create_mcp_state` (`:203-212`) — but they are always `None` because the
  handler never read them.
- The show-form response (`:178-185`) does not echo them, so the template's
  hidden inputs (`templates/aw-oauth-authorization-form.html:15-16`) render
  empty and the form POST cannot carry them back either.
- The provider-button `mcp_context` built at
  `handlers/oauth2_endpoints.py:652-661` has no challenge fields at all.
- The callback (`oauth2_server.py:321-322`, `:412-419`) and
  `TokenManager.create_authorization_code` (`token_manager.py:60-110`)
  already carry the challenge into the stored code, and
  `exchange_authorization_code` validates it when present
  (`:165-176`, `_validate_pkce` at `:941-988`).

So the storage and validation halves exist; the request-reading half is
missing on every library path. The report's "password path binds it" refers
to the consumer's own `api/oauth_password.py` (its comment at line 258 says
`/oauth/authorize does not thread code_challenge into the rendered` form),
which calls `create_authorization_code` directly with the challenge. No
library path does.

Also confirmed: `plain` is accepted at authorize (`oauth2_server.py:163`)
and at exchange (`token_manager.py:969-970`) while the metadata advertises
`S256` only (`oauth2_server.py:637`). Owner decision: the library's own
authorize path binds `S256` only; exchange keeps accepting `plain` so the
consumer's password path (which defaults to `plain` when the method is
absent, per RFC 7636) keeps working.

### 4. Refresh token not rotated, old access token not revoked — confirmed, reuse available

- `TokenManager.refresh_access_token` (`token_manager.py:252-303`) returns the
  same refresh token (`:302`), never marks it used, and re-stores it with the
  new `access_token_id`.
- The "revoke old access token" step (`:283-286`) calls
  `_revoke_access_token_by_id` (`:894-919`), which does nothing except log a
  WARNING — "requires full search - not implemented for efficiency" — on
  **every refresh**. Its sibling `_revoke_refresh_tokens_for_access_token`
  (`:921-939`) is the same no-op, called from `revoke_token` (`:328-330`).
- Access tokens are keyed by token string with a global index
  (`_store_access_token`, `:617-651`); the refresh record holds only the
  hex `token_id` (`_create_refresh_token`, `:403-419`), which nothing indexes.
  That is the structural reason the revoke is a no-op.

What the check changed: the design already exists in the library.
`actingweb/oauth_session.py` implements chain ids
(`create_refresh_token`, `:552-600`), atomic consume via
`conditional_update_attr` (`try_mark_refresh_token_used`, `:682-773`), a
bounded reuse window (`SPA_REFRESH_TOKEN_REUSE_WINDOW`), grace-window full
rotation and token-family revocation (`handlers/oauth2_spa.py:690-727`,
`revoke_token_chain`), all shipped in 3.11 and tested in
`tests/test_oauth2_spa_refresh_rotation.py`. The MCP token manager predates it.
Two differences make the MCP port cheaper than the SPA original: MCP tokens
live in **per-actor** buckets (`self.tokens_bucket`, `self.refresh_tokens_bucket`),
so a chain revoke is a scan of one actor's tokens, the pattern
`revoke_client_tokens` (`:1046-1117`) already uses, not the SPA store's
global-partition scan; and storing the access-token string on the refresh
record makes old-token revocation a direct delete plus
`evict_caches_for_token` (`mcp/invalidation.py:31`).

### 5. DCR records and system-actor trust rows never expire — confirmed in code

`register_client` stores `created_at` only (`client_registry.py:61-71`), with
no TTL on the `mcp_clients` bucket write (`:300-311`) or the global index
(`:565-574`). `_create_client_trust_relationship` walks
`actor_interface.trust.relationships` to find the row it just created
(`:462-465`), a full list per registration. "One claude.ai connect creates two
registrations, only the second used" and "removing a connector does not
remove its registration" are live observations, not verified here.
**Todo**: `thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md`.

### 6. Redirect URIs exact-match only — confirmed

`validate_redirect_uri` is `redirect_uri in registered_uris`
(`client_registry.py:150-166`). No loopback rule (RFC 8252 §7.3). **Todo**
(conformance follow-ups).

### 7. No RFC 8707 `resource` / audience binding — confirmed

Neither the authorize params (`oauth2_endpoints.py:212-246`) nor the token
params (`:325-333`) read `resource`; no token record carries an audience.
**Todo** (conformance follow-ups).

### 8. No Client ID Metadata Document support — confirmed

`client_id_metadata_document_supported` appears nowhere in the tree.
**Todo** (conformance follow-ups).

### Context items

| Item | Verdict |
| --- | --- |
| `client_credentials` advertised | By design; app API clients use it. |
| `serverInfo.version` is the library version (`handlers/mcp.py:961`) | By design. |
| GET `/mcp` returns JSON, not SSE | Known; the primary consumer's API Gateway deployment cannot serve SSE (see the dual-era todo). |
| App middleware re-validates the bearer because there is no post-auth hook | Real gap, not scheduled; noted in the conformance follow-ups todo. |
| `tools.listChanged: true` advertised, notification never sent (`:936-950`) | Confirmed. Conformance follow-ups todo. |
| `MCP-Protocol-Version: 2026-07-28` rejected once per connect | Expected legacy-server handshake; the dual-era todo's trap section says why it must stay `-32600`. |
| Claude Code CLI 2.1.280 retried five times in 300 s before connecting | Live sighting of the dual-era todo's pickup trigger 2. Appended to that todo; not itself grounds to act (one CLI build, one day, and it did connect). |
| ChatGPT probes `/.well-known/openid-configuration`, gets 404 | Confirmed: the integrations register only `oauth-authorization-server` and `oauth-protected-resource[/mcp]`. Conformance follow-ups todo. |
| Protected-resource document says `"resources": false` (`oauth2_endpoints.py:795`) while `initialize` advertises resources | Confirmed. Conformance follow-ups todo. |
| `resources/templates/list` is method-not-found while `resources/list` returns a templated URI | Confirmed (`handlers/mcp.py:866-880` dispatch). Conformance follow-ups todo. |
| Shared registrations flip the Connections card name (`_update_trust_with_client_info` last-writer-wins) | Confirmed structurally (`handlers/mcp.py:2608-2680` skips only when unchanged). Conformance follow-ups todo. |
| `tools/list` fails open on evaluator error (`handlers/mcp.py:1174-1178`) | **Known, deliberate**: `CHANGELOG.rst:1102` records that a permission-subsystem outage stays fail-open so it does not lock out every client; per-call checks are fail-closed since 3.14.4. Not a finding. |

## Decisions Needed

All resolved with the owner on 2026-09-25 (recorded in the plan):

- Trust list: **list-only strip**, per-relationship GET unchanged, spec example
  updated.
- MCP refresh rotation: **in 3.15.0**, porting the `oauth_session` pattern.
- PKCE `plain`: **accepted at exchange**, rejected on the library's own
  authorize path.

Three more were taken while the plan was evaluated (2026-09-25, same
session), each recorded with its reason in the plan's "Decisions Made":
authorization codes become single-use atomically (the refresh port rewrites
the same function); consumed MCP token rows get a named reaper per backend
(the shortened TTL alone reaps nothing on PostgreSQL); rotation pops one
token from the per-process MCP cache instead of evicting the actor.

## Where the surviving findings went

- Plan (3.15.0): reports 1 and 2; report 3 items 1–4.
- `thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md`: item 5.
- `thoughts/todo/mcp-oauth-connector-conformance-followups.md`: items 6–8 and
  the context items marked above.
- `thoughts/todo/mcp-2026-07-28-dual-era-support.md`: the Claude Code CLI
  sighting, appended to the trigger list.
- `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md`: reduced to a
  stub pointing at the plan.
- The two `thoughts/inbound/` files are deleted; this note carries their
  attribution.
