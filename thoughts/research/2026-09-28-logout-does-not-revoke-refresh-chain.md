# Research: SPA logout and `/oauth/revoke` do not end the refresh chain

**Date:** 2026-09-28
**Branch:** docs/triage-spa-revoke-chain
**Commit:** 0dc4aed
**Input:** `thoughts/todo/logout-does-not-revoke-refresh-chain.md` (reported by
the `actingweb_mcp` consumer on 2026-09-04 and widened by their second report on
2026-09-28, their todo #85), along with `thoughts/todo/token-store-fault-contract-gaps.md`
item 1 and `thoughts/todo/mcp-logout-fault-path-followups.md` item 3, which the
todo says must land with it. The todo's line references predate 3.15.
Every reference below was re-read at `0dc4aed`.

## Research Questions

1. **Which handler serves each logout and revoke route, and is
   `OAuth2SPAHandler._handle_logout` dead?** It is dead. Both logout routes
   reach `OAuth2EndpointsHandler._handle_logout_request`, and both revoke
   routes reach `OAuth2SPAHandler._handle_revoke`. See [Routing](#routing).
2. **What do the live logout and revoke paths do today?** Logout deletes the
   access-token row and clears cookie names that nothing sets. Revoke deletes
   one row. Neither reads `chain_id`, and both answer success whatever the
   store did. See [The live logout path](#the-live-logout-path) and
   [`_handle_revoke`](#_handle_revoke).
3. **Where are SPA tokens minted, and can the login access token carry the
   refresh token's `chain_id`?** Six sites mint a login pair and one rotates.
   Every login site mints the access token first. `create_refresh_token`
   generates the chain id internally and returns only the token string. See
   [Mint sites](#mint-sites).
4. **How does the SPA `revoke_token_chain` behave on a fault on each backend,
   and what did the MCP path do in 3.15?** On PostgreSQL a fault silently
   deletes nothing. On DynamoDB it raises part-way and skips the cache
   eviction. The MCP `_revoke_chain` anchor pattern is the existing fix
   shape. See [Chain revocation and faults](#chain-revocation-and-faults).
5. **Which tests and doubles exist?** `tests/mcp_token_double.py` already
   has the fault switches. No test checks refresh-token state after an SPA
   logout or revoke, and no integration test calls `/oauth/revoke`. See
   [Tests](#tests).
6. **What do the docs and CHANGELOG claim, and is this still a patch?** The
   SPA guide's claim "clear all tokens" is false. The API reference promises
   revoke always answers `{"success": true}`. See [Docs and changelog](#docs-and-changelog)
   and [Release shape](#release-shape).
7. **What do the standards say?** Revoking a refresh token SHOULD invalidate
   the grant's access tokens, and revoking an access token MAY revoke the
   refresh token (RFC 7009 §2.1). A 503 means "assume the token still exists,
   retry" (RFC 7009 §2.2.1). `Retry-After` needs
   `Access-Control-Expose-Headers` to be readable cross-origin. See
   [External References](#external-references).

## Summary

The todo's diagnosis holds at HEAD, and the check found three more gaps.

Confirmed from the todo:
- `/oauth/logout` with a hex SPA token deletes only that access-token row.
- It answers `action: success` on every path.
- It clears `oauth_token`, `oauth_refresh_token` and `session_id`. SPA
  issuance sets `access_token`, `oauth_token` and `refresh_token`.
- `/oauth/revoke` with a refresh hint deletes one row, which can be a used
  row. Deleting a used row removes the replay tripwire.
- `/oauth/revoke` catches every exception and always answers 200.
- `_handle_logout`, the only code that clears the right cookie names on
  logout, is unreachable.
- No login site links its access token to the refresh chain.

New from this check:
- **An expired access token cannot reach its chain.** Access tokens live 1 h,
  and `validate_access_token` deletes an expired row and returns `None`. A
  user who logs out after an idle hour therefore presents a token with no
  `chain_id`, even once the login sites are fixed.
- **A store fault on the logout lookup reads as "unknown token".** It is
  non-strict `get_attr`, so the response is "logged out" with no revocation.
- **FastAPI's `oauth_token`-cookie branch rewrites a 503.** It answers 200
  (or a 302) and deletes the cookie. That branch is exactly where a
  cookie-mode browser SPA lands. It never mattered while the SPA branch
  could not fail, but it will once it can. This is
  `mcp-logout-fault-path-followups.md` item 1, and it becomes live for SPA
  users.

The existing code already supplies every building block:
- `delete_by_chain(defer_name=)` on both backends.
- `get_attr_strict`.
- `TokenStoreUnavailable`.
- The SPA handler's `_store_unavailable()` 503 helper, whose `Retry-After`
  both integrations already pass through on `/oauth/revoke`.
- The MCP `_revoke_chain` pattern: anchor the presented token, strict-read on
  zero deleted, evict in `finally`.
- The MCP exchange's "pick the chain first, give it to both mints" order.

The owner settled the DynamoDB scan cost on 2026-09-28 (accept the scan). The
remaining decisions are listed under [Decisions Needed](#decisions-needed).

## Detailed Findings

### Routing

| Route | Flask | FastAPI | Reaches |
| --- | --- | --- | --- |
| `/oauth/logout` | `flask_integration.py:215-217` → `_handle_oauth2_endpoint("logout")` | inline route `fastapi_integration.py:750-829` | `OAuth2EndpointsHandler._handle_logout_request` (`oauth2_endpoints.py:92-93`, `:136-137`) |
| `/oauth/spa/logout` | `:258-261` "Delegate to main logout handler" | `:895-900`, straight to `_handle_oauth2_endpoint`, skipping the inline cookie branch | same |
| `/oauth/revoke` | `:224-226` → `_handle_oauth2_spa_endpoint("revoke")` | `:838-842` | `OAuth2SPAHandler._handle_revoke` (`oauth2_spa.py:235-236`) |
| `/oauth/spa/revoke` | `:250-252` | `:876-880` | same |

The only reference to `_handle_logout` (defined at `oauth2_spa.py:1484`) is
the dispatch `elif path == "logout": return self._handle_logout()` at
`oauth2_spa.py:237-238`. No route sends `"logout"` to the SPA handler, and no
test calls it. `tests/integration/test_oauth2_flows.py:513-533` pins the
delegation to the main handler.

### The live logout path

`_handle_logout_request` (`oauth2_endpoints.py:867-1003`):

- **Where the token comes from:** a Bearer header, otherwise the
  `oauth_token` cookie (`:885-900`). The `access_token` and `refresh_token`
  cookies are never read.
- **Dispatch by prefix** (`:1025-1027`): an `aw_` token goes to
  `_handle_mcp_token_logout`, anything else to the SPA branch. SPA tokens are
  hex from `config.new_token()` (`config.py:436-438`).
- **The SPA branch** (`:1029-1073`) does this:
  1. `validate_access_token(token)`, then `_clear_provider_token_for_actor`.
  2. `revoke_access_token(token)`, logging any exception at DEBUG.
  3. It always returns `action: "success"` with
     `clear_cookies: ["oauth_token", "oauth_refresh_token", "session_id"]`
     (`:1054-1059`, `:1071`).
- **The MCP branch** (`:1075-1102`) maps `TokenStoreUnavailable` to
  `action: "retry"`. On `retry`, `_handle_logout_request` sets 503 and
  `Retry-After: 5`, clears no cookies, and answers
  `{"success": false, "error": "temporarily_unavailable"}` (`:953-965`).
  **The SPA branch can reuse this unchanged**; it only needs to return
  `retry`.
- **An unexpected exception still yields `action: "success"`**, with the
  message "Logged out (token revocation failed)" (`:936-951`).
- **Nothing ever sets the names this path clears.** No code in `actingweb/`
  sets `oauth_refresh_token` or `session_id`. The names appear only in clear
  lists (`oauth2_endpoints.py:917-918`, `:947-948`, `:1057`, `:1071`,
  `:1100`; `oauth2_server.py:780`, `:792`).

**`validate_access_token`** (`oauth_session.py:476-512`):
- It uses non-strict `Attributes.get_attr` (`:497`), so unknown, expired and
  store-fault all return `None`.
- On an expired row it calls `bucket.delete_attr(name=token)` and returns
  `None` (`:505-508`).
- It returns the whole row dict otherwise. That includes `chain_id`, which is
  `None` for every login-minted token (`store_access_token`, `:459-465`).

**`revoke_access_token`** (`:514-552`) and **`revoke_refresh_token`**
(`:779-811`):
- Each does `get_attr` + `delete_attr` + `_evict_mcp_caches_for_token_owner`.
- Each ignores `delete_attr`'s return value. Per `attribute.py:227-228`,
  "PostgreSQL returns ``False`` on a caught exception; DynamoDB swallows and
  returns ``True``", so both methods answer `True` for an unknown token and
  usually for a faulted delete.

**How the integrations answer:**
- **Flask** `_handle_oauth2_endpoint` (`flask_integration.py:1183-1300`)
  passes the handler's status and headers through (`:1257-1263`), so a 503
  with `Retry-After` reaches the client.
- **FastAPI, `oauth_token` cookie present** (`fastapi_integration.py:790-816`,
  checked before the Bearer header):
  - An AJAX request gets a `JSONResponse` built from
    `_logout_outcome(handler_response)`. That is always status 200 with no
    `Retry-After`; a failure shows only as `success: false`. It then calls
    `delete_cookie("oauth_token")`.
  - A non-AJAX request gets a 302 to `/` that deletes `oauth_token`, whatever
    the handler said.
  - A cookie-mode browser SPA carries its hex session token in `oauth_token`
    (`oauth2_spa.py:1653-1672`), so this is its path. Once the SPA branch can
    return `retry`, a FastAPI browser logout on a fault clears the cookie over
    a revocation that did not happen. This is
    `mcp-logout-fault-path-followups.md` item 1, which that todo calls rare
    because "the cookie normally holds a hex session token". The SPA fix makes
    it the common case.
- **FastAPI, Bearer header without the cookie** (`:819-821`) and
  `/oauth/spa/logout` pass the status and headers through (`:2147-2160`).

**Cookies.** Issuance sets these:

| Setter | Cookie | Path | SameSite |
| --- | --- | --- | --- |
| `_set_token_cookies` (`oauth2_spa.py:1653-1672`) | `access_token`, `oauth_token` | `/` | — |
| `_set_refresh_token_cookie` (`:1680-1690`), from the token endpoint in cookie and hybrid mode (`:777-787`) | `refresh_token` | `/` | Lax |
| The provider callback in hybrid mode (`oauth2_callback.py:729-739`, `:1273-1284`) | `refresh_token` | `/oauth/spa/token` | Strict |

A browser never sends the callback's refresh cookie to `/oauth/logout` or
`/oauth/revoke`. So a hybrid session whose only refresh so far came from the
callback has no refresh cookie that logout can read.

`_clear_token_cookies` (`oauth2_spa.py:1692-1712`) clears `access_token`,
`oauth_token`, `refresh_token` and `session_id` at `/`, and `refresh_token` a
second time at `/oauth/spa/token`. Only `_handle_revoke` and the dead
`_handle_logout` call it.

### `_handle_revoke`

`oauth2_spa.py:1404-1482`:

- **Default hint:** `token_type_hint` defaults to `"access_token"` (`:1431`).
- **Token source** (`:1430-1448`), in order:
  1. the body `token`,
  2. a Bearer header,
  3. the `access_token` or `oauth_token` cookie.

  It never reads the `refresh_token` cookie.
- **Refresh hint:** `session_manager.revoke_refresh_token(token)` (`:1459-1460`).
  There is no lookup, no chain, and no check whether the row is used.
- **Any other hint:** `validate_access_token`, then
  `_clear_provider_token_for_actor`, then `revoke_access_token` (`:1463-1471`).
- **Errors:** `except Exception as e: logger.warning(...)` (`:1473-1474`).
- **Response:** `_clear_token_cookies()` (`:1477`), then
  `{"success": True, "message": "Token revoked successfully"}` with no status
  set (`:1479-1482`).

The theft case, as the todo put it: a thief who redeemed RT1 first holds the
chain's tip. A client that revokes RT1 deletes the used row, and with it the
replay that would have revoked the chain.

### Mint sites

`create_refresh_token` (`oauth_session.py:554-614`):
- It writes `"chain_id": chain_id or secrets.token_urlsafe(16)` (`:594`) and
  returns only the token string (`:614`).
- Its docstring gives the reason for a fresh chain per login: "each
  device/session gets its own independent lineage" (`:568-574`).
- It raises `TokenStoreUnavailable` if the write fails (`:602-611`).

`store_access_token` (`:431-474`):
- It accepts `chain_id`.
- Its docstring (`:447-452`) says login tokens are chain-less and "simply
  self-expire".
- It ignores what `set_attr` returns.

`_generate_actingweb_token(actor_id, identifier, chain_id=None)`
(`oauth2_spa.py:1617-1641`) is the access-mint helper for the SPA handler. It
already forwards `chain_id`.

| # | Site | Flow | Order | Access `chain_id` |
| --- | --- | --- | --- | --- |
| A | `oauth2_callback.py:710-719` | Provider callback, SPA JSON | `store_access_token` inline `:712-714`, then `create_refresh_token` `:717-719` | none |
| B | `oauth2_callback.py:1240-1246` | Provider callback, SPA redirect with pending session | inline `:1242`, then `:1244-1246` | none |
| C | `oauth2_spa.py:967-972` | `authorization_code` at `/oauth/spa/token` | `_generate_actingweb_token` `:967`, then `:972` | none |
| D | `oauth2_spa.py:1123-1128`, `_finalize_native_session` | JWT-bearer / native OIDC grant **and** mobile ticket grant | `:1123`, then `:1128` | none |
| E | `oauth2_spa.py:1367-1372` | Passphrase grant | `:1367`, then `:1372` | none |
| F | `oauth2_spa.py:746-753` | Refresh rotation | the consumed row's `chain_id` goes to both mints | set |
| G | `oauth2_callback.py:785-787` | www `oauth_token` cookie | access only, no refresh | none (correctly) |

Two more facts:
- No shared SPA pair-mint helper exists. Five login sites (A–E; D serves two
  grants) each make two calls.
- The existing pair pattern is the MCP exchange
  (`oauth2_server/token_manager.py:233-249`). It calls `_new_chain_id()`
  (`:622-625`, `secrets.token_urlsafe(16)`) first and passes the id to both
  `_create_access_token` and `_create_refresh_token`.

`create_refresh_token` already takes `chain_id`, so pre-generating it at each
login site needs no signature change.

### Chain revocation and faults

**The `delete_by_chain` contract** is in `db/protocols.py:1214-1240`. The
`defer_name` text reads: "A backend that deletes row by row (DynamoDB) removes
it only after every other row … a set-based delete (PostgreSQL) is atomic and
ignores it." The contract does not say how a fault is reported.

**DynamoDB** (`db/dynamodb/attribute.py:376-426`):
- It runs a `consistent_read=True` Query per bucket over the whole
  `OAUTH2_SYSTEM_ACTOR` partition (`:404-408`) and filters on `chain_id` in
  memory (`:413-417`).
- A failure to build the query is swallowed with `continue` (`:409-410`),
  which skips that bucket silently.
- A failure in `list(query)` (`:411`) or in `t.delete()` (`:421`, `:424`)
  raises.
- The docstring says "Revocation is rare (a theft event), so the scan is
  acceptable" (`:381-385`).
- The owner accepted the per-logout scan on 2026-09-28 from production
  numbers: 42 rows in the partition, about 3 RCU per call, about 0.4 logouts a
  day. That docstring rationale needs updating.

**PostgreSQL** (`db/postgresql/attribute.py:658-700`):
- It is one `DELETE … data->>'chain_id' = %s` statement, using
  `idx_attributes_chain_id`.
- On a fault it does `except Exception: logger.error(...); return 0`
  (`:698-700`). It never raises.

**The strict read.** `get_attr_strict` (`protocols.py:1058-1077`; DynamoDB
`:107-137`, PostgreSQL `:276-…`) "returns None only for a confirmed absence
and raises otherwise". It counts an expired `ttl_timestamp` as absent. The
SPA refresh consume already uses it (`oauth_session.py:728-737`).

**SPA `revoke_token_chain`** (`oauth_session.py:896-958`):
- It calls `delete_by_chain` positionally, with no `defer_name` (`:938-943`).
- It logs at WARNING only when `revoked` is non-zero (`:945-949`).
- It calls `evict_caches_for_actor(actor_id)` after the delete, not in a
  `finally` (`:954-956`).
- It has no try.
- Its docstring (`:907-912`) says chain-less access tokens are "left to
  self-expire".

**The SPA theft branch** (`oauth2_spa.py:714-740`) calls it at `:725` with no
try, then answers 401 "Refresh token already used - session revoked for
security". What happens on a fault depends on the backend, as
`token-store-fault-contract-gaps.md` item 1 says:
- **PostgreSQL:** it answers 401 "revoked" while the chain survives (fail-open).
- **DynamoDB:** the exception escapes through `post()` and both
  integrations' `handler.post` calls (`flask_integration.py:1322`,
  `fastapi_integration.py:2199`) as a framework 500, and the eviction is
  skipped.

**The MCP pattern** (`oauth2_server/token_manager.py:686-790`, `_revoke_chain`):
1. It passes `defer_name=anchor[1]`.
2. A raise from the delete becomes `TokenStoreUnavailable`.
3. On zero deleted, it runs `_strict_read` on the anchor:
   - absent means "already revoked" (INFO, return 0);
   - present means a fault (ERROR, raise).
   - Without an anchor, 0 always counts as a fault.
4. It evicts in `finally`.

Callers keep the presented token on a fault (`revoke_token`, `:543-552` and
`:578-591`). `TokenStoreUnavailable` is defined at `token_manager.py:28-42`,
and `StoreFault` at `single_use.py:85`.

**The 503 helper.** `OAuth2SPAHandler._store_unavailable()`
(`oauth2_spa.py:1753-1761`) returns
`_json_error(503, "Token store temporarily unavailable; retry")` with
`Retry-After: 5`. Both integrations copy `Retry-After` from the SPA handler
(`flask_integration.py:1337-1339`, `fastapi_integration.py:2228-2230`,
tested in `tests/test_spa_token_retry_after.py`). So `/oauth/revoke` can
answer 503 through the same helper with no integration change.

**Caches.**
- SPA access-token validation is not cached in-process.
  `auth.py:367-377` calls `validate_access_token`, which reads storage on
  every request.
- `evict_caches_for_actor` (`mcp/invalidation.py:52-69`) clears the MCP
  handler's per-actor `_actor_cache` and `_trust_cache` entries and bumps the
  generation. It is per-process only.

### CORS

- `Access-Control-Expose-Headers` appears nowhere in `actingweb/` or `tests/`.
- Both integrations build their own CORS headers for logout
  (`flask_integration.py:1279-1291`; `fastapi_integration.py:764-772`,
  `:2126-2137`) and for the SPA endpoints (`flask_integration.py:1353-1360`,
  `fastapi_integration.py:2209-2230`).
- On the SPA endpoints they discard the headers the handler's own
  `_set_cors_headers` (`oauth2_spa.py:153-175`) set.
- So neither logout's 503 (since 3.15.0), nor the SPA refresh grant's 503
  (since 3.15.0), nor a new revoke 503 is readable cross-origin.

A separate defect, outside this work: FastAPI's OPTIONS on `/oauth/spa/logout`
merges the handler's `Access-Control-Allow-Origin: *` over its own echo-origin
(`:2147-2150`) while also sending `Allow-Credentials: true`. Browsers refuse
that combination.

### Tests

- **`tests/mcp_token_double.py`** (`MemoryStore`, `:55-72`) has these fault
  switches:
  - `faulty_buckets`: `get_bucket` → None and `get_attr_strict` raises.
  - `raising_buckets`.
  - `chain_delete_fault` = `"zero"` / `"raise"` / `"partial"`. `"partial"`
    honours `defer_name` (`:165-195`).
  - `delete_faults`, `write_faults`, `cas_fault`.
- The only SPA suite on the double is
  `tests/test_oauth2_spa_refresh_rotation.py`. It has
  `_assert_retryable_503` (`:303-307`) and a handler builder (`:52-60`).
- MCP logout tests live in `tests/test_oauth2_logout_mcp_tokens.py`:
  - `test_logout_after_a_revocation_fault_can_be_retried` (`:58`) is the
    template.
  - The only SPA-token logout test, `:112`, asserts a MagicMock's
    `revoke_access_token` was called.
- `tests/test_oauth2_spa.py:714-830` tests only provider-token clearing.
- `tests/test_oauth_session.py:432`, `:477` test `revoke_token_chain`
  scoping, on its own mock.
- Nothing tests `_handle_revoke` directly.
- No integration test calls `/oauth/revoke` or `/oauth/spa/revoke`.
- The integration SPA token fixture is the passphrase grant
  (`tests/integration/test_oauth2_spa_passphrase.py:20-54`, using
  `actor_factory`).
- The backend-level chain delete is covered for MCP only
  (`tests/integration/test_mcp_refresh_rotation_backend.py:143`). It has no
  SPA-bucket counterpart.
- Legacy chain-less reuse revoking only itself is pinned by
  `test_oauth2_spa_refresh_rotation.py:179`.

### Docs and changelog

- **`docs/guides/spa-authentication.rst`:**
  - `:205-207` says `/oauth/logout` will "Logout and clear all tokens", which
    is false.
  - The logout example (`:931-950`) sends only the access token and handles
    no 503.
  - The note at `:955-962` is accurate about the provider token.
  - The Token Revocation example (`:964-981`) has no error handling.
  - The complete example (`:1099-1110`) uses `/oauth/spa/logout`.
  - The API reference (`:1379-1400`) says `/oauth/revoke` responds
    `{"success": true, "message": "Token revoked successfully"}`.
  - The API reference (`:1432-1447`) says `/oauth/logout` responds
    `{"success": true, …}`.
- **`docs/migration/v3.15.rst:94-105`:**
  - It states MCP chain revocation and the logout 503 contract.
  - It says "**`/oauth/logout` with an SPA session token is unchanged.**"
- **`docs/reference/security.rst:55`, `:58`:** reuse revokes the rotation
  family, and revocation is per-process.
- **CHANGELOG.rst:** `Unreleased` (`:5-6`) is empty. The 3.15.0 entries at
  `:99-118` state the MCP logout contract and "SPA session tokens keep their
  existing logout path."

### Prior decisions that bind this work

From `thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`:
- Revoking any token revokes its chain (Iteration 5, `:1328-1343`).
- A chain-revocation fault keeps the presented token and answers 503 +
  `Retry-After` (`:142-154`, Iterations 17, 20, 22).
- Behaviour that only one caller wants stays in that caller (`:262-277`).
- Logout dispatch by prefix stays (Iteration 18, `:1731-1765`).
- SPA chain revocation was deferred as "its own todo" (`:322-323`).

From `thoughts/verifications/2026-09-27-refresh-grace-setting-3.md:233`:
- "A legacy chain-less SPA token revokes only itself."

From the todo:
- Chain scope, not actor scope. `revoke_all_tokens` is rejected, per the
  per-device chain design.
- The DynamoDB scan is accepted and shipped as 3.15.1, with option 3 (a GSI on
  a promoted `chain_id`) named as the growth path.

## Decisions Needed

The chain-scope semantics, the fault contract, prefix dispatch, the chain-less
legacy rule and the scan cost are settled (see above). The questions below are
still open.

### Decision 1: How does logout reach the chain when the access token has expired?

Access tokens live `SPA_ACCESS_TOKEN_TTL` (1 h), and `validate_access_token`
deletes an expired row (`oauth_session.py:505-508`). Tagging the login token
fixes a logout within the hour, but not one after an idle period.

**Options:**
1. **Logout also accepts the refresh token.** It would read a `refresh_token`
   from the JSON body (mobile, JSON-mode SPA) and the `refresh_token` cookie
   (cookie mode, path `/`), and revoke its chain.
   - Pro: covers every client that holds its refresh token.
   - Con: a hybrid session whose refresh cookie came from the provider
     callback (path `/oauth/spa/token`, `oauth2_callback.py:733`) is not
     covered. So is a cross-site SPA: the cookie is `SameSite=Lax`, which is
     not sent on a cross-site `fetch` POST.
   - It adds a request field to `/oauth/logout`. Additive, but it is new API
     surface.
2. **Document it: revoke the refresh token at `/oauth/revoke` before
   logout.** This becomes a real chain revocation with this fix, and the
   todo's "workaround does not close the theft case" stops being true.
   - Pro: no new logout surface.
   - Con: every client has to remember a second call, which is the belief the
     original report showed consumers do not have. A browser in cookie mode
     cannot send an HttpOnly cookie in a body, so it needs Decision 4's
     cookie read.
3. **Keep the expired access row readable for its `chain_id`.** Stop
   deleting it in `validate_access_token`, and give it a storage TTL longer
   than `expires_at`.
   - Con: `get_attr_strict` counts an expired `ttl_timestamp` as absent, so
     the storage TTL has to change. Rows live longer, and the DynamoDB scan
     reads more of them.
4. **Accept the gap.** A logout after an idle hour leaves the chain alive, as
   today. Document it.

These are not exclusive: 1 plus 2's documentation is a coherent pair.

### Decision 2: What does an access token presented to `/oauth/revoke` revoke?

RFC 7009 §2.1: revoking an access token "MAY revoke the respective refresh
token as well".

**Options:**
1. **Revoke its chain when it has a `chain_id`, else the row only.**
   - This matches the MCP rule "revoking any token of a chain revokes the
     chain".
   - Once logins are tagged, it is the same effect as logout.
2. **Revoke the row only.** An access-token revoke stays narrow.
   - Two SPA stores would follow different rules. That contradicts the rule
     the 3.15 MCP work set.

### Decision 3: `_handle_logout` — delete or wire?

It is unreachable, and it is maintained as if it were live (see the todo).

**Options:**
1. **Delete it and its dispatch at `oauth2_spa.py:237-238`.** The live path
   takes over its one correct behaviour, calling `_clear_token_cookies`'s
   names.
2. **Route `/oauth/spa/logout` to it.** That makes two logout
   implementations. The 3.15 contract lives in `_handle_logout_request`, so
   the fault handling would need duplicating.

### Decision 4: Should `/oauth/revoke` read the `refresh_token` cookie?

Today the token comes from the body, a Bearer header, or the
`access_token`/`oauth_token` cookie (`:1430-1448`).

**Options:**
1. **Also read the `refresh_token` cookie** when no body token is given and
   the hint is `refresh_token`. This lets a cookie-mode browser revoke its
   chain, subject to the same path and SameSite limits as Decision 1.
2. **Leave it.** A cookie-mode browser revokes through its access-token
   cookie, which is enough once Decision 2 option 1 and the login tagging
   land, and the access token is still valid.

### Decision 5: How does logout avoid logging like a theft event?

`revoke_token_chain` logs WARNING "Revoked N token(s) in chain …" and is
worded as a theft response (`oauth_session.py:945-949`).

**Options:**
1. **A keyword-only `reason=` (or a `log_level`) parameter** on
   `revoke_token_chain`. Callers pick the level.
   - Additive and keyword-only with a default, so patch-safe.
2. **Move the WARNING to the theft caller** (`oauth2_spa.py:726-730`, which
   already logs its own WARNING) and log at INFO inside
   `revoke_token_chain`.
   - Fits the rule "behaviour only one caller wants belongs in that caller"
     (plan `:262-277`).

### Decision 6: Which surfaces get `Access-Control-Expose-Headers: Retry-After`?

**Options:**
1. **Logout and revoke only**, as the two todos scope it.
2. **Logout, revoke and `/oauth/spa/token`.** The refresh grant's 503 has the
   same gap since 3.15.0, and the SPA guide tells clients to retry it.
   - Both integrations set SPA-endpoint CORS in one place each
     (`flask_integration.py:1353-1360`, `fastapi_integration.py:2209-2230`),
     so this is the same edit.

### Decision 7: Does `mcp-logout-fault-path-followups.md` item 1 land in this patch?

Once the SPA branch can answer `retry`, FastAPI's cookie branch
(`fastapi_integration.py:790-816`) rewrites the 503 as 200/302 and deletes
`oauth_token`, for every cookie-mode browser SPA on FastAPI.

**Options:**
1. **Land it with this fix.** On a failed `_logout_outcome`, pass the
   handler's status and `Retry-After` through and do not delete the cookie.
2. **Leave it.** The SPA fault contract then holds on Flask and on FastAPI
   Bearer logouts, but not on FastAPI cookie logouts.

**Recommendation:** option 1. Without it, the fault contract the owner chose
in 3.15 fails on the most common browser path this fix touches.

## Release shape

The owner decided a 3.15.1 patch on 2026-09-28. Against the `### Release`
rule ("no route, hook name, kwarg, response field, public signature or config
option changes"), the diff introduces these changes:

- **A 503 status on `/oauth/revoke`**, with body
  `{"error": "temporarily_unavailable", …}` or the SPA handler's
  `_json_error` shape. The API reference (`spa-authentication.rst:1379-1400`)
  documents only `{"success": true}`. 3.15.0 introduced the same 503 on
  `/oauth/logout` inside a minor, with a migration note.
- **A new 503 on SPA-token `/oauth/logout`.** The status is already
  documented for MCP tokens; the migration guide says the SPA path is
  "unchanged".
- **A new keyword-only parameter** on `revoke_token_chain`, if Decision 5
  option 1 is chosen. Additive with a default, so allowed.
- **A new logout request field**, if Decision 1 option 1 is chosen.
- **Behaviour changes with no signature change:**
  - Logout and revoke end the whole chain.
  - The theft response also kills the login access token.
  - The cookie-name fix.

These are facts for the plan to record next to the owner's 3.15.1 decision.
The CHANGELOG entry needs **Behavior change:** sentences for each item. Per the
`### Changelog` rule, a patch touches no `docs/migration/`. The v3.15 guide's
"SPA … unchanged" line is therefore contradicted by the changelog, not
edited.

## Code References

- `actingweb/handlers/oauth2_endpoints.py:867-1003` - `_handle_logout_request`, including the `retry` → 503 handling at `:953-965`
- `actingweb/handlers/oauth2_endpoints.py:1025-1073` - prefix dispatch and the SPA branch (always `success`, wrong cookie names)
- `actingweb/handlers/oauth2_endpoints.py:1075-1102` - `_handle_mcp_token_logout` (`retry` on `TokenStoreUnavailable`)
- `actingweb/handlers/oauth2_spa.py:237-238`, `:1484-1550` - dead `_handle_logout`
- `actingweb/handlers/oauth2_spa.py:1404-1482` - `_handle_revoke`
- `actingweb/handlers/oauth2_spa.py:714-740` - SPA theft branch
- `actingweb/handlers/oauth2_spa.py:1617-1641` - `_generate_actingweb_token(chain_id=)`
- `actingweb/handlers/oauth2_spa.py:1653-1712` - cookie setters and `_clear_token_cookies`
- `actingweb/handlers/oauth2_spa.py:1753-1761` - `_store_unavailable()`
- `actingweb/handlers/oauth2_spa.py:967-972`, `:1123-1128`, `:1367-1372`, `:746-753` - SPA mint sites
- `actingweb/handlers/oauth2_callback.py:710-739`, `:1240-1284` - callback mint sites and hybrid cookie at `/oauth/spa/token`
- `actingweb/oauth_session.py:431-474` - `store_access_token`
- `actingweb/oauth_session.py:476-512` - `validate_access_token` (non-strict, deletes expired)
- `actingweb/oauth_session.py:514-552`, `:779-811` - single-row revokes
- `actingweb/oauth_session.py:554-614` - `create_refresh_token` (chain id generated, not returned)
- `actingweb/oauth_session.py:692-777` - `try_mark_refresh_token_used` (strict-read and `StoreFault` pattern)
- `actingweb/oauth_session.py:896-958` - SPA `revoke_token_chain`
- `actingweb/oauth2_server/token_manager.py:233-249`, `:622-625` - MCP chain-first pair mint
- `actingweb/oauth2_server/token_manager.py:686-790` - MCP `_revoke_chain` anchor pattern
- `actingweb/oauth2_server/token_manager.py:28-42` - `TokenStoreUnavailable`
- `actingweb/db/protocols.py:1058-1077`, `:1214-1240` - `get_attr_strict`, `delete_by_chain` contracts
- `actingweb/db/dynamodb/attribute.py:376-426` - scan-based `delete_by_chain`, raises on iterate/delete
- `actingweb/db/postgresql/attribute.py:658-700` - indexed `delete_by_chain`, returns 0 on fault
- `actingweb/interface/integrations/fastapi_integration.py:37-61`, `:750-829` - `_logout_outcome` and the cookie branch
- `actingweb/interface/integrations/flask_integration.py:1257-1263`, `:1337-1339` - status and `Retry-After` pass-through
- `tests/mcp_token_double.py:55-72`, `:165-195` - fault switches
- `tests/test_oauth2_logout_mcp_tokens.py:58` - template fault-retry logout test
- `tests/test_oauth2_spa_refresh_rotation.py:52-60`, `:179`, `:303-307` - SPA handler on the double
- `tests/integration/test_oauth2_spa_passphrase.py:20-54` - live-server SPA token fixture
- `docs/guides/spa-authentication.rst:205-207`, `:931-981`, `:1379-1447` - claims to correct
- `docs/migration/v3.15.rst:94-105` - "SPA session token is unchanged"

## External References

Accuracy caveat from the web researcher: "my fetch tool condenses pages, so I
used text it returned in quotation marks, cross-checked with narrower
follow-up fetches. Before any of this goes into a changelog or docs, compare
the wording against the linked page. The RFC 10017 section numbers are the
least certain."

- https://www.rfc-editor.org/rfc/rfc7009 - RFC 7009:
  - §2.1: "If the particular token is a refresh token and the authorization
    server supports the revocation of access tokens, then the authorization
    server SHOULD also invalidate all access tokens based on the same
    authorization grant." And "If the token passed to the request is an
    access token, the server MAY revoke the respective refresh token as
    well."
  - §2.2: 200 for an invalid token.
  - §2.2.1: "If the server responds with HTTP status code 503, the client
    must assume the token still exists and may retry after a reasonable
    delay", with an optional `Retry-After`.
  - §2.3: the endpoint MAY support CORS.
- https://www.rfc-editor.org/rfc/rfc9700.txt - RFC 9700 §4.14.2:
  - On rotation, the previous token is invalidated but "information about the
    relationship is retained".
  - On reuse, the server "will revoke the active refresh token".
  - Revocation on "logout at the authorization server" is listed as a
    security event a server may act on.
- https://raw.githubusercontent.com/oauth-wg/oauth-v2-1/main/draft-ietf-oauth-v2-1.md - OAuth 2.1 §4.3.3: on reuse, the server "will revoke the active refresh token as well as the access authorization grant associated with it".
- https://www.rfc-editor.org/rfc/rfc10017.txt - Browser-Based Apps, published as RFC 10017:
  - Logout behaviour is left to the application (§6.1.2.1).
  - "It suffices to revoke the user's access token and/or refresh token"
    (§6.1.2.3).
- https://fetch.spec.whatwg.org/#cors-safelisted-response-header-name and https://developer.mozilla.org/en-US/docs/Glossary/CORS-safelisted_response_header - `Retry-After` is not safelisted. `Access-Control-Expose-Headers` is required for a cross-origin script to read it.
