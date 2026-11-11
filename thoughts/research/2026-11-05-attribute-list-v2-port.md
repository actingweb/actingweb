# Research: porting `ListAttribute` to the v2 fractional-rank format

**Date:** 2026-11-05
**Branch:** docs/3-16-rollup-records
**Commit:** fea9e42

Source: `thoughts/todo/attribute-list-shift-design.md` (High leverage in
`thoughts/todo/INDEX.md`). The todo fixes the approach (the full v2 port) and
leaves the sequencing against `thoughts/todo/whole-list-rewrite-atomicity.md`
open.

## Research Questions

1. **Is this a port, a duplication, or an extraction of a shared core?** The
   coupling is to the storage protocol and the value encoding, not to anything
   property-specific: `ListProperty` v2 rests on seven `DbProperty` primitives
   the attribute layer does not declare, and on item values being raw strings.
   See "What v2 rests on" and "The attribute storage layer".
2. **What does the attribute layer offer on both backends?** Point reads and
   writes, a whole-bucket read, and three conditional operations whose
   semantics differ from the property ones. No range, prefix, last-in-range,
   value-conditional delete or batch delete. See the gap table.
3. **Who uses `ListAttribute`?** Only `RemotePeerStore`, in `remote:{peer_id}`
   buckets, in the library and in both consumers. Every attribute list found is
   a subscription replica. See "Who uses it".
4. **What do the receiver's operations cost today and under ranks?** Today
   `insert(k)` and `delete(k)` are O(n−k) point reads and one to two writes per
   shifted item; under ranks each positional operation is one whole-list key
   read and one write. See "Receiver cost".
5. **Does a replica need `compact()`?** Rank length grows logarithmically
   under appends and front-inserts (5 characters at 3 million) and linearly
   only for inserts into one gap (the 180-character cap after about 900 to
   1,070 such inserts). A resync rewrites the replica wholesale. See "Rank
   growth".
6. **What does the diff vocabulary look like on both sides?** Ten operations,
   closed; the receiver handles every one the notifying wrapper emits. The REST
   handlers emit a second shape without `list`/`operation` that the receiver
   stores as scalars. See "Diff vocabulary".
7. **What happens to a failed list operation on the callback path?** A
   `DbError` answers 503 and the diff can be applied twice; any other exception
   is recorded in a result dict nobody reads, and the sequence advances. See
   "Fault handling on the callback path".
8. **Is there an operator surface?** None for attribute lists; the two
   property-list tools construct `ListProperty` only. See "Operator surface".
9. **Which constraints from earlier work apply?** See "Constraints inherited".
10. **Which tests and docs state the v1 layout?** Four test files assert it;
    no `docs/` page mentions `ListAttribute`. See "Tests" and "Documentation
    Impact".

## Summary

`ListAttribute` (`actingweb/attribute_list.py`, 683 lines) stores a list as
attribute rows `list:{name}:{index}` plus `list:{name}:meta` holding an
absolute `length`. `insert()` (`:551-644`) and `__delitem__()` (`:288-387`)
move every later item with separate writes and update `length` last. It is
constructed in one place, `AttributeListStore.__getattr__`
(`attribute_list_store.py:102`), which is constructed in one place,
`RemotePeerStore._get_list_store` (`remote_storage.py:100-110`), always with
bucket `remote:{peer_id}`. Both consumers use it the same way. So the
population is subscription replicas: derived data that `set_list` already
rewrites wholesale on every resync (`remote_storage.py:156-182`).

`ListProperty` v2 (`actingweb/property_list.py`, 5,921 lines) contains no
HTTP, permission or `register_diffs` code; those live in wrappers. What binds
it to properties is the storage protocol: `get_range`, `get_prefix`,
`get_last_in_range`, `create_if_not_exists`, `set_if_value_equals`,
`delete_if_value_equals` and `batch_delete` (`db/protocols.py:343-670`), plus
the assumption that an item row's value is a raw string a compare-and-swap
matches byte for byte. `DbAttributeProtocol` (`db/protocols.py:1251-1541`)
declares none of the seven; its conditional operations compare JSON-normalised
data, fold a fault to `False` where the property ones raise, and
`create_attr_if_absent` answers `True` for an existing row with equal data.
The DynamoDB key schema can already express a per-list range read
(`bucket_name` is the String range key); PostgreSQL's `attributes.bucket_name`
is `VARCHAR(255)` with no `COLLATE "C"` anywhere in the attribute queries.

The sequencing question the todo leaves open turns on `compact()`. Measured
with `fractional_indexing`, rank keys stay short under every pattern except
repeated insertion into one gap, and the replica has no operator action today:
its only whole-list rewrite is `set_list`, which is `clear()` then `extend()`
and is already not crash-atomic.

## Detailed Findings

### The v1 format today

- Rows: `list:{name}:{index}` (`attribute_list.py:91`), `list:{name}:meta`
  (`:71`). Meta defaults: `length`, `created_at`, `updated_at`, `item_type`,
  `chunk_size: 1`, `version: "1.0"`, `description`, `explanation`
  (`:132-144`).
- `__len__` reads `length` from a per-instance `_meta_cache` (`:95-96`,
  `:219-223`). `AttributeListStore` caches one `ListAttribute` per name
  (`attribute_list_store.py:97-104`); `RemotePeerStore` is built per callback
  (`handlers/callbacks.py:671`).
- Every item read is one `get_attr` (`:225-258`). `ListAttribute` never calls
  `get_bucket`; there is no bulk read.
- `append` writes the item, then `length + 1` (`:404-425`). `extend` is a loop
  of `append` (`:427-430`): n item writes and n meta writes.
- A falsy item is not stored. `Attributes.set_attr` treats `{}`, `[]`, `""`,
  `0`, `False` and `None` as a delete on both backends (`attribute.py:356-363`;
  `db/dynamodb/attribute.py:239`, `db/postgresql/attribute.py:377`), so
  `append(0)` writes no row and still increments `length`; `to_list()` then
  raises `IndexError` for that slot (`:479-498`). `ListProperty` encodes every
  item to a non-empty JSON string first.
- No size check anywhere; `DbAttribute` declares no `MAX_ROW_BYTES`.

### What v2 rests on

Format (`property_list.py`):

- Item rows `list:{name}-#{rank}` (`:85-104`, `:1295-1299`); range bounds
  `["list:{name}-#", "list:{name}-$"]` (`:1301-1304`). Meta row
  `list:{name}-meta` with `format: 2`, `count_hint`, `format_ever_changed` and
  no `length` (`:1435-1447`).
- Ranks are base62 keys from `fractional_indexing` (`:112`). Every range read
  applies the shape filter `_v2_is_rank` (`:236-246`) because sibling lists'
  rows can fall inside the byte range. New list names may not contain `#` or
  `$` (`:1466-1473`).
- Cap 180 characters, `needs_rebalance` at 140 (`:106-109`), 8 retries on a
  rank collision (`:110`). At the cap, `append`/`extend`/`insert` raise
  `RuntimeError` naming `compact()` (`:2599-2603`, `:3230-3234`, `:3755-3759`).
- `len()` counts the rank list from one keys-only range read (`:2089-2093`,
  `:1306-1324`); `get_metadata()["length"]` is the advisory `count_hint`
  (`:2071-2077`).

Primitives, with where `ListProperty` calls them and where they are declared:

| Primitive | Protocol | DynamoDB `property.py` | PostgreSQL `property.py` | Used for |
| --- | --- | --- | --- | --- |
| `get_range` | `protocols.py:343` | `:619` (`between`) | `:532` (`COLLATE "C"`, `:562-574`) | rank list, full load (`:1317`, `:1388`) |
| `get_prefix` | `:405` | `:658` | `:583` (`starts_with`) | side-partition rows (`:907`) |
| `get_last_in_range` | `:593` | `:778` (reverse, `limit=1`) | `:762` | append's last rank (`:1350`) |
| `create_if_not_exists` | `:475` | `:702` | `:657` | item and meta creation (`:2517`, `:2607`, `:3238`, `:3763`) |
| `set_if_value_equals` | `:545` | `:748` | `:726` | meta CAS (`:1858`), `update_by_handle` (`:4217`) |
| `delete_if_value_equals` | `:502` | `:724` | `:690` | `pop`, `remove`, `delete_by_handle` (`:2922`, `:3691`, `:3889`, `:4165`) |
| `batch_delete` | `:632` | `:809` | `:801` | `clear`, `delete` (`:3405`, `:3446`, `:3510`) |

Per-operation cost in v2 (every mutator also does one meta point read at
dispatch, `:724-770`, and an advisory meta CAS touch, `:2175-2276`):

| Operation | Reads | Writes |
| --- | --- | --- |
| `append` | last rank only (`:2535-2621`) | 1 conditional create |
| `extend(n)` | one last-rank read (`:3174-3277`) | n conditional creates |
| `insert(i)` | keys-only range read (`:3732-3777`) | 1 conditional create |
| `__setitem__`, `__delitem__` | forced range read + head point read (`:2278-2321`, `:2356-2384`) | 1 write |
| `pop` | forced range read + point get, per attempt (`:3648-3702`) | `delete_if_value_equals`, up to 8 attempts |
| `remove(v)` | range read with values, per attempt (`:3872-3920`) | `delete_if_value_equals` |
| `clear`, `delete` | range read | `batch_delete` + meta |
| `to_list`, iteration | 1 range read with values | none |

Size of the pieces (`property_list.py`, comments and docstrings included):
module-level pure code about 590 lines (`:1-592`: constants, exceptions,
`diff_reference`, `ListItemHandle` `:520-557`, `_v2_is_rank`); the span codec
456 lines (`property_list_span.py`, imports nothing from `actingweb.db`); rank
helpers and range loads about 135 (`:1293-1426`); metadata load and CAS about
455 (`:1427-1884`); positional and append mutators about 560; `extend` 125;
`clear`/`delete` 135; reads 100; `pop`/`insert` 185; value matching 175;
handles and `_where` 350 (`:4009-4356`); `append_once` and key rows 515
(`:2659-3172`); v2 verify and repair 510; v2 compact 340; v1 code, migration
and format residue about 900.

Property-specific code inside the class: the scalar-name collision check
(`:1475-1482`), the whole v1 path and `migrate_to_v2` (`:5532-5921`), the
partition-dump hydration (`:1885-2021`), and the `{actor_id}$aux` side
partition used by spanned bodies and `append_once` key rows (`:866-912`).

### The attribute storage layer

Contract (`db/protocols.py:1251-1541`), wrapper `Attributes`
(`attribute.py:210-583`):

- `get_bucket(actor_id, bucket, *, strict=True)` — whole bucket.
- `get_attr`, `get_attr_strict`, `set_attr`, `delete_attr`.
- `delete_attr_conditional` (`:1358`) — conditional on the row existing, not on
  its value; answers `False` for an absent row, a lost race or a fault.
- `conditional_update_attr` (`:1386`) — compares JSON-normalised data; never an
  upsert; `False` on mismatch, missing row or fault. `new_data=None` nulls the
  data, it does not delete.
- `create_attr_if_absent` (`:1423`) — `True` if this call created the row,
  replaced an expired one, **or the stored data is JSON-equal to what it
  wrote** ("Two callers that write identical data both get True", `:1463`).
  Raises `DbError` on a fault.
- `delete_bucket`, `delete_expired`, `delete_by_chain`.

DynamoDB (`db/dynamodb/attribute.py`): table `<prefix>_attributes`, hash key
`id`, String range key `bucket_name = bucket + ":" + name` (`:58-77`, `:264`),
`data` a `JSONAttribute` (JSON text in a string attribute). `get_bucket` is
`query(actor_id, bucket_name.startswith(bucket + ":"), consistent_read=True)`
plus an exact `bucket` filter (`:126-131`). `delete_attr` is a consistent get
then a delete (`:239-250`, `:277-279`). `conditional_update_attr` is two round
trips (`:364-403`). `delete_bucket` deletes row by row (`:489-496`). No
`between`, reverse scan, `limit` or `batch_write` in the file. A per-list range
is expressible on the existing key schema with `bucket_name.between(...)`, the
construct `db/dynamodb/property.py:642` uses.

PostgreSQL (`db/postgresql/attribute.py`, `schema.py:214-243`, migration
`3307e3616c5e`): columns `id`, `bucket_name`, `bucket`, `name` all
`VARCHAR(255)`, `data JSONB`; primary key `(id, bucket_name)`; no index on
`bucket`. No `COLLATE` in any attribute query; `get_bucket` has no `ORDER BY`
(`:218-225`). `properties.name` was widened to `TEXT` for rank keys by
`e5f6a7b8c9d0_widen_properties_name_to_text.py:31`; no migration widens an
attribute column. `delete_bucket` is one set-based `DELETE` (`:720-726`).

Gap table:

| v2 needs | Attribute layer (DynamoDB / PostgreSQL) | Difference where partial |
| --- | --- | --- |
| range read over item names | no / no (key schema allows it on both) | — |
| last-in-range | no / no | — |
| prefix read | no / no as a primitive | — |
| create-if-absent | partial / partial (`create_attr_if_absent`) | answers `True` on JSON-equal existing data; replaces expired rows |
| value compare-and-swap | partial / partial (`conditional_update_attr`) | folds a fault to `False`; JSON-normalised compare; two round trips on DynamoDB |
| value-conditional delete | no / no (`delete_attr_conditional` is exists-only) | — |
| batch delete by name | no / no | — |
| name column wide enough for ranks | yes / no (`VARCHAR(255)`) | — |
| byte-order sort of names | yes / not pinned (`COLLATE "C"` absent) | — |

Length budget on PostgreSQL: a replica row's `bucket_name` is
`remote:{32 hex}:list:{name}:{rank}`, 46 fixed characters plus the name and the
rank (4 more for a hyphenated peer id, `remote_storage.py:25-27`). At the
180-character rank cap, 29 characters remain for the list name.

Key hazards for a rank in the attribute name:

- The composite key `bucket + ":" + name` can collide because both halves may
  contain `:`; both backends attribute a colliding row to the last writer and
  compare `bucket` exactly on every read and delete
  (`thoughts/todo/prop-list-key-prefix-scheme.md:107-114`,
  `tests/test_attribute.py:572-600`). Base62 ranks add no colons, so the class
  is inherited unchanged.
- List names may contain `:`: nothing validates them
  (`attribute_list_store.py:83-104`), and on the replica path the name comes
  from the publisher's diff (`remote_storage.py:357`, `:364`), where only `#`,
  `$` and control characters are banned (`property_list.py:1466-1473`,
  `handlers/properties.py:1035-1051`). `list_all` recovers names with
  `":".join(parts[1:-1])` (`attribute_list_store.py:72-75`), and
  `tests/test_attribute_list_store.py:198-214` pins `my:complex:name`. A range
  on `list:a:` includes sibling list `a:b`'s rows.
- `_v2_is_rank("meta")` is `True` (all four letters are base62), and so is
  `_v2_is_rank("0")`. Generated keys always start with a letter and are never
  `meta`, but the shape filter does not know that. Property lists keep the meta
  row out of the rank range by separator (`-#{rank}` against `-meta`), not by
  shape. A layout of `list:{name}:{rank}` beside `list:{name}:meta` and v1's
  `list:{name}:{index}` puts all three in one namespace.

### Who uses it

Library: `RemotePeerStore` only.

| `RemotePeerStore` method | `ListAttribute` calls |
| --- | --- |
| `get_list` (`remote_storage.py:145-154`) | iteration |
| `set_list` (`:156-182`) | `clear`, `extend`, `set_description`, `set_explanation` |
| `delete_list` (`:184-188`) | `delete` |
| `list_all_lists` (`:190-194`) | `AttributeListStore.list_all` |
| `_apply_list_operation` (`:395-522`) | `append`, `insert`, iteration + `__setitem__`, `len`, `extend`, `__delitem__`, `pop`, `clear`, `delete` |

`list_all_scalars` (`:196-211`) and `get_storage_stats` (`:305-324`) read the
raw bucket and treat every `list:`-prefixed name as list storage.

Public surface: `actingweb/__init__.py:38-42` lists `attribute_list` and
`attribute_list_store` in `__all__` as lazy pre-3.x compatibility modules
(`tests/test_init_docstring.py:21-22` pins the names).
`actingweb/interface/__init__.py:12`, `:81` exports `RemotePeerStore` and
`get_remote_bucket`. No `docs/` page mentions `ListAttribute` or
`AttributeListStore`.

`../actingweb_mcp`: every `AttributeListStore(...)` passes a `RemotePeerStore`
bucket and uses only `exists(name)`, `getattr` and
`get_metadata()["updated_at"]` (`hooks/mcp/tools/get.py:208-216`, `:486-494`,
`:621-629`; `api/trust_unified.py:111-119`, `:1202-1210`, `:1252-1260`;
`api/trust.py:1117-1125`; `repositories/peer_helpers.py:129-137`).
`RemotePeerStore` use is read-only (`get_list`, `list_all_lists`, `get_value`,
`get_all_properties`) except `delete_all()` at `api/trust.py:728`.
`scripts/debug_actor.py:666-688`, `:1254-1281` read raw remote buckets and
filter on `startswith('list:')`. `application.py:549` sets `auto_storage=True`.
What the consumer relies on: `exists()` keyed on `list:{name}:meta`
(`attribute_list_store.py:45`), `list_all()` name parsing, and the `updated_at`
key.

`../actingwebdemo`: no use outside its vendored copy of the library.

No application-owned attribute list was found. A third-party application could
have one through the compatibility modules; nothing in this repository can
show whether any does.

### Diff vocabulary

Publisher, notifying wrapper (`interface/property_store.py:256-343`, mapping at
`:427-607`). Base fields `list`, `operation`, `length` (advisory `count_hint`
under v2):

| Call | `operation` | Other fields | `index` |
| --- | --- | --- | --- |
| `append`, creating `append_once` | `append` | `item` | derived from the advisory length |
| announced `append_once` repeat | `insert` | `item` | position at adoption |
| `extend` | `extend` | `items` | absent |
| `insert` | `insert` | `item` | caller's raw argument |
| `__setitem__` | `update` | `item` | caller's raw argument |
| `update_by_handle`, `update_where` | `update` | `item`, `old_item` | absent |
| `__delitem__` | `delete` | — | caller's raw argument |
| `pop` | `pop` | — | caller's raw argument, default −1 |
| `remove`, `delete_by_handle`, `remove_where` | `remove` | `item` | absent |
| `clear` | `clear` | — | absent |
| `delete` | `delete_all` | — | absent |
| `set_description`, `set_explanation`, `compact`, `repair_keys`, `sweep_span_orphans`, `migrate_to_v2` | `metadata` | — | absent |

A diff over `list_item_span_threshold` becomes a reference: value fields
removed, `"spanned": true` and `bytes` added (`property_list.py:386-434`). A
peer without resync support gets the full state as `{"list", "operation":
"extend", "items"}` (`actor.py:3598-3604`).

Spec: `docs/protocol/actingweb-spec.rst:2615-2741`. The ten operations
(`:2633-2635`); `length` is advisory, "Receivers MUST NOT use it to address
rows" (`:2637-2641`); `index` is advisory for `append` (`:2646-2650`). The spec
does not define `spanned` references; those are in
`docs/guides/subscriptions.rst:415-437` and `docs/migration/v3.16.rst:1082-1085`.

Receiver (`remote_storage.py:395-522`):

| Operation | Requires | Addressing | On a miss |
| --- | --- | --- | --- |
| `spanned is True` (`:399-413`) | — | not applied, WARNING | `{"success": False, "spanned": True}` |
| `append` | `item` | appends, ignores `index` | unknown operation |
| `insert` | `item`, `index` | positional; `ListAttribute.insert` clamps | — |
| `update` | `item` and (`index` or `old_item`) | value first when unique, then index | WARNING, or "index out of range" |
| `extend` | `items` | append | — |
| `delete` | `index` | positional, `0 <= idx < len` | "index out of range" |
| `pop` | — | positional; only −1 is normalised | error for any other negative index |
| `remove` | `item` | first value match | "item not found" |
| `clear`, `delete_all` | — | whole list | — |
| `metadata` | — | ignored | — |

The receiver never reads `length`. The deliberate decision not to resolve a
spanned reference is recorded at `remote_storage.py:399-413` and
`docs/migration/v3.16.rst:1082-1085`.

Two publisher shapes the receiver does not treat as list operations:

- **REST list edits.** The `/properties` handlers mutate the core
  `ListProperty` (`actor.py:135`), not the notifying wrapper, and register
  their own blobs with no `list` or `operation`: `{"index", "value"}` for
  `PUT ?index=N` (`handlers/properties.py:881-889`), `{"action": "add" |
  "update" | "delete", "index", "value"}` for the items endpoint (`:2269-2282`,
  `:2352-2361`, `:2415-2419`), `{"action": "metadata_update"}` (`:2052-2056`),
  `""` for a list delete (`:1806`), and a text summary for bulk writes
  (`:282-284`, `:1722`). On a subscription with a matching subtarget the blob
  arrives as top-level keys `index` and `value`, which the scalar branch
  (`remote_storage.py:369-386`) stores as scalars with those names; on a
  target-level subscription it is stored as a scalar named after the list.
  Traced from the code, not run.
- **A non-resync peer's full state** is an `extend`, applied on top of the
  existing rows (`remote_storage.py:476-482`); only `set_list` clears first.

### Receiver cost

Today, list of n items, index k. "+Dd": one extra consistent read per delete
on DynamoDB.

| Branch | Reads | Writes |
| --- | --- | --- |
| append | 1 meta | 1 item + 1 meta |
| extend(m) | 1 meta | m items + m meta |
| insert(k) | 1 meta + (n−k) gets | (n−k) sets + 1 item + 1 meta |
| update by index | 1 meta | 1 item + 1 meta |
| update by `old_item` | 1 meta + n gets | 2 |
| delete(k) | 1 meta + (n−k−1) gets, +Dd | 1 delete + 2 per shifted item + 1 meta |
| pop(k) | delete(k) + 1 get | as delete(k) |
| remove, first match at j | 1 meta + (j+1) gets + delete(j) reads | delete(j) writes |
| clear | 1 meta, +Dd n | n deletes + 1 meta |
| `set_list` from m to n items | 1 meta, +Dd m | m + 2n + 1 |

`set_list` writes no description or explanation on the resync paths: neither
caller passes those keys (`remote_storage.py:566-573`, `:596-603`;
`handlers/callbacks.py:970-976`, `:987-993`).

Under a rank layout, by the cost model `docs/guides/property-lists.rst:109-132`
states and the code above implements:

- one conditional write plus a last-rank read: `append`, `extend`;
- one whole-list key read to resolve an index, then one write: `insert`,
  `update` by index, `delete`, `pop`;
- one whole-list value read, then one value-conditional write: `remove`,
  `update` by `old_item` (both already read the whole list today);
- one range read and a batch delete: `clear`, `delete_all`.

On today's attribute protocol the only whole-list read available is
`get_bucket` of the whole `remote:{peer}` bucket, every list and scalar
replicated from that peer. Measured DynamoDB figures for the property-side
range read: an 81-row list costs 241 RCU consistent, 120.5 eventual; a
keys-only projection saves no capacity
(`thoughts/research/2026-08-20-v2-positional-access-cost.md:104-110`).

### Rank growth

Measured on this tree with `fractional_indexing` and the base62 alphabet
`property_list.py:112` uses:

| Pattern | Rank length |
| --- | --- |
| append, 200,000 items | 4 |
| `insert(0, …)` repeated 3,000,000 times | 5 |
| 20,000 inserts at uniformly random positions | 8 at most |
| insert at index 1 repeatedly (same left neighbour) | ≥140 after 823, >180 after 1,069 |
| insert just before the last item repeatedly | ≥140 after 686, >180 after 891 |

Only `compact()` rebalances a `ListProperty`, and nothing calls it
automatically; the 140 threshold surfaces through `verify()["needs_rebalance"]`
and `actingweb-verify-property-lists --repair`
(`maintenance/verify_property_lists.py:385-403`). When a publisher compacts,
it emits a `metadata` diff (`interface/property_store.py:573-607`), which the
receiver ignores, so a replica's ranks would not follow the publisher's.

A replica's rows are reset only by `set_list`. Its callers: a resync callback
(`handlers/callbacks.py:558-588`, `:674-675`, sent by
`resume_subscriptions()`, `actor.py:3041-3103`); the baseline after a gap
timeout when no diffs are pending (`callback_processor.py:861-878` →
`subscription_manager.py:961-1015`, `:1129-1217`); the initial subscribe
baseline (`subscription_manager.py:315-334`, `:414-433`); the permission-grant
fetch (`handlers/callbacks.py:924-993`). None is periodic.

Key-length limits: DynamoDB sort key 1,024 bytes; PostgreSQL `VARCHAR(255)` as
above.

### Fault handling on the callback path

- `apply_callback_data` and `apply_resync_data` re-raise `DbError`
  (`remote_storage.py:387-388`, `:615-616`). `CallbackProcessor` releases its
  batch claim and re-raises (`callback_processor.py:958-972`: "data the handler
  wrote before the fault can be applied twice"); the integrations answer 503
  (`flask_integration.py:62-65`, `fastapi_integration.py:82`).
- Any other exception from a list operation (the shift loop's `RuntimeError`,
  `IndexError`, `ValueError`) is caught per key and stored as
  `results[key] = {"error": …}` (`remote_storage.py:389-391`, `:617-619`).
  Both handler closures discard the result (`handlers/callbacks.py:677`,
  `subscription_manager.py:1070`). The sequence advances
  (`callback_processor.py:983-996`), the callback answers 204, and no resync is
  requested.
- Callbacks for one subscription are serialised by a claim
  (`callback_processor.py:941-951`, lease `CLAIM_LEASE_SECONDS = 60`,
  `:71-78`). Nothing in `RemotePeerStore` deduplicates a re-applied diff;
  `append`, `extend` and `insert` are not idempotent.
- `thoughts/todo/subscription-subscriber-fault-hardening.md:21-29`, `:48-50`,
  `:62-66` leaves open keying applied diffs by `(subscription, sequence)` or
  having auto-storage's list operations carry the diff's sequence, and names
  `ListProperty.append_once()` as usable "once each diff carries a stable key".
  `ListAttribute` has no `append_once`.

Teardown: `delete_all()` is `Attributes.delete_bucket()`
(`remote_storage.py:294-301`), called from trust deletion
(`actor.py:2106-2127`) and from the last outbound subscription's deletion
(`:2600-2619`); `_delete_revoked_peer_data` deletes list by list
(`handlers/callbacks.py:1083-1132`); `Actor.delete` removes every bucket
(`actor.py:1144-1145`). All are name-agnostic within the bucket.

### Operator surface

`pyproject.toml:36-43`: `actingweb-verify-property-lists`
(`maintenance/verify_property_lists.py`) and `actingweb-migrate-property-lists`
(`maintenance/migrate_property_lists.py`) construct `ListProperty` only and
discover lists through `PropertyListStore.list_all()`. No tool walks attribute
lists. The parts exist: `DbActorList.iter_rows`, `Buckets.fetch()`
(`attribute.py:586-617`), `AttributeListStore.list_all`. `check_ready()`
(`interface/app.py:1557-1683`) has no list-format check.

For properties, v1 and v2 coexist, dispatched on the meta row's `format`
(`property_list.py:699-711`); lazy migration is off by default
(`ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH`, `:111`, `:168-208`).

### Constraints inherited

- **Swallowed errors corrupt without a crash.**
  `thoughts/research/2026-08-07-property-list-index-integrity.md:23-51`,
  `:144-179`: a read fault returned as `None`, or an unchecked write result,
  destroys an item. `conditional_update_attr` and `delete_attr_conditional`
  still fold a fault to `False`.
- **Interrupted shifts leave holes or exact duplicates, about half each**;
  duplicates keep a correct `length` and leave no fingerprint (`:109-142`).
  Writing `length` first turns a data-preserving residue into silent loss
  (`:398-404`). The review records that `ListAttribute` shares the defect
  (`thoughts/research/2026-08-08-property-list-index-integrity-review.md:141-149`).
- **Transactions are ruled out**: 100 actions per `TransactWriteItems`
  (`thoughts/plans/2026-08-08-property-list-index-integrity.md:70-71`).
- **The chosen format requires** a format marker in meta, range isolation by
  delimiter plus shape filter, conditional creates, and position-to-key
  translation at the edges (same plan `:44-60`, `:455-513`); every mutation
  must persist the meta row or the list is invisible to `exists`/`list_all`
  (`:627-640`).
- **Never write a cached metadata dict back**; name the changed fields and
  merge into a fresh read
  (`thoughts/plans/2026-08-15-property-list-metadata-integrity.md:112-126`).
- **Handles** (`thoughts/plans/2026-08-20-v2-positional-access-cost.md`, Phase
  7 `:1096-1113`, Phase 10 `:1707-1734`): built from strongly consistent reads;
  carry the raw stored value; not wire-stable across a list generation (after
  `delete()` and `append()` the first rank is `a0` again); mutators are
  single-shot with no retry; `BatchWriteItem` cannot express conditions, so k
  handle mutations are k conditional point writes.
- **Whole-list rewrites** (`thoughts/todo/whole-list-rewrite-atomicity.md`):
  `compact()` leaves both copies on a crash; two designs were cut; prefer a
  visible failure to an invisible one; `length` as an absolute value with more
  than one writer is the residual that todo assigns to its own design. That
  todo names this one as sequenced after it (`:98-99`).

### Tests

Assert the v1 layout directly: `tests/test_attribute_list.py:49`, `:60-62`,
`:80-95`, `:234-245` (names, `length`, `chunk_size`, `version`);
`tests/test_attribute_list_store.py:70`, `:130-151`, `:203-214`;
`tests/test_remote_storage.py:920-994` (raw-bucket fixtures);
`tests/integration/conftest.py:1049-1093` (`verify_list_exists` keys on
`list:{name}:meta`; no caller).

Through the API only: `tests/integration/test_attribute_lists_advanced.py`
(19 tests, real backend, no fault or concurrency cases);
`tests/integration/test_list_diff_peer_replica.py` (publisher
`remove_where`/`update_where` against a real replica; a spanned diff skipped).
`tests/test_remote_storage.py` (67 tests) replaces `AttributeListStore` with a
`MockListAttr` (`:241-278`), so it never reaches `ListAttribute` storage.

Harness on the property side: `tests/test_property_list_integrity.py` —
`FakePropertyDb` (`:31-133`), `CrashInjectingPropertyDb` (`:136-163`),
`CountingPropertyDb` (`:490-519`), `StaleReadPropertyDb` (`:522-551`). Their
shape (`(actor_id, name) -> str`) differs from attributes
(`(actor_id, bucket, name) -> {"data", "timestamp"}`); the pattern carries
over, the code does not. An in-memory attribute backend exists at
`tests/mcp_token_double.py:59`, `:125`.

## Documentation Impact

### The storage format

- `docs/` — no page mentions `ListAttribute`, `AttributeListStore` or
  "attribute list": none. `docs/sdk/attributes-buckets.rst` has no list or
  `remote:` coverage: none. The modules have no `automodule` entry, so their
  docstrings are not rendered.
- Docstrings `actingweb/attribute_list.py:8-19`, `:54-60`, `:288-304`,
  `:551-569` (O(n) insert and delete, non-transactional shifting, the
  `list:{name}:{index}` pattern) — false after the change.
- `docs/guides/property-lists.rst` — `ListProperty` only. "Storage Format (v1 /
  v2)" at `:102`. Needs a section only if attribute lists become documented.

### Replica behaviour

- `docs/guides/subscriptions.rst:364-391` — the operation table ("at specific
  index"). Stands.
- `docs/guides/subscriptions.rst:392-446` — closed vocabulary, `old_item`,
  references; `:427-431` says the receiver logs out-of-sync. Stands; the place
  for any new statement about what a replica does when it cannot apply a diff.
- `docs/guides/subscriptions.rst:253-291`, `:751-778` — resync triggers and the
  gap timeout. Stand.
- `docs/protocol/actingweb-spec.rst:2615-2741` — the wire format. Stands; a
  storage change does not touch it.
- `docs/migration/v3.14.rst:150-174`, `docs/migration/v3.16.rst:1082-1085` —
  historical and current notes on value-addressed diffs and references. Stand.

### Custom backends and operators

- `docs/migration/v3.16.rst:698` ("Custom database backends") — lists what a
  custom backend must implement in 3.16. Needs an addition for every method
  added to `DbAttributeProtocol`.
- `docs/guides/property-lists.rst:335-347`, `:1036-1049` — the property-list
  tools. Stand unless a tool gains attribute-list coverage.
- `docs/migration/v3.16.rst` — no section covers attribute lists; a new one
  would sit after "Idempotent appends" (`:1135`).

### Already wrong against the code

- `docs/guides/subscriptions.rst:347-350` and
  `docs/contributing/testing.rst:512-543` call `store.apply_list_operation(...)`;
  no such public method exists.
- `docs/guides/subscriptions.rst:556-566` shows
  `apply_callback_data(target=, data=)`; the signature takes `data` only.
  `:696` names `ProcessResult.RESYNC_REQUIRED`; the code has
  `RESYNC_TRIGGERED`.

## Decisions Needed

### Decision 1: sequencing against whole-list rewrite atomicity

The todo's stated blocker. Facts that bear on it: a replica has no `compact()`
caller today; its one whole-list rewrite, `set_list`, is already `clear()` then
`extend()` with no commit protocol; rank growth reaches the cap only for
inserts into one gap; a publisher's own `compact()` does not propagate.

**Options:**

1. **Port without a `compact()`.** At the rank cap the replica has to do
   something: fail the diff (see Decision 6) or rebuild itself from its own
   contents the way `set_list` does. No new whole-list rewrite class is added,
   so nothing waits on the atomicity todo.
2. **Port `compact()` with the window `ListProperty` documents.** Same
   duplicate-residue failure on a crash, visible to a `verify()` that would
   also have to be ported, and an operator tool to run it.
3. **Sequence after `whole-list-rewrite-atomicity.md`.** That todo has two
   dead designs and no third; the shift loop stays on the subscription path
   until it lands.

**Recommendation:** option 1 or 2 rather than 3. The evidence is that a
replica is rebuildable from its publisher and already rewrites wholesale
without atomicity on every resync, so the gap the atomicity todo describes is
not introduced by the port.

### Decision 2: how the code is shared

1. **A purpose-built v2 `ListAttribute`** that reuses the pure pieces
   (`fractional_indexing`, `ListItemHandle`, `_v2_is_rank`) and implements the
   operations `RemotePeerStore` uses against new attribute primitives. Two
   implementations of the format to keep in step; the smaller diff, and no
   change to `property_list.py`.
2. **Extract a storage-agnostic core from `ListProperty`** behind an adapter
   with a property and an attribute implementation. One implementation of the
   format; a refactor of 5,921 lines whose behaviour is pinned by the
   fault-injection suites listed under "Tests", with the property-specific
   parts (v1, migration, the `$aux` side partition, partition-dump hydration)
   staying outside the core.
3. **Store replica lists as property rows** in a side partition per peer, the
   way spanned bodies use `{actor_id}$aux`, and run `ListProperty` unchanged.
   Needs no new attribute primitive. Scalars of the same replica stay in the
   attribute bucket, so one replica spans two tables; `delete_all()`, actor
   deletion and `_delete_revoked_peer_data` would each need a second wipe; the
   consumer's `AttributeListStore(bucket=…).exists()` and `get_metadata()`
   calls would need a facade. How actor deletion treats side partitions was
   not traced.

### Decision 3: which primitives join `DbAttributeProtocol`

Under options 1 and 2 of Decision 2. Each addition is a method both backends
implement and a line in "Custom database backends".

- A range read over names in one bucket, and last-in-range. DynamoDB: a key
  condition on the existing schema. PostgreSQL: needs `COLLATE "C"` on the
  bounds and the order.
- A value-conditional delete. None exists.
- A batch delete by name. None exists; without it `clear()` stays n deletes
  (2n round trips on DynamoDB).
- Create-if-absent: use `create_attr_if_absent` as it is (two writers of an
  equal item at one rank both get `True`, leaving one row), or add a strict
  variant.
- Compare-and-swap: use `conditional_update_attr` as it is (a fault reads as a
  lost race), or add a raising variant.

And one schema change: widen `attributes.bucket_name` and `name` on PostgreSQL
(an Alembic revision, as `e5f6a7b8c9d0` did for properties), or cap list-name
plus rank length at what `VARCHAR(255)` leaves.

### Decision 4: row naming

Constraints: the consumer keys `exists()` on `list:{name}:meta`; `list_all()`
and `list_all_scalars()` parse and filter on the `list:` prefix and the `:meta`
suffix; names may contain `:`; `meta` and all-digit strings pass the rank
shape filter.

1. **Keep `list:{name}:meta`; put ranks behind a marker** that is neither
   base62 nor `:` (the property side uses `#`), with the shape filter on every
   range read. v1 `list:{name}:{index}` rows stay distinguishable.
2. **Move to the property layout** (`list:{name}-#{rank}`, `-meta`). Breaks
   the consumer's `exists()` key and the `list_all` parsing unless both are
   changed in step.

### Decision 5: existing v1 replicas

Every attribute list found is a replica. Unknown: third-party lists created
through the compatibility modules.

1. **Dual format, converted when rewritten.** A `format` field in meta; v1
   rows stay readable; `set_list` (every resync and baseline) writes v2. A v1
   list that only receives diffs keeps the shift loop until its next resync,
   unless the first mutation converts it.
2. **Convert on first mutation.** The first diff applied to a v1 list reads it
   whole and rewrites it as v2. Bounded by one list; no operator step.
3. **An operator migration tool** walking every actor's `remote:*` buckets,
   with v1 support removed afterwards. Needs the tool, a readiness check, and
   a migration-guide step.
4. **Drop and resync.** Delete v1 replica lists and let the next baseline
   rebuild them. Loses the replica for peers that are unreachable or do not
   support resync.

### Decision 6: what a failed list operation does on the callback path

Today a non-`DbError` failure is swallowed and the sequence advances. A v2
port adds failures of its own: a lost conditional write, the rank cap, a
malformed row.

1. **Leave as is.** A v2 failure diverges the replica silently, as a shift
   failure does today.
2. **Raise a `DbError`-class fault** so the callback answers 503 and the diff
   stays on the publisher, accepting the double-application the processor
   documents.
3. **Mark the replica for resync** and request one (for peers that support
   it). This is the territory of
   `thoughts/todo/subscription-subscriber-fault-hardening.md`.

### Decision 7: how much of the `ListProperty` surface comes across

The todo says to adopt the handle API. Beyond that:

- **Handles and value-addressed mutators** — used by the receiver's `remove`
  and `update`-by-`old_item` branches (one value read, one conditional write).
- **Item encoding** — v2 needs every item stored as a non-falsy value with a
  stable compare form; today a falsy item stores no row.
- **`append_once`** — would let a re-applied `append` be idempotent once diffs
  carry a key; no diff carries one today. In scope, or left to the
  subscriber-hardening todo.
- **Spanned items** — the receiver does not apply spanned references, so a
  replica item is at most the publisher's span threshold. Not needed for
  parity.
- **`verify()` and an operator tool** — none exists for attribute lists.
  Tied to Decision 1.

### Decision 8: defects found on the way

Outside the format question; each could ride along, become a todo, or be left:

- REST list edits reach a replica as scalars named `index`, `value` or after
  the list (`handlers/properties.py:881-889`, `:2269-2419`).
- A non-resync peer's full state is appended to the existing replica
  (`actor.py:3598-3604` → `remote_storage.py:476-482`).
- `pop` with a negative index other than −1 is a miss on the receiver
  (`remote_storage.py:491-499`).
- The three documentation errors under "Already wrong against the code".

## Release shape

3.16, the unreleased minor. Any method added to `DbAttributeProtocol` is a
change custom backends must implement (the existing "Custom database backends"
section, `docs/migration/v3.16.rst:698`), and a PostgreSQL column change is an
Alembic revision operators run; either makes this a minor on its own. The
stored format of replica lists changes, which is a `**Behavior change:**`
entry under `CHANGED` with what an operator checks, plus a migration-guide
section whose content depends on Decision 5.

Owner decisions: 1 (sequencing and `compact()`), 2 (code sharing), 3
(primitives and the PostgreSQL column), 4 (row naming), 5 (existing replicas),
6 (failure on the callback path), 7 (surface), 8 (ride-alongs).

## Code References

- `actingweb/attribute_list.py:288-387` — `__delitem__` shift loop
- `actingweb/attribute_list.py:551-644` — `insert` shift loop
- `actingweb/attribute_list.py:404-430` — `append`, `extend`
- `actingweb/attribute_list_store.py:36-104` — `exists`, `list_all`, the per-name cache
- `actingweb/remote_storage.py:156-182` — `set_list`
- `actingweb/remote_storage.py:328-393` — `apply_callback_data`, the swallowed exceptions
- `actingweb/remote_storage.py:395-522` — `_apply_list_operation`
- `actingweb/attribute.py:334-370` — `set_attr`, falsy data deletes
- `actingweb/db/protocols.py:1251-1541` — `DbAttributeProtocol`
- `actingweb/db/protocols.py:343-670` — the property primitives v2 uses
- `actingweb/db/dynamodb/attribute.py:58-77`, `:126-131` — key schema, `get_bucket`
- `actingweb/db/postgresql/schema.py:214-243` — `attributes` table
- `actingweb/db/postgresql/property.py:532-581`, `:762-799` — `COLLATE "C"` range and last-in-range
- `actingweb/property_list.py:85-112` — v2 naming, rank limits
- `actingweb/property_list.py:520-557` — `ListItemHandle`
- `actingweb/property_list.py:1293-1426` — rank helpers and range loads
- `actingweb/property_list.py:4009-4356` — handles and `_where` mutators
- `actingweb/interface/property_store.py:256-343`, `:427-607` — diff construction
- `actingweb/handlers/properties.py:881-889`, `:2269-2419` — REST diff blobs
- `actingweb/callback_processor.py:941-1016` — claim, handler faults, sequence write
- `actingweb/handlers/callbacks.py:667-677` — the handler closure that discards results
- `actingweb/maintenance/verify_property_lists.py`, `migrate_property_lists.py` — property-only tools
- `tests/test_property_list_integrity.py:31-190`, `:490-572` — the fault-injection fakes
- `tests/integration/test_list_diff_peer_replica.py` — publisher to real replica

## External References

None. `fractional_indexing` behaviour was measured locally rather than looked
up.
