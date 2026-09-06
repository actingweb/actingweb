# TODO: No reachable logout path revokes a refresh token

**Status:** Open. Triaged 2026-09-06 from an inbound consumer report.
**Filed by:** the `actingweb_mcp` consumer, 2026-09-04, out of the security
evaluation of its `thoughts/plans/2026-09-04-mobile-session-loss-on-401.md`
(that plan closed a different bug; this one was traced into the library and
left here for a library decision).
**Severity:** Medium. Real, not urgent — logout does not *create* the exposure,
it fails to close it. Exploitation needs the refresh token to have leaked by
other means (malware, a device backup, a shared or jailbroken device). A
consumer-side workaround exists today and needs no library change (see
"The workaround, available today" below).

## The gap

`POST /oauth/logout` revokes the presented **access token and nothing else**.
The refresh token stays valid server-side for its full TTL — 14 days in the
consumer's deployment (`SPA_REFRESH_TOKEN_TTL`). A user who logs out reasonably
believes the session is over on the server, not just on the device.

The single live path is `_handle_logout_request`
(`actingweb/handlers/oauth2_endpoints.py:800`) →
`_handle_provider_token_logout` (`:922`), which calls
`_clear_provider_token_for_actor(actor_id)` and
`session_manager.revoke_access_token(token)`. There is no `revoke_refresh_token`
or `revoke_token_chain` call anywhere on it.

### It is wider than the report says — every client shape, not just mobile

The report reasoned that mobile is uniquely exposed because it never sends the
refresh token (native keeps it in the Keychain and only ever presents it in
`/oauth/spa/token`'s JSON body), while the browser's `refresh_token` cookie is
revoked by `OAuth2SPAHandler._handle_logout`
(`actingweb/handlers/oauth2_spa.py:1470-1524`).

**`_handle_logout` is dead code.** Both integrations route `/oauth/spa/logout`
to the *main* endpoints handler, not to the SPA handler:

- `actingweb/interface/integrations/flask_integration.py:263-266` — "Delegate
  to main logout handler for consistency"
- `actingweb/interface/integrations/fastapi_integration.py:874-879` — same,
  marked deprecated in favour of `/oauth/logout`

`OAuth2SPAHandler.post()` still dispatches `"logout"` to it (`:232-233`), but
nothing routes there. So the cookie-revoking branch never runs, and the browser
is **worse off than mobile** — see the cookie-name defect below.

The dead branch is still being maintained — a later change edited
`_handle_logout`'s provider lookup alongside the two live paths, treating all
three as reachable, which is how this recurs. Re-confirm the routing before
fixing, and decide whether to delete `_handle_logout` or wire it.

### The browser also keeps its cookies — an independent, cheap fix

The live path clears the wrong cookie names. `_handle_provider_token_logout`
returns `"clear_cookies": ["oauth_token", "oauth_refresh_token", "session_id"]`
(`oauth2_endpoints.py:966`, `:980`), and both integrations delete only
`oauth_token` themselves. SPA issuance writes `access_token`, `oauth_token`
(compat) and `refresh_token` (`oauth2_spa.py:1638-1675`, HttpOnly by default).

So after `/oauth/logout` in a browser, `access_token` and `refresh_token` are
still in the cookie jar — `oauth_refresh_token` is a name nothing ever writes.
The dead `_handle_logout` gets this right: it calls `_clear_token_cookies()`,
which uses the names the issuance path actually sets. The live path drifted
from it.

**Two consequences, both independent of everything below:**

1. The browser is not merely as exposed as mobile. Mobile wipes its own
   Keychain copy, so the surviving refresh token is only usable by someone who
   already stole it. The browser **keeps a working refresh cookie on the
   device**, and it is sent automatically on the next request.
2. **The workaround does not save the browser.** The refresh cookie is HttpOnly,
   so page JavaScript cannot read it to call `/oauth/revoke` with a
   `token_type_hint`. Only a server-side fix closes the browser case.

Fixing the name list is a two-line change with no design question attached —
reuse `_clear_token_cookies()`'s list, or have the endpoints handler call it —
and it should not wait behind the storage decision below.

## The decision is already made — by `create_refresh_token`, not by us

The report presents "chain-scoped vs actor-scoped revoke" as an open question
the consumer cannot decide from outside. The library answered it when it built
token-family revocation. `create_refresh_token`
(`actingweb/oauth_session.py:409-447`) starts a fresh `chain_id` per login, and
says why in its docstring: "each device/session gets its own independent lineage
and a theft response on one device never logs out the others."
`revoke_token_chain` (`:750`) exists, is indexed on PostgreSQL, is tested
(`tests/test_oauth_session.py:426-495`), and is the production theft response.

So:

- **`revoke_all_tokens(actor_id)` (the report's candidate 1) is rejected.** It
  logs out the user's other devices, contradicting the per-device chain design
  by name. "Log out" here means this session.
- **Chain-scoped is the right semantics.** Logout ends one lineage.

## What actually blocks it

Two things, both concrete.

### 1. The login-minted access token carries no `chain_id`

`store_access_token` accepts `chain_id` (`oauth_session.py:286-292`) and the
docstring says it is "None for tokens not tied to a rotation chain (e.g. the
initial login token), which simply self-expire." Only the **rotation** site
propagates it — `oauth2_spa.py:718-727`, which passes the consumed token's
`chain_id` to both the new access and the new refresh token.

The four **login** sites mint the two tokens independently, so the access token
has no link to the refresh chain it was issued alongside:

| Site | Flow |
| --- | --- |
| `actingweb/handlers/oauth2_callback.py:737-744` | Provider callback (SPA/mobile) |
| `actingweb/handlers/oauth2_spa.py:945-950` | Mobile/native ticket grant |
| `actingweb/handlers/oauth2_spa.py:1109-1114` | JWT-bearer / native OIDC grant |
| `actingweb/handlers/oauth2_spa.py:1354-1358` | Passphrase grant |

A user who logs in and immediately logs out — the common case — presents an
access token with no chain to scope on. **Fix shape:** mint the refresh token
first, then pass its `chain_id` into `store_access_token`. Four sites, small.
(`oauth2_callback.py:812` mints a www cookie token with no refresh token at all;
leave it chain-less.)

### 2. `revoke_token_chain` on DynamoDB is a per-logout scan of the global token partition

`delete_by_chain` (`actingweb/db/dynamodb/attribute.py:365-404`) has no index on
the JSON-embedded `chain_id`: it runs a `consistent_read=True` Query over the
whole shared `OAUTH2_SYSTEM_ACTOR` partition for **both** token buckets and
filters in memory. Its own docstring licenses that cost as "Revocation is rare
(a theft event), so the scan is acceptable."

Calling it on every logout voids that justification. The partition holds every
live SPA token for every user in the deployment, so the scan grows with the user
base while the work it does is deleting two rows. PostgreSQL is unaffected —
`idx_attributes_chain_id` makes it O(chain)
(`actingweb/db/postgresql/attribute.py:650-675`).

**This is the real library decision**, and it is a storage question, not a
semantics one. Three options:

1. **Accept the scan.** Simplest, no schema change. Defensible only if logout is
   genuinely rare per deployment and the token partition stays small — measure
   before assuming, and note it interacts with the partition-size ceiling in
   `prop-list-key-prefix-scheme.md`.
2. **Store the refresh-token identity on the access-token row** so logout
   deletes exactly the two rows it means to, no scan on either backend. Needs a
   new field and legacy-token fallback; the strongest option if logout is hot.
3. **Promote `chain_id` to a top-level attribute with a GSI** — already named as
   the optimization path in `delete_by_chain`'s docstring. Fixes theft response
   and logout together, costs a GSI and a backfill.

### Also, `revoke_token_chain` is written as a theft response

It logs at WARNING ("Revoked N token(s) in chain …") and unconditionally calls
`evict_caches_for_actor`, both deliberate for suspected theft. An ordinary
logout wants a quieter entry point or a level change, or every logout in
production reads as a security event.

## Fix sketch

In `_handle_provider_token_logout`, `token_data` from `validate_access_token`
already gives `actor_id`. Take `chain_id` from the same dict and:

```python
chain_id = token_data.get("chain_id")
if chain_id:
    session_manager.revoke_token_chain(actor_id, chain_id)
else:
    session_manager.revoke_access_token(token)
```

— the same chain-with-legacy-fallback shape the rotation path already uses
(`oauth2_spa.py:698-712`). Do this **with** blocker 1, not before it: without
the login-site change the `if` is false on exactly the sessions that need it.

**Two docstrings go stale with blocker 1**, and both describe the current
behaviour as deliberate, so leaving them contradicts the code:
`store_access_token` ("None for tokens not tied to a rotation chain (e.g. the
initial login token), which simply self-expire", `oauth_session.py:301-306`) and
`revoke_token_chain` ("Access tokens with no `chain_id` (e.g. the initial login
token) are left to self-expire", `:761-765`).

Tagging the login token also **widens the theft response**: `revoke_token_chain`
will start killing the login-minted access token instead of letting it live out
its TTL. That is an improvement and the reason the second docstring exists —
name it in the change so it doesn't read as an accident.

## Testing

No test in `tests/test_oauth2_spa.py`, `tests/test_oauth2_spa_refresh_rotation.py`
or `tests/test_mobile_oauth2.py` asserts anything about a refresh token after
logout — the logout tests there cover only that the *provider* token is cleared
without calling the provider's revoke endpoint (`test_oauth2_spa.py:770`, `:792`).
The assertion to add: log in, log out with the access token, then present the
refresh token to `/oauth/spa/token` and require a 401. Cover both a login-minted
session and a rotated one, and a legacy chain-less token (must still revoke the
access token and not mass-revoke).

## The workaround, available today

`POST /oauth/revoke` — handled by `_handle_revoke` (`oauth2_spa.py:1390`) —
already accepts `{"token": "<refresh>", "token_type_hint": "refresh_token"}` in
the body and revokes that refresh token. It is routed on both integrations
(`flask_integration.py:229`, `fastapi_integration.py:817`);
`/oauth/spa/revoke` is a deprecated alias for the same handler
(`flask_integration.py:255`, `fastapi_integration.py:855-858`) — point consumers
at the canonical path.

A mobile client can therefore revoke its refresh token before calling
`/oauth/logout`, today, with no library change. **A browser SPA cannot** — its
refresh token is an HttpOnly cookie that page JavaScript cannot read. The report's candidate 2
("expose a dedicated revoke") is already shipped — which is why this is filed
as "real, not urgent" rather than queued behind a release. It does not make the
library-side fix unnecessary: correct logout should not depend on every client
remembering a second call.

## The published docs currently claim otherwise — the cheap half

`docs/guides/spa-authentication.rst:205-207` lists `/oauth/logout` as "Logout
and clear **all tokens**". That is false today for every client shape. The
endpoint reference at `:1305-1308` ("Logout and clear session") is vague enough
to survive, and the 3.11.0 note at `:833` is accurate — it is precise about the
*provider* token and silent on the refresh token.

Neither the logout example (`:809-829`) nor the Token Revocation section that
follows it tells a client to revoke its refresh token, so a consumer reading
the guide gets the belief the report describes and no hint of the workaround.

Two lines of documentation are worth doing whether or not the code fix is
scheduled: correct `:207`, and add the `token_type_hint: "refresh_token"` call
to the logout example. When the code fix lands, `:207` becomes true and the
example's extra call becomes redundant — say so then rather than leaving both.

## Related

- `thoughts/plans/2026-04-05-mobile-oauth2-support.md`,
  `thoughts/plans/2026-05-29-apple-signin-and-native-oidc-grant.md` — the flows
  that mint the chain-less login tokens.
- `mcp-cache-lifecycle-and-revocation.md` §1 — cross-process invalidation. A
  correct logout still leaves other processes serving cached state until TTL;
  same class, different layer.
- `prop-list-key-prefix-scheme.md` — the shared-partition size ceiling
  that option 1 above leans on.
