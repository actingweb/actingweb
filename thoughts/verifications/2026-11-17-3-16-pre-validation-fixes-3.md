# Verification: the fixes 3.16 takes before its release validation (re-run 5)

**Date:** 2026-11-17
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 8bb63cf plus the uncommitted third to fifth iterations
(iterations log entries 11 to 26)

A re-run, scaled to the fifth iteration (entries 21 to 26: the legacy
hook in the callback gate, the processor's owed REBUILD told, covered
subscriptions owed only to a replica, the poll's target, tests), the
migration guide and changelog edits from the review of the consumer's
runs, and, at the owner's request, a check that the branch carries no
unreleased security records.

## Automated Check Results

The Full tier's test lanes ran on this tree's code after entry 26
(`actingweb/` and `tests/` have not changed since); the docs build ran
again after the guide and changelog edits.

- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass, 599 files.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass.
- `make test-all-parallel`, **DynamoDB**: pass, 8,046 passed, 212 skipped,
  2 xfailed.
- `make test-all-parallel`, **PostgreSQL**: pass, 7,818 passed, 440
  skipped, 2 xfailed.
- `sphinx-build -W --keep-going`: pass, no warning.
- **The consumer's suite** (environment 9; the library worktree at
  `8bb63cf` with this tree's `actingweb/` diff applied, identical by
  `diff`; the preview server up for the PostgreSQL lane, stopped after):
  PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected; DynamoDB
  lane 3 failed, 54 passed. The baseline's six failures by name, nothing
  new.
- **Second opinion:** codex (`codex exec -s read-only`) and a
  fresh-context reviewer on entries 21 to 26 and the docs edits: two
  Medium, six Low (Issues below). Confirmed clean: `rebuild_was_owed` is
  per request and set only on the owed branch; the gate and the processor
  never both tell one callback; there is one callback handler for both
  integrations.
- **Security review:** not re-run (re-run 3 covered the whole branch;
  entries 21 to 26 change whom a subscriber tells).
- **Browser QA:** not re-run; nothing a user sees changed.

## Unreleased security records

Owner rule (2026-11-07): records describing holes in the released library
stay local until the fix PR. Checked on 2026-11-17:

- The two named records, `thoughts/plans/2026-11-06-peer-authorisation-fixes.md`
  and `thoughts/research/2026-11-07-peer-authorisation-research-pass.md`,
  are on `origin/master` (merged with their fix, #171); this branch does
  not change them (`git diff --name-only origin/master` on both: empty).
- The branch's merge base is `origin/master` (`e928e5b`); `docs/3-16-rollup-records` and
  `spike/subscription-wire-harness` no longer exist locally and are not in
  `HEAD`. The only local branch not on `origin` is this one.
- The branch's own security-relevant text describes the `list:` key leak
  in the subscription delivery filter and its fix in the same branch.
  `filter_subscription_blob` does not exist in 3.15.1 (`git show
  v3.15.1:actingweb/actor.py`): the leak is in unreleased 3.16 code, so
  its description ships with its fix. One residual is recorded unfixed:
  a value shaped like a list diff stored under a `list:` key inside an
  ordinary property skips exclusions deeper than the key (security review
  confidence 2 of 10; `thoughts/verifications/2026-11-17-3-16-pre-validation-fixes.md`,
  iterations entry 1). 3.15.1 filtered top-level keys only and applied no
  exclusion beneath a subtarget's keys at all, so the residual is narrower
  than released behaviour and discloses nothing 3.15.1's code does not.

**Result: no unreleased security record on the branch.** The residual is
the owner's to judge if a stricter reading is wanted; it is in two
documents already committed on this branch (`3fb93ab`) and one uncommitted.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-2.md
**Iterations since:** entries 21 to 26 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A legacy-hook-only subscriber's owed rebuild runs untold (Medium) | Fixed on the callback path; a poll still consumes it untold (Issue 2) | `actingweb/handlers/callbacks.py` `legacy_hook`; `tests/test_subscriber_receiver_1_5.py::test_a_legacy_hook_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told` |
| 2. "Told when it is sent again" (Low) | Fixed | `docs/reference/hooks-reference.rst`, `CHANGELOG.rst` |
| 3. The window between the check and the claim (Low) | Fixed on the callback path; the poll's twin is open (Issue 3) | `CallbackProcessor.rebuild_was_owed`; `::test_an_owed_rebuild_the_processor_runs_tells_the_hooks` |
| 4. Deleting a covering subscription without a replica (Low) | Fixed, with a default that differs from the manager's (Issue 5) | `actingweb/actor.py`; `tests/test_replica_rebuild.py::TestVerification4Covered::test_without_a_replica_deleting_a_covering_subscription_owes_nothing` |
| 5. Callback fault unstated; two reads on the async poll (Low) | Fixed | `hooks-reference.rst`; the poll passes `target=` |
| 6. Tests (Low) | Fixed | `::test_the_callback_gate_asks_for_a_hook_on_the_subscriptions_target`; async twins |

## Acceptance Criteria

No AC changed in entries 21 to 26. AC-8 stands as in re-run 4.

## Remaining Tasks

- [ ] Issues 1 and 2 (Medium) before the PR, by the stop rule.
- [ ] Issues 3 to 8 (Low), at the owner's choice.
- [ ] Commit entries 11 to 26 with the verifications of re-runs 2 to 5.

## Issues Found

### 1. The guide's new DynamoDB permissions table omits `ConditionCheckItem` on the properties table
**Severity:** Medium (an operator who builds a policy from the table is
refused every claim of an indexed property's lookup row; not
peer-reachable; new in the docs edits)
**Description:** The table gives the actors table's `ConditionCheckItem`
only for the creator claim and has no properties row. With reverse lookup
on, an indexed write checks the actor and property rows in one
transaction whatever the uniqueness setting, as the configuration page
says.
**Location:** `docs/migration/v3.16.rst`, the "What 3.16 adds to a role
that lists actions" table; `actingweb/db/dynamodb/property.py:358-359`
(`t.condition_check(Actor, ...)`, `t.condition_check(Property, ...)`);
`actingweb/db/dynamodb/property_lookup.py:252-254`;
`docs/quickstart/configuration.rst:242`
**Recommendation:** Add a `<prefix>_properties` row (`ConditionCheckItem`,
with reverse lookup on) and give the actors row both reasons.

### 2. A poll still runs an owed rebuild without telling the legacy hook
**Severity:** Medium (peer-reachable: a resync URL that fails owes the
rebuild); the poll's half of re-run 4's Issue 1
**Description:** The poll's owed check passes no `told_elsewhere`, so for a
subscriber whose only hook is the legacy one it answers not owed; the
poll's processor then answers REBUILD for the owed rebuild, the poll runs
it and marks it told (`rebuild_told`), and drops the baseline. The owed
state is settled, so no later callback tells it. The guide says such a
rebuild is run by the next callback. The poll tells data hooks only by
design, so the legacy hook cannot hear it there.
**Location:** `actingweb/interface/subscription_manager.py` the poll's
REBUILD branch (`rebuild_told = True`, "The diff was told to the hooks;
the baseline is not.") and its async twin; `docs/migration/v3.16.rst`
subscriber section
**Recommendation:** Leave a rebuild owed from before for a callback when
the poll would tell nobody (no data hook), or say in the guide that a poll
can run it untold for the legacy hook. For data hooks, Issue 3's fix.

### 3. The poll's twin of the check-to-claim window drops an owed baseline
**Severity:** Low
**Description:** As re-run 4's Issue 3 on the poll: every REBUILD in the
poll is treated as following a told diff, including one owed from before.
**Location:** `actingweb/interface/subscription_manager.py` "The diff was
told to the hooks; the baseline is not."
**Recommendation:** `rebuild_told = not processor.rebuild_was_owed`.

### 4. The callback paths tell a baseline another subscription covers
**Severity:** Low
**Description:** Both callback paths tell `rebuilt.baseline` without
checking `baseline_skipped`; the poll does not tell it. Entry 11 kept the
callback's telling on purpose (the callback's change is in the baseline),
but the two paths now disagree.
**Location:** `actingweb/handlers/callbacks.py` `elif
processor.rebuild_was_owed:` and the gate's tell
**Recommendation:** Decide one rule and state it in the hooks reference.

### 5. A missing subscription configuration means "no replica" in one place and "a replica" in another
**Severity:** Low
**Description:** `actor.py` reads a missing `_subscription_config` as no
`auto_storage`; the manager's default configuration has `auto_storage`
on. A `Config` not built through `ActingWebApp` keeps a replica but is no
longer owed covered rebuilds.
**Location:** `actingweb/actor.py` `getattr(processing, "auto_storage",
False)`; `actingweb/subscription_config.py` `auto_storage: bool = True`
**Recommendation:** Default to `True` when there is no configuration.

### 6. "A subscriber with neither keeps no rebuild state" is not true
**Severity:** Low
**Description:** A failed resync fetch owes a rebuild with no hook or
storage check, and the processor runs it on the next callback (a
baseline GET and a clearing PUT for nobody).
**Location:** `docs/migration/v3.16.rst` subscriber section;
`actingweb/handlers/callbacks.py:211` (`_resync_fetch_failed`)
**Recommendation:** Owe it only when `rebuilds_for` or a legacy hook
holds, or drop the sentence.

### 7. In the window, a callback tells its diff and then the baseline
**Severity:** Low
**Description:** The docs say the baseline is told "in place of that
callback's diff"; in the window of entry 23 the diff was told first.
**Location:** `docs/migration/v3.16.rst` subscriber section
**Recommendation:** "in place of, or after,".

### 8. A `"*"` callback hook counts as the legacy hook
**Severity:** Low
**Description:** `has_callback_hook("subscription")` matches a `"*"`
callback hook, so an application with a catch-all callback hook runs owed
rebuilds without `auto_storage`, its hook gets `"resync"` baselines, and
every subscription callback reads the rebuild state. Consistent with
`execute_callback_hooks`, which runs `"*"` hooks for `"subscription"`,
but undocumented.
**Location:** `actingweb/handlers/callbacks.py` `legacy_hook = bool(...)`;
`actingweb/interface/hooks.py:561-568`
**Recommendation:** Say "or a `"*"` callback hook" in the hooks reference
and the changelog.

## Spec Merge

- Not merged, and `spec_merged:` is not written: the plan carries no
  mergeable Spec Delta (`thoughts/specs/README.md:20-21`).

## Overall Assessment

Entries 21 to 26 closed re-run 4's findings on the callback path, the Full
tier is green on both backends, the consumer's suite is at its baseline,
and the branch carries no unreleased security record.

Two Medium remain by the stop rule. One is a documentation error the
guide's new permissions table introduced, a one-row fix. The other is the
poll's half of the owed-rebuild telling: a poll can consume a rebuild only
the legacy hook would hear. The rebuild-telling rules have now taken five
rounds and each round has found the next path; the remaining poll edge is
narrow (a legacy-hook-only subscriber that also polls, after a failed
resync fetch). Fixing it here, documenting it, or moving the owed-rebuild
telling as a whole to the subscriber fault-hardening todo is the owner's
decision.
