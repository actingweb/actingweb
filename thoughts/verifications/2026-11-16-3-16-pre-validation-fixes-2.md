# Verification: the fixes 3.16 takes before its release validation (re-run 1)

**Date:** 2026-11-16
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 3b1200e

A re-run, scaled to what changed since the first verification: the
iteration (`3fb93ab`: the delivery filter, the poll's quiet path, the
new-trust handler, two templates, tests) and the workflow contract commit
(`3b1200e`: Markdown only). The phases and the acceptance criteria the
iteration did not touch were verified in the first run and are not
repeated.

## Automated Check Results

The Full tier ran on the tree of `3fb93ab`. `f89d25d` and `3b1200e` after
it change only `CLAUDE.md`, `thoughts/` and `.claude/workflow/`, which no
check reads; it was not run again.

- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass, 599 files.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass.
- `make test-all-parallel`, **DynamoDB**: pass, 8,004 passed, 212 skipped,
  2 xfailed (parallel run, no failure).
- `make test-all-parallel`, **PostgreSQL**: pass, 7,776 passed, 440
  skipped, 2 xfailed (parallel run).
- `sphinx-build -W --keep-going`: pass.
- **The consumer's suite** on `3fb93ab`, environment 9: PostgreSQL 3
  failed, 7,405 passed, 14 skipped, 179 deselected; DynamoDB lane 3 failed,
  54 passed. The same six failures by name as on `d62021b` and `2f1a891`.
- **Browser QA:** not re-run. What the iteration changed on the pages is
  one legend sentence in each trust template and the condition for the
  re-pair notice. The notices were checked over HTTP against a real second
  actor on the demo in local QA mode (first create: no notice; the same
  again: `trust_repaired`; the host typed in another case with a trailing
  slash: the same; another relationship: `trust_exists`; a port that is not
  a number: back on the form). The legend sentences were not loaded in a
  browser.
- **Second opinion:** provider codex (`gpt-5.6-sol`, read-only) with a
  fresh-context reviewer, on `b3b5300..3fb93ab`. The reviewer called the
  filter and the URL match with mocks. Nothing High; one Medium, ten Low.
- **Built-in code review and security review:** not run as separate
  providers, as in the first run.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-16-3-16-pre-validation-fixes.md
**Iterations since:** entries 1 to 6 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The `list:` key fix filters beneath the key, not the key itself (Medium) | Fixed for the leak; it now over-filters under a narrower grant (Issue 2 below) | `actingweb/actor.py:4385-4386`; `tests/test_grant_stored_text.py::TestListDiffObjects::test_a_list_key_the_grant_excludes_by_its_path_is_not_sent` (12 cases). The reviewer ran `profile/list:secret`, `*/list:secret`, `profile/list:*`, `profile/list:secret/*` against text, null, array, object and list-diff values: the key is dropped each time, as for a whole-target subscription |
| 2. A quiet poll after a gap resync is not state the hook has heard (Medium) | Partly fixed | `actingweb/interface/subscription_manager.py:1359`; `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_poll_with_nothing_to_fetch_that_was_behind_tells_the_hook`. Open: an empty baseline (Issue 1 below), a skipped or partly stored one (Issue 3) |
| 3. "Paired again" shown when a different peer answered (Low) | Fixed for the stated case | `actingweb/handlers/www.py:1160-1163`; `tests/test_www_trust_pages.py::test_a_different_peer_at_the_url_is_not_called_a_re_pair`. The other notice still speaks for the matched row (Issue 5) |
| 4. A malformed port matches the stored peer (Low) | Partly fixed | `actingweb/handlers/www.py:60-72`; `::test_which_typed_urls_name_the_stored_peer`. An empty `?` or `#` and a tab in the host still match (Issue 4) |
| 5. Four acceptance criteria have weak tests (Low) | Partly fixed | AC-15 and AC-16 have their cases; AC-3 and AC-6 accepted as they are (iterations entry 5) |
| 6. No test joins a publisher's holed list to a subscriber's resync (Low) | Still open | not in the iteration's scope |
| 7. A resync is not fenced against a diff in progress (Low, predates the branch) | Still open, recorded | `thoughts/todo/subscription-subscriber-fault-hardening.md` |
| 8. Browser, low (hover contrast, the legend) | Legend fixed; contrast accepted (the demo's styling) | both `aw-actor-www-trust.html` templates |
| 9. Hygiene (line endings, the threat model, stale plan lines) | Fixed | `git diff --stat e928e5b -- examples/demo/templates/aw-actor-www-root.html` shows 3 insertions; `.oss-scanner/threat_model.md:118` |

## Acceptance Criteria

Only the criteria the iteration touched; the others stand as in the first
run (13 Covered, 4 Weak then).

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-8 (annotation extended: quiet means level with the publisher) | `tests/test_replica_rebuild.py`: `test_a_quiet_poll_tells_no_hook` - `assert seen == []` with the sequence level; `test_a_poll_with_nothing_to_fetch_that_was_behind_tells_the_hook` - `assert seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]` | Yes (the comparison reversed fails the second). Not for an empty baseline: Issue 1 | Pass |
| AC-15 | `tests/test_www_trust_pages.py`: `test_a_row_waiting_for_approval_is_not_an_existing_trust` - `create.assert_called_once()`, `location == f"{site.www}/trust"`; `test_a_different_peer_at_the_url_is_not_called_a_re_pair` | Yes (now fails without the approved condition) | Pass |
| AC-16 | `tests/test_www_trust_pages.py::test_nothing_from_the_query_string_is_rendered` - a known code with other parameters shows only its text; `not re.search(r'<option[^>]*value="admin"[^>]*selected', form)` | Mostly: the reviewer did not confirm the test site offers an `admin` option, in which case the select assertion is vacuous | Pass |
| AC-3, AC-6 | unchanged | Weak, accepted in iterations entry 5 | Pass |

## Remaining Tasks

- [ ] Issues 1 to 6 below, if the owner wants a clean record before the PR.
- [ ] The legend sentences in a browser (one page load each).

## Issues Found

### 1. A poll that was behind tells no hook when the baseline is empty
**Severity:** Medium (no attacker needed; the publisher's own data decides)
**Description:** The fix for the previous Issue 2 sets the baseline for the
hooks inside the block that applies it, and a whole-target baseline that is
an empty object is neither applied nor told. After a gap resync whose lost
callbacks were the deletion of the publisher's last properties, the poll
fetches `{}`, tells nothing, and records the publisher's sequence, so every
later poll is level. The replica is not emptied either; that part predates
the branch.
**Location:** `actingweb/interface/subscription_manager.py:1384` `if
transformed_data is not None if sub.subtarget else transformed_data:`
(async twin `:2400`), with the sequence write at `:1408-1420`
**Recommendation:** When behind, apply and tell an empty whole-target
baseline as a rebuild does (`test_a_settled_empty_baseline_is_told` is the
rebuild's test of the same).

### 2. The new path check drops every `list:` key under a grant that names the property
**Severity:** Low (peer-visible, in the direction of sending less; new in
the iteration)
**Description:** The second gate asks the access decision for
`<subtarget>/<key>`. Under a grant whose allow patterns name the property
and not its children (`["profile"]`), that answers no for every `list:`
key, while the sibling keys at the same depth are never asked and are sent.
The reviewer ran it: patterns `["profile", "open", "secret"]`, no
exclusion, `profile = {"name": "x", "list:secret": "hunter2", "list:open":
"v"}` gives a subtarget subscriber `{"name": "x"}` and a whole-target
subscriber all three keys. The subscriber applies what it is sent as the
property's whole value and loses the keys silently. The bare-name gate
before it has the same effect for any grant narrower than `*`, which is
wider than iterations entry 1 records ("an excluded top-level name").
**Location:** `actingweb/actor.py:4385-4386` `and self._may_read(snapshot,
k[5:])` / `and self._may_read(snapshot, f"{subtarget}/{k}")`
**Recommendation:** Make the second gate exclusion-only, or fold every key
that is not a list diff into the `_diff_part(rules, subtarget, ...)` call
beside it (the first verification's recommendation), and apply the
bare-name gate to list diffs only. A test with an allow list that names the
property.

### 3. A behind poll whose baseline was skipped or partly stored loses its claim to be told
**Severity:** Low (needs a store failure or a covering subscription)
**Description:** Such a baseline is rightly not told, but the sequence is
then written level, and "recorded below the publisher" is the only memory
that a hook is owed.
**Location:** `actingweb/interface/subscription_manager.py:1404` `if behind
and not applied.skipped and not applied.failed:` followed by `:1408`
**Recommendation:** Leave the recorded sequence where it was when an entry
failed to store.

### 4. `_same_peer_url` still matches three inputs the library refuses elsewhere
**Severity:** Low (authenticated owner only; the request goes to the stored
URI)
**Description:** `https://peer.example/a?`, `https://peer.example/a#` and a
host with a tab in it match `https://peer.example/a` and rotate the secret.
**Location:** `actingweb/handlers/www.py:68` `if not parts.hostname or "@"
in parts.netloc or parts.query or parts.fragment:`
**Recommendation:** Answer no match when `is_valid_peer_baseuri` refuses
the URL, as the first verification recommended.

### 5. The "already exists" notice still speaks for the row matched by URL
**Severity:** Low (owner only; the peer at the URL decides)
**Description:** With another relationship the handler answers
`trust_exists` before anyone asks who answers at the URL. `repaired` can be
true by `None == None` for a row without a peer id; no such row was found.
**Location:** `actingweb/handlers/www.py:1120`, `:1162`
**Recommendation:** Require a non-empty peer id on both sides; accept the
first and record it.

### 6. Smaller findings in the poll's new comparison
**Severity:** Low
**Description:**
- A callback that lands during a poll with nothing to fetch gets one extra
  `"resync"` hook call (the comparison is made before the baseline is
  fetched).
- A publisher that answers `NaN` or `Infinity` as its sequence now raises
  before the baseline is fetched; a string or `null` raised before the
  iteration too, later.
- Two mutations survive the new tests: removing `not applied.skipped` from
  the behind path, and removing the `isinstance` from `repaired`.
- The changelog does not say that the form shows no notice when another
  peer id answers, or that a URL with userinfo, a query, a fragment or a
  bad port matches no stored trust.
**Location:** `actingweb/interface/subscription_manager.py:1359-1361`,
`:1404`; `actingweb/handlers/www.py:1160`; `CHANGELOG.rst:1319-1323`
**Recommendation:** One case each for the two mutations; a failed sync
result for a sequence that is not an integer; two sentences in the
changelog.

### 7. The workflow contract's cut-off date excludes the plan it was written beside
**Severity:** Low
**Description:** `CLAUDE.md` and both READMEs say plans written "before
2026-11-16" carry no mergeable Spec Delta. This plan is dated 2026-11-16
and was written that day, before the repository adopted living specs; its
Spec Delta says the repository keeps none and holds no statement to merge.
**Location:** `CLAUDE.md` ("Living specs"), `thoughts/README.md`,
`thoughts/specs/README.md`
**Recommendation:** Say "before `3b1200e`" or name this plan as the last
one without a mergeable delta.

## Spec Merge

- Not merged, and `spec_merged:` is not written. `thoughts/specs/` exists
  since `3b1200e` with an empty index. The plan's Spec Delta predates it:
  it has no ADDED, MODIFIED, REMOVED or DECISION line, so there is nothing
  to merge and no partial spec to create from it. The capabilities this
  plan changed (subscriptions and callbacks, grants, the web UI's trust
  pages, OAuth2 sign-in) get their specs from `/create_specs`.

## Overall Assessment

The iteration closed what it set out to close for the cases the first
verification stated: the excluded `list:` key is no longer sent, a poll
that was behind tells its baseline, the form no longer announces a re-pair
for another peer, and a malformed port matches nothing. The Full tier is
green on both backends on that tree and the consumer's suite is at its
baseline. Nothing High is open.

Each fix left an edge, and one of them is Medium: the behind-poll rule
does not hold for an empty baseline, which is the same hole the previous
Issue 2 described, for a publisher that deleted everything. The filter fix
traded a leak for an omission under grants that name a property without
its children. Neither exposes data; both make a hook-driven or replicated
application miss something without an error. They are small and belong to
one more iteration, with Issues 3 to 7; whether that happens before the PR
or in the release validation is the owner's call. The record is not clean
by the stop rule until Issue 1 is closed or accepted.
