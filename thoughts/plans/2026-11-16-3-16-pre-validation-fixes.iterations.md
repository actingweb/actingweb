# Iterations: the fixes 3.16 takes before its release validation

**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md

## 2026-11-16, after verification thoughts/verifications/2026-11-16-3-16-pre-validation-fixes.md

Scope: the verification's Issues 1 to 5, and the hygiene of Issues 8 and 9.
Issues 6 and 7 stay where the verification put them.

1. **[Verification fix] A `list:` key the grant excludes by its own path is not sent to a subtarget subscriber** — beneath a subtarget a `list:<x>` key must be readable by its bare name and at `<subtarget>/<key>`; it was filtered beneath itself only, so `profile/list:secret` excluded still reached a subscriber to `properties/profile` (`actingweb/actor.py`, `filter_subscription_blob`). Why: Issue 1, peer-reachable. Test: `tests/test_grant_stored_text.py::TestListDiffObjects::test_a_list_key_the_grant_excludes_by_its_path_is_not_sent` (12 cases, red first). Not changed: a key whose bare name is an excluded top-level name is still kept back (fail closed; a subscriber may lose a key a direct read gives it), and a stored object under such a key with `list` and `operation` keys is still read as a list diff. AC: none. Spec: none.
2. **[Verification fix] A poll with nothing to fetch tells its baseline when the subscriber was behind** — the quiet path compares the recorded sequence with the publisher's before it fetches: level, no hook (the owner's rule); behind, the baseline is told once as `"resync"`, when it was applied whole (`actingweb/interface/subscription_manager.py`, both twins, `_recorded_sequence`; `CHANGELOG.rst`, `hooks-reference.rst`, `v3.16.rst`). Why: Issue 2: a gap resync resets the sequence and clears queued callbacks no hook saw, and the poll after it can find nothing retained. Tests: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_poll_with_nothing_to_fetch_that_was_behind_tells_the_hook` (red first), `::test_a_behind_poll_whose_baseline_was_not_applied_whole_is_not_told`; the quiet test now sets the sequence level. AC: AC-8's annotation extended. Spec: none.
3. **[Verification fix] "Paired again" only when the same peer came back** — the notice `trust_repaired` is shown when the row the create returns has the peer id of the row matched by URL; otherwise the plain redirect (`actingweb/handlers/www.py`). Why: Issue 3: the library acts on the id the URL's `/meta` answers now, and another id means a second trust was made under a notice saying nothing else changed. Test: `tests/test_www_trust_pages.py::test_a_different_peer_at_the_url_is_not_called_a_re_pair` (red first). AC: none (AC-15 unchanged). Spec: none.
4. **[Verification fix] A URL that is no peer address matches no stored trust** — `_same_peer_url` answers no match for a port that is not a number, userinfo, a query or a fragment; it read a bad port as the default one (`actingweb/handlers/www.py`). Why: Issue 4: such a URL matched the stored peer and rotated its secret. Test: `::test_which_typed_urls_name_the_stored_peer` (11 cases, 4 red first). AC: none. Spec: none.
5. **[Verification fix] Tests for the weak criteria** — AC-15: a row waiting for approval is not an existing trust (`::test_a_row_waiting_for_approval_is_not_an_existing_trust`, fails without the approved condition); AC-16: a known code with other parameters shows only its text, the trust type in the URL is not selected, and a form's code means nothing to the list (`::test_nothing_from_the_query_string_is_rendered`). Not changed, accepted: AC-3 stays a timing test whose evidence is the measured rate (forcing the overlap is what `tests/test_callback_pending_drain.py` does); AC-6's "records it" stays the return value (the caller's bookkeeping is `request_resync`'s, tested in `tests/test_list_diff_resync_and_filter.py::test_a_missed_subscriber_is_recorded`). AC: none. Spec: none.
6. **[Verification fix] Hygiene** — the demo's dashboard template has its CRLF line endings back (the phase commit had rewritten the file; the change is three lines again); `.oss-scanner/threat_model.md` no longer lists the removed handler; both trust templates' legend says "Waiting for peer" also covers a peer that has not verified; three lines of the plan that its later section superseded now say so. Why: Issues 8 and 9. AC: none. Spec: none.

**After the batch:** Full tier on the batch's tree: DynamoDB 8,004 passed,
PostgreSQL 7,776 passed, docs clean; committed as `3fb93ab`. The re-pair
notices checked against a real second actor on the demo (first create: no
notice; the same again: `trust_repaired`; a differently typed host: the
same; another relationship: `trust_exists`; a port that is not a number:
back on the form). The consumer's suite on `3fb93ab`, environment 9:
PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected; DynamoDB lane
3 failed, 54 passed; the same six failures by name as on `d62021b` and
`2f1a891`, nothing new (logs
`../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-3fb93ab.log`). Not
re-verified: the next `/verify_implementation` reports on this batch.

## 2026-11-16, after verification thoughts/verifications/2026-11-16-3-16-pre-validation-fixes-2.md

Scope: its Issues 1 to 7.

7. **[Verification fix] The check at a `list:` key's own path asks the exclusions only** — entry 1 asked the access decision at `<subtarget>/<key>`, which a grant that names the property and not its children fails for every `list:` key while its sibling keys are sent; it is now `path_excluded` (`actingweb/actor.py`). Why: re-run 1, Issue 2 (a regression of entry 1, in the direction of sending less). Test: `tests/test_grant_stored_text.py::TestListDiffObjects::test_a_grant_that_names_the_property_keeps_its_list_keys` (red first); entry 1's twelve cases still pass. Correction to entry 1's residual: the bare-name gate keeps a `list:<x>` key back under any grant by which the top-level name `<x>` cannot be read (a grant narrower than `*`, not only an exclusion naming it); it stays, fail closed, as the earlier verifications set it. AC: none. Spec: none.
8. **[Verification fix] A poll with nothing to fetch that is behind the publisher runs a rebuild** — entry 2 told the baseline of the quiet path's refresh, which skips an empty whole-target baseline and records the sequence whatever was stored. Behind (and with `auto_sequence`, since without it no callback records a sequence) the poll now calls `rebuild_subscription(force=True)`: it deletes what the baseline no longer carries, tells an empty baseline too, stays owed when an entry could not be stored, and tells nothing when a callback was recorded meanwhile (`actingweb/interface/subscription_manager.py`, `_behind_publisher`, both twins; `CHANGELOG.rst`, `hooks-reference.rst`, `v3.16.rst`). A publisher's sequence that is not an integer is never "behind" (a `NaN` raised). Why: re-run 1, Issues 1, 3 and 6. Tests: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_behind_poll_tells_an_empty_baseline_and_empties_the_replica`, `::test_a_behind_poll_whose_baseline_was_not_stored_whole_stays_owed`, `::test_a_publisher_sequence_that_is_no_integer_is_not_behind` (red first), `::test_without_sequence_tracking_a_quiet_poll_is_never_behind`. AC: AC-8's annotation covers it. Spec: none.
9. **[Verification fix] The stored-trust match accepts only what the library accepts as a base URI** — `_same_peer_url` answers no match for a URL `is_valid_peer_baseuri` refuses and for an empty query or fragment (`https://peer/a?`, `...#`, a tab in the host matched and rotated the secret); "paired again" needs a peer id on the matched row (`actingweb/handlers/www.py`, `CHANGELOG.rst`). Why: re-run 1, Issues 4 and 5. Tests: `tests/test_www_trust_pages.py::test_which_typed_urls_name_the_stored_peer` (four more cases, three red first), `::test_a_returned_row_without_a_peer_id_is_not_called_a_re_pair` (red first). Accepted, not changed: with another relationship the form answers "already exists" for the row matched by URL without asking who answers there now (owner only; nothing is changed by it). AC: none. Spec: none.
10. **[Verification fix] Small things from re-run 1** — AC-16's select assertion first checks the type is offered; the changelog names the two form rules; the workflow contract names this plan as the last without a mergeable Spec Delta instead of a date that excluded it (`tests/test_www_trust_pages.py`, `CHANGELOG.rst`, `CLAUDE.md`, `thoughts/specs/README.md`). Why: Issues 6 and 7. AC: none. Spec: none.

**After the batch:** Full tier on the batch's tree: DynamoDB 8,018 passed,
PostgreSQL 7,790 passed, docs clean (one test argument's type was corrected
after that run; `tests/test_replica_rebuild.py` re-run green on both
backends, `pyright` 0 errors); committed as `ab11326`. The consumer's suite
on `ab11326`, environment 9: PostgreSQL 3 failed, 7,405 passed, 14 skipped,
179 deselected; DynamoDB lane 3 failed, 54 passed; the same six failures by
name, nothing new (logs
`../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-ab11326.log`). Not loaded
in a browser: the two legend sentences of entry 6. Not re-verified.

## 2026-11-17, after verification thoughts/verifications/2026-11-16-3-16-pre-validation-fixes-3.md

Scope: its Issues 1 to 4 (all Low), and the text or `null` sequence its
previous-issue table left open.

11. **[Verification fix] A poll does not tell a rebuild's baseline that another subscription covers** — a behind poll of a covered subtarget subscription told a baseline the replica did not store. The rebuild still returns its baseline (the callback path tells the one that answered for its callback) and says `baseline_skipped`, a new defaulted field of `SubscriptionSyncResult`; the poll does not tell it (`actingweb/interface/subscription_manager.py`). Why: re-run 2, Issue 1; the docs already said a skipped baseline is not told. Tests: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_behind_poll_of_a_covered_subscription_tells_no_hook` (red first), `::test_a_skipped_rebuild_still_returns_its_baseline`. AC: AC-8 annotated. Spec: none.
12. **[Verification fix] A behind poll's rebuild that failed is attempted again at most once a minute** — entry 8 forced every attempt, so a failed baseline fetch was repeated on every poll. Now forced only when no rebuild is owed (an interval a pushed resync's sweep started does not hold it back); a failed one is owed, and a poll inside its interval fails with 429 (both twins, `_rebuild_owed`; `CHANGELOG.rst`, `hooks-reference.rst`, `v3.16.rst`). Why: re-run 2, Issue 2. Tests: `::test_a_failing_behind_rebuild_is_attempted_once_a_minute`, `::test_an_interval_another_path_started_does_not_hold_the_behind_poll` (each fails with the force rule changed the other way). AC: AC-8 annotated. Spec: none.
13. **[Verification fix] A behind poll without `auto_storage` tells a registered data hook** — the comparison sat inside the storage branch, so a hooks-only subscriber heard nothing after a gap resync. It now runs before it when `auto_storage` is on or a data hook is registered; the rebuild then stores nothing, records the sequence and tells. Without either, the poll stays one request and records the sequence, as before (the five quiet-path tests in `tests/test_subscription_sync.py` and `tests/test_subscription_manager.py` pass unchanged). Same files and docs. Why: re-run 2, Issue 3. Tests: `::test_a_behind_poll_without_auto_storage_tells_the_hook` (red first), `::test_a_level_poll_without_auto_storage_tells_no_hook`. AC: AC-8 annotated. Spec: none.
14. **[Verification fix] The trust form strips the typed URL** — whitespace around a pasted URL made a second trust instead of a re-pair once the match refused what a base URI refuses (`actingweb/handlers/www.py`). Why: re-run 2, Issue 4. Test: `tests/test_www_trust_pages.py::test_whitespace_around_a_typed_url_still_names_the_stored_peer` (red first). AC: none. Spec: none.
15. **[Verification fix] A publisher sequence that is not an integer is never recorded** — the poll's six sequence writes and results read it through `_publisher_sequence` (0 for text, `null`, a boolean); a text or `null` sequence raised `TypeError` and `true` was recorded (`actingweb/interface/subscription_manager.py`). Why: re-run 1, Issue 6, left partly open. Test: `::test_a_publisher_sequence_that_is_no_integer_is_not_behind` now asserts success and nothing recorded (red first for three of four cases). AC: none. Spec: none.

## 2026-11-17, after verification thoughts/verifications/2026-11-17-3-16-pre-validation-fixes.md

Scope: its Issues 1 to 5 (one Medium, four Low). Entries 11 to 15 are not
yet committed; this batch lands with them.

16. **[Verification fix] A hooks-only subscriber's owed rebuild runs where it is told** — entry 13 let a behind poll without `auto_storage` leave a rebuild owed, while the poll's owed-and-due check and the callback's owed-rebuild branch ran only with `auto_storage`; the processor's REBUILD answer then ran it after the interval without telling any hook, and the gap was lost. All three now ask one rule, `rebuilds_for(config, target)`: a replica, or a data hook for the subscription's target or `"*"` (`actingweb/interface/subscription_manager.py`, `_rebuild_owed_and_due(target=)`; `actingweb/handlers/callbacks.py`). Why: re-run 3, Issue 1 (Medium, peer-reachable). Tests: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_hooks_only_rebuild_owed_after_a_failure_is_told_when_it_runs`, `tests/test_subscriber_receiver_1_5.py::test_a_hooks_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told` (both red first). AC: AC-8 annotated. Spec: none.
17. **[Verification fix] Only a hook for the subscription's target makes a behind poll rebuild** — `bool(subscription_data_hooks)` counted a hook on any target, so a subscription nobody hears ran a rebuild and could fail on every poll; `rebuilds_for` (entry 16) asks for the target or `"*"`. Why: re-run 3, Issue 2. Test: `::test_a_hook_on_another_target_does_not_make_a_behind_poll_rebuild` (red first, on the request count). AC: none. Spec: none.
18. **[Verification fix] Duplicates under a sequence that is not an integer tell no hook** — the duplicate-diffs path records and clears nothing then, so it returned the same baseline on every poll; it now returns none (both twins). Why: re-run 3, Issue 3. Test: `::test_duplicates_under_a_sequence_that_is_no_integer_tell_no_hook` (red first). AC: none. Spec: none.
19. **[Verification fix] The fault contract of a hooks-only rebuild is stated, not changed** — a store fault raises `DbError` from the rebuild's reservation, as with a replica; the gap-resync caller relies on it to answer 503. `sync_subscription`'s docstring says so. Why: re-run 3, Issue 4 (accepted as the existing contract). AC: none. Spec: none.
20. **[Verification fix] The once-a-minute test runs without `auto_storage` too** — parametrized over a replica and hooks only. Why: re-run 3, Issue 5. AC: none. Spec: none.

## 2026-11-17, after verification thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-2.md

Scope: its Issues 1 to 6. Issue 1 predates the branch (the owing and the
untold REBUILD branch are on master since specification 1.5); the owner
asked for it here.

21. **[Verification fix] The legacy `subscription` hook counts as a hook that hears an owed rebuild** — with `auto_storage` off and only that hook, a failed resync fetch owed a rebuild that the processor's REBUILD answer ran untold. The callback gate now counts a registered legacy hook, and `_rebuild_owed_and_due(told_elsewhere=)` answers for it (`actingweb/handlers/callbacks.py`, `actingweb/interface/subscription_manager.py`). Why: re-run 4, Issue 1 (Medium, peer-reachable). Test: `tests/test_subscriber_receiver_1_5.py::test_a_legacy_hook_only_subscribers_owed_rebuild_runs_on_a_callback_and_is_told` (red first). AC: none. Spec: none.
22. **[Verification fix] An unsettled rebuild is told by the next rebuild, not by the callback sent again** — the docs promised the 503'd callback is told when sent again; it is usually a recorded duplicate by then. Corrected in `hooks-reference.rst` and `CHANGELOG.rst`, with the test's docstring. Why: re-run 4, Issue 2. AC: none. Spec: none.
23. **[Verification fix] The processor's REBUILD answer for a rebuild owed from before tells the hooks** — its interval can run out between the callback's check and the processor's claim; `CallbackProcessor.rebuild_was_owed` marks that answer (not one an out-of-step diff in this callback caused, which its handler told), and the branch tells the settled baseline as a resync (`actingweb/callback_processor.py`, `actingweb/handlers/callbacks.py`). Why: re-run 4, Issue 3. Test: `::test_an_owed_rebuild_the_processor_runs_tells_the_hooks` (red first). AC: none. Spec: none.
24. **[Verification fix] Deleting a covering subscription owes a rebuild only to a replica** — without `auto_storage` the covered subscriptions' diffs were applied and told all along; owing them made the next diff a resync (`actingweb/actor.py`). Why: re-run 4, Issue 4. Test: `tests/test_replica_rebuild.py::TestVerification4Covered::test_without_a_replica_deleting_a_covering_subscription_owes_nothing` (red first, two cases). AC: none. Spec: none.
25. **[Verification fix] The poll passes its target to the owed check; the callback path's fault is stated** — the poll loads the subscription before the owed check and passes `target=`, so a hooks-only poll reads it once; a subscription that is gone answers 404 before an owed rebuild is tried. The hooks reference says reserving a rebuild uses the callback state store without `auto_storage` too, and a fault answers 503 (`subscription_manager.py` both twins, `hooks-reference.rst`; `::TestReservation::test_a_sync_runs_an_owed_rebuild` now has a subscription). Why: re-run 4, Issue 5. AC: none. Spec: none.
26. **[Verification fix] Tests that pin entries 16 to 18 on both paths** — the callback gate without the owed check patched (`::test_the_callback_gate_asks_for_a_hook_on_the_subscriptions_target`, three cases); the other-target and duplicates cases on the async poll too. Why: re-run 4, Issue 6. AC: none. Spec: none.

**After the batch:** Full tier on the batch's tree: DynamoDB 8,046 passed,
PostgreSQL 7,818 passed, docs clean (built again after the migration guide
edits below). The consumer's suite (environment 9, the library worktree at
`8bb63cf` with this tree's `actingweb/` diff applied): PostgreSQL 3 failed,
7,405 passed, 14 skipped, 179 deselected; DynamoDB lane 3 failed, 54
passed; the same six failures by name, nothing new (logs
`../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-iter5.log`). From the
owner's review of what the consumer's runs taught: the migration guide
gained one table of the DynamoDB permissions 3.16 adds (and that IAM has no
`TransactWriteItems` action), the fresh-database order for CI, two fault
contract checks (a broad `except` around a write; test doubles that passed
because 3.15 swallowed a failed write), and the hooks-only subscriber's
`"resync"` and the poll's 429; the changelog's owed-rebuild entry says the
same. The todo index and the consumer-suite and fault-hardening todos are
updated. Not re-verified.

## 2026-11-17, after verification thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-3.md

Scope: its Issue 1 now; the rest after an audit of the owed-rebuild rules
(owner, 2026-11-17: five rounds each found the next path, so the rule is
mapped as a whole before the next fix).

27. **[Verification fix] The guide's permissions table names `ConditionCheckItem` on the properties table** — with reverse lookup on, an indexed write checks the actor and property rows in one transaction whatever the uniqueness setting; the table had no properties row and gave the actors row the creator claim only (`docs/migration/v3.16.rst`). Why: re-run 5, Issue 1 (an operator's policy built from it refuses indexed writes). AC: none. Spec: none.

**The audit (2026-11-17).** A map of every place that owes, runs and tells
a subscriber's rebuild, by subscriber shape (replica, data hook, legacy or
`"*"` callback hook), made from the code by one agent and checked against
the code by a second (codex and a fresh-context reviewer); the claims list
is in the session's scratchpad, the result here. It confirmed re-run 5's
Issues 2 to 8 and found more: a poll that stops at a list diff it could
not apply drops the rest of its diffs and suppresses the baseline as told,
so hooks lose those changes; a poll called without a configuration
rebuilds a replica the application never configured; a polled resync
marker reaches a hooks-only subscriber as an empty diff; the gap resync's
replay discards a REBUILD answer; the all-duplicates path tells a baseline
while a rebuild is owed. **Owner decisions:** one rule, applied here —
a rebuild is owed only when it has work (a replica, or a hook that hears
it); a settled rebuild **always** tells its baseline to every hook the
path that ran it can reach (a hook may hear a list diff, then the
baseline); a baseline another subscription's replica covers is **never**
told; a poll never runs a rebuild only the legacy hook would hear; a
callback whose own change was applied answers 204 when the rebuild after
it does not settle.

28. **[Decision changed] A settled rebuild always tells its baseline; a covered one never** — the poll's `rebuild_told` and the processor's `rebuild_was_owed` are gone: every REBUILD answer, on a callback (`CallbacksHandler._run_rebuild_answer`, also for the gap resync's replay, which discarded it) and in a poll (both twins), tells its settled baseline, also after the list diff it was told first; no path tells a `baseline_skipped` baseline (`actingweb/handlers/callbacks.py`, `actingweb/callback_processor.py`, `actingweb/interface/subscription_manager.py`). Why: the audit; a poll that stopped at an out-of-step diff lost the diffs after it, and re-run 5's Issues 3, 4 and 7. Tests: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_rebuild_after_a_list_diff_the_poll_told_tells_the_baseline_too` (was `..._tells_no_second_hook`), `tests/test_subscriber_receiver_1_5.py::test_a_rebuild_after_the_callbacks_own_list_diff_tells_the_baseline`, `::test_a_covered_baseline_is_not_told_on_the_callback_path` (red first). AC: AC-8 annotated. Spec: none.
29. **[Decision changed] A rebuild is owed or run only when it has work** — a failed resync fetch owes one only with a replica or a hook that hears it (`_resync_fetch_failed(owe=)`, `_hears_a_rebuild`, which counts a `"*"` callback hook as the legacy one); a REBUILD answer on a callback with nothing to rebuild and nobody to tell drops the debt; a poll leaves a rebuild only the legacy hook would hear owed for the next callback; a polled resync marker rebuilds whenever `rebuilds_for` (it reached a hooks-only subscriber as an empty diff). Why: the audit, re-run 5's Issues 2, 6 and 8. Tests: `::test_a_failed_resync_fetch_owes_a_rebuild_only_when_it_has_work` (three shapes), `::test_a_poll_leaves_a_rebuild_only_the_legacy_hook_hears_owed`, `::test_a_polled_marker_rebuilds_for_a_hooks_only_subscriber` (red first). AC: AC-8 annotated. Spec: none.
30. **[Bug fix] A poll without a configuration uses the application's** — `_processing_config`: the passed one, else `with_subscription_processing()`'s, else the defaults; `sync_subscription(config=None)` built a replica an application without `auto_storage` never configured (poll twins, `rebuild_subscription`, the baseline sync). With no processing configuration at all, deleting a covering subscription owes the covered ones again (the defaults keep a replica; re-run 5, Issue 5). Tests: `::test_a_poll_uses_the_applications_configuration_when_given_none` (red first); the covered-owing test's unconfigured case. AC: none. Spec: none.
31. **[Bug fix] The all-duplicates poll path tells no baseline while a rebuild is owed** — the rebuild tells it (both twins). Test: `::test_duplicates_while_a_rebuild_is_owed_tell_no_baseline` (red first). AC: none. Spec: none.
32. **[Verification fix] The docs state the rule** — the hooks reference's poll and owed-rebuild bullets are rewritten as the rule (what tells, who runs, quiet and behind polls, answers: 503 for a callback whose rebuild replaced its diff, 204 for one whose own change was applied); the migration guide's subscriber paragraph and the changelog's poll and owed-rebuild entries likewise, with `sync_peer()` without a configuration as a check item; `sync_subscription` and `rebuild_subscription` docstrings (`rebuild_subscription` tells no hook; its caller does). Why: the audit's doc findings and re-run 5's Issues 6 to 8. AC: none. Spec: none.

## 2026-11-17, after verification thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-4.md

Scope: its Issues 1 to 6. The two wire rows (WD7, WL13.target) changed as
the rule says and are re-recorded under this plan's ownership with the
commit (gate 5).

33. **[Bug fix] A poll without a configuration tells the application's hooks its baseline** — `sync_subscription` and its twin resolve the configuration once and pass it to the poll and to `_tell_polled_baseline`; the teller got the raw `None`, found no hooks, and a settled rebuild's change was lost (`actingweb/interface/subscription_manager.py`). Why: re-run 6, Issue 1 (High; a consumer polls with `sync_peer_async(peer_id)`). Test: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_poll_without_a_configuration_tells_the_applications_hooks` (red first). AC: none. Spec: none.
34. **[Bug fix] A polled marker owes a rebuild a poll cannot tell** — with no replica and no data hook the marker is still applied as an empty diff (it tells nobody) and now owes the rebuild (`_owe_rebuild`, all four marker sites), which the next callback runs and tells the legacy hook, or drops when nobody hears. Why: re-run 6, Issue 2. Test: `::test_a_polled_marker_owes_a_rebuild_a_poll_cannot_tell` (red first). AC: none. Spec: none.
35. **[Bug fix] A callback whose change a batch's rebuild dropped answers 503 when that rebuild fails** — `CallbackProcessor.applied_through` records what the last batch applied; `_run_rebuild_answer` returns whether the rebuild settled, and the handler answers 503 when it did not and the delivered sequence is above what was applied (`actingweb/callback_processor.py`, `actingweb/handlers/callbacks.py`). Why: re-run 6, Issue 3. Test: `tests/test_subscriber_receiver_1_5.py::test_a_failed_rebuild_answers_503_when_the_callbacks_change_was_dropped` (dropped case red first; applied case 204). AC: none. Spec: none.
36. **[Bug fix] A gap resync owes a rebuild the legacy hook alone would hear** — its poll tells data hooks only; with none and a legacy hook, the rebuild is owed after a successful sync, for the next callback (`actingweb/handlers/callbacks.py`). Why: re-run 6, Issue 4 (the audit's claim 8). Test: `::test_the_gap_resync_owes_a_rebuild_only_the_legacy_hook_hears` (red first). AC: none. Spec: none.
37. **[Verification fix] The rule's remaining cells: docs and tests** — the hooks reference says a callback drops a debt nobody hears and a poll, which cannot see the legacy hook, keeps it; the answers bullet, the changelog and the guide state the 503 for a dropped change, the fault after an applied change, and the marker and gap-resync owing. Tests for `_run_rebuild_answer`'s covered and drop-the-debt branches (`::test_the_processors_rebuild_tells_no_covered_baseline`, `::test_a_rebuild_answer_nobody_hears_drops_the_debt`; they pass on entry 28's code, coverage only). Why: re-run 6, Issues 5 and 6. AC: none. Spec: none.

**After the batch:** the wire rows WD7, WL13.target and WD11 changed as
the rule says (a poll without a configuration uses and tells the
application's; a settled rebuild tells its baseline): each gains one data
hook event and nothing else. Ownership commits `4e19295` and `bafc726`,
then re-recorded, each identical on a second DynamoDB run and on
PostgreSQL. Full tier on the batch's tree: DynamoDB 8,069 passed,
PostgreSQL 7,841 passed, docs clean. Not re-verified.

## 2026-11-17, after verification thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-5.md

Scope: its Issues 1 to 6 (owner: revert entries 34 and 35, close Issue 1
in code).

38. **[Decision changed] Entry 35 reverted: no 503 for a "dropped" callback** — the processor claims one callback at a time and prunes only that one, so a delivered callback's change is never dropped by a batch's rebuild; the 503 fired only for a callback still queued. `CallbackProcessor.applied_through` and the branch are gone; the docs say a callback whose change was applied, or is queued, answers 204, and that this library's publisher does not resend on 503 (`actingweb/callback_processor.py`, `actingweb/handlers/callbacks.py`, `hooks-reference.rst`, `CHANGELOG.rst`). Why: re-run 7, Issues 3 and 4. AC: none. Spec: none.
39. **[Decision changed] Entry 34 reverted: a polled marker owes nothing a poll cannot tell** — markers are stored only for subscribers that get no callbacks, so the debt was never collected; with no replica and no data hook a marker is applied as an empty diff and tells nobody, as the docs now say (`actingweb/interface/subscription_manager.py`, the four sites). Why: re-run 7, Issue 2. Test: `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_polled_marker_owes_nothing_a_poll_cannot_tell` (replaces entry 34's). AC: none. Spec: none.
40. **[Bug fix] A gap resync owes a rebuild whenever the legacy hook is registered** — its poll tells data hooks only, so a subscriber with a replica or a data hook and the legacy hook missed the gap there; the rebuild is now owed whatever `rebuilds_for` says, and a later callback (or the replayed one) runs and tells every hook (`actingweb/handlers/callbacks.py`, `hooks-reference.rst`, `CHANGELOG.rst`, `v3.16.rst`). Why: re-run 7, Issue 1 (Medium). Test: `tests/test_subscriber_receiver_1_5.py::test_the_gap_resync_owes_a_rebuild_when_a_legacy_hook_hears` (four shapes; the replica-data-and-legacy case red under entry 36's rule). AC: none. Spec: none.
41. **[Verification fix] A lost owe is logged; the drop-the-debt test owes first** — `_owe_rebuild` logs a warning when `settle_rebuild` loses every compare-and-swap; `test_a_rebuild_answer_nobody_hears_drops_the_debt` marks the debt before the callback, so it fails without the drop. Why: re-run 7, Issues 5 and 6. AC: none. Spec: none.

**After the batch:** Full tier on the batch's tree: DynamoDB 8,070
passed, PostgreSQL 7,842 passed, docs clean; no wire recording changed.
`ruff format` then rewrapped one condition in `_owe_rebuild`; the four
subscription test modules re-run green. Not re-verified.

## 2026-11-17, after verification thoughts/verifications/2026-11-17-3-16-pre-validation-fixes-6.md

Scope: its Issues 1 to 7.

42. **[Verification fix] Entry 41's test change, made** — `test_a_rebuild_answer_nobody_hears_drops_the_debt` now owes first (`owe=True`) and fails with the drop removed (checked by removing it). Entry 41 claimed the change, but the script that made it replaced an argument an earlier step of the same script had already removed, and the replacement matched nothing without failing; the commit `1a68f1d` did not carry it. Why: re-run 8, Issue 1. AC: none. Spec: none.
43. **[Decision changed] A gap resync with a legacy hook rebuilds there, instead of owing** — entry 40's debt could be settled by an application's poll, which tells data hooks only, so the legacy hook still missed the gap. The gap resync now runs `_run_rebuild_answer(force=True)` after its sync (forced past the interval its own poll's rebuild may have started; not twice when the replay already rebuilt), and tells every hook; a rebuild that fails stays owed. `_owe_rebuild` and its warning are gone; the lingering debt's side effects (a 429 on a behind poll, a withheld all-duplicates baseline) with it (`actingweb/handlers/callbacks.py`, `actingweb/interface/subscription_manager.py`, `hooks-reference.rst`, `CHANGELOG.rst`, `v3.16.rst`). Why: re-run 8, Issues 2, 3 and 4. Test: `tests/test_subscriber_receiver_1_5.py::test_the_gap_resync_rebuilds_and_tells_when_a_legacy_hook_hears` (five shapes, a `"*"` callback hook among them; the three with a hook red first). AC: none. Spec: none.
44. **[Verification fix] The 204 for an unsettled REBUILD is pinned; the guide's behind-poll sentence** — `::test_an_unsettled_rebuild_answer_keeps_the_callback_and_the_debt`; "on a behind poll and on a polled resync marker (with a data hook)". Why: re-run 8, Issues 5 to 7. AC: none. Spec: none.

**After the batch:** Full tier on the batch's tree: PostgreSQL 7,844
passed; DynamoDB 8,071 passed and 1 error, the setup of
`tests/performance/test_backend_performance.py::TestSpannedListPropertyPerformance::test_list_property_spanned_to_list`
("too many rank collisions, retry later", list storage under the
parallel run's load); run alone it passed three times of three, so a
parallel-isolation flake, not this batch's. Docs clean; no wire recording
changed. Not re-verified.
45. **[Decision changed] The legacy hook is not served by polls; entry 43's forced rebuild is removed** — owner, 2026-11-17, after weighing the consumer consequence: no known consumer registers the legacy `subscription` callback hook (Emm and the demo use `subscription_data_hook`; the docs already steer to it), while entry 43 made every gap resync rebuild once more for any application with a `"*"` callback hook. The rule is stated instead: the legacy hook hears callbacks and the rebuilds the callback path runs; what a poll does, the gap resync's included, reaches data hooks only (`actingweb/handlers/callbacks.py`: the gap resync's rebuild and `_run_rebuild_answer`'s `force` removed; `hooks-reference.rst`, `CHANGELOG.rst`, `v3.16.rst`). Test: `tests/test_subscriber_receiver_1_5.py::test_the_gap_resync_runs_no_rebuild_for_the_legacy_hook` (four shapes, a `"*"` callback hook among them; replaces entry 43's). No todo is filed for polls telling the legacy hook: the owner judged the consequence too small for the design change. AC: none. Spec: none.

**After entry 45:** Full tier: DynamoDB 8,071 passed, PostgreSQL 7,843
passed, docs clean; no wire recording changed. Not re-verified.
