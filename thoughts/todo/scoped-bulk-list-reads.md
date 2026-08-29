# Scoped bulk list reads, and `get_attr()` after `get_bucket()`

**Created:** 2026-08-29
**Research:** `thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md`
(measurements, provenance, and the code-level diagnosis for both items)
**Trigger:** none — both are additive and can land in a 3.14.x patch.

Two independent items from one consumer measurement. They are filed together
because they came from one investigation, not because they need one change.

---

## A. `fetch_all_including_lists()` cannot be scoped to named list families

**What.** `db/dynamodb/property.py:734` issues `Property.query(actor_id)` with
no range condition, so a caller that wants two list families pays for all of
them. `property.py:31` (`list_all()`) then throws away everything but the
`-meta` rows — *name discovery alone costs a whole-partition dump.*

**What it buys.** On the consumer's heaviest account: **1,361 RCU across 11
sequential pages → 686 RCU across 8 independent queries.** Half the capacity,
and the 8 have no pagination chain between them, so they can be issued
concurrently: measured **1,224 ms serial vs 700 ms concurrent**. For a page load
the concurrency is the bigger half.

**Why us and not the consumer.** `property.py:64-71` documents the row-name
encoding as opaque and slated to change in the next major, so a consumer that
builds its own range bounds writes against an interface we have reserved the
right to break.

**Precedent, and the two traps it already found.** 3.14 made this exact change
for the *plain-property* path (`thoughts/plans/2026-08-20-v2-positional-access-cost.md`)
and deliberately left the bulk path alone — "it legitimately wants the whole
partition". That was true then; this is the caller that makes it no longer true.
That plan also paid for two lessons that apply here directly:

1. The upper sentinel must be the byte **after** the prefix (`list;`, 0x3B),
   never `list:~` — `~` is 0x7E and every non-ASCII list name sorts past it.
2. PostgreSQL must not use ordering comparisons (collation-dependent); use
   `LIKE`, and double the `%` when it is literal SQL rather than a bound param.

**Shape.** Scope expressed in **list names**, never row-key bounds — otherwise
this writes today's encoding into a public signature and blocks
`prop-list-key-prefix-scheme.md`. Reaches the existing `get_range`
(`db/protocols.py:185`, both backends), so nothing new is needed at the database
layer. Unscoped calls must stay byte-identical to today.

**Effort.** Small-to-medium. The primitive exists; this is a public API surface,
its two backend paths, and the tests that pin the sentinel and collation traps.

---

## B. `get_attr()` ignores the `_bucket_loaded` flag `get_bucket()` sets

**What.** `attribute.py:101-115` checks `if name not in self.data` and never
consults `self._bucket_loaded`, which `get_bucket()` sets at `:98` and whose
docstring calls authoritative for full-bucket loads. So after a complete bucket
load, a lookup of a name that is **absent from the bucket** issues a database
point read to re-learn what the object already knows.

**Not a missing negative cache.** The miss *is* cached — `self.data[name]` is
assigned even when the result is `None` — so repeat lookups are free. This is a
first-lookup-after-`get_bucket()` problem only. (An earlier consumer-side
write-up called it a missing negative cache; that is wrong.)

**What it buys today: nothing.** Stated plainly so it does not borrow item A's
numbers. The saving needs `get_bucket()` and `get_attr()` on the *same
instance*, and the consumer's ~225 call sites all construct a fresh `Attributes`
per call. The one path that did read the bucket first now bypasses `get_attr()`
entirely and reads the dict, with a comment explaining why — which is the actual
report: **our own accessor is the wrong tool after our own bulk loader, and a
consumer had to route around it.** Seven attributes, three normally absent, on a
path that runs every page load.

**Shape.** Return `None` for a name absent from `self.data` when
`_bucket_loaded` is true. Two things to get right: `set_attr()`/`delete_attr()`
must not leave the flag true over a stale dict (this change makes the flag
load-bearing for correctness, not just for `get_bucket()`'s short-circuit); and
"absent" vs "present with value `None`" becomes observable, so pin it in tests
rather than leaving it to inference.

**Effort.** Small — roughly three lines plus the invalidation audit and tests.

**Worth more later than now.** A consumer building one aggregate endpoint over
one bucket read is exactly the caller who would call `get_bucket()` and then
reach for `get_attr()`, and would silently pay a read per absent name. That
consumer is currently planning such an endpoint.
