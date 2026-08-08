# TODO: an interrupted `ListProperty.__delitem__` leaves a permanent hole and an inflated `length`

> **Verified 2026-08-07 — read `thoughts/research/2026-08-07-property-list-index-integrity.md`
> before acting on this file.** The mechanism is real and was reproduced, but
> three claims below are wrong: the trigger does **not** require a process death
> (two no-crash paths measured against real DynamoDB), `length > readable` is
> **not** a reliable fingerprint (roughly half of interruptions leave an
> invisible duplicate instead), and the damage is **not** contained by the
> consumer-side fix (ActingWeb's own `/properties/{name}/items` API has the same
> pairing). The proposed fix "update `length` first" was measured to make things
> worse. A separate, unreported bug — `insert()` is broken on DynamoDB and
> destroys data on every call into a non-empty list — was found while verifying.
>
> **Re-verified 2026-08-08 —
> `thoughts/research/2026-08-08-property-list-index-integrity-review.md`**
> independently reproduced every measured claim (fake harness + real
> dynamodb-local), confirmed all code citations, and found a fourth no-crash
> formation path (stale metadata cache / concurrent mutation — no locking
> exists) plus the same shift design in `ListAttribute`.

**Date:** 2026-08-05
**Status:** Open in the library as of 3.13.0rc4. The *consequence* that destroyed
user data was fixed downstream in `actingweb_mcp` (#242, v2026.08.02) by
addressing storage indices instead of compacted ones — so the damage is
contained, but the hole-forming mechanism here is untouched.
**Severity:** Medium. Rare trigger (needs a process death mid-delete), but the
effect is **permanent and self-propagating**: the list logs an ERROR on every
read forever, `length` stays one too high forever, and nothing in the library
can repair it. Was High until the consumer-side fix — it silently destroyed a
user-visible document in production.
**Origin:** Production forensics in `actingweb_mcp` — two holed lists on one
actor, one Self-Review output permanently overwritten and unrecoverable. Full
analysis: `actingweb_mcp/thoughts/research/2026-07-28-run-records-index-skew.md`.
**Owner:** unassigned

## Summary

`__delitem__` (`actingweb/property_list.py:306-355`) deletes the target row and
then shifts every later row down one, as a loop of **separate, non-transactional
writes with no rollback**, and updates `length` **last**:

```python
# actingweb/property_list.py:306
prop.set(actor_id=..., name=self._get_item_property_name(index), value=None)

for i in range(index + 1, length):
    item_value = item_db.get(actor_id=..., name=self._get_item_property_name(i))
    if item_value is not None:
        move_db.set(actor_id=..., name=self._get_item_property_name(i - 1), value=item_value)
        delete_db.set(actor_id=..., name=self._get_item_property_name(i), value=None)

meta = self._load_metadata()
meta["length"] = length - 1     # only now
self._save_metadata(meta)
```

Deleting item *i* from a list of *n* costs `1 + 3 × (n − i − 1)` sequential
round trips. Any interruption inside that window — Lambda timeout, throttle,
container recycle — leaves the list permanently inconsistent, and the caller
gets no signal because the process is already gone.

## What an interruption leaves behind

| Interrupted at | Residue |
| --- | --- |
| After the target delete, before any shift | One absent row at *index*; `length` one too high |
| Mid-shift | One absent row at the interruption point; every row above it un-shifted; `length` one too high |
| Between `move` to *i−1* and `delete` of *i* | An **exact duplicate** at *i−1* and *i*; `length` one too high |

All three share one fingerprint: **`length` is one greater than the number of
readable rows.** That is the signature to look for.

## Why it never heals

1. **`to_list()` hides it.** It iterates `range(length)` and `continue`s past any
   unreadable row (`property_list.py:433-445`), returning a *compacted* list. The
   caller cannot tell a slot was skipped — the only trace is the log line
   `Error loading list item N: List item at index N not found in database`,
   emitted on every single read for the life of the list.
2. **`__delitem__` steps over holes rather than repairing them.** The shift loop
   skips absent rows (`if item_value is not None`), so a later delete *migrates*
   the hole down a slot instead of closing it.
3. **Nothing ever recomputes `length`.** It is only ever incremented by `append`
   and decremented by a completed `__delitem__`, so the off-by-one is permanent.

## Production evidence (measured, `actingweb_mcp`)

One actor, swept across all 43 property lists: 41 intact, **2 holed**.

```
run_records        : metadata length 202, to_list() returned 201, missing slot 111
output_improvement : 33 slots, 32 readable,                      missing slot 11
```

Both holed lists are the actor's two **longest** — the most shift operations per
delete, so the most exposure. The `output_improvement` error line is already
present in the oldest retained CloudWatch event (2026-07-06 10:09 UTC, 30-day
retention), so that hole predates the retained window and its formation can no
longer be measured. No swallowed-exception lines appear in the retained logs,
which is consistent with a hard timeout mid-shift — that leaves no log line at
all.

**Treat the interrupted-delete chain as inferred, not observed.** No one has
watched a hole form. It is the only mechanism whose residue matches what was
measured, including the `length`-off-by-one that a lost-update race cannot
produce.

### What it cost, before the consumer fix

A consumer that read `to_list()`, `enumerate()`d it, and passed the position
back to `__setitem__` / `__delitem__` — which address **storage** — wrote one
slot too low for every item past the hole. In production that overwrote a
neighbouring document with a copy of the item being edited, left the intended
item unchanged, and returned success. One Self-Review output was destroyed this
way and is unrecoverable.

That is fixed on the consumer side, but the library still hands out a compacted
list from an API whose sibling methods address storage. The next consumer to
pair them will rediscover it.

## Proposed fix

Near-term, in the library:

1. **Make the shift crash-safe, or make it repair.** Either update `length`
   *first* and treat a trailing absent row as benign, or replace the row-by-row
   shift with a single rewrite of the affected range. Downstream, `run_records`
   already abandoned row-by-row deletion for a wholesale rewrite for exactly
   this reason — that fix belongs here, not in every consumer.
2. **Stop compacting silently.** Give callers a `to_indexed_list()` (index,
   value) — `actingweb_mcp` had to build this as `to_indexed_items()` in its own
   accessor to fix the skew, which is a library concern leaking into consumers.
   At minimum, `to_list()` should be documented as lossy and pointed at the
   indexed variant.
3. **Add a repair primitive.** `verify()` / `compact()` that recomputes `length`
   from the readable rows and closes holes in one rewrite. There is currently
   **no supported way to repair a holed list** — the two production lists above
   still need it, and any fix ships without a remediation path until this exists.

Durable direction (its own cycle): stop addressing list items positionally.
Stable ids inside the row plus find-and-update removes this entire class of
bug — positional addressing over a non-transactional store is the root of it.

## Test notes

`actingweb_mcp/tests/repositories/test_sparse_index_addressing.py` already has a
fake that reproduces the real shift loop including its skip over absent rows,
and the pattern worth copying: seed a list, punch a hole, address an item after
it, then assert **both** that the intended item changed *and* that its
neighbour is byte-identical. Without the neighbour assertion the test passes on
the buggy code too.

A library-side test should additionally interrupt the shift partway and assert
the list is still readable, `length` matches the readable rows, and no duplicate
was left at the boundary.
