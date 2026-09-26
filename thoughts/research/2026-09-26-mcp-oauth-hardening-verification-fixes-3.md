# Research: the revocation retry regression and the Lows (3.15 third verification)

**Date:** 2026-09-26
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
(Iterations 20–21)
**Verification:** thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure-3.md
**Branch:** release/3.15.0-mcp-oauth-hardening (uncommitted working tree on 800b917)

The `/fix_bug` record for the third batch. The earlier batches are
`2026-09-25-mcp-oauth-hardening-verification-fixes.md` and `-fixes-2.md`.
Every regression test below fails on `6748937` and passes after the fix.

## 1. A faulted revocation removed the row its retry needed (Medium, a regression)

- **Root cause:** Iteration 17 added two safeguards that work against each
  other in `revoke_token`:
  - `_revoke_chain(anchor=)` with `delete_by_chain(defer_name=)` keeps the
    presented token's row through a fault, so a retry can start from it;
  - a `finally` in `revoke_token` then deleted that row whatever happened,
    and its last follow-up made that delete confirmed, so it succeeded even
    during a fault.

  On `/oauth/logout` the `aw_` access token went, the chain's `rt_` refresh
  token lived on, and nothing could retry: the access token no longer
  resolved, and `/oauth/logout` does not route `rt_` tokens to the MCP store.
- **Fix:** on `TokenStoreUnavailable` from `_revoke_chain`, `revoke_token`
  evicts this process's cache and re-raises, leaving the row. The presented
  token is deleted only after the chain is revoked, or when it has no chain.
- **Tests:**
  - `tests/test_mcp_refresh_rotation.py::test_revocation_fault_keeps_the_presented_token_to_retry_from[zero|raise|partial]`
    asserts that the token is evicted from the cache but its row stays, and
    that a second `revoke_token` removes the chain's refresh token.
  - `::test_refresh_token_revocation_fault_keeps_it_to_retry_from`.
  - `tests/test_oauth2_logout_mcp_tokens.py::test_logout_after_a_revocation_fault_can_be_retried`,
    end to end through `/oauth/logout`.

## 2. `revoke_token` returned True for an unconfirmed delete (Medium)

- **Root cause:** the `finally` blocks ignored the booleans that
  `_remove_access_token(actor_id=...)` and `_remove_refresh_token_row` began
  returning in Iteration 17.
- **Fix:**
  - An unconfirmed delete raises `TokenStoreUnavailable`.
  - For a refresh token, the linked access token is deleted first and the
    presented token last, so a failure leaves the presented token to retry
    with.
- **Test:**
  `tests/test_mcp_refresh_rotation.py::test_unconfirmed_delete_of_a_chainless_token_is_not_reported_revoked`
  asserts `pytest.raises(TokenStoreUnavailable)` and that the row remains.

## 3. `revoke_client_tokens` swallowed a mid-loop failure (Low)

- **Root cause:** one `except Exception` around both loops, a structure that
  predates this plan.
- **Fix:** a `try` per token; a failure counts as unconfirmed and feeds the
  existing raise.
- **Test:**
  `tests/test_mcp_token_store_faults.py::test_revoke_client_tokens_counts_a_raising_delete_and_goes_on`.

## 4–5. Client-info ownership edges (Low)

- **Root causes:**
  - the overwrite guard covered only unowned writes;
  - a claim reset the age but not the insertion order the size bound evicts
    by.
- **Fix:**
  - an owned entry is replaced only by its owner;
  - a claim pops the entry and re-inserts it.
- **Tests** (in `tests/test_mcp_client_info_cache.py`):
  - `::test_another_actors_authenticated_initialize_cannot_replace_an_owned_entry`
  - `::test_an_entry_in_use_survives_the_size_bound`

## 6. Changelog wording (Low)

The consume-fault sentence now says "MCP" and that the SPA endpoint still
answers 401. The logout retry is described in `CHANGELOG.rst` and
`docs/migration/v3.15.rst`.

## 7. A lost swap response burned an authorization code (Low)

- **Root cause:** both backends answer False when the update fails, including
  when it landed but the response was lost. The strict re-read then saw
  `used` and read it as another caller's consume.
- **Fix:** `consume_once` writes a random `consume_id`. A re-read carrying
  this call's id is its own write, and counts as consumed (logged at
  WARNING). The id is random per call, so two callers can never both claim
  one row.
- **Tests:**
  - `tests/test_mcp_auth_code_single_use.py::test_a_swap_whose_response_was_lost_still_exchanges_the_code`
    uses the double's new `cas_lost_response`.
  - `::test_a_competing_consume_is_still_refused` pins the race rule (it
    passes on both versions).
- **Reuse:** `secrets.token_hex`.

## 8. Smaller items (Low)

- A test docstring names the accepted "winner still mints" residual.
- The `StoreFault` ERROR line carries the actor and a masked name.
- The FastAPI cookie logout passes a failure message through. Test:
  `tests/test_oauth2_logout_mcp_tokens.py::test_fastapi_cookie_logout_passes_a_failure_message_through`
  drives `_logout_message`.

## Release decision

Everything stays in **3.15.0**. Nothing public changes shape:
- `revoke_token` raises in more fault cases, as its documented `Raises:`
  already says;
- the stored consumed record gains an internal `consume_id` field.
