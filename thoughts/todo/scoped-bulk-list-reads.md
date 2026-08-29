# Scoped bulk list reads, and `get_attr()` after `get_bucket()`

**Created:** 2026-08-29
**Revised:** 2026-08-29 — independently verified against the working tree; the
numbers, the API shape and item B's scope all changed. See the research doc's §6.
**Research:** `thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md`
(measurements, provenance, per-figure corrections, and six open decisions)
**Trigger:** none — both are additive and can land in a 3.14.x patch.

Two independent items from one consumer measurement. They are filed together
because they came from one investigation, not because they need one change.
Item A has grown a third part (A3) that needs no public API at all and may be
worth landing first.

---

## A. A bulk list read cannot be scoped to a namespace of lists

**What.** `db/dynamodb/property.py:734` issues `Property.query(actor_id)` with
no range condition, and `db/postgresql/property.py:793` is the same unfiltered
`SELECT`. A caller that wants two list families pays for all of them.
`property.py:31` (`list_all()`) then throws away everything but the `-meta`
rows — *name discovery alone costs a whole-partition dump.*

**What it buys.** On the consumer's heaviest account (1,291 rows, 10.5 MB):
**1,361.0 RCU across 11 chained pages → 685.0 RCU across 8 queries in 5
chains.** Half the capacity, and the five families are independent of each
other, so they issue as five concurrent streams instead of one eleven-page
chain: measured **1,224 ms serial vs 700 ms concurrent**. For a page load the
concurrency is the bigger half.

Two things that number is not. It is **not** 686-across-8 — that figure paired
nine-query capacity with an eight-query count, and called five families "eight".
And prefix reads are **not cheaper per byte**: summing every family including the
embeddings block gives 1,363.5 RCU across 15 queries against 1,361.0 across 11.
The entire saving is *not reading families you do not need*. A scoped read
invoked once per family is a small regression.

**Why us and not the consumer.** `property.py:64-71` documents the row-name
encoding as opaque and slated to change in the next major, so a consumer that
builds its own range bounds writes against an interface we have reserved the
right to break.

### A1. The public scoping parameter

**It must take a list-name PREFIX, not an exact list name.** This is settled,
not open. The consumer's list names are created at runtime
(`getattr(actor.property_lists, memory_type)`), so `memory_*` in the measurement
is N lists sharing the prefix `memory_`, not one list. Exact-name scoping
delivers none of the measured saving and cannot discover the names it would need.

The constraint the original filing states as "list names, never row-key bounds"
is right but imprecise. The line that actually matters:

> A list *name prefix* is caller-supplied text and keeps the row encoding
> opaque; a row-key bound does not.

A caller passing `"memory_"` says nothing about `list:`, `-meta` or `-#{rank}`,
so `prop-list-key-prefix-scheme.md` stays free to change all of it.

Prefix semantics also dissolves a problem exact names cannot solve: list names
may contain `-`, so a list named `foo-old` writes `list:foo-old-meta` inside any
prefix built for list `foo`. Under "every list whose name begins with `foo`"
that is the contract, not a leak. (The library already knows this collision
class: `property_list.py:45-83`, `_v2_is_rank()`, `_V1_INDEX_RE`,
`tests/test_property_list_integrity.py:733-830`.)

**Do not call the parameter `only=`.** SQLAlchemy's `load_only()` and Django's
`only()` mean a *deferred* load with a silent re-fetch on access. Nothing here is
deferred. `prefixes=` / `name_prefixes=` says what it is.

### A2. Two traps, one of them new and load-bearing

1. **`get_range`'s `consistent_read` defaults to `True`; today's dump is
   eventually consistent.** `Property.query()` takes PynamoDB's
   `consistent_read=False` default, and a strongly consistent DynamoDB read
   costs **twice** an eventual one. Every measured figure is an eventual read —
   the byte arithmetic confirms it (10.5 MB ⇒ 2,688 units ⇒ 1,344 eventual vs
   1,361 measured; same for each family). **A scoped read at `get_range`'s
   default would cost ~1,370 RCU for the five families — more than the 1,361 RCU
   dump it replaces.** Pass `consistent_read=False` explicitly and pin it in a
   test. `get_range`'s default cannot change: its four v2 callers
   (`property_list.py:465`, `:536`, `:1664`, `:1697`) chose it and
   `tests/test_v2_consistent_read.py` pins those choices.
2. **The sentinel trap is avoidable, not merely survivable.** PynamoDB 6.1.0's
   `UnicodeAttribute.startswith` compiles to DynamoDB's native `begins_with`,
   which is exact for any UTF-8 prefix (String sort keys are ordered by UTF-8
   bytes, and UTF-8 is prefix-preserving) and needs no sentinel. No synthesised
   upper bound for `between()` is exact — whatever byte is appended, a real name
   can exceed it. The `list;`-vs-`list:~` lesson from
   `thoughts/plans/2026-08-20-v2-positional-access-cost.md` is real; a
   `get_prefix()` primitive removes the class of bug instead of getting it right
   once more. Watch: `begins_with` does no Unicode normalization, and the repo
   already tests a list named `"étag"`.

**Correction to the earlier filing:** "PostgreSQL must not use ordering
comparisons; use `LIKE`" is over-general. That rule belongs to `fetch()`'s
*exclusion* predicate. The shipped `get_range` on PostgreSQL uses
`name COLLATE "C" >= %s AND name COLLATE "C" <= %s`
(`db/postgresql/property.py:511-518`), and `COLLATE "C"` *is* byte order — the
collation hazard is already answered and matches DynamoDB's UTF-8 byte ordering.
**No `LIKE` and no `%%` doubling is needed.** If a `LIKE` is introduced anyway,
note that every family prefix in the measurement contains `_`, which is a
single-character wildcard, so `%`, `_` and the escape character all need escaping
in the *parameter value* with an explicit `ESCAPE` clause. Also note the
psycopg3 rule is `params is not None`, not client-vs-server binding:
`execute(sql, ())` and `execute(sql, None)` treat `%%` differently.

Two more PostgreSQL specifics for the plan: the `properties` PK is `(id, name)`
under the **default** collation with no secondary index, so a `COLLATE "C"`
predicate cannot be an index range scan on `name` (pre-existing for all four
shipped `get_range` callers; the PostgreSQL win is rows returned and TOAST
detoasting, not index seeks). And `fetch()` returns `{}` for zero rows while
`fetch_all_including_lists()` returns `None` — a new scoped method must pick one
deliberately so "empty prefix" and "error" do not collide.

### A3. Three internal callers dump the partition to read *one* list — no API needed

Not in the original filing, and plausibly the largest single-actor cost in the
repository today. These v1-format methods each call
`fetch_all_including_lists()` and then index it by exact row name:

- `ListProperty.verify()` — `property_list.py:2743`
- `ListProperty.compact()` — `property_list.py:3013`
- `ListProperty.migrate_to_v2()` — `property_list.py:3180`

The v2 counterparts do not: `_v2_verify()` (`:2578`) goes through
`_v2_load_full()` (`:536`), a scoped `get_range`.

The maintenance scripts multiply it. `maintenance/migrate_property_lists.py:192`
and `maintenance/verify_property_lists.py:153` call `list_all()` (one dump) and
then iterate per list, and `migrate_to_v2()` internally calls `verify()` — so
migrating N v1 lists on one actor costs on the order of **2N + 1 whole-partition
dumps**. On the measured account that is 1,361 RCU times the list count.

This needs no public API and no new public contract, which is an argument for
landing it first: it exercises the primitive from inside the library before any
consumer depends on the surface.

### A4. What scoping does *not* fix — say so in the plan, don't promise it

Global name discovery stays a whole-partition dump. `-meta` rows are interleaved
across lists in key space (within one list, `-#{rank}` at 0x23 and `-{index}` at
0x30–0x39 both sort before `-meta` at 0x6D, but the blocks alternate), so **no
range or prefix read selects only the `-meta` rows**, and a keys-only projection
saves no DynamoDB capacity — AWS: *"requesting a subset of attributes … has no
impact on the item size calculations"*, and §2 measured 1,361.0 either way. What a
prefix gives is cheap discovery *within a namespace*, which is the consumer's
actual shape. A cheap global registry is a key-layout question and belongs to
`prop-list-key-prefix-scheme.md`.

### A5. Consistency contract

`whole-list-rewrite-atomicity.md:52` already records that
`fetch_all_including_lists()` "is a paginated DynamoDB `Query`, not a snapshot",
and `list_all_with_rows()`'s docstring already tells callers the rows are stale
the moment a mutation lands. K concurrent per-prefix reads are strictly weaker:
today's pages at least advance monotonically through one key space, whereas
independent prefix reads can straddle a mutation in either direction and produce
**cross-family** skew. Not worse in kind, but the window widens and the failure
mode changes shape — the scoped method's docstring must say so rather than
inherit the existing sentence.

### A6. The invariant that keeps a partial `rows` dict safe

Every caller of `list_all_with_rows()` today assumes a **complete** partition
dump (`handlers/www.py:186`, `handlers/trust.py:1190`,
`handlers/properties.py:589-640`, `actor.py:2575-2577`). Traced through
`property_list.py:1011-1094`, a partial dict is safe in two of three cases and
silently wrong in the third: a list entirely absent falls back to the lazy path
(`:1039`), a **v1** list with meta-but-no-items falls back to a per-item read
(`:1088-1091`), but a **v2** list with meta-but-no-items returns `[]` with no
fallback (`:1071-1077`) and `len()` reports 0.

So:

> A scoped read must bound on the **list-name namespace** (`list:{prefix}`), so
> every list it returns a `-meta` row for also gets all of that list's item rows.
> Never bound on a per-list sub-range that could separate the two.

`names` is necessarily scoped alongside `rows` — a scoped read cannot know names
outside its prefix without paying for them — so the `(names, rows)` pair stays
internally consistent and a caller iterating `names` never reaches the bad case.
Record that as forced, not chosen. Still open: whether the existing method gains
the parameter (its docstring's "the actor's WHOLE partition" then becomes
conditional) or a scoped variant takes its own name.

**Unscoped calls must stay byte-identical to today.**

**Acceptance gate.** §5 of the research doc records that the 685/8 figure is
*not* reproducible from any committed script, so the RCU number cannot be the
test. The gate is `tests/test_v2_cost_library_callers.py`'s existing query-count
spies (`_count_get_range`, and the per-caller budgets at `:139`, `:191`, `:215`)
plus `tests/test_hot_path_n_plus_one.py` — extended so that **one of them asserts
`consistent_read=False` was passed**, in the style of
`tests/test_v2_consistent_read.py:32`, `:205-208`. Without that assertion A2.1 is
a comment, not a constraint, and the regression it warns about ships green.

**Effort.** Medium. A backend primitive on both backends, a public API surface
and its interface wrapper, the internal-caller conversion (A3), and tests that
pin the consistency default (A2.1), the prefix exactness (A2.2) and the
call-budget regressions in `tests/test_v2_cost_library_callers.py`.

**Open decisions** (seven, laid out with options and evidence in the research doc §7):
prefix vs exact names and the parameter name; reuse `get_range` vs add
`get_prefix()`; where the concurrency lives, given a synchronous DB layer and a
latency win that requires it somewhere; which public surfaces get the parameter
and whether a permission-checked variant is needed; whether A3 ships in the same
change; what a partial `rows` dict promises (A6); and how far item B's
preconditions extend.

---

## B. `get_attr()` ignores the `_bucket_loaded` flag `get_bucket()` sets

**What.** `attribute.py:101-115` checks `if name not in self.data` and never
consults `self._bucket_loaded`, which `get_bucket()` sets at `:98` and whose
docstring calls authoritative for full-bucket loads. So after a complete bucket
load, a lookup of a name that is **absent from the bucket** issues a database
point read to re-learn what the object already knows.

**Not a missing negative cache.** The miss *is* cached — `self.data[name]` is
assigned even when the result is `None` — so repeat lookups are free. This is a
first-lookup-after-`get_bucket()` problem only.

**What it buys today: nothing.** Stated plainly so it does not borrow item A's
numbers. The saving needs `get_bucket()` and `get_attr()` on the *same instance*,
and across `actingweb/` **zero** call sites pair them; the consumer's ~225 call
sites construct a fresh `Attributes` per call.

**The contract argument now has an in-repo witness.** `InternalStore`
(`attribute.py:9-66`, held for an `Actor`'s lifetime at `actor.py:89`, `:238`,
`:398`) calls `get_bucket()` once in `_ensure_loaded()` and thereafter reads its
own `__dict__` — never `get_attr`. That is exactly the bypass the consumer wrote
a seven-line comment to justify, already in the library, for the same reason.
Take the item on that, not on a number.

**It is also a correctness fix, in the other direction.** `get_attr()`'s
`:110` assigns `self.data[name] = None` on a miss, and `get_bucket()` returns
`self.data` **by identity** (`:99`) and unfiltered once loaded. So today
`get_bucket()` → `get_attr("absent")` → `get_bucket()` returns a dict containing
a key with no stored row. The early return removes that too.

### What the invalidation audit found

**Clean, where the request expected trouble.** `_bucket_loaded` is written in
exactly three places (`:98` True in `get_bucket`, `:245` False in
`delete_bucket`, `:269` False in `__init__`) and read in exactly one (`:85`).
`delete_attr` does `del self.data[name]` (`:209`) — it removes the key rather
than nulling it — as does `delete_attr_conditional` (`:232`); `set_attr`
(`:139-144`) and `conditional_update_attr` (`:196-201`) add a previously-absent
key. The dict stays in step with mutations made *through this instance*.

**"Absent" vs "present with value `None`" is already observable, and survives.**
`set_attr(name, data=None)` does not store a null — it takes the backends'
falsy-delete branch, which is also how `delete_attr` is implemented. Both
backends' `get_attr` return `None` for a missing row and a **truthy dict**
`{"data": None, …}` for a present row holding null. The only path that can store
a null is `conditional_update_attr`, whose sole library caller
(`oauth_session.py:589`) never passes one. The test is cheap; write it.

### Two things the request did not know about

**B-i. A precondition on DynamoDB: `get_bucket()` over-matches.**
`db/dynamodb/attribute.py:60-62` queries `Attribute.bucket_name.startswith(bucket)`
where `bucket_name` is `bucket + ":" + name` — the prefix is `bucket`, **not**
`bucket + ":"` — and keys the result by bare `name` (`:67`). PostgreSQL is exact
(`WHERE id = %s AND bucket = %s`, `db/postgresql/attribute.py:199-206`), so the
backends disagree. The repo already compensates elsewhere:
`db/dynamodb/attribute.py:358` filters `if t.bucket == bucket` inside
`delete_by_chain`. Every *constant* bucket name is prefix-free, but
`remote:{peer_id}` (`remote_storage.py:50`) admits variable-length peer ids, so
`remote:abc` is a prefix of `remote:abcd`.

Today `get_attr()`'s unconditional point read is exact and corrects the
over-match. Making `_bucket_loaded` authoritative for absence promotes an
over-matched bucket into the answer. **Fix `startswith(bucket)` →
`startswith(bucket + ":")` in the same change**, or item B converts a latent
divergence into a wrong answer.

**B-ii. A real invariant break, in the "present" direction.** Both backends treat
a **falsy** value as a delete (`if not data:` → delete the row, return `True`:
`db/dynamodb/attribute.py:140-148`, `db/postgresql/attribute.py:339-365`), while
`Attributes.set_attr` has already cached `{"data": {}, …}` and returns that
`True`. So `set_attr(name, data={})` — or `[]`, `""`, `0`, `False` — leaves a
`_bucket_loaded=True` dict claiming a key whose row was deleted. Honouring the
flag for absence does not make this worse, but any test asserting "the loaded
dict is authoritative" has to decide what this case means. Separable; decide
explicitly rather than by omission.

**B-iii. It is a semantic change for a long-lived instance, not three lines.**
`handlers/mcp.py` caches a live `ActorInterface` on a sliding five-minute TTL
that can last a warm container's lifetime
(`thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`), and
`Actor.store` holds an `Attributes` inside it. Nothing invalidates that dict on a
write made through a *different* instance — `oauth_session.py:622-628` builds a
second `Attributes` specifically to "bypass cache". Today's first-miss re-read is
an accidental escape hatch from that. In-repo exposure is nil (nothing calls
`get_attr` after `get_bucket`), but for a consumer holding an `Attributes` across
requests this belongs in the release note, not in "small".

**Effort.** Small for the core change; medium once B-i ships with it.

**Worth more later than now.** A consumer building one aggregate endpoint over
one bucket read is exactly the caller who would call `get_bucket()` and then
reach for `get_attr()`, and would silently pay a read per absent name. That
consumer is currently planning such an endpoint.
