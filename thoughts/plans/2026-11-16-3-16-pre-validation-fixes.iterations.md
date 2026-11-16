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
