# Verification: the fixes 3.16 takes before its release validation (re-run 9)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** e6a8976 (plus one uncommitted line in
`thoughts/todo/emm-suite-against-master.md`)

The closing run: entries 42 to 45, and a site-by-site check of the
owed-rebuild rule (the audit's owing sites A1 to A8 and running sites B1
to B8) on the final code, as the owner asked instead of a second audit.

## Automated Check Results

- The Full tier ran on the tree committed as `e6a8976`: `ruff check`,
  `ruff format --check` (599 files), `pyright` (0 errors),
  `verify_groups.py`; **DynamoDB** 8,071 passed, 212 skipped, 2 xfailed,
  no error; **PostgreSQL** 7,843 passed, 440 skipped, 2 xfailed;
  `sphinx-build -W` clean; no wire recording changed.
- **The consumer's suite** on `e6a8976` (the library worktree checked out
  at the commit; the preview server up for the PostgreSQL lane, stopped
  after): PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected;
  DynamoDB lane 3 failed, 54 passed. The baseline's six by name.
- **Unreleased security records:** the merge base is `origin/master`
  (`e928e5b`); the named records are unchanged; no text added since
  `1a68f1d` describes a hole. None.
- **Second opinion:** codex (`codex exec -s read-only`) and a
  fresh-context reviewer, against the rule site by site. All sixteen
  sites FOLLOW; rule 6 (the configuration) follows at every entry. No
  Medium or High. Twelve Low (below). Rejected with reasons: codex's
  "a failed callback-path rebuild answers 204" (rule 5 as decided, pinned
  by `test_an_unsettled_rebuild_answer_keeps_the_callback_and_the_debt`),
  "the `force` removal is incomplete" (only `_run_rebuild_answer`'s was
  removed; `begin_rebuild` and `rebuild_subscription` keep theirs), "the
  sequence-write fault answers 204" (predates the branch; the documented
  at-most-once fold), "a public rebuild runs with no work" (a direct API
  call; documented to tell no hook).
- **Leftovers of entries 34, 35, 43:** no live `applied_through`,
  `_owe_rebuild` or `_run_rebuild_answer(force=...)`; no test asserts the
  removed behaviour.
- **Security review, browser QA:** not re-run (the whole-branch security
  review is re-run 3's; the pages were walked in re-run 2).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-6.md
**Iterations since:** entries 42 to 45

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Entry 41's test change missing (record) | Fixed, and seen failing with the drop removed | entry 42 |
| 2. A poll can settle the legacy hook's debt (Medium) | Resolved by decision: polls reach data hooks only, stated; no debt, no forced rebuild | entry 45; `test_the_gap_resync_runs_no_rebuild_for_the_legacy_hook` |
| 3. The lingering debt's side effects (Low) | Gone with the debt | entries 43, 45 |
| 4. The lost-owe warning's wording (Low) | Gone with `_owe_rebuild`; the silence it covered is Issue 4 below | entry 43 |
| 5. The 204 for an unsettled REBUILD unpinned (Low) | Fixed | `test_an_unsettled_rebuild_answer_keeps_the_callback_and_the_debt` |
| 6. The guide's behind-poll sentence (Low) | Fixed | entry 44 |
| 7. A `"*"` callback hook untested (Low) | Fixed | the gap-resync test's `"*"` shape |

## Remaining Tasks

- [ ] The Low findings below, at the owner's choice (the stop rule
  accepts them without code); the comment and doc ones are a short edit.

## Issues Found

All Low.

1. **`_run_rebuild_answer` returns a value nobody reads** (`actingweb/handlers/callbacks.py:225`), left from entry 35. Return `None`.
2. **Its docstring's reason is not literal** (`callbacks.py:226-227` "the processor claims one callback at a time"): the in-order path claims the delivered callback with the queued ones after it; the delivered one heads its batch, so its change is applied, and queued ones behind a stop are carried by the rebuild. Reword.
3. **A stale comment** (`actingweb/interface/subscription_manager.py:1665-1667`, `2696-2698` "left owed for the next callback, whose legacy hook does"): with no legacy hook the next callback drops the debt. Reword.
4. **Debt writes that lose every compare-and-swap are silent** (`callbacks.py:284`, `subscription_manager.py:2934`, `actor.py:4008`, `actingweb/maintenance/verify_property_lists.py:622-628`, which counts the mark anyway). Not peer-reachable. Log on False; count only landed marks.
5. **A rebuild whose final settle loses reports success** (`subscription_manager.py:3141` logs, `:3152` `success=settled`): the debt stays and the baseline is told again after the interval, which the rule allows. Accept.
6. **A publisher can make every poll a forced rebuild** (`subscription_manager.py:1451` `force=not self._rebuild_owed(...)`): answering each poll with no diffs and a sequence one higher makes each poll fetch a baseline and tell the data hooks. Peer-reachable cost only (the subscriber polls on its own schedule). Rate-limit behind rebuilds separately, or accept.
7. **The gate's 503 when another delivery won the reservation** (`callbacks.py:1189-1212`): the loser's change is in the winner's baseline, so nothing is lost, but it answers 503 although a rebuild settled. Fall through to normal processing on a lost reservation, or accept.
8. **"As before" is false** (`docs/migration/v3.16.rst:2372`): the callback path's rebuild told no hook before 3.16. Drop it.
9. **The all-duplicates poll is a refresh, not a rebuild** (`hooks-reference.rst:233`, `v3.16.rst:2366`, `CHANGELOG.rst:1381`): it needs `auto_storage` and reserves nothing. Say so.
10. **"Wherever it runs" is too broad** (`CHANGELOG.rst:1376-1377`, `v3.16.rst:2361`): the public `rebuild_subscription()` tells no hook. "Wherever the library runs it".
11. **"The legacy hook hears callbacks" claims too much** (`hooks-reference.rst:250-251`): callbacks queued and answered 204 that a gap resync then clears reach data hooks only (its poll). "Hears the callbacks it processes".
12. **The changelog's "told by the rebuild the next callback or poll runs"** (`CHANGELOG.rst:1043-1045`) reads as if a poll tells the legacy hook. "Told to the hooks that path reaches".

Unverified (recorded, not a finding): markers are assumed to reach only
subscribers that get no callbacks (`actor.py:5009-5011`); a trust that
gains an endpoint after a marker was stored, or another publisher, would
break that, and a subscriber with no replica and no data hook would then
not hear the marker.

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

The plan is complete and verified: the receiver keeps every callback, a
resume always sends a resync, `notify_subscribers(resource=)` sends the
whole value, the trust pages show both sides, `CallbackOauthHandler` is
gone, and the owed-rebuild rule the audit wrote holds at every site the
audit mapped. The Full tier and the consumer's suite are green, and the
branch carries no unreleased security record.

By the owner's stop rule the record is clean: no peer-reachable Medium or
higher is open. Twelve Low remain: four comment or return-value leftovers
of the last iterations, five doc sentences that overclaim, and three
behaviours to accept or tighten later (a lost compare-and-swap that is
silent, a settle that loses, a publisher that can force a rebuild per
poll). The comment and doc items are a short edit before the PR if the
owner wants the docs exact; none blocks it.
