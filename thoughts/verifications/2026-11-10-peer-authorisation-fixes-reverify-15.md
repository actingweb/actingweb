# Verification: peer authorisation fixes (fifteenth run: reverify-14's fixes)

**Date:** 2026-11-10
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 8b7b444 (code as of 999f3b6; 8b7b444 adds records only)

This run verifies Iteration 91 (`d9aa071..999f3b6`), which answered Issues
1 to 3 of `verifications/2026-11-10-peer-authorisation-fixes-reverify-14.md`
under the owner's scope choice. The reviews were scaled to the delta:
about 30 lines of code, two doc paragraphs and four tests.

## Automated Check Results

- **Browser QA:** N/A. No page, template or `handlers/www.py` changed.
- **Outside voice** (the outside-voice agent, fresh-context Claude only;
  codex not run for a delta this size): three Low findings (Issues 3 to 5
  below); it agreed with my two (Issues 1 and 2).
- **Built-in code and security review:** run in this context on the delta.
  No grant bypass: every path the check accepts is re-read under the
  client's own grant, and the served URL is rebuilt on this actor's host.
- **ruff check:** pass. **ruff format --check:** pass, 532 files.
  **pyright:** 0 errors, 0 warnings. **verify_groups:** 54 groups
  documented, wire registry consistent.
- **DynamoDB** (`make test-all-parallel`): 6181 passed, 60 skipped,
  1 xfailed, no failure.
- **PostgreSQL** (`make test-all-parallel` with the PostgreSQL env):
  5978 passed, 263 skipped, 1 xfailed, no failure.
- **Docs** (`sphinx-build -W`): pass.
- **Wire recordings:** unchanged.
- **Emm's suite on `999f3b6`** (recorded in `8b7b444`): PostgreSQL
  2 failed / 7406 passed, DynamoDB 3 failed / 54 passed: the `master`
  baseline's failures, by name.

## Phase Verification

### Iteration 91 - VERIFIED (with Low notes)

**Changes verified:**
- `actingweb/actor.py:88-113` - `resync_marker_url` accepts a marker only
  when its path after `/<actor>/` is the subscription's `target[/subtarget]`
  or under it, and returns the URL rebuilt by `_resync_url` from the
  current config. Matches the plan.
- `actingweb/handlers/subscription.py:35-43` - `_served` passes the
  subscription's target and subtarget.
- `docs/protocol/actingweb-spec.rst:3008-3017`,
  `docs/guides/subscriptions.rst:261-270`, `CHANGELOG.rst:29-33` - the
  scope, the discard, the skip rule.

**Tests verified:**
- `test_data_shaped_like_a_marker_outside_the_subscription_is_data`
  (sibling, `trust`, parent) and
  `test_a_marker_stored_before_a_host_change_points_at_the_new_host` -
  fail on the code before, pass now.
- `test_a_marker_for_one_subtarget_reaches_a_whole_target_subscriber` -
  pins the narrow marker the docs describe.

**Deviations from plan:** none.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-10-peer-authorisation-fixes-reverify-14.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Unscoped marker after a subtarget resume (Medium) | Fixed (docs) | Spec and guide: discard only what the `url` names; test pins the URL |
| 2. Diffs after a marker applied twice (Medium) | Fixed for the list answer; see Issues 2 and 3 below | Spec `:3013-3016` |
| 3. Prefix-only recognition (Low) | Fixed; see Issue 1 below | `actor.py:108-113`; tests above |
| 4. Marker deleted on its per-sequence GET (Low) | Accepted (owner's scope) | Iteration 91 scope note |
| 5. Marker URL leaves out `resource` (Low) | Accepted (owner's scope); see Issue 4 below | |
| 6. Unknown type merges `{}` (Low) | Accepted | |

## Remaining Tasks

- [ ] Nothing the owner's rule takes: every issue below needs a client
      polling subscriptions, and none is known.
- [ ] Before anything is pushed: the second security plan
      (`grant-enforcement-per-route`).

## Issues Found

### Issue 1: dot segments pass the scope check
**Severity:** Low
**Description:** `actor.py:112` `if path != scope and not
path.startswith(f"{scope}/")` accepts `properties/notes/../../trust`, and
the URL is served as it is; an HTTP client normalises it to `/<actor>/trust`.
It needs a value written in the marker's shape (the owner or a peer with
a write grant); the read is under the reader's own grant.
**Location:** `actingweb/actor.py:110-113`
**Recommendation:** refuse a path with `.` or `..` segments.

### Issue 2: the skip rule covers one list answer, not per-sequence reads
**Severity:** Low
**Description:** a client reading `/<seq>` one by one can fetch a diff
stored before its re-read after the re-read, and apply it again. The spec
text speaks of "the same answer" only.
**Location:** `docs/protocol/actingweb-spec.rst:3013-3016`
**Recommendation:** point polling clients at the list endpoint (also
answers reverify-14 Issue 4).

### Issue 3: the skip rule does not say how a URL maps to a diff's keys
**Severity:** Low
**Description:** a diff carries no path. `actingweb-spec.rst:3015` "skip
those parts of the diffs after the marker" leaves the client to infer that
the segment after the target is the diff's top-level key.
**Location:** `docs/protocol/actingweb-spec.rst:3015`, `docs/guides/subscriptions.rst:269`
**Recommendation:** state the mapping in one sentence.

### Issue 4: a resource subscription gets a broader marker than it subscribed to
**Severity:** Low (reverify-14 Issue 5, now contradicted by the new text)
**Description:** `actor.py:4518-4519` builds the URL without `resource`,
while the subscription's diffs are the resource's bare value
(`actor.py:5082`). The spec now says the URL "is the subscription's target
or lies under it", which a resource subscription reads as broader.
**Location:** `actingweb/actor.py:4518`
**Recommendation:** append the resource to the URL and to the scope.

### Issue 5: an empty target narrows the scope check to the actor root
**Severity:** Low (no known path creates one)
**Description:** with `target=""`, `actor.py:111` gives an empty scope, so
only the root URL matches.
**Location:** `actingweb/actor.py:111`
**Recommendation:** none unless whole-actor subscriptions become possible.

## Overall Assessment

Iteration 91 does what reverify-14 asked: a marker is recognised only
within its subscription and survives a host change, and the spec says
what a polling client discards and skips. The Full tier is green on both
backends (DynamoDB 6181, PostgreSQL 5978), the docs build passes, no
recording changed, and Emm's suite matches its baseline.

The five Low notes all concern a polling client written to the new spec
text; none is known, and none leaks data. Under the owner's rule nothing
here blocks the PR. The second security plan (`grant-enforcement-per-route`)
still comes before anything is pushed.
