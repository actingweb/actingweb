# Verification: 3.15.0 — MCP OAuth hardening and two credential exposures (re-run)

**Date:** 2026-09-25
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Research:** thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md,
thoughts/research/2026-09-25-mcp-oauth-hardening-verification-fixes.md
**Branch:** release/3.15.0-mcp-oauth-hardening
**Commit:** 71da8ea (a merge of `origin/master` at `d6a9130` that changes no
files; the code is in `253ee76`, the thoughts in `cbc1330`)

This is the second verification of the plan on the same day. The first run is
`2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`, so this file
takes a `-2` suffix. The suffix is deduced, not confirmed:
`thoughts/README.md` does not say how to name two runs on one date. This run
covers Iterations 1–15 (both batches) on top of Phases 1–3. Phase 4 has not
started.

## Automated Check Results

- **Browser QA:** Not run. The only user-facing change is the authorize
  form's two hidden PKCE inputs, and they have not changed since the first
  run. The demo app logs in through a real provider, and no credentials exist
  in this session (`CLAUDE.md`, "Test account"). The Phase 4 connector pass
  exercises the form.
- **Second opinion:** the outside-voice agent ran codex outside the sandbox,
  plus a fresh-context Claude (Opus 5.5). A separate fresh-context agent also
  ran the high-effort code review and the security review in one pass, over
  the code the Iterations touched. The security review found nothing at or
  above 80% confidence. All findings are folded into Issues Found below.
- `poetry run ruff check actingweb tests`: pass ("All checks passed!").
- `poetry run ruff format --check actingweb tests`: pass (396 files already
  formatted).
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings, 0
  informations).
- `make test-all-parallel`, DynamoDB: 3637 passed, 31 skipped, **1 error**.
  The error was a teardown error in
  `tests/test_bulk_list_update_handles.py::TestNoConcurrentWriterEverythingApplies::test_k10_update_and_k10_delete_all_apply_and_none_is_reported_raced`:
  DynamoDB Local reported "This action timed out because it too long waiting
  for a lock" on `BatchWriteItem`. Re-run sequentially (the file alone): 20
  passed. It is a parallel isolation flake, not a regression, and that file
  is outside this plan.
- `make test-all-parallel`, PostgreSQL: 3526 passed, 140 skipped, 2 failed.
  The two failures are
  `tests/performance/test_backend_performance.py::TestSubscriptionPerformance::test_subscription_create_performance`
  and `::test_subscription_read_performance`, which fail with
  `invalid input syntax for type boolean: "https://callback.example.com"`.
  They are pre-existing and already filed as
  `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`.
- `sphinx-build -W ...`: pass ("build succeeded").

## Phase Verification

### Phases 1–3 — VERIFIED as planned, with the Iterations' deviations

The first run verified Phases 1–3 file by file. This run re-read the code the
Iterations changed, and the Previous Verification table below records each
earlier issue's fate. No phase item regressed.

Where each security property the plan claims is pinned (the project addendum
requires a named test and its assertion):

- **FastAPI `/mcp` answers 503 on a store fault:**
  `tests/test_mcp_token_store_faults.py::test_async_mcp_post_answers_503_on_store_fault`
  asserts status 503, `Retry-After: 5` and the generic message. Code:
  `actingweb/handlers/async_mcp.py:108-109`.
- **A client-lookup fault is not `invalid_client`:**
  `tests/test_mcp_token_store_faults.py::test_client_lookup_fault_is_server_error_not_invalid_client[client_index|mcp_clients]`
  asserts `out["error"] == "server_error"`, and that the refresh token still
  works once the fault clears. Code:
  `actingweb/oauth2_server/oauth2_server.py:510-511` via
  `client_registry.py:188` `load_client_strict`.
- **Theft revocation survives either backend's fault shape:** in
  `tests/test_mcp_refresh_rotation.py`,
  - `::test_theft_revocation_when_bucket_read_raises` pins the raising read;
  - `::test_theft_revocation_that_deletes_nothing_is_a_fault[zero|raise]`
    asserts `pytest.raises(TokenStoreUnavailable)`, that the chain is intact,
    and that a retry revokes it.

  Code: `token_manager.py:559-578`, `:633-648`.
- **Legacy tokens join a chain that theft detection can revoke:**
  `tests/test_mcp_refresh_rotation.py::test_legacy_record_replayed_after_grace_revokes_its_new_chain`.
- **Revoking any token of a chain revokes the whole chain:**
  `tests/test_mcp_refresh_rotation.py::test_revoke_refresh_token_revokes_its_whole_chain`
  asserts `refresh_access_token(first["refresh_token"], CLIENT) is None`.
  `::test_revoke_access_token_revokes_its_whole_chain` covers the access-token
  branch. But see Issue 2: no HTTP route reaches this.
- **No credentials in logs:**
  - `tests/test_actor_logging_redaction.py::test_async_trust_request_logs_no_secret`
    asserts `SECRET not in caplog.text` and `VERIFY not in caplog.text`.
  - `::test_peer_info_body_is_summarised` asserts `"tok123" not in caplog.text`.
  - `tests/test_mcp_auth_code_single_use.py::test_code_is_never_logged_in_full`.
  - `tests/test_log_summary.py::test_key_names_are_sanitised_and_capped`.
- **Basic header and body credentials that disagree are refused:**
  `tests/test_oauth2_public_clients.py::TestTokenHandlerCredentials::test_differing_body_and_header_secrets_are_refused`
  and `::test_mismatched_client_ids_are_refused`.
- **Live `clientInfo` is read by token before session:**
  `tests/test_mcp_client_info_cache.py::test_token_entry_wins_over_a_session_entry`.
  See Issue 9 for how long that protection lasts.
- **The OAuth callback writes no cached client name:**
  `tests/test_oauth2_pkce_binding.py::TestCallbackDoesNotUseCachedClientInfo::test_callback_writes_no_cached_client_name`.

**Deviations from plan (all recorded in the plan's Iterations):**

- A client-lookup fault answers 500 `server_error`, not the 503 the first run
  suggested. This matches the refresh grant's existing contract. Acceptable.
- `delete_client` still deletes the client when its tokens cannot be listed
  (Iteration 11f). The rationale is sound, but it depends on the delete
  itself succeeding, which is not checked (Issue 6).
- Issue 7 of the first run is deferred to
  `thoughts/todo/mcp-cleanup-expired-tokens-strict-read.md`, which has an
  `INDEX.md` row. Acceptable.

### Phase 4: Release — NOT STARTED

The consumer message (plan, Phase 4) is still accurate, clause by clause.
Since the first run, `AsyncMCPHandler` answers 503 too, so the consumer's
FastAPI `/mcp` gets the documented behaviour. The message should also mention
Issue 2: `/oauth/logout` does not revoke the connector's MCP tokens.

### Todo bookkeeping

- `trust-list-endpoint-returns-peer-secrets.md` and
  `actor-trust-request-logs-peer-secret.md` are deleted, and so are their
  `INDEX.md` rows.
- The deferral files the plan names exist:
  - `mcp-cache-lifecycle-and-revocation.md`
  - `mcp-oauth-connector-conformance-followups.md`
  - `dcr-registrations-and-client-trust-rows-never-expire.md`
  - `mcp-cleanup-expired-tokens-strict-read.md`
- Every todo file has an `INDEX.md` row, and every row has a file.
- `logout-does-not-revoke-refresh-chain.md` is about the SPA session store
  (`oauth_session.py`), not the MCP token manager, and stays open.

## Previous Verification

**Previous:** thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. FastAPI MCP handler never answers 503 | Fixed | `async_mcp.py:108-109`; Iteration 1 |
| 2. Client-lookup fault answers `invalid_client` | Fixed (500 `server_error`, not 503) | `oauth2_server.py:510-511`, `client_registry.py:188-220`; Iteration 2 |
| 3. Chain revocation aborts or reports success on a fault | Fixed | `token_manager.py:559-578`, `:633-648`; Iteration 3. A partial DynamoDB delete remains (Issue 5) |
| 4. Legacy token's first rotation has no theft detection | Fixed | `token_manager.py:359` `stamp=`, `:417-419`; Iteration 4 |
| 5. `revoke_token` leaves the rest of the chain live | Fixed | `token_manager.py:496-497`, `:507-508`; Iteration 5 |
| 6. First purge runs after the rotation | Fixed (purge before the grant) | `oauth2_endpoints.py:404-413`; Iteration 6 |
| 7. `cleanup_expired_tokens` orphans rows, aborts on a fault | Accepted, deferred | `thoughts/todo/mcp-cleanup-expired-tokens-strict-read.md` |
| 8. Raw authorization codes logged | Fixed | `_mask_token` at every site; `test_code_is_never_logged_in_full`; Iteration 7 |
| 9. Session key consulted before token key | Fixed, with a time limit | `mcp.py:2146`; Issue 9 below |
| 10. Behavioural callback test replaced by a structural one | Fixed | `test_oauth2_pkce_binding.py:175-230` |
| 11. Smaller items (nine) | Fixed | `mcp.py:28`, `:2850`, `:2901` (lock); per-token eviction `mcp.py:295-331`; `log_summary.py`; `single_use.py`; Iterations 9–15 |
| Remaining: merge `master` | Done | `71da8ea` |
| Remaining: `actor-trust-request-logs-peer-secret.md` | Done | Iteration 7; todo deleted |
| Remaining: manual curl pass with a real provider | Still open | Superseded by the Phase 4 connector pass once that runs |

## Remaining Tasks

- [ ] Fix Issues 1–6 below through `/iterate_plan` before `3.15.0rc1`, then
      re-run this verification.
- [ ] Phase 4 in full: rc1, the four-connector pass, the demo deployment, the
      stable tag, and the consumer message (with Issue 2's outcome added).
- [ ] Manual curl pass (Phase 1 Verification): record it as superseded by
      the rc connector pass, or run it.

## Issues Found

### 1. A store fault during the compare-and-swap deletes a valid refresh token

**Severity:** High
**Description:** Both backends' `conditional_update_attr` return `False` on
any exception:
- DynamoDB, `db/dynamodb/attribute.py:311-313`:
  `except Exception: # Item doesn't exist or condition check failed (race condition) return False`.
- PostgreSQL, `db/postgresql/attribute.py:566-570`: logs, then `return False`.

`consume_once` reads `False` as "lost the race" and re-reads through the
non-strict `get_attr` (`single_use.py:84-88`), which gives one of two
outcomes:
- The re-read returns the still-unused row. `refresh_access_token` then runs
  `if not used_at: self._remove_refresh_token(refresh_token); return None`
  (`token_manager.py:412-414`), which deletes the client's valid refresh
  token and answers `invalid_grant`.
- The re-read also faults. The grant logs "Refresh token vanished during
  rotation" and answers `invalid_grant`.

A single DynamoDB throttle or PostgreSQL error at the swap therefore forces
the connector to sign in again. That is exactly the "fault read as a dead
token" Phase 2 exists to remove. The authorization-code path has the same
shape (a faulted swap reads as "already used"). Found independently by the
outside voice and the code review.
**Location:** `actingweb/single_use.py:74-88`,
`actingweb/oauth2_server/token_manager.py:412-414`
**Recommendation:** in `consume_once`, re-read strictly (`get_attr_strict`).
When the row is still unused and equal to `record`, raise
`TokenStoreUnavailable` instead of returning `(False, …)`. Never delete a
refresh token because `used_at` is missing. Add a test that uses the double's
fault mode on `conditional_update_attr` and asserts `server_error` and a
still-usable token.

### 2. No HTTP route revokes MCP tokens, but the 3.15 docs say `/oauth/logout` does

**Severity:** Medium
**Description:** `/oauth/logout` runs
`OAuth2EndpointsHandler._handle_logout_request`, which calls
`_handle_provider_token_logout` (`oauth2_endpoints.py:909`). That uses only
the SPA session manager: `session_manager.revoke_access_token(token)` at
`:1023`. `ActingWebTokenManager.revoke_token` is called from exactly one
place, `ActingWebOAuth2Server.handle_logout_request`
(`oauth2_server.py:750`), and nothing routes to that; `grep` finds no caller.
`/oauth/revoke` (`oauth2_spa.py`) likewise uses only the session manager. So
an MCP bearer token sent to `/oauth/logout` is evicted from this process's
cache (`oauth2_endpoints.py:923-927`), but its rows and its chain stay live.
This gap predates 3.15, but 3.15's own text now claims the opposite:
- `CHANGELOG.rst:79`: "Revoking a token (``/oauth/logout``,
  ``revoke_token``) revokes every token in its chain".
- `docs/migration/v3.15.rst:80`: "Revoking any token of a chain
  (``/oauth/logout``, ``ActingWebTokenManager.revoke_token``) revokes the
  whole chain".
**Location:** `CHANGELOG.rst:79`, `docs/migration/v3.15.rst:80`,
`actingweb/handlers/oauth2_endpoints.py:1006-1026`
**Recommendation:** either drop `/oauth/logout` from both claims (the
cheapest option, correct for 3.15), or route tokens with the MCP prefix
(`token_manager.token_prefix`) in `_handle_provider_token_logout` to
`ActingWebTokenManager.revoke_token`, with a test. Which one is the owner's
call.

### 3. The best-effort TTL restamp can re-create a row that a revocation just deleted

**Severity:** Medium
**Description:** after winning the swap, `consume_once` calls
`store.set_attr(name=name, data=new_data, ttl_seconds=restamp_ttl)`
(`single_use.py:75-79`). That is an upsert on both backends. The failing
sequence:
1. A refresh wins the swap.
2. A theft response or revocation of the same chain deletes the chain.
3. The restamp writes the consumed row back with its `chain_id`, and
   `token_manager.py:377-381` writes its index row back.
4. The winner mints a fresh pair in the revoked chain (`:447-457`).
5. A replay within 60 s takes the grace path and mints more.

The docstring at `:48-51` calls the re-creation "equally harmless"; it is
not. The window is milliseconds wide, and the minting is a
rotation-versus-revocation race that exists without the restamp too. The
restamp is what turns it into a row that grace can rotate. The SPA store
shares `consume_once`.
**Location:** `actingweb/single_use.py:48-51`, `:74-79`
**Recommendation:** make the restamp conditional on the row existing (a
conditional update on the new data, not `set_attr`), and correct the
docstring. Re-checking the chain after minting is optional and costs a read.

### 4. A revocation fault skips removing the presented token and evicting caches

**Severity:** Medium
**Description:** `revoke_token` calls `_revoke_chain` before
`self._remove_access_token(token)` and `evict_caches_for_token(token)`
(`token_manager.py:496-500`). `_revoke_chain` raises at `:640` or `:648`
before its own `evict_caches_for_actor(actor_id)` at `:670`. On a store fault,
or on the "two revocations race" case that the docstring (`:590-594`)
accepts as "fails safe", this process therefore does neither of the
following:
- remove the presented token;
- evict the actor's cached tokens, so a worker that lost the race keeps
  serving a revoked access token from `_token_cache` for up to 300 s.

It does not fail safe. `handle_logout_request` then swallows the exception
(`oauth2_server.py:761-770`) and answers "Successfully logged out" (`:776`).
That method is SDK-only today (Issue 2).
**Location:** `actingweb/oauth2_server/token_manager.py:496-500`, `:640-648`,
`:670`; `actingweb/oauth2_server/oauth2_server.py:761-776`
**Recommendation:** evict in a `finally` in `_revoke_chain`. Remove the
presented token before revoking the chain. Have `handle_logout_request` return
the "Logged out (with errors)" shape on `TokenStoreUnavailable`. Correct the
"fails safe" sentence.

### 5. A partial DynamoDB chain delete can remove the replayed row and leave the rest

**Severity:** Medium (narrow window)
**Description:** DynamoDB's `delete_by_chain` deletes row by row
(`db/dynamodb/attribute.py:395-403`, `t.delete(); deleted += 1`). A
pagination throttle raises before any delete, because `list(query)` reads
everything first. A failed `t.delete()` partway through the refresh bucket,
though, can come after the consumed, replayed row is already gone.
`_revoke_chain` then raises `TokenStoreUnavailable` (`token_manager.py:640`),
and the docstring's recovery (`:596-597`, "the rows stay, so the next
presentation of the token tries again") no longer holds. The replayed token
now answers "invalid", and the thief's live refresh token survives until its
30-day expiry. Reviewer finding, confirmed by reading; not reproduced.
**Location:** `actingweb/db/dynamodb/attribute.py:395-403`,
`actingweb/oauth2_server/token_manager.py:596-597`
**Recommendation:** have `_revoke_chain` delete the presented token's row
last, for example by deleting the snapshot's other chain rows first. Or write
a "chain revoked" marker before deleting and check it on rotation.

### 6. `delete_client` reports success without checking its own delete

**Severity:** Medium
**Description:** Iteration 11f kept deleting the client when
`revoke_client_tokens` raises, because "Deleting the client below is what
stops its refresh tokens" (`client_registry.py:343-345`). But
`bucket.delete_attr(name=client_id)` (`:357`) is not checked. PostgreSQL
returns `False` on a fault, and DynamoDB swallows it. The same outage that
made the token listing fail usually fails this delete as well. The client
and its tokens then survive, while the log and the return value say
"Successfully deleted" (`:375-378`).
**Location:** `actingweb/oauth2_server/client_registry.py:357`, `:375-378`
**Recommendation:** check the result, log at ERROR and return `False` when
the client row was not deleted. Add the case to
`test_delete_client_still_deletes_when_tokens_cannot_be_listed`.

### 7. A failed delete of the old access token during rotation is invisible

**Severity:** Low
**Description:** rotation revokes the previous access token through
`_remove_access_token(old_access_token, actor_id=..., ...)`
(`token_manager.py:391-395`), whose actor-row `delete_attr` result is not
checked. PostgreSQL's `False` and DynamoDB's swallowed error both look like
success. The old token then stays valid for up to its 1 h lifetime on every
worker. It is bounded and occurs only on a fault, but it contradicts "the
access token it was issued with is revoked" (`docs/migration/v3.15.rst:67-68`).
**Location:** `actingweb/oauth2_server/token_manager.py:385-401`
**Recommendation:** check the result and log at ERROR. Failing the grant is
not warranted, because the refresh token is already consumed.

### 8. `revoke_client_tokens` counts deletions it did not confirm

**Severity:** Low
**Description:** `self._remove_access_token(token_name)` and
`self._remove_refresh_token(token_name)` inside the loop
(`token_manager.py:1385`, `:1407`) go back through the global index, even
though `actor_id` and the record are in hand. A strict index read that faults
is swallowed inside `_remove_access_token` (`:1168-1169`). A stale index row
skips the actor row. In both cases `revoked_count += 1`, and the INFO line
claims the revocation happened.
**Location:** `actingweb/oauth2_server/token_manager.py:1385-1412`
**Recommendation:** pass `actor_id` and `google_token_key`, delete refresh
rows directly from the actor bucket, and count confirmed deletes only.

### 9. Reading `clientInfo` by token first protects for only ten minutes

**Severity:** Low
**Description:** `_resolve_live_client_info` tries the token key and then
the session key (`mcp.py:2146`). The token entry expires after 600 s
(`mcp.py:2905`), and only `initialize` writes it, so every hourly rotation
leaves the new token without an entry. After that the lookup falls through
to the client-chosen `Mcp-Session-Id` key again, which an unauthenticated
`initialize` can overwrite: the case Iteration 8 set out to close. The impact
is limited to `client_type` detection and `MCPContext.client_info`, and the
attacker must know the victim's session id.
**Location:** `actingweb/handlers/mcp.py:2146`, `:2905`
**Recommendation:** when a bearer token is present, consult only the token
key, or carry the entry over to the new token on rotation.

### 10. Smaller items (Low)

- **The docstring overstates legacy revocation.** `revoke_token`'s docstring
  (`token_manager.py:475-476`, "A pre-chain token revokes itself and the one
  token it is linked to") is false for pre-3.15 records: they link only by
  `access_token_id`, which nothing reads now. This is not a regression: the
  removed `_revoke_access_token_by_id` and
  `_revoke_refresh_tokens_for_access_token` were stubs that only logged "not
  implemented" (`git show 2d5eaa4:actingweb/oauth2_server/token_manager.py`,
  lines 894-938). The comment on `access_token_id` at `:753` is stale the
  same way.
- **The eviction record is kept for less time than the cache it guards.**
  `_TOKEN_EVICTION_KEEP_SECONDS = 120` (`mcp.py:304`) is less than the 300 s
  token-cache TTL. A storage read stalled for more than 120 s could cache a
  rotated-out token. Keep records for at least the cache TTL.
- **The eviction test checks the helper, not the real fill.**
  `TestTokenOnlyEviction` unit-tests `_token_fill_still_valid`, and no test
  drives the fill in `authenticate_and_get_actor_cached` (`mcp.py:2280-2283`).
- **The purge throttle uses wall-clock time.** `PurgeThrottle.claim` uses
  `time.time()` (`single_use.py:105`); if the clock steps back, purging
  pauses. Use `time.monotonic()`.
- **Stale docstrings and a hard-coded bucket name.**
  - The `TokenStoreUnavailable` docstring (`token_manager.py:28-34`) omits
    client lookup and `revoke_client_tokens`.
  - `refresh_access_token` and `revoke_token` have no `Raises:` section.
  - `_snapshot_bucket` says PostgreSQL answers `{}`, but it returns `None`
    (harmless: `loaded` covers it).
  - `load_client_strict` hard-codes `"mcp_clients"` (`client_registry.py:215`).
- **Unverified: `initialize` hides a store fault.** The `except Exception:
  pass` around the authenticated part of `initialize` (`mcp.py:1019-1030`,
  per the outside voice) would swallow `TokenStoreUnavailable` silently.

## Overall Assessment

Every High and Medium issue from the first run is fixed and pinned by a named
test that fails without the fix. Issue 7 of that run is deferred to a todo.
The Full tier is clean on both backends, apart from one DynamoDB Local lock
flake that passed on its own and the two benchmark failures already filed.
The security review found no way around the properties the plan claims:
- confidential-client authentication, with header and body credentials that
  must agree;
- S256 PKCE for public clients;
- single-use codes and refresh tokens;
- chain revocation;
- log redaction.

This run's findings are one layer below the first run's. The backends report
faults as ordinary results: a `False` from compare-and-swap, a swallowed
delete, an upsert that re-creates a row. The single-use and revocation logic
takes those results at face value. The worst case is Issue 1: one throttle at
the swap deletes a legitimate refresh token, which is the failure Phase 2 was
built to prevent. Issues 3–6 are narrower races and fault paths in revocation.
Issue 2 is a documentation claim that 3.15 introduces and the code does not
back. Issues 1–6 should go through `/iterate_plan` before `3.15.0rc1`; Issue 2
needs the owner's choice between fixing the docs and routing MCP tokens. The
UI was not exercised in a browser. The plan stays `active` with no
`verified:` link, because Phase 4 has not started; this verification covers
Phases 1–3 and Iterations 1–15.
