# Verification: 3.15.0 — MCP OAuth hardening and two credential exposures (fourth run)

**Date:** 2026-09-26
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Research:** thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md,
and the fix records `-verification-fixes.md`, `-verification-fixes-2.md` (both
2026-09-25) and `2026-09-26-mcp-oauth-hardening-verification-fixes-3.md`
**Branch:** release/3.15.0-mcp-oauth-hardening
**Commit:** 2202199 (the code; `9e70e47`, the HEAD, adds only the thoughts
documents)

This is the fourth verification of the plan, and the first dated 2026-09-26.
It covers Iterations 20–21, which fix the third run's issues 1–8, on top of
Phases 1–3 and Iterations 1–19. Phase 4 has not started.

## Automated Check Results

- **Browser QA:** not run. No iteration touched a page a user sees. The
  FastAPI cookie logout changes a JSON message and is covered by a unit test.
  There are no provider credentials in this session; the Phase 4 connector
  pass exercises the authorize form.
- **Second opinion:** the outside-voice agent ran two providers:
  - codex (`codex exec -s read-only`, unsandboxed): no findings. It traced
    the revoke callers, the chain ordering, `revoke_client_tokens`, the CAS
    on both backends, legacy rows without `consume_id`, the owner check, the
    LRU move and `_logout_message`.
  - a fresh-context Claude (Opus 5.5): one Medium and four Lows (Issues 1–5
    below).
- **Code and security review:** a separate fresh-context agent ran the
  high-effort code review and the security review. It found no High and
  no Medium at confidence 7 or above, and three Lows, two of which the
  outside voice also raised. The security review found nothing to report.
- Full tier on `9e70e47`, whose code is `2202199`:
  - `ruff check`: pass.
  - `ruff format --check`: pass (397 files).
  - `pyright`: pass (0 errors, 0 warnings).
- `make test-all-parallel`, DynamoDB: 3675 passed, 31 skipped, **2 errors**.
  - Both errors were teardown errors in `tests/test_bulk_list_update_handles.py`,
    with DynamoDB Local reporting "This action timed out because it too long
    waiting for a lock" on `BatchWriteItem`. It is the parallel isolation
    flake seen in the first run.
  - Re-run sequentially (the file alone): 20 passed. It is not a regression,
    and the file is outside this plan.
- `make test-all-parallel`, PostgreSQL: 3564 passed, 140 skipped, 2 failed.
  The failures are the two `TestSubscriptionPerformance` benchmarks already
  filed in
  `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`.
- `sphinx-build -W ...`: pass.

## Phase Verification

### Phases 1–3 with Iterations 1–21 — VERIFIED, with Lows and one design trade-off

Where the properties this batch claims are pinned:

- **A faulted revocation keeps the presented token for a retry:**
  - `tests/test_mcp_refresh_rotation.py::test_revocation_fault_keeps_the_presented_token_to_retry_from[zero|raise|partial]`
    asserts that the cache entry is gone, that the row remains, and that a
    second `revoke_token` removes the chain's refresh token.
  - `::test_refresh_token_revocation_fault_keeps_it_to_retry_from`.
  - `tests/test_oauth2_logout_mcp_tokens.py::test_logout_after_a_revocation_fault_can_be_retried`
    covers the same end to end.
  - Code: `token_manager.py:535-543`.
- **An unconfirmed delete is never reported as a revocation:**
  `tests/test_mcp_refresh_rotation.py::test_unconfirmed_delete_of_a_chainless_token_is_not_reported_revoked`
  asserts `pytest.raises(TokenStoreUnavailable)`. See Issue 2 for what a
  retry then finds.
- **A lost swap response does not burn a code, and a competing consume is
  still refused:**
  `tests/test_mcp_auth_code_single_use.py::test_a_swap_whose_response_was_lost_still_exchanges_the_code`
  and `::test_a_competing_consume_is_still_refused`. Both reviewers checked
  that `consume_id` is written only into the new data, never into the
  compare-and-swap's expected value, and is random per call, so it cannot
  allow a double consume.
- **Client-info ownership and eviction order:**
  `tests/test_mcp_client_info_cache.py::test_another_actors_authenticated_initialize_cannot_replace_an_owned_entry`
  and `::test_an_entry_in_use_survives_the_size_bound`.
- **Client token revocation counts a raising delete:**
  `tests/test_mcp_token_store_faults.py::test_revoke_client_tokens_counts_a_raising_delete_and_goes_on`.

**Callers of the new raises:** `revoke_token` is called only by
`oauth2_server.handle_logout_request` (which catches `Exception` and
reports "with errors") and `oauth2_endpoints._handle_mcp_token_logout`
(which catches `TokenStoreUnavailable`). Trust and client deletion do not
call it. No caller breaks.

**Deviations from plan:** none new.

### Phase 4: Release — NOT STARTED

The consumer message is accurate, apart from Issue 1's fault path.

## Previous Verification

**Previous:** thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A fault removed the row the retry needed (Medium, regression) | Fixed | `token_manager.py:535-543`; Iteration 20. The trade-off it creates is Issue 1 below |
| 2. Unconfirmed delete reported as True (Medium) | Fixed | it raises; Iteration 20. A retry cannot reach the kept row (Issue 2 below) |
| 3. Broad `except` in `revoke_client_tokens` | Fixed | a `try` per token; Iteration 21 |
| 4. Another actor could replace an owned entry | Fixed | `mcp.py` owner guard; Iteration 21 |
| 5. A claim did not move the entry in eviction order | Fixed | pop and re-insert; Iteration 21 |
| 6. Changelog overstated the consume-fault rule for SPA | Fixed | `CHANGELOG.rst` names MCP and the SPA 401 |
| 7. A lost swap response burned a code | Fixed | `consume_id`; Iteration 21 |
| 8. Smaller items (test docstring, fault log, FastAPI cookie message) | Fixed | Iteration 21; the FastAPI route itself is untested (Issue 4 below) |

## Remaining Tasks

- [ ] Decide Issue 1 (owner's call); fix Issue 2 and optionally 3–5 through
      `/iterate_plan`, or file them as todos. None blocks `3.15.0rc1` on
      its own.
- [ ] Phase 4 in full: rc1, the four-connector pass, the demo deployment,
      the stable tag, and the consumer message.
- [ ] Manual curl pass (Phase 1 Verification): record it as superseded by
      the rc connector pass, or run it.

## Issues Found

### 1. After a faulted logout both tokens stay valid, and nothing prompts the retry

**Severity:** Medium. This is a design trade-off rather than a defect. The
code review rates it Low at confidence 9 "that it is real; a deliberate
choice".
**Description:** Iteration 20 keeps the presented token when
`_revoke_chain` faults (`token_manager.py:539-543`, `except
TokenStoreUnavailable: ... evict_caches_for_token(token); raise`) so that
presenting it again retries the revocation. But `/oauth/logout` answers that
fault with HTTP 200, `"action": "success"` and `clear_cookies`
(`oauth2_endpoints.py:1076-1082`), and no OAuth client retries a 200.

Until the token is presented again:
- the access token validates for up to an hour, on every worker, this one
  included once it re-reads the store;
- the refresh token stays live for up to 30 days, sliding.

At `800b917` the access token was deleted, though the refresh token also
survived, with nothing to retry from. So the change trades "no retry
possible" for "a retry nobody triggers", and during the fault window more
is left alive than before. The changelog says "presenting it again (another
``/oauth/logout``) retries the revocation", which is true but relies on an
action clients do not take.
**Location:** `actingweb/oauth2_server/token_manager.py:539-543`,
`actingweb/handlers/oauth2_endpoints.py:1062-1082`
**Recommendation:** owner's call between:
- (a) keep the row but mark it `revoked`, so `validate_access_token` and the
  refresh grant refuse it while `revoke_token` can still resolve it and
  retry. This closes the window without the client doing anything, at the
  cost of one extra conditional write on the fault path.
- (b) answer 503 with `Retry-After` on the bearer (non-cookie) logout path.
- (c) accept it, and say plainly in `CHANGELOG.rst` that only a client that
  logs out again completes the revocation.

(a) is the one that does not depend on client behaviour.

### 2. An unconfirmed delete removes the index row, so the "retry" cannot reach the kept token

**Severity:** Low (both reviews, confidence 8)
**Description:** `_remove_access_token(actor_id=...)` deletes the global
index row even when the actor row's delete is unconfirmed
(`token_manager.py:1237-1248`: `gone = delete_confirmed(...)` ...
`.delete_attr(name=token)` ... `return gone`). `_remove_refresh_token_row`
does the same ("the index row is removed either way").

Take a chainless token whose delete is unconfirmed:
1. `revoke_token` raises and the actor row stays;
2. the index row is gone (always on PostgreSQL, usually on DynamoDB);
3. a second logout cannot resolve the token, so `revoke_token` returns False
   and `_handle_mcp_token_logout` says "Successfully logged out";
4. the actor row is orphaned until the TTL sweep.

The token is in fact unusable, because every lookup goes through the index,
so this is not a security hole. But it contradicts the `revoke_token`
docstring, `CHANGELOG.rst:83` and `docs/migration/v3.15.rst:89`. The test
asserts only that the row remains; it never retries.
**Location:** `actingweb/oauth2_server/token_manager.py:1237-1248`, `:1345-1357`
**Recommendation:** skip the index delete when `gone` is False, and extend the
test with a second `revoke_token` call that succeeds.

### 3. `_logout_message` says "Logged out successfully" when the handler failed with a 500

**Severity:** Low
**Description:** `_logout_message` (`fastapi_integration.py:36-52`) passes
through only a string `message`. The logout handler's 500 path uses
`error_response`, whose body is `{"error": ..., "error_description": ...}`
(`oauth2_endpoints.py:1004`, "Internal server error during logout"). So the
cookie AJAX branch still says "Logged out successfully" over a failed
handler, which is the misreport Iteration 21 removed for the revocation
path.
**Location:** `actingweb/interface/integrations/fastapi_integration.py:36-52`
**Recommendation:** return a failure message when
`handler_response.status_code >= 400` or the body carries `error`.

### 4. The FastAPI cookie branch is tested through its helper only, and still drops two cookies

**Severity:** Low (the dropped cookies predate this plan)
**Description:** `test_fastapi_cookie_logout_passes_a_failure_message_through`
drives `_logout_message` directly. The wiring
`handler_response = await self._handle_oauth2_endpoint(request, "logout")`
(`fastapi_integration.py:788`) is untested. The branch also deletes only
`oauth_token` (`:799`, `:803`), while the handler asks to clear
`oauth_token`, `oauth_refresh_token` and `session_id`
(`oauth2_endpoints.py:1081`).
**Location:** `actingweb/interface/integrations/fastapi_integration.py:785-806`
**Recommendation:** add a route-level `TestClient` test, and delete every
name the handler lists, or copy its `set-cookie` headers.

### 5. `revoke_client_tokens` does not evict this process's MCP token cache

**Severity:** Low (predates this plan; the function was rewritten in
Iteration 21 without closing it)
**Description:** the per-token loop (`token_manager.py:1524-1561`) deletes
access tokens but never calls `evict_caches_for_token`, unlike `revoke_token`
and `_revoke_chain`. A deleted client's access token that is already cached
keeps authenticating on that worker for up to 300 s.
**Location:** `actingweb/oauth2_server/token_manager.py:1524-1561`
**Recommendation:** call `evict_caches_for_token(token_name)` after each
confirmed access-token delete.

### 6. Smaller items (Low)

- `single_use._mask` duplicates `token_manager._mask_token`. It is kept
  local on purpose (`single_use` must not import upward); this is cosmetic.
- The first authenticated owner of a session id now wins over any later
  actor that names it. The only effect is blank client info for the
  latecomer (denial of service, out of scope).

## Overall Assessment

All eight issues from the third run are fixed and pinned by tests that fail
on `6748937`. The Full tier is clean on both backends, apart from the known
DynamoDB Local lock flake (which passed on its own) and the two benchmark
failures already filed. Codex found nothing. The code and security review
found no High and no Medium, and nothing at the security bar. The
properties the plan claims hold on the paths the tests drive: single-use
codes and refresh tokens, chain revocation (now retryable), confirmed
deletes, and client-info ownership.

What is left is one trade-off and four Lows. Issue 1 is a choice about what
a logout that hits a store fault should leave behind. The current behaviour
is safer than `800b917` for retryability, but it leaves the access token
usable until someone presents it again. Marking the row `revoked` would
close that without relying on the client. Issue 2 makes the documented retry
unreachable in the chainless unconfirmed-delete case, which is a one-line
fix. None of the five blocks `3.15.0rc1` on its own; Issue 1 needs the
owner's decision. The UI was not exercised in a browser. The plan stays
`active` with no `verified:` link, because Phase 4 has not started. This
verification covers Phases 1–3 and Iterations 1–21.
