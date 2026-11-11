# Verification: peer authorisation fixes (third re-run, after iterations 18 to 24)

**Date:** 2026-11-08
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** dca966f

This run verifies the plan's Iterations 18 to 24 (`a8007e5..dca966f`), which
answered `verifications/2026-11-08-peer-authorisation-fixes-reverify-2.md`.
It is scaled to that delta: earlier phases and iterations are not re-walked.

## Automated Check Results

- **Browser QA:** N/A. No iteration changes a page.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`,
  outside the sandbox) and a fresh-context Claude reviewer, on
  `git diff a8007e5..dca966f -- actingweb tests docs CHANGELOG.rst`. Nine
  findings plus four unverified notes. I checked findings 1 to 4, 6, 7 and
  9 against the code (quoted below); 5 and 8 are wording and an accepted
  cost.
- **Built-in code review and security review:** not run as skills, as in
  the two previous re-runs. The outside voice (two models) and my own read
  of `callbacks.py`, `peer_permissions.py`, `trust_permissions.py`,
  `peer_state.py` and `aw_proxy.py` cover the delta.
- **Full tier**, run on the exact tree committed as `dca966f` (the commit
  followed the run; nothing changed between):
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups
    documented; wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6051 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5848 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - No wire recording changed.
  - The run before it failed
    `tests/integration/test_peer_state_flow.py::test_prune_removes_the_stale_and_the_pair_still_works`
    on both backends: it expected the live peer's future-dated copy to stay
    removed, which iteration 21 changed on purpose. The test was updated
    (plan iteration 21) before the run above.
- **Emm's suite on `dca966f`** (library worktree re-pointed, `_retry_after`
  present; adoption worktree with the two `subscriber` rows; environment
  9):

  | Line | `dca966f` | `master` baseline |
  | --- | --- | --- |
  | `scripts/with-preview-env.sh 9 poetry run pytest --timeout=180 --deselect tests/test_dependency_pin_guard.py` (PostgreSQL) | 2 failed, 7406 passed, 14 skipped, 179 deselected | 2 failed, 7406 passed, 14 skipped, 179 deselected |
  | `scripts/test-backends.sh 9` (DynamoDB Local) | 3 failed, 54 passed | 3 failed, 54 passed |

  The baseline's failures, by name; no new one.

## Phase Verification

### Iterations 18 to 24 - ISSUES FOUND

**Changes verified:**
- `actingweb/trust_permissions.py:325-337`, `:403-414`: both senders resend
  a 503 up to twice with the same `callback_data`; `_retry_after` caps and
  defaults. Matches iteration 18, with a logging gap (Issue 2).
- `actingweb/handlers/callbacks.py:378-468`, `:1115`: `deleted` collects
  every attempt's deletion; the ignored path syncs it, the stored path
  syncs granted plus deleted minus the last diff's revoked patterns.
  Matches iteration 19's text, but the filter is the last diff, not the
  stored copy (Issue 1).
- `actingweb/peer_permissions.py` `store_permissions`,
  `replace_permissions`: database read, `fetched_at` compare, conditional
  write, five attempts; a refused update on an unchanged row raises
  `DbError`. Matches iteration 20; query copies drop the sender's
  timestamp (Issue 4).
- `actingweb/maintenance/peer_state.py:340-365`: per-copy rebuild after
  each removal, `future-permissions` included, a store fault listed.
  Matches iteration 21, except a fault during the fetch (Issue 3).
- `actingweb/interface/subscription_manager.py`: both refreshes skip a
  failed fetch. Matches.
- `actingweb/actor.py`: probe needs `peerid == self.id`; `/meta` two tries
  of `(3, 5)`; replacement WARNING (Issue 5 on its placement). Matches
  iterations 22 and 23.
- Docs: security reference re-pair wording (iteration 24) matches
  `handlers/trust.py:450-452`.

**Security properties, the test that pins each:**

| Property | Test | What it asserts |
| --- | --- | --- |
| A 503 is resent with the same body | `tests/test_trust_permissions_unit.py` `TestThePermissionSenderResendsA503` | two identical bodies; three sends at most; async waits `Retry-After` (1.0) |
| Data a losing revocation deleted comes back under a re-grant | `tests/test_peer_binding.py` `test_a_revocation_that_loses_to_a_regrant_restores_what_it_deleted` | delete of `["p/*"]`, then sync of `["p/*"]`, stored `patterns == ["p/*"]` |
| A query older than the stored copy is not stored, in another process | `tests/test_peer_binding.py` `test_a_query_older_than_the_stored_copy_is_not_stored` | `store_permissions(...) is False`, stored `patterns == []` |
| A fault on the conditional write is not a lost race | `tests/test_peer_binding.py` `test_a_fault_on_the_conditional_write_raises` | `DbError` |
| A copy is rebuilt before the next removal | `tests/test_peer_state_command.py` `test_each_copy_is_rebuilt_before_the_next_is_removed` | each `rebuilt` line follows its own `removed` line |
| A failed query keeps the copy | `tests/test_subscription_baseline_fetch.py` `test_a_failed_permission_query_keeps_the_stored_copy` | `store_permissions` not called on `fetch_error` (sync and async) |
| A probe answer that is not our row confirms nothing | `tests/test_trust_re_pair.py` `test_an_answer_that_is_not_our_trust_row_confirms_nothing` | three cases; row unchanged |
| The `/meta` check is two short tries | `tests/test_trust_re_pair.py` `test_the_meta_check_is_two_short_tries` | two calls, `timeout == META_CHECK_TIMEOUT` |

All of them failed before their fix (checked by stashing the code change).
No test covers a revocation that loses to a writer that also lacks the
pattern (Issue 1) or a query write between a 503 and its resend (Issue 4).

**Deviations from plan:** none beyond the Issues.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A 503 permission callback is never sent again | Fixed (owner: bounded resend); the final failure is logged as success on the sync path (Issue 2) | `trust_permissions.py:325-337`, `:403-414` |
| 2. Revoked data deleted before the write wins | Fixed for the tested case; the filter is too narrow (Issue 1), the 503 exit restores nothing (Issue 6) | `callbacks.py:378-468` |
| 3. The query path overwrites unconditionally | Fixed; query copies drop the sender timestamp (Issue 4) | `peer_permissions.py` `store_permissions` |
| 4. A fault reads as a lost race | Fixed | `peer_permissions.py` `replace_permissions` |
| 5. Prune rebuilds late and not everything | Fixed, except a fault during the fetch (Issue 3) | `peer_state.py:340-365` |
| 6. The probe accepts any 200/202 | Fixed | `actor.py` `_re_pair_probed` |
| 7. A displaced pending row is silent | Fixed; the WARNING precedes the write (Issue 5) | `actor.py:2282` |
| 8. `/meta` can hold a worker a minute | Fixed (owner: two short tries); the trust POST's worst case is now about 30 s, the verification GET unchanged | `actor.py` `META_CHECK_*` |
| 9. Security reference wording | Fixed | `docs/reference/security.rst:113` |

## Remaining Tasks

- [ ] Issues 1 to 4 (`/iterate_plan`).
- [ ] Issues 5 to 7: fold or accept.
- Accepted by the owner (iteration 18 decision): the synchronous resend
  blocks the owner's permission change (outside voice finding 8).
- Todos: the plan closes none; its deferral
  `thoughts/todo/full-state-fallback-replica.md` has its `INDEX.md` row.

## Issues Found

### Issue 1: the restore filters by the last diff, not by what the stored copy grants
**Severity:** Medium
**Description:** `callbacks.py:457`
`final_revoked = set(permission_changes.get("revoked_patterns", []))` holds
only what the last attempt's diff revoked. A revocation that deletes P,
loses to a writer whose row also lacks P, and then stores (its diff
against a row without P revokes nothing) syncs P again (`:462`). The
ignored-as-older path (`:408`) syncs everything deleted, unfiltered. Both
then rely on the granting peer refusing P; a granting worker serving a
stale cached grant (`trust_permissions.py` `get_permissions`, a per-process
cache) would hand revoked data back, after the revocation was handled.
The CHANGELOG says "the stored permissions no longer revoke", which is not
what the code checks.
**Location:** `actingweb/handlers/callbacks.py:405-412`, `:455-468`
**Recommendation:** sync only deleted patterns that the final stored copy
grants: `peer_perms` on the stored path, `old_permissions` on the ignored
path (its `properties["patterns"]`, minus `excluded_patterns`); add the
test for a revocation losing to a writer that also lacks the pattern.

### Issue 2: the synchronous sender logs a final 503 as a success
**Severity:** Medium
**Description:** `trust_permissions.py:341`
`if response is not None and "error" not in response:` decides success.
The callback handler's 503 has no body, and `AwProxy.create_resource`
returns `{}` for a body it cannot parse (`aw_proxy.py:283-289`), so after
both resends fail the lost update is logged at DEBUG as delivered. The
async sender decides on `status_code`.
**Location:** `actingweb/trust_permissions.py:341`
**Recommendation:** decide on `proxy.last_response_code` being 2xx, and
log the final status at WARNING otherwise; a test for 503 three times.

### Issue 3: a fault while the rebuild queries the peer escapes `prune`
**Severity:** Medium
**Description:** `peer_state.py:354`
`perms = fetch_peer_permissions(f.actor_id, peer_id, config)` is outside
the `try`; `fetch_peer_permissions` re-raises `DbError`
(`peer_permissions.py:600-601`), which `AwProxy`'s strict trust read can
raise. The copy is already deleted, no `not rebuilt` line is printed, and
`main` catches only `StoreUnavailable`, so the command ends in a
traceback rather than exit 2.
**Location:** `actingweb/maintenance/peer_state.py:354`
**Recommendation:** include the fetch in the `except DbError` (`store
fault`), or raise `StoreUnavailable` naming what was removed; a test.

### Issue 4: a copy written by a query drops the sender's timestamp
**Severity:** Medium
**Description:** query copies are built with empty `extra_attributes`
(`peer_permissions.py` `fetch_peer_permissions`, `fetch_peer_permissions_async`)
and stored whole by `store_permissions`, so the next callback's ordering
check (`callbacks.py:392` `previous = ... .get(SENDER_TIMESTAMP_KEY)`)
finds none and accepts any older callback. With the new resend, a callback
answered 503, then a newer callback stored, then a query refresh, lets the
1-2 s later resend of the older callback win: an old grant comes back, or
data the peer grants again is deleted. The CHANGELOG's "an older callback
... changes nothing" holds only until the next query write.
**Location:** `actingweb/peer_permissions.py` `store_permissions`
**Recommendation:** carry the stored row's `sender_timestamp` into the
query copy before the conditional write; a test.

### Issue 5: the pending-row WARNING precedes the write that can lose
**Severity:** Low
**Description:** `actor.py:2282` logs "replaces its pending row ... the
previous requester's secret no longer works here" before
`create(..., only_if_pending=True)`, which can lose.
**Location:** `actingweb/actor.py:2281-2285`
**Recommendation:** log after `created` is truthy.

### Issue 6: the 503 exit restores nothing
**Severity:** Low
**Description:** on five lost races, or a `DbError` from
`replace_permissions`, what earlier attempts deleted is dropped
(`callbacks.py:436-446` returns, and the `DbError` propagates). The resend
starts with an empty `deleted`; if it is then older than the winner it
answers 204 and restores nothing.
**Location:** `actingweb/handlers/callbacks.py:436-446`
**Recommendation:** on that exit, sync what was deleted, filtered by the
stored copy as in Issue 1 (best effort).

### Issue 7: the 503 is described as lost races only; the restore as certain
**Severity:** Low
**Description:** CHANGELOG (`:111`) and `docs/migration/v3.16.rst` name
only lost races as the cause of the 503; a storage fault (`DbError` from
`replace_permissions`) answers 503 too, as the spec paragraph says. "Is
fetched again" reads as certain; the sync is attempted once and a failure
only logged (`callbacks.py:1150`).
**Location:** `CHANGELOG.rst:105-121`; `docs/migration/v3.16.rst`
**Recommendation:** "or a storage fault"; "is fetched again (best effort;
a failure is logged)".

### Notes (not findings)
- `_rebuild_copy` waits on the limiter once per copy, for one HTTP call and
  up to about 16 database operations; `--rps` undercounts there.
- A permanent DynamoDB failure on the conditional update (an item-size
  `ValidationException`) becomes a transient-looking 503; the sender
  resends and the deletion runs again.
- The trust POST's worst case is now about 30 s (`/meta` two tries of
  `(3, 5)` after the verification GET's `(5, 10)`).
- `remote_storage.apply_permission_data` has no library caller; a consumer
  calling it writes a copy without `sender_timestamp` (Issue 4).

## Overall Assessment

The iteration closes reverify-2's nine issues as decided: the sender
resends, every writer of the stored copy is conditional, a fault is a
fault, prune rebuilds per copy, the probe needs our row and `/meta` is
bounded. Every new test failed before its fix. Both backends are green,
the docs build, no recording changed, and Emm's suite on `dca966f` matches
its baseline.

Four medium issues remain in the permission-copy path, all at its edges:
the restore's filter is the last diff instead of the stored grant
(Issue 1), the sync sender's final failure is logged as success (Issue 2),
a fault during the rebuild's fetch escapes `prune` (Issue 3), and a query
write drops the sender's ordering timestamp (Issue 4). None exposes data
to another peer or lets a peer act as another; each can leave a receiver's
copy or replica out of step without an error. They are small, local
fixes; I would make them, with Issues 5 to 7, before the PR opens. If code
changes, the next verification can be scaled further.
