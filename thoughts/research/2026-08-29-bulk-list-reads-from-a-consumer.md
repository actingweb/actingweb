# Research: bulk list reads, measured from a consumer

**Date:** 2026-08-29
**Branch:** master
**Commit:** 36254ca
**Measured against:** ActingWeb **3.14.0** on DynamoDB (`AI_*`, eu-central-1).
Re-checked at the consumer's current pin, **3.14.2**: nothing in 3.14.1 or
3.14.2 touches the property or property-list read path, so the numbers hold.
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
**1,361 RCU across 11 sequential Query pages**; the eight families its pages
actually render measure **686 RCU across 8 independent queries** — half the
capacity, and issuable concurrently rather than chained. The primitive already
exists (`get_range`); what is missing is a way to reach it through the public
list API without the caller encoding row names.

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
which a prefix-scoped read simply excludes — that exclusion *is* how the 686
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

Reading the eight families the consumer's pages need: **686 RCU across 8
queries**, against 1,361 across 11. Two findings worth carrying:

1. **A keys-only projection saves no capacity at all** — 1,361.0 RCU either
   way. Capacity is charged on items read, before projection. It cuts wall time
   (453 ms vs ~1,300 ms) because the bytes still travel, but it is not a cost
   fix. Anyone reaching for `attributes_to_get` as the answer here should see
   this number first.
2. **The 8 queries are independent; the 11 pages are not.** Pagination is a
   chain — each page needs the previous page's `LastEvaluatedKey`. Eight range
   reads have no such dependency and can be issued concurrently: measured 1,224
   ms serial vs **700 ms concurrent** from the same laptop, where the uplink
   rather than the database is the limiter. So this is a latency request as
   well as a cost one, and the latency half is the larger of the two for a page
   load.

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

**Do not add this to Problem A's saving.** The 686-RCU figure in §2 is derived
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
