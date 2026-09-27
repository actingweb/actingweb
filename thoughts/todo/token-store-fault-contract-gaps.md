# Store-fault contract gaps outside the paths 3.15 hardened

**Provenance:** the Claude code review of PR #148 (2026-09-26), verified
against `a3950a9` on 2026-09-27. None is a regression: each path behaved
this way before 3.15, and the 3.15 plan scoped the SPA store's fault
contract out ("the SPA refresh endpoint's own fault contract is outside this
change", `oauth_session.py`, `try_mark_refresh_token_used`). They are filed
together because they are one decision: whether the fail-closed-but-
retryable contract the MCP paths got in 3.15 (`TokenStoreUnavailable` →
503 + `Retry-After`) applies to the SPA ladder and the auth-code lookup too.

**Natural home:** items 1 and 2 touch exactly the functions
`thoughts/plans/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md`
Phase 2 rewrites, and that phase moves the SPA tests onto
`tests/mcp_token_double.py`, which already injects `cas_fault` and
`chain_delete_fault`. The owner decides at that plan's approval whether
Phase 2 absorbs them; if not, they stay here.

## Items

1. **A store fault on an SPA refresh forces a re-login.**
   `oauth_session.py`, `try_mark_refresh_token_used`, catches
   `single_use.StoreFault` and returns `(False, None)`, the same shape as
   "unknown or expired". `handlers/oauth2_spa.py`'s refresh grant then
   answers 401 "Invalid or expired refresh_token", and the SPA drops its
   session on a transient backend blip. The token itself is untouched (the
   compare-and-swap did not land), so the client *could* retry. A 503 with
   `Retry-After` here is a consumer-visible behaviour change for SPA
   clients, which is why it was not folded into 3.15 late.

2. **The SPA theft response has no fault handling and no anchor.**
   `oauth_session.py`, `revoke_token_chain`, calls `delete_by_chain` with
   no `try`, no `defer_name`, and no strict read of the presented row
   afterwards, unlike `ActingWebTokenManager._revoke_chain`. Consequences by
   backend:
   - PostgreSQL's `delete_by_chain` returns 0 on a fault, so the handler
     logs nothing, still answers 401 "session revoked for security", and
     the surviving branch of the chain keeps working: a fail-open theft
     response.
   - DynamoDB's raises, possibly partway through the scan, so the SPA
     handler answers a framework 500 and the cache eviction below the call
     is skipped.
   The fix is the MCP shape: pass the presented refresh token as
   `defer_name`, and on 0 deleted read it strictly to tell "already
   revoked" from "fault", raising for the handler to answer 503.

3. **The auth-code lookups fold a fault into "not found".**
   `oauth2_server/token_manager.py`, `_search_auth_code_in_actors` and
   `_load_google_token_data`, end in `except Exception: return None`. A
   transient fault while a code is being exchanged is answered
   `invalid_grant` (400) instead of a retryable 5xx, and the user redoes the
   consent redirect. The consume itself is hardened (`consume_once` raises
   `StoreFault`, translated to `TokenStoreUnavailable`); only the reads
   before it swallow. Cheap: let `TokenStoreUnavailable`-shaped faults out
   of the two readers, as `_load_access_token` does.

## Tests

Each item wants the regression test the review noted is missing: a fault
injected into the bucket the path reads (`tests/mcp_token_double.py` has
`faulty_buckets`), asserting the new status and that the token or code is
still usable afterwards.

## Related

- `mcp-logout-fault-path-followups.md`: the same contract on `/oauth/logout`.
- `db-layer-get-bucket-or-empty.md`: bucket reads that fold a fault into
  "empty".
- `mcp-cleanup-expired-tokens-strict-read.md`: the sweep's fault handling.
