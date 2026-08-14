# DynamoDB scalability: known-next items (deferred from v3.13)

**Created:** 2026-07-23. Source: the plan-evaluation pass for
`thoughts/plans/2026-07-23-dynamodb-scalability.md` (scalability
evaluator findings, verified against the code at the time). These were
deliberately deferred — each needs design work or carries behavioural
risk disproportionate to the v3.13 release. Line references are from
commit `29783f8`; re-verify before implementing.

**Decided 2026-08-14** (owner walkthrough): fold that re-verification into the
**3.13.0 GA** work — walk all nine items against the settled codebase and
refresh the line references then, rather than per-item at pick-up time.

## 1. batch_write for delete loops
`batch_write`/`BatchWriteItem` is used nowhere. Item-by-item serial
delete loops: `DbPropertyList.delete()`, `DbTrustList.delete()`,
`attribute.py` `delete_bucket`/`DbAttributeBucketList.delete`/
`delete_by_chain`, and worst `ListProperty.clear()/delete()` (per item:
fresh accessor + GetItem + DeleteItem — a 1000-item list delete is 1000
serial round-trip pairs). `Actor.delete()` cascades through all of them.
Needs 25-item chunking + unprocessed-item retry; lookup-row cleanup and
property hooks stay per-item, so batching covers only the raw deletes.

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
