# Verification: peer authorisation fixes (fourteenth run: reverify-13's fix)

**Date:** 2026-11-10
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** f29b3df (code as of 409adeb; f29b3df adds records only)

This run verifies Iteration 90 (`8430bbc..409adeb`). It answers Issue 1
of `verifications/2026-11-09-peer-authorisation-fixes-reverify-13.md` with
the owner's option 1: an OAuth2 client's resync is a marker stored as its
next diff, and the client re-reads the target under its own grant. The
reviews were scaled to the delta: about 130 lines of `actor.py` and
`handlers/subscription.py`, their tests, and three doc paragraphs.

## Automated Check Results

- **Browser QA:** N/A. Iteration 90 touches no page, template or
  `handlers/www.py`.
- **Outside voice** (the outside-voice agent), with two providers:
  - **Codex** (`codex exec -s read-only`, outside the sandbox): a marker
    read through its own diff URL is deleted before the re-read
    (Issue 4); the URL leaves out `resource` (Issue 5); an unknown type
    merges `{}` (Issue 6; codex rated it High against iteration 88, which
    never shipped).
  - **The fresh-context Claude reviewer:** a resume of one subtarget sends
    a whole-target subscriber to one property, unscoped (Issue 1); later
    diffs in the same poll are applied twice after the re-read (Issue 2);
    a marker stored before a host change is served as data (Issue 3).
  - **Both agreed** with my own finding on the prefix-only check (Issue 3
    folds it in).
  - Consumers checked clean: `interface/subscription_manager.py`'s
    `sync_peer` and `handlers/callbacks.py`'s low-granularity fetch never
    meet a marker. Markers are stored only on the `not _has_peer_endpoint`
    branch, and a library peer's row at the publisher always has an
    endpoint.
- **Built-in code and security review:** run in this context on the delta.
  One finding at the bar, the prefix-only check (folded into Issue 3). No
  grant bypass: a marker carries no data, `_served` returns `data: {}`, and
  a forged marker only points the reader at a URL it reads under its own
  grant.
- **ruff check:** pass. **ruff format --check:** pass, 532 files.
  **pyright:** 0 errors, 0 warnings. **verify_groups:** 54 groups
  documented, wire registry consistent.
- **DynamoDB** (`make test-all-parallel`): 6176 passed, 60 skipped,
  1 xfailed, no failure.
- **PostgreSQL** (`make test-all-parallel` with the PostgreSQL env):
  5973 passed, 263 skipped, 1 xfailed, no failure.
- **Docs** (`sphinx-build -W`): pass.
- **Wire recordings:** unchanged (`git status` clean after both runs).
- **Emm's suite on `409adeb`** (recorded in `f29b3df`): PostgreSQL
  2 failed / 7406 passed, DynamoDB 3 failed / 54 passed: the `master`
  baseline's failing tests, by name.

## Phase Verification

### Iteration 90 - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py:74-102` - `_resync_url`, `resync_marker`,
  `resync_marker_url` as planned.
- `actingweb/actor.py:4487-4511` - the client branch stores
  `resync_marker(...)` at the next sequence; `_store_full_state_diff` is
  gone and the peer fallback builds its full state inline again
  (`:4605-4625`), unchanged in behaviour from before iteration 88.
- `actingweb/handlers/subscription.py:27-41` - `_served` serves a marker as
  `type`, `url`, `data: {}`, and every other diff through `_as_permitted`;
  used at `:422` and `:658`.
- `CHANGELOG.rst:29-32`, `docs/guides/subscriptions.rst:261-266`,
  `docs/protocol/actingweb-spec.rst:3008-3013` - describe the marker.

**Tests verified:**
- `TestTheResyncAfterReverify11::test_a_clients_row_gets_a_resync_marker`
  (both client kinds) - the stored diff is exactly the marker, count 1, no
  pending record.
- `test_the_marker_carries_nothing_the_grant_excludes` (list and
  per-sequence) - drives both handlers with the client's bearer; the
  excluded value is absent, the URL is the subscription's subtarget, data
  is `{}`. Meaningful: it fails on 8430bbc.
- `test_a_peer_still_gets_its_resync` - control.
- Not covered: a resume of a subtarget for a whole-target subscription, a
  marker whose prefix no longer matches, a forged marker value.

**Deviations from plan:** none beyond the iteration's own entry.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-13.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Full state escapes the grant (High) | Fixed | No data stored; `handlers/subscription.py:40`; test above |
| 2. No marker, client merges full state (Medium) | Fixed | The marker is the type; `actor.py:84` |
| 3. Retry stacks a second full state (Medium) | Fixed | A second marker only repeats the re-read |
| 4. Unbuildable state stored as `{}` and counted (Medium) | Fixed | No state is built for a client |
| 5. Sequence used on a failed store (Low) | Accepted (moot for clients) | Iteration 90 scope note |
| 6. Snapshot races a later write (Low) | Fixed for clients, replaced by Issue 2 below | No snapshot; the re-read happens at read time |
| 7. A full-state row per resume (Low) | Fixed (rows are tiny) | `granularity="none"` still gets a marker; accepted |
| 8. State rebuilt per client subscription (Low) | Fixed | No state is built |
| 9. Count documented as "callbacks sent" (Low) | Accepted (owner's rule) | `actor.py` resume docstring unchanged |
| 10. Edge cases of the client branch (Low) | Accepted (owner's rule) | Dead guard still at the peer branch |
| 11. Test coverage, error reporting (Low) | Partly: grant filter and subtarget covered; the rest accepted | Tests above |

## Remaining Tasks

- [ ] `/iterate_plan` on the issues below, under the owner's rule (only
      what users would meet). No known client polls
      `/subscriptions/<peer>/<sub>` today (Emm's frontend calls the actor's
      own `sync-all`), so every issue below reaches a user only through a
      client written to the new spec text; Issues 1 and 2 are where that
      text gives wrong results.
- [ ] Todos are unchanged. `grant-enforcement-per-route.md`,
      `web-ui-trust-page-gaps.md` and `full-state-fallback-replica.md`
      (now with the two peer-fallback items) keep their `INDEX.md` rows.
- [ ] Before anything is pushed: the second security plan
      (`grant-enforcement-per-route`).

## Issues Found

### Issue 1: a resume of one subtarget sends a whole-target subscriber an unscoped marker
**Severity:** Medium (wrong client data, silently, for a client that follows the spec)
**Description:**
- `resume_subscriptions("properties", "memory_travel")` resyncs every
  subscription to `properties` with `resync_subtarget = subtarget if
  subtarget else sub_subtarget` (`actor.py:4256`); the marker URL is
  built from it (`actor.py:4508`), so it is `/properties/memory_travel`.
- The per-sequence answer serves `"subtarget": sub_dict["subtarget"]`
  (`handlers/subscription.py:665`), the subscription's own (none); the
  list answer serves no scope at all.
- The guide says "The client discards its cached state for the target and
  GETs the URL" (`docs/guides/subscriptions.rst`), and the spec says act on
  it as on a resync callback, step 1 "Discard any cached state for the
  target/subtarget" (`actingweb-spec.rst:3002`). A client subscribed to all
  of `properties` drops every cached property and stores one property's
  body as all of them. A peer's resync callback carries the resumed
  subtarget (`actor.py:4598`), so peers are not affected.

**Location:** `actingweb/actor.py:4508`, `actingweb/handlers/subscription.py:665`,
`docs/guides/subscriptions.rst:263-266`, `docs/protocol/actingweb-spec.rst:3008-3013`
**Recommendation:** say in the spec and guide that a polling subscriber
discards only what the marker's `url` names (or serve the marker's own
`target`/`subtarget` with it).

### Issue 2: diffs after a marker in the same poll are applied on top of the re-read
**Severity:** Medium (duplicated list items for a merging client)
**Description:**
- `SubscriptionHandler.get` returns every pending diff
  (`handlers/subscription.py:414` `diffs = sub_with_diffs.get_diffs()`).
- A poll that returns `[marker@5, append@6, append@7]`: the re-read at poll
  time already contains 6 and 7, and the client then applies them again.
  `append`/`insert` are not idempotent. The spec text tells the client to
  act on the marker but nothing about the diffs after it. For a pushed
  callback this is a narrow race; for a polling client the window is the
  whole poll interval.

**Location:** `docs/protocol/actingweb-spec.rst:3008-3013`
**Recommendation:** spec text: a subscriber that finds a marker re-reads
once, takes the highest sequence in the batch as its own, and drops the
diffs at or below it.

### Issue 3: a marker is recognised only by this actor's current URL prefix
**Severity:** Low
**Description:**
- `handlers/subscription.py:35` `own_root = f"{config.proto}{config.fqdn}/{myself.id}/"`;
  `resync_marker_url` accepts any URL under it (`actor.py:102`
  `return url if url.startswith(own_root) else None`).
- A property value written as exactly `{"type": "resync", "url":
  "<this actor>/properties/other"}` (by the owner, or a peer with a write
  grant) is served to every subscriber of that property as a marker for a
  different resource; a spec-following client fills its cache for its
  target with another resource it may read. No leak (its own grant).
- The other way round: after `APP_HOST_FQDN` or the protocol changes,
  unread markers fall through to `_as_permitted` and are served as data
  (`{"type": ..., "url": ...}` merged as two properties), with no log.

**Location:** `actingweb/actor.py:89-102`, `actingweb/handlers/subscription.py:33-38`
**Recommendation:** match the path after `/<actor>/` against the
subscription's `target[/subtarget]` (or the resumed subtarget under it),
and rebuild the served `url` from the current config.

### Issue 4: a marker read through its own diff URL is deleted before the re-read
**Severity:** Low (a lost resync after a failed re-read)
**Description:** `handlers/subscription.py:670`
`sub_with_diffs.clear_diff(seqnr)` deletes on GET. An ordinary diff
delivers its data in that response; a marker delivers only the instruction.
If the re-read then fails, a retry of the diff URL answers 404 and the
client stays stale. The spec text names this path ("or on the diff's own
URL").
**Location:** `actingweb/handlers/subscription.py:670`
**Recommendation:** keep a marker until the acknowledging PUT, or point
polling clients at the list endpoint only in the spec.

### Issue 5: the marker URL leaves out the subscription's resource
**Severity:** Low
**Description:** `actor.py:4508` builds the URL from target and subtarget
only. A client subscribed to `properties/<p>/<resource>` is sent to `<p>`.
The resync callback has always done the same.
**Location:** `actingweb/actor.py:4508`
**Recommendation:** accept, or append the resource.

### Issue 6: a client that does not know the type stays stale with no error
**Severity:** Low (nothing shipped regresses; 3.16 is held)
**Description:** `handlers/subscription.py:40` serves `data: {}`; an old
client merges nothing and moves its sequence on. The spec text accepts this.
**Location:** `actingweb/handlers/subscription.py:40`
**Recommendation:** accept; the changelog entry already describes the
served shape.

## Overall Assessment

Iteration 90 closes reverify-13's High: a client's resync stores no data,
so nothing escapes its grant, and the merge corruption, the stacked full
states and the counted `{}` go with it. The Full tier is green on both
backends (DynamoDB 6176, PostgreSQL 5973), the docs build passes, no
recording changed, and Emm's suite matches its baseline.

What the reviews found is about the marker's context rather than its
content. A marker for one resumed subtarget goes to whole-target
subscribers without scope (Issue 1), and the spec text does not say what to
do with the diffs after it (Issue 2). Both give a client that follows the
new spec text wrong data. No known client polls subscriptions today, so
both reach users only through new clients, and both are mostly spec and
guide wording. The second security plan (`grant-enforcement-per-route`)
still comes before anything is pushed.
