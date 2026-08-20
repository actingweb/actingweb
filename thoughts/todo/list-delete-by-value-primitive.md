# A list has no way to delete an item by *what it is*, only by where it sits

**Status:** Open — unscheduled. **Superseded in scope on 2026-08-20**: see
[`thoughts/research/2026-08-20-v2-positional-access-cost.md`](../research/2026-08-20-v2-positional-access-cost.md),
which establishes that this is a *special case* of a larger fix and should be
built on it rather than beside it. Read that first; this file is the narrower
proposal it grew out of.
**Came out of:** the 2026-08-19 consumer incident recorded in
[`dynamodb-known-next.md`](dynamodb-known-next.md) ("Consumer incident
2026-08-19"), where it was the strongest remedy suggested and had nowhere of
its own to live.
**Closes two threads at once:** the positional-read cost of item 2 there, and
the index-skew corruption class that produced the 2026-07-19 neighbour
destruction (`thoughts/research/2026-08-07-property-list-index-integrity.md`).

## What the research changed

`remove_where` is `items_with_handles()` + match in memory + `delete_by_handle`.
The research names the general form: **v2 already has stable per-item identity —
the rank — and the public API hides it**, so every mutation re-derives a fragile
handle (a position) from a stable one, and re-derivation is the whole-list read.
Exposing the rank as an opaque handle removes the cost *and* makes the
position-vs-storage-index skew unrepresentable.

Two constraints the sketch below did not account for, both now established:

- **`BatchWriteItem` cannot express conditions**, so a batch delete built on it
  gives up the concurrency guarantee `_v2_pop` exists to keep.
  `TransactWriteItems` can, but is all-or-nothing across 100 actions / 4 MB.
- **A rank is unique only within a list generation.** After `delete()` +
  `append()`, `generate_n_keys_between(None, None, n)` is deterministic, so the
  new list's first rank is also `a0` — `property_list.py:2343-2352` documents
  this in the migration rollback. Any handle must be mutated **conditional on
  the bytes read**, never by rank name alone.

## The gap

`ListProperty` addresses items by **position**: `__getitem__`, `__setitem__`,
`__delitem__`, `pop`. Consumers do not think in positions. They hold an id — a
memory id, an output id, a run id — and want the row carrying it gone. So every
consumer writes the same three-step dance:

1. read the list,
2. scan it for the record whose `id` matches,
3. translate that to an index and delete by index.

Steps 2 and 3 are where both defects live.

## Why it is worth a primitive rather than better consumer code

**The index that escapes step 3 is a loaded gun.** Positions and storage
identity coincided under v1 only while the list had no holes; the moment one
appeared, every index past it addressed its neighbour, and a write destroyed
that neighbour. That is a measured production data loss, not a hypothetical,
and the reference consumer now carries a `to_indexed_items()` /
`to_items()` distinction, a docstring explaining it, and a dedicated test file
(`test_sparse_index_addressing.py`) purely to keep the two apart. All of that
exists because an index has to travel from a read to a write. A value-addressed
delete means no index is ever derived, so none of it is needed.

**Step 1 is the cost.** After the consumer's 2026-08-19 fix, a *k*-id delete is
still ~2·*k* whole-list reads: one range query to locate each id, plus the
forced rank-cache reload inside `_v2_delitem`. Fine at hundreds of rows. It is
the next wall, and it is the wall this removes — one range read resolves every
id in the batch at once.

## Sketch

The substrate is already there, which is the main argument for doing it:

- **Resolution** is one range read. `_v2_load_full()` already returns sorted
  `(rank, raw_value)` pairs in a single query, and the rank *is* the storage
  identity under v2 — no position need be computed at any point.
- **The delete is already conditional.** `delete_if_value_equals` exists on
  both backends, is in `DbPropertyProtocol`, and `_v2_pop` already uses it in
  exactly the shape wanted: resolve, read, delete conditional on the value
  being unchanged, retry on a conditional failure because "changed" and
  "already gone" mean the same thing to the caller.

So `remove_where` is mostly composition:

```
remove_where(key, value, *, first_only=False) -> int   # rows removed
```

one `_v2_load_full()`, match `item.get(key) == value` in memory, then one
`delete_if_value_equals` per match against the matched rank's raw value, with
`_v2_pop`'s re-resolve-and-retry loop around it. Cost: **1 range read + k
conditional deletes**, against today's *k* × (range read + range read + delete).

## Open questions — none of these are decided

- **Matching contract.** `key`/`value` equality is what every known consumer
  needs (`id`), but a predicate is not expressible across the wire and a
  general query language is not wanted. Is a single top-level key enough?
- **Duplicates.** `first_only` vs "remove all matches" — and what a duplicate
  `id` even means, given the consumer treats it as unique. Returning the count
  lets the caller notice rather than forcing a choice.
- **v1.** It could be implemented positionally under v1 (locate, `__delitem__`,
  eat the shift) or refused. Prod is 730/730 format 2 and new lists are born
  v2, so refusing is defensible and much simpler — but it is a public API and
  the library does not otherwise refuse on format.
- **The sibling on the write side.** `update_where` has the same argument and
  the same skew exposure. Worth designing together even if only one ships.

## What this does not fix

- The per-partition read amplification — that is
  [I0](property-fetch-reads-whole-partition.md), a different query.
- Bulk *raw* deletes (`clear()`/`delete()`), which want `batch_write` —
  item 1 of the register. `remove_where` deleting k rows would still be k
  serial conditional deletes, and conditional writes cannot be batched, so the
  two do not overlap as much as they look like they should.
- `ListAttribute`, which still has the pre-3.13 shift design entirely
  ([`attribute-list-shift-design.md`](attribute-list-shift-design.md)). If the
  v2 port there happens first, this primitive should be designed to port with
  it rather than twice.
