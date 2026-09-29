# Verification: SPA logout and `/oauth/revoke` end the refresh chain (re-run after iteration)

**Date:** 2026-09-29
**Plan:** thoughts/plans/2026-09-29-logout-does-not-revoke-refresh-chain.md
**Research:** thoughts/research/2026-09-28-logout-does-not-revoke-refresh-chain.md
**Branch:** fix/3.15.1-logout-revokes-chain
**Commit:** 63c1cb3 (the implementation and the iteration are an uncommitted working tree on top of it)

No feature document, so no Success Measures section.

## Automated Check Results

Full tier from `CLAUDE.md`, run once, one run at a time. Both test runs are the
**parallel** `make test-all-parallel`; neither showed a failure, so no
sequential re-run was needed and every number comes from the parallel run.

- **Browser QA:** N/A. No phase adds or changes a page; browser QA cannot log in
  (real OAuth2 provider, no test account). **The UI was not exercised.** The
  www UI's non-AJAX logout is covered by route tests only.
- **Second opinion:** the outside-voice agent ran with a fresh-context Claude
  reviewer only (Codex was not run this pass, so no second-model coverage).
  Findings I13-I17 below.
- **Built-in code review (high):** ran, 9 findings. Its first finding
  (`oauth2_endpoints.py:969` failing open) was an artifact of my own brief
  mutation check, which was applied while the reviewer read the tree and
  restored immediately (byte-identical to the backup; the full tier had
  finished before the mutation). The rest are known, accepted or pre-existing
  (see I16, and "Previous Verification"); none is new and serious.
- **Built-in security review:** 0 findings at confidence 8 or above.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass.
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel` on **DynamoDB**: pass, **3889 passed, 31 skipped**,
  0 failed.
- `make test-all-parallel` on **PostgreSQL** (port 5433): pass, **3780 passed,
  140 skipped**, 0 failed.
- `sphinx-build -W --keep-going ...`: pass ("build succeeded", exit 0 under `-W`).
- Benchmarks: not run (no list-storage change).
- **Mutation check of the new regression tests:** reverting the logout
  catch-all to the old 200 made
  `tests/test_oauth2_spa_logout_revokes_chain.py::test_an_unexpected_error_is_500_and_keeps_the_cookies_and_tokens`
  fail (1 failed, 35 passed); the file was restored. The query-string
  mutation I tried was mis-aimed (it sat behind the form content-type branch that
  test does not reach), so that test is judged by inspection: the old code read
  `request.params` on every POST and would have accepted the token.

## Previous Verification

**Previous:** thoughts/verifications/2026-09-29-logout-does-not-revoke-refresh-chain.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| I1 Logout/refresh race (Medium) | Deferred to a todo, by owner decision | `thoughts/todo/spa-logout-refresh-rotation-race.md`, `INDEX.md` row, Iteration 2 |
| I2 Catch-all answers 200 and clears cookies (Medium) | **Fixed** | `actingweb/handlers/oauth2_endpoints.py:969` returns `error_response(500, ...)`; `tests/test_oauth2_spa_logout_revokes_chain.py:404`; mutation-checked; changelog **Behavior change:** sentence; Iteration 1 |
| I3 PostgreSQL `delete_by_chain` reads errors as 0 (Low) | **Fixed** | `actingweb/db/postgresql/attribute.py:713` re-raises; `tests/test_postgresql_delete_by_chain.py`; Iteration 7 |
| I4 Sweep counts unconfirmed deletes, deletes non-mapping rows (Low) | **Fixed** | `token_manager.py` `_sweep_index` (`:1583`, non-mapping branch `:1665`); `tests/test_mcp_token_store_faults.py:525,549`; Iteration 6 |
| I5 Provider row left behind for an expired-unreaped access row (Low) | Accepted as-is, documented | Provider row shares the access row's TTL and is reaped by native TTL or `delete_expired`; comments in `_remove_access_token` and `_sweep_index`; Iteration 9 |
| I6 `revoke_session` reports a malformed row as unknown (Low) | **Fixed** | `oauth_session.py:1098`; `tests/test_oauth_session.py:870,878`; Iteration 8 (see I15 for a residue) |
| I7 Stale `_store_unavailable` docstring (Low) | **Fixed** | `oauth2_spa.py` docstring; Iteration 5 |
| I8 FastAPI `OPTIONS /oauth/spa/logout` fixed instead of filed (Low) | Accepted as-is | Iteration 4 |
| I9 Patch with wire-shape changes, no **Breaking:** lead (Medium) | Accepted as-is, owner decision "patch" | Iteration 3 |
| I10 MCP token plus SPA refresh cookie (Low) | Deferred to a todo | `thoughts/todo/logout-mcp-token-with-spa-refresh-cookie.md`, `INDEX.md` row, Iteration 10 |
| I11 Refresh token accepted in the POST query string (Low) | **Fixed** | `oauth2_endpoints.py:1069` reads the form body via `parse_qs`; `tests/test_oauth2_spa_logout_revokes_chain.py:283`; Iteration 5 |
| I12 Sweep unconfirmed delete never retried (Low) | **Fixed** | Actor row first, index row only after confirmation; `tests/test_mcp_token_store_faults.py:525` retries on the next run |

## Phase Verification

The three phases were verified against the code in the previous document and
are unchanged except for the iteration items above. This run re-read the
changed code (Iterations 1 and 5-9) and re-ran the full tier.

- **Phase 1** - VERIFIED. `single_use.revoke_chain_confirmed`,
  `revoke_token_chain(anchor=)`, `revoke_session`, both `delete_by_chain`
  backends (PostgreSQL now raises), `_sweep_index`. All Phase 1 tests and the
  integration file `tests/integration/test_spa_chain_revocation_backend.py`
  pass on both backends.
- **Phase 2** - VERIFIED. Login tagging, `/oauth/revoke`, `/oauth/logout` (now
  500 on an unexpected error, form-body refresh token), SDK logout, FastAPI
  route. `tests/integration/test_oauth2_spa_logout.py` passes on both backends.
- **Phase 3** - VERIFIED. CORS builder, docs (build passes), changelog (now
  also names the 500, the PostgreSQL raise, the sweep counting and the
  malformed-row `revoke_session` behaviour), todo bookkeeping (two new todos:
  the race and the mixed MCP/SPA logout).

**Security property, re-demonstrated:** the tests named in the previous
document still pass on both backends (a logged-out refresh token answers 401,
another chain survives, a fault answers 503 with no cookie change and a
retry succeeds), and the new fail-closed test pins that an unexpected error
leaves cookies and tokens alone.

## Remaining Tasks

- [ ] Optional: fix I13, I15 and I16 (small, no behaviour risk) in one more
      iterate/verify pass, or accept them.
- [ ] The whole change is uncommitted; `/changelog` then `/commit` then a PR
      to `master` on `fix/3.15.1-logout-revokes-chain` is next. The five todo
      deletions are currently unstaged after a stash round-trip during the
      iteration and must be staged with the commit.

## Issues Found

### I13. `_handle_session_token_logout` docstring is now false
**Severity:** Low
**Description:** "Deliberately outside the caller's catch-all: a token store
fault is answered ``retry`` (503)" (`oauth2_endpoints.py:1114`). The call sits
inside the `try/except Exception` whose handler now returns 500. Behaviour is
right (`TokenStoreUnavailable` is caught first, inside the method); the comment
is wrong.
**Recommendation:** Reword to say the fault is converted to `retry` here,
before the caller's fail-closed 500.

### I14. The sweep counts a non-mapping row as skipped on every run
**Severity:** Low (accepted)
**Description:** The row stays until its TTL, so `skipped` and the
"skipped N row(s)" WARNING fire on each scheduled sweep (`token_manager.py:1665`).
Noise, not a fault; it is also the safe choice.
**Recommendation:** Accept.

### I15. `revoke_session` returns `{}` after a malformed row without searching the other bucket
**Severity:** Low
**Description:** `oauth_session.py:1098` `logger.warning(f"Removed a malformed token row ...")` is followed by `return {}`. A same-named row with a real chain in the other bucket is not revoked. Token names are random, so the collision is theoretical.
**Recommendation:** `continue` to the next bucket and return `{}` only if nothing else is found.

### I16. "Exposes nothing and ends one session" undersells the provider-token clear on GET logout
**Severity:** Low (wording)
**Description:** `CHANGELOG.rst:85` and `docs/guides/spa-authentication.rst:1029`
say a cross-site forced logout "exposes nothing" and ends one session. It also
clears the actor's stored provider token for every device (the guide says so
elsewhere), so the side effect reaches beyond one session. Availability only.
**Recommendation:** Add "and clears the actor's stored provider token for every
device" to both sentences.

### I17. A recurring internal error makes browser logout unrecoverable
**Severity:** Low (accepted trade-off)
**Description:** With the fail-closed 500, a persistent bug in the logout path
leaves the browser unable to clear `oauth_token` through `/oauth/logout`, and a
non-AJAX FastAPI request shows JSON instead of the redirect. This is the
consequence of the owner-approved choice (keep the retry handle, RFC 7009
§2.2.1) and is named in the changelog.
**Recommendation:** Accept.

## Overall Assessment

Every finding from the previous run is fixed, accepted or filed as a todo, and
the fixes are pinned by tests that pass on both backends (DynamoDB 3889 passed,
PostgreSQL 3780 passed, no failures); lint, type check and the `-W` docs build
are clean. The logout guarantee now holds without the earlier exception: a
confirmed revoke clears cookies, a known store fault answers 503, and any other
error answers 500 with nothing cleared. The UI was not exercised (no page
changed; login cannot be automated here).

Nothing found blocks merging. Five new Low findings (I13-I17) came out of the
second pass; I13, I15 and I16 are small and worth one more short iteration,
I14 and I17 are accepted. The Medium race (I1) and the mixed MCP/SPA logout
(I10) are filed as todos. The plan's `verified:` link points at this document;
the change is still uncommitted.
