# Verification: DB fault contract (Phases 1-2, PR 1), sixth run

**Date:** 2026-10-29
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 85a4deb (all Phase 1-2 work uncommitted; master is now 3c6284f
after PR #156, not yet merged into the branch)

Scope: Phases 1-2, after Iterations entries 37-41. Phases 3-4 are not
started, so the plan keeps `status: active` and no `verified:` link.

## Automated Check Results

- **Browser QA:** N/A, no page changed.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed) and a
  fresh-context Claude reviewer through outside-voice. A6-F6 below.
- **Code review (built-in, high, no `--fix`):** ten findings, unverified by
  the skill; checked here. G6 and H6 come from it; the other eight were
  already filed, accepted, or notes.
- **Security review (built-in):** no findings at confidence 8 or above. It
  confirmed the creator-change restore cannot put back a vouched marker
  after the creator changed: the restore follows a consistent re-read
  (`db/dynamodb/actor.py:68`, `consistent_read=True`) that must show the
  original creator.
- Full tier: run after entries 37-41 on this exact tree (only plan text
  changed since). ruff, ruff format, pyright clean (437 files); fast tier
  3244 passed, 23 skipped; guard 0 violations; `verify_groups.py` 50 groups;
  DynamoDB 4240 passed, 31 skipped; PostgreSQL 4129 passed, 142 skipped; no
  failures or reruns; docs build clean.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A5 resume loses the window | Fixed for transient faults; a permanent fault now pins the suspension (A6), a landed-then-raised resume still loses it (C6) | entry 37 |
| B5 creator-change marker | Fixed | entry 38; landed branch untested (E6) |
| C5 redirect and cookies on a fault | Fixed; drops a session-clearing cookie too (F6) | entry 39 |
| D5 DynamoDB overwrites a taken number | Fixed; the resync fallback ignores the refusal (B6) | entry 40 |
| E5 409 CORS on `/` | Filed for PR 2 | `thoughts/todo/creator-uniqueness-not-enforced.md` |
| F5, G5, H5, I5, J5, K5 | Fixed | entries 40-41 |

## Issues Found

### A6. One subscriber whose resync always faults keeps the target suspended forever
**Severity:** High (introduced by entry 37)
**Description:** `actor.py` `_send_resync_callbacks` puts the suspension
back and raises on *any* `DbError`. A permanent one (DynamoDB's 400 KB item
limit on the fallback full-state diff, `_store_subscription_diff`) comes
back on every attempt and answers 500 (`is_permanent`), so diff
registration stays off for every subscriber on the target.
**Recommendation:** re-suspend only for a transient fault; a permanent one
is logged as that subscriber's failure.

### B6. The resync fallback sends the URL of a diff it did not store
**Severity:** Medium
**Description:** `actor.py` `_store_subscription_diff` logs a False
`create` and returns the URL anyway. Since entry 40 DynamoDB answers False
when the number already has a diff, so the low-granularity callback points
the subscriber at another change's diff.
**Recommendation:** return "" and skip the callback.

### C6. A resume whose marker delete landed but raised still loses the window
**Severity:** Medium
**Description:** `db.resume()` in `resume_subscriptions` sits outside the
restore. A delete that committed with its answer lost raises `DbError`; the
retry finds no marker and answers 0.
**Recommendation:** on a `DbError` from `db.resume()`, put the suspension
back (best effort) before raising.

### D6. A failed HTTP resync lifts the suspension with the window lost to that subscriber
**Severity:** Medium (older than 3.16 in kind; filed)
**Description:** `_callback_subscription_resync` returns False on a
network failure or non-2xx; the suspension stays lifted. On the
resync-capable path no diff is stored at the allocated number, so a
subscriber that recovers by polling gets nothing for it. The only sign is a
lower count returned to the caller. A retry also resends to every
subscriber at a new sequence (and stores a new fallback diff each time).
**Recommendation:** document the count; file a per-subscriber resync record
in the follow-ups.

### E6. The B5 test does not cover "modify landed, then raised"
**Severity:** Low
**Description:** `tests/test_db_fault_sixth_pass.py` patches `modify` to
raise without writing, so nothing pins that a landed change keeps
`creator_changed` (the security property). The code is correct.
**Recommendation:** add a test whose `modify` writes, then raises
`DbError`.

### F6. Clearing every queued cookie also drops a session-clearing one
**Severity:** Low (no current path)
**Description:** `_errors.py` `map_db_error` sets `response.cookies = []`.
A handler that queued an expiring cookie (logout) and then faulted would no
longer clear the session. No such path today.
**Recommendation:** keep cookies with `max_age <= 0`.

### G6. A drained pending entry can be applied twice when two writes fault
**Severity:** Medium (subscriber side; filed)
**Description:** `callback_processor.py` (both twins): after the handlers
ran, a faulted `_update_last_seq` is folded and `_prune_pending` runs; if
it faults too, `last_seq` is stale and the drained entries stay pending, so
a later drain applies them again. The comment "a later read skips them
anyway" is false in that case.
**Recommendation:** correct the comment; add to
`thoughts/todo/subscription-subscriber-fault-hardening.md`.

### H6. `get_by_creator`'s default no longer re-reads each row
**Severity:** Low
**Description:** `db/dynamodb/actor.py` `get_by_creator` without
`consistent=True` returns the index projection, so a caller of the DB layer
can see a just-changed passphrase or a just-deleted actor. Before, each row
was read with `consistent_read=True`. The library's callers that act on it
pass `consistent=True` or `ids_only`; the CHANGELOG mentions the flag but
not the default's change.
**Recommendation:** a **Behavior change:** sentence.

### Notes
- `register_diffs`' list-read fault loses the change with no gap: documented
  in entry 32.
- `find_db_error` follows `__context__`; replacement and pick read costs;
  DynamoDB type hints; the create rollback's orphaned `_internal` rows: filed.
- `Actors.__init__` still fetches strictly; unchanged code, no library
  caller.
- The successor step fails a sign-in when a classified sibling is deleted
  concurrently (`oauth2.py`); fails closed, a race.
- `reason_phrase` labels any status outside its table "Service
  Unavailable"; `db_error_answer` only returns 409, 500 and 503.

## Remaining Tasks

- [ ] Fix A6-C6, E6, F6; correct G6's comment; document D6 and H6; file D6
  and G6.
- [ ] Then `/commit` (merging master, which now has PR #156), open PR 1, and
  cut `release/3.16.0-creator-uniqueness`.

## Overall Assessment

Entries 37-41 fix verification 5's findings, and the security property
behind B5 holds. Entry 37 overcorrected: treating every resync fault as
retryable turns a permanent one into a target suspended for good (A6). It
also left two edges of the same path (B6, C6). All three are small and
local to the resume path; the rest is wording, one test and two filings.
The plan stays `active` without a `verified:` link.
