# Verification: 3.15.0 — MCP OAuth hardening and two credential exposures (third run)

**Date:** 2026-09-25
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Research:** thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md,
thoughts/research/2026-09-25-mcp-oauth-hardening-verification-fixes.md,
thoughts/research/2026-09-25-mcp-oauth-hardening-verification-fixes-2.md
**Branch:** release/3.15.0-mcp-oauth-hardening
**Commit:** 6748937 (the code; `800b917` records the second verification and
the fix notes)

This is the third verification of the plan today, so the file takes a `-3`
suffix, following the `-2` convention: deduced, not confirmed, because
`thoughts/README.md` says nothing about two runs on one date. This run covers
Iterations 16–19, which fix the second run's issues 1–10. Phase 4 has not
started.

## Automated Check Results

- **Browser QA:** Not run. No iteration since the first run touched anything
  a user sees. The authorize form has no provider credentials in this
  session; the Phase 4 connector pass exercises it.
- **Second opinion:** the outside-voice agent ran two providers: codex
  (`codex exec -s read-only`, outside the sandbox) and a fresh-context Claude
  (Opus 5.5). A separate fresh-context agent ran the high-effort code review
  and the security review over the same diff. The security review found
  nothing at or above confidence 7. The two reviews each found Issue 1 below
  without seeing the other's result.
- The Full tier ran on the tree that became `6748937`. The run started
  before the commit, and nothing changed between them.
  - `ruff check`: pass.
  - `ruff format --check`: pass (397 files).
  - `pyright`: pass (0 errors, 0 warnings).
- `make test-all-parallel`, DynamoDB: 3665 passed, 31 skipped, **1 error**.
  - The error was in
    `tests/test_hot_path_n_plus_one.py::TestPropertyStoreBulkReads::test_items_and_values_are_bulk_reads`.
    It is the DynamoDB Local lock-timeout flake seen in the first run.
  - Re-run sequentially (the file alone): 11 passed. It is not a regression,
    and the file is outside this plan.
- `make test-all-parallel`, PostgreSQL: 3554 passed, 140 skipped, 2 failed.
  - The failures are
    `tests/performance/test_backend_performance.py::TestSubscriptionPerformance::test_subscription_create_performance`
    and `::test_subscription_read_performance`, with
    `invalid input syntax for type boolean`.
  - They are already filed:
    `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`.
- `sphinx-build -W ...`: pass.
- `tests/integration/test_mcp_refresh_rotation_backend.py`: 4 passed on
  DynamoDB and 4 passed on PostgreSQL. This file includes the new
  `TestBackendKeywordsForSingleUse`, and was run on its own during
  Iteration 19.

## Phase Verification

### Phases 1–3 with Iterations 1–19 — ISSUES FOUND (one Medium regression from Iteration 17)

Where each security property of this batch is pinned (the project addendum
asks for a named test and its assertion):

- **A faulted swap is not "already used":**
  - `tests/test_mcp_refresh_rotation.py::test_cas_fault_is_a_store_fault_not_a_dead_token`
    asserts `pytest.raises(TokenStoreUnavailable)`, that the token is still
    stored and unused, and that it rotates after the fault clears.
  - `tests/test_mcp_auth_code_single_use.py::test_cas_fault_leaves_the_code_exchangeable`
    covers codes.
  - Code: `actingweb/single_use.py`, the strict re-read after a failed
    `conditional_update_attr`.
- **A revocation is not undone by the TTL write:**
  `tests/test_mcp_refresh_rotation.py::test_revocation_between_swap_and_mint_is_not_undone`.
  It pins that the consumed row is not re-created. It does not pin the
  winner's mint (accepted residual; see Issue 8).
- **A partial chain delete leaves the replayed token for a retry:**
  `::test_partial_chain_delete_leaves_the_replayed_token_to_retry_from`. This
  holds on the theft path. `revoke_token` undoes it (Issue 1).
- **`/oauth/logout` revokes an MCP token's chain:**
  `tests/test_oauth2_logout_mcp_tokens.py::test_logout_revokes_the_mcp_token_and_its_chain`
  asserts that both rows are gone and that the consumed predecessor cannot
  rotate.
- **Confirmed deletes:**
  - `tests/test_mcp_token_store_faults.py::test_delete_client_fails_when_nothing_is_confirmed_deleted`
  - `::test_revoke_client_tokens_counts_only_confirmed_deletes`
- **Session `clientInfo` ownership:**
  `tests/test_mcp_client_info_cache.py::test_expired_token_entry_does_not_hand_over_to_a_spoofed_session`,
  `::test_a_session_entry_owned_by_another_actor_is_ignored`.

**Deviations from plan:**
- The token-eviction window is closed with a "pruned-through" floor rather
  than a longer keep time. The reviewers traced it: pruned sequence numbers
  never exceed a current snapshot, so it cannot refuse fills spuriously.
  Acceptable.
- The SPA store keeps answering 401 on a consume fault; this is a deliberate
  non-change. But the changelog sentence overstates it (Issue 6).

**Test double fidelity:** `cas_fault` and `delete_faults` match both
backends. There are two gaps, neither on a tested path:
- the double's `get_attr_strict` ignores TTL, while both backends treat an
  expired row as absent;
- the order `defer_name` produces is pinned only by the double, because the
  integration test proves the whole chain is deleted but cannot observe the
  order.

### Phase 4: Release — NOT STARTED

The consumer message now includes the `/oauth/logout` change and the backend
keywords (plan, Phase 4, `[Updated 2026-09-25]`). It is accurate against the
tree, apart from Issue 1's fault path.

## Previous Verification

**Previous:** thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. CAS fault deletes a valid refresh token (High) | Fixed | `single_use.py` strict re-read and `StoreFault`; Iteration 16 |
| 2. No route revokes MCP tokens; docs claimed `/oauth/logout` does | Fixed for `aw_` access tokens; the docs now match | `oauth2_endpoints.py:1010`; Iteration 18. `rt_` tokens are not routed (Issue 1) |
| 3. Restamp re-creates a revoked row | Fixed; the winner's mint is an accepted residual | `conditional_update_attr(ttl_seconds=)`; Iteration 16 |
| 4. Revocation fault skips removal and eviction | Fixed, but the fix causes Issue 1 | `token_manager.py:534-547`, `:562-581`; Iteration 17 |
| 5. Partial DynamoDB delete loses the replayed row | Fixed on the theft path; undone in `revoke_token` (Issue 1) | `token_manager.py:717`; Iteration 17 |
| 6. `delete_client` unchecked | Fixed | `client_registry.py` `delete_confirmed` for the row and the index |
| 7. Old access-token delete invisible | Fixed | `_remove_access_token` returns the confirmed result and logs ERROR |
| 8. `revoke_client_tokens` counts unconfirmed deletes | Fixed; one broad `except` remains (Issue 3) | Iteration 17 |
| 9. Token-first `clientInfo` lapses | Fixed for clients that send `Mcp-Session-Id` | Iteration 19; Issues 4 and 5 are narrower residuals |
| 10. Smaller items | Fixed | Iteration 19 |

## Remaining Tasks

- [ ] Fix Issue 1, and preferably 2 and 6, through `/iterate_plan` before
      `3.15.0rc1`.
- [ ] Phase 4 in full: rc1, the four-connector pass, the demo deployment,
      the stable tag, and the consumer message.
- [ ] Manual curl pass (Phase 1 Verification): record it as superseded by
      the rc connector pass, or run it.

## Issues Found

### 1. After a failed chain revocation, logout removes the token needed to retry it

**Severity:** Medium (the outside voice rates it High)
**Description:** Iteration 17 made `_revoke_chain` keep its anchor row, the
presented token, so a fault leaves something to retry from
(`token_manager.py:717` `defer_name=anchor[1] if anchor else None`). The same
iteration made `revoke_token` delete that row in a `finally` whatever
happened (`:534-535`, "The presented token goes even when its chain could
not be revoked"). The follow-up at the end of that iteration then made the
delete bypass the index and confirm, so on a fault it now succeeds.

The failing sequence, for `/oauth/logout` with an `aw_` access token:
1. `delete_by_chain` faults. On DynamoDB that is a throttle before the
   refresh bucket is reached; on PostgreSQL the delete returns 0.
2. The `finally` deletes the access token.
3. The chain's `rt_` refresh token stays live and keeps rotating for up to
   30 days.
4. The user is told "Logged out (token revocation failed)", with success.

Nothing can retry:
- the access token no longer resolves;
- `/oauth/logout` sends `rt_` tokens to the SPA store
  (`oauth2_endpoints.py:1010` dispatches on `aw_` only);
- there is no MCP revocation route.

The theft path is not affected: it calls `_revoke_chain` directly and never
deletes the anchor itself.
**Location:** `actingweb/oauth2_server/token_manager.py:534-547`, `:562-581`,
`:717`
**Recommendation:** when `_revoke_chain` raises, evict the token from the
cache but keep its row, so the next presentation retries the whole
revocation. Remove the presented token in the `finally` only when there is
no chain (legacy). Add a test: `chain_delete_fault="zero"`, logout, clear the
fault, log out again, and assert that the chain's refresh token is gone.

### 2. `revoke_token` answers True when the presented token's delete was not confirmed

**Severity:** Medium
**Description:** the `finally` blocks ignore the return values of
`self._remove_access_token(token, actor_id=actor_id, ...)` (`:540-544`) and
`self._remove_refresh_token_row(actor_id, token)` (`:567`), then
`return True` (`:548`, `:582`). Take a pre-3.15 access token (no chain)
presented during a DynamoDB fault:
- `delete_confirmed` answers False and logs ERROR;
- `revoke_token` still answers True;
- `/oauth/logout` reports "Successfully logged out" while the token stays
  valid for up to an hour.

That is the "report work that did not happen" pattern the
`TokenStoreUnavailable` docstring says the module removed.
**Location:** `actingweb/oauth2_server/token_manager.py:540-548`, `:567`,
`:582`
**Recommendation:** raise `TokenStoreUnavailable` when the presented token's
delete is not confirmed. Fix it together with Issue 1.

### 3. `revoke_client_tokens` still wraps both loops in one broad `except`

**Severity:** Low
**Description:** `except Exception as e: logger.error(f"Error revoking tokens
for client {client_id}: {e}")` (`token_manager.py:1554-1555`) catches
anything raised mid-loop. A partial `revoked_count` is then returned without
a raise, and `delete_client` logs success. This is narrow now, because
`delete_confirmed` and `_remove_google_token_data` swallow their own errors;
an index-row `delete_attr` raising is the remaining route (not confirmed).
The structure predates this plan.
**Location:** `actingweb/oauth2_server/token_manager.py:1554`
**Recommendation:** catch per token, count the failure in `unconfirmed`, and
let the final raise fire.

### 4. An authenticated actor can replace another actor's owned session entry

**Severity:** Low
**Description:** the overwrite guard in `_cache_client_info` covers unowned
writes only (`and existing.get("owner")`, `mcp.py:2911`). An owned write from
actor B, an authenticated `initialize` carrying A's `Mcp-Session-Id`,
replaces A's entry. A's later lookups then see `owner != actor_id` and get
None. That blanks A's fallback `clientInfo`; it does not inject anything. It
needs A's client-chosen session id.
**Location:** `actingweb/handlers/mcp.py:2905-2920`
**Recommendation:** an owned write must not replace a fresh entry owned by a
different actor.

### 5. Claiming an entry does not move it in the size-bound eviction order

**Severity:** Low
**Description:** `_claim_client_info` resets `data["timestamp"]` (`mcp.py:2982`)
but leaves the entry where it is in the dict, and the size cap evicts in
insertion order (`while len(_mcp_client_info_cache) > MCP_CLIENT_INFO_CACHE_MAX`,
`:2932`). Enough new sessions (more than 1000, for example unauthenticated
`initialize` calls with random session ids) evict an active owned entry.
That reopens, without any idle time, the re-seeding window the docstring
says needs ten idle minutes.
**Location:** `actingweb/handlers/mcp.py:2932`, `:2981-2982`
**Recommendation:** in the claim, pop the entry and re-insert it.

### 6. The changelog says every consume fault answers `server_error`; the SPA store answers 401

**Severity:** Low
**Description:** `CHANGELOG.rst:79-81`: "A store fault while a refresh token
or an authorization code is being consumed answers ``server_error`` and
leaves it usable". The SPA store shares `consume_once`, but maps `StoreFault`
to `(False, None)` (`oauth_session.py:742-747`), which `oauth2_spa.py:628`
answers with 401 "Invalid or expired refresh_token". The contract's entry
style requires exactly-true wording.
**Location:** `CHANGELOG.rst:79`
**Recommendation:** say "an MCP refresh token", or add that the SPA endpoint
still answers 401 on that fault.

### 7. A lost swap response can burn an authorization code

**Severity:** Low
**Description:** if a code's `item.update` succeeds on DynamoDB but the
response is lost, the backend answers False
(`db/dynamodb/attribute.py:316-318`). The strict re-read then sees `used`,
and the exchange refuses the code; the user re-authorizes. It fails closed
and is rare. A refresh token in the same case lands in the grace window and
rotates, which is fine. It contradicts the changelog's "never read as
already used" only at the edge.
**Location:** `actingweb/single_use.py` (the loser branch)
**Recommendation:** optional. Compare the stored `used_at` with the value
this call wrote, or accept it and soften the changelog wording.

### 8. Smaller items (Low)

- **A test docstring overstates.**
  `test_revocation_between_swap_and_mint_is_not_undone`
  (`tests/test_mcp_refresh_rotation.py:528`) says the revocation "stays in
  force". The winner still mints a pair in the revoked chain, which is the
  accepted residual; the docstring should say so.
- **The FastAPI cookie logout discards the handler's message** (pre-existing).
  `fastapi_integration.py:766-786` returns "Logged out successfully" when an
  `oauth_token` cookie is present, so "token revocation failed" never reaches
  a browser that also sent an MCP bearer token.
- **The `StoreFault` ERROR line lacks context.** "Compare-and-swap in
  {bucket} failed with no competing consume" (`single_use.py`) names no actor
  or masked name, so a persistent CAS mismatch cannot be told from a
  transient fault. Unverified side note: a stored row whose serialisation
  never matches would now answer `server_error` on every attempt, where it
  used to be "already used"; no such rows are known.

## Overall Assessment

Every issue from the second run is fixed, and pinned by tests that fail on
`253ee76` and pass on `6748937`. The Full tier is clean on both backends,
apart from a DynamoDB Local lock flake that passed on its own and the two
benchmark failures already filed. The new protocol keywords run on real
DynamoDB and PostgreSQL. The security review found nothing new at the
reporting bar:
- `/oauth/logout` needs possession of the `aw_` token, and a cookie never
  routes to the MCP store;
- the PostgreSQL TTL fragment is a constant;
- no raw credential is newly logged.

One regression came in with Iteration 17 (Issue 1). Two fixes meant to make
revocation safe work against each other in `revoke_token`, and a logout that
hits a store fault can leave the chain's refresh token live with nothing
left to retry the revocation. It is narrow (a fault during logout) but
permanent, and it should be fixed, with Issue 2, through `/iterate_plan`
before `3.15.0rc1`. The rest is Low. The UI was not exercised in a browser.
The plan stays `active` with no `verified:` link, because Phase 4 has not
started. This verification covers Phases 1–3 and Iterations 1–19.
