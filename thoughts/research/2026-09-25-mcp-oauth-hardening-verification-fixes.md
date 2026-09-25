# Research: fault-path and theft-detection defects found by the 3.15 verification

**Date:** 2026-09-25
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Verification:** thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Branch:** release/3.15.0-mcp-oauth-hardening (uncommitted working tree on 661ee03)

The `/fix_bug` record for the bug fixes in the plan's first Iterations batch.
Each section gives the root cause, confirmed against the tree, and the
regression test that failed before the fix and passes after it. Issues 2 and 6
reverse decisions the plan made, so they are recorded here and in the plan's
Decisions Made. The logging todo is a plain fix.

## Release decision

All of this stays in **3.15.0** (a minor). The only public-surface additions
are `MCPClientRegistry.load_client_strict()`, an additive keyword-only
`stamp=` on the private `_consume`, and two test-double fault modes. No
route, hook, kwarg or response field changes beyond what 3.15 already
changes.

## 1. The FastAPI MCP handler never answered 503 on a token-store fault

- **Root cause:** Phase 2 wrapped the two `authenticate_and_get_actor_cached()`
  calls in `MCPHandler.get`/`post`. `AsyncMCPHandler.post_async` has its own
  copy of the POST dispatch (`handlers/async_mcp.py:103` before the fix), so
  `TokenStoreUnavailable` fell into its generic `except Exception` and
  returned HTTP 200 with `-32603 "Internal error: <fault text>"`, which
  carried the actor id and bucket name. `get_async` delegates to `get()` and
  was already correct.
- **Blast radius:** every FastAPI deployment, including the consumer
  (`actingweb_mcp/application.py:135`).
- **Regression test:**
  `tests/test_mcp_token_store_faults.py::test_async_mcp_post_answers_503_on_store_fault`,
  which asserts `handler.response.status_code == 503`,
  `headers["Retry-After"] == "5"` and
  `out["error"]["message"] == "Token store temporarily unavailable; retry"`.
  It failed before the fix.
- **Reuse:** `MCPHandler._token_store_unavailable_response`.

## 3. Chain revocation aborted, or reported success, on a store fault

- **Root cause:** there were two backend shapes. On DynamoDB, `get_bucket`
  raises when a page of the Query is throttled (`attribute.py:102-106`
  documents this), and `_snapshot_bucket` had no `try`, so `_revoke_chain`
  raised before `delete_by_chain` ran. On PostgreSQL, `delete_by_chain`
  catches every error and returns 0 (`db/postgresql/attribute.py:674-676`),
  and `_revoke_chain` reported "revoked 0 token(s)" while the chain stayed
  live. DynamoDB's `delete_by_chain` raises from inside its delete loop.
- **Fix:** `_snapshot_bucket` catches either fault shape and returns `None`.
  A failed snapshot only skips cleanup of the index rows and provider rows.
  `_revoke_chain` turns an exception from `delete_by_chain`, or a count of 0,
  into `TokenStoreUnavailable`. Its callers only revoke chains that hold at
  least the token they just loaded, so 0 means a fault. The rows stay in
  place, so the next presentation of the replayed token takes the theft
  branch again and retries.
- **Regression tests** (in `tests/test_mcp_refresh_rotation.py`):
  - `::test_theft_revocation_when_bucket_read_raises` asserts that the
    chain's rows are gone after a raising `get_bucket`.
  - `::test_theft_revocation_that_deletes_nothing_is_a_fault[zero|raise]`
    asserts `pytest.raises(TokenStoreUnavailable)`, that the chain is
    intact, and that a retry revokes it.
  - All three failed before the fix. The double gained `raising_buckets` and
    `chain_delete_fault`.
- **Reuse:** `delete_by_chain`, `Attributes.loaded`.

## 4. A legacy refresh token's first rotation had no theft detection

- **Root cause:** a record without `chain_id` rotated into a fresh chain, but
  `_consume` wrote a copy of the old record, so the consumed legacy row never
  got that chain. A replay more than 60 s later took the theft branch with
  `current.get("chain_id") is None` and removed only the dead row.
- **Fix:** the chain id is chosen before `_consume` and stamped into the
  consumed row's new data (`stamp=`), never into the compare-and-swap's
  expected value. The grace branch rotates in the chain the winner recorded.
- **Regression test:**
  `tests/test_mcp_refresh_rotation.py::test_legacy_record_replayed_after_grace_revokes_its_new_chain`.
  It asserts that the consumed legacy row carries the new chain and that a
  replay after 5 minutes removes the rotated pair. It failed before the fix.

## 5. Revoking a token left the rest of its chain live

- **Root cause:** the refresh-token branch of `revoke_token` removed the
  token and its one access token. The access-token branch removed the
  chain's refresh tokens but not its other access tokens. A consumed
  predecessor (`used_at` < 60 s) could still rotate after its successor was
  revoked. This was the plan's own spec (F, `revoke_token`), so the fix is a
  plan gap closed, not an implementation slip.
- **Fix:** both branches call `_revoke_chain` when the record has a chain.
  `_remove_refresh_tokens_in_chain` is removed; `revoke_token` was its only
  caller.
- **Regression tests** (in `tests/test_mcp_refresh_rotation.py`):
  - `::test_revoke_refresh_token_revokes_its_whole_chain` asserts
    `refresh_access_token(first["refresh_token"], CLIENT) is None` after
    `second` is revoked, and that another chain survives.
  - `::test_revoke_access_token_revokes_its_whole_chain` asserts that a grace
    sibling's pair is gone.
  - Both failed before the fix.

## 7. Credentials in logs outside the plan's three lines (the todo)

- `actor.py`: the async reciprocal-trust request logged its body, which
  carries `secret` and `verify`, at **INFO**. The subscription create and
  callback bodies, and the peer-info response bodies, were logged at DEBUG.
  All of them now use `summarize_payload`.
- `token_manager.py`: the auth-code helpers logged raw codes at DEBUG,
  WARNING and ERROR. The provider-token row names are
  `google_token_<code>`, so their five log lines leaked the code too, which
  the new test caught. `revoke_client_tokens` logged token names. All are
  now logged through `_mask_token`.
- `fastapi_integration.py`: the decrypted MCP state and the authorize
  template values are now logged as a summary.
- **Regression tests:**
  - `tests/test_actor_logging_redaction.py::test_async_trust_request_logs_no_secret`
    asserts that `SECRET not in caplog.text` and `VERIFY not in caplog.text`.
  - `tests/test_actor_logging_redaction.py::test_peer_info_body_is_summarised`.
  - `tests/test_mcp_auth_code_single_use.py::test_code_is_never_logged_in_full`.
  - All three failed before the fix.

## Decisions reversed (see the plan)

- **2.** A client-lookup fault at the token endpoint answered 401
  `invalid_client`: `_load_client` swallows faults
  (`client_registry.py:377-379`), and the plan kept strict reads to the two
  token lookups. The grants now read the client with
  `MCPClientRegistry.load_client_strict` (`get_attr_strict` on the index row
  and the client row). A fault raises `TokenStoreUnavailable`, which the
  token endpoint answers with 500 `server_error`, the same contract as the
  refresh grant's token lookup. `_authenticate_client` also compares the
  secret against the record it already loaded, so there is one read instead
  of two. Authorize, the callback filter and the SDK keep the fail-as-absent
  lookup.
  - **Regression test:**
    `tests/test_mcp_token_store_faults.py::test_client_lookup_fault_is_server_error_not_invalid_client[client_index|mcp_clients]`,
    which asserts `out["error"] == "server_error"` and that the refresh
    token still works after the fault clears.
- **6.** The opportunistic purge ran after the grant, so a slow first purge
  on a backlogged PostgreSQL table could hold back the response to a refresh
  whose token was already consumed. A retry after 60 s then read as theft.
  The purge now runs before the grant: a slow or failed purge delays or
  skips housekeeping, never a rotated response. Bounding the `DELETE` would
  change the backend protocol and was not needed for this. Seeding the
  throttle at import was rejected because Lambda containers rarely live an
  hour, so the purge would never run there.
  - **Regression test:**
    `tests/test_oauth2_token_endpoint_errors.py::test_purge_runs_before_the_grant`,
    which asserts `order == ["purge", "grant"]`.

## Both backends

The unit tests run on the in-memory double, with both fault shapes modelled.
The Full tier runs `tests/integration/test_mcp_refresh_rotation_backend.py`
on DynamoDB and PostgreSQL. Its outcome is recorded in the plan's Iterations
batch.
