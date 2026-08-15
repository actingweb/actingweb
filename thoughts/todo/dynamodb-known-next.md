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

**Line references are deliberately not re-pinned to specific numbers** for items
whose anchors are stable by name. Pinning them is what made this list go stale
in the first place: `29783f8`'s numbers were wrong within weeks. Where a number
appears above it is because the identifier alone is ambiguous.

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

## 3. consistent_read audit (~22 sites)
Strongly-consistent reads cost 2× RCU and exclude DAX. Candidates for
relaxation: bulk list fetches (`property.py` fetch/fetch_all, trust
list, attribute bucket list, subscriptions). NOT candidates: CAS paths
(`conditional_update_attr`), read-after-write within a request, the
post-lookup property load. Deferred because eventual consistency in
list reads is a behavioural change the test suite and some same-request
flows may depend on.

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
