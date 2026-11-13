# Verification: per-request actors on the MCP path, and a subscription list that caches empty (re-run)

**Date:** 2026-11-13
**Plan:** thoughts/plans/2026-11-06-subs-list-cache-lifetime.md
**Research:** thoughts/research/2026-11-05-subs-list-cache-lifetime.md
**Branch:** release/3.16.0-subs-list-cache-lifetime
**Commit:** 1d761cc

Scope: a re-run after `/iterate_plan` (the plan's Iterations 1-7, commit
`1d761cc`). Phases 1-3 were verified on 2026-11-12 and are unchanged except
where those iterations touched them. This run checks that commit and the
fate of the previous run's ten issues. It covers the whole plan, so the
plan's `verified:` link moves here.

## Automated Check Results

- **Browser QA:** N/A (no phase touches anything a user sees).
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`) and fresh-context Claude (Opus 5.5), on
  `git show 1d761cc`. Seven findings and one unverified note; each was
  checked against the tree (see Issues Found). The built-in code review was
  not run as a separate pass: the change is about 150 lines of code, so it
  was read directly in this context, along with every caller of
  `Subscriptions.delete()`, the PostgreSQL pool's rollback on exit, and the
  DynamoDB diff hash key. The security review was not run again: the change
  touches no auth, input handling or anything that leaves the process
  (deletion clean-up and store fault folding only), so the 2026-11-12
  security review still applies.
- `ruff check actingweb tests`: pass
- `ruff format --check actingweb tests`: pass (560 files)
- `pyright actingweb tests`: 0 errors, 0 warnings
- `tests/integration/verify_groups.py`: pass (43 groups; wire rows
  consistent; Wire-Phase trailers match)
- `make test-all-parallel` (DynamoDB): 6,686 passed, 54 skipped, 1 xfailed
- `make test-all-parallel` (PostgreSQL): 6,483 passed, 257 skipped, 1 xfailed
- `sphinx-build -W …`: pass
- Wire step on Python 3.11 (`.venv311`): 320 passed on each backend

Both suites, the docs build and the 3.11 wire step ran in this session on
the tree committed as `1d761cc`, with nothing changed since. Lint, format,
pyright and `verify_groups` ran again for this document.

## Phase Verification

### Phase 1: the MCP path builds its actor per request - VERIFIED

Unchanged since 2026-11-12. `1d761cc` touches only changelog wording about
it (Issues 4-5); the wording now matches `handlers/mcp.py`.

### Phase 2: the subscription list memo, its sibling, the clean-up, the accessor - VERIFIED (with owner-only findings)

**Changes verified (commit `1d761cc`):**
- `actingweb/subscription.py:329` `clear_actor_suspensions`: re-raises
  `DbError`, turns any other exception into `DbError("suspension clear")`,
  and raises when the store answers False. Matches Iteration 1.
- `actingweb/actor.py:1236-1238`: suspensions are cleared before
  `clear_actor_tombstone(..., strict=True)`, inside the same `except DbError`
  rollback. Matches Iteration 2.
- `actingweb/maintenance/deletions.py:197-198`: the UNFINISHED branch wipes
  rows, diffs and suspensions by actor id. Matches Iteration 3 (see Issue 1
  below for the stale-scan question).
- `actingweb/db/dynamodb/subscription_diff.py:225` and
  `actingweb/db/postgresql/subscription_diff.py:403` `delete_all_of_actor`.
  DynamoDB queries the hash key `id` (the actor id; pynamodb paginates).
  PostgreSQL runs one `DELETE … WHERE id = %s`. Both are in the protocol
  (`db/protocols.py`). `Subscriptions.delete()` (`subscription.py:291`) uses
  it. Every caller (`actor.py:1606` deletion, purge, `oauth2.py:2895`
  adoption, `deletion_finish.py:255`) wipes the whole actor, so deleting by
  actor id removes nothing that should have stayed. Matches Iteration 4.
- `actingweb/db/postgresql/subscription_suspension.py:164`: `UndefinedTable`
  answers True. The pool's `connection()` context rolls back on exit, so no
  aborted transaction leaks. Matches Iteration 5.

**Tests verified (all pass on both backends):**
- `tests/test_subscription_list_memo.py:914`
  `test_a_failed_clear_keeps_the_deleted_actors_tombstone` (Issue 2)
- `:944` `test_an_error_building_the_store_rolls_the_create_back` and `:965`
  `test_an_error_building_the_store_stops_a_delete_with_503` (Issue 1)
- `:1092` `test_a_missing_postgresql_table_holds_no_suspension` (Issue 10)
- `:1106` `test_the_diff_wipe_reads_no_diff` (Issue 8)
- `tests/test_deletions_command.py:124`
  `test_what_a_late_subscriber_left_goes_too` (Issue 3)

**Deviations from plan:** none beyond those recorded in Iterations 1-7.

### Phase 3: documentation, changelog and records - VERIFIED (two Low wording findings)

The changelog, migration guide, subscriptions guide and caching guide
corrections (Issues 4-7) are in place. Issues 4 and 5 below are wording that
the new code makes slightly too strong.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-12-subs-list-cache-lifetime.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Suspension store constructor raises a non-`DbError` | Fixed | `subscription.py:329-341`; Iteration 1; tests `:944`, `:965` |
| 2. A failed explicit-id create loses the tombstone | Fixed | `actor.py:1236-1238`; Iteration 2; test `:914` |
| 3. `actingweb-deletions` UNFINISHED skips the wipes | Fixed (new owner-only edge, Issue 1 below) | `deletions.py:197-198`; Iteration 3; `test_deletions_command.py:124` |
| 4. Changelog: "never creates the actor" | Fixed | Iteration 6 |
| 5. Changelog: "every instance … one request" | Fixed | Iteration 6 |
| 6. Changelog: "after a trust call that sent a request" | Fixed | Iteration 6 |
| 7. Caching guide shows the removed pattern | Fixed | `docs/guides/caching.rst`; Iteration 6 |
| 8. Diff wipe reads every diff body | Fixed on PostgreSQL. On DynamoDB the reads are now by key with no per-subscription pass, but the query still returns full items (Issue 6 below) | `subscription.py:291`, `:347`; Iteration 4 |
| 9. Wire tests lack type hints | Fixed | `tests/integration/test_wire_queue_and_lifecycle.py`; Iteration 7 |
| 10. PostgreSQL without the suspensions table fails deletes | Fixed for deletes and creates (reads: Issue 5 below) | `postgresql/subscription_suspension.py:164`; Iteration 5 |

The accepted items (the deletion race, filed as
`thoughts/todo/verify-orphans-subscription-tables.md`) are unchanged.

## Remaining Tasks

- [ ] Owner decision on Issues 1-3 below. All are owner- or operator-only;
  none is peer-reachable. Under the stop rule they do not block.
- [ ] Emm's suite on this branch before the PR (the plan changes library
  code). Emm's `api/trust_unified.py:845` comment describes the old falsy
  guard.
- [ ] Open the PR (one PR for the plan).

## Issues Found

### 1. `actingweb-deletions resume` wipes by a stale "row gone" scan
**Severity:** Medium (operator-only; not peer-reachable). Found by codex and
Claude in the outside voice; confirmed.
**Description:** `_finish_one` acts on the `UNFINISHED` state from `scan()`
and does not read the actor row or the tombstone again. Suppose
`Actor.create(actor_id=X)` lands between the scan and the finish. The create
clears X's tombstone (and, since Iteration 2, its suspensions first). The
resume then deletes the live actor's subscription rows, diffs and
suspensions. `deletion.mark_finished` answers True when the tombstone is gone
(`deletion.py:569-570` "if current is None: return True"), and the actor is
listed as finished, so the operator runs `actor_deleted_complete` clean-up
for a live actor. The client-row delete at `deletions.py:200`
(`_delete_actor_clients(..., actor_deleted=True)`) already had this shape
before 3.16. The new wipes widen what such a run removes.
**Location:** `actingweb/maintenance/deletions.py:186` "if finding.state ==
UNFINISHED:", `:197-198`
**Recommendation:** at the top of the UNFINISHED branch, re-read the
tombstone and the row strictly. Skip (report "re-created") if the tombstone
is gone or the row is back. Add a test with a create between scan and
finish.

### 2. The new helpers build the diff and subscription stores outside the `DbError` wrapper
**Severity:** Medium (operator/backend fault; not peer-reachable). Confirmed.
**Description:** `delete_actor_subscription_rows` (`subscription.py:324`
"rows = get_subscription_list(config)") and
`delete_actor_diffs_and_suspensions` (`:347`
"get_subscription_diff_list(config).delete_all_of_actor(actor_id)") build
their DynamoDB stores outside any try. Each constructor calls
`ensure_table`, which with auto-creation on lets a raw `exists()` or
`create_table` error through (`db/dynamodb/_ensure.py:95-97`). This is
Issue 1's fault class on two more stores. In `actingweb-deletions resume`
the loop catches only `DbError` (`deletions.py:276`). So one raw error stops
the whole run, skips `_purge_expired`, and loses the printed list of actors
already finished in that run. Purge's
`except DbError` (`actor.py:3491`) lets the same raw error through. Delete
and explicit-id create were already exposed to this through the stores' own
construction before this plan.
**Location:** `actingweb/subscription.py:324`, `:347`
**Recommendation:** build both stores under the same
`except Exception → DbError` that `clear_actor_suspensions` uses.

### 3. A missing DynamoDB diffs table now fails every actor delete
**Severity:** Low (a deployment that manages tables externally and never
provisioned the diffs table; not peer-reachable). Confirmed.
**Description:** on master the diff table was touched only when the actor
had subscriptions. On this branch every delete, purge and UNFINISHED resume
calls `delete_all_of_actor` (`subscription.py:347`), and on DynamoDB a
missing table raises `DbError` (`db/dynamodb/subscription_diff.py:229-232`).
That is a 503 on every delete, where the suspensions table is treated as
empty under the same condition.
**Location:** `actingweb/db/dynamodb/subscription_diff.py:225-233`
**Recommendation:** answer True on `is_resource_not_found` (DynamoDB) and
`UndefinedTable` (PostgreSQL), as for suspensions; or document the table as
required.

### 4. "A missing suspensions table counts as holding none, on both backends" is not exact on DynamoDB
**Severity:** Low. **Location:** `CHANGELOG.rst:961`
**Description:** with auto-creation on and `CreateTable` denied, the store
cannot be built. Since Iteration 1 that is a `DbError`: a delete answers 503
and an explicit-id create rolls back.
**Recommendation:** qualify the sentence: on DynamoDB, when the store can be
built.

### 5. On PostgreSQL only `delete_all` treats a missing suspensions table as empty
**Severity:** Low. **Location:**
`actingweb/db/postgresql/subscription_suspension.py` `is_suspended`
("raise DbError(\"subscription suspension read\" …)")
**Description:** a schema without the table can now create and delete
actors, but every suspension check still faults. That is the behaviour
before 3.16 for reads, and it is not stated.
**Recommendation:** answer False on `UndefinedTable` in `is_suspended`, or
say in the changelog that only clean-up tolerates the missing table.

### 6. DynamoDB diff wipe: full items returned, and run twice per delete
**Severity:** Low (cost only).
**Location:** `actingweb/db/dynamodb/subscription_diff.py:229`
"SubscriptionDiff.query(actor_id, consistent_read=True)" (no projection);
`actor.py:1606` `subs.delete()` and the leftovers wipe after the trusts both
call `delete_all_of_actor`.
**Description:** "unread" (`CHANGELOG.rst:956`) is exact on PostgreSQL. On
DynamoDB the diff bodies are still read as query capacity, and a delete of an
actor with subscriptions queries the diffs twice.
**Recommendation:** project the keys only (`attributes_to_get`), and soften
"unread" to "without reading them one subscription at a time" or similar.

### 7. No test shows `delete_all_of_actor` leaves another actor's diffs
**Severity:** Low (test coverage).
**Location:** `tests/test_subscription_list_memo.py:1123` (one actor only);
`tests/test_subscription_core.py:546` (mock).
**Recommendation:** a two-actor test on real storage, both backends.

### Unverified note (outside voice)
- `create(actor_id=…, replace_holder=…)`: on a failed suspension clear the
  row is kept (`actor.py:1244` "if replace_holder is None:"), and with the
  new order so is the tombstone, which would leave a live actor under a
  tombstone. No library caller combines the two arguments; not reproduced.

## Overall Assessment

All ten issues from 2026-11-12 are addressed, each with a regression test or
a corrected text. Both backends pass the full tier, and the wire step passes
on Python 3.11. The plan is complete and correct for every peer-reachable
path. No peer-reachable Medium or higher remains, so under the stop rule this
run is clean.

The second opinion found two Medium issues and five Low ones, all
owner- or operator-only. The two Mediums (Issues 1 and 2) both sit in the new
`actingweb-deletions resume` clean-up. A resume can act on a stale scan and
wipe a re-created actor's subscription data. A raw store-construction error
can stop a run and lose its list of finished actors. Both are small, local
fixes. Whether to make them before the PR is the owner's call. Emm's suite
still has to run before the PR.
