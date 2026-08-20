# DynamoDB scalability: known-next items (deferred from v3.13)

**Created:** 2026-07-23. Source: the plan-evaluation pass for
`thoughts/plans/2026-07-23-dynamodb-scalability.md` (scalability
evaluator findings, verified against the code at the time). These were
deliberately deferred — each needs design work or carries behavioural
risk disproportionate to the v3.13 release. Line references were from commit
`29783f8` and were already wrong by the time anyone looked; **see the
re-verification below, which is current as of 2026-08-15.**

**Decided 2026-08-14** (owner walkthrough): fold that re-verification into the
**3.13.0 GA** work — walk all nine items against the settled codebase and
refresh the line references then, rather than per-item at pick-up time.

## Re-verified 2026-08-15 against `6187636`

All nine walked against the GA codebase, after the last of the GA branches
landed, so "the settled codebase" is true rather than aspirational. **All nine
still stand and none has been silently fixed.** One (item 3) is measurably
larger than the original note said. What changed is confidence in the list
rather than its contents — which is the outcome the re-verification was for, not
a disappointing one. Specifics:

- **Item 1 stands, and got slightly worse** (see its own note below).
  `batch_write` / `BatchWriteItem` still appear nowhere in the package.
- **Item 2 half stands, and the half that is gone matters.** The per-item N+1
  is unchanged: `ListProperty.__getitem__` still does a fresh accessor plus a
  `GetItem` per item, on both formats. **The `__delitem__` O(N) shift is gone
  for v2 lists.** `_v2_delitem()` deletes exactly one ranked row and then says
  so in the code — *"a single row delete IS the whole operation under v2 — no
  shift loop"*. So the shift cost survives only on legacy v1 lists, which the
  migration tools exist to retire.

  This correction matters more than a tally: the original item proposes
  "tombstones or stable item ids instead of positional `list:<name>-<i>`" as
  the fix, and **that is what fractional rank keys already are.** Reading the
  item as written would send someone to redesign a key layout that shipped in
  3.13. What remains for item 2 is the item cache with staleness semantics,
  and nothing else. Caught by Codex review on PR #131.
- **Item 3's count is now 27, not ~22**, across eight `db/dynamodb` modules
  (`attribute.py` 8, `property_lookup.py` 4, `subscription_diff.py` 4,
  `property.py` 3, `subscription.py` 3, `trust.py` 3, `actor.py` 1,
  `peertrustee.py` 1). The growth is from work that legitimately needed strong
  reads, so the audit's shape is unchanged — but anyone scoping it should
  budget for a quarter more sites than the original note implied.
- **Item 4 stands.** `subscription_diff.get()` still takes an optional `seqnr`
  and still scans the `subid:` prefix in memory; the range key is still an
  unpadded lexicographic string.
- **Item 5 stands and its premise has expired.** The entry says "no in-library
  callers (public API only)". That is **no longer true**: both
  `actingweb/maintenance/migrate_property_lists.py` and
  `actingweb/maintenance/verify_property_lists.py` call
  `get_actor_list(config).fetch()` to enumerate the fleet. Those are the two
  operator tools GA exists to make safe to run, so the unpaginated full-table
  scan is now on a real operational path, not a hypothetical one — and it is
  the path whose input size grows with the deployment. The `fetch()` docstring
  does carry an explicit "Admin/maintenance use only … deliberate full-table
  Scan, O(table size) and unpaginated — do not call it on a serving path"
  warning, which the maintenance callers honour; a sweep is not a serving path.
  But "add a limit/cursor API before anyone uses it at scale" has quietly
  become "before the next fleet sweep on a large table". Caught by Codex review
  on PR #131.
- **Item 6 stands, unchanged.** `table_name = os.getenv("AWS_DB_PREFIX", …)`
  is still evaluated in each model's `class Meta` body at import time.
- **Item 7 stands.** `is_token_in_db` is still the GSI-based uniqueness check.
- **Item 8 stands.** Both backends still do the read-then-write lookup update
  (`property.py`); PostgreSQL has since gained an in-transaction variant
  (`_update_lookup_entry_in_transaction`), which narrows the window on that
  backend only and leaves DynamoDB's exactly as described.
- **Item 9 stands at both call sites, and "only the cost half is open" would
  be wrong.** `if not self.subs_list` remains at `actor.py:1351` (the
  trust-deletion sibling, item 3 of the linked todo) and `actor.py:1620`
  (`get_subscriptions()`). The invalidation fix is present and visible —
  `self.subs_list = None` at three sites — but it only refreshes the `Actor`
  instance the create or delete happened on. A **different process** can still
  hold a truthy stale `subs_list`, and the trust-deletion site then skips the
  fetch and can leave a subscription created elsewhere undeleted. So a
  correctness residue survives alongside the cost one, exactly as item 3 of
  `thoughts/todo/subs-list-cache-asymmetry.md` records. Item 4 of that file was
  half-answered on 2026-08-15 (see it); the guard stays blocked. Caught by
  Codex review on PR #131.

**#132 (the v3.13.0 tag) postdates this pass** and affects no item: it added a
repair refusal and a stale-format warning to `property_list.py` /
`verify_property_lists.py`, no new delete loop or read path.

**Line references are deliberately not re-pinned to specific numbers** for items
whose anchors are stable by name. Pinning them is what made this list go stale
in the first place: `29783f8`'s numbers were wrong within weeks. Where a number
appears above it is because the identifier alone is ambiguous.

## Consumer incident 2026-08-19 — item 2, in production

The reference consumer (`actingweb_mcp`) took a user-visible outage on the read
half of item 2, three days after the v2 migration retired its write half.
Deleting a batch of ten items from a property list ran **40.7 s** and was cut
off by the API gateway's 30 s integration ceiling, which the client saw as a
500. The server finished the deletions anyway, so the rows were gone while the
UI restored them and abandoned the rest of the batch. DynamoDB consumed
**464,147 RCU in one minute** against a ~5,000/min baseline — ~1.19M for ~67
deletions, about 18,000 RCU per deleted item.

The shape is item 2 exactly: the consumer's accessor located each item with a
positional loop over the list, and under v2 each of those positional reads is a
whole-list Query (see the corrections on item 2 below). *k* deletions over an
*n*-row list cost *k·n* whole-list reads. Fixed consumer-side by switching that
loop to `to_indexed_list()` — a 10-id batch over a 300-row list went from
**5,930 reads to 30**, measured against a real `ListProperty` in v2 mode.

**Three things this says about the library, none of which the consumer fix
addresses:**

1. **The v1→v2 migration was a cost regression on this path, not just a
   correctness win.** The same 10-id delete took **4.5 s under v1** (logged
   2026-08-09, in the incident that motivated the migration) and **40.7 s under
   v2**. v2 removed the O(N) shift and replaced a per-item point read with a
   per-item whole-list Query. Nothing in the migration's validation would have
   caught that — it is invisible without per-call capacity instrumentation,
   the same blind spot I0 records.
2. **The residual is still O(k) whole-list reads.** Post-fix, each delete is
   one Query for the lookup plus one forced rank reload inside `_v2_delitem`,
   so a 10-id batch is ~20 whole-list reads. Fine at hundreds of rows; it is
   the next wall. **A `remove_where(key, value)` / stable-id delete primitive
   would remove it** — and would also remove the reason a consumer writes a
   positional loop at all, which is the same reason that produced the
   neighbour-destroying index skew on 2026-07-19. One primitive closes a cost
   defect and a corruption class together. That looks like the strongest
   candidate to come out of this.
3. **Item 1's batching applies here too.** The item scopes `batch_write` to
   `clear()`/`delete()`; bulk *item* removal has the same shape and no
   primitive at all.

## 1. batch_write for delete loops
`batch_write`/`BatchWriteItem` is used nowhere. Item-by-item serial
delete loops: `DbPropertyList.delete()`, `DbTrustList.delete()`,
`attribute.py` `delete_bucket`/`DbAttributeBucketList.delete`/
`delete_by_chain`, and worst `ListProperty.clear()/delete()` (per item:
fresh accessor + GetItem + DeleteItem — a 1000-item list delete is 1000
serial round-trip pairs). `Actor.delete()` cascades through all of them.
Needs 25-item chunking + unprocessed-item retry; lookup-row cleanup and
property hooks stay per-item, so batching covers only the raw deletes.

**Got slightly worse on 2026-08-15** (`thoughts/plans/2026-08-15-property-list-metadata-integrity.md`,
Phase 2): `ListProperty.clear()` and `delete()` now also call
`sweep_foreign_format_rows()`, which adds one meta-row read plus one
keys-only range read, and then deletes any rows found serially like
everything else here. Necessary — a cleared or deleted list has to be
empty in *both* storage namespaces, or an interrupted migration's residue
gets adopted by the next list created under the same name — but it is one
more serial delete loop for a `batch_write` fix to cover, not one fewer.
Separately, every list *mutation* now costs one extra point read
(`_save_metadata()` merges into a fresh read of the meta row), which is
adjacent to item 2's N+1 and belongs in the same measurement.

**Adjacent, filed separately:** `DbPropertyList.fetch()` reading the whole
partition (`list:` rows included) is I0, and lives in
`thoughts/todo/property-fetch-reads-whole-partition.md`. It is the per-*partition*
read amplification; item 2 below is the per-*item* N+1. Item 3 touches both.

## 2. General ListProperty item N+1 and __delitem__ O(N) shift
`ListProperty.__getitem__` does a fresh accessor + GetItem per item
(iteration = N serial GetItems); `__delitem__` shifts every subsequent
item down with ~3 round trips each. v3.13 fixed the handler-level cases
(bulk-read serving) — the general fix needs an instance-level item cache
with staleness semantics, and `__delitem__` needs a key-layout redesign
(tombstones or stable item ids instead of positional `list:<name>-<i>`).

**Corrected 2026-08-20 — under v2 this is quadratic, not N+1, and the
remedy above cannot be reached.** See "Consumer incident" below. Three
corrections, in order of how much they change the item:

1. **`__getitem__` under v2 is not "a GetItem".** `_v2_getitem` calls
   `_v2_ensure_rank_cache(force=True)` before every read — a **full-range
   Query over the whole list** — and then the GetItem. So a positional walk
   of an *n*-row list is *n* whole-list Queries, and its cost scales with the
   list's **bytes**, not its length. The forced reload is deliberate and
   correct (a cached rank still exists after another writer inserts earlier,
   so a stale read returns the item that *used* to be at that position); it is
   the cost that was not costed. It shipped with the v2 format in rc5 (#121),
   so it predates the 2026-08-15 re-verification — that pass's "still does a
   fresh accessor plus a `GetItem` per item, on both formats" was already
   understating v2 when written.
2. **An instance-level item cache cannot help a consumer, and caching the
   instance is worse than it looks.** `PropertyListStore.__getattr__`
   constructs a **fresh `ListProperty` on every attribute access**, so
   `_v2_rank_cache` and `_meta_cache` never survive from one
   `actor.property_lists.foo` to the next.

   **Corrected 2026-08-20 — the obvious remedy is unsafe.** Caching the list
   objects per store (which `attribute_list_store.py:87-93` does) splits the
   wrong way: `ActorInterface.property_lists` memoizes the store
   (`interface/actor_interface.py:304-316`) and `handlers/mcp.py:52` caches the
   `ActorInterface` under a **5-minute TTL renewed on every access**, so for an
   active actor the store can outlive many requests. The positional paths force
   a rank reload regardless and gain nothing; `len()` / `to_list()` / `append()`
   have no forced refresh and would read a rank cache minutes stale, in a later
   request. `ListAttribute` is exempt only because it has no rank cache. Full
   analysis in
   [`thoughts/research/2026-08-20-v2-positional-access-cost.md`](../research/2026-08-20-v2-positional-access-cost.md)
   option E. A fix has to live in the key layout, in a bulk primitive, or in a
   *request-scoped* handle lifetime; not in a long-lived instance.
3. **The exposure is narrower than "iteration", and that is the useful part.**
   `__iter__` already dispatches to `_v2_to_list()` under v2 — one range query
   — and its docstring names this exact hazard: *"per-item `__getitem__` calls
   in a loop would cost one query per item, which the range-read design exists
   specifically to avoid."* `to_list()`, `slice()` and `to_indexed_list()` are
   all one query too. So the defect is reachable **only** through an explicit
   positional loop (`for i in range(len(lst)): lst[i]`), which is precisely
   what the reference consumer's accessor did. The library defended the
   idiomatic path and left the positional one undefended and unmarked.

What follows from 3 is that this may be cheaper to close than the item
implies: a docstring on `__getitem__` naming the v2 cost, or a debug-level
warning when a single `ListProperty` instance forces the rank cache more than
once, would have surfaced it. A `remove_where(key, value)` primitive would
remove the reason consumers write the loop at all — see the incident note.

**Superseded 2026-08-20 by the general form.** `remove_where` is a special case
of exposing the rank as an opaque handle: v2 already *has* stable per-item
identity, and the public API hides it, so every mutation re-derives a fragile
handle (a position) from a stable one — and re-derivation is the whole-list
read. See the research above, option A. Two constraints it establishes and this
item did not know: `BatchWriteItem` cannot express conditions, and a rank is
unique only within a **list generation** (after `delete()` + `append()` the
first rank is `a0` again — `property_list.py:2343-2352`), so any handle must be
mutated conditional on the bytes read.

## 3. consistent_read audit (~22 sites)
Strongly-consistent reads cost 2× RCU and exclude DAX. Candidates for
relaxation: bulk list fetches (`property.py` fetch/fetch_all, trust
list, attribute bucket list, subscriptions). NOT candidates: CAS paths
(`conditional_update_attr`), read-after-write within a request, the
post-lookup property load. Deferred because eventual consistency in
list reads is a behavioural change the test suite and some same-request
flows may depend on.

**Added 2026-08-20: `db/dynamodb/property.py::get_range` is a site, and it did
not exist when this item was written.** It is `consistent_read=True` and it is
now the single hottest read in v2 list storage — every `to_list()`, `slice()`,
`__iter__`, `to_indexed_list()` and every forced rank-cache reload goes through
it. Measured against production (`ReturnConsumedCapacity`, an 81-row list in a
1,190-row partition):

| Query | rows | RCU |
| --- | --- | --- |
| the list's range, full projection, consistent | 81 | **241.0** |
| the list's range, **keys-only**, consistent | 81 | **241.0** |
| the list's range, keys-only, **eventually** consistent | 81 | **120.5** |

Two results there, and the second is not about this item:

- The 2× is exactly as described. Relaxing `get_range` alone roughly halves the
  read cost of every v2 list operation in the library.
- **`keys_only=True` buys nothing.** DynamoDB charges capacity on the items
  *read*, before the projection is applied, so `attributes_to_get=["name"]`
  saves network bytes and no RCU. `_v2_ensure_rank_cache` is written as *"one
  keys-only range query"*, which reads as a cheap probe and is in fact a full
  read of the list priced at the list's whole byte size. Worth correcting in
  the comment whatever happens to this item — it is the sentence that makes
  item 2's forced reload look affordable.

**Split by call site, not by function.** `get_range` serves both pure reads
(listing, search, `to_list`) where eventual consistency is fine, and the rank
cache feeding a *positional write* (`_v2_getitem`/`_v2_setitem`/`_v2_delitem`),
where a stale rank means touching the wrong row — the very failure the
`force=True` exists to prevent. The first is a candidate; the second is a CAS
path in all but name and belongs in this item's "NOT candidates" list.

## 4. SubscriptionDiff seqnr ordering / unbounded backlog read
`subscription_diff.py` `get()` without seqnr queries the whole
`subid:` prefix and scans in memory for the lowest seqnr — the range key
is a lexicographic string (`"<subid>:<seqnr>"`, unpadded), so numeric
order ≠ sort order and `limit=1` cannot work. Fixing needs a key-format
change (zero-padded seqnr or numeric range key) = data migration for
existing diff rows. A large diff backlog is re-read entirely on every
fetch until then.

## 5. DbActorList.fetch pagination
`actor.py` `DbActorList.fetch()` is an unpaginated full-table scan
materialised into a list. No in-library callers (public API only, docs
note added in v3.13) — add a limit/cursor API before anyone uses it at
scale.

## 6. Import-time freezing of Meta.table_name / host
Every DynamoDB model binds `AWS_DB_PREFIX` / `AWS_DB_HOST` /
`AWS_DEFAULT_REGION` at class-definition time, and importing ANYTHING
under `actingweb.db.dynamodb` (the package `__init__` imports every
model module) freezes all of them. Consumers that configure env after
import silently talk to the wrong tables/endpoint (bit the test harness
during v3.13 development). Consider deferred resolution (resolve names
at first connection, or a `configure()` entry point that fails loudly on
late changes).

## 7. Trust secret-uniqueness check is eventually consistent
`trust.py` `is_token_in_db` checks secret uniqueness via the
`secret-index` GSI (GSIs cannot be strongly consistent), so a
just-written duplicate secret can be missed. Pre-existing; needs a
conditional-write uniqueness scheme if it matters.

## 8. Lookup-table write path amplification
`_update_lookup_entry` on a value change = ownership-check GetItem +
delete + conditional put. Fine at current scale; a transactional
(TransactWriteItems) property+lookup write would also close the
"property saved, lookup write failed" inconsistency window that today
is only logged (LOOKUP_TABLE_SYNC_FAILED / LOOKUP_CREATE_FAILED).

## 9. `Actor.subs_list` cache asymmetry (added 2026-07-26, post-3.13.0)
`get_subscriptions()` guards its memo on truthiness (`if not
self.subs_list`), so the cache never sticks for actors with **zero**
subscriptions — `register_diffs()` runs per property write, so that is
one strongly-consistent `Query` per write to learn there is nobody to
notify. Conversely, for actors that *do* have subscriptions the cache
sticks and `create_subscription()` never invalidates it, so a
subscription created mid-instance is invisible to `register_diffs()`
(the protocol handler patches this by hand at one call site; two
interface paths do not). The two defects mask each other, and fixing the
cheap one first makes the correctness one worse — invalidation must land
before the guard change. Overlaps item 3: the subscription list fetch is
one of the `consistent_read=True` relaxation candidates. Full analysis,
affected call sites and proposed ordering:
`thoughts/todo/subs-list-cache-asymmetry.md`.
