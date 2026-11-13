# Verification: per-request actors on the MCP path, and a subscription list that caches empty (second run, 2026-11-13)

**Date:** 2026-11-13
**Plan:** thoughts/plans/2026-11-06-subs-list-cache-lifetime.md
**Research:** thoughts/research/2026-11-05-subs-list-cache-lifetime.md
**Branch:** release/3.16.0-subs-list-cache-lifetime
**Commit:** 1d761cc plus the uncommitted working tree (Iterations 8-13)

Scope: a re-run after `/iterate_plan` (the plan's Iterations 8-13, not yet
committed). It checks that change and what happened to the first 2026-11-13
run's seven issues. Phases 1-3 and Iterations 1-7 are as verified in
`thoughts/verifications/2026-11-13-subs-list-cache-lifetime.md`. Together
the two cover the whole plan, so the plan's `verified:` link moves here.
Second document of the day, hence the `-2` suffix.

## Automated Check Results

- **Browser QA:** N/A (no phase touches anything a user sees).
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`) and fresh-context Claude, on the uncommitted
  diff. Eleven findings (two dropped as already accepted); each checked
  against the tree below. The change is about 120 lines of code, so the code
  review was a direct read in this context. The security review was not
  run: no auth, input or outward path changed.
- `ruff check actingweb tests`: pass
- `ruff format --check actingweb tests`: pass
- `pyright actingweb tests`: 0 errors, 0 warnings
- `tests/integration/verify_groups.py`: pass
- `make test-all-parallel` (DynamoDB): 6,695 passed, 54 skipped, 1 xfailed
- `make test-all-parallel` (PostgreSQL): 6,491 passed, 258 skipped, 1 xfailed
- `sphinx-build -W …`: pass
- Wire step on 3.11: not re-run (no recording or wire path changed)

All of the above ran in this session on this exact working tree.

## Phase Verification

### Iterations 8-13 - VERIFIED (owner-only findings)

**Changes verified:**
- `actingweb/maintenance/deletions.py:209` re-runs `scan(config,
  actor_id)` and raises `ChangedSinceScan` unless still UNFINISHED; the loop
  prints and counts it (`:301`, `:303`). Matches Iteration 8, but uses the
  stale finding's data afterwards (Issue 1).
- `actingweb/subscription.py` `_store()` wraps the builds in
  `delete_actor_subscription_rows`, `delete_actor_diffs_and_suspensions` and
  `Subscriptions.delete()`. Matches Iteration 9.
- `delete_all_of_actor` answers True on a missing table on both backends;
  the DynamoDB query projects `id`, `subid_seqnr`. `SubscriptionDiff` has no
  version attribute, so a key-only `delete()` works (and
  `test_another_actors_diffs_stay` deletes through it). Matches Iterations
  10 and 12.
- `Subscriptions.delete(*, wipe_diffs=True)`; `actor.py:1607` and `:3487`
  pass False. Matches Iteration 12 (see Issue 4).
- `is_suspended` unchanged on both backends; the changelog and the
  protocol docstring say only clean-up treats a missing table as empty.
  Matches Iteration 11.

**Tests verified:** the nine new tests pass on both backends; all but the
coverage-only `test_another_actors_diffs_stay` failed on the unfixed code
(run in this session). Weaknesses: Issue 6.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-13-subs-list-cache-lifetime.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. resume wipes by a stale scan | Fixed for the gate; the clean-up still reads the stale finding's data (Issue 1 below) | Iteration 8; `deletions.py:209`, `:223` |
| 2. stores built outside the `DbError` wrapper | Fixed | Iteration 9; `subscription.py` `_store` |
| 3. missing diffs table fails every delete | Fixed | Iteration 10 |
| 4. "on both backends" not exact | Fixed in wording, one refinement left (Issue 5 below) | Iteration 11 |
| 5. PostgreSQL read vs clean-up on a missing table | Accepted as-is by design, documented (the 3.16 loud-read rule) | Iteration 11 |
| 6. DynamoDB wipe reads bodies, runs twice | Fixed | Iteration 12 |
| 7. no neighbour test | Fixed | Iteration 13 |

## Remaining Tasks

- [ ] Owner decision on Issues 1-7 below (none peer-reachable as Medium).
- [ ] Commit Iterations 8-13 with both 2026-11-13 verification documents.
- [ ] Emm's suite on this branch before the PR.
- [ ] Open the PR.

## Issues Found

### 1. The unfinished clean-up uses the stale finding's client ids
**Severity:** Medium (operator-only; not peer-reachable).
**Location:** `actingweb/maintenance/deletions.py:223` `ids =
finding.data.get("client_ids")`, after the re-scan at `:209`.
**Description:** if the id is created again and deleted again between the
two scans, the re-scan is UNFINISHED for the new tombstone. The clean-up
then deletes the old tombstone's client rows, marks the new one finished,
and the new one's `client_ids` rows are left with nothing to find them.
**Recommendation:** use `now[0].data`, and raise `ChangedSinceScan` when
`now[0].deleted_at != finding.deleted_at`.

### 2. "nothing left to finish" (exit 0) hides an old deletion's leftovers under a re-created id
**Severity:** Low (operator-only; needs a create under an explicit id of a
deleted actor whose deletion left rows). The outside voice rated it Medium.
**Location:** `deletions.py:301`; `actor.py:1237` (create clears only the
suspensions before the tombstone).
**Description:** a create under the id clears the tombstone and its
`client_ids`. Subscription rows or diffs a peer wrote after the last wipe
now belong to the live actor, with no trust behind them; resume reports
nothing and exits 0. This is the accepted deletion race
(`thoughts/todo/verify-orphans-subscription-tables.md`) seen from the create
side; the message overstates it.
**Recommendation:** print "id in use again; the old deletion's leftovers
were not removed", and add the create-side case to the verify-orphans todo
(or have `create(actor_id=…)` also wipe subscription rows and diffs).

### 3. "run report again" after a LEGACY re-scan leads nowhere
**Severity:** Low. **Location:** `deletions.py:303`; the bulk scan skips a
finished tombstone (`if finished and not only: continue`).
**Description:** resume exits 1 and says to run `report`, which lists
nothing for that id unless it is named.
**Recommendation:** say `report <id>` in the message.

### 4. A delete or purge that fails after the subscription rows go now leaves the diffs
**Severity:** Low. **Location:** `actor.py:1607`, `:3487`
`subs.delete(wipe_diffs=False)`.
**Description:** the diff wipe moved after the trusts. A fault in between
leaves the diffs until the next call. `delete()` is resumable (its next
call runs the wipe). `purge_relationships()` raises before its `try`, so the
caller sees the `DbError` and a repeated purge wipes them.
**Recommendation:** accept and say so in the plan, or run the purge's
`subs.delete` inside the `try` so it folds to `confirmed: False`.

### 5. Two changelog phrases not exact
**Severity:** Low. **Location:** `CHANGELOG.rst:956` "one key-only query"
(paged: several on a large actor); `:965` "still raises ``DbError``" (on
DynamoDB with auto-creation on, the constructor creates the table and the
check answers "not suspended").
**Recommendation:** "a key-only query (paged)"; "(on DynamoDB, when
auto-creation is off)".

### 6. Test precision
**Severity:** Low.
**Location:** `tests/test_subscription_list_memo.py`
`test_a_raw_error_building_a_store_is_a_dberror` (two calls in one
`pytest.raises`), `test_a_delete_wipes_the_diffs_once` (docstring says
"after the trusts", asserts only the count), `_missing_table_patch` (raises
`TableDoesNotExist` from `query`, where a real query raises `QueryError`
with `cause_response_code`; PostgreSQL patches `get_connection`, not the
statement); `tests/test_deletions_command.py` (no test of the exit-1
`now <state>` branch).
**Recommendation:** one `pytest.raises` per call with the cause asserted;
raise `QueryError` with the response code; a test for the exit-1 branch.

### 7. `is_resource_not_found` falls back to text matching
**Severity:** Low. **Location:** `actingweb/db/dynamodb/property_lookup.py:91-92`,
used by the diff and suspension clean-ups.
**Description:** an unrelated error whose text says "ResourceNotFound"
would be taken for a missing table and the clean-up would answer True.
Pre-existing helper, now on one more path.
**Recommendation:** match `cause_response_code` and the
`TableDoesNotExist` type only on the clean-up paths.

### Unverified notes
- PostgreSQL `UndefinedTable` also covers a wrong schema or prefix; in a
  deletion an earlier strict read on the same schema fails first.

## Overall Assessment

The seven issues of the first 2026-11-13 run are addressed: six fixed, and
Issue 5 accepted by design (a suspension check keeps raising on a missing
table, the 3.16 rule) with the wording to match. Both backends pass the full
tier. No peer-reachable Medium or higher was found, so under the stop rule
this run is clean.

One operator-only Medium remains: the `actingweb-deletions resume`
clean-up re-checks the state but still reads the client ids from the
stale scan (Issue 1), a two-line fix. The rest are Low: messages,
changelog precision, test precision, and the diff wipe's new position.
Whether to take Issue 1 (and any Lows) before committing and opening the
PR is the owner's call. Emm's suite still runs before the PR.
