# Research: the faulted-logout contract and four follow-ups (3.15 fourth verification)

**Date:** 2026-09-26
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
(Iterations 22–23)
**Verification:** thoughts/verifications/2026-09-26-mcp-oauth-hardening-and-credential-exposure.md
**Branch:** release/3.15.0-mcp-oauth-hardening (uncommitted working tree on 9e70e47)

The `/fix_bug` record for the fourth batch. Every regression test below
fails on `9e70e47` and passes after the fix.

## 1. A faulted logout answered 200, so nothing triggered the retry (owner's option b)

- **Root cause:** Iteration 20 kept the presented token on a revocation
  fault so a retry could complete the revocation. But `/oauth/logout`
  mapped the fault to 200 "Logged out (token revocation failed)", and no
  OAuth client retries a 200. Both tokens stayed valid until someone
  happened to present the access token again.
- **Fix:**
  - The fault becomes the action `retry`, answered with 503,
    `Retry-After: 5` and `error: temporarily_unavailable`.
  - No cookies are cleared, because the client needs its token for the retry.
  - The window in which the token stays valid is unchanged (the owner chose
    503 over a `revoked` mark); it now ends when the client retries.
- **Tests:**
  - `tests/test_oauth2_logout_mcp_tokens.py::test_logout_after_a_revocation_fault_can_be_retried`
    asserts `handler.response.status_code == 503`, `Retry-After == "5"`, and
    that the retry removes both tokens.
  - `::test_faulted_bearer_logout_is_503_with_retry_after_on_fastapi` and
    `::test_faulted_bearer_logout_is_503_with_retry_after_on_flask` go
    through the real routes.

## 2. An unconfirmed delete removed the index row the retry needed

- **Root cause:** `_remove_access_token(actor_id=...)` and
  `_remove_refresh_token_row` deleted the global index row after an
  unconfirmed actor-row delete. The retry could then not resolve the token.
- **Fix:** return False before touching the index or provider row.
- **Test:**
  `tests/test_mcp_refresh_rotation.py::test_unconfirmed_delete_of_a_chainless_token_is_not_reported_revoked`
  asserts that the index row still points at the actor after the fault, and
  that a retry once the fault clears answers True and removes both rows.

## 3. The FastAPI cookie logout reported success over a handler 500

- **Root cause:** `_logout_message` read only a `message` field. The
  handler's `error_response` body has `error` and `error_description`.
- **Fix:** `_logout_outcome` returns `(success, message)`. A status of 400 or
  more, or an `error` body, is a failure.
- **Tests:**
  `tests/test_oauth2_logout_mcp_tokens.py::test_fastapi_cookie_logout_reports_a_handler_failure`
  (through the route) and `::test_logout_outcome_helper`.

## 4. Route-level coverage for the cookie branch

`::test_fastapi_cookie_logout_reports_a_failed_revocation` drives the real
`/oauth/logout` route with an `oauth_token` cookie and asserts the exact JSON
body. The branch still clears only `oauth_token`; that predates the plan and
was left as is, because the owner asked for tests only.

## 5. Client deletion left access tokens in this process's cache

- **Root cause:** `revoke_client_tokens` deleted rows but never called
  `evict_caches_for_token`. This predates the plan.
- **Fix:** evict each of the client's access tokens after its delete,
  whether or not the delete was confirmed.
- **Test:**
  `tests/test_mcp_token_store_faults.py::test_revoke_client_tokens_evicts_the_access_tokens_from_the_cache`.
- **Reuse:** `mcp.invalidation.evict_caches_for_token`.

## Release decision

Everything stays in **3.15.0**. The 503 on a faulted MCP logout refines
3.15's own new logout behaviour; it is documented in `CHANGELOG.rst` and
`docs/migration/v3.15.rst`, and the consumer message says clients should
retry a 503 logout.
