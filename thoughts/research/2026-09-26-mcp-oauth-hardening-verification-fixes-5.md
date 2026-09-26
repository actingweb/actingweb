# Research: the revocation invariant that ends the fault-path loop (3.15 fifth verification)

**Date:** 2026-09-26
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
(Iteration 24)
**Verification:** thoughts/verifications/2026-09-26-mcp-oauth-hardening-and-credential-exposure-2.md
**Branch:** release/3.15.0-mcp-oauth-hardening (uncommitted working tree on 7e9c0b9)

The `/fix_bug` record for the fifth batch, and the note on why there were
five. Every regression test below fails on `fade3da` and passes after the
fix.

## Why this went round four times

One question, "what happens to the presented token when a revocation hits a
store fault?", was answered by mechanism four times, each time buying one
property and paying with the other:

| Iteration | Mechanism | Gained | Broke |
| --- | --- | --- | --- |
| 17 | `finally` deletes the presented token | dead at once | retry impossible |
| 20 | keep the token on a fault, re-raise | retry possible | token valid, and a 200 nobody retries |
| 22 | 503, and keep the *index row* on an unconfirmed delete, in the shared helpers | retry reaches the token | rotation and client deletion leave tokens valid for an hour |

Two causes. The invariant was never written down. And twice (17 and 22) a
shared helper was changed to serve the one caller that retries,
`revoke_token`, out of four callers.

## The invariant (now in the plan's Decisions)

Every token lookup resolves through the global index row, so deleting it
*is* the revocation as far as any worker is concerned. Therefore:

- **Single-token removal** (rotation's old access token, client deletion, a
  chainless token, the presented token after its chain is gone): delete the
  index row first, unconditionally. The token is dead everywhere at once.
  Then confirm the actor row; when that is unconfirmed, the leftover row is
  cleanup for TTL or the PostgreSQL purge, and the caller is told
  (`revoke_token` raises, logout answers 503). Presenting the token again
  finds "unknown", which is answered as revoked: the retry confirms.
- **Chain fault**: keep the presented token whole, as the handle to the rest
  of its chain, and let the 503 send the client back to retry. This is the
  owner's option (b) from the fourth run, and the one bounded window that
  remains: it ends when the client retries.

The property, not the mechanism, is what the new test pins:
`tests/test_mcp_refresh_rotation.py::TestAnUnconfirmedDeleteStillRevokes`
injects an unconfirmed delete into each revocation path (rotation,
`revoke_token` for an access and for a refresh token, client deletion) and
asserts `validate_access_token(token) is None` (and
`refresh_access_token(rt) is None`) afterwards, whatever else the path did.
Had it existed, Iteration 22 would have failed it before any review.

## 1. Rotation left the old access token valid after an unconfirmed delete (High)

- **Root cause:** Iteration 22's early `return False` in
  `_remove_access_token(actor_id=...)` came before the index delete.
  `refresh_access_token` ignores the result and never presents the old token
  again, so nothing retried.
- **Fix:** the index row (and the provider row) are deleted first,
  unconditionally; the actor row's delete is confirmed after.
- **Tests:**
  - `::TestAnUnconfirmedDeleteStillRevokes::test_rotation`
  - `::test_unconfirmed_delete_of_the_old_access_token_is_logged`, which now
    also asserts `validate_access_token(old) is None`.

## 2. The same in client deletion (Medium)

- **Root cause:** `revoke_client_tokens` uses the same helper, and
  `delete_client` is never re-run.
- **Fix:** the same; `_remove_refresh_token_row` gets the same order.
- **Test:** `::TestAnUnconfirmedDeleteStillRevokes::test_client_deletion`.

## 3. `revoke_token` under the invariant

- The refresh branch removes both the linked access token and the presented
  refresh token whatever the other's outcome (before, an unconfirmed access
  delete skipped the presented token "so it stayed reachable").
- The docstring states the two outcomes above.
- **Test:**
  `::test_unconfirmed_delete_of_a_chainless_token_is_not_reported_revoked`
  now asserts that the index row is gone and the token does not validate,
  and that a retry answers `False` (confirms), instead of asserting that the
  token was reachable.

## 4. A lookup fault on logout no longer evicted the cached token (Medium)

- **Root cause:** `_handle_logout_request` cleared the MCP cache only on
  `action == "success"`; Iteration 22 mapped the fault to `retry`, and a
  fault in `_load_access_token` happens before `revoke_token` evicts.
- **Fix:** clear the cache on `retry` too.
- **Test:**
  `tests/test_oauth2_logout_mcp_tokens.py::test_a_lookup_fault_on_logout_still_evicts_the_cached_token`
  faults the index bucket, asserts the 503 body and that the token is gone
  from `_token_cache`.

## 5–8. Filed, not fixed

The four Lows of the fifth run are in
`thoughts/todo/mcp-logout-fault-path-followups.md` with an `INDEX.md` row.
This is the exit rule for the loop: fix only High and Medium and
regressions; a run with none of those closes the loop, whatever Lows it
lists. A fresh adversarial reviewer on any non-trivial diff produces Lows
indefinitely, and fixing every one in the same loop is what kept the diff
growing.

## Docs

`CHANGELOG.rst` and `docs/migration/v3.15.rst` state the invariant and the
one exception in place of the "left in place, stays valid until retry"
wording.

## Release decision

Everything stays in **3.15.0**. No route, field or signature changes; the
503 contract from the fourth run is unchanged.
