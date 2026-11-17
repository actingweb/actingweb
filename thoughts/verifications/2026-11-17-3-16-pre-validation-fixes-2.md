# Verification: the fixes 3.16 takes before its release validation (re-run 4)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 8bb63cf plus the uncommitted third and fourth iterations
(iterations log entries 11 to 20)

A re-run, scaled to the fourth iteration (entries 16 to 20): one rule,
`rebuilds_for`, for every path that runs an owed rebuild; a hook on another
target; duplicates under a sequence that is not an integer; the fault
contract stated; the once-a-minute test without `auto_storage`.

## Automated Check Results

The Full tier ran on the working tree.

- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass, 599 files.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass.
- `make test-all-parallel`, **DynamoDB**: pass, 8,037 passed, 212 skipped,
  2 xfailed.
- `make test-all-parallel`, **PostgreSQL**: pass, 7,809 passed, 440
  skipped, 2 xfailed.
- `sphinx-build -W --keep-going`: pass.
- **The consumer's suite** (environment 9; the library worktree checked
  out at `8bb63cf` with this tree's uncommitted `actingweb/` diff applied,
  identical by `diff`): PostgreSQL 3 failed, 7,405 passed, 14 skipped,
  179 deselected; DynamoDB lane 3 failed, 54 passed. The same six failures
  by name as on `ab11326`, nothing new (logs
  `../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-iter4.log`). The first
  PostgreSQL run also had 125 errors, every one a refused connection to the
  environment's preview server on port 5009, which was not running; with
  `scripts/preview-start.sh 9 --no-ngrok` up the lane was run again (the
  numbers above) and the server stopped after.
- **Second opinion:** codex (`codex exec -s read-only`, told not to run
  tests) and a fresh-context reviewer, on entries 16 to 20. Two Medium,
  six Low, one disputed (Issues below).
- **Security review:** not re-run. Re-run 3 ran it on the whole branch
  (nothing at the bar); entries 16 to 20 change only when a subscriber
  rebuilds and whom it tells.
- **Browser QA:** not re-run; nothing a user sees changed.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-17-3-16-pre-validation-fixes.md
**Iterations since:** entries 16 to 20 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A hooks-only subscriber's failed behind rebuild is settled untold (Medium) | Fixed for a subscriber with a data hook: the owed rebuild runs on its next poll or callback after the interval and tells. Residuals: a subscriber with only the legacy hook (Issue 1, predates the branch) and a millisecond window (Issue 3) | `rebuilds_for`; `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_hooks_only_rebuild_owed_after_a_failure_is_told_when_it_runs`; `tests/test_subscriber_receiver_1_5.py::test_a_hooks_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told` |
| 2. The hook condition counts a hook on any target (Low) | Fixed | `::test_a_hook_on_another_target_does_not_make_a_behind_poll_rebuild` |
| 3. Duplicates under a non-integer sequence tell every poll (Low) | Fixed (the refetch and reapply remain, a cost only) | `::test_duplicates_under_a_sequence_that_is_no_integer_tell_no_hook` |
| 4. A store fault on a hooks-only behind poll escapes as `DbError` (Low) | Accepted and stated for the poll; the callback path is not stated (Issue 5) | `sync_subscription` docstring |
| 5. Two new tests do not pin what they describe (Low) | Partly: the once-a-minute hooks-only case pins entry 13, not 16 (Issue 6) | `::test_a_failing_behind_rebuild_is_attempted_once_a_minute` |

## Acceptance Criteria

Only AC-8 changed (annotation, entries 16 and 17).

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-8 | `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks` (the hooks-only owed rebuild, the other target, with the earlier cases); `tests/test_subscriber_receiver_1_5.py::test_a_hooks_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told` | Yes for the poll. The callback test patches `_rebuild_owed_and_due`, so it pins the gate, not the `target=` plumbing (Issue 6) | Pass |

## Remaining Tasks

- [ ] Issue 1: the owner's call (it predates the branch; see its text).
- [ ] Issues 2 to 6 (Low), at the owner's choice.
- [ ] Commit entries 11 to 20 with the third, fourth and this verification.

## Issues Found

### 1. A subscriber with only the legacy `subscription` hook still owes rebuilds that run untold
**Severity:** Medium (peer-reachable: a publisher's resync URL that fails
marks the rebuild owed). **Predates the branch**: the owing, the
processor's REBUILD answer and its untold branch are on master as they
are here.
**Description:** `rebuilds_for` counts data hooks only, but the callback
path also tells the legacy `subscription` callback hook. With
`auto_storage` off and only that hook, a resync whose fetch fails marks
the rebuild owed; the next diff skips the gate, the processor answers
REBUILD after the interval, and that branch rebuilds, records the sequence
and clears the publisher's diffs without telling the hook. Entry 16's
"all three ask one rule" is true for data hooks only.
**Location:** `actingweb/interface/subscription_manager.py` `rebuilds_for`
`hooks = getattr(config, "subscription_data_hooks", None) or {}`;
`actingweb/handlers/callbacks.py:211` (`_resync_fetch_failed`, no
`auto_storage` check); `actingweb/callback_processor.py:873`;
`actingweb/handlers/callbacks.py` `if result == ProcessResult.REBUILD:`
(no hook call)
**Recommendation:** Count a registered legacy `subscription` hook in the
callback gate (the handler has `self.hooks`). Telling the hooks inside the
REBUILD branch instead is not safe as it stands: with a replica that
answer usually follows a list diff whose handler already told the hooks,
and the poll deliberately does not tell twice.

### 2. "Told when it is sent again" is not what happens after an unsettled rebuild
**Severity:** Low (the hook is told, later: the rebuild stays owed and the
next poll or callback after the interval runs it and tells; the same holds
with a replica)
**Description:** An unsettled rebuild still records the publisher's
sequence and clears its diffs, so the callback sent again is a duplicate
(204), told nothing. The docs promise it is told then.
**Location:** `docs/reference/hooks-reference.rst` "A rebuild that does not
settle tells no hook; the callback answers 503 and is told when it is sent
again."; `actingweb/interface/subscription_manager.py`
`rebuild_subscription` (`sub_obj.handle.modify(seqnr=sequence)` and
`proxy.change_resource(...)` regardless of `settled`)
**Recommendation:** Correct the sentence: the owed rebuild tells it on the
next poll or callback after the interval.

### 3. The interval can run out between the callback's check and the processor's claim
**Severity:** Low (a millisecond window, or a folded read fault in the
check)
**Description:** The callback's owed-rebuild check answers not due; the
processor, claiming a moment later, finds it due and answers REBUILD,
whose branch tells nothing. The poll has the same boundary between its
owed check and a list diff's rebuild.
**Location:** `actingweb/handlers/callbacks.py` the gate on `rebuilds_for`
and `_rebuild_owed_and_due`; `actingweb/callback_processor.py:873`
**Recommendation:** Accept (the next owed rebuild does not exist once this
one settled, so the hook misses one baseline, rarely), or make the REBUILD
answer for an owed rebuild (not an out-of-step diff) carry a flag that the
branch tells on.

### 4. A hooks-only actor that deletes a covering subscription now gets a "resync"
**Severity:** Low (owner-initiated)
**Description:** Deleting a whole-target subscription owes the covered
ones a rebuild without checking `auto_storage`; with a data hook, the next
diff on a covered subscription now runs that rebuild and is told as a
`"resync"` baseline instead of a diff. Before entry 16 the rebuild ran
untold after the diff was told.
**Location:** `actingweb/actor.py:3965-3966` `if result and covered and
peerid: self._owe_covered_rebuilds(peerid, covered)`
**Recommendation:** Owe covered rebuilds only with `auto_storage` (there
is no replica to rebuild otherwise).

### 5. Smaller points
**Severity:** Low
**Description:**
- A store fault on the callback path's owed rebuild now raises `DbError`
  for a hooks-only subscriber; entry 19 states it for the poll only.
- `_rebuild_owed_and_due` without `target` looks the subscription up, and
  the poll looks it up again: two blocking reads on the async poll's loop.
**Location:** `actingweb/handlers/callbacks.py` `rebuilt =
mgr.rebuild_subscription(...)`; `actingweb/interface/subscription_manager.py`
`_rebuild_owed_and_due` `sub = self.get_callback_subscription(...)`
**Recommendation:** A sentence in the hooks reference; pass the target
from the poll.

### 6. Tests that do not pin entries 16 to 18 fully
**Severity:** Low
**Description:** The callback test patches `_rebuild_owed_and_due`, so the
`target=` plumbing and a hook on another target on the callback path are
untested; entries 17 and 18 are tested on the synchronous poll only; the
once-a-minute hooks-only case passes with entry 16 reverted.
**Location:** `tests/test_subscriber_receiver_1_5.py:311-313`;
`tests/test_replica_rebuild.py`
**Recommendation:** A callback-path case without the patch; the async
twins.

Disputed and not recorded: codex's "the REBUILD branch answers 204 when
the rebuild fails" (that callback's own diff was applied, told and
recorded; a 503 would only bring back a duplicate).

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

The fourth iteration closed re-run 3's Medium for what it was: a
subscriber with a data hook now has every owed rebuild run by a path that
tells it. The Full tier is green on both backends, and the consumer's suite shows
its baseline's six failures and nothing else.

One Medium remains open by the stop rule, but it is not this branch's: a
subscriber with only the legacy `subscription` hook and no replica has
owed a rebuild that runs untold since specification 1.5 shipped on
master. Fixing it is one more condition in the callback gate. The Lows are
a docs sentence that promises too much, a narrow window, a hooks-only edge
on deleting a covering subscription, and test coverage. Whether to close
Issue 1 here or record it with the subscriber fault-hardening todo is the
owner's decision.
