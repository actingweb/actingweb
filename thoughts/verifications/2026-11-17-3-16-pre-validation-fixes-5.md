# Verification: the fixes 3.16 takes before its release validation (re-run 7)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 320925d (plus one uncommitted line in
`thoughts/todo/emm-suite-against-master.md`)

A re-run scaled to entries 33 to 37 (re-run 6's Issues 1 to 6), committed
in `320925d` with the re-recorded wire rows.

## Automated Check Results

- The Full tier ran on the tree committed as `320925d` (nothing in
  `actingweb/`, `tests/` or `docs/` changed after it): `ruff check`,
  `ruff format --check`, `pyright` (0 errors), `verify_groups.py` (the
  `Wire-Phase` trailers match WD7, WL13.target and WD11), **DynamoDB**
  8,069 passed, 212 skipped, 2 xfailed; **PostgreSQL** 7,841 passed, 440
  skipped, 2 xfailed; `sphinx-build -W` clean.
- **The consumer's suite** on `320925d` (the library worktree checked out
  at the commit; the preview server up for the PostgreSQL lane, stopped
  after): PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected;
  DynamoDB lane 3 failed, 54 passed. The baseline's six by name.
- **Second opinion:** codex (`codex exec -s read-only`, run outside the
  sandbox after it failed inside) and a fresh-context reviewer. One
  Medium, six Low recorded below. Not recorded: codex's two
  `applied_through` claims (a stale value across batches, the value set
  before a sequence write that faults): it gave no scenario with a wrong
  answer, and the fault case is the at-most-once 204 the code documents.
- **Security review, browser QA:** not re-run (subscriber bookkeeping and
  docs only).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-4.md
**Iterations since:** entries 33 to 37

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A poll without a configuration tells no hook (High) | Fixed | `sync_subscription` and its twin resolve once; `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_poll_without_a_configuration_tells_the_applications_hooks` |
| 2. A polled marker is lost for a legacy-only subscriber (Medium) | Fixed as written, but the debt is never collected (Issue 2 below) | entry 34 |
| 3. A callback dropped by a batch's rebuild answers 204 (Medium) | The case cannot occur (Issue 3 below); the fix answers 503 for a callback that is still queued | entry 35 |
| 4. The gap resync and a legacy-only subscriber (Medium) | Fixed for the legacy-only shape; open for a subscriber with a replica or data hook and a legacy hook (Issue 1) | entry 36 |
| 5. "Nothing is kept" (Low) | Reworded; now contradicted by entry 34's marker debt (Issue 2) | entry 37 |
| 6. Tests and the fault sentence (Low) | Partly: some new tests do not pin their fix (Issue 5) | entry 37 |

## Acceptance Criteria

No AC changed in entries 33 to 37; AC-8 stands as annotated.

## Remaining Tasks

- [ ] Issue 1 (Medium) before the PR, by the stop rule, or accepted.
- [ ] Issues 2 to 6 (Low), at the owner's choice.

## Issues Found

### 1. A gap resync tells the legacy hook nothing when the subscriber also has a replica or a data hook
**Severity:** Medium (peer-reachable: a skipped sequence and the gap
timeout). **Not a regression of a release**: the gap resync's poll told
the legacy hook nothing before the branch; the rule states the callback
path tells it, so the rule is not met here.
**Description:** Entry 36 owes a rebuild after the gap resync only when
`rebuilds_for` is false. With a replica or a data hook and a legacy hook,
the poll applies the retained diffs or rebuilds, tells the data hooks,
and owes nothing, so the legacy hook never hears the gap.
**Location:** `actingweb/handlers/callbacks.py` the gap resync's `if not
rebuilds_for(config, sub_target) and self._hears_a_rebuild(config,
sub_target):`; `actingweb/interface/subscription_manager.py`
`_tell_polled_baseline` "Not the legacy ``subscription`` callback hook,
which no poll path tells."
**Recommendation:** Either owe the rebuild after a gap resync whenever a
legacy hook is registered (the next callback rebuilds and tells both;
one extra rebuild per gap timeout), or state the exception: on the gap
resync the legacy hook hears only the replayed callback.

### 2. A polled marker's debt is never collected
**Severity:** Low
**Description:** Markers are stored only for subscribers without a
callback endpoint or with granularity `none`, which never receive a
callback, so the rebuild entry 34 owes is never run or dropped. It is
inert (no poll runs it for that shape) but contradicts "owed only when it
has work", and every poll that sees the marker writes the state row.
**Location:** `actingweb/actor.py:5007-5009` (markers only for
`not _has_peer_endpoint(...) or granularity == "none"`);
`actingweb/interface/subscription_manager.py` the four `if
diff.get("type") == "resync":` owing sites
**Recommendation:** Revert entry 34 and state that a subscriber with no
replica and no data hook hears nothing from a polled marker (a poll
never tells the legacy hook).

### 3. Entry 35's 503 covers a case that cannot occur
**Severity:** Low
**Description:** The processor claims one callback per claim and prunes
only that one, so a delivered callback's change is never dropped by a
batch's rebuild. `sequence > applied_through` happens only when the
delivered callback was queued and the drain stopped below it; the
callback is still queued and runs when the gap fills, so the 503 is
harmless but its comment ("dropped its change") and the docs are wrong.
**Location:** `actingweb/handlers/callbacks.py` the REBUILD branch's 503;
`actingweb/callback_processor.py:747` "One callback per claim"
**Recommendation:** Revert entry 35 (and `applied_through`), and the
docs' sentence.

### 4. Docs: "so it is sent again", and "for the next callback"
**Severity:** Low
**Description:** This library's publisher does not resend a diff callback
on 503; the change returns through a poll or a gap resync. The gap
resync's debt is often run by its own replay, not the next callback.
**Location:** `docs/reference/hooks-reference.rst` "answers 503 ..., so
it is sent again"; `CHANGELOG.rst` the same; `actingweb/callback_processor.py:909-911`
"the publisher, which does not retry"
**Recommendation:** Reword both.

### 5. Tests that do not pin their fix
**Severity:** Low
**Description:** The drop-the-debt test never owes first; the entry-35
test sets `applied_through` through the mock; the marker test has no
hook; the gap-resync test never reaches the replay nor checks the legacy
hook on the next callback; the no-sequence marker sites are untested.
**Location:** `tests/test_subscriber_receiver_1_5.py` `_rebuild_answered`
and its tests; `tests/test_replica_rebuild.py`
`test_a_polled_marker_owes_a_rebuild_a_poll_cannot_tell`
**Recommendation:** Owe first in the drop test; the rest follow the
choices on Issues 1 to 3.

### 6. `_owe_rebuild` ignores a lost compare-and-swap
**Severity:** Low
**Description:** `settle_rebuild` answers False after its retries without
a log; the gap resync owes exactly when deliveries contend for the row.
**Location:** `actingweb/interface/subscription_manager.py` `_owe_rebuild`
**Recommendation:** Log a warning on False.

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

Re-run 6's High is fixed: a poll without a configuration now tells the
application's hooks, the call shape a consumer uses. The Full tier and
the consumer's suite are green on the committed tree.

Two of the last iteration's fixes went further than the code needed:
entry 35 answers for a case the one-callback-per-claim processor never
produces, and entry 34 owes a debt for subscribers that never get a
callback. Reverting both makes the code smaller and the docs truer. One
Medium remains by the stop rule, on the gap resync for a subscriber with
both a replica (or data hook) and a legacy hook, which predates the
branch. It is the owner's call to close it (owe after every gap resync
when a legacy hook exists) or to state it as the exception.
