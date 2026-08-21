# Research: the library's own callers pay the v2 list cost it told the consumer to avoid

**Date:** 2026-08-20
**Branch:** research/v2-positional-access-cost
**Commit:** 2fe4693

## Research Question

`actingweb_mcp`'s maintainer filed
`actingweb_mcp/thoughts/research/2026-08-20-v2-list-read-cost.md` after the
2026-08-19 outage. Most of it is about their own repo, but a block of it —
explicitly labelled *"Findings carried from the audit agent, not re-verified
here"* — makes claims about **this** library, with line numbers the document
itself says are approximate.

Which of those claims hold first-hand, which belong to this library, and what
work do they create here?

This is a **verification and ownership pass**, not a second design pass. The
design question — what the library should build — was answered the same day in
[`2026-08-20-v2-positional-access-cost.md`](2026-08-20-v2-positional-access-cost.md)
(options A–G, Decisions 1–5). That document is not re-litigated here. Where a
verification **moves** one of its decisions, this document says which decision
and which way.

## Summary

**Six of the seven library-side claims hold. The headline is that the library's
own callers commit the exact defect the consumer was told to fix in its own
code.** The consumer's `count_items` called `len()` on a cold list to render a
count badge; `handlers/www.py:183` does the same thing on the built-in web UI,
and `handlers/trust.py:1180` does it once per list property when rendering what
a peer may subscribe to. The consumer's `delete_memory_items` looped positional
deletes; `handlers/properties.py:1113-1147` — the library's **documented bulk
API**, `{"items": [...]}` — does the same, at roughly `2k + 2` whole-list range
Queries for a *k*-item request. That reframes rows 14 and 15 from "a primitive
consumers would like" into "our own endpoints need it", and it means a
consumer can hit the 2026-08-19 shape without writing a positional loop at all,
simply by calling the bulk endpoint the docs recommend.

**Two findings change decisions in the earlier document.** Option C
(`last_rank` hint to make `append()` O(1)) was recorded there as *"plausible
and cheap, not verified — trace the retry loop before planning on it."* Traced:
**the existing retry does not cover a stale hint.** `_v2_append`'s loop reacts
only to a `create_if_not_exists` collision, and the dangerous case produces no
collision — a stale hint whose successor rank was *deleted* generates a key
that lands **mid-list**, silently out of order. Option C as sketched is unsafe;
a monotonic **high-water mark** is the safe variant, and it needs a conditional
meta-row update the library does not have. Separately, Decision 1's handle API
splits cleanly on the Postgres question the earlier document listed as *"not
evaluated"*: `delete_by_handle` is composable **today** on both backends, but
`update_by_handle` is **blocked on a primitive that does not exist** —
`DbPropertyProtocol` has a conditional *create* and a conditional *delete* and
**no conditional set**.

One claim is a live functional bug and has nothing to do with v2:
`AuthenticatedPropertyListStore.create()` and `.delete(name)` raise
`TypeError: 'NotifyingListProperty' object is not callable` on every call. It
has been broken since 2025-12-14, has no callers, no tests and no docs in this
repo, and is exported from `actingweb.interface`.

## Detailed Findings

### The library's own bulk API is the outage shape — CLAIM HOLDS

The consumer reported this as one-hop at `handlers/properties.py:1112-1151`.
The line numbers are close; the mechanism is worse than stated because the
`len()` calls were not counted.

`handlers/properties.py:1019` opens the batch with one `len(list_prop)`:

```python
projected_length = len(list_prop)
```

Then pass 1, per update (`:1113-1125`):

```python
for index, item_data in pending_updates:
    while len(list_prop) <= index:
        list_prop.append(None)
    list_prop[index] = item_data
```

and pass 2, per delete (`:1143-1147`):

```python
for index in sorted(pending_deletes, reverse=True):
    if index < len(list_prop):
        del list_prop[index]
```

closing with `current_items = list_prop.to_list()` at `:1163` for the post hook.

Under v2 on an *n*-row list, each of those is a whole-list range Query:
`len()` has no stored length to read (`__len__` → `_v2_ensure_rank_cache`), and
`_v2_setitem`/`_v2_delitem` each call `_v2_ensure_rank_cache(force=True)` before
acting. The `while len(...)` guard evaluates at least once per update even when
no append happens. So a *k*-item batch costs approximately:

| Step | whole-list Queries |
| --- | --- |
| `projected_length = len(list_prop)` | 1 |
| per update: `while len(...)` + forced reload in `_v2_setitem` | 2 each |
| per delete: `if index < len(...)` + forced reload in `_v2_delitem` | 2 each |
| `to_list()` for the post hook | 1 |
| **total** | **≈ 2k + 2** |

This is the same `O(k·n)` shape that produced 40.7 s and ~1.19M RCU on
2026-08-19 — reached here through the library's own endpoint rather than
through consumer code. The docstring at `:798-801` presents it as the batch
path (*"`{"items": [...]}` against a list ... regardless of the order items"*),
so a consumer following the documentation lands on it.

**The good pattern exists in the same file and is read-side only.**
`prime_from_rows` (`property_list.py:588`) is called at
`handlers/properties.py:509`, `:529` and `:560`, always paired with
`to_list_from_rows`, and it works by priming a `ListProperty` from a
partition dump the handler already fetched — **zero additional queries**. It is
a genuine template for the *read* side (and `ListPropertyItemsHandler.get` at
`:1666` is already correct: one `to_indexed_list()`, then `len(indexed)`
in memory). It is **not** a template for the write side: there is no
`mutate_from_rows` counterpart, and the earlier document's option A is exactly
what such a counterpart would need. Verdict on the consumer's "template for
fixing the above": **half right** — right that it is the good pattern, wrong
that it fixes the bulk write path.

Two adjacent single-item sites, both correct-as-designed but each one forced
reload: `handlers/properties.py:223` (`item = list_prop[index]`, GET by index)
and `:674` (`list_prop[index] = item_value`, PUT by index).

### The web UI renders count badges the expensive way — CLAIM HOLDS

`handlers/www.py:181-184`, inside a loop over every property:

```python
list_prop = getattr(myself.property_lists, prop_name)
list_length = len(list_prop)
display_properties[prop_name] = f"[List with {list_length} items]"
```

One whole-list range Query per list property, to render a badge — the
`count_items` defect, in the library. The properties overview page therefore
costs one whole-list read per list the actor owns.

`handlers/trust.py:1175-1180` is the same shape on the peer-sharing view:

```python
prop_list = getattr(actor_interface.property_lists, prop_name, None)
if prop_list and hasattr(prop_list, "__len__"):
    item_count = len(prop_list)
```

again once per property name, after `list_all()` enumerated them.

**A third site is worse and was not in the consumer's list.**
`handlers/www.py:889-891`:

```python
logger.debug(f"List length before append: {len(list_prop)}")
list_prop.append(parsed_value)
logger.debug(f"List length after append: {len(list_prop)}")
```

Python evaluates an f-string **before** calling `logger.debug`, so both
`len()` calls run at any log level. Adding one item through the built-in web UI
costs **three** whole-list range Queries (two debug counts plus `_v2_append`'s
own tail read) for one point write, in production with DEBUG off.

`handlers/www.py:925` and `:956` each spend a `len()` on a bounds check
immediately before a positional write that forces its own reload — two
whole-list reads per single-item UI edit.

For contrast, `handlers/www.py:353-354` is **correct** and shows the fix shape:
`list_items = list_prop.to_list()` then `list_length = len(list_items)` — one
query, count taken in memory. And `handlers/www.py:1032` uses `_ = len(list_prop)`
deliberately as a side-effecting metadata initialiser, which works but spends a
whole-list Query to create an empty list.

### `clear()`/`delete()` — CLAIM HOLDS, with the mechanism named

On a v2 list, both methods (`property_list.py:1166`, `:1210`) run
`_invalidate_cache()` then `sweep_foreign_format_rows()` then their own scan.
`sweep_foreign_format_rows` (`:1144-1150`) reads the meta row and branches:

```python
stored = self._read_meta_row()
if stored is None:
    names = self._v1_item_names_in_range() + self._v2_item_names_in_range()
elif int(stored.get("format", 1) or 1) == 2:
    names = self._v1_item_names_in_range()
```

So a healthy v2 list pays a range Query over the **v1** byte range that is
structurally guaranteed to return nothing on an all-v2 fleet, plus
`_v2_item_names_in_range()`'s own range Query, plus one meta `GetItem`, plus
*n* serial `set(value=None)` point deletes. **2 range Queries + 1 GetItem + n
serial deletes**, one of the two range Queries always empty. That matches the
consumer's "0 → 2 range queries plus an always-empty v1 sweep".

The sweep is not gratuitous — its docstring records that cross-format residue
is invisible to `exists()`/`list_all()` until a new list adopts it as its own
items. What is available is skipping it when the list's own metadata says no
format change was ever interrupted. The *n* serial deletes are item 1 of
[`dynamodb-known-next.md`](../todo/dynamodb-known-next.md) (`batch_write`),
unchanged.

### `AuthenticatedPropertyListStore.create()`/`delete()` raise `TypeError` — REAL BUG

Not a cost finding, and not a v2 side effect. `interface/authenticated_views.py:252-259`:

```python
def create(self, name: str, **kwargs: Any) -> Any:
    self._check_permission(name, "write")
    return self._store.create(name, **kwargs)

def delete(self, name: str) -> bool:
    self._check_permission(name, "delete")
    return self._store.delete(name)
```

`self._store` is `interface/property_store.py:404` `PropertyListStore`, built at
`authenticated_views.py:422`. That class defines exactly three things —
`exists`, `list_all`, and `__getattr__` (`:427-437`), which returns a
`NotifyingListProperty` for **any** non-underscore name. It has no `create` and
no `delete`. Neither `NotifyingListProperty` nor `ListProperty` defines
`__call__`.

So both methods resolve to a list object named `"create"` / `"delete"` and then
call it: `TypeError: 'NotifyingListProperty' object is not callable`, after the
permission check has passed. The same holds one layer down — `property.py:15-67`
`PropertyListStore` also defines only `exists`, `list_all`, `__getattr__`.

`create()` is arguably redundant (lists are created lazily on first write), but
**`delete(name)` is a real operation with a real implementation** —
`ListProperty.delete()` at `property_list.py:1210`. The wrapper simply reaches
for it wrongly; `getattr(self._store, name).delete()` is what it means.

Reachability: `grep` finds **no callers, no tests and no documentation** for
either method anywhere in the repo. It is exported from `actingweb.interface`
(`interface/__init__.py:19,64`), so it is reachable only by an application
developer using the permission-enforcing view. Introduced 2025-12-14 (`30216d1`),
untouched since 2026-01-30 (`6be6158`) — it predates v2 entirely and has never
worked.

### `ListAttribute` has no v2 code — CLAIM HOLDS, and is already filed

`attribute_list.py` still stores `list:{name}:{index}` with an authoritative
`length` in metadata (`:79`, `:132`, `:214-221`) and shifts on delete/insert
(`:293-309`). No `_v2` symbol appears in `attribute_list.py` or
`attribute_list_store.py`. `RemotePeerStore` (`remote_storage.py:53`, using
`AttributeListStore` at `:103`) is the consumer of it, reached from
`actor.py:1390` and `:1759` on subscription and trust teardown.

The consumer's framing — *"the migration left it behind rather than making it
worse"* — is right, and it is the **cost** reading: `len()` there is genuinely a
metadata read (`attribute_list.py:218`, *"Get list length from metadata only
(no item loading)"* — true, unlike the v2 property-list case). The correctness
reading is the opposite and is already row 4 of the index,
[`attribute-list-shift-design.md`](../todo/attribute-list-shift-design.md), with
**option 3 (full v2 port) decided on 2026-08-14**. Nothing new here; noted so
the two readings are not confused when that row is picked up. If the port
happens, it inherits this cost profile — which is an argument for designing the
handle API and the port together, as that file already says.

### Where the cost claims come from, and what is verified about them

The RCU figures below are the consumer's, **measured against production**,
not re-measured here:

| Fact | Value |
| --- | --- |
| one 81-row list, range read, consistent | 241 RCU |
| same, keys-only projection | 241 RCU (no saving) |
| same, eventually consistent | 120.5 RCU |
| the actor's entire 1,190-row partition | 254 RCU |
| largest list, bytes in one page | 964 KB (94% of the 1 MB Query limit) |

**The mechanism behind the keys-only result is confirmed first-hand here**, and
it is the one way the claim could have been narrower than stated. A keys-only
*secondary index* would genuinely be cheaper; a `ProjectionExpression` on a
*base table* is not. `db/dynamodb/property.py:504-514` settles it — this is a
base-table `Property.query` with `attributes_to_get`, no index:

```python
condition = Property.name.between(lower, upper)
attributes_to_get = ["name"] if keys_only else ["name", "value"]
for item in Property.query(
    actor_id,
    range_key_condition=condition,
    consistent_read=True,
    attributes_to_get=attributes_to_get,
):
```

`consistent_read=True` is hardcoded with no caller opt-out, confirming the
earlier document's option D needs a parameter. PostgreSQL genuinely projects —
`db/postgresql/property.py:492-501` issues `SELECT name` under `keys_only` —
so `keys_only` is a real saving there and a false economy on DynamoDB, exactly
as claimed. Three in-library docstrings assert the false version:
`property_list.py:288-289` (*"one keys-only range query"*),
`property_list.py:1105` (*"via one keys-only range read"*), and
`db/protocols.py:216` (*"a cheaper projection read"*).

**The AWS citation exists and is explicit**, from *Capacity unit consumption
for read operations*:

> *"For any operation that returns items, you can request a subset of
> attributes to retrieve. However, doing so has no impact on the item size
> calculations. In addition, `Query` and `Scan` can return item counts instead
> of attribute values. Getting the count of items uses the same quantity of
> read units and is subject to the same item size calculations. This is because
> DynamoDB has to read each item in order to increment the count."*

So the consumer's 241 = 241 measurement is the documented behaviour, not an
artefact, and the three docstrings above can be corrected against a quotable
contract. The same page states the 2× that option D turns on — *"A strongly
consistent read request of an item up to 4 KB requires one read unit. An
eventually consistent read request of an item up to 4 KB requires one-half read
unit."*

**Two further quotes from that page bear on the earlier document's Decision 2**
(what a batch delete uses underneath), and both push away from
`TransactWriteItems`:

> *"DynamoDB performs two underlying writes for each item — one to prepare the
> transaction and one to commit it — so a transactional write of an item up to
> 1 KB consumes two write units. **This capacity is consumed even when the
> transaction is canceled** (for example, because a condition check fails)."*

A transactional conditional batch therefore costs 2× per row **and** burns the
full amount again on every all-or-nothing abort — so a single concurrently
modified row makes the whole batch pay twice and accomplish nothing. That
sharpens "all-or-nothing" from an ergonomic objection into a cost one.

The same holds, more mildly, for the k-sequential-conditional-deletes shape
option A rests on:

> *"If the expression evaluates to false, DynamoDB still consumes write capacity
> units from the table."*

A losing conditional delete is not free. It is still far cheaper than the
whole-list read it replaces, but a handle API's retry loop should not be
written as though failed attempts cost nothing.

### What the guide already says, and where it is short

`docs/guides/property-lists.rst:109-118` already carries a v2 cost warning,
which is more than the consumer's document credits:

> *"reading items one at a time by index costs more under v2 ... a
> `for i in range(len(lst)): lst[i]` loop is two queries per item under v2,
> where v1 was one. Use `to_list()`, `to_indexed_list()` or plain iteration
> instead"*

Three gaps. **"Two queries per item" reads as a constant factor of 2** when the
first of the two is a whole-list Query whose cost scales with *n* — the
sentence describes an O(1) overhead where the defect is O(n). **`len()` is not
mentioned at all** as a cost, yet it is the single most common way the library's
own handlers pay it, and it sits unannotated in the guide's own Basics example
at `:19` (`count = len(notes)`). **`append()` is not mentioned**: `:99-100`
presents `notes.append(...)` as the primitive with no note that under v2 each
append is a whole-list range read (`_v2_append` → `_v2_ensure_rank_cache`, cold
because `property.py:54` mints a fresh `ListProperty` per attribute access).

### Option C (`last_rank`) is unsafe as sketched — this MOVES Decision 3

The earlier document recorded option C as *"plausible and cheap, not verified.
The retry loop's exact behaviour under a bad hint has not been traced."* Traced
now, at `property_list.py:1004-1029`:

```python
for attempt in range(_V2_MAX_RANK_RETRIES):
    ranks = self._v2_ensure_rank_cache(force=(attempt > 0))
    last = ranks[-1] if ranks else None
    candidate = fi.generate_key_between(last, None)
    ...
    if item_db.create_if_not_exists(..., name=self._v2_item_name(candidate), ...):
        ranks.append(candidate)
        self._v2_touch_metadata()
        return
    # Collision: another writer took this rank ...
```

**The loop reacts to exactly one signal: a `create_if_not_exists` collision.**
That covers the case the comment names — a concurrent appender took the rank —
because consecutive appends fill consecutive keys, so a stale hint's successor
is usually occupied.

It does **not** cover the case where the successor was *deleted*. Take ranks
`a1..a5`, a hint that has gone stale at `a2`, and `a3`/`a4` since removed.
`generate_key_between("a2", None)` yields `a3`; `a3` no longer exists, so
`create_if_not_exists` **succeeds**, no collision fires, no retry happens — and
the appended item lands between `a2` and `a5`, i.e. **silently in the middle of
the list**. Deleting from a list is ordinary traffic, so this is not an exotic
interleaving.

The stale-hint hazard is therefore real and the existing machinery does not
catch it. It is not fatal to the idea: storing a **monotonic high-water mark**
(the greatest rank ever issued in this list generation, never lowered by a
delete) instead of "the last rank" makes every generated key strictly greater
than every rank in use, so a mid-list landing becomes unrepresentable and the
only remaining failure is a genuine collision — which the existing loop already
handles. That variant costs two things the sketch did not budget for: the
meta-row update must be **monotonic** (a last-writer-wins regression re-opens
the hazard, and the meta row is already the contention point the GA plan's
stale-metadata defect lives on), and rank keys grow without bound within a
generation, which leans on `compact()` and the existing `_V2_RANK_MAX_LEN`
guard at `:1009-1013`.

**Effect on Decision 3** ("does C ship independently?"): as sketched, no — it
is a correctness risk, not a cheap win. As a high-water mark, it is still
independent of option A but is no longer nearly free, because it needs a
conditional meta-row write.

### The handle API splits on Postgres — this SHARPENS Decisions 1 and 2

The earlier document listed the Postgres backend under "not evaluated". It
divides option A cleanly in two.

`DbPropertyProtocol` (`db/protocols.py`) declares seven property methods:
`get`, `get_actor_id_from_property`, `set`, `delete`, `get_range`,
`create_if_not_exists` (`:229`) and `delete_if_value_equals` (`:256`). There is
a conditional **create** and a conditional **delete**, and **no conditional
set**.

- **`delete_by_handle` is composable today, on both backends.**
  `delete_if_value_equals` is implemented in both — DynamoDB at
  `db/dynamodb/property.py:543`, PostgreSQL at `db/postgresql/property.py:552`
  as a single atomic statement:

  ```sql
  DELETE FROM properties
  WHERE id = %s AND name = %s AND value = %s
  ```

  with `deleted = cur.rowcount == 1`. Semantics match: both return `False` for
  both "changed" and "already gone", which the protocol docstring at `:256-291`
  explicitly declares equivalent to the caller. And the protocol already states
  the constraint a handle API must carry — *"`value` must be the RAW STORED
  STRING the caller read, not a re-serialization of a decoded value"*.

- **`update_by_handle` is blocked on a primitive that does not exist.** It needs
  compare-and-swap — write only if the row still holds the bytes read — and
  nothing in the protocol expresses it. That is a new method on
  `DbPropertyProtocol` plus two implementations. On PostgreSQL it is one
  `UPDATE ... WHERE value = %s`; on DynamoDB a `ConditionExpression` on
  `UpdateItem`. Neither is hard; both are new public backend surface, so this is
  a scoping fact for Decision 1, not a blocker.

The protocol docstring also records, at `:279-282`, why the positional methods
deliberately skip the conditional path — *"'delete whatever is at position i'
and last-writer-wins are both satisfied by an unconditional write"* — which is
the clearest statement anywhere in the codebase of why positions and handles are
different guarantees, not just different spellings.

**A naming precedent already exists for option B.** `ListProperty.verify()`
takes `identity_key` (`property_list.py:1754`, *"Optional field name that
identifies an item within your data (`"id"`, `"uuid"`, ...)"*) and reports
`duplicate_identities`. The library has already accepted that items carry an
identity field and already named the parameter. `remove_where(key, value)`
should reuse `identity_key` rather than invent a second word for the same idea —
and `verify()`'s duplicate reporting is the existing answer to that file's open
"what does a duplicate id even mean" question.

No public method on `ListProperty` or either `PropertyListStore` exposes a rank
today; `to_indexed_list()` (`:1327`) is the closest and is explicitly positional.

## Decisions Needed

### Decision A: Do the library's own callers get fixed independently of rows 14/15?

The bulk API, `www.py` and `trust.py` sites need **no new library API** — they
are the same caller-side fix the consumer already shipped (`to_indexed_list()`
once, count in memory, mutate from the primed rows). They could ship in the
next patch release.

**Options:**
1. **Fix the callers now, independently.** Removes a documented endpoint that
   reproduces the outage shape, and stops the built-in web UI costing a
   whole-list read per badge. Does not need Decisions 1–5 resolved.
2. **Hold until the handle API lands**, then fix the callers onto it once.
   Avoids touching `handlers/properties.py:1113-1147` twice, but leaves the
   documented bulk endpoint at `2k + 2` whole-list reads for at least one
   release.

**Evidence:** the read-side fixes (`len()` → `to_list()`/`to_indexed_list()`)
are strictly caller-local and cannot be improved by any future API. The bulk
*write* loop is the only part that would be rewritten twice.

### Decision B: What happens to `AuthenticatedPropertyListStore.create()`/`delete()`?

**Options:**
1. **Fix both** — `delete(name)` becomes `getattr(self._store, name).delete()`;
   `create(name)` either materialises the list or is removed.
2. **Delete `create()`, fix `delete()`** — `create()` has no meaning under lazy
   list creation, and removing an exported method that has never worked breaks
   nobody.
3. **Leave it and file it** — no callers exist in this repo.

**Evidence:** it is on the permission-enforcing public interface, has been
broken for eight months, and has no test. Whatever is chosen, it is not a v2
matter and should not be sequenced behind the cost work.

### Decision C: Does the `last_rank` hint survive at all, and in which form?

Restated from the earlier Decision 3 now that the trace exists. The naive form
is unsafe. The high-water-mark form is safe but needs a monotonic meta-row
update, which is adjacent to the stale-metadata defect that row 9c already
tracks.

**Options:**
1. **High-water mark**, designed together with row 9c's meta-row read/dispatch
   fix, since both are about the meta row being written from stale state.
2. **Drop option C** and let option A's batch shapes carry the saving —
   `append()` is not on the positional path, so A does not help it, and every
   append keeps its whole-list read.
3. **Document the append cost** and defer, which is the zero-risk move.

### Decision D: Does `update_by_handle` ship in the same release as `delete_by_handle`?

`delete_by_handle` needs no new backend surface; `update_by_handle` needs a new
conditional-set primitive on `DbPropertyProtocol` and both backends. Splitting
them gets the delete path — which is what both incidents were about — out
sooner. Keeping them together means the protocol changes once.

## Code References

- `actingweb/handlers/properties.py:1019,1113-1125,1143-1147,1163` — the bulk
  `{"items": [...]}` path, ≈`2k + 2` whole-list Queries per request
- `actingweb/handlers/properties.py:798-801` — its docstring, presenting it as
  the batch API
- `actingweb/handlers/properties.py:509,529,560` — `prime_from_rows`, the good
  read-side pattern with no write-side counterpart
- `actingweb/handlers/properties.py:1666` — `to_indexed_list()` then in-memory
  count; already correct
- `actingweb/handlers/www.py:181-184` — `len()` per list property for a badge
- `actingweb/handlers/www.py:889-891` — two eagerly-evaluated `len()` in
  `logger.debug` f-strings around an append
- `actingweb/handlers/www.py:925,956` — `len()` bounds check before a forced
  positional write
- `actingweb/handlers/www.py:353-354` — the correct shape, for contrast
- `actingweb/handlers/trust.py:1175-1180` — `len()` per property on the peer
  sharing view
- `actingweb/interface/authenticated_views.py:252-259` — `create()`/`delete()`,
  both `TypeError`
- `actingweb/interface/property_store.py:404-437` — the wrapped store: `exists`,
  `list_all`, `__getattr__`, nothing else
- `actingweb/property.py:15-67` — the core store, same three members
- `actingweb/property_list.py:1004-1029` — `_v2_append`'s retry loop, collision
  only
- `actingweb/property_list.py:1144-1150` — `sweep_foreign_format_rows`'s
  always-empty v1 branch on a v2 list
- `actingweb/property_list.py:1166,1210` — `clear()`/`delete()`, 2 range Queries
  + n serial deletes
- `actingweb/property_list.py:1754` — `verify(identity_key=...)`, the naming
  precedent for `remove_where`
- `actingweb/db/dynamodb/property.py:504-514` — base-table Query with
  `attributes_to_get`, `consistent_read=True` hardcoded
- `actingweb/db/postgresql/property.py:492-501` — `SELECT name`, a real
  projection
- `actingweb/db/postgresql/property.py:552-585` — atomic conditional delete
- `actingweb/db/protocols.py:229,256` — conditional create and conditional
  delete; no conditional set anywhere in the protocol
- `actingweb/db/protocols.py:279-282` — why positional writes deliberately skip
  the conditional path
- `actingweb/attribute_list.py:79,132,214-221,293-309` — v1-only, authoritative
  `length`, shift loop
- `docs/guides/property-lists.rst:19,99-100,109-118` — the existing warning and
  its three gaps

## External References

- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/read-write-operations.html>
  — fetched for this document. Capacity is charged on items read, **not** on
  attributes returned (*"requesting a subset of attributes ... has no impact on
  the item size calculations"*); the strong/eventual 2×; transactional writes
  cost two write units per item **and consume that capacity even when the
  transaction is cancelled**; a conditional write whose expression evaluates to
  false still consumes write capacity

Both DynamoDB API facts the earlier document relies on were verified there and
are not re-fetched:

- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchWriteItem.html>
  — no conditions on batch put/delete; 25 items / 16 MB
- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html>
  — 100 actions, 4 MB, conditional `Delete`, all-or-nothing

## Confidence

**Verified first-hand for this document:** every claim above and every code
reference, read directly from the working tree at `2fe4693`. The
`TypeError` bug including its absence of callers, tests and docs, and its
introduction date from `git log -S`. The `_v2_append` retry trace and the
stale-hint hazard. The conditional-primitive inventory across
`protocols.py` and both backends. The base-table-vs-index question behind the
keys-only result. The `clear()`/`delete()` query counts.

**Measured by the consumer, not re-measured here:** every RCU figure and the
964 KB page finding. Source:
`actingweb_mcp/thoughts/research/2026-08-20-v2-list-read-cost.md`.

**Not evaluated:** the actual per-request cost of the `www.py`/`trust.py` sites
in RCU on a real deployment — the shape is established, the magnitude is
inferred from the consumer's per-list figures. The consumer's own repo
(`memory_service`, the four unenforced `maxItems: 25` caps, `reference_rewriter`,
the create-then-update double write) is theirs and is deliberately untouched
here.
