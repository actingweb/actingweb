# Research: store faults read as results, and the MCP logout gap (3.15 re-verification)

**Date:** 2026-09-25
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
(Iterations 16–19)
**Verification:** thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure-2.md
**Branch:** release/3.15.0-mcp-oauth-hardening (uncommitted working tree on 71da8ea)

The `/fix_bug` record for the second batch. The first batch is
`2026-09-25-mcp-oauth-hardening-verification-fixes.md`. Each section gives
the root cause (checked against the tree) and the regression tests, which
fail on `253ee76` and pass after the fix.

## The common root cause

The backends report faults as ordinary results, and the single-use and
revocation logic took those results at face value:

| Call | DynamoDB on a fault | PostgreSQL on a fault |
| --- | --- | --- |
| `conditional_update_attr` | `False` (`db/dynamodb/attribute.py`, `except Exception: return False`) | `False` (logs, returns False) |
| `delete_attr` (via `set_attr(data=None)`) | `True` (swallows) | `False` |
| `delete_attr_conditional` | `False` | `False` |
| `delete_by_chain` | raises, possibly after deleting some rows | `0` |
| `set_attr` | upsert (re-creates a deleted row) | upsert |

The backends' fault semantics are **not** changed; they are shared with every
other caller in the library. The fixes sit in the callers, using primitives
that already exist (`get_attr_strict`, `delete_attr_conditional`,
`delete_by_chain`), plus two additive protocol keywords.

## 1. A faulted compare-and-swap deleted a valid refresh token (High)

- **Root cause:**
  - `consume_once` read `False` as "lost the race" and re-read with the
    non-strict `get_attr`, which found the unused row.
  - `refresh_access_token` then ran
    `if not used_at: self._remove_refresh_token(refresh_token)`.
  - A code exchange read the same fault as "already used".
- **Fix:**
  - The loser re-reads with `get_attr_strict`. A row that is still unused, or
    a re-read that faults, raises `single_use.StoreFault`.
  - The MCP `_consume` turns that into `TokenStoreUnavailable`, which the
    token endpoint answers with `server_error`.
  - The SPA `try_mark_refresh_token_used` catches it and returns
    `(False, None)`, the 401 that path always gave. That is a deliberate
    non-change: the SPA endpoint's fault contract is outside this plan.
  - A consumed row without `used_at` is refused, never deleted.
- **Tests:**
  - `tests/test_mcp_refresh_rotation.py::test_cas_fault_is_a_store_fault_not_a_dead_token`
    asserts `pytest.raises(TokenStoreUnavailable)`, that the token is still
    stored and unused, and that it rotates once the fault clears.
  - `::test_cas_fault_with_unreadable_store_is_a_store_fault`.
  - `tests/test_mcp_auth_code_single_use.py::test_cas_fault_leaves_the_code_exchangeable`.
- **Reuse:** `get_attr_strict`.

## 2. `/oauth/logout` never revoked an MCP token (Medium)

- **Root cause:** `_handle_provider_token_logout` used only the SPA session
  manager. `ActingWebTokenManager.revoke_token` had one caller,
  `ActingWebOAuth2Server.handle_logout_request`, and nothing routes to it.
  The 3.15 changelog and migration guide claimed the opposite.
- **Fix (the owner's choice: route, not re-word):**
  - A token carrying the MCP prefix `aw_` goes to the new
    `_handle_mcp_token_logout`, which calls `revoke_token`.
  - The prefix is unambiguous: SPA tokens come from `config.new_token()`,
    which is hex and cannot contain `_`.
  - A store fault keeps the route's always-success contract, with the message
    "Logged out (token revocation failed)".
  - `handle_logout_request` stops answering "Successfully logged out" when
    revocation raised.
- **Tests** (all in `tests/test_oauth2_logout_mcp_tokens.py`):
  - `::test_logout_revokes_the_mcp_token_and_its_chain` asserts that both
    rows are gone and that the consumed predecessor cannot rotate.
  - `::test_logout_reports_a_revocation_fault_and_still_drops_the_token`.
  - `::test_sdk_logout_does_not_claim_success_on_a_fault`.
  - `::test_a_session_token_still_goes_to_the_session_store` pins the
    unchanged SPA path (it passes on both versions).

## 3. The consumed-row TTL re-stamp could revive a revoked row (Medium)

- **Root cause:** after winning the swap, `consume_once` wrote the row again
  with `set_attr(..., ttl_seconds=)`. That is an upsert on both backends, so a
  revocation between the two writes was undone, and the re-created row could
  rotate within the grace period.
- **Fix:**
  - `conditional_update_attr` gains an additive `ttl_seconds=` (wrapper,
    protocol, both backends, the three test doubles), and the swap writes the
    TTL itself. The second write is gone.
  - The `Attributes` wrapper passes the keyword only when it is given, so an
    older custom backend keeps working for every other caller.
  - Residual: a winner whose chain is revoked between swap and mint still
    gets its own pair. That needs a transaction.
- **Test:**
  `tests/test_mcp_refresh_rotation.py::test_revocation_between_swap_and_mint_is_not_undone`
  deletes the row right after a successful swap and asserts that it stays
  deleted and that a replay answers None.

## 4. A revocation fault skipped removing the presented token and evicting (Medium)

- **Root cause:** `revoke_token` called `_revoke_chain` first. On a fault that
  raised before `_remove_access_token(token)`, before
  `evict_caches_for_token`, and before `_revoke_chain`'s own
  `evict_caches_for_actor`. The "two revocations race" case, which the
  docstring called "fails safe", took the same path.
- **Fix:**
  - `_revoke_chain` evicts in a `finally`.
  - `revoke_token` removes the presented token in a `finally`.
  - With `anchor=`, a delete that removed nothing reads the anchor strictly:
    if it is gone, a concurrent revocation already did the work (INFO,
    returns 0); if it is present, that is a fault.
- **Tests** (in `tests/test_mcp_refresh_rotation.py`):
  - `::test_revocation_fault_still_removes_the_presented_token_and_evicts`
  - `::test_a_chain_revoked_concurrently_is_not_a_fault`

## 5. A partial DynamoDB chain delete could remove the replayed row (Medium)

- **Root cause:** DynamoDB's `delete_by_chain` deletes row by row. A failed
  `t.delete()` after the replayed row was already gone left nothing to retry
  from.
- **Fix:** `delete_by_chain(defer_name=)`, additive on the protocol and both
  backends. DynamoDB deletes that row last; PostgreSQL's single DELETE is
  atomic and ignores it. `_revoke_chain` passes the anchor's name.
- **Test:**
  `tests/test_mcp_refresh_rotation.py::test_partial_chain_delete_leaves_the_replayed_token_to_retry_from`.
  The double's `"partial"` fault deletes every row but the last and then
  raises.
- **Both backends:** the PostgreSQL path is unchanged apart from accepting
  the keyword; the Full tier runs the backend rotation suite on both.

## 6–8. Unchecked deletes (Medium, Low, Low)

- **Root cause:**
  - `delete_client`, the rotation's delete of the old access token, and
    `revoke_client_tokens` ignored the delete result.
  - Even a checked result is meaningless on DynamoDB, which answers True for
    a failed delete.
  - `revoke_client_tokens` also went back through the global index for rows
    whose actor it already knew.
- **Fix:**
  - New `single_use.delete_confirmed()`: `delete_attr_conditional`, then
    `get_attr_strict` when that answers False.
  - `_remove_access_token(actor_id=...)` and the new
    `_remove_refresh_token_row` return whether the row is confirmed gone and
    log ERROR when it is not.
  - `revoke_client_tokens` counts confirmed deletes and raises naming the
    unconfirmed ones.
  - `delete_client` confirms both the client row and the index row. It
    answers False only when neither is gone, because the token endpoint needs
    both, so either one gone disables the client.
- **Tests:**
  - `tests/test_mcp_token_store_faults.py::test_delete_client_fails_when_nothing_is_confirmed_deleted`
  - `::test_revoke_client_tokens_counts_only_confirmed_deletes`
  - `tests/test_mcp_refresh_rotation.py::test_unconfirmed_delete_of_the_old_access_token_is_logged`
  - `::test_delete_client_succeeds_when_its_index_row_is_gone` pins the rule
    (it passes on both versions).
- **Reuse:** `delete_attr_conditional`, `get_attr_strict`.

## 9. The token-first `clientInfo` lookup lapsed (Low)

- **Root cause:** the token entry expires after ten minutes and is not carried
  over to a rotated token. The lookup then fell back to the `Mcp-Session-Id`
  entry, which any unauthenticated `initialize` naming the session could
  overwrite.
- **Fix:**
  - Entries carry the owning actor, and an unowned write cannot replace a
    fresh owned entry.
  - On an authenticated request, a session entry is used only when it is
    this actor's, or unowned (it is then claimed). Each hit resets its age.
  - Residual: after ten idle minutes the gap reopens for an attacker who
    knows the session id.
- **Tests** (in `tests/test_mcp_client_info_cache.py`; all fail on
  `253ee76`):
  - `::test_expired_token_entry_does_not_hand_over_to_a_spoofed_session`
  - `::test_rotated_token_uses_its_own_session_entry`
  - `::test_a_session_entry_owned_by_another_actor_is_ignored`
  - `::test_an_unowned_session_entry_is_claimed_on_first_authenticated_use`
  - `::test_an_active_session_entry_does_not_lapse`
  - `::test_token_entry_wins_over_a_session_entry`, which now asserts that the
    owned entry survives the spoof

## 10. Smaller items (Low)

- **`initialize` swallowed every exception** around its authenticated part.
  It now logs WARNING. Test:
  `tests/test_mcp_client_info_cache.py::test_initialize_logs_a_token_store_fault`.
- **The token-eviction keep time (120 s) was shorter than a stalled read
  could take.** A fill that snapshotted before the highest pruned sequence is
  now refused. Test:
  `tests/test_mcp_trust_cache_key.py::TestRotationEvictionDuringFill::test_a_fill_older_than_a_pruned_eviction_is_refused`.
  The same class drives the real fill in `authenticate_and_get_actor_cached`,
  which no test did before.
- **`PurgeThrottle` stopped purging when the wall clock stepped back.** It
  now uses `time.monotonic()`, with `None` meaning "never ran". Test:
  `tests/test_single_use.py::test_a_wall_clock_step_back_does_not_stop_the_purge`.
- **Stale docstrings:**
  - `revoke_token`'s legacy claim is corrected. The removed helpers were
    stubs, so this is not a regression.
  - The `access_token_id` comment is corrected.
  - `TokenStoreUnavailable` lists every raiser.
  - `refresh_access_token` and `revoke_token` gain `Raises:`.
  - `_snapshot_bucket` describes the PostgreSQL fault shape correctly.
  - `load_client_strict` uses `self.clients_bucket`.

## Release decision

Everything stays in **3.15.0**, a minor release with a migration guide. The
additions are additive:
- two keyword-only backend protocol arguments with defaults (documented for
  custom backends in `docs/migration/v3.15.rst`);
- `single_use.StoreFault` and `delete_confirmed`, both internal;
- one route behaviour change: `/oauth/logout` with an MCP token, in the
  changelog as a **Behavior change**;
- `delete_client` answers False when nothing was confirmed deleted.
