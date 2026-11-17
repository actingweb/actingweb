# Verification: the fixes 3.16 takes before its release validation (re-run 6)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 8bb63cf plus the uncommitted third to sixth iterations
(iterations log entries 11 to 32)

A re-run after the audit of the owed-rebuild rules and the owner's rule
(iterations log, "The audit (2026-11-17)", entries 27 to 32). The review
was briefed to check every owing and running site of the audit's map
against the rule, not only the diff.

## Automated Check Results

- `ruff check`, `ruff format --check`, `pyright actingweb tests`
  (0 errors), `verify_groups.py`: pass.
- `make test-all-parallel`, **DynamoDB**: **4 failed**, 8,056 passed, 212
  skipped, 2 xfailed. **PostgreSQL**: **4 failed**, 7,828 passed, 440
  skipped, 2 xfailed. The same four on both: the wire rows WD7 and
  WL13.target, both topologies. Both differences are the rule's intended
  effect, not regressions (read from the `.actual.json` diffs):
  - **WD7** (`sync_peer(a.id)` without a configuration): the poll now uses
    the application's configuration (entry 30), so the wire app's data
    hook hears the polled diff, one added `subscription_data` event
    (`"diff"`, sequence 1).
  - **WL13.target** (a callback's spanned list diff the replica cannot
    apply): the settled rebuild now tells its baseline (entry 28), one
    added `subscription_data` event (`"resync"`, sequence 2).
  Both rows are owned by `spec-1-5` and earlier plans; gate 5 requires an
  ownership commit to this plan before they are re-recorded with its
  `Wire-Phase` trailer. Not done: no commit was asked for.
- `sphinx-build -W --keep-going`: pass.
- **The consumer's suite** (environment 9, the library worktree at
  `8bb63cf` with this tree's `actingweb/` diff applied, identical by
  `diff`; preview server up for the PostgreSQL lane, stopped after):
  PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected; DynamoDB
  lane 3 failed, 54 passed. The baseline's six by name, nothing new (logs
  `../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-iter6.log`).
- **Second opinion:** codex (`codex exec -s read-only`; a first run hung
  on standard input and was re-run) and a fresh-context reviewer, against
  the audit's sites A1 to A8 and B1 to B8. One High, three Medium, two Low
  (Issues below). Sites following the rule: A1, A2, A3, A7, B1, B5, B6;
  A4 in practice. Checked without finding: the legacy-only conversion to
  PROCESSED clears only diffs it applied and does not loop; the gap
  replay cannot rebuild twice (the unforced reservation's interval); no
  poll reads `enabled`, and `ActingWebApp` always attaches a
  configuration, so `_processing_config` changes nothing for an
  application that never called `with_subscription_processing()`.
- **Security review, browser QA:** not re-run (nothing reaches a peer or a
  page differently beyond the issues below).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-3.md
**Iterations since:** entries 27 to 32

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The guide's permissions table omits the properties table (Medium) | Fixed | entry 27 |
| 2. A poll consumes a rebuild only the legacy hook hears (Medium) | Fixed for owed rebuilds; a polled marker for that shape is still lost (Issue 2) | entry 29; `test_a_poll_leaves_a_rebuild_only_the_legacy_hook_hears_owed` |
| 3. The poll's check-to-claim window (Low) | Fixed (a settled rebuild always tells) | entry 28 |
| 4. The callback paths tell a covered baseline (Low) | Fixed (never told) | entry 28; the gate's test only (Issue 6) |
| 5. A missing configuration means two things (Low) | Fixed where a rebuild runs; not where its baseline is told (Issue 1) | entry 30 |
| 6. "Keeps no rebuild state" (Low) | Fixed for a failed resync fetch; "nothing is kept" still overstates (Issue 5) | entry 29 |
| 7. "In place of that callback's diff" (Low) | Fixed ("or right after it") | entry 32 |
| 8. A `"*"` callback hook counts (Low) | Fixed (stated) | entries 29, 32 |

## Remaining Tasks

- [ ] Issue 1 (High) and Issues 2 to 4 (Medium).
- [ ] WD7 and WL13.target: ownership commit, then re-record with the
  plan's `Wire-Phase` trailer (gate 5).
- [ ] Commit entries 11 onward with the verifications.

## Issues Found

### 1. A poll without a configuration tells no hook the baseline it settled
**Severity:** High (peer-reachable: a failed resync fetch owes the
rebuild; a consumer polls this way: `sync_peer_async(peer_id)`)
**Description:** `sync_subscription` and its async twin pass the caller's
raw `config` to `_tell_polled_baseline`, while `_poll_subscription`
resolves it through `_processing_config`. With `config=None` the per-diff
hooks run with the application's configuration, but the rebuild's
baseline is handed to `run_subscription_data_hooks(None, ...)`, which
finds no hooks and returns. The owed rebuild is settled and its change
is never told, without a log. Entry 30 made the poll use the
application's configuration and left this call on the raw value; before
entry 30 a configuration-less poll told no baseline either (the defaults
have no hooks), so this is a defect of the rule's implementation, not a
regression of a release.
**Location:** `actingweb/interface/subscription_manager.py:1337-1338`
`result = self._poll_subscription(peer_id, subscription_id, config)` /
`self._tell_polled_baseline(peer_id, config, result)`; async twin
`:2380-2383`; `actingweb/handlers/callbacks.py:115-117`
**Recommendation:** Resolve the configuration once in `sync_subscription`
and its twin and pass the resolved one to both calls; assert the hook in
`test_a_poll_uses_the_applications_configuration_when_given_none`.

### 2. A polled resync marker is lost for a legacy-hook-only subscriber
**Severity:** Medium (peer-reachable)
**Description:** With no replica and no data hook, `rebuilds_for` is
false, so the marker is processed as an empty diff, recorded and cleared
on the publisher; nothing is owed, and the legacy hook never hears the
state the marker asked for. Entry 29 fixed this for data hooks only.
**Location:** `actingweb/interface/subscription_manager.py:1637`, `:1683`,
`:2666`, `:2711` `if diff.get("type") == "resync" and rebuilds_for(config,
sub.target):`
**Recommendation:** For that shape, owe the rebuild and stop before the
marker (the next callback runs and tells it); a legacy-only marker test.

### 3. A callback dropped by a drained batch's rebuild answers 204 when the rebuild fails
**Severity:** Medium (peer-reachable; with `auto_storage`)
**Description:** `_run_rebuild_answer` assumes the callback's own change
was applied. On the drain path a batch [1, 2, 3] that stops at an
out-of-step 2 prunes 3, the delivered callback, without applying it; if
the rebuild then fails, 3 answers 204 and waits for a later rebuild
instead of a 503 retry.
**Location:** `actingweb/handlers/callbacks.py` `_run_rebuild_answer`
docstring "The callback's own change was applied, so a rebuild that fails
only stays owed: the callback still answers 204."; `actingweb/callback_processor.py`
`_finish_batch` "a batch stopped for a rebuild drops the rest"
**Recommendation:** Have the processor say whether the delivered sequence
was applied; answer 503 when it was not and the rebuild did not settle.

### 4. The gap resync tells data hooks only, and a legacy-only subscriber owes nothing
**Severity:** Medium (peer-reachable; the audit's claim 8, still open)
**Description:** The gap resync runs a poll on the callback path; the
poll's diffs and baseline reach data hooks only, and for a legacy-only
subscriber the behind path is skipped (`rebuilds_for` false), so the
publisher's sequence is recorded and nothing is owed. The rule says the
callback path tells the legacy hook; the docs' "hears it on the callback
path, as before" hides the exception.
**Location:** `actingweb/handlers/callbacks.py` `sync_result =
mgr.sync_subscription(peer_id, subscription_id, config=config)`;
`actingweb/interface/subscription_manager.py` the behind check `and
rebuilds_for(config, sub.target)`
**Recommendation:** On the gap path, owe the rebuild when only the legacy
hook hears it, so the next callback tells it; or state the exception.

### 5. "Otherwise nothing is kept" overstates
**Severity:** Low
**Description:** A debt with no listener (a direct
`rebuild_subscription()`, or the maintenance tool's marking, which reads
no configuration) is kept by a poll and dropped only by a callback.
**Location:** `docs/reference/hooks-reference.rst` "Only then is one owed
or run; otherwise nothing is kept."; `actingweb/maintenance/verify_property_lists.py:589-630`
**Recommendation:** Drop such a debt in the poll as on the callback path,
or soften the sentence.

### 6. Rule cells without a test, and a fault after an applied change
**Severity:** Low
**Description:**
- No test for `_run_rebuild_answer`'s covered branch (the covered test
  goes through the gate), its drop-the-debt branch, the gap replay's
  REBUILD, a legacy-only or `"*"`-hook shape in the failed-fetch test, a
  legacy-only marker, the baseline told with `config=None`, or 204 after
  the callback's own diff when the rebuild fails.
- A `DbError` in `_run_rebuild_answer` after the callback's change was
  applied answers 503, not the 204 rule 5 states; the hooks reference
  mentions the fault, the changelog's rule sentence does not.
**Location:** `tests/test_subscriber_receiver_1_5.py`;
`actingweb/handlers/callbacks.py` `_run_rebuild_answer` `except DbError:
raise`
**Recommendation:** The missing tests with Issues 1 to 4; one sentence in
the changelog.

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

The rule holds at most of the audit's sites, the consumer's suite is at
its baseline, and the two wire rows that changed changed as the rule
says they should. The record is not clean: the configuration resolution
of entry 30 stops short of the baseline teller, so the call shape a
consumer uses (`sync_peer_async(peer_id)`) settles a rebuild and tells no
hook (High). Three Medium follow the legacy-hook-only shape and the drain
path. All four are small, local fixes in code this branch already
touched; with the wire rows' ownership commit, one more iteration closes
them.
