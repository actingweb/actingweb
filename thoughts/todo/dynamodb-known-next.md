# DynamoDB scalability: known-next items

Deferred from `thoughts/plans/2026-07-23-dynamodb-scalability.md` — each needs
design work or carries behavioural risk disproportionate to a patch release.
The items below are what is left; the plan and
`thoughts/research/2026-08-20-v2-cost-in-library-callers.md` hold the
measurements and the reasoning for what has already been closed.

**Line references are deliberately not pinned to numbers** for items whose
anchors are stable by name. Pinning them is what made this list go stale in the
first place. Where a number appears it is because the identifier alone is
ambiguous.

## 1. Batched deletes for the remaining delete loops

`batch_delete()` exists on `DbPropertyProtocol` and `ListProperty.clear()` /
`delete()` use it. These still delete serially, one call per row:

- `DbTrustList.delete()`
- `attribute.py`: `delete_bucket`, `DbAttributeBucketList.delete`,
  `delete_by_chain`

`Actor.delete()` cascades through all of them, so actor deletion is where the
cost lands.

**Bulk *item* removal has the same shape and no primitive at all.** The handle
mutators (`remove_where`, `update_where`, `delete_by_handle`) are *k* point
writes, not one batch call, because `BatchWriteItem` cannot express conditions
and the mutators are compare-and-swap. Batching is only available where the
delete is unconditional — which is what `clear()`/`delete()` are and the handle
path is not.

## 2. `consistent_read` audit (~26 sites)

Strongly-consistent reads cost 2× RCU and exclude DAX. Candidates for
relaxation: bulk list fetches (property fetch/fetch_all, trust list, attribute
bucket list, subscriptions). **Not** candidates: CAS paths
(`conditional_update_attr`), read-after-write within a request, the post-lookup
property load. Deferred because eventual consistency in list reads is a
behavioural change the test suite and some same-request flows may depend on.

Remaining sites by module: `attribute.py` (8), `property_lookup.py` (4),
`subscription_diff.py` (4), `property.py` (3, excluding `get_range`),
`subscription.py` (3), `trust.py` (3), `actor.py` (1), `peertrustee.py` (1).

`get_range` is out of this list: it takes a per-call `consistent=` parameter,
split by call site — pure reads may relax, the rank cache feeding a positional
write may not, because a stale rank means touching the wrong row. **Apply the
same split to any site this audit relaxes.**

**Correct one comment while here.** `_v2_ensure_rank_cache` describes itself as
"one keys-only range query", which reads as a cheap probe. DynamoDB charges
capacity on the items *read*, before the projection is applied, so a keys-only
query over an 81-row list measured **241.0 RCU — identical to the full
projection**, and 120.5 eventually consistent. Keys-only buys network bytes and
no RCU.

## 3. `SubscriptionDiff` seqnr ordering / unbounded backlog read

`subscription_diff.py`'s `get()` without a seqnr queries the whole `subid:`
prefix and scans in memory for the lowest seqnr — the range key is a
lexicographic string (`"<subid>:<seqnr>"`, unpadded), so numeric order ≠ sort
order and `limit=1` cannot work. Fixing it needs a key-format change
(zero-padded seqnr or a numeric range key), which is a data migration for
existing diff rows. Until then a large diff backlog is re-read entirely on
every fetch.

## 4. `DbActorList.fetch` pagination

`actor.py`'s `DbActorList.fetch()` is an unpaginated full-table scan
materialised into a list, with an explicit "Admin/maintenance use only … do not
call it on a serving path" docstring.

**It is on a real operational path now:** both
`actingweb/maintenance/migrate_property_lists.py` and
`verify_property_lists.py` call `get_actor_list(config).fetch()` to enumerate
the fleet. Those are the operator tools that exist to make a migration safe to
run, and their input grows with the deployment. "Add a limit/cursor API before
anyone uses it at scale" is therefore "before the next fleet sweep on a large
table".

## 5. Import-time freezing of `Meta.table_name` / host

Every DynamoDB model binds `AWS_DB_PREFIX` / `AWS_DB_HOST` /
`AWS_DEFAULT_REGION` at class-definition time, and importing anything under
`actingweb.db.dynamodb` (the package `__init__` imports every model module)
freezes all of them. A consumer that configures env after import silently talks
to the wrong tables or endpoint — it bit the test harness during v3.13
development. Consider deferred resolution (resolve names at first connection,
or a `configure()` entry point that fails loudly on a late change).

## 6. Trust secret-uniqueness check is eventually consistent

`trust.py`'s `is_token_in_db` checks secret uniqueness via the `secret-index`
GSI, and GSIs cannot be strongly consistent, so a just-written duplicate secret
can be missed. Pre-existing; needs a conditional-write uniqueness scheme if it
matters.

## 7. Lookup-table write path amplification

`_update_lookup_entry` on a value change is an ownership-check GetItem plus a
delete plus a conditional put. Fine at current scale. A transactional
(`TransactWriteItems`) property+lookup write would also close the "property
saved, lookup write failed" inconsistency window that today is only logged
(`LOOKUP_TABLE_SYNC_FAILED` / `LOOKUP_CREATE_FAILED`).

## Related

- `thoughts/todo/subs-list-cache-asymmetry.md` — the subscription-list memo
  costs one strongly-consistent Query per property write for actors with no
  subscribers. Its fetch is also one of item 2's relaxation candidates.
