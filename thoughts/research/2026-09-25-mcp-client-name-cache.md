# Research: inbound report — MCP client-name cache, token-store faults, trust-list text, `get_bucket` ambiguity

**Date:** 2026-09-25
**Branch:** release/3.15.0-mcp-oauth-hardening (Phase 1 of the 3.15.0 plan landed in the working tree)
**Source:** `thoughts/inbound/mcp-client-name-cache.md`, filed 2026-09-25 by
`actingweb_mcp` (Emm AI) from its connector-alignment work (its plan #95,
todo #100). It is the section of the 2026-09-18 connector audit that was
withheld until the consumer's own sanitising fix shipped (`v2026.09.25.1`),
plus three asks from that fix's two verifications. The inbound file is
deleted by this triage; this note carries the attribution.

Plan: `thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`
(Phase 2, added by this triage).

## Summary

All four items hold. Checking the tree changed three of them:

- **Item 1 (client-info cache):** the mechanism is as reported, but the
  suggested fix (key the cache by client id or bearer token at the point of
  the trust write) is impossible there: the write happens in the OAuth
  callback, a browser redirect that carries no MCP session, header or token,
  so nothing links it to a pre-auth `initialize`. The fix is to delete that
  write and rely on the authenticated `initialize` path that already writes
  the trust row. There is also a **second unauthenticated source** of the
  same text the report did not name: the DCR `client_name`, which seeds the
  trust row's `client_name` and `desc` at registration.
- **Item 2 (store faults read as "no such token"):** the report's ask
  (raise from `_search_token_in_actors`) would change nothing on its own:
  both backends' `get_attr` already catch every exception and return `None`
  one layer below. The strict read exists (`get_attr_strict`, both
  backends, `db/protocols.py:1059`), used only by `deletion.py`.
- **Item 4 (`get_bucket` ambiguity):** also a defect in the Phase 1 code.
  `Attributes.get_bucket()` never returns `None` — on a backend fault it
  returns `{}` with `_bucket_loaded` unset — so the new `_revoke_chain`
  snapshot's "`None` → WARNING, treat as empty" branch is dead, and a read
  fault during theft revocation leaves the chain's global index rows and
  provider-token rows behind silently.

## Item 1: the `clientInfo` cache attaches unauthenticated text to authenticated users

### Verified

- `handlers/mcp.py:910-917`: `_handle_initialize` stores `params["clientInfo"]`
  before any authentication and logs `client_info['name']` raw at INFO (a
  `clientInfo` without `name` raises `KeyError` there, swallowed nowhere —
  the initialize fails).
- `:22` `_mcp_client_info_cache` is a module global; `:2713-2732` prunes by
  age (600 s) only; no size bound.
- `:2734-2767` `_get_session_key`: `mcp-session:<Mcp-Session-Id>` when the
  header is present, else `remote_addr:hash(User-Agent[:50])`. Nothing sets
  `remote_addr` (`:1977-1984` says so), so the fallback is
  `unknown:<hash>` and every client with the same UA prefix shares a slot.
  The library never issues `Mcp-Session-Id`; it is client-chosen.
- `:2045-2051` `_resolve_live_client_info` feeds that slot into the
  authenticated runtime context (`:2139`, `:2220`); client-type detection
  reads it at `:1093-1100` and `:1246`.
- `oauth2_server.py:447` → `_store_mcp_client_info_in_trust` (`:881-919`)
  takes the first cache entry under ten minutes old **whatever its key** and
  writes its name and version into the trust row of whoever just signed in;
  failures are swallowed at DEBUG.
- `interface/trust_manager.py:512-514`, `:562-563` seed `desc` as
  `"OAuth2 client: {client_name}"`. The `client_name` there comes from the
  DCR registration body (`client_registry.py` `_create_client_trust_relationship`),
  which is unauthenticated too.
- The authenticated path already exists: `_handle_initialize` `:918-926`
  authenticates and calls `_update_trust_with_client_info(actor,
  client_info)` with the request's own `clientInfo`.

### What the check changed

- The cross-user write is real on any process that serves more than one
  user. The fix is removal of the callback-time write, not re-keying it.
- **Deduced, not confirmed:** every connector sends `initialize` again with
  its bearer token after OAuth, so the authenticated path names the trust
  row. If one continues its pre-auth session instead, its row keeps the
  DCR `client_name` until its first authenticated `initialize`. The rc
  connector pass (plan Phase 4) checks this per connector in the demo and
  consumer logs.
- The live-context leak (`_resolve_live_client_info` on the UA fallback) is
  lower severity — not persisted — but hands one client's name to another
  user's tools as "live". Keyed by `Mcp-Session-Id` or, after
  authentication, by a hash of the bearer token, it cannot cross users.
- The name flip between two clients sharing one registration is the
  existing last-writer-wins item in
  `thoughts/todo/mcp-oauth-connector-conformance-followups.md`; not repeated.

## Item 2: a token-store fault is indistinguishable from an invalid token

### Verified

- `token_manager.py` `_search_token_in_actors` and
  `_search_refresh_token_in_actors` catch everything and return `None`.
- Below them, `db/dynamodb/attribute.py:94-97` and the PostgreSQL `get_attr`
  return `None` on any exception as well.
- `handlers/mcp.py` `authenticate_and_get_actor_cached` catches every
  exception on the cache-miss path and returns `None`; both callers (`:718`,
  `:845`) answer 401 `invalid_token`. A throttle during a refresh answers
  `invalid_grant`, so a client drops a good refresh token.
- The consumer's suspended-account middleware sees `None`, lets the request
  through, and the library serves it from its five-minute token cache.

### Delta

Strict reads in the token manager's index and row lookups, a distinct
`TokenStoreUnavailable` exception, and a 503 with `Retry-After` from the MCP
endpoint on it; the refresh grant answers 500 `server_error` rather than
`invalid_grant`. The trade — a store outage turns every uncached MCP request
into a 503 rather than a 401 — is recorded as a plan decision for the owner.

## Item 3: `GET /{actor_id}/trust` serves client-supplied text unsanitised

Verified: `_public_trust_row` (added in Phase 1) and the per-relationship
GET pass `client_name`, `client_version` and `desc` through as stored.
Primary fix is at write (item 1's sources); read-time sanitising in both
GET routes covers rows stored before 3.15. `desc` is user-editable, so it
is stripped of control characters but never capped; that is a behaviour
change on read for every trust row, peers' included.

## Item 4: `Attributes.get_bucket()` answers `{}` for "empty" and "could not read"

Verified at `attribute.py:77-125`. Delta: a public `Attributes.loaded`
property; `_snapshot_bucket` in the token manager uses it and aborts the
index and provider-row cleanup with a WARNING on a fault (the
`delete_by_chain` delete still runs; the orphaned index rows expire on their
TTL and point at deleted rows, which the lookups already treat as stale).

## Where the findings went

- Plan Phase 2 (new): items 1–4.
- `thoughts/todo/mcp-oauth-connector-conformance-followups.md`: unchanged
  (the name flip is already there).
- `thoughts/inbound/mcp-client-name-cache.md`: deleted.
