# Verification: the fixes 3.16 takes before its release validation (re-run 3)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 8bb63cf plus the uncommitted third iteration (iterations log
entries 11 to 15)

A re-run, scaled to the third iteration: the behind poll's rebuild (the
covered baseline, the interval, subscribers without `auto_storage`), the
trust form's typed URL, and a publisher sequence that is not an integer.
At the owner's request it also carries a security review of the whole
branch against master, which the earlier runs had not run as a separate
provider.

## Automated Check Results

The Full tier ran on the working tree (8bb63cf plus the iteration).

- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass, 599 files.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass (43 groups, wire registry,
  Wire-Phase trailers).
- `make test-all-parallel`, **DynamoDB**: pass, 8,030 passed, 212 skipped,
  2 xfailed.
- `make test-all-parallel`, **PostgreSQL**: pass, 7,802 passed, 440
  skipped, 2 xfailed.
- `sphinx-build -W --keep-going`: pass.
- **Security review** (the built-in `/security-review`, on `git diff
  e928e5b`, the whole branch with the iteration): no finding at confidence
  8 or above. Checked: grant filtering of whole-value sends, `list:` keys
  beneath a subtarget, the resync on resume (the removed full-state
  fallback was the only path that pushed data), the drained queue (keyed
  by peer and subscription, filled after authentication), the web form's
  re-pair (the secret goes to the stored base URI; owner-authenticated;
  possible before the branch), the form's redirects and notices (fixed
  paths and fixed tables; exception text no longer rendered), the
  templates (no new `|safe` or `Markup`; autoescaped), the OAuth2 default
  and the removed `CallbackOauthHandler` (which built a redirect from
  unencoded request values). One residual noted at confidence 2: a value
  shaped like a list diff stored under a `list:` key inside an ordinary
  property skips exclusions deeper than the key; it predates the branch,
  which narrows it.
- **Second opinion:** codex (`codex review --uncommitted`, a plain review:
  the adversarial brief's run exited 2 and was lost) found nothing
  actionable; a fresh-context reviewer with the brief found one Medium and
  four Low (Issues 1 to 5). It confirmed that five of the seven new tests
  fail with their behaviour removed.
- **The consumer's suite:** not run on this tree (the iteration is
  uncommitted, and Issue 1 changes it again).
- **Browser QA:** not re-run. The iteration's only change a user sees is
  whitespace stripped from the trust form's URL, which
  `test_whitespace_around_a_typed_url_still_names_the_stored_peer` drives
  through both integrations.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-16-3-16-pre-validation-fixes-3.md
**Iterations since:** entries 11 to 15 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A covered subtarget's behind poll is told a baseline it did not store (Low) | Fixed | `SubscriptionSyncResult.baseline_skipped`, `_tell_polled_baseline`; the callback path still gets the baseline. `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_behind_poll_of_a_covered_subscription_tells_no_hook` |
| 2. A forced rebuild that fails is retried every poll (Low) | Fixed for `auto_storage`; for a hooks-only subscriber the owed state it leaves is new and mishandled (Issue 1) | `force=not self._rebuild_owed(...)`; `::test_a_failing_behind_rebuild_is_attempted_once_a_minute`, `::test_an_interval_another_path_started_does_not_hold_the_behind_poll` |
| 3. The behind fix holds only with `auto_storage` (Low) | Fixed when a data hook is registered, with a new Medium (Issue 1) and a gate wider than the target (Issue 2) | `subscription_manager.py:1400`; `::test_a_behind_poll_without_auto_storage_tells_the_hook` |
| 4. Whitespace around a typed URL no longer matches (Low) | Fixed | `actingweb/handlers/www.py:1080`; `tests/test_www_trust_pages.py::test_whitespace_around_a_typed_url_still_names_the_stored_peer` |
| (re-run 1, Issue 6) A text or `null` sequence raised later | Fixed, with one path that now tells repeatedly (Issue 3) | `_publisher_sequence`; `::test_a_publisher_sequence_that_is_no_integer_is_not_behind` |

## Acceptance Criteria

Only AC-8 changed (annotation of 2026-11-17).

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-8 | `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks`: the covered, interval, once-a-minute and hooks-only cases, with the earlier ones | Yes with `auto_storage`; for hooks-only, the first behind poll only: a failed attempt and its retry are not exercised (Issue 5) | Pass |

## Remaining Tasks

- [ ] Issue 1 (Medium) before the PR, by the stop rule.
- [ ] Issues 2 to 5 (Low), at the owner's choice.
- [ ] The consumer's suite on the commit that carries the iteration.

## Issues Found

### 1. A hooks-only subscriber's failed behind rebuild is later settled without telling the hook
**Severity:** Medium (peer-reachable: the publisher decides whether the
baseline fetch fails; new in entry 13)
**Description:** With `auto_storage` off, the behind poll's rebuild now
reserves the attempt, which marks the rebuild owed, and a failure or an
unsettled rebuild leaves it owed. Nothing that tells a hook runs it: the
poll's owed-and-due check and the callback path's owed-rebuild branch are
both gated on `auto_storage`. The state machine is not: the next callback
after the interval is answered `REBUILD`, and that branch runs the rebuild,
records the publisher's sequence, clears its diffs and settles, logging
only. Every later poll is level, so the gap entry 13 meant to tell is lost
without a trace. Before entry 13 a hooks-only subscriber never owed a
rebuild.
**Location:** `actingweb/callback_processor.py:873` `elif
claimed_row.get("rebuild_owed") and self._rebuild_due(claimed_row):`;
`actingweb/handlers/callbacks.py:1481-1497` (the `REBUILD` branch, no
hook); `actingweb/handlers/callbacks.py:1090` `if callback_type !=
"resync" and config.auto_storage:`; `actingweb/interface/subscription_manager.py`
`_rebuild_owed_and_due` `if not config.auto_storage: return False`
**Recommendation:** Apply the same condition as the poll's new gate
(`auto_storage` or a data hook for the target) to `_rebuild_owed_and_due`
and the callback gate at `:1090`, so the owed rebuild runs where it is
told; or have the `REBUILD` branch tell the hooks the settled baseline. A
hooks-only test: fail once, then a callback after the interval.

### 2. The hook condition counts a hook on any target
**Severity:** Low
**Description:** `bool(config.subscription_data_hooks)` is true for a hook
on another target. A subscription to a target with no hook (and no `"*"`
hook) then runs a full rebuild that tells nobody, and if its baseline
cannot be read (a target the peer lets it subscribe to but not read), each
poll fails (502, then 429) and the sequence is never recorded, where it
was one successful request before.
**Location:** `actingweb/interface/subscription_manager.py:1400` `and
(config.auto_storage or bool(config.subscription_data_hooks))`; compare
`actingweb/handlers/callbacks.py:121-122` `for name in (target, "*"):`
**Recommendation:** Gate on `sub.target` or `"*"` having a hook.

### 3. With duplicate diffs and a sequence that is not an integer, every poll tells the hooks
**Severity:** Low (a broken or hostile publisher)
**Description:** The duplicate-diffs path records and clears nothing when
the sequence reads as 0, but still returns the baseline, so each poll
refetches it and tells the hooks with sequence 0 and `"resync"`. Before the
iteration it raised before telling.
**Location:** `actingweb/interface/subscription_manager.py:1746-1747`
`final_seq = _publisher_sequence(response)` / `if final_seq > 0:`, with
the `baseline=` at `:1787-1791`
**Recommendation:** Return no baseline (or a failed result) on that path
when the sequence is not an integer.

### 4. A store fault on a hooks-only subscriber's behind poll escapes as `DbError`
**Severity:** Low
**Description:** `_rebuild_owed` folds a read fault into "owed", but the
rebuild's `begin_rebuild` and `settle_rebuild` raise on the same fault.
For a hooks-only subscriber that state table was not touched before.
**Location:** `actingweb/interface/subscription_manager.py` `_rebuild_owed`
`return True  # ... not forced`; `actingweb/callback_processor.py:507`
**Recommendation:** Accept and say so in the docstring (the
`auto_storage` path raises the same way), or answer a 503 result.

### 5. Two new tests do not pin what they describe
**Severity:** Low
**Description:** The once-a-minute test runs with `auto_storage`, so its
third poll is taken by the owed-and-due branch, not the behind path; the
hooks-only retry (where Issue 1 lives) is untested.
`test_a_level_poll_without_auto_storage_tells_no_hook` and
`test_a_skipped_rebuild_still_returns_its_baseline` pass without the
iteration (regression guards only).
**Location:** `tests/test_replica_rebuild.py`
`test_a_failing_behind_rebuild_is_attempted_once_a_minute`
**Recommendation:** Parametrize it over a hooks-only configuration with
Issue 1's fix.

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

The iteration closed re-run 2's four Low findings for subscribers with a
replica, and the Full tier is green on DynamoDB. The security review of the
whole branch found nothing at the reporting bar; the branch narrows what
leaves the publisher and removes a handler that built redirects from
request values.

Extending the behind rebuild to subscribers without `auto_storage`
(entry 13) opened a Medium: such a subscriber can now owe a rebuild that
only a hook-less path ever runs, so after one failed baseline fetch the
gap is closed silently. By the stop rule the record is not clean until
Issue 1 is fixed or accepted. The alternative to fixing it is to take
entry 13 back (hooks-only subscribers told nothing after a gap, as
before the branch, documented).
