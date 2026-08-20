# Research: how the library should answer v2's positional-access cost

**Date:** 2026-08-20
**Branch:** research/v2-positional-access-cost
**Commit:** aaf101f

## Research Question

The v2 (fractional rank key) list format made every positional access cost a
whole-list range Query. A consumer took a production outage from it on
2026-08-19. Consumers cannot fix it — the cost is inside the library. What
should the library do?

## Summary

**v2 already has stable per-item identity. The public API hides it, and that is
the whole cost.** `to_indexed_list`'s own docstring states the position:

> *"v2: storage identity is the row's rank key, NOT its position — `index` here
> is purely positional (`0..len-1`, derived from rank sort order), and every
> mutation method translates position → rank internally."*
> — `actingweb/property_list.py:1338-1341`

That translation is the expense. A rank is stable under concurrent mutation
(inserting elsewhere does not renumber it) — which is exactly what a position is
*not*. So every mutation re-derives a fragile handle from a stable one it
already had, and re-derivation means reading the whole list. `_v2_getitem`,
`_v2_setitem` and `_v2_delitem` therefore call
`_v2_ensure_rank_cache(force=True)` before acting, and the force is correct: a
cached *position* goes stale the moment another writer inserts earlier.

The consequence, measured by the consumer against production: one 81-row list
costs **241 RCU** to read, a keys-only projection saves **nothing**, and a k-item
positional batch costs k whole-list reads. Their `memory_delete` runs ~3 such
reads per id with no batch cap.

The fix that removes the class rather than shaving it is to **expose the rank as
an opaque handle** and offer conditional mutate-by-handle. Then a batch is one
range read plus k point writes, no position is ever derived, and the
position-vs-storage-index skew that destroyed a production row on 2026-07-19
becomes unrepresentable. Two constraints shape it: `BatchWriteItem` **cannot do
conditional writes**, and a rank is only unique *within a list generation* —
delete-and-recreate resets the rank space deterministically, which
`_v2_migrate`'s rollback already guards against by deleting conditional on
value (`property_list.py:2343-2352`). Both point the same way: a handle must be
mutated conditionally on the bytes that were read, never by rank name alone.

## Detailed Findings

### What the forced reload is actually for

`_v2_ensure_rank_cache(force=True)` guards a real race, documented at
`property_list.py:738-743`: a cached rank at position *i* still exists after
another writer inserts earlier, so the missing-row fallback never fires and a
stale read returns the item that *used* to be there. The force is not
defensive over-caution; it is what makes positional addressing correct at all
under v2.

This is why the cost cannot be cached away. It is intrinsic to *positions*, not
to the storage format.

### Rank stability, and its one boundary

A fractional rank is stable for the lifetime of the row: inserts elsewhere
generate keys between neighbours and never renumber existing ones. That is the
property positions lack.

The boundary is **list generation**. `property_list.py:2343-2352` records it
precisely, in the migration rollback:

> *"An unconditional delete by name would then destroy the successor's item and
> leave its metadata intact"* — because after a `delete()` and a fresh
> `append()`, `generate_n_keys_between(None, None, n)` is deterministic and the
> new list's first rank is also `a0`.

So a handle is not a global identity; it is an identity within one list
generation. Any API taking a handle must be conditional on the value read, which
is what `_v2_pop` (`:1349-1397`) and the rollback already do via
`delete_if_value_equals`. That primitive is on both backends and in
`DbPropertyProtocol`.

### The external constraints

From the DynamoDB API reference:

- **`BatchWriteItem` cannot express conditions** — *"you cannot specify
  conditions on individual put and delete requests"*. 25 items / 16 MB. Parallel
  execution *"consumes the same number of write capacity units"*, so it buys
  round trips, not capacity.
- **`TransactWriteItems` can** — `Delete` takes *"an optional condition
  expression that must be satisfied for the deletion to succeed"* — but is
  capped at 100 actions / 4 MB aggregate and is all-or-nothing, so one
  concurrently-modified row fails the whole batch.

A batch of conditional deletes therefore has no single-call form that is both
conditional and forgiving. k point writes, issued concurrently where the caller
allows, is the shape that keeps the guarantee.

### Where the cost actually lands (consumer measurements)

Reproduced from `actingweb_mcp/thoughts/research/2026-08-20-v2-list-read-cost.md`,
measured against production:

| Fact | Value |
| --- | --- |
| one 81-row list, range read, consistent | **241 RCU** |
| same, keys-only projection | **241 RCU** (no saving) |
| same, eventually consistent | 120.5 RCU |
| the actor's *entire* 1,190-row partition | 254 RCU |
| largest list, bytes in one page | **964 KB** (94% of the 1 MB Query limit) |

Two things follow for the library. `keys_only=True` in
`_v2_ensure_rank_cache` is a false economy on DynamoDB — capacity is charged on
items read, before projection — so the rank scan costs the whole list's bytes,
and the code comment calling it *"one keys-only range query"* reads as cheap
when it is not. And the "exactly one range query" invariant the v2 read design
rests on has a ceiling a real production list is already at 94% of; past 1 MB it
becomes N sequential queries (correctly — PynamoDB follows `LastEvaluatedKey` —
but N then multiplies against k).

## Candidate Solutions, Evaluated

### A. Expose the rank as an opaque handle, mutate conditionally

`items_with_handles() -> [(handle, item)]` from one `_v2_load_full()`, where the
handle carries the rank and the exact bytes read. Then
`delete_by_handle(handle)` / `update_by_handle(handle, item)` resolve to
`delete_if_value_equals` / a conditional put on `_v2_item_name(rank)` — **no
reload, no position, no translation**.

- **Cost:** 1 range read + k point writes for a k-item batch, against k whole-list
  reads today.
- **Correctness:** strictly better than positions. The conditional check gives
  the same guarantee `_v2_pop` has, and the generation boundary is handled by it
  rather than by hoping.
- **It also retires a bug class.** No caller can derive an index that outlives
  the read it came from, which is the 2026-07-19 neighbour-destruction shape and
  the reason the consumer maintains a `to_indexed_items` / `to_items`
  distinction, a docstring explaining it, and a dedicated test file.
- **Cost to build:** the primitives all exist (`_v2_load_full`, `_v2_item_name`,
  `delete_if_value_equals`, `_v2_pop`'s retry shape). What is missing is the
  public surface and the v1 answer.
- **Open:** what a handle is on a **v1** list. Options: refuse (prod is
  730/730 v2 and new lists are born v2), or synthesise from the index and accept
  that it is only as good as a position.

### B. `remove_where(key, value)` — currently filed as INDEX row 15

A value-addressed delete. **This is a special case of A**: `remove_where` is
`items_with_handles()` + match in memory + `delete_by_handle`. Worth keeping as
a convenience because it is the shape consumers actually want (they hold an
`id`), but it should be built on A rather than beside it. Row 15 predates this
analysis and should be re-pointed.

### C. `last_rank` hint in the meta row — makes `append` O(1)

Every append currently pays one whole-list range read to find the tail, because
`_v2_append` needs the last rank and the instance is nearly always cold.
`_v2_touch_metadata()` already re-reads and rewrites the meta row on every
mutation, so carrying a `last_rank` there is close to free.

- **Failure modes:** a stale hint (another appender moved the tail) or a hint
  pointing at a deleted tail. Both surface as a `create_if_not_exists`
  collision, which is **already the retry path** — fall back to the forced range
  read on collision.
- **Status: plausible and cheap, not verified.** The retry loop's exact
  behaviour under a bad hint has not been traced.

### D. `consistent_read` opt-out on `get_range`

Measured 2×. `get_range` serves both pure reads (`to_list`, `__iter__`,
`slice`, `to_indexed_list`) where eventual consistency is fine, and the rank
cache feeding positional writes, where a stale rank means touching the wrong
row. The split is **per call site**, so it needs a parameter on `get_range` and
`DbPropertyProtocol`. Note this becomes far less interesting under A, which
removes most of the reads rather than halving them.

### E. Cache `ListProperty` instances per store — **evaluated and rejected**

Tempting, and `AttributeListStore` (`attribute_list_store.py:87-93`) already
caches this way. It does not transfer.

`ActorInterface.property_lists` memoizes the store
(`interface/actor_interface.py:304-316`), and `handlers/mcp.py` caches
`ActorInterface` under a **5-minute TTL renewed on every access**
(`:52`, `_cache_ttl = 300`). For an active actor the store can live indefinitely
across requests. A cached `ListProperty` carries `_meta_cache` and
`_v2_rank_cache`, so:

- the positional paths force a reload regardless — caching **gains them nothing**;
- `len()`, `to_list()`, `append()` have no forced refresh — caching would let
  them read a rank cache minutes old, in a later request, in a different logical
  operation. A stale rank feeding `append()` generates against a tail that moved.

Unsafe where it helps, useless where it is safe. `ListAttribute` is exempt only
because it has no rank cache to go stale.

### F. Restore a stored count for `len()` — evaluated, narrow

v2 deliberately has no authoritative `length`; v1's stored length is what the
index-integrity work removed, because it could disagree with the rows present.
A **display-only, explicitly-advisory** count in metadata would be safe in a way
the v1 `length` was not — the corruption came from using it to *address* rows
(`range(length)`), not from reporting it.

But the consumer's two `len()` defects were both callers asking for a count
immediately before reading the items anyway. Removing the call is strictly
better than making it cheap. Low priority; do not reintroduce a stored length
that anything addresses from.

### G. Document the cost — cheapest, and it addresses the observed failure mode

Both consumer defects were caused by **v1-era comments asserting cheapness**:
one said `len()` *"avoids N DB reads"*, another that a count came *"from
metadata only"*. Neither is true under v2. Inside the library the same shape
exists: `_v2_ensure_rank_cache`'s *"one keys-only range query"*,
`get_metadata`'s *"cheap after the first call"* (true only within an instance
the store discards), `protocols.py`'s `keys_only` as *"a cheaper projection
read"* (true on Postgres, not DynamoDB).

`__len__` and `__getitem__` should state their v2 cost. This is the only option
here that costs nothing and prevents the exact mistake that has now been made
three times.

## Decisions Needed

### Decision 1: Is the handle API (A) the direction, or is `remove_where` (B) enough?

A is a larger surface but removes the class; B is smaller but leaves positional
batches unfixed and leaves the skew hazard representable. They are not
independent — B should be built on A if A is taken.

### Decision 2: What is a handle on a v1 list?

Refuse (defensible: 730/730 v2, new lists born v2, migration tooling exists), or
synthesise from a position and document that it carries a position's weaknesses.
Refusing makes the API's guarantee honest; synthesising makes it universal.

### Decision 3: Does C (`last_rank`) ship independently?

It is orthogonal to A — appends do not go through positions. It could ship
first, as the single highest-volume saving, or wait so the meta-row format
changes once.

### Decision 4: Is D worth doing at all if A lands?

A removes most of the reads; D halves what remains. Sequencing matters more than
the choice.

### Decision 5: Does G ship now, regardless?

Docstring corrections are releasable immediately and independent of every
decision above.

## Code References

- `actingweb/property_list.py:1338-1341` — storage identity is the rank, not the
  position (the finding this document turns on)
- `actingweb/property_list.py:288-304` — `_v2_ensure_rank_cache`, the keys-only
  scan
- `actingweb/property_list.py:737-767` — `_v2_getitem` and why the force is
  correct
- `actingweb/property_list.py:908-925` — `_v2_delitem`
- `actingweb/property_list.py:1004-1031` — `_v2_append`, the cold-cache tail read
- `actingweb/property_list.py:1349-1397` — `_v2_pop`, the resolve → read →
  conditional-delete → retry shape a handle API would reuse
- `actingweb/property_list.py:2343-2352` — why a rank must never be acted on
  unconditionally: the generation boundary
- `actingweb/property.py:54` — `__getattr__` mints a fresh `ListProperty`
- `actingweb/interface/actor_interface.py:304-316` — the store is memoized
- `actingweb/handlers/mcp.py:52` — the 5-minute renewed actor-cache TTL
- `actingweb/attribute_list_store.py:87-93` — the caching precedent that does
  not transfer
- `actingweb/db/dynamodb/property.py:483-519` — `get_range`, `consistent_read`
  and the projection

## External References

- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchWriteItem.html>
  — no conditions on batch put/delete; 25 items / 16 MB; parallelism does not
  reduce capacity
- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html>
  — 100 actions, 4 MB, `Delete` supports a condition, all-or-nothing

## Confidence

**Verified first-hand:** the identity-vs-position finding and every code
reference above; the generation-boundary constraint; the actor-cache lifetime
chain behind E; both DynamoDB API facts.

**Measured by the consumer, not re-measured here:** every RCU figure and the
964 KB page finding. Source:
`actingweb_mcp/thoughts/research/2026-08-20-v2-list-read-cost.md`.

**Plausible, not verified:** option C's claim that the existing
`create_if_not_exists` retry already covers a stale `last_rank`. Trace the retry
loop before planning on it.

**Not evaluated:** what a handle API means for the Postgres backend, which has
different cost characteristics throughout (`get_range` is one SELECT and
`keys_only` genuinely projects); and `ListAttribute`, which has no v2 code at
all and is a separate, unmigrated design.
