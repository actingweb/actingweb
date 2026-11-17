# Verification: the fixes 3.16 takes before its release validation (re-run 8)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 1a68f1d (plus one uncommitted line in
`thoughts/todo/emm-suite-against-master.md`)

A re-run scaled to entries 38 to 41 (`320925d..1a68f1d`).

## Automated Check Results

- The Full tier ran on this tree before the commit: `ruff check`,
  `pyright` (0 errors), `verify_groups.py`, **DynamoDB** 8,070 passed,
  212 skipped, 2 xfailed; **PostgreSQL** 7,842 passed, 440 skipped, 2
  xfailed; `sphinx-build -W` clean. `ruff format --check` flagged one file
  in that run; the formatter then rewrapped one condition in
  `_owe_rebuild` (no behaviour change) and the four subscription test
  modules were re-run green (232 passed); the format check passes on the
  commit.
- **The consumer's suite** on `1a68f1d` (the library worktree checked out
  at the commit; the preview server up for the PostgreSQL lane, stopped
  after): PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected;
  DynamoDB lane 3 failed, 54 passed. The baseline's six by name.
- **Unreleased security records:** checked again for `320925d..1a68f1d`:
  the merge base is `origin/master` (`e928e5b`), the named records are not
  changed, and no added text describes a hole. None.
- **Second opinion:** codex (`codex exec -s read-only`) and a
  fresh-context reviewer. One finding about the record (High for its
  integrity, no runtime effect), one Medium, six Low. The reverts of
  entries 34 and 35 are complete (no `applied_through` left; no sentence
  claims a 503 for a dropped callback or a marker's debt); `legacy_hook`
  is in scope and correct at the gap resync.
- **Security review, browser QA:** not re-run.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-5.md
**Iterations since:** entries 38 to 41

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A gap resync tells the legacy hook nothing with a replica or data hook (Medium) | Moved, not closed: the debt it now owes can be run by a poll, which tells data hooks only (Issue 2) | entry 40 |
| 2. A polled marker's debt is never collected (Low) | Fixed (entry 34 reverted) | entry 39 |
| 3. Entry 35's 503 for an impossible case (Low) | Fixed (reverted); the 204 is not pinned by a test (Issue 5) | entry 38 |
| 4. Docs: "sent again", "the next callback" (Low) | "Sent again" fixed; "or the replayed callback" overstates (Issue 2) | entries 38, 40 |
| 5. Tests that do not pin their fix (Low) | Not fixed for the drop-the-debt test (Issue 1) | entry 41 |
| 6. `_owe_rebuild` ignores a lost CAS (Low) | Logged; the wording can be false (Issue 4) | entry 41 |

## Remaining Tasks

- [ ] Issue 1: make the test owe first, or correct entry 41.
- [ ] Issue 2 (Medium) by the stop rule, or accepted.
- [ ] Issues 3 to 7 (Low), at the owner's choice.

## Issues Found

### 1. Entry 41's test change is not in the commit
**Severity:** High for the record's integrity (the iterations log claims a
change that was not made); no runtime effect
**Description:** Entry 41 says the drop-the-debt test "marks the debt
before the callback, so it fails without the drop". The test passes no
`owe=True`: the script that made the edit replaced an argument an earlier
step of the same script had already removed, and its replacement matched
nothing without failing. With the drop deleted from
`_run_rebuild_answer`, the test still passes.
**Location:** `tests/test_subscriber_receiver_1_5.py:656-660`
`_rebuild_answered(_synced(True, 3, {}), auto_storage=False,
data_hook=False)`; iterations log entry 41
**Recommendation:** Pass `owe=True` and see it fail with the drop
removed; note the correction in the log.

### 2. A poll can run the rebuild entry 40 owes for the legacy hook
**Severity:** Medium (the gap is peer-triggered; the poll's timing is the
application's)
**Description:** With a replica or a data hook, the poll's owed check
runs any owed rebuild and tells data hooks only. The debt entry 40 owes
after a gap resync exists only for the legacy hook (the gap poll already
brought the replica and the data hooks up to date), so an application
poll that runs first settles it and the legacy hook never hears the gap:
the hole re-run 7 named is moved, not closed. The docs say "a later
callback (or the replayed callback) runs and tells every hook"; the
replay runs it only when it is in order and the debt is due, which is
not the usual case (the gap poll's own rebuild restarts the interval).
**Location:** `actingweb/interface/subscription_manager.py` the poll's
`if self._rebuild_owed_and_due(peer_id, subscription_id, config,
target=sub.target):`; `actingweb/handlers/callbacks.py` the gap resync's
`if legacy_hook:` and its comment; `docs/reference/hooks-reference.rst`,
`CHANGELOG.rst`, `docs/migration/v3.16.rst` (the same sentence)
**Recommendation:** Owe nothing: after a successful gap resync with a
legacy hook registered, run the rebuild there and tell its baseline to
every hook (one rebuild per gap resync, as entry 40 already costs); a
rebuild that fails stays owed as any other. Or record the debt as
legacy-only and have the poll leave it.

### 3. The debt lingers with side effects for shapes that had none
**Severity:** Low
**Description:** A replica-and-legacy subscriber whose gap poll rebuilt
holds a debt that is not due for a minute: inside it, a behind poll is
not forced and answers 429, and the all-duplicates path withholds its
baseline. With a publisher whose baseline GET fails, every gap resync
owes again. Issue 2's recommendation removes the debt and these with it.
**Location:** `actingweb/interface/subscription_manager.py`
`force=not self._rebuild_owed(...)`; `or self._rebuild_owed(peer_id,
subscription_id)`

### 4. The lost-owe warning can be false
**Severity:** Low
**Description:** `settle_rebuild` answering False means this caller lost
every CAS; a concurrent winner may have written the debt.
**Location:** `actingweb/interface/subscription_manager.py`
`_owe_rebuild` "lost every compare-and-swap; it is not owed"
**Recommendation:** "may not be owed".

### 5. Entry 38's 204 for an unsettled REBUILD is not pinned
**Severity:** Low
**Location:** `tests/test_subscriber_receiver_1_5.py` (no REBUILD test with
an unsettled rebuild)
**Recommendation:** A case with an unsettled rebuild asserting 204 and the
debt still owed.

### 6. The guide's "on a behind poll" includes the legacy hook
**Severity:** Low
**Description:** A legacy-only subscriber never rebuilds on a behind poll
(`rebuilds_for` is required).
**Location:** `docs/migration/v3.16.rst` "A subscriber without a replica
now rebuilds too when such a hook is registered: on a behind poll"
**Recommendation:** "(with a data hook)", as for the marker.

### 7. A `"*"` callback hook is untested as the legacy hook
**Severity:** Low
**Location:** `tests/test_subscriber_receiver_1_5.py`
`test_the_gap_resync_owes_a_rebuild_when_a_legacy_hook_hears` (only
`"subscription"` registered)
**Recommendation:** A `"*"` shape.

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

The reverts are clean and the code is smaller; the Full tier and the
consumer's suite are green; the branch carries no unreleased security
record. The record has an error of mine: entry 41 claims a test change
that is not in the commit.

The gap resync's legacy-hook case is still open: entry 40 owes a debt
that a poll can settle without telling that hook. Running the rebuild in
the gap resync itself, instead of owing it, closes it and removes the
lingering-debt side effects with it. That, the test, and the small doc
and test items are one more short iteration.
