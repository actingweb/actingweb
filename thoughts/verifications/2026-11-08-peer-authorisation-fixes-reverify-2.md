# Verification: peer authorisation fixes (second re-run, after iterations 11 to 17)

**Date:** 2026-11-08
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** a8007e5

This run verifies the plan's Iterations 11 to 17 (`d836bd0..a8007e5`), which
answered `verifications/2026-11-08-peer-authorisation-fixes-reverify-1.md`.
Phases 0 to 5 and Iterations 1 to 10 were verified in the two earlier runs
and are not re-walked here, except where this delta touches them.

## Automated Check Results

- **Browser QA:** N/A. No iteration changes a page.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`,
  outside the sandbox) and a fresh-context Claude reviewer, on
  `git diff d836bd0..a8007e5 -- actingweb tests/test_*.py docs CHANGELOG.rst`.
  Twelve findings and three unverified notes. I checked each against the
  code (see Issues Found; one codex finding, equal timestamps, is a note).
- **Built-in code review and security review:** not run as skills, as in
  the previous run. The delta is about 450 lines of library code; it got
  the outside voice (two models) and my own read of
  `actor.py`, `handlers/trust.py`, `handlers/callbacks.py`,
  `peer_permissions.py` and the concurrency tests.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (530 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: 54 groups
  documented; wire rows registry consistent.
- `make test-all-parallel`, DynamoDB: **6036 passed**, 60 skipped,
  1 xfailed (exit 0). The previous run's parallel flake in
  `test_actor_update_performance` did not recur.
- `make test-all-parallel`, PostgreSQL: **5833 passed**, 263 skipped,
  1 xfailed (exit 0).
- `sphinx-build -W ...`: build succeeded.
- No wire recording changed (`git diff d836bd0..a8007e5 -- tests/integration/wire` is empty).
- **Emm's suite on `a8007e5`** (gate 2), as
  `research/2026-11-07-emm-suite-against-master.md` describes: the library
  worktree re-pointed at `a8007e5` (`actingweb.__file__` confirmed in the
  worktree, the new auto-accept line present), Emm's adoption worktree
  with the two `subscriber` rows (uncommitted), environment 9.

  | Line | `a8007e5` | `master` baseline |
  | --- | --- | --- |
  | `scripts/with-preview-env.sh 9 poetry run pytest --timeout=180 --deselect tests/test_dependency_pin_guard.py` (PostgreSQL) | 2 failed, 7406 passed, 14 skipped, 179 deselected | 2 failed, 7406 passed, 14 skipped, 179 deselected |
  | `scripts/test-backends.sh 9` (DynamoDB Local) | 3 failed, 54 passed | 3 failed, 54 passed |

  The failures are the baseline's, by name
  (`test_dynamodb_iam_coverage`, `test_stripe_integration`'s expired Apple
  subscription; the two `test_dynamodb_operation_profile` constructions,
  `test_restore_actor_dynamodb`'s force import). Emm's suite has no test
  that creates a trust under auto-accept with a failing verification or
  reads a pending trust as its peer, so the two answers this iteration
  changed (202 instead of 201; 202 instead of 403) are not exercised by it.

## Phase Verification

### Iterations 11 to 17 - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py:2249-2257`: `if approved and not verified:` logs a
  WARNING and sets `approved = False`, after both the token check and
  `_base_uri_serves`. The async creation wraps the sync function, so no
  path approves an unverified creation. Matches iteration 11 (owner
  option (a)).
- `actingweb/handlers/trust.py:533-539`: the creation answers 201 only when
  the stored row's `approved` parses as `"true"`. Matches.
- `actingweb/actor.py:2303-2309`: `_base_uri_serves` uses `get_peer_info`'s
  defaults; its docstring states the limit. Matches iteration 16, with a
  cost (Issue 8).
- `actingweb/handlers/trust.py:687-699`: an unapproved row answers its own
  peer (by `acl["peerid"]`) and 403 to any other peer. The own peer gets
  back the secret and token it holds. Matches iteration 13.
- `actingweb/actor.py:2046-2070`, `2087`, `2111-2115`: the probe accepts
  200 or 202, parses `approved` as the string `"true"`, logs the probe's
  status, and the async probe catches `Exception`. Matches, with a gap
  (Issue 6).
- `actingweb/peer_permissions.py:325-368`, `handlers/callbacks.py:372-436`:
  read from the database, decide, delete, conditional write; five attempts,
  then 503 with `Retry-After: 1`. Matches iteration 14, with three gaps
  (Issues 1 to 3).
- `actingweb/maintenance/peer_state.py:327-360`: `rebuild_copies` after
  `prune`, printing `rebuilt` / `not rebuilt`. Matches iteration 15, with
  gaps (Issue 5).
- `db/dynamodb/trust.py`, `db/postgresql/trust.py`, `trust.py`: a refused
  modify restores the handle; `auth.py` `_record_trust_usage` and
  `interface/trust_manager.py` check the result. Matches iteration 16.
- `actingweb/fanout.py`: a `DbError` on `get_trust` becomes a
  `DeliveryResult` for that peer. Matches iteration 17.
- Docs (`CHANGELOG.rst`, `docs/reference/security.rst`,
  `docs/migration/v3.16.rst`, `docs/protocol/actingweb-spec.rst`,
  `docs/guides/database-maintenance.rst`): describe the above; two
  sentences overclaim (Issues 2 and 9).

**Security properties, the test that pins each:**

| Property | Test | What it asserts |
| --- | --- | --- |
| Auto-accept approves a verified creation | `tests/test_trust_re_pair.py:823` | 201, `row["approved"] is True` |
| Auto-accept does not approve an unverified one | `tests/test_trust_re_pair.py:830` | 202, `approved is False and verified is False` when `/meta` names `someone-else` |
| The real peer then replaces the unverified squat | `tests/test_trust_re_pair.py:838` | 202 for the squat, then 201 and `approved and verified` for the real peer |
| The own peer reads its pending row; another peer does not | `tests/test_trust_re_pair.py:861`, `:867` | 202 with `approved is False`; 403 |
| A lost re-pair answered 202 is confirmed | `tests/test_trust_re_pair.py:872` | `row["secret"] == new and row["peer_approved"] is False` (the 202 is mocked; `:861` pins the receiver side separately) |
| A refused modify keeps the local copy | `tests/test_trust_re_pair.py:894` | `stale.modify(...) is False`, `stale.trust == before` |
| An older callback that loses the race is ignored | `tests/test_peer_binding.py:773` | 204, stored `excluded_patterns == ["newer"]` (real conditional update, a row existed) |
| A newer callback that loses the race is stored | `tests/test_peer_binding.py:814` | 204, the newer row stored (real `create_attr_if_absent`, no row before) |
| A removed copy is rebuilt from the peer | `tests/test_peer_state_command.py:273` | `rebuilt` line and the copy stored; a fetch failure prints `not rebuilt` (`:270`) |
| A trust read fault is reported for its peer | `tests/test_fanout.py:724` | `DeliveryResult(peer, error="trust read failed")` |

The concurrency tests inject a racing callback between the read and the
write; they do not cover a revocation and a grant racing (Issue 2) or a
query writer racing a callback (Issue 3).

**Deviations from plan:**
- None beyond what Issues 1 to 9 describe.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-1.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The `/meta` check does not stop a squat; auto-accept approves one regardless | **Fixed as decided (owner option (a))**: an unverified creation is never auto-approved; a squatter that runs its own server and verifies is documented as a limitation | `actor.py:2249-2257`; `test_trust_re_pair.py:830`, `:838`; `docs/reference/security.rst:113` |
| 2. An `admin` peer can become another peer through DELETE | **Accepted as-is (owner)**, documented | `docs/reference/security.rst`, `docs/migration/v3.16.rst`, CHANGELOG |
| 3. A lost 202 re-pair is never confirmed | Fixed; the probe accepts any 200/202 body (Issue 6) | `actor.py:2050`; `handlers/trust.py:687-699`; `test_trust_re_pair.py:861`, `:872` |
| 4. Concurrent permission callbacks roll back a revocation | **Fixed between callbacks**; open against query writers and for a revoke racing a grant (Issues 2, 3) | `callbacks.py:372-436`; `test_peer_binding.py:773`, `:814` |
| 5. After `prune --all-permissions --apply` the next revocation deletes nothing | Fixed for `permissions-copy`; window and gaps (Issue 5) | `peer_state.py:327-360`; `test_peer_state_command.py:273` |
| 6. A refused DynamoDB modify changes the local object; callers ignore False | Fixed | `db/dynamodb/trust.py`, `db/postgresql/trust.py`, `trust.py`; `test_trust_re_pair.py:894` |
| 7. The `/meta` fetch: one try | Fixed, with a cost (Issue 8) | `actor.py:2309` |
| 8. `FanOutManager` reads the trust outside its `try` | Fixed | `fanout.py`; `test_fanout.py:724` |

## Remaining Tasks

- [ ] Issues 1 to 4 (`/iterate_plan`): the permission-callback path the
      SECURITY entry describes.
- [ ] Issues 5 to 9: fold or accept.
- Todos: the plan closes none. Its one deferral,
  `thoughts/todo/full-state-fallback-replica.md`, has its `INDEX.md` row.

## Issues Found

### Issue 1: a 503 permission callback is never sent again
**Severity:** Medium
**Description:** After five lost races, or one backend fault (which the
conditional write reports as a lost race, see Issue 4), the callback answers
503 with `Retry-After: 1` and the log says "answered 503 for the sender to
retry". The library's own sender does not retry: `trust_permissions.py`
`_notify_peer` (`:264`) and `_notify_peer_async` (`:327`) send once and log
a failed status at WARNING. The grant or revocation is lost until the next
callback or query, and the receiver may already have deleted data (Issue 2).
The CHANGELOG's "(503 with ``Retry-After`` after five lost races in a row)"
reads as if delivery is assured.
**Location:** `actingweb/handlers/callbacks.py:428-436`;
`actingweb/trust_permissions.py:264`, `:327`
**Recommendation:** a bounded retry on 503 in both senders (honouring
`Retry-After`), or reword the CHANGELOG and the log line so they promise
nothing the sender does not do.

### Issue 2: revoked data is deleted before the write wins
**Severity:** Medium
**Description:** `_delete_revoked_peer_data` (`callbacks.py:419`) runs before
`store.replace_permissions(peer_perms, expected)` (`:425`). Take a
revocation (sender time T1) and a newer re-grant (T2) that both read the
row T0, which grants pattern P. The revocation deletes P's data and loses
the write. T2 wins, but compared against T0 it sees no new grant, so no
sync runs (`:450-455` needs `granted_patterns`). The revocation's retry
reads T2, is older, answers 204. Result: the copy grants P and the replica
holds none of P's data, with no error. The CHANGELOG's "an older callback
... changes nothing (no deletion of revoked data, ...)" is false in this
case. Before this delta the same pair could instead roll back the
revocation, so this is not a regression, but the race is not closed.
**Location:** `actingweb/handlers/callbacks.py:410-427`
**Recommendation:** delete only after the conditional write wins (the
retry then sees the same revocation again if a later attempt fails), or
re-sync the winner's grants that the losing attempt deleted.

### Issue 3: the query path still overwrites the copy unconditionally
**Severity:** Medium
**Description:** `store_permissions` orders writes by this process's cache
only (`peer_permissions.py:282-283`, `existing = self._cache.get(cache_key)`)
and then calls `bucket.set_attr`. Its writers
(`interface/subscription_manager.py:2503`, `:2585`, `:2907`;
`maintenance/peer_state.py:354`) are not part of the conditional write. A
query fetched before a revocation and stored after it, in another worker
or Lambda instance, writes the old grant over the revocation. Iteration
14's rationale ("a sync after the winner's revocation fetches from the
granting peer") assumes the fetch starts after the revocation; nothing
enforces that.
**Location:** `actingweb/peer_permissions.py:264-310`
**Recommendation:** store query results through the same read and
conditional write, refusing a copy whose `fetched_at` is older than the
stored row's; or record the residual race in the plan and the CHANGELOG.

### Issue 4: a backend fault on the write reads as a lost race
**Severity:** Low
**Description:** `conditional_update_attr` returns False on a fault on
both backends (`attribute.py` docstring: "Both backends also answer False
on a fault"), while `create_attr_if_absent` raises `DbError`. A fault on an
existing row therefore runs the deletion and the write five times and logs
"lost 5 concurrent writes in a row". The answer (503) is right; the log
names the wrong cause, and the backends differ by whether a row existed.
**Location:** `actingweb/peer_permissions.py:358-363`;
`actingweb/handlers/callbacks.py:428-433`
**Recommendation:** after a False, re-read; if the row still equals
`expected`, raise `DbError` (the handler's fault path answers 503).

### Issue 5: `prune --all-permissions --apply` rebuilds late and not everything
**Severity:** Low
**Description:** `cmd_prune` removes every finding (`peer_state.py:327`)
before it rebuilds any (`:328`). Across many actors at `--rps`, each copy
stays missing for the length of the run, and a `StoreUnavailable` raised
in `prune` stops the command before any rebuild, with no `not rebuilt`
lines. `rebuild_copies` also skips `future-permissions` findings
(`:350`, `if f.kind != PERMISSIONS_COPY`), which are removed for a trusted
peer without `--all-permissions` too and leave the same gap. Separately,
`subscription_manager.py:2503` and `:2585` store a failed fetch
(`fetch_error` set, empty permissions) over a good copy, which reaches the
same "no copy to compare against" state without any prune; `:2902` has the
guard. That path predates this branch.
**Location:** `actingweb/maintenance/peer_state.py:327-350`;
`actingweb/interface/subscription_manager.py:2497-2503`, `:2580-2585`
**Recommendation:** rebuild each copy right after removing it, include
`future-permissions` for a trusted peer, and add the `fetch_error` guard at
the two sites.

### Issue 6: the lost-answer probe accepts any 200 or 202
**Severity:** Low
**Description:** `_re_pair_probed` treats `status in (200, 202)` as
confirmation whatever the body (`actor.py:2050-2061`); a body that does not
parse is `None` and reads as "pending". A peer behind a proxy or catch-all
that answers 200 with HTML makes the initiator store a secret the peer
never received, logged at INFO as confirmed. Only the initiator's own
pairing splits; nothing is exposed.
**Location:** `actingweb/actor.py:2050-2061`
**Recommendation:** require a JSON object whose `peerid` is this actor's
id before confirming.

### Issue 7: under auto-accept, a transiently unverified honest row can be displaced
**Severity:** Low
**Description:** an honest peer whose verification or `/meta` fetch fails
transiently is now stored pending (`actor.py:2249-2257`). A pending row is
replaced by any request that verifies (`:2263-2278`), so a squatter running
its own server can replace it and be auto-approved. The honest peer has a
202 and a secret that no longer works at the receiver. The documented
limitation covers an id with no row, not this one. No log names the
replacement as such.
**Location:** `actingweb/actor.py:2249-2278`
**Recommendation:** a WARNING when a pending row is replaced, and one
sentence next to the limitation in `docs/reference/security.rst`.

### Issue 8: an unauthenticated trust request can hold a worker for about a minute
**Severity:** Low
**Description:** `_base_uri_serves` now uses `get_peer_info`'s defaults
(`actor.py:2309`; `max_retries=3` at `:150`, `timeout=(5, 10)` at `:186`).
With the verification GET (`timeout=(5, 10)`) before it, one
`POST /trust/<rel>` naming a slow host can take roughly 60 s. The previous
run's Issue 7 asked for retries; this is the cost.
**Location:** `actingweb/actor.py:2309`
**Recommendation:** one retry with a short connect timeout, or record the
cost as accepted.

### Issue 9: the security reference understates when a request is a re-pair
**Severity:** Low
**Description:** `docs/reference/security.rst:113` says "For a peer that
already has a verified row it is a re-pair". The code also re-pairs an
approved row, and any row whose current secret the requester proves
(`handlers/trust.py:450-452`).
**Location:** `docs/reference/security.rst:113`
**Recommendation:** "For a peer that already has a row it is a re-pair
when the request proves the row's current secret, or when the row is
verified or approved".

### Notes (not findings)
- **Equal sender timestamps** (codex): two callbacks with the same
  timestamp both pass `<` (`callbacks.py:396`). The sender stamps with
  microsecond precision (`trust_permissions.py:486`), and `<=` would also
  refuse a resend of the same callback. Not changed.
- **A fault mid-modify** leaves the `Trust` object holding values never
  written (the restore runs only on a refused write, not on `DbError`).
  No caller found that keeps using the object after catching `DbError`.
- **The pending row's own peer can read `?permissions=true`**
  (`handlers/trust.py:664-684` runs before the pending check): it sees the
  permissions the owner has set for it before approving. These are its own
  grants; listed for the owner's awareness.
- Each worker keeps its own `PeerPermissionStore._cache`; other workers
  serve a stale copy after a conditional write. Predates the branch; the
  prune output tells operators to restart.

## Overall Assessment

The iteration does what the owner decided and what the previous run asked
for, in the cases its tests exercise. Auto-accept no longer approves an
unverified creation, and the self-asserted id is documented as a limitation
rather than claimed as fixed. The admin DELETE is documented. A lost 202
re-pair is now confirmed, a refused modify keeps local state, and fanout
reports a trust read fault. Both backends are green, the docs build, no
recording changed, and Emm's suite on `a8007e5` matches its `master`
baseline on both backends.

The permission-callback concurrency fix is narrower than the CHANGELOG's
SECURITY entry reads. It orders callbacks against each other. It does not
order them against the query path (Issue 3). It deletes data before it
knows it has won (Issue 2), and its 503 assumes a sender that retries,
which the library's own sender does not (Issue 1). None of these exposes
data to another peer. Each one can leave a receiver's replica or its
permission copy out of step with the granting peer, with no error. I would
fix Issues 1 to 3, or narrow the CHANGELOG to what holds, before the PR
opens. Issues 4 to 9 are small; fold or accept them. If code changes, a
further verification is warranted, scaled to that delta.
