# Research: Version history and restore for properties, attributes and list elements

**Date:** 2026-11-26
**Feature:** thoughts/features/2026-11-26-version-history-and-restore.md
**Branch:** master
**Commit:** f7b32ff (version `4.0.0rc4`; 4.0.0 final not shipped)

Consumer facts are from a read-only survey of `../actingweb_mcp` on
2026-11-26; its paths are prefixed `emm:`.

## Research Questions

1. **L1, L2, L3 for list elements** — The library already has two partial
   identities: the v2 rank and the application's `append_once` key. Neither is
   durable as it stands. A library-maintained identity must be named in `need`
   (PLS-D2), and 4.0.0 then refuses those items. L2 works for Emm only if the key
   is an application string, not just the element `id`. → [Lists](#list-elements-today), [Decision 3](#decision-3-list-element-history-l1-l2-l3)
2. **What `/properties` and a diff carry for an element** — the whole
   decoded value, embedding included. The only per-element data stored and
   not sent is the library's own envelope fields. → [Wire](#what-the-wire-carries-for-a-list-element)
3. **L2: any application string as key, version of a gone element still listed** — Nothing in the code constrains this: a separate store keyed by
   (owner, item key) does not depend on the element existing. → [Decision 3](#decision-3-list-element-history-l1-l2-l3)
4. **Whole stored element or an application-passed value** — Both are
   possible. Emm's memories carry the embedding inline, and every save is
   followed by a second, embedding-only write. Documents keep embeddings in a
   sidecar list. → [Emm](#the-consumer-emm), [Decision 5](#decision-5-what-a-version-holds)
5. **No migration for non-opt-in, and what an opt-in deployment runs** — On
   DynamoDB, yes: a conditional `required_models()` entry, as `creators` has.
   On PostgreSQL, a new table either goes in the Alembic chain (every operator
   who runs `alembic upgrade head` gets an empty table; only a configured app
   checks for it) or is built by a feature command outside the chain
   (precedent: `ux_actors_creator`). A store inside the existing tables needs no
   schema change at all. → [Storage](#where-a-version-store-could-live), [Decision 1](#decision-1-where-versions-are-stored)
6. **An all-or-nothing restore, and `DbErrorAfterWrite`** — For a plain
   property or attribute, yes, inside one new backend call. That call holds
   the version write, the value write and, for an indexed name, the lookup
   claim, on both backends. Diff registration always runs after commit, so a
   restore can end in `DbErrorAfterWrite` like any write. For a list element
   that is not spanned, the write is one head row plus a meta touch, so an
   atomic restore would need a new `ListStorage` primitive, under any option.
   For a spanned element (bodies first, then the head; 4 MB per DynamoDB
   transaction) the code offers no way to make it atomic. → [Atomicity](#atomicity)
7. **Automatic versioning: complexity and cost** — There is no single choke
   point. The interface layer misses the HTTP, `www` and replica writers. The
   backend layer has 5 entry points for properties and 8 for attributes, and
   sees list plumbing rows it cannot tell apart from elements. Each auto-version
   adds a read before every blind write, plus one write. → [Write paths](#write-and-delete-paths), [Decision 6](#decision-6-automatic-versioning)
8. **Granularity of automatic versioning** — Per property name and per
   bucket can be expressed at the interface layer only. Below it, names are
   row names (`list:{name}-#{rank}`). → [Decision 6](#decision-6-automatic-versioning)
9. **Large values** — A version of a value near 400 KB, with its metadata,
   does not fit a DynamoDB row. A spanned element (up to 2 MiB) plus its copy
   can exceed the 4 MB transaction limit. A version store on DynamoDB needs
   spanning, or a cap below the value cap. → [Limits](#size-limits)
10. **Bounding "all versions with content"** — There is no paging precedent
    in the public storage calls. A DynamoDB `Query` pages natively. Whether a
    content-free listing reads the content depends on the row layout. → [Decision 7](#decision-7-row-layout-and-listing-cost)
11. **Removal paths reaching a new store** — Actor, bucket and trust removal all
    delete rows directly (PLS-D4 holds). None of them reaches a new table.
    Actor deletion already sweeps `{actor_id}$aux` in the properties table. →
    [Removal](#removal-paths)
12. **Custom backend: what to implement, and when it fails** — A missing
    method fails at the first call (`AttributeError`). The exception is a name
    `check_ready()` probes, as it does for `ATTRIBUTE_LIST_PRIMITIVES`. → [Backends](#backend-selection-and-custom-backends)
13. **Patch, minor or major** — A minor (4.1.0) under the release rule, or
    part of 4.0.0 if it lands before final; the owner decides. →
    [Release shape](#release-shape)
14. **AC-16 counter** — `tests/_read_counters.py` counts DynamoDB API calls.
    On PostgreSQL it counts connections, not statements. → [Testability](#acceptance-criteria-testability)
15. **A normal write of an indexed value another actor holds** — The property is
    written and the lookup row stays with the holder. DynamoDB logs
    `LOOKUP_COLLISION` (error), PostgreSQL logs `LOOKUP_CONFLICT` (warning).
    Pinned by `tests/test_property_lookup_sync.py:124-137`. → [Reverse lookup](#reverse-lookup)
16. **Storage cost per version, bounding growth, observing it** — One full
    copy per version, compressed only by PostgreSQL TOAST. Nothing bounds it
    without a limit. No per-actor or per-account storage figure exists on
    either backend. → [Storage accounting](#storage-accounting)
17. **Versions of elements when a whole list is deleted or cleared** — Not
    decided by any code. A separate store would keep them unless the delete
    reaches it. → [Lists](#list-elements-today), [Decision 8](#decision-8-what-removes-versions)
18. **Owner-undecided questions** (versioning turned off, placement, auto plus
    restore, restoring a deleted item, removal by `-x`, lowering the limit,
    L1 fallback) — not answerable from code; carried to
    [Decisions Needed](#decisions-needed).
19. **Does Emm need a version of a deleted list element** — Yes. Every
    memory, document and instruction is a list element, and each type has
    several delete paths. → [Emm](#the-consumer-emm)
20. **Metadata size Emm needs** — Today `{who, how}` plus `action` and a
    timestamp, all short strings. `how` holds a client name and a description.
    Nothing bounds it. → [Emm](#the-consumer-emm)

21. **How big is it, and how does each option move the size?** — From about
    7–10k diff lines (3–5 days) for the lean scope to the size of the largest
    PRs in the repository (20k+, 2–3+ weeks) for the full feature document.
    Automatic versioning and L1 move it most. → [Size Estimate](#size-estimate)

## Summary

The hypothesis says a version store separate from current values is invisible
to every existing read, and the code supports that. Every listing, `/properties`,
peer read, subscription baseline and reverse lookup reads only the
`properties`, `attributes` or lookup tables, scoped to the actor's own
partition. The property side has a working analogue already: the
`{actor_id}$aux` side partition holds list span bodies and key rows in the
existing properties table. No actor read returns it, actor deletion sweeps it,
and `verify_orphans` knows it (`actingweb/property.py:470-525`,
`maintenance/verify_orphans.py:31-35`). The attribute side has no equivalent.
Its `{bucket}$aux` side bucket sits in the actor's own partition, and the
bucket listing returns it (`db/dynamodb/attribute.py:1012-1035`).

The hypothesis's "all-or-nothing restore" holds for plain properties and
attributes, and only through a new backend method. Each backend already
commits a property row plus a row in another table in one call: DynamoDB
`TransactWriteItems` for the property plus its lookup row, PostgreSQL
`_set_indexed`'s transaction. Subscription diffs are always registered
after the commit, so a restore can end in `DbErrorAfterWrite` like every
write. A plain list element write is one head row plus a meta-row touch
(`list_core.py:2203-2245`), and could be paired with a version row through
a new `ListStorage` primitive. A spanned element is several rows (bodies
first, then the head), and no list operation spanning rows is atomic today
(`todo/whole-list-rewrite-atomicity.md`). Under L1 or L3, then, the "never
partial" restore is available only for unspanned elements, and only with a
new list-storage primitive. That narrows what L2 gives up compared with the
feature's statement.

The consumer survey changes three premises in the feature document.
- Emm's wiki documents are property lists (`output_<category>`), not
  attribute lists.
- A memory's `id` changes when it moves to another type.
- An instruction is a one-element list whose identity is the list name.

So an L2 key that works for Emm is an application string (`memory_<type>/7`,
`output:<origin>/<seq>`, `instruction_<name>`), not the element `id` alone.
For L1, an identity the library maintains on every element must, under
PLS-D2, be named in `need`. 4.0.0 then refuses those items. 4.0.0 is still at
rc4, so when that becomes safe is an owner decision.

Automatic versioning is costly in this codebase. There is no single choke
point, each auto-version adds a read before each blind write, and Emm's
embedding-only second write would make two versions per memory save.

Size: the lean scope (S1–S5, L2) is about 3× the compare-and-delete PR,
7–10k diff lines over 3–5 days. The full feature document is the size of the
largest PRs in the repository. Automatic versioning and a library-minted
list identity account for most of the difference.

Success measures: AC-16's "same store work" can be observed on DynamoDB with
the existing call counter. "Storage per account" cannot be observed: nothing
measures it today.

## Detailed Findings

### Where a version store could live

**DynamoDB: the library creates tables.**
- `ensure_table(model)` creates a missing table once per process
  (`actingweb/db/dynamodb/_ensure.py:73-107`). It can be turned off with
  `AWS_DB_AUTO_CREATE_TABLES=false` / `with_dynamodb(auto_create_tables=False)`
  (`_ensure.py:43-51`, `interface/app.py:614-637`).
- `required_models()` is the one list of tables (`db/verify_tables.py:42-81`).
  `Creator` is added only when `unique_creator` is on (`:77-80`): this is the
  precedent for a table only an opted-in deployment has.
- `check_ready()` pre-warms the required tables (`app.py:1744-1785`).

**PostgreSQL: Alembic, run by the operator.**
- The library never creates tables (`db/postgresql/attribute.py:238-239`,
  `docs/quickstart/deployment.rst:251-253`). Every addition so far was a chain
  revision that every deployment applies.
- A configuration-gated check has precedent:
  - The `property_lookup_backfill` table is in the chain, but checked only
    when indexed properties are configured (`app.py:1880-1899`).
  - `ux_actors_creator` is deliberately left out of the Alembic metadata
    (`db/postgresql/schema.py:37-55`, `migrations/env.py:67-68,115-116`). It
    is built by `actingweb-unique-creators enable` or at first start on an
    empty store (`maintenance/unique_creators.py:1266,1607`, `app.py:1975-2008`).
- Delete paths already tolerate a missing table: `UndefinedTable` is treated
  as "holds none" (`db/postgresql/subscription_suspension.py:164-167`,
  `subscription_diff.py:414-415`).

**Inside the existing tables.**
- Properties: key `(id, name)` on both backends (`db/dynamodb/property.py:23-57`,
  `schema.py:69-81`). A partition `{actor_id}$<kind>` is a different `id`.
  - Every actor read misses it: `fetch` by actor id
    (`db/dynamodb/property.py:851-895`, `db/postgresql/property.py:850-913`)
    and `fetch_all_including_lists` (`:897-917`, `:915-958`).
  - `$` in actor ids has been refused since 4.0 (`property.py:497-500`).
  - Values are `TEXT`/string, so a version row would hold an encoded record
    (value plus metadata plus timestamp).
- Attributes: key `(id, bucket_name)`, with `data` as JSON and `timestamp`
  (`db/dynamodb/attribute.py:65-84`, `schema.py:214-255`).
  - `DbAttributeBucketList.fetch` queries the whole actor partition and
    groups by bucket (`db/dynamodb/attribute.py:1012-1035`;
    `db/postgresql/attribute.py:1218-1243`). A version bucket under the
    actor's id would appear in bucket listings (AC-10). So would today's
    `{bucket}$aux`.
  - A partition `{actor_id}$<kind>` in the attributes table has no precedent,
    and no delete path reaches it (`Buckets.delete` deletes by `actor_id`,
    `db/dynamodb/attribute.py:1059-1069`).

### Atomicity

- DynamoDB transactions run through `DbActor._run_transaction`
  (`db/dynamodb/actor.py:815-880`). They are already used across tables:
  - property plus lookup row (`db/dynamodb/property.py:426-455`);
  - actor plus `creators` plus `_internal` attributes (`actor.py:367-369`).
- A plain property `set` is a single `save()` (`db/dynamodb/property.py:273-284`).
  `set_attr` is a single conditional put (`db/dynamodb/attribute.py:378-390`).
- PostgreSQL: one accessor call is one transaction (`connection.py:172-205`).
  `_set_indexed` does a `SELECT … FOR UPDATE`, the property write and the
  lookup claim in one transaction (`db/postgresql/property.py:293-359`).
  Two accessor calls are two transactions.
- The order of a property write (`interface/property_store.py:136-147`):
  1. The put hook runs and may transform the value (`:139`).
  2. The previous value is read, but only for resource-level subscribers (`:141`).
  3. The core write, where lookup indexing happens inside the backend call.
  4. `register_diffs` runs after commit, as separate store calls:
     `increment_seq`, then the diff create (`subscription.py:172-219`).
- `DbErrorAfterWrite` means the value is stored and its diff is not
  (`db/exceptions.py:23-46`, PLS-2). It is raised at
  `interface/property_store.py:122-128,296,406-412`, at
  `handlers/properties.py:355,731,1783,2818,2864` and at `handlers/www.py:632,1826`.
- So a restore can bring "save current, write chosen, re-index" into one
  backend call on each backend. Diff registration stays after the commit.
  "Never partial" (AC-28) covers the stored value. A failed diff is
  `DbErrorAfterWrite`, the same as for an ordinary write.
- List elements:
  - `_v2_setitem` reads the head, writes span bodies to `$aux`, writes the
    head, cascade-deletes the old generation and touches meta
    (`list_core.py:2203-2245`, `:955`).
  - A spanned item's bodies are written before its head and removed again
    only when the head is known not to have landed (`list_core.py:936-1044`).
  - An unspanned element: `_v2_setitem` is one point read of the head, one
    unconditional `put` of the head, and `_v2_touch_metadata` (a meta-row
    write that keeps `list_all()`/`exists()` working, `list_core.py:2100-2115`).
    `update_by_handle` is the same with a CAS (`set_if_value_equals`) on the
    head (`:3772-3821`). Pairing that head write with a version row is a new
    `ListStorage` primitive. The meta touch can stay outside it, since it
    carries no value.
  - A spanned element: no list operation that spans rows is atomic today.
  - The DynamoDB limits: 100 items and 4 MB per transaction, and one item
    cannot be targeted twice (AWS, external references). A 2 MiB element plus
    its version is already over 4 MB.

### Size limits

- `MAX_ROW_BYTES = 409_600` on DynamoDB `DbProperty` and `DbAttribute`
  (`db/dynamodb/property.py:95-98`, `db/dynamodb/attribute.py:196-198`).
  `None` on PostgreSQL (`db/postgresql/property.py:58-61`,
  `db/postgresql/attribute.py:234-236`).
- Plain properties and attributes have no library-side size check. An
  oversized DynamoDB row is a `PERMANENT` `DbError` (`faults.py:79-88,157`).
- Lists:
  - A span threshold of 390,000 bytes and a 2 MiB ceiling on a backend with a
    row cap (`property_list_span.py:49-87`, PLS-5).
  - Bodies are stored at `list:{name}-$span-{gen}-p{NNNN}` under `$aux`.
  - On PostgreSQL nothing spans unless the application sets a threshold.
- A version of a value near the row cap, with metadata added, does not fit
  one DynamoDB row. A version store there needs the span codec, or a refusal
  below the value cap.
- PostgreSQL `property_lookup` limits a key row to about 2.7 KB
  (`maintenance/property_lookup.py:717-720`). It affects only a restore of an
  indexed property (the claim runs in the transaction and rolls back on
  failure, `db/postgresql/property.py:427-447`). Version rows are not indexed.

### Write and delete paths

**Properties.** Everything ends in `DbProperty.set`, where a `None` value is
the delete (`db/dynamodb/property.py:247-253`, `db/postgresql/property.py:248-254`).
The callers:
- the interface `PropertyStore` (`interface/property_store.py:144,152,205,301`),
  and the peer and client views built on it (`interface/authenticated_views.py:159,252-262`);
- the HTTP handlers, which write the core `myself.property` directly
  (`handlers/properties.py:1777,1835,2023,2051,2671,2815,2863`);
- `handlers/www.py:629,1824`;
- `services/service_client.py`;
- the deprecated `Actor.set_property`.

**Attributes.** There is no choke point above the backend. `Attributes`
methods (`attribute.py:424-764`) and `InternalStore` (`attribute.py:97-250`)
each call a different backend method, and about 30 modules call the backend
directly.

**Backend entry points that overwrite or delete a value.**
- Properties (5): `set`, `delete`, `set_if_value_equals`,
  `delete_if_value_equals`, `batch_delete`.
- Attributes (8): `set_attr`, `delete_attr`, `delete_attr_conditional`,
  `conditional_update_attr`, `set_attr_if_data_equals`,
  `delete_attr_if_data_equals`, `delete_attrs`, `put_attr`.
- Plus `DbActor.rename_creator`, which writes `_internal` rows inside the
  actor transaction (`db/dynamodb/actor.py:421-462`).

**Lists.**
- List writes go through the `ListStorage` adapters onto those same backend
  methods (`property_list.py:407-489`, `attribute_list.py:242-290`).
- Rows `list:{name}-meta`, `-#{rank}`, `$span-`, `$key-`, and v1 shift writes
  (`property_list.py:842-869`), all reach the backend as ordinary row writes.
- A backend-level hook therefore sees list plumbing and library-internal
  buckets (`_internal`, `remote:*`, OAuth state) as if they were application
  values.

**Blind writes.** A non-indexed property `set` and a DynamoDB `set_attr` do
not read the old value (`db/dynamodb/property.py:274-284`,
`db/postgresql/property.py:263-276`, `db/dynamodb/attribute.py:369-390`). An
automatic version adds a read there. The indexed `set` already reads it
(`db/dynamodb/property.py:314`, `db/postgresql/property.py:307-316`).

### Hooks and diffs (AC-15, AC-26)

**Python API.**
- `actor.properties["x"] = v` runs the put hook, writes, then registers the
  diff. A hook returning `None` does not stop it: the original value is
  written (`interface/property_store.py:80,139-147`).
- `del actor.properties["x"]` registers a diff and fires no hook (`:149-153`).
- `set_without_notification` does neither (`:200-205`).

**HTTP.**
- A put hook returning `None` gives a 400 (`handlers/properties.py:1764-1768`).
- A delete hook returning `None` gives a 403 (`:2796-2831`).
- List edits register diffs by hand (`:349-360`).

**Attributes and attribute lists** fire no hook and register no diff (grep).
The docstring at `interface/actor_interface.py:363-364` says the same.

**Consequences for the ACs.** "The same hooks as a normal write" (AC-26)
names one path among several that differ. A put hook can transform the
value, so the restored current value can differ from the version's content
(AC-23). For attributes, AC-26 is vacuous: no hook, no diff.

### Reverse lookup

- Only names in `indexed_properties` that do not start with `list:` are indexed
  (`db/dynamodb/property.py:114-125`). A lookup reads only the lookup table,
  then the property row (`:192-221`). A value held only in another store is
  never found (AC-14).
- A collision on DynamoDB: the transaction's lookup condition fails. The code
  logs `LOOKUP_COLLISION` at error level and writes the property alone
  (`db/dynamodb/property.py:467-501`). If the holder no longer has the value,
  it takes the row over (`:473-484`).
- A collision on PostgreSQL: `claim_in_transaction` logs `LOOKUP_CONFLICT` at
  warning level and returns `"held"`. The property commits
  (`db/postgresql/property_lookup.py:77-83`).
- Pinned by `tests/test_property_lookup_sync.py:124-181`. This is the AC-27
  baseline.

### Removal paths

- **Actor.** `Actor.delete` (`actor.py:1611-1722`) does:
  1. `Properties.delete`, which removes the actor's partition and its lookup
     rows, then sweeps `{actor_id}$aux` (`property.py:470-525`);
  2. `Buckets.delete`, which deletes by `actor_id`
     (`db/dynamodb/attribute.py:1059-1069`, `db/postgresql/attribute.py:1322-1354`);
  3. the actor row, last.

  PostgreSQL has no foreign key from `properties` or `attributes` to
  `actors`; only `property_lookup` cascades (`schema.py:91-96`). A new table
  is reached only if a call is added here, or if it is a `$`-partition that
  `Properties.delete` sweeps.
- **Bucket.** `Attributes.delete_bucket` deletes `{bucket}$aux` and then the
  bucket (`attribute.py:736-764`). `maintenance/peer_state.py:299` calls the
  backend's `delete_bucket` directly. It reports `remote:<peer>$aux` side
  buckets as findings of their own (`peer_state.py:47-50,148-160`), so they
  are pruned separately, not skipped. A new version store would need the same
  treatment there.
- **Trust.** `delete_reciprocal_trust` calls `RemotePeerStore.delete_all()`,
  which calls `Attributes.delete_bucket("remote:{peer}")`
  (`actor.py:3397-3418`, `remote_storage.py:433-440`). So does
  `delete_subscription` (`actor.py:3983-4002`). A narrowed grant deletes names
  row by row (`replica_revocation.py:131-160`).

  None of this touches the actor's own data. "Data that goes with a trust"
  (AC-40) is the replica bucket `remote:{peer}`, which holds peer-written data
  replicated in. Whether it should be versionable at all is open.
- PLS-D4 holds: actor deletion and trust revocation remove rows directly, not
  through `ListCore.delete()`.

### List elements today

**Addressing.**
- v2 lists (every new list, and attribute lists) store items at
  `list:{name}-#{rank}`, where the rank is a base62 fractional key
  (`property_list.py:503-505`, `attribute_list.py:1-13`).
- Insert and delete touch one row. Other rows are not rewritten
  (`list_core.py:2265-2279,3395-3421`).
- v1 lists shift rows (`property_list.py:833-869,1254-1270`).
- There is no `move`: a move is a delete plus an insert, with a new rank.

**The rank is a near-identity.** It is stable across inserts and deletes of
other elements. Three things break it:
- `compact()` renames ranks (`list_core.py:4454-4658`);
- a deleted tail rank is reissued, since generation is deterministic
  (`list_core.py:396-403`);
- delete plus recreate resets ranks
  (`thoughts/research/2026-08-20-v2-positional-access-cost.md:16-46`).

`ListItemHandle` is "not wire-stable … never persist or transmit one"
(`list_core.py:386-423`).

**`append_once` key.**
- It is application-supplied and stored as an HMAC in the envelope `key` and
  in a `$key-` side row (`list_core.py:2528-2545`).
- It survives `[i]=`, `update_by_handle` and `compact()`, and is removed with
  the item (`list_core.py:2823-2826,4660-4684`).
- Only `append_once` sets it. `insert`, `extend` and REST take no keys
  (CHANGELOG.rst:3455-3456). An existing element cannot be given one, and
  delete plus insert loses it.
- The first keyed item makes the list unreadable to readers older than 4.0
  (`list_core.py:2874-2876`).

**Envelope rules.**
- Unknown fields go to `Envelope.extra`. They are ignored on read and carried
  by rewrites, but they belong to the rank slot, not to the value
  (`property_list_span.py:166,335`, `list_core.py:978-991,2232,2243`).
  `append`, `insert` and `extend` create heads without them.
- `need` names features. 4.0.0 implements none (`IMPLEMENTED_NEEDS = frozenset()`,
  `property_list_span.py:168-169`). An item that names one is refused for
  read, write, move and repair (PLS-3).
- PLS-D2 forbids carrying a field a writer must maintain in a field 4.0.0
  ignores. An identity the library maintains therefore needs a `need` name.
- A new side-row kind (PLS-D3) is left alone by 4.0.0's clear, delete and
  sweep, and actor deletion and `delete_bucket` reap it (`property.py:490-516`,
  `attribute.py:736-754`).

**Whole-list delete and clear.**
- `clear()` deletes heads, bodies and key rows and resets meta
  (`list_core.py:3141-3204`). `delete()` also deletes the meta row (`:3206-3250`).
- Rows in a separate store are not touched. Neither are side rows of a kind
  4.0.0 does not recognise (PLS-4).

**Prior decisions.**
- "Stable ids + an order array in meta" was rejected for fractional keys
  (`research/2026-08-07-property-list-index-integrity.md:427-449`).
- A writer token on every item was cut for roll-back readability
  (`plans/2026-11-19-emm-4-0-adoption-findings.md:140-141`).
- A list incarnation id was deferred (`:135-137`).
- `todo/prop-list-key-prefix-scheme.md:68-119` records the need for
  out-of-band per-item payload: 66.3% of a consumer partition was embedding
  bytes. This is L3's problem.
- `todo/list-items-conditional-create-ttl-and-retained-bodies.md` (V4):
  retaining a previous span generation needs a new locating field via `need`.

### What the wire carries for a list element

- `/properties/<list>`, `/<list>/<n>`, `?format=full` and `/items` return
  `_resolve`'s decoded value through the get hook
  (`handlers/properties.py:997-1104,1435-1481,3021-3076`; `list_core.py:1215-1238`).
  Rank, `key`, `tok`, `span` and `extra` never leave the library.
- Diffs (`build_list_diff`, `property_list.py:202-243`) carry the whole value
  the caller passed, or the post-hook value on REST. `old_item` is read from
  the handle. Diffs do not pass through get hooks.
- Over the span threshold, or for an unread spanned item, a diff becomes a
  reference (`property_list.py:259-319`). That threshold is none at
  PostgreSQL defaults.
- Delivery filters by the peer's grant per path (`actor.py:4054-4088,4301-4328`).
- Answer to the open question: yes, the whole stored element, embedding
  included, is what `/properties` and diffs carry. No application data per
  element is stored without being sent. An L3 home for such data would be new
  (a side-row kind or an envelope field under `need`). Anything moved there
  stops reaching subscribers, whose replicas hold it today
  (`remote_storage.py:855-990`).

### The consumer (Emm)

**What is stored, and how** (all three are property lists; there are no
attribute lists):

| Item | Storage | Element identity | Embedding |
| --- | --- | --- | --- |
| Memory | `memory_<type>`, one element each | per-type integer counter, never reused (`emm:memory_id_seq.py:5,43`), **reassigned on a move to another type** (`emm:repositories/local_memory_repository.py:448,477`) | inline `embedding` on the element, written by a second `update_item` after each save (`emm:memory_service.py:850-855,1906-1911`) |
| Document | `output_<category>`, one element each | `(origin_category, seq)`, kept across moves (`emm:output_repository.py:352-370,1430+`) | sidecar list `output_embeddings_<body>` (`emm:output_repository.py:1683-1690`) |
| Instruction | `instruction_<name>`, one element, `id` 1 (`emm:instruction_repository.py:3-7,57`) | the list name | none |

**The audit log.**
- `emm:repositories/audit_log_repository.py`. 20 records per resource
  (`:46`), overwritten in place at the cap (`:165-185`).
- It never raises (`:186-190`, with a second catch at
  `emm:instruction_repository.py:387-390`).
- The overview reads every list with `list_all_with_rows()` (`:206-249`).
- Full snapshots are forbidden for memories and outputs: "would balloon
  storage" (`:4-9`).
- Snapshots are taken on content-changing saves with an origin, and on
  delete (`emm:instruction_repository.py:280-281,300-301`).
- Restore actions exist (`guided_assembler.py`, "restore"), but there is no
  restore endpoint.

**Metadata.**
- `{who, how}` from `emm:helpers/write_origin.py:71-104`. Examples: "You" /
  "web app · guided", "AI agent" / "<client> · <description>".
- Plus `action`, which is one of create, update, delete, reset, merge,
  rewrite, assemble or restore.
- Documents already set `last_edited_by` "agent" or "user" on the element.

**Where to take a version.**
- Every instruction write goes through `InstructionRepository.save()`.
- Document writes go through `update_by_handle` from several MCP tools
  (`output_update`, `output_edit`, `output_publish_html`) and the web PUT.
  `touch=False` marks system rewrites.
- Memory writes come from MCP `memory_update`, a web PUT and a merge.
- Delete paths exist for all three, including batch delete (25 items) and
  whole-type or whole-category deletes. Emm needs versions of deleted
  elements.

**Sizes.**
- A document row is capped at 380,000 bytes (`emm:helpers/output_limits.py:9`).
- Memory bodies have no limit. A free tier allows 30 memories.
- Instruction bodies can be up to 1,000,000 characters through the merge API.
- The code gives the memory embedding as 1024 or 768 dimensions; the two
  places disagree. About 12 KB is quoted.
- No volume numbers are recorded.

### Backend selection and custom backends

- The backend is `database` or `DATABASE_BACKEND`. Config imports eight
  modules from `actingweb.db.<name>` (`config.py:449-472`). There is no
  registry, and a missing module is an `ImportError` at Config construction.
- The factories call `config.DbX.DbX(...)` with no checks (`db/__init__.py:70-87,339-361`).
  A missing method is an `AttributeError` at the first call.
- Probe precedent: `ATTRIBUTE_LIST_PRIMITIVES` (`db/protocols.py:1722-1735`),
  checked by `_check_attribute_schema_ready`, raises `AttributeSchemaNotReady`
  (`app.py:2050-2068`). `rename_creator` raises `EmailAsCreatorNotReady`
  (`app.py:2028-2034`). The optional class attribute `MAX_ROW_BYTES` is read
  with `getattr`.
- The contract is documented in `docs/migration/v4.0.rst:3617-3700` and
  `docs/reference/database-backends.rst:555-602`.

### Configuration and errors

- The `with_*` pattern:
  - keyword-only arguments, validated, stored privately, applied by
    `_apply_runtime_changes_to_config` (`app.py:273-340`);
  - the closest analogue for an app-wide limit is `with_list_item_limits`
    (`app.py:787-842`, `config.py:534-556`);
  - the analogue for an env-var counterpart is `with_indexed_properties`
    (builder over env over default, `app.py:559-593,1700-1708`).
- No exception means "feature not configured". Today a missing service is a
  plain `RuntimeError` (`interface/actor_interface.py:395-402`), and a lookup
  on an unindexed name logs and returns `None`. AC-3 needs a new class. The
  public error homes are `db/exceptions.py` (only `DbError` re-exported) and
  top-level re-exports in `actingweb/__init__.py:39-87`.
- Where the public API would sit:
  - `PropertyStore` (`interface/property_store.py:33`) holds the hooks and
    config a restore needs.
  - `NotifyingListProperty` (`:325`) for property list elements.
  - `Attributes` (`attribute.py:300`). Apps construct it directly; there is
    no interface accessor.
  - `ListAttribute` / `AttributeListStore` for attribute list elements.

### Storage accounting

- No per-actor or per-account storage figure exists. The only size figure is
  `GET /<actor>/properties?metadata=true`. It reports `total_bytes` for
  visible plain properties and per-list head sizes, with no attributes and
  no `$aux` (`handlers/properties.py:1290,1396-1434`).
- No consumed-capacity or `pg_*_size` reads exist anywhere.
- So "storage per account with history on" (Success Measures) cannot be
  observed without new code: a count or bytes figure per item, kept by the
  version store, or an operator report.

### Release shape

- `CONTRIBUTING.rst:183-204`. New configuration and public methods rule out
  a patch. A minor needs an unchanged application to keep working, with
  stored data readable by the previous minor unless an opt-in or an operator
  step changed it. The rule says nothing explicit about a new backend
  protocol method. The precedent is 4.0's `ATTRIBUTE_LIST_PRIMITIVES` probe.
- An opt-in store that a non-configured app never touches is a **minor
  (4.1.0)**, with `docs/migration/v4.1.rst` and an index row.
- 4.0.0 is not final (`pyproject.toml:3`, `4.0.0rc4`). Landing it in 4.0.0
  is possible and is the owner's call.
- An L1 element identity under `need` is safe as an opt-in. Old readers
  refuse only the lists where it was turned on: "unreadable only after an
  opt-in call" in the minor rule.

## Acceptance Criteria Testability

Every AC runs on both backends through `DATABASE_BACKEND`; the suite is the
same (`docs/contributing/backend-testing.rst:34,104-109`, AC-44).

| AC | Code path | Test level and harness |
| --- | --- | --- |
| AC-1 | `check_ready()` gates (`app.py:1787-1850`); `required_models()` conditional (`verify_tables.py:77-80`) | integration: start with versioning off on a store without the new table/revision; precedent `tests/integration/test_unique_creator_empty_store.py` |
| AC-2 | new store untouched when off | unit: `count_dynamodb_operations` (`tests/_read_counters.py:38-53`) on DynamoDB; PostgreSQL: absence of the table/rows |
| AC-3 | new exception at the version API entry | unit |
| AC-4, 5 | new API on `PropertyStore` / `Attributes` / list classes → new backend method | unit plus integration, both backends |
| AC-6 | DynamoDB `Query` paging; PG `ORDER BY` | integration, 1000 rows (slow; mark like benchmarks or keep small rows) |
| AC-7 | retention at write | unit |
| AC-8 | read current first | unit |
| AC-9, 28 | backend fault | `backend_fault`, `seam_fault` (`tests/_adoption_helpers.py:99,147`); `backend_fault` patches only the attribute backend, so property faults use `seam_fault` or a new helper |
| AC-10 | `fetch`, `fetch_all_including_lists`, `DbAttributeBucketList.fetch` | unit, both backends; **under a `{bucket}$ver`-style attribute layout the bucket listing would show it** (see Decision 1) |
| AC-11, 12 | `handlers/properties.py` reads | integration, `test_app`/`peer_app` fixtures (`tests/integration/conftest.py:483+`) |
| AC-13, 15 | `register_diffs` only from explicit writers | unit: spy on `register_diffs`; `tests/test_property_store_notifications.py` pattern |
| AC-14 | lookup table only | unit, `tests/test_property_lookup_sync.py` pattern |
| AC-16 | read paths | DynamoDB: `count_dynamodb_operations` exact counts (precedent `tests/test_list_prefix_with_rows.py:286-300`). PostgreSQL: `count_reads` counts connections, not statements or rows: weak; a statement counter is missing |
| AC-17–22 | new API | unit plus integration |
| AC-23, 24, 25 | restore → new atomic backend call → `register_diffs` | unit plus integration |
| AC-26 | which "normal write" (Python vs HTTP, hook-returns-None behaviour) must be named first | unit with a registered put hook |
| AC-27 | collision baseline `tests/test_property_lookup_sync.py:124-137` | unit, both backends |
| AC-29–32 | depends on Decision 3 | unit; parity over property and attribute lists via `tests/_attribute_parity.py` |
| AC-33, 34, 35, 36, 37 | new API | unit |
| AC-38 | `Actor.delete` (`actor.py:1611-1722`) | integration: delete actor, scan the version store |
| AC-39 | `Attributes.delete_bucket` (`attribute.py:736-764`); `peer_state.py:299` deletes buckets through the backend directly | unit |
| AC-40 | `RemotePeerStore.delete_all` (`remote_storage.py:433-440`) | integration with `trust_helper`; needs the scope answered (Decision 8) |
| AC-41–43 | depends on Decision 6 | unit |

## Documentation Impact

### Configuration (`with_*` for versioning)

- `docs/quickstart/configuration.rst:40-70` ("Runtime Switches"): needs a new
  bullet. The list-limits bullet at `:51-68` is the model.
- `docs/quickstart/configuration.rst:486-497`: env precedence, if an env var
  is added.

### Version API (take, list, read, restore, remove)

- `docs/sdk/actor-interface.rst:79-86` lists `PropertyStore` methods only
  as get/set/delete/update/to_dict. It needs the new methods.
- `docs/sdk/attributes-buckets.rst` (sections `:63,165,218,265,277`) needs a
  version-history section. Its custom backend paragraph is at `:309-314`.
- `docs/guides/property-lists.rst:71-118` (attribute lists) and a new section
  on element history. `:98-105` ("no route serves it") stays true and should
  say versions are equally private.
- `docs/reference/interface-api.rst` (automodule) picks up new classes.

### Delete semantics

- `docs/sdk/actor-interface.rst:84` says "`delete(key)`: Remove property".
  Under AC-33 a delete leaves history, so it needs qualifying.
- `docs/sdk/attributes-buckets.rst:486-516` ("All actor properties deleted",
  "removes ALL buckets") stays true only if versions go with them.
- `docs/reference/actor-deletion.rst:42-71` (deletion order) needs a
  versions step.
- `docs/guides/trust-relationships.rst:150-166`,
  `docs/guides/subscriptions.rst:475` and
  `docs/quickstart/configuration.rst:989-1006` (replica deletion on revoke)
  are affected only if replica buckets are versionable.

### Hooks

- `docs/reference/hooks-reference.rst:12-51,475`: state that version calls fire
  nothing and that a restore fires what the chosen write path fires.

### Backends and maintenance

- `docs/reference/database-backends.rst:329-379,381-505`: table mapping and
  required tables, for a new table (with a "Required when" row).
- `docs/reference/database-backends.rst:555-602` and
  `docs/migration/v4.0.rst:3617-3700`: the custom backend contract (a new
  method plus its probe).
- `docs/reference/database-backends.rst:180` says "25 operations per
  transaction". **This is already wrong against AWS** (100 items, 4 MB).
- `docs/guides/database-maintenance.rst:132,866`: `actingweb-verify-orphans`
  must know a new store or partition kind.

### Release

- `CHANGELOG.rst` Unreleased (empty, `:5-6`) gets an ADDED entry.
- `docs/migration/v4.1.rst` plus its `docs/migration/index.rst` row, if a minor.
- Released migration guides and changelog sections stay as they are.

### Protocol specification

- None. History is not on the wire (Not In Scope). `docs/protocol/` is
  unaffected.

## Reuse and New Patterns

**Nearest analogue:** the property-list side partition `{actor_id}$aux`, a
hidden partition in the existing properties table. No actor read returns it,
actor deletion sweeps it, `verify_orphans` reports it, and no schema change
was needed (`property.py:470-525`). It has the same scope (per actor, private
to the library) and the same auth path (none: there is no route). For the
write side, the nearest analogue is DynamoDB's property plus lookup
transaction and PostgreSQL's `_set_indexed`: a value row plus a second row
committed in one backend call.

| Need | Existing piece | State | Evidence |
| --- | --- | --- | --- |
| Hidden per-actor store (properties table) | `{actor_id}$aux` partition, `aux_partition()` | reusable as-is (a new `$<kind>`) | `property.py:470-525`, `property_list_span.py:505-517` |
| Hidden per-actor store (attributes table) | `{bucket}$aux` is in the actor partition and is listed | nothing exists that is hidden | `db/dynamodb/attribute.py:1012-1035` |
| Opt-in table (DynamoDB) | conditional `required_models()` (`Creator`) | reusable as-is | `verify_tables.py:77-80` |
| Opt-in table (PostgreSQL) | chain revision plus a config-gated check, or an out-of-chain object built by a command | embedded pattern (copy) | `app.py:1880-1899`; `schema.py:37-55`, `unique_creators.py:1266` |
| Atomic two-row write | DynamoDB `_run_transaction`; PG single-connection transaction | embedded in the indexed-set path; a new backend method copies the shape | `db/dynamodb/actor.py:815-880`, `db/postgresql/property.py:293-359` |
| Restore as an ordinary write | `PropertyStore.__setitem__` hook → write → `register_diffs` → `DbErrorAfterWrite` | embedded in `PropertyStore`; restore needs the same steps around a different backend call | `interface/property_store.py:101-147` |
| Large version bodies | span codec (`property_list_span.py`) | exists, embedded in list code | `list_core.py:936-1044` |
| CAS write for restore | `set_if_value_equals` (properties), `set_attr_if_data_equals` (attributes) | reusable for non-indexed names; properties CAS skips lookup maintenance | `db/protocols.py:588-636,1681-1702` |
| Element key (app-supplied) | `append_once` key (HMAC, `$key-` row) | exists but embedded; set only by `append_once` | `list_core.py:2528-2545` |
| Element identity (library) | v2 rank | not durable (`compact`, reuse) | `list_core.py:396-423,4454-4658` |
| Config builder plus limit | `with_list_item_limits` | reusable pattern | `app.py:787-842` |
| Custom-backend probe | `ATTRIBUTE_LIST_PRIMITIVES` plus `check_ready` | reusable pattern | `db/protocols.py:1722-1735`, `app.py:2050-2068` |
| "Not configured" error | none | nothing exists | |
| Store-call counter | `tests/_read_counters.py` | reusable on DynamoDB; weak on PG | `tests/_read_counters.py:38-93` |
| Storage accounting | none | nothing exists | |
| Paging over a store | none in public calls | nothing exists | |

**Embedded pieces.**
- Restore's hook-write-diff sequence can be copied locally inside
  `PropertyStore` (a `restore()` that calls a new backend method in place of
  `self._core_store[key] = v`), or extracted into a shared helper. The
  extraction touches `__setitem__`, `__delitem__` and `clear`, which raise
  `DbErrorAfterWrite`: that is a fault path under spec (PLS-2).
- The span codec is list-specific (row names carry the list name). Reusing
  it for version bodies needs a locating field
  (`todo/list-items-conditional-create-ttl-and-retained-bodies.md` V4).

**Simplifications that change an AC or the scope** (owner's call):
- **S1.** Store versions in a `{actor_id}$ver` partition of the **properties**
  table, for all three item kinds, attributes included (the value encoded as
  text). This avoids a new table on both backends, an Alembic revision, a
  `required_models` entry and a new `Actor.delete` call: the actor sweep
  gains a second partition. It changes **AC-1/AC-2** (trivially met) and
  **AC-39**: a bucket delete must sweep the bucket's versions out of another
  table's partition. Other costs:
  - `actingweb-verify-orphans` must learn the `$ver` kind, as it knows `$aux`
    (`maintenance/verify_orphans.py:31-35,212`).
  - The lookup backfill scans the properties table. It skips rows whose id
    is not an actor: PostgreSQL by `JOIN actors`
    (`maintenance/property_lookup.py:767,971`), DynamoDB by `_actor_exists`
    (`:568-585`). A `$ver` row is never indexed (AC-14), but on DynamoDB it is
    counted under `orphans` in the backfill report.
  - One text row per version means a content-free listing reads the content
    (Decision 7, AC-17).
- **S2.** Restore only for plain properties and attributes. List elements get
  take/list/read/remove under an application key (L2), and the application
  writes the value back. This avoids a new list-storage primitive, and an
  atomic restore that is not available for spanned elements anyway. It drops **AC-30, AC-31**, narrows **AC-28** to non-list items
  (already the case under L2), and changes **AC-23/26** for lists to "the
  application's write".
- **S3.** A version holds a value the application passes, defaulting to the
  current value. This avoids copying memory embeddings into every version
  (the wall named in `emm:audit_log_repository.py:4-9`). It changes **AC-4**:
  "holding the current value" becomes "holding the given or current value".
- **S4.** No automatic versioning in this round. This avoids a hook in 13
  backend entry points or a partial interface-layer hook. It drops
  **AC-41–43**.
- **S5.** Replica buckets (`remote:*`) are not versionable. **AC-40**
  becomes vacuous: the actor's own data has no trust-tied versions.

## Size Estimate

**Method.** Each moving part is sized against merged PRs that did similar
work, in lines of library code, tests and total diff (tests plus `docs/`
plus `thoughts/`). Time is taken from the PRs' commit dates. The figures
count lines and calendar days only; no effort or hours are recorded.

**Calibration** (`git diff --shortstat` over each merge):

| PR | Shape | Library | Tests | Total | Calendar |
| --- | --- | --- | --- | --- | --- |
| #191 attribute compare-and-delete | one new backend primitive on both backends, public API, spec delta | ~390 | ~980 | ~2,950 | 1 day, 4 commits |
| #188 rc3 consumer fixes | several fixes across the library | ~765 | ~1,520 | ~4,420 | 1 day, 8 commits |
| #187 rc2 consumer fixes | several fixes, faults | ~640 | ~1,520 | ~3,850 | 1 day |
| #172 grant enforcement | cross-cutting change on every route | ~5,300 | ~34,500 | ~46,600 | 2 days, 24 commits |
| #171 peer authorisation | cross-cutting, wire recordings | ~3,600 | ~73,500 | ~96,500 | 6 days, 65 commits |

The ratio in this repository is about 2.5 test lines per library line for a
storage primitive (#191, #188). It rises far above that for cross-cutting
changes, where the tests and recordings dominate.

**Moving parts** (library lines, both backends; tests follow the ratio):

| Part | Unit of comparison | Library | Note |
| --- | --- | --- | --- |
| Backend version primitives: take, list, get, remove, remove-all, retention trim | ≈ 2–3 × #191 | 700–1,000 | both backends, protocol plus probe |
| Atomic restore, property (including indexed path) and attribute | ≈ 1 × #191 | 300–500 | copies `_write_indexed` / `_set_indexed` shape |
| Public API on `PropertyStore`, `Attributes`, list classes (key-based) | small | 300–500 | restore copies the hook → write → diff sequence |
| Config builder, error class, `check_ready` probe | small | 100–200 | `with_list_item_limits` and `ATTRIBUTE_LIST_PRIMITIVES` patterns |
| Removal: actor sweep, bucket delete, `peer_state`, `verify_orphans` | small | 150–300 | `$aux` sweep pattern |
| DynamoDB size: cap below 400 KB (no spanning) | trivial | 30–50 | spanning instead: +400–700 |
| Docs, changelog, `v4.1.rst`, spec delta | — | — | 1,000–1,500 doc lines |

**Scopes:**

| Scope | Contents | Library | Tests | Total | Phases | Calendar |
| --- | --- | --- | --- | --- | --- | --- |
| A, lean | S1–S5, L2, cap instead of spanning | 1,500–2,500 | 3,000–5,000 | 7–10k | 3–4 | 3–5 days |
| B, middle | A plus a dedicated table, a list restore primitive for unspanned elements, spanning on DynamoDB | 3,500–5,000 | 8–12k | 15–20k | 5–6 | 1.5–2 weeks |
| C, full feature doc | B plus L1 identity under `need`, automatic versioning | 6–8k | 20k+ | 30k+ | 7+ | 2–3+ weeks |

**Not counted:**
- Emm's adoption work (replacing its audit log, history for memories and
  documents).
- A `/create_spec` for properties and attributes, which `/create_plan` will
  offer first (no spec covers them).
- The Full tier on both backends per phase.

**Confidence.** Scope A is close to the calibration PRs in shape and is
likely within ±30%. Scope C contains two kinds of work this repository has no
direct precedent for: a stored-format identity that every list operation
maintains, and a write-path interceptor. The grant-enforcement PRs show that
cross-cutting work in this repository grows mostly in tests, so C's upper
bound is open.

## Decisions Needed

Each option carries a **Size** line: the change it makes to Scope A (the lean
baseline) in [Size Estimate](#size-estimate). Size is one input beside the
evidence; it does not override a correctness or security finding.

### Decision 1: Where versions are stored

**Options:**
1. **A new table per backend** (the hypothesis).
   - Clean separation and a natural key: (actor, item key, version order).
   - **New paradigm: a new table.**
     - DynamoDB: a conditional `required_models()` entry and auto-create.
     - PostgreSQL: either a chain revision (an empty table for everyone who
       runs `alembic upgrade head`, checked only when configured) or an
       out-of-chain object built by a command (`ux_actors_creator` precedent).
     - A `check_ready` gate, a new `Actor.delete` step, `verify_tables` and
       `verify_orphans` awareness, and `UndefinedTable` tolerance on delete.
   - Atomic restore across tables is possible on both backends: a DynamoDB
     transaction, or one PG connection.
   - **Size:** +800–1,500 library and deploy lines (Alembic revision, model,
     `required_models` flag, ready gate, `verify_tables` flag, deletion step,
     two docs tables), about +1 phase, +1–2 days. It also adds an operator step
     for opted-in PostgreSQL deployments.
2. **A hidden partition in the existing properties table** (S1,
   `{actor_id}$ver`).
   - No schema change, no operator step on either backend.
   - Actor deletion already sweeps `$aux` and gains one more prefix.
   - Atomic with a property write (same table) on both backends.
   - For attributes: a cross-table transaction (attributes plus properties).
     DynamoDB supports it, and PG does if both go on one connection.
   - Values are text. The rows sit next to user data, so a full-table scan
     tool (`verify_orphans`) must learn the kind.
   - A bucket delete must reach into the properties table.
   - **Size:** baseline (Scope A). About 200–400 library lines across the
     sweep, the bucket-delete reach-in and `verify_orphans`.
3. **A `$ver` partition in each item's own table.** Property versions go in
   the properties table under `{actor_id}$ver`. Attribute versions go in the
   attributes table under `{actor_id}$ver`, a partition with no precedent and
   no delete path yet.
   - Same-table atomicity for both kinds.
   - Attribute-side deletion and orphan reporting are new.
   - **Size:** +300–600 over option 2. A new delete path in the attributes
     table on both backends, plus orphan reporting for it; no phase added.

**Recommendation:** none on evidence alone. The evidence weighs schema cost
(option 1) against reuse with cross-table attribute writes (options 2 and 3).
Size favours option 2: it is about a phase and an operator step smaller than
option 1. Option 3 sits between them.

### Decision 2: The atomic restore boundary (AC-28)

**Options:**
1. **A new backend method per kind** (`restore`, or a `set_with_version`).
   - Commits the pre-restore version, the new value and the lookup claim
     together.
   - Diffs follow as usual, and their failure is `DbErrorAfterWrite`.
   - Delivers AC-28 for properties and attributes.
   - New protocol method(s), probed in `check_ready()` only when versioning
     is configured.
   - **Size:** baseline (counted in Scope A as "atomic restore"), 300–500
     library lines.
2. **Two public calls** (take version, then write).
   - The "minimal" alternative the feature rejected. A crash between the
     calls leaves an extra version, never a partial value.
   - So "partial" means an orphan version, not a wrong current value. Worth
     stating, since the feature doc framed it as a partial value.
   - It also has a window: a write that lands between the two calls is
     overwritten with no version of it. A compare-and-swap on the second call
     closes that window: `set_if_value_equals` for properties,
     `set_attr_if_data_equals` for attributes. But `set_if_value_equals` does
     no lookup maintenance, because it is only for `list:` names
     (`db/protocols.py:588-636`). So it cannot restore an indexed property
     as it stands.
   - **Size:** −200–300 library lines against option 1 for non-indexed
     names. An indexed property still needs a CAS that maintains the lookup,
     which is most of option 1's work. The saving is small and buys a weaker
     AC-28.

### Decision 3: List-element history (L1, L2, L3)

**Options:**
1. **L2 with an application string key.** Emm passes `memory_<type>/<id>`,
   `output:<origin>/<seq>` or `instruction_<name>`.
   - Needs nothing from lists. No `need`, no migration.
   - A version of a deleted element stays listed, because the store does not
     check the element.
   - Fits documents (`(origin_category, seq)` survives moves) and
     instructions.
   - A memory's history does not follow a move to another type. Both parts
     of `memory_<type>/<id>` change, because the move reassigns the id. That
     holds unless Emm adopts a key that survives the move, or the store
     offers a re-key call (new surface).
   - Gives consumers without element ids nothing.
   - Key length: the key would sit in a row name or a sort key. DynamoDB
     allows sort keys up to 1024 bytes; PostgreSQL `name` is `TEXT`
     (`e5f6a7b8c9d0` widened it). A bound has to be chosen.
   - **Size:** baseline. List classes gain thin key-based wrappers over the
     same primitives as properties (~100–200 library lines).
2. **L1 via `append_once`-style keys.** Let `insert` and `append` take an
   application key, and allow assigning a key to an existing element.
   - Reuses the HMAC key plus `$key-` row and the rewrite-carrying rules.
   - Still an application-supplied key, so it does not solve "no ids".
   - Makes the list unreadable before 4.0, as keys already do.
   - **Size:** +500–900 library lines. Key arguments on `insert`/`append`,
     assigning a key to an existing element, REST pass-through or not, and
     parity on both list kinds. About +1 phase.
3. **L1, a library-minted identity.**
   - A new envelope field under a `need` name (PLS-D2), which 4.0.0 readers
     refuse (PLS-3), opt-in per list.
   - **New protocol concept on the stored format.**
   - Every list operation must maintain it, including `insert`, `extend`,
     REST, `compact` and moves.
   - The rank cannot stand in (`compact`, reuse).
   - If 4.0.0 final ships with the `need` name in `IMPLEMENTED_NEEDS`, the
     refusal applies only to rc readers.
   - **Size:** +1,500–2,500 library lines and the largest test growth. Every
     list operation on both list kinds and both backends, `compact`, REST,
     the newer-format refusal tests (PLS-3) and a roll-back story. About +2
     phases and +1 week. This is the main item that turns Scope B into C.
4. **L3.** Per-element application-only data.
   - **New paradigm**: a side-row kind, or an envelope field under `need`.
   - Anything moved there stops reaching subscribers' replicas.
   - The problem is already recorded separately in
     `todo/prop-list-key-prefix-scheme.md`. It fits the feature doc's
     "separate capability".
   - **Size:** a feature of its own, at least the size of option 3, plus
     subscriber-side changes. Not estimated further here.

**One interface for L1 and L2?** Yes, as far as the code goes. If version
calls take an opaque item key, an L1 identity can be handed to the
application (as `AppendOnceResult` hands back a handle) and passed where Emm
passes its own string. Nothing in the store needs to tell the two apart.

**Recommendation:** L2 with an application string key for this round. Emm
has a key for documents and instructions; memories lose history across a
type move. L1 (option 3) is the only way to give history to consumers
without ids; its cost is a `need` name and about +2 phases. Size and
evidence point the same way. Because one interface serves both, L1 can
follow in a later minor without changing the L2 calls.

### Decision 4: Restore semantics the owner left open

These are not answerable from code:
- turning versioning off after it was on;
- whether automatic versioning plus restore makes one version or two;
- what restoring a deleted item saves first (nothing, or an "empty" version);
- whether removal is also by `-x`;
- whether lowering the limit drops surplus versions at once or lazily.

Also open:
- the placement default under L1/L3;
- a metadata size bound;
- confirming "oldest dropped at the limit".

External precedent:
- S3 restores by copying the old version forward, and the previous current
  version is kept (AC-23 matches).
- S3's delete is a marker that is itself a version. That is one answer to
  "what does restoring a deleted item save".
- S3 retention is count-based (`NewerNoncurrentVersions`, 1–100) and applies
  only to noncurrent versions, which is the AC-7 shape.

What the code does fix:
- "Lazy" retention means the trim happens on that item's next version write
  (one query plus deletes).
- "At once" needs a scan, which is a maintenance command (the
  `actingweb-property-lookup` precedent).

**Size:** none of the semantic choices moves the estimate by more than a few
dozen lines each, except two. "Drop at once when the limit is lowered" adds
a maintenance command (+300–500 library lines, by `actingweb-property-lookup`
and `operator-commands` spec precedent). "Removed when versioning is turned
off" adds the same scan. Lazy behaviour for both is the baseline.

### Decision 5: What a version holds

**Options:**
1. **The whole stored value** (AC-4 as written). For memories this copies the
   embedding into every version.
   - **Size:** baseline.
2. **A value the application passes, defaulting to the current value**
   (S3). This lets Emm leave the embedding out.
   - **Size:** +50–100 library lines, one optional argument plus validation.
     It changes Emm's storage growth far more than the library's size.
3. **Separately: metadata bounds.** Emm's metadata is a few short strings.
   With a version store on DynamoDB, value plus metadata must fit 400 KB or
   be spanned.
   - **Size:** a cap is trivial (baseline). Spanning version bodies is
     +400–700 library lines: the span codec needs a locating field outside
     list row names (`todo/list-items-conditional-create-ttl-and-retained-bodies.md`
     V4). That is about half a phase.

### Decision 6: Automatic versioning

**Options:**
1. **Drop it this round** (S4).
   - **Size:** baseline.
2. **At the interface layer.** Hook into `PropertyStore.__setitem__` and
   `__delitem__`, the `NotifyingListProperty` mutators, and the `Attributes`
   methods.
   - Granularity per property name or bucket is expressible here.
   - It misses the HTTP handlers, `www.py`, `service_client` and the replica
     writers, which write the core store directly.
   - It adds a read before each blind write. On DynamoDB each item in a
     transaction costs two writes (prepare plus commit), so an atomic
     version-then-write is about four write units where today's plain `set`
     is one.
   - Emm's second, embedding-only write makes a second version per memory
     save.
   - **Size:** +800–1,500 library lines. Hooks in the interface store, list
     mutators and `Attributes`, per-name and per-bucket configuration, and a
     read before blind writes. Tests cover every write path in both modes.
     About +1–2 phases. Closing the gap for HTTP, `www` and replicas means
     routing those writers through the interface store: a sweep the size of
     #172 in kind, if not in lines.
3. **At the backend layer.** Five property and eight attribute entry points,
   plus `rename_creator`.
   - It catches everything, but cannot tell list plumbing (meta, `$span-`,
     `$key-`, v1 shifts) or library buckets from application values without
     parsing row names.
   - **New paradigm: a write-path interceptor on a security-sensitive layer**
     (`_internal`, OAuth state).
   - **Size:** +1,500–2,500 library lines, the most uncertain figure here.
     It needs a row-name classifier for list plumbing and library buckets on
     13+ entry points and both backends, plus security review. Expect
     +2 phases or more.

The evidence shows options 2 and 3 are each either partial or entangled with
library internals. Size points the same way: automatic versioning is the
single largest optional item. Leaving it out roughly halves the distance
from Scope A to Scope C.

### Decision 7: Row layout and listing cost

- A content-free listing (AC-17) on DynamoDB reads whole items unless the
  content is in a separate row, or a projection is used. A `Query` with
  `ProjectionExpression` still consumes capacity for the full item size.
- Option: a metadata row per version plus a content row, or spanned bodies.
  That is two rows per version and two-row atomicity.
- On PostgreSQL a column list avoids reading TOASTed content.
- AC-19 ("all versions with content") with no limit has no paging precedent
  in the public calls. It needs an iterator or a documented cost.

**Size:** one row per version is the baseline. A separate metadata row plus
a content row is +300–500 library lines (two-row writes in every primitive
and in the restore transaction). An iterator for AC-19 is +100–200; a
documented cost is none.

### Decision 8: What removes versions

- Actor delete: no code path reaches a new store today. Under S1 or Decision 1
  option 2, extend `_delete_side_partition`. Otherwise add a step in
  `Actor.delete`.
- Bucket delete: `Attributes.delete_bucket`, plus the backend-direct
  `delete_bucket` in `maintenance/peer_state.py:299`. That one prunes `$aux`
  side buckets as separate findings, and would need the version store as
  another.
- Trust revoke (AC-40): only replica buckets are trust-tied. Are they
  versionable (S5)?
- Whole-list delete and clear (open question 17): keep versions, like an
  item delete (AC-33), or remove them? `ListCore.delete()` would need to reach
  the store.
- The "destructive delete" (AC-37): a new call, or a flag.

**Size:** actor and bucket removal are in the baseline. Versions removed
with a whole-list delete or clear adds a reach from `ListCore.delete()`/
`clear()` into the store on both list kinds (+150–300). Keeping them, like
an item delete, adds nothing. Versionable replica buckets (no S5) add
revocation and baseline-rebuild cases in `remote_storage.py` and
`replica_revocation.py` (+300–600, with subscription tests).

### Decision 9: Release

- A **minor (4.1.0)** with `docs/migration/v4.1.rst`, or inside **4.0.0**
  before final.
- If L1 (Decision 3 option 3) is chosen, shipping its `need` name in 4.0.0
  final limits the refusal to rc readers.

**Size:** the release choice does not change the code size. It does change
the calendar. Landing Scope A inside 4.0.0 holds 4.0.0 final for its 3–5
days plus an rc. Scope B or C inside 4.0.0 holds it for weeks. A minor
leaves 4.0.0 on its own schedule and adds `v4.1.rst` (counted in the docs
line).

## Code References

- `actingweb/property.py:470-525` - actor property delete, `$aux` sweep
- `actingweb/db/dynamodb/attribute.py:1012-1035` - bucket listing reads the whole actor partition
- `actingweb/db/verify_tables.py:42-81` - required DynamoDB tables, conditional `Creator`
- `actingweb/db/dynamodb/_ensure.py:73-107` - auto-create
- `actingweb/db/postgresql/schema.py:37-55` - out-of-chain `ux_actors_creator`
- `actingweb/interface/app.py:1787-1850,1876-1929,2050-2068` - `check_ready()` and probes
- `actingweb/db/dynamodb/actor.py:815-880` - transaction runner
- `actingweb/db/dynamodb/property.py:393-516` - property plus lookup transaction, collision
- `actingweb/db/postgresql/property.py:293-359,427-447` - indexed set transaction
- `actingweb/db/postgresql/property_lookup.py:77-83` - `LOOKUP_CONFLICT`
- `actingweb/interface/property_store.py:80,101-153,200-205` - hook, write, diff order
- `actingweb/db/exceptions.py:23-46` - `DbErrorAfterWrite`
- `actingweb/handlers/properties.py:1755-1854,2796-2873` - HTTP write and delete with hooks
- `actingweb/list_core.py:386-423,936-1044,2203-2279,2528-2545,3141-3250,4454-4684` - lists
- `actingweb/property_list_span.py:7-32,49-87,166-169,297-335` - envelope, span, `need`
- `actingweb/property_list.py:202-319` - list diffs
- `actingweb/actor.py:1611-1722,3397-3418,3983-4002` - actor, trust and subscription removal
- `actingweb/attribute.py:300,424-764,811-819` - `Attributes`, `Buckets`
- `actingweb/remote_storage.py:433-440` - replica bucket delete
- `actingweb/config.py:449-472` - backend module import
- `actingweb/db/protocols.py:1722-1735` - `ATTRIBUTE_LIST_PRIMITIVES`
- `tests/_read_counters.py:38-93` - call counters
- `tests/_adoption_helpers.py:99-147` - fault injection
- `tests/test_property_lookup_sync.py:124-181` - collision baseline
- `emm:repositories/audit_log_repository.py:4-9,46,165-249` - Emm audit log
- `emm:repositories/local_memory_repository.py:448,477` - memory id reassigned on move
- `emm:output_repository.py:352-370,1683-1690` - document identity, embedding sidecar

## External References

- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-sort-keys.html#bp-sort-keys-version-control - version items with a `v0_`/`vN_` sort-key prefix
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html - TransactWriteItems: 100 distinct items, 4 MB, no item twice
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html - 400 KB item cap
- https://www.postgresql.org/docs/current/storage-toast.html - TOAST: a history copy costs its compressed size
- https://www.postgresql.org/docs/current/ddl-temporal-tables.html - no system versioning in core PostgreSQL
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/RestoringPreviousVersions.html - restore copies the old version forward; the previous current version is kept
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeleteMarker.html - delete markers; undelete
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html - `NewerNoncurrentVersions` count retention (1–100)
- https://developers.google.com/drive/manage-revisions - Drive: 30 days or 100 revisions, `keepForever`
- https://docs.couchdb.org/en/stable/intro/api.html - `_rev` is not a history store
- https://www.figma.com/blog/realtime-editing-of-ordered-sequences/ - fractional indexing: id separate from position
- https://automerge.org/docs/reference/under-the-hood/merge-rules/ - per-insert unique element ids
