# The library's own callers pay the v2 list cost we told the consumer to fix

**Status:** Open — unscheduled, and the cheapest item in the v2 cost cluster.
**Established in:**
[`thoughts/research/2026-08-20-v2-cost-in-library-callers.md`](../research/2026-08-20-v2-cost-in-library-callers.md)
— every site below verified first-hand at `2fe4693`.

**Why it is separate from rows 14 and 15.** Those are about the *primitive*
being expensive and about giving callers a better one. This is about **our own
callers using the primitive badly**, and it needs **no new API** — it is the
same caller-side fix the reference consumer already shipped for itself after the
2026-08-19 outage. It can land in a patch release without any decision from
[`list-delete-by-value-primitive.md`](list-delete-by-value-primitive.md) being
settled.

## The sites

### 1. The documented bulk API is the outage shape

`handlers/properties.py` — the `{"items": [...]}` path whose docstring at
`:798-801` presents it as *the* batch endpoint:

- `:1019` `projected_length = len(list_prop)` — 1 whole-list Query
- `:1113-1125` per update: `while len(list_prop) <= index` then
  `list_prop[index] = item_data` — 2 whole-list Queries each (the `while` guard
  evaluates at least once even when no append happens; `_v2_setitem` then forces
  a rank-cache reload)
- `:1143-1147` per delete: `if index < len(list_prop)` then
  `del list_prop[index]` — 2 whole-list Queries each
- `:1163` `to_list()` for the post hook — 1 more

**≈ `2k + 2` whole-list range Queries for a *k*-item request**, i.e. `O(k·n)` —
the same shape that ran 40.7 s and burned ~1.19M RCU on 2026-08-19, reachable
here without a consumer writing a positional loop at all. **This is the site
that matters most**; everything below is smaller.

### 2. `len()` on cold instances, to render counts

- `handlers/www.py:181-184` — one whole-list Query per list property, for
  `f"[List with {list_length} items]"` on the properties overview page
- `handlers/trust.py:1175-1180` — one per property name, for `item_count` on the
  peer-sharing view

Identical to the consumer's `count_items` defect, in the library.

### 3. Two `len()` calls per web-UI append, at any log level

`handlers/www.py:889-891`:

```python
logger.debug(f"List length before append: {len(list_prop)}")
list_prop.append(parsed_value)
logger.debug(f"List length after append: {len(list_prop)}")
```

Python evaluates the f-string before `logger.debug` is called, so **both
whole-list Queries run in production with DEBUG off**. Adding one item via the
built-in UI costs three whole-list reads (these two plus `_v2_append`'s own tail
read) for one point write. The cheapest fix on this page and the most clearly
wrong.

### 4. Bounds checks that double a single-item edit

`handlers/www.py:925` and `:956` — `len(list_prop)` immediately before a
positional write that forces its own reload. Two whole-list reads per
single-item UI update or delete.

Also `handlers/www.py:1032` — `_ = len(list_prop)` used as a side-effecting
metadata initialiser; works, but spends a whole-list Query to create an *empty*
list.

## The fix shapes, all already present in the codebase

- **Count without reading twice:** `handlers/www.py:353-354` already does it
  right — `list_items = list_prop.to_list()` then `len(list_items)`. One query,
  count in memory.
- **Read the whole list once, indexed:** `handlers/properties.py:1666`
  (`ListPropertyItemsHandler.get`) is already correct — one
  `to_indexed_list()`, then `len(indexed)`.
- **Prime from rows already fetched:** `prime_from_rows` /
  `to_list_from_rows`, used at `handlers/properties.py:509`, `:529`, `:560` —
  zero additional queries. **Read side only.** There is no `mutate_from_rows`
  counterpart, which is precisely the gap row 15 fills.

So sites 2, 3 and 4 are straightforward. Site 1's *read* half is too; site 1's
*write* half (`pending_updates` / `pending_deletes`) is the only part that would
be rewritten again when row 15 lands — see the open question below.

## Also in scope: the guide understates the cost

`docs/guides/property-lists.rst:109-118` already warns about positional access,
which is more than the consumer's report credited. Three gaps:

- *"two queries per item under v2"* reads as a constant factor of 2. The first
  of those two is a **whole-list** Query, so the overhead is O(n) per item, not
  O(1). This wording is very likely how the shape stayed invisible.
- **`len()` is not mentioned as a cost at all**, yet it is how every site above
  pays it — and it sits unannotated in the guide's own Basics example at `:19`
  (`count = len(notes)`).
- **`append()` is not mentioned.** `:99-100` presents it as the primitive; under
  v2 every append is a whole-list range read (`_v2_append` →
  `_v2_ensure_rank_cache`, always cold because `property.py:54` mints a fresh
  `ListProperty` per attribute access).

Three in-library docstrings assert the opposite of what DynamoDB does:
`property_list.py:288-289` and `:1105` (*"one keys-only range query"*) and
`db/protocols.py:216` (*"a cheaper projection read"*). A keys-only projection is
a real saving on PostgreSQL (`db/postgresql/property.py:492-501` issues
`SELECT name`) and **none at all** on DynamoDB, where
`db/dynamodb/property.py:504-514` is a base-table Query with
`attributes_to_get`. The AWS contract to correct them against is explicit —
*"For any operation that returns items, you can request a subset of attributes
to retrieve. However, doing so has no impact on the item size calculations"*
([Capacity unit consumption for read operations](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/read-write-operations.html)) —
so `protocols.py:216` can be rewritten to say "cheaper on PostgreSQL, no saving
on DynamoDB" rather than the flat claim it makes now.

## Open question

**Does site 1's write half get fixed now or once, later?** Sites 2–4 and site
1's reads can never be improved by a future API, so they are unconditional
wins. The `pending_updates`/`pending_deletes` loops are the one place that a
handle-based API (row 15) would rewrite a second time. Fixing them now costs a
duplicated edit; not fixing them leaves the documented bulk endpoint at
`O(k·n)` for at least one more release.

## Related

- Row 14 — the positional primitive's cost, in
  [`dynamodb-known-next.md`](dynamodb-known-next.md) item 2 with the 2026-08-19
  incident. **This file is its caller-side half**, and unlike row 14 it is
  actionable without any design work.
- Row 15 — [`list-delete-by-value-primitive.md`](list-delete-by-value-primitive.md).
  Site 1's write loop is the library's own instance of the caller shape that
  file exists to retire.
- Row 5 — [`property-fetch-reads-whole-partition.md`](property-fetch-reads-whole-partition.md).
  Different query, different defect; `prime_from_rows` is the pattern both
  files point at.
