# Verification: Spanned list items, Phase 3, third run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-idempotent-append
**Commit:** 18d7541, plus the uncommitted Phase 3 tree with entries 66-74

**Scope.** Entries 71-74, which answer verification 9.

## Automated Check Results

- **Browser QA:** N/A (no UI).
- **Second opinion:** outside-voice agent, providers codex and a
  fresh-context Claude reviewer. Codex finds V9-1 to V9-6 closed. Five
  findings (Claude 1 to 5; codex's one High is downgraded below with its
  reason) and 2 unverified.
- **Built-in code review** (`/code-review high`): 10 findings.
- **Built-in security review:** last run at entries 66-70 found nothing.
  Since then the changes are the public `announced` and `announce_index`
  fields, `repair_keys()` on the permission view (`write`) and the
  notifying list, and `clear()`'s key rule. None of these opens a path
  that pass did not cover.
- **Full tier**, at entries 71-74:
  - ruff, format and pyright: 0/0.
  - `verify_groups.py`: 51 documented.
  - DynamoDB: 4952 passed, 40 skipped, 1 xfailed.
  - PostgreSQL: 4760 passed, 232 skipped, 1 xfailed.
  - sphinx `-W`: pass.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-9.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| V9-1: an announcement could be lost; "exactly once" | Fixed: "at most once", public fields, back-out by key and token | entry 71 |
| V9-2: in-flight gaps in the repair and the report | Fixed | entry 72 |
| V9-3: budget exit after an adoption | Narrowed; the gap remains (V10-1) | entry 73; `test_a_budget_exit_keeps_a_head_another_call_adopted` |
| V9-4: `clear()` freed a surviving item's key | Fixed; now leaves old dangling rows (V10-5) | entry 73 |
| V9-5: small edges | Fixed, except the token normalisation in `_retire_key_row` (V10-3) | entries 72-74 |
| V9-6: documentation | Fixed | entry 74 |

## Issues Found

### V10-1. A writer can still delete a head a repeat has just adopted
**Severity:** Medium
**Sources:** Claude 1; code review 2.
**Location:** `_v2_append_once`, at the budget exit and at the loser path:
`self._retire_own_head(...)` after the last key-row read.
**Failure:** between the writer's last check and its conditional delete, a
repeat finds the head (its key row being absent or dangling), binds the
key and announces it, and the writer then deletes it. One more re-read
narrows the gap and never closes it.
**Recommendation:** make adoption change the head: mark the envelope by
compare-and-swap before binding the key. The writer deletes only by its
original bytes, so a marked head can never be deleted by it.

### V10-2. An SDK retry of an adoption's key-row create never announces
**Severity:** Low
**Source:** code review 1.
**Location:** `_find_keyed`: `if now.tok == head_tok: return
self._keyed_result(rank, raw)`, with no `by` check.
**Failure:** the adopter's own create landed and reported `False`. It stays
quiet, its writer is dead, and the item is never announced.
**Recommendation:** announce when `now.by` is this call's token.

### V10-3. Token normalisation missed in `_retire_key_row`
**Severity:** Low
**Sources:** Claude 3; code review 3.
**Location:** `named.tok == env.tok`.
**Recommendation:** compare with `(env.tok or "")`.

### V10-4. Smaller edges
**Severity:** Low
- The adoption loop gives up after two vanished rows and returns "none",
  so the caller writes another head (code review 4). Retry from the top
  instead.
- `_sweep_spans` removes a broken keyed head without freeing its key row
  (code review 5).
- `repair_keys()` lacks the connection check and leaves a stale rank cache
  (code review 7).
- `_write_spanning` builds a carried head twice (code review 10).

### V10-5. `clear()` leaves old dangling key rows
**Severity:** Low
**Source:** code review 6.
**Recommendation:** also delete rows that name no head the read saw and are
older than the in-flight window.

### V10-6. Documentation precision
**Severity:** Low
**Sources:** Claude 2, 4 and 5.
- A delete landing between a writer's head and its key row still gets that
  writer `created=True`. This is the "delete at the same moment" case the
  guide already names, and it matches plain `append()` (codex rated it
  High; downgraded for that reason). The `clear()` sentence, though,
  claims more than holds.
- A repeat after a delete returns a leftover losing copy, if one exists,
  rather than creating again.
- `announce_index` is a position in the stored list, which a subscriber
  that missed other items may not share.

Accepted, as before:
- the first call's O(heads) strong read (code review 8);
- `compact()` computing the key findings twice (code review 9).

Not taken up (Low): a slow writer whose head was adopted returns a handle
read before the mark, so one handle operation answers "changed"; it is now
documented.

## Overall Assessment

No High or Critical. V10-1 is the last mechanism-level gap. The adoption
mark closes the class rather than narrowing it again; the rest are small
and listed for one batch.
