# Research: bulk list reads, measured from a consumer

**Date:** 2026-08-29
**Branch:** master
**Commit:** 36254ca
**Measured against:** ActingWeb **3.14.0** on DynamoDB (`AI_*`, eu-central-1).
Re-checked at the consumer's current pin, **3.14.2**: nothing in 3.14.1 or
3.14.2 touches the property or property-list read path, so the numbers hold.
**Revised:** 2026-08-29, after independent verification in this repository —
see **§6**, which corrects three claims below (marked `[see §6]`), adds four
findings the original measurement did not reach, and settles the open design
call. The corrections are in-place per `thoughts/README.md` ("never edited
afterwards except to correct an error"); §5's provenance is untouched.
**Consumer:** `actingweb_mcp` (Emm AI). Its own analysis lives in that
repository at `thoughts/research/2026-08-24-spa-fanout-cost-and-latency.md` §4
and `thoughts/verifications/2026-08-23-v2-list-read-cost.md`. **All numbers
below are reproduced inline** — a relative link from this repository into that
one would be dead, and these figures are the whole point of the document.

## Research Question

A consumer application renders a page from several list families at once. What
does the library charge it for that, and which of the costs are the library's
to remove?

Three problems came out of the measurement. Two are ordinary bugs-or-gaps with
a clear shape; the third is mostly already solved by fixing the first, and what
survives of it belongs to work this repository has already filed.

## Summary

**Problem A — the bulk list path still reads the whole partition, and it is the
one path 3.14 deliberately did not fix.** `fetch_all_including_lists()` issues
`Property.query(actor_id)` with no range condition, so a caller that wants two
list families pays for all of them. On the consumer's heaviest account that is
**1,361 RCU across 11 sequential Query pages**; the five list families its
pages actually render measure **685 RCU across 8 queries in 5 chains** —
half the capacity, and issuable as five concurrent streams rather than one
eleven-page chain `[see §6, C1]`. The primitive already exists (`get_range`);
what is missing is a way to reach it through the public list API without the
caller encoding row names — and, as §6 C3 shows, reaching it at its **default
consistency** would cost more than the dump it replaces.

**Problem B — `get_attr()` ignores the flag `get_bucket()` sets.** After a full
bucket load, a `get_attr()` for a name that is absent still issues a database
point read, because the miss check is `if name not in self.data` and never
consults `self._bucket_loaded`. **The measured saving today is zero** — see
§3, which says why plainly rather than letting this problem borrow Problem A's
credibility. It is filed as a contract bug: `get_bucket()`'s docstring
describes the flag as authoritative for full-bucket loads, and `get_attr()`
does not honour it. The evidence is that a consumer had to bypass the accessor
and leave a comment explaining why.

**Problem C — in-body vector payload — is 3/4 solved by Problem A, and the rest
is already filed here.** 66.3% of the consumer's partition is embedding
payload no page renders. But 49.8% of it is the `output_embeddings_*` sidecar,
which a prefix-scoped read simply excludes — that exclusion *is* how the 685
figure is derived. Only the remaining **16.7%**, vectors stored inside
`memory_*` item bodies, is beyond a prefix's reach, because those bytes sit in
rows the page does render. That residue is appended to
`thoughts/todo/prop-list-key-prefix-scheme.md` rather than filed separately.

---

## 1. Context: what the consumer does, and why this is the library's problem

The consumer is a single-page app whose shell renders memory, outputs and
instructions together. Three of its endpoints each independently call a bulk
list read on the same actor, so one page load pays the whole-partition cost
three times over.

It cannot fix this itself, for a reason the library states deliberately. The
row-name encoding — `list:{name}-meta`, `list:{name}-{index}`,
`list:{name}-#{rank}` — is documented in `actingweb/property.py:64-71` as *"a
storage detail the next major version's key-prefix scheme will change"*. A
consumer that builds its own range bounds from that encoding is writing against
an interface the library has explicitly reserved the right to break. The
consumer's own rule ("never bypass the storage layer") says the same thing from
the other side. So a range read that is *correct* is only available here.

That is the whole argument for these being upstream requests rather than
consumer work. The measurement below exists to size them: a feature request
without a number is a wish.

## 2. Problem A: `fetch_all_including_lists()` reads the whole partition

### What the code does

`actingweb/db/dynamodb/property.py:734-748`:

```python
def fetch_all_including_lists(self, actor_id=None):
    ...
    self.handle = Property.query(actor_id)   # no range_key_condition
```

Every row in the actor's partition, always. `actingweb/property.py:31-52`'s
`list_all()` then calls it and **discards every row but the `-meta` ones** — so
*name discovery alone costs a whole-partition dump*.
`list_all_with_rows()` (`:53-87`) at least returns the dump it paid for, which
is why the consumer uses it.

### What it costs

Measured read-only against the consumer's heaviest production account (1,291
rows, 10.5 MB, actor `5a1c8087…`, eu-central-1), driven from a laptop. Query
**counts** and **RCU** are exact and portable; wall times carry WAN RTT (~40 ms
floor) and are upper bounds:

| Operation | Queries | RCU | Wall |
| --- | --- | --- | --- |
| `fetch_all_including_lists` — whole partition | **11 sequential** | **1,361.0** | 1,233–1,744 ms |
| …the same, keys-only projection | 11 | **1,361.0** — *identical* | 453 ms |
| `list:memory_*` range | 2 | 248.5 | 365 ms |
| `list:output_*` bodies (skipping the embeddings block) | 3 | 363.5 | 470 ms |
| `list:output_embeddings_*` (what no page renders) | **6** | **678.0** | 935 ms |
| `list:instruction_*` | 1 | 18.5 | 49 ms |
| `list:audit_*` | 1 | 37.5 | 189 ms |
| `list:run_*` (252 rows) | 1 | 17.0 | 41 ms |
| plain properties | 1 | ~0.5 | 39 ms |

Reading the five list families the consumer's pages need: **685.0 RCU across 8
queries**, against 1,361.0 across 11. (With plain properties: 685.5 across 9.
The original "686 across 8" added plain properties' RCU to a query count that
excluded them, and called the five families "eight" — `[see §6, C1]`.) Two
findings worth carrying:

1. **A keys-only projection saves no capacity at all** — 1,361.0 RCU either
   way. Capacity is charged on items read, before projection. It cuts wall time
   (453 ms vs ~1,300 ms) because the bytes still travel, but it is not a cost
   fix. Anyone reaching for `attributes_to_get` as the answer here should see
   this number first.
2. **The five families are independent of each other; the 11 pages are not.**
   Pagination is a chain — each page needs the previous page's
   `LastEvaluatedKey`. Five prefix reads have no dependency *between* them and
   can be issued concurrently: measured 1,224 ms serial vs **700 ms
   concurrent** from the same laptop, where the uplink rather than the database
   is the limiter. Note the concurrency is five streams deep-3 at worst, not
   eight independent singles: `memory_*` paginates twice and `output_*` three
   times, so the floor is the longest chain, not one round trip `[see §6, C1]`.
   So this is a latency request as well as a cost one, and the latency half is
   the larger of the two for a page load.

### Why this is a follow-on, not a new idea

**3.14 already made exactly this change for the plain-property path.**
`thoughts/plans/2026-08-20-v2-positional-access-cost.md` replaced `fetch()`'s
whole-partition query with a pair of range-constrained Queries — and scoped the
bulk path out on purpose:

> `fetch_all_including_lists()` is unchanged on both backends: it legitimately
> wants the whole partition, and Phase 3 depends on it doing exactly that.

That was right at the time: the only callers wanted everything. This document
is the evidence that a caller now wants a *part*, and that the part is half the
bytes.

The primitive is also already here. `get_range` exists on the protocol
(`db/protocols.py:185`) and both backends (`db/dynamodb/property.py:491`,
`db/postgresql/property.py:474`), and already carries a real `between()`
range-key condition. Nothing needs to be built at the database layer. What is
missing is a way for a *list* caller to say which families it wants without
touching row names.

### Request A

> **Superseded in three places by §6.** The sketch below reads `only=[...]` as
> *exact list names* — C2 shows that delivers none of the measured saving, and
> that the parameter must take a **name prefix**. Its PostgreSQL bullet is
> over-general — C4 shows the shipped `get_range` already answers the collation
> hazard with `COLLATE "C"`, so no `LIKE` and no `%%` is needed. And it omits the
> constraint that decides whether the change is a win at all — C3: `get_range`
> defaults to *strong* consistency, which would cost more than the dump it
> replaces. The rest of this section stands.

Give `PropertyListStore` a way to scope a bulk read to named list families —
expressed in terms of **list names**, never row-key bounds — and have it reach
`get_range` instead of `fetch_all_including_lists`. Shape suggestion, not a
specification:

```python
names, rows = actor.property_lists.list_all_with_rows(only=["memory", "output"])
```

Three constraints the implementation will hit, two of which this repository has
already paid for once:

- **The sentinel trap.** `2026-08-20-v2-positional-access-cost.md` found that
  the upper sentinel must be the byte *after* the prefix (`list;`, 0x3B), never
  `list:~` — `~` is 0x7E, so any list whose name begins above it (every
  non-ASCII name) sorts past the bound and leaks. The same reasoning applies
  per-family here. `get_range`'s own docstring already states the caller must
  choose a sentinel no real row name can equal; this makes the library that
  caller, which is the right place for the responsibility to sit.
- **PostgreSQL must not use ordering comparisons.** Same plan: text ordering is
  collation-dependent and a non-C collation disagrees with byte order on
  punctuation. Use `LIKE 'list:name-%'`, and note that plan's finding that
  psycopg3 needs the `%` doubled when it is literal SQL text rather than a bound
  parameter.
- **Keep the encoding opaque.** If the scoping parameter takes row-key bounds
  rather than list names, this request writes the current encoding into a public
  signature and blocks the very key-scheme change that
  `thoughts/todo/prop-list-key-prefix-scheme.md` is filed for.

`prefix=None` (or `only=None`) must be byte-identical to today's behaviour —
this is additive.

## 3. Problem B: `get_attr()` does not honour `_bucket_loaded`

### What the code does

`get_bucket()` (`actingweb/attribute.py:77-99`) loads the whole bucket and sets
a flag, and its docstring is explicit that the flag — not data emptiness — is
what "loaded" means:

> Tracks full-bucket loads with a flag rather than data emptiness: a
> `set_attr()`/`get_attr()` may have cached individual entries, and treating a
> partially-cached dict as "loaded" would silently return an incomplete bucket.

`get_attr()` (`:101-115`) then never reads that flag:

```python
if name not in self.data:
    self.data[name] = self.dbprop.get_attr(...)   # point read
```

So after a full bucket load, asking for a name that is **absent from the bucket**
issues a database round trip to re-learn something the object already knows. The
flag says the dict is complete; the miss check does not ask.

Note what is *not* wrong: the miss result is cached (`self.data[name]` is
assigned even when `None`), so a second lookup of the same absent name is free.
This is a first-lookup-after-`get_bucket()` problem only. An earlier write-up of
this in the consumer's repository described it as a missing negative cache;
that description is wrong and this supersedes it.

### What it costs today: nothing

Stated plainly, because this problem sits in a document whose other numbers are
large and it should not borrow them.

The saving only exists where `get_bucket()` and `get_attr()` are called on the
**same instance**. In the consumer, they are not: its ~225 `get_attr()` call
sites construct a fresh `Attributes` per call (`_attrs(actor_id, config)
.get_attr(name=…)` is the common shape), so `_bucket_loaded` is `False` and
honouring it would change nothing.

The one path that did read the bucket first now avoids `get_attr()` entirely.
From the consumer's `api/service_info.py:227-234`:

> `get_bucket()` only populates keys that are actually present in the bucket —
> `power_user`, `beta_tester` and `mobile_promo_dismissed` are normally unset —
> so calling `get_attr()` for any of them here would miss the bucket-loaded
> cache and issue its own extra point read per absent attribute. Reading the
> dict avoids that entirely.

That is the actual report: **the API's own accessor was the wrong tool after
its own bulk loader, and the consumer had to bypass it and write a comment
explaining why.** Seven attributes, of which three are normally absent, on a
path that runs on every page load.

### Request B

> **Extended by §6's B1–B7.** The invalidation audit this section asks for comes
> back clean (B1), but two things it did not know about: the fix inherits
> DynamoDB's over-matching `get_bucket()` and should ship with that fixed (B4),
> and it is a semantic change for any long-lived `Attributes` instance (B7). It
> is also a correctness fix in the opposite direction — `get_attr()` currently
> pollutes the loaded bucket with keys that have no row (B2).

Have `get_attr()` consult `self._bucket_loaded`: when the bucket is fully
loaded, a name absent from `self.data` is known-absent and must not trigger a
read. Roughly:

```python
if name not in self.data:
    if self._bucket_loaded:
        return None
    ...
```

Small, and worth doing on the contract argument alone rather than on a saving.
Two things to get right:

- `set_attr()`/`delete_attr()` must not leave `_bucket_loaded` true over a dict
  that no longer reflects the bucket — check the invalidation paths, since this
  change is what makes the flag load-bearing for correctness rather than just
  for `get_bucket()`'s own short-circuit.
- The distinction between "absent" and "present with value `None`" becomes
  observable. If a stored attribute can legitimately hold `None`, returning
  early on absence is still correct, but the test suite should pin the
  difference rather than leave it to inference.

It also matters more later than now: a consumer building one aggregate endpoint
over one bucket read is exactly the caller that would use `get_bucket()` and
then reach for `get_attr()`, and would silently pay a read per absent name.

## 4. Problem C: in-body vector payload — mostly already answered

The consumer's partition, tallied by list family (bytes as stored):

| family | rows | size | share |
| --- | --- | --- | --- |
| `output_embeddings_*` (the outputs sidecar) | 403 | 5.23 MB | **49.8%** |
| `output_*` (document bodies) | 447 | 2.78 MB | 26.5% |
| `memory_*` | 147 | 1.93 MB | 18.4% |
| `audit_*` | 16 | 0.29 MB | 2.8% |
| `instruction_*` | 14 | 0.14 MB | 1.3% |
| `run_*` | 249 | 0.12 MB | 1.1% |
| plain properties | 5 | <0.01 MB | 0.0% |

**66.3% is embedding payload no page renders** — the sidecar (49.8%) plus
in-body vectors inside memory items (16.7%; 90.6% of all `memory_*` bytes are
vector).

**Do not add this to Problem A's saving.** The 685-RCU figure in §2 is derived
*by* excluding `output_embeddings_*` — the sidecar's 49.8% and Problem A's ~50%
are the same bytes counted twice. Request A delivers this half; nothing further
is needed for it.

What Request A cannot reach is the **16.7% in-body memory vectors**, because
those bytes are inside `memory_*` rows that the page does render. No range read
can exclude part of a row. The consumer also cannot fix it with its own
sidecar: outputs already did exactly that, and those rows landed in the *same
partition*, which is why they still cost 678 RCU on every dump. Relocating
bytes within a partition does not reduce what a partition read costs.

### Request C, narrowed

A way to store per-item payload **out of band from the item body** — so a list
can carry a large per-item blob that bulk and range reads do not pay for.

This is a key-layout question, and this repository has already filed it:
`thoughts/todo/prop-list-key-prefix-scheme.md` (created 2026-08-21, triggered by
the next major bump), which is motivated by the same partition and already
cites a consumer list at 964 KB against DynamoDB's 1 MB Query ceiling. The
narrowed request is appended there rather than filed separately.

## 5. What was measured, and what is not reproducible

Provenance, since these numbers will outlive the session that produced them:

- **1,361 RCU across 11 pages** — reproducible. The consumer commits
  `scripts/measure_snapshot_rcu.py`, which drives `list_all_with_rows()` through
  the public accessor and reports queries and consumed capacity. Independently
  recorded in that repository's `thoughts/verifications/2026-08-23-v2-list-read-cost.md`
  (1,352.5 RCU / 11 queries, a separate run on the same account).
- **The partition breakdown in §4** — reproducible, same verification document.
- **686 RCU across 8 queries**, and **1,224 ms serial vs 700 ms concurrent** —
  **one-off, not reproducible from a committed script.** These came from an
  ad-hoc session driving `get_range` directly against production. The committed
  script measures only the whole-partition read. Treat them as a sized estimate
  from a real account, not as a repeatable benchmark — and if the implementation
  wants a before/after, the script needs extending first.
- **Problems A and B as code facts** — read directly from 3.14.2 at commit
  36254ca; line numbers cited inline.

One caveat on generality: these are **one heavy account**. The same consumer's
median account measures ~11.5 RCU for the whole dump, where none of this
matters. The case for Request A is that the cost scales with an individual
user's accumulated data, so today's heaviest account is a preview of an ordinary
one later — not that every account pays 1,361 RCU today.

---

## 6. Independent verification in this repository (2026-08-29)

Everything above was re-checked against the working tree at `989eb95` (3.14.2
code, unchanged from `36254ca`). The code-level diagnosis of Problems A and B
holds exactly as written. Three claims needed correcting, four findings the
consumer-side measurement could not reach are recorded here, and the design call
§2 left open is settled by C2.

### C1 — The query arithmetic does not reconcile, and "eight families" is wrong

Sum the non-embedding rows of §2's table:

```
248.5 (memory) + 363.5 (output) + 18.5 (instruction) + 37.5 (audit) + 17.0 (run)
    = 685.0 RCU across 2+3+1+1+1 = 8 queries
  + 0.5 (plain properties, 1 query)
    = 685.5 RCU across 9 queries
```

So **"686 RCU across 8 queries" pairs the nine-query capacity with the
eight-query count.** Neither reading is 686-across-8. And there are **five list
families plus plain properties — six sources, not eight**; the "8" is a query
count that got read as a family count.

The consequence is not the headline number (685 vs 686 is noise) but the
**shape**: `memory_*` takes 2 pages and `output_*` takes 3, so those are
pagination chains too. "Eight independent queries that parallelise" is really
**five concurrent streams, the deepest three pages long**. The 700 ms
concurrent figure stands as measured; its explanation is max-of-chains, not
max-of-single-round-trips, and an implementation that fans out per family will
see that floor, not a one-RTT floor.

One more thing the table says only when summed. Every family including the
embeddings block:

```
248.5 + 363.5 + 678.0 + 18.5 + 37.5 + 17.0 + 0.5 = 1,363.5 RCU across 15 queries
```

against **1,361.0 across 11** for the single dump. **Prefix reads are not
cheaper per byte — they are very slightly more expensive**, because each query
rounds up independently and each family adds its own page boundaries. The entire
saving comes from *not reading families you do not need*. That matters for the
plan's success criterion: a scoped read that a caller invokes for every family
is a small regression, not a small win.

### C2 — A "family" is many lists sharing a name prefix, so the parameter must take a prefix

**This is the design call §2 left open, and the measurement already answers it.**

The consumer's list names are user-defined at runtime:
`getattr(actor.property_lists, memory_type)` — `actingweb_mcp`
`hooks/mcp/resources.py:108`, `:252`, `:392`, `hooks/mcp/services/ai_service.py:2004`,
`repositories/local_memory_repository.py:689`. The names that exist in that
repository include `memory_bikes`, `memory_config`, `memory_contact_info`,
`instruction_tasks`, `instruction_skills`, `audit_instruction_style`. So
`memory_*` in §2's table is **N lists whose names share the prefix `memory_`**,
not one list — which is why the table counts `output_*` and
`output_embeddings_*` as separate rows at all.

Therefore `list_all_with_rows(only=["memory", "output"])` read as **exact list
names delivers none of the measured saving**: it would need one query per actual
list name, and the caller cannot know those names without the whole-partition
dump the request exists to avoid.

This also sharpens the constraint the original states as "list names, never
row-key bounds". The real line is:

> **A list *name prefix* is caller-supplied text and keeps the row encoding
> opaque; a row-key bound does not.**

A caller passing `"memory_"` says nothing about `list:`, `-meta`, `-#{rank}` or
any other storage detail — the library still owns the whole translation from
name-space to key-space, and `prop-list-key-prefix-scheme.md` stays free to
change it. That is a stronger and more usable contract than exact names, and it
is the one the numbers were taken under.

### C3 — `get_range` at its default consistency costs 2× and would erase the saving

**The single most important implementation constraint, and it is in neither
filed document.**

- `fetch_all_including_lists()` reaches `Property.query(actor_id)`
  (`actingweb/db/dynamodb/property.py:741`) with no `consistent_read`.
  PynamoDB 6.1.0's `Model.query` defaults `consistent_read=False` — verified in
  the pinned environment. **Today's whole-partition dump is eventually
  consistent.**
- `DbProperty.get_range()` defaults `consistent_read: bool = True`
  (`actingweb/db/protocols.py:185-192`, `actingweb/db/dynamodb/property.py:491-497`).
  A strongly consistent DynamoDB read costs **twice** an eventually consistent
  one.

Every figure in §2 is an eventually consistent measurement, and the byte
arithmetic proves it independently of what the ad-hoc script passed:

| family | stored bytes | 4 KB units | eventual | strong | §2 measured |
| --- | --- | --- | --- | --- | --- |
| whole partition | 10.5 MB | 2,688 | 1,344 | 2,688 | **1,361.0** |
| `memory_*` | 1.93 MB | 494 | 247 | 494 | **248.5** |
| `output_*` | 2.78 MB | 712 | 356 | 712 | **363.5** |
| `output_embeddings_*` | 5.23 MB | 1,339 | 669 | 1,339 | **678.0** |

Every measurement sits just above the *eventual* column and at half the strong
column.

So a scoped read implemented as a plain `get_range` call **at its default**
would cost roughly **1,370 RCU for the five families** — more than the 1,361 RCU
dump it replaces. The scoped path must pass `consistent_read=False` to preserve
today's semantics, and a test must pin that it does; `get_range`'s default
cannot be changed, because its existing v2 callers
(`actingweb/property_list.py:465`, `:536`, `:1664`, `:1697`) chose it
deliberately and `tests/test_v2_consistent_read.py` pins those choices.

### C4 — The PostgreSQL "must not use ordering comparisons, use LIKE" rule is over-generalised

The `NOT LIKE 'list:%%'` lesson from `2026-08-20-v2-positional-access-cost.md`
applies to `fetch()`'s **exclusion** predicate, where an ordering comparison
would have to be trusted across a namespace boundary. It is not a general ban.
The shipped `get_range` on PostgreSQL uses ordering comparisons and pins the
collation:

```sql
SELECT name, value FROM properties
WHERE id = %s AND name COLLATE "C" >= %s AND name COLLATE "C" <= %s
```
(`actingweb/db/postgresql/property.py:511-518`; `get_last_in_range` does the same
with `ORDER BY name COLLATE "C" DESC LIMIT 1`, `:630-667`.)

`COLLATE "C"` *is* byte order, so the collation hazard is already answered, and
it makes the two backends semantically identical (DynamoDB orders strings "in
order of UTF-8 bytes"). **Reusing `get_range` on PostgreSQL needs no `LIKE` and
no `%` doubling** — the psycopg3 `%%` lesson only binds if a new literal `LIKE`
pattern is introduced.

One refinement to that lesson while it is being carried forward: psycopg3's rule
is not "client-side vs server-side binding" but simply **`params is not None`**.
When `vars is None` the query bytes pass through verbatim and `%%` is sent as two
literal percent signs; when parameters are present — *including an empty tuple* —
the placeholder parser runs and `%%` collapses to `%`. So `execute(sql, ())` and
`execute(sql, None)` are not interchangeable. The design that sidesteps all of it
is the one already in use: keep `%` out of the SQL text and put it in the
parameter value.

Two PostgreSQL specifics the plan should carry instead:

- The `properties` primary key is `(id, name)` under the **database default
  collation** (`actingweb/db/postgresql/schema.py:45-57`; the only secondary
  index was dropped in migration `c3d4e5f6a7b8`). PostgreSQL documents that a
  predicate's collation must match the index's for the index to serve it — an
  explicit `COLLATE "C"` on the column side does not match a default-opclass
  index. So `name COLLATE "C" >= %s` cannot be an index range scan on `name`;
  PostgreSQL seeks on `id` and filters the actor's entries. Bounded and cheap
  for one actor, but the PostgreSQL saving is in **rows returned and TOAST
  detoasting**, not in index seeks. Do not claim a symmetric win. (This is
  already true of the four shipped `get_range` callers, so it is a pre-existing
  property, not one this change introduces. If it ever matters, the fix is a
  migration adding `(id, name COLLATE "C")` — out of scope for a patch, and it
  should be measured with `EXPLAIN` first rather than assumed.)
- `fetch()` returns `{}` for an actor with no matching rows while
  `fetch_all_including_lists()` returns `None`
  (`actingweb/db/postgresql/property.py:830-831` vs `:787`), and
  `DbPropertyListProtocol` does not distinguish them
  (`actingweb/db/protocols.py:453-477`). A new scoped method has to pick one
  deliberately; "no rows in this prefix" and "error" must not collide.

### C5 — The sentinel trap is avoidable on DynamoDB, and unavoidable-but-harmless with exact names

PynamoDB 6.1.0's `UnicodeAttribute` exposes `startswith`, which compiles to
DynamoDB's native `begins_with` in a `KeyConditionExpression` — exact for
arbitrary UTF-8 prefixes, with no sentinel to choose: DynamoDB orders String
sort keys "in order of UTF-8 bytes", and UTF-8 is prefix-preserving, so byte
prefix and character prefix agree exactly. `between()` cannot be made exact for a
synthesised upper bound: whatever byte is appended, a real name can exceed it
(`P + "￿" + "x"` sorts above `P + "￿"`). So a `get_prefix()` primitive is
strictly safer than reusing `get_range` with a computed upper — the
`list;`-vs-`list:~` lesson is real, and `begins_with` sidesteps the class of bug
rather than getting it right once more. AWS also documents that `begins_with` is
rejected on Number sort keys (irrelevant here — `name` is a `UnicodeAttribute`)
and performs **no Unicode normalization**, so an NFD-composed prefix will not
match an NFC-stored name. Since `tests/test_v2_cost_plain_property_partition.py:89`
already creates a list named `"étag"`, that is a live case for a caller-supplied
prefix, not a hypothetical one.

Separately: **exact-list-name scoping cannot be made exact anyway.** List names
may contain `-`, so a list named `foo-old` writes `list:foo-old-meta`, which sits
inside any prefix built for list `foo`. The library already knows this class —
`actingweb/property_list.py:45-83` documents the sibling-collision problem and
solves it with post-read shape filters (`_v2_is_rank()` at `:154`, `_V1_INDEX_RE`
at `:82`), and `tests/test_property_list_integrity.py:733-830` pins it. Under
**prefix** semantics that collision is not a bug at all — "every list whose name
begins with `foo`" is exactly what was asked for — which is a second, independent
argument for C2's shape.

### C6 — Three library-internal callers dump the whole partition to read *one* list

Not in either filed document, and plausibly the largest single-actor cost in the
repository today. These three v1-format methods each call
`fetch_all_including_lists()` and then index the result by exact row name:

- `ListProperty.verify()` — `actingweb/property_list.py:2743`
- `ListProperty.compact()` — `actingweb/property_list.py:3013`
- `ListProperty.migrate_to_v2()` — `actingweb/property_list.py:3180`

The v2 equivalents do not: `_v2_verify()` (`:2578`) goes through
`_v2_load_full()` (`:536`), a scoped `get_range`. So this is a v1-path-only gap
that a prefix primitive closes without any public API change.

The maintenance scripts multiply it. `actingweb/maintenance/migrate_property_lists.py:192`
and `actingweb/maintenance/verify_property_lists.py:153` call `list_all()` (one
whole-partition dump) and then iterate per list, and `migrate_to_v2()` internally
calls `verify()` — so migrating N v1 lists on one actor costs on the order of
**2N + 1 whole-partition dumps**. On the account measured in §2 that is 1,361 RCU
multiplied by the list count.

### C7 — Splitting one chained dump into K concurrent reads widens the skew window

`thoughts/todo/whole-list-rewrite-atomicity.md:52` already records that
`fetch_all_including_lists()` "is a paginated DynamoDB `Query`, not a snapshot",
and `list_all_with_rows()`'s docstring
(`actingweb/property.py:64-71`) already tells callers the rows are "a
point-in-time snapshot, stale the moment a mutation lands". K concurrent
per-prefix reads are strictly weaker than that: today's pages at least advance
monotonically through one key space, whereas independent prefix reads can
straddle a mutation in either direction and produce **cross-family** skew. The
guarantee does not get worse in kind, but the window widens and the failure mode
changes shape, so the scoped method's docstring has to say so rather than inherit
the existing sentence unchanged.

### Findings specific to Problem B

**B1 — the invalidation audit the request asks for comes back clean.**
`_bucket_loaded` is written in exactly three places (`actingweb/attribute.py:98`
`True` in `get_bucket`, `:245` `False` in `delete_bucket`, `:269` `False` in
`__init__`) and read in exactly one (`:85`). `delete_attr` does
`del self.data[name]` (`:209`) — it removes the key rather than nulling it — and
`delete_attr_conditional` does the same (`:232`); `set_attr` (`:139-144`) and
`conditional_update_attr` (`:196-201`) add a previously-absent key. So the dict
stays in step with the mutations made *through this instance*, and the flag can
legitimately stay `True` across them.

**B2 — but `get_attr()` currently pollutes the bucket in the other direction.**
`:110` assigns `self.data[name] = None` on a miss, and `get_bucket()` returns
`self.data` **by identity** (`:99`) and unfiltered once loaded. So today,
`get_bucket()` → `get_attr("absent")` → `get_bucket()` returns a dict containing
a key with no stored row. The proposed early return removes that too, which is a
stronger correctness argument than the request currently makes — it is not only
a saved read.

**B3 — a real invariant break, in the "present" direction.** Both backends treat
a **falsy** value as a delete: `if not data:` → delete the row and return `True`
(`actingweb/db/dynamodb/attribute.py:140-148`,
`actingweb/db/postgresql/attribute.py:339-365`). Meanwhile
`Attributes.set_attr` has already cached `{"data": {}, "timestamp": …}` and
returns that `True` (`attribute.py:139-144`). So `set_attr(name, data={})` —
or `[]`, `""`, `0`, `False` — leaves a `_bucket_loaded=True` dict claiming a key
whose row was deleted. Honouring the flag for **absence** does not make this
worse, but it is the invalidation defect the request asked us to look for, and
any test that pins "the loaded dict is authoritative" has to decide what this
case means.

**B4 — a precondition on DynamoDB: `get_bucket()` over-matches.**
`DbAttribute.get_bucket` queries
`Attribute.bucket_name.startswith(bucket)` (`actingweb/db/dynamodb/attribute.py:60-62`)
where `bucket_name` is `bucket + ":" + name` — the prefix is `bucket`, **not**
`bucket + ":"`. So a bucket whose name is a prefix of another bucket's name
returns the other bucket's rows, keyed by bare `name` (`:67`). PostgreSQL is
exact (`WHERE id = %s AND bucket = %s`,
`actingweb/db/postgresql/attribute.py:199-206`), so the backends disagree. The
repository already compensates for this elsewhere —
`db/dynamodb/attribute.py:358` filters `if t.bucket == bucket` inside
`delete_by_chain`. Every *constant* bucket name in the library is prefix-free
(`actingweb/constants.py:120-173` and the OAuth/MCP bucket names), but
**dynamic** ones are not guaranteed to be: `remote:{peer_id}`
(`actingweb/remote_storage.py:50`) admits variable-length peer ids, so
`remote:abc` is a prefix of `remote:abcd`.

This matters *because of* the request. Today `get_attr()`'s unconditional point
read is an exact lookup and corrects the over-match. Making `_bucket_loaded`
authoritative for absence promotes an over-matched bucket into the answer.
**Fix `startswith(bucket)` → `startswith(bucket + ":")` in the same change**, or
Problem B's fix converts a latent divergence into a wrong answer.

**B5 — "absent" vs "present with value `None`" is already observable, and the
distinction survives.** `set_attr(name, data=None)` does **not** store a null —
it takes the same falsy-delete branch as B3, which is also how `delete_attr` is
implemented on both backends. Both backends' `get_attr` return `None` for a
missing row (`dynamodb/attribute.py:81`, `postgresql/attribute.py:259`) and a
**truthy dict** `{"data": None, "timestamp": …}` for a present row holding null.
The only write path that can store a null is `conditional_update_attr`, and its
sole library caller (`actingweb/oauth_session.py:589`) never passes one. So the
early return is safe, and the test the request asks for is cheap to write.

**B6 — no library-internal caller does `get_bucket()` then `get_attr()` on the
same instance, and the library's own store is the consumer's workaround.**
Across `actingweb/`, zero call sites pair the two on one object. The closest is
`InternalStore` (`actingweb/attribute.py:9-66`), held for an `Actor`'s lifetime
(`actingweb/actor.py:89`, `:238`, `:398`): it calls `get_bucket()` once in
`_ensure_loaded()` (`:34`) and thereafter reads its own `__dict__` (`:66`),
never `get_attr`. That is **exactly the bypass the consumer wrote a seven-line
comment to justify** — already present in the library, for the same reason. The
contract argument in §3 has an in-repo witness, which is worth more than the
absent number.

**B7 — the staleness that the current re-read accidentally provides.**
`handlers/mcp.py` caches a live `ActorInterface` on a sliding five-minute TTL
that on a warm container can last its lifetime
(`thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`), and
`Actor.store` is an `InternalStore` holding an `Attributes` with
`_bucket_loaded=True`. Nothing invalidates that dict on a write made through a
*different* instance — `actingweb/oauth_session.py:622-628` constructs a second
`Attributes` specifically to "bypass cache". Today `get_attr()`'s unconditional
first-miss read is an accidental escape hatch from that. In-repo exposure is nil
(B6: nothing calls `get_attr` after `get_bucket`), but for a consumer holding an
`Attributes` across requests this is a **semantic change**, not three lines, and
it belongs in the release note.

### What did not change

- Problem A's code-level diagnosis: `fetch_all_including_lists()` at
  `actingweb/db/dynamodb/property.py:734-748` and
  `actingweb/db/postgresql/property.py:793-834` is an unconstrained partition
  read on both backends; `list_all()` (`actingweb/property.py:31-52`) discards
  everything but the `-meta` rows.
- Problem B's code-level diagnosis: `attribute.py:101-115` never reads
  `_bucket_loaded`, the miss *is* cached so repeats are free, and it is a
  first-lookup-after-`get_bucket()` problem only.
- That the measured saving for Problem B is zero today.
- §5's provenance, verbatim. The 686-across-8 figure recorded there is what the
  ad-hoc session reported; C1 explains what it was.
- Problem C's conclusion and its filing under
  `thoughts/todo/prop-list-key-prefix-scheme.md`.

### Also confirmed: name discovery cannot be made cheap by scoping alone

The request notes that `list_all()` pays a whole-partition dump for names. That
does not change, and it is worth being explicit about why, so the plan does not
promise it. Within one list, `-#{rank}` rows (`#` = 0x23) and `-{index}` rows
(digits, 0x30–0x39) both sort *before* `-meta` (`m` = 0x6D), but across lists the
blocks alternate — `list:a-meta`, `list:b-#…`, `list:b-meta`, … — so **no range
or prefix read selects only the `-meta` rows.** A keys-only projection does not
help either: it saves no DynamoDB capacity
(`actingweb/db/protocols.py:217-224`, and §2's 1,361.0-either-way measurement).

What a prefix argument *does* give is cheap discovery **within a namespace** —
`list_all(only=["memory_"])` reads one prefix and returns both the names and the
rows under it, which is the consumer's actual shape. A cheap *global* registry is
a key-layout question and belongs to
`thoughts/todo/prop-list-key-prefix-scheme.md`.

---

## 7. Decisions Needed

### Decision 1: What does the scoping parameter accept?

1. **A list-name prefix** — `only=["memory_", "output_"]` means "every list whose
   name begins with one of these". *Pro:* it is the shape the §2 numbers were
   measured under (C2); it makes discovery-within-a-namespace work, which exact
   names cannot; sibling-name collisions (`foo` vs `foo-old`) stop being bugs and
   become the documented contract (C5); it keeps the row encoding entirely
   library-side. *Con:* "prefix" is a weaker promise than "these lists", so a
   caller wanting exactly one list gets its prefix-siblings too and must filter —
   though `prime_from_rows()`/`to_list_from_rows()` already filter by row shape.
2. **Exact list names** — `only=["memory_bikes"]`. *Pro:* the most precise thing
   a caller can ask for; matches the `getattr(store, name)` idiom. *Con:*
   delivers none of the measured saving for the consumer that asked (C2); cannot
   be made exact anyway because list names may contain `-` (C5); N names means N
   queries with no way to discover N.
3. **Both** — `only=[...]` for prefixes and a separate `names=[...]`. *Pro:*
   covers a caller that genuinely holds a name list. *Con:* two parameters, two
   sets of semantics and two sets of tests for a second case with no measured
   demand; option 1 already serves it (an exact name is a prefix of itself, plus
   its siblings).

**Evidence favours option 1.** It is the only shape consistent with the
measurement, and C5 shows option 2's precision is not achievable regardless.

**Sub-decision — the parameter name.** The `only=` sketched in §2 collides with
established Python meaning: SQLAlchemy's `load_only()` and Django's `only()` name
a *deferred* load, where unselected columns still exist on the object and are
transparently re-fetched on first access. Nothing here is deferred — rows outside
the prefix are simply absent. The "absent, not deferred" family is the right
prior art (`pandas.read_csv(usecols=…)`, `pyarrow.read_table(columns=…)`,
`ProjectionExpression`, and the library's own `keys_only=`, which names a result
shape rather than a loading strategy). `prefixes=` or `name_prefixes=` says what
it is; `only=` invites a reader who knows the ORMs to expect a lazy re-fetch that
will never come.

### Decision 2: Reuse `get_range`, or add a `get_prefix()` primitive?

1. **Reuse `get_range(lower, upper)`** with the library computing the sentinel.
   *Pro:* no protocol change, no new backend methods, both backends already
   implement it and it is already pinned by `tests/integration/test_db_property_range.py`.
   *Con:* no synthesised upper bound is exact for an arbitrary UTF-8 prefix
   (C5); it re-runs the `list:~`-class risk per family instead of removing it.
2. **Add `get_prefix()` to `DbPropertyProtocol`** — DynamoDB
   `Property.name.startswith(prefix)` (native `begins_with`), PostgreSQL
   `name COLLATE "C" >= prefix AND name COLLATE "C" < prefix||…` or a
   parameterised `LIKE` with escaping. *Pro:* exact by construction on DynamoDB
   for any prefix; the primitive then says what it means. *Con:* a new protocol
   method (a third implementation surface if a backend is ever added), plus
   PostgreSQL needs its own decision between a bound pair and a `LIKE` with
   `%`/`_`/`\` escaping on caller-supplied text.

Cross-cutting: whichever is chosen, **C3 applies** — `consistent_read=False`
must be passed explicitly, and pinned by a test.

### Decision 3: Where does the concurrency live?

The §2 latency win (1,224 ms → 700 ms) requires the K prefix reads to be issued
concurrently, and the library's database layer is synchronous.

1. **Caller-side** — one prefix per call; the caller runs them in its own
   threads, tasks or (as the consumer already does) separate HTTP endpoints.
   *Pro:* no threading in the library; matches the consumer's existing three
   independent endpoints. *Con:* the API then advertises a cost win only, and the
   latency half — described in §2 as the larger half — is the caller's problem.
2. **Library-side fan-out** — `only=[...]` takes a list and the implementation
   fans out over a thread pool. *Pro:* one call delivers both halves. *Con:*
   introduces a thread pool into a synchronous library, on a path also reached
   from FastAPI's async integration; and C7's skew window is then created by the
   library rather than chosen by the caller.
3. **Both** — accept a list, execute serially, and document that concurrent
   single-prefix calls are the way to get the latency win. *Pro:* no threads, and
   the multi-prefix ergonomics survive. *Con:* the obvious call shape is the slow
   one.

### Decision 4: Which public surfaces get the parameter?

`list_all()` (`actingweb/property.py:31`), `list_all_with_rows()` (`:53`), and
their interface wrappers (`actingweb/interface/property_store.py:539`, `:543`).
Not currently proxied by `AuthenticatedPropertyListStore`/`authenticated_views.py`
— only `prime_from_rows`/`to_list_from_rows` are (`:240-244`) — so whether a
scoped bulk read needs a permission-checked variant is an open question, and
Phase 2 of `2026-08-20-v2-positional-access-cost.md` was a security fix in
exactly this area. Also open: does `handlers/properties.py:471`'s `listall()`
gain a query parameter, or stay unscoped?

### Decision 5: Is C6 in scope for the same change?

Scoping `verify()`/`compact()`/`migrate_to_v2()` (C6) needs no public API and no
new tests of the public contract, and removes an O(N) partition-dump multiplier
from the maintenance scripts. It can ship in the same patch as Request A, or as
its own item. The argument for together: it exercises the new primitive from
inside the library before any consumer depends on it. The argument for apart: it
touches v1 migration paths, whose crash-recovery discipline is the subject of
`thoughts/todo/whole-list-rewrite-atomicity.md`.

### Decision 6: Does Problem B ship with the DynamoDB `get_bucket()` fix (B4)?

Honouring `_bucket_loaded` promotes DynamoDB's over-matching `get_bucket()` into
the answer for absence. Either fix `startswith(bucket)` →
`startswith(bucket + ":")` in the same change, or establish that no deployment
can have one bucket name that is a prefix of another — which
`remote:{peer_id}` (`actingweb/remote_storage.py:50`) makes hard to assert.
B3's falsy-delete divergence is a second, separable question: leave it as
recorded behaviour, or make `set_attr` mirror the backends' delete.

---

### Decision 7: What does a *partial* `rows` dict promise?

Today every consumer of `list_all_with_rows()` feeds the dict to
`prime_from_rows()` / `to_list_from_rows()` over lists it then touches
(`handlers/www.py:186`, `handlers/trust.py:1190`,
`handlers/properties.py:589-640`, `actor.py:2575-2577`), and all of them assume
it is a **complete** partition dump. A scoped read returns something that is not.
Traced through `actingweb/property_list.py:1011-1094`, the behaviour splits three
ways:

- **List entirely absent from the dict** (no `-meta` row): `prime_from_rows()`
  returns early at `:1039` and the lazy path applies unchanged — a later read
  hits the database. Correct, just not primed. This is the same behaviour
  `tests/test_hot_path_n_plus_one.py:189` already pins for the empty dict.
- **v1 list with `-meta` present but item rows absent**: `to_list_from_rows()`
  falls back to `self[i]` per missing row (`:1088-1091`) and raises
  `ListCorruptionError` only if the row is genuinely missing from *storage*.
  Correct, but a per-item read.
- **v2 list with `-meta` present but item rows absent**: the rank cache is built
  from rows matching the item prefix (`:1046-1052`) and
  `to_list_from_rows()`'s v2 branch is "derived entirely from `rows` — no
  fallback reads" (`:1064`, `:1071-1077`). So it returns `[]` **silently**, and
  `len()` reports 0.

Only the third is dangerous, and it is reachable only if a list's `-meta` row is
in the dict while its item rows are not. That gives the plan an **invariant to
state and test rather than a contract to redesign**:

> A scoped read must bound on the **list-name namespace** (`list:{prefix}`), so
> every list it returns a `-meta` row for also gets all of that list's item rows.
> It must never bound on a per-list sub-range that could separate the two.

Note also that `names` is *necessarily* scoped alongside `rows`: a scoped read
cannot produce the names of lists outside its prefix without paying for them,
which is the cost the request exists to avoid. So `(names, rows)` stays
internally consistent, and a caller iterating `names` never reaches the third
case. Decision 4 should record that as forced rather than chosen — and if
Decision 3 lands on caller-side concurrency, the same invariant has to survive a
caller merging several partial dicts, which it does as long as each was bounded
on a namespace prefix.

What still needs deciding: whether the existing method gains the parameter (its
docstring's "the actor's WHOLE partition" then becomes conditional) or a scoped
variant gets its own name so the complete-dump contract stays literally true.

---

## 8. Code References

- `actingweb/db/dynamodb/property.py:734-748` — `fetch_all_including_lists()`, unconstrained `Property.query(actor_id)`; PynamoDB's `consistent_read` default is `False`
- `actingweb/db/postgresql/property.py:793-834` — the same, `SELECT name, value FROM properties WHERE id = %s`; returns `None` (not `{}`) for zero rows
- `actingweb/db/dynamodb/property.py:700-732` — `fetch()`, the 3.14 precedent: the `list:`/`list;` sentinel pair
- `actingweb/db/dynamodb/property.py:491-528` — `get_range()`, `Property.name.between()`, `consistent_read: bool = True`
- `actingweb/db/postgresql/property.py:474-523` — `get_range()`, `name COLLATE "C" >= %s AND name COLLATE "C" <= %s`
- `actingweb/db/postgresql/property.py:630-667` — `get_last_in_range()`, `ORDER BY name COLLATE "C" DESC LIMIT 1`
- `actingweb/db/postgresql/schema.py:45-57` — `properties`: PK `(id, name)`, default collation, no secondary index
- `actingweb/db/protocols.py:185-244` — `DbPropertyProtocol.get_range` contract, incl. the sentinel requirement and the "no capacity saving on DynamoDB" note for `keys_only`
- `actingweb/db/protocols.py:453-477` — `DbPropertyListProtocol.fetch` / `fetch_all_including_lists`, both typed `dict[str, str] | None`
- `actingweb/property.py:31-52` — `PropertyListStore.list_all()`, dumps the partition and keeps only `-meta`
- `actingweb/property.py:53-87` — `list_all_with_rows()`, and the docstring declaring rows opaque and snapshot-stale
- `actingweb/interface/property_store.py:539`, `:543` — the interface wrappers
- `actingweb/property_list.py:45-83` — the sibling-collision comment block; `:154` `_v2_is_rank()`, `:82` `_V1_INDEX_RE`
- `actingweb/property_list.py:465`, `:536`, `:1664`, `:1697` — the four existing `get_range` callers whose `consistent_read` choices are pinned
- `actingweb/property_list.py:2743`, `:3013`, `:3180` — `verify()` / `compact()` / `migrate_to_v2()` dumping the partition for one list (C6)
- `actingweb/property_list.py:2578`, `:536` — `_v2_verify()` via `_v2_load_full()`, the scoped counterpart
- `actingweb/maintenance/migrate_property_lists.py:192`, `actingweb/maintenance/verify_property_lists.py:153` — the per-list loops that multiply C6
- `actingweb/handlers/properties.py:471` — `listall()`, direct partition dump
- `actingweb/handlers/www.py:170`, `actingweb/handlers/trust.py:1165` — the two handlers reaching it via `list_all_with_rows()`
- `actingweb/actor.py:2572` — `_get_full_state_for_subscription()`, library-API-only path
- `actingweb/attribute.py:77-99` — `get_bucket()`, sets `_bucket_loaded` at `:98`, returns `self.data` by identity at `:99`
- `actingweb/attribute.py:101-115` — `get_attr()`, the miss check that ignores the flag (`:110` is the polluting assignment, B2)
- `actingweb/attribute.py:205-214`, `:216-233` — `delete_attr` / `delete_attr_conditional`, both `del self.data[name]`
- `actingweb/attribute.py:235-248` — `delete_bucket()`, the only runtime reset of `_bucket_loaded`
- `actingweb/attribute.py:9-66` — `InternalStore`, the library's own get_bucket-then-read-the-dict bypass (B6)
- `actingweb/actor.py:89`, `:238`, `:398` — `Actor.store`, where that instance lives
- `actingweb/db/dynamodb/attribute.py:60-71` — `get_bucket()`'s `startswith(bucket)` over-match (B4); `:140-148` the falsy-delete branch (B3); `:358` the existing `t.bucket == bucket` compensation
- `actingweb/db/postgresql/attribute.py:199-206` — the exact-match counterpart; `:339-365` the falsy-delete branch
- `actingweb/remote_storage.py:50` — `remote:{peer_id}`, the variable-length bucket name B4 turns on
- `tests/test_v2_cost_plain_property_partition.py:82-97` — the non-ASCII list-name test that fails under a `~` sentinel
- `tests/test_property_list_integrity.py:733-830` — `TestV2LegacyHashSiblingIsolation`, the existing sibling-collision pins
- `tests/test_v2_consistent_read.py:32`, `:205-208` — the existing `consistent_read` call-kwarg pins
- `tests/test_v2_cost_library_callers.py:93-119`, `:139`, `:191`, `:215` — the `list_all_with_rows()` call-budget tests a scoped variant must not break
- `docs/guides/property-lists.rst:458-479` — "Reading Many Lists Cheaply", the prose a scoped variant has to extend

Consumer-side (`../actingweb_mcp`, for C2 only):

- `hooks/mcp/resources.py:108`, `:252`, `:392`; `hooks/mcp/services/ai_service.py:2004`; `repositories/local_memory_repository.py:689` — `getattr(actor.property_lists, memory_type)`, list names chosen at runtime
- `repositories/property_list_accessor.py:460-489` — the consumer's `list_all_with_rows()` wrapper

## 9. External References

Read capacity and projections — all three confirm §2's "keys-only saves no
capacity" measurement from the vendor side, which matters because the finding is
counter-intuitive enough that a reviewer will want a citation:

- [DynamoDB read and write operations](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/read-write-operations.html) — *"you can request a subset of attributes to retrieve. However, doing so has no impact on the item size calculations."*
- [Query — API Reference](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html) — *"The number of capacity units consumed will be the same whether you request all of the attributes … or just some of them"*; also *"the process of filtering does not consume any additional read capacity units."*
- [Using projection expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ProjectionExpressions.html) and [AttributesToGet (legacy)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/LegacyConditionalParameters.AttributesToGet.html) — the same statement for both parameter spellings.
- [Local secondary indexes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/LSI.html) — the one construct that *does* make a keys-only read cheaper is a keys-only **index**, charged on index-entry size. That is a schema change with write amplification, not a read flag.

Prefix reads and pagination:

- [Query — `KeyConditionExpression`](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html) — `begins_with(sortKeyName, :val)` is a first-class sort-key condition (String/Binary only, function name case-sensitive), and is a *key* condition rather than a filter, so it seeks rather than reads-and-discards. Cost-identical to `BETWEEN` over the same range.
- [Query — `ScanIndexForward`](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html) — *"For type String, the results are stored in order of UTF-8 bytes."* This is what makes `begins_with` exact for arbitrary prefixes and what makes PostgreSQL's `COLLATE "C"` the matching choice.
- [Query — `Limit` / `LastEvaluatedKey`](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html) — the 1 MB page cap, and that `LastEvaluatedKey` being non-empty does not imply more data (loop until it is absent). `Query` has no `Segment`/`TotalSegments`; only [`Scan`](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Scan.html) does — the API-level reason pages cannot be parallelised, independent of the `ExclusiveStartKey` data dependency.

PostgreSQL collation — the sourcing behind C4:

- [Collation Support](https://www.postgresql.org/docs/current/collation.html) — operators such as `<` use the input's collation; *"The `C` and `POSIX` collations … sort by byte values rather than natural language order."*
- [UTS #10, Unicode Collation Algorithm](https://www.unicode.org/reports/tr10/) — *"The position of characters in the Unicode code charts does not specify their sort order"*; punctuation is variable-weighted. [ICU: Ignore Punctuation Options](https://unicode-org.github.io/icu/userguide/collation/customization/ignorepunct.html) shows glibc-style primary-level punctuation ignoring (`"De Anza" = "De-Anza" = "DeAnza"`).
- [pgsql-general: "String comparison problem in select — too many results"](https://www.postgresql.org/message-id/20180114111407.dxtp2d3ip45oc2ju%40hjp.at) — the same failure on delimiter-separated keys; the thread's fix is `COLLATE "C"`. [A worked demonstration](https://gist.github.com/rraval/ef4e4bdc63e68fe3e83c9f98f56af7a4) shows `'a' < '{'` returning **false** under `en_CA.UTF-8`.
- [pgEdge, "What is a Collation, and Why is My Data Corrupt?"](https://www.pgedge.com/blog/what-is-a-collation-and-why-is-my-data-corrupt) — glibc 2.28 flipped the relative order of `'a-a'` and `'a+a'`. The stronger form of the rule: do not depend on *any* non-C punctuation ordering, because it is not stable across glibc versions, and ICU under PostgreSQL 15+ differs again (CLDR non-ignorable).
- [Index Types](https://www.postgresql.org/docs/current/indexes-types.html) and [Operator Classes](https://www.postgresql.org/docs/current/indexes-opclass.html) — a B-tree can serve an anchored `LIKE 'foo%'` **only** under the C locale or with `text_pattern_ops`, and *"you should also create an index with the default operator class if you want queries involving ordinary `<`, `<=`, `>`, or `>=` comparisons to use an index. Such queries cannot use the `xxx_pattern_ops` operator classes."* So predicate style and index must be chosen together; the library's `COLLATE "C"` range design and a `LIKE`/`text_pattern_ops` design are two coherent alternatives that must not be mixed.

psycopg3:

- [Passing parameters to SQL queries](https://www.psycopg.org/psycopg3/docs/basic/params.html) — *"When parameters are used, in order to include a literal `%` in the query you can use the `%%` string."* The opening clause is the whole rule; the boundary is `params is not None`, visible in `psycopg/_queries.py` (`PostgresQuery.convert`, and `_split_query`'s `collapse_double_percent`).
- If a `LIKE` predicate is ever introduced over caller-supplied text, `%`, `_` and the escape character must be escaped **in the parameter value** with an explicit `ESCAPE` clause — a list-name prefix containing `_` (which every family in §2 does: `memory_`, `output_`, `run_`) would otherwise match as a single-character wildcard. This is a distinct problem from `%%`, and the current `COLLATE "C"` range design has none of it.

API naming prior art (Decision 1's sub-decision):

- [SQLAlchemy, Column Loading Options](https://docs.sqlalchemy.org/en/20/orm/queryguide/columns.html) and [Django, `only()`/`defer()`](https://docs.djangoproject.com/en/stable/ref/models/querysets/#only) — both mean *deferred*: the column still exists and is silently re-fetched on access (SQLAlchemy offers `raiseload=True` because that is a footgun). Wrong connotation for a read that simply omits rows.
- pandas `read_csv(usecols=…)` / `read_sql(columns=…)`, pyarrow `read_table(columns=…)`, DynamoDB `ProjectionExpression`, PynamoDB `attributes_to_get=` — the "absent, not deferred" family, and the better precedent.
