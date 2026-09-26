# Verification: 3.15.0 — MCP OAuth hardening and two credential exposures (fifth run)

**Date:** 2026-09-26
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Research:** the plan's research, and the fix records `-verification-fixes.md`
(2026-09-25), `-verification-fixes-2.md` (2026-09-25), `-verification-fixes-3.md`
(2026-09-26) and `2026-09-26-mcp-oauth-hardening-verification-fixes-4.md`
**Branch:** release/3.15.0-mcp-oauth-hardening
**Commit:** fade3da (the code; `7e9c0b9` records the fourth verification)

This is the second verification dated 2026-09-26, so the file takes a `-2`
suffix, following the earlier convention (deduced, not confirmed). It covers
Iterations 22–23, which apply the owner's decisions on the fourth run's
issues 1–5. The review ran on the working tree that the owner then committed
as `fade3da`; the code is identical. Phase 4 has not started.

## Automated Check Results

- **Browser QA:** not run. The logout route changes are JSON and status
  only, and are covered by route-level tests through the real FastAPI and
  Flask routes. No provider credentials are available.
- **Second opinion:** the outside-voice agent ran two providers:
  - codex (`codex exec -s read-only`, unsandboxed): Issue 1 and Issue 4 below.
  - a fresh-context Claude: Issues 2, 3 and 5–8.
- **Code and security review:** a separate fresh-context agent ran the code
  review and the security review. It found Issue 1 (High) and Issue 2
  (Medium) on its own, plus two Lows. The security review found nothing else
  at the bar: the 503 leaks nothing, and no raw secret is logged.
- The Full tier ran on this code just before the commit (Iteration 23's
  checks). The plan document is the only file changed since.
  - `ruff check`, `ruff format --check` (397 files), `pyright`: pass.
  - `make test-all-parallel`, DynamoDB: 3681 passed, 31 skipped, 3 errors.
    All three are DynamoDB Local "waiting for a lock" teardown errors in
    `test_hot_path_n_plus_one.py` and `test_bulk_list_update_handles.py`.
    Re-run sequentially: 31 passed. Not a regression; outside this plan.
  - `make test-all-parallel`, PostgreSQL: 3570 passed, 140 skipped, 2 failed.
    The failures are the benchmark subscription tests already filed.
  - `sphinx-build -W`: pass.

## Phase Verification

### Phases 1–3 with Iterations 1–23 — ISSUES FOUND (one High regression from Iteration 22)

What holds:
- a faulted MCP logout answers 503 with `Retry-After` on both frameworks'
  bearer paths (`test_faulted_bearer_logout_is_503_with_retry_after_on_fastapi`
  and `…_on_flask`), and a retry completes the revocation
  (`test_logout_after_a_revocation_fault_can_be_retried`);
- the FastAPI cookie branch reports a failed revocation and a handler 500 in
  its JSON body;
- `revoke_client_tokens` evicts this process's cache.

What regressed: Iteration 22's "keep the index row on an unconfirmed delete"
went into the two shared remove helpers, and so into callers that never
retry (Issues 1 and 2).

**Deviations from plan:** none beyond the regression.

### Phase 4: Release — NOT STARTED

## Previous Verification

**Previous:** thoughts/verifications/2026-09-26-mcp-oauth-hardening-and-credential-exposure.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Faulted logout answered 200 (owner chose 503) | Fixed on the bearer paths | `oauth2_endpoints.py` `retry` action; Iteration 22. The FastAPI cookie branch still answers 200/302 (Issue 5) |
| 2. Unconfirmed delete removed the index row the retry needed | Fixed for `revoke_token`, but regresses rotation and client deletion | Issues 1–2 below |
| 3. FastAPI cookie logout reported success over a 500 | Fixed in the AJAX body (`_logout_outcome`) | its status is not passed through (Issue 5) |
| 4. Route-level tests | Added | they stub the changed dispatch (Issue 8) |
| 5. Client deletion left tokens cached | Fixed, except when the delete raises | Issue 6 below |

## Remaining Tasks

- [ ] Fix Issues 1–2 before `3.15.0rc1`, preferably by the simpler design in
      Issue 3. Fix the rest, or file them as todos.
- [ ] Phase 4 in full: rc1, the four-connector pass, the demo deployment,
      the stable tag, and the consumer message.
- [ ] Manual curl pass: record it as superseded by the rc connector pass, or
      run it.

## Issues Found

### 1. A rotated-out access token stays valid for up to an hour after a faulted delete

**Severity:** High (codex and the code review, confidence 8; a regression
from Iteration 22)
**Description:** `_remove_access_token(actor_id=...)` now returns `False`
before deleting the index row when the actor row's delete is unconfirmed
(`token_manager.py:1244-1245`). Tokens resolve only through that index row
(`_search_indexed_token`, `:1194`). Refresh rotation calls
`self._remove_access_token(old_access_token, actor_id=actor_id, ...)`
(`:404`) and ignores the result.

So during a transient fault the rotated-out access token keeps validating on
every worker until it expires (`default_expires_in = 3600`), and nothing ever
retries it: the consumed refresh row leads nobody to it. Before Iteration 22
the index delete made it unusable at once.
`test_unconfirmed_delete_of_the_old_access_token_is_logged` asserts only the
log line.
**Location:** `actingweb/oauth2_server/token_manager.py:404`, `:1238-1245`
**Recommendation:** see Issue 3. Add a rotation test that faults the old
token's delete and asserts `validate_access_token(old) is None`.

### 2. The same regression in client deletion

**Severity:** Medium. The code review rates it Medium at confidence 7; the
outside voice rates it High.
**Description:** `revoke_client_tokens` uses the same helper
(`token_manager.py:1533`). `delete_client` then deletes the client anyway
(`client_registry.py:340-350`), and nothing re-runs it. A client access
token whose delete is unconfirmed keeps validating through its index row for
its remaining TTL, on every worker; the new eviction covers only this
process. The refresh tokens are harmless, because the client can no longer
authenticate.
**Location:** `actingweb/oauth2_server/token_manager.py:1533`, `:1350-1358`
**Recommendation:** see Issue 3.

### 3. The simpler rule: always delete the index row

**Severity:** Medium (a design recommendation that resolves Issues 1 and 2)
**Description:** lookup is index-only, so deleting the index row already
revokes a token for every validator. Keeping the index row "so a retry can
reach the token" (Iteration 22) keeps the token alive during the fault, even
for `revoke_token`, and the only thing it buys is tidier cleanup of the
provider row and the orphaned actor row. If the index row is always deleted:
- the token is dead at once, on every worker;
- `revoke_token` still raises for the 503;
- a retry finds the token "unknown", which maps to success, which is true;
- the leftover actor and provider rows expire by TTL, or are removed by the
  PostgreSQL purge.
**Location:** `actingweb/oauth2_server/token_manager.py:1238-1245`, `:1350-1358`
**Recommendation:** delete the index row whatever the actor-row outcome
(the pre-Iteration-22 behaviour), keep returning the confirmed result so
`revoke_token` raises, and update the retry wording in `CHANGELOG.rst`,
`docs/migration/v3.15.rst` and the docstrings: the retry now confirms
rather than completes. The owner's issue 1 decision (503) is unaffected.

### 4. A lookup fault on logout no longer evicts the token from this process's cache

**Severity:** Medium (a regression from Iteration 22)
**Description:** `_handle_logout_request` clears the MCP cache only
`if token and response.get("action") == "success":`
(`oauth2_endpoints.py:924`). When `_load_access_token` itself raises
(`token_manager.py:530`), `revoke_token` has not evicted anything yet, and
the action is now `retry`, not `success`. The token keeps authenticating
from this process's cache for up to 300 s while the client is told 503.
**Location:** `actingweb/handlers/oauth2_endpoints.py:924`
**Recommendation:** also clear the cache on `retry`, or evict at the start of
`revoke_token`.

### 5. The FastAPI cookie branch drops the 503 and Retry-After

**Severity:** Low (a rare mixed request)
**Description:** a request carrying an `oauth_token` cookie and an MCP
bearer token takes the cookie branch; the handler prefers the bearer. On a
fault:
- the AJAX response is HTTP 200 with `success: false`;
- the non-AJAX response is a plain 302 (`fastapi_integration.py:797-815`);
- both clear the cookie.

The retry signal is lost.
**Location:** `actingweb/interface/integrations/fastapi_integration.py:797-815`
**Recommendation:** on a failed outcome, pass through the handler's status
and `Retry-After`, and do not clear the cookie.

### 6. A raising delete in `revoke_client_tokens` skips the cache eviction, and each eviction is actor-wide

**Severity:** Low
**Description:** `evict_caches_for_token(name)` (`token_manager.py:1539`)
runs only when `_remove_access_token` returns, so the raising path does not
evict. Its default `actor_wide=True` also bumps the process-wide generation
once per token of the deleted client.
**Recommendation:** evict in a `finally` with `actor_wide=False`, then call
`evict_caches_for_actor(actor_id)` once after the loop.

### 7. Cross-origin SPAs cannot read `Retry-After`

**Severity:** Low
**Description:** the logout CORS headers (`fastapi_integration.py:2131-2137`,
`flask_integration.py:1279-1290`) have no `Access-Control-Expose-Headers`,
and `Retry-After` is not a CORS-safelisted response header.
**Recommendation:** add `Access-Control-Expose-Headers: Retry-After` on
logout responses.

### 8. The route tests stub the changed dispatch

**Severity:** Low
**Description:** `_patched_logout` replaces `_handle_provider_token_logout`,
so neither the MCP-prefix dispatch nor the `TokenStoreUnavailable` → `retry`
mapping runs through a route. `test_fastapi_cookie_logout_reports_a_handler_failure`
does not assert the status. The fault-to-503 mapping is covered at handler
level only.
**Recommendation:** add one route test with a real token manager and an
injected fault, including the cookie-plus-bearer case.

### Notes (not findings)

- A persistent fault gives an unbounded 503 loop at a fixed 5 s. Clients
  normally back off; a cap is a later refinement. This is unverified
  reasoning.
- The generic-exception branch of the logout handler still answers success
  for errors other than store faults. That matches the changelog, which
  scopes the 503 to store faults.

## Overall Assessment

The owner's decisions are implemented and tested on the paths they target,
and the Full tier is clean apart from the known lock flake and the filed
benchmarks. But Iteration 22 changed the two shared remove helpers to keep
the index row whenever a delete is unconfirmed. That suits only
`revoke_token`. Rotation and client deletion never retry, so a transient
fault now leaves a revoked access token valid for up to an hour on every
worker, where before it was unusable at once. That is the High finding, and
it should be fixed before `3.15.0rc1`.

The cleanest fix is to delete the index row whatever the outcome. That also
makes a logout during a fault revoke immediately, while still answering 503
so the client confirms. Issue 4, cache eviction on a lookup fault, is a
second small regression from the same iteration. The rest is Low. The plan
stays `active` with no `verified:` link, because Phase 4 has not started.
This verification covers Phases 1–3 and Iterations 1–23.
