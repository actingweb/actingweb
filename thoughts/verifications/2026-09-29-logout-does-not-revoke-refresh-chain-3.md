# Verification: SPA logout and `/oauth/revoke` end the refresh chain (third run)

**Date:** 2026-09-29
**Plan:** thoughts/plans/2026-09-29-logout-does-not-revoke-refresh-chain.md
**Research:** thoughts/research/2026-09-28-logout-does-not-revoke-refresh-chain.md
**Branch:** fix/3.15.1-logout-revokes-chain
**Commit:** 60aecbe, plus an uncommitted delta of six files (plan Iterations 11-13)

No feature document, so no Success Measures section. This run covers the whole
plan (all three phases, Iterations 1-13), re-checked at the full tier; the
adversarial passes concentrated on the delta since the second run, because the
two earlier runs covered the rest.

## Automated Check Results

Full tier from `CLAUDE.md`, run once, one run at a time. Both test runs are the
**parallel** `make test-all-parallel`; neither showed a failure, so no
sequential re-run was needed.

- **Browser QA:** N/A. No phase changes a page; browser QA cannot log in (real
  OAuth2 provider, no test account). **The UI was not exercised.**
- **Second opinion:** the outside-voice agent ran with a fresh-context Claude
  reviewer only (no Codex, so no second-model coverage) on the delta. Nothing
  High or Medium; three Low notes (I18 to I20 below carry the ones kept).
- **Built-in code review (high):** ran, 10 findings. Two are kept (I18, I19);
  the others repeat accepted or filed items (the mixed MCP/SPA logout I10, the
  pre-3.15.1 session limitation, the duplicated helpers and cookie lists, the
  DynamoDB scan cost) or are style.
- **Built-in security review:** 0 findings at confidence 8 or above.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass.
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel` on **DynamoDB**: pass, **3890 passed, 31 skipped**,
  0 failed.
- `make test-all-parallel` on **PostgreSQL** (port 5433): pass, **3781 passed,
  140 skipped**, 0 failed.
- `sphinx-build -W --keep-going ...`: pass (exit 0 under `-W`).
- Benchmarks: not run (no list-storage change).
- No file was modified while the reviewers ran (the second run's brief
  mutation check was not repeated).

## Previous Verification

**Previous:** thoughts/verifications/2026-09-29-logout-does-not-revoke-refresh-chain-2.md
(and, before it, `...-refresh-chain.md`; their fixed items stay fixed, the full
tier passing again on both backends).

| Issue then | Status now | Evidence |
| --- | --- | --- |
| I13 `_handle_session_token_logout` docstring false | **Fixed** | `oauth2_endpoints.py:1114` "A token store fault is caught here and answered ``retry`` (503)... before the caller's catch-all"; Iteration 11 |
| I14 Sweep counts a non-mapping row as skipped every run | Accepted as-is | unchanged |
| I15 `revoke_session` returns `{}` without searching the other bucket | **Fixed** | `oauth_session.py:1078,1100,1104` (`removed_malformed`, search continues); `tests/test_oauth_session.py:878`; Iteration 12 |
| I16 GET-logout wording undersells the provider-token clear | **Fixed** | `CHANGELOG.rst:86`, `docs/guides/spa-authentication.rst` GET-logout note; Iteration 13 |
| I17 Recurring internal error makes logout unrecoverable | Accepted as-is | owner-approved fail-closed 500 |
| I1 Logout/refresh race | Filed | `thoughts/todo/spa-logout-refresh-rotation-race.md` |
| I10 MCP token plus SPA refresh cookie | Filed | `thoughts/todo/logout-mcp-token-with-spa-refresh-cookie.md` |
| I5, I8, I9 | Accepted as-is | unchanged (Iterations 3, 4, 9) |

## Phase Verification

- **Phase 1 - VERIFIED.** Chain revocation core, `revoke_session`
  (`oauth_session.py:1030` onwards, now searching past a malformed row),
  both `delete_by_chain` backends, `_sweep_index`; Phase 1 tests and
  `tests/integration/test_spa_chain_revocation_backend.py` pass on both
  backends.
- **Phase 2 - VERIFIED.** Login tagging, `/oauth/revoke`, `/oauth/logout`
  (500 on an unexpected error, form-body refresh token), SDK logout, FastAPI
  route; `tests/integration/test_oauth2_spa_logout.py` passes on both backends.
- **Phase 3 - VERIFIED.** CORS builder, docs (`-W` build passes), changelog,
  todo bookkeeping (two new todos filed, five deleted).

**Security property, re-demonstrated** by the tests named in the first
verification (logged-out refresh token answers 401 and another chain survives;
a fault answers 503 with no cookie change and the retry succeeds) plus the
fail-closed test
`tests/test_oauth2_spa_logout_revokes_chain.py:404`, all passing on both
backends.

## Remaining Tasks

- [ ] Commit the six-file delta (Iterations 11-13) and this verification.
- [ ] Optional: I18 and I19 below.
- [ ] Then the PR to `master`; the version bump and changelog promotion belong
      to the release PR.

## Issues Found

### I18. A logout that partly succeeds and returns 503 cannot repair the provider-token clear on retry
**Severity:** Low
**Description:** `_handle_session_token_logout` collects `actor_id`s from
`revoke_session` and clears the provider token only after the loop
(`oauth2_endpoints.py` around `:1141`). If the first token (say an access token)
revokes and the second (a refresh token of another chain) faults, the answer is
503 before any clear. On the retry the first token's row is gone, so its actor is
not collected. It matters only when the two tokens belong to different actors;
for the same actor the second token's row still names it. The same gap exists
if `_clear_provider_token_for_actor` swallows an error after a confirmed revoke
(it logs at debug). The exposure is a stored provider token surviving a logout.
**Recommendation:** Clear the provider token for each actor as its revoke is
confirmed, or accept: the request shape is unusual.

### I19. The login sites do not catch the new `TokenStoreUnavailable`
**Severity:** Low (accepted; scope stated in the plan)
**Description:** `store_access_token` and `_generate_actingweb_token` raise on a
failed write and the login and callback sites (`oauth2_spa.py:1012,1173,1422`,
`oauth2_callback.py:714,789,1246`) do not convert it to 503, so a store fault
during login is a framework 500. The plan states the scope: the SPA sites already
failed the same way through `create_refresh_token`; the www cookie login gains a
500, named in the changelog.
**Recommendation:** Accept for 3.15.1; a consistent 503 for every login site is
a separate change.

### I20. The malformed-row fix is defensive, not an observed leak
**Severity:** Low (wording)
**Description:** The same token string sits in both buckets only if planted
(access and refresh tokens are generated independently), so the Iteration 12
scenario is unreachable in production; the new test proves the loop.
**Recommendation:** Read Iteration 12 as hardening; no change needed.

## Overall Assessment

The implementation is complete and correct against the plan. Every finding from
the earlier runs is fixed, accepted or filed, the three Iterations 11-13 fixes
are pinned by tests, and the full tier is green on both backends (DynamoDB 3890
passed, PostgreSQL 3781 passed, no failures) with lint, type check and the `-W`
docs build clean. The adversarial passes on the delta found nothing High or
Medium; the security review found nothing at confidence 8 or above. The UI was
not exercised (no page changed; login cannot be automated here).

Nothing found blocks merging. The loop can close here: I18 to I20 are Low and
optional, and the two Medium/Low items with real consequences (the
logout/refresh race and the mixed MCP/SPA logout) are filed as todos. The
plan's `verified:` link points at this document. The delta is uncommitted.
