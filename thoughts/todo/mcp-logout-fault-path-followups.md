# TODO: `/oauth/logout` fault-path follow-ups (Lows from the 3.15 verifications)

**Status:** Open. Filed 2026-09-26 from
`thoughts/verifications/2026-09-26-mcp-oauth-hardening-and-credential-exposure-2.md`
(issues 5–8), after the owner chose to close the 3.15 verify/iterate loop on
"no High or Medium and no regression". None blocks `3.15.0rc1`.
**Severity:** Low, all four.

## Items

1. **The FastAPI cookie branch drops the 503 and `Retry-After`.** A request
   carrying an `oauth_token` cookie *and* an MCP bearer token takes the
   cookie branch (`fastapi_integration.py`, `oauth2_logout`); the handler
   prefers the bearer. On a store fault the AJAX answer is HTTP 200 with
   `success: false`, the non-AJAX answer is a plain 302, and both clear the
   cookie. Pass the handler's status and `Retry-After` through on a failed
   `_logout_outcome`, and do not clear the cookie. The mixed request is rare:
   the cookie normally holds a hex session token.
2. **`revoke_client_tokens` cache eviction.** `evict_caches_for_token(name)`
   runs only when `_remove_access_token` returns, so the raising path skips
   it; and its default `actor_wide=True` bumps the process-wide cache
   generation once per token of the deleted client. Evict in a `finally`
   with `actor_wide=False`, then `evict_caches_for_actor(actor_id)` once
   after the loop.
3. **Cross-origin SPAs cannot read `Retry-After`.** The logout CORS headers in
   both integrations set no `Access-Control-Expose-Headers`, and
   `Retry-After` is not CORS-safelisted. Add
   `Access-Control-Expose-Headers: Retry-After` on logout responses.
4. **The route tests stub the changed dispatch.** `_patched_logout` in
   `tests/test_oauth2_logout_mcp_tokens.py` replaces
   `_handle_provider_token_logout`, so the MCP-prefix dispatch and the
   fault-to-`retry` mapping run through a route only with a synthetic dict;
   `test_fastapi_cookie_logout_reports_a_handler_failure` asserts no status.
   Add one route test with a real token manager and an injected delete
   fault, including the cookie-plus-bearer case.

## Related

- `logout-does-not-revoke-refresh-chain.md`: the SPA session store's own
  logout gap, a separate store.
- `mcp-cache-lifecycle-and-revocation.md`: cross-process invalidation.
