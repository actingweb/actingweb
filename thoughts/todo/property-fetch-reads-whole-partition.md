# `DbPropertyList.fetch()` reads the whole partition, `list:` rows included (I0)

**Origin:** I0 in `thoughts/research/2026-07-25-v3.13.0rc1-consumer-feedback.md`
— *"the most valuable thing in this document"*, measured in production, not
reasoned about. Triaged in `thoughts/research/2026-07-25-rc2-triage.md`
("Defer to 3.14") and re-listed as still-open in
`thoughts/research/2026-07-26-actor-deletion-triage.md` §"Not done".
**Status:** Open. Deliberately deferred from 3.13 as a hot-path rewrite on a
release that was already validated in production.

## What was measured

The 3.13 `Scan`→`Query` fix constrains only the **hash** key. Property-list
items share the actor's partition under range keys prefixed `list:`, so a query
for plain properties reads every one of them and discards them client-side.

Against the real production `AI_properties` table (16.7 MB, 43 actors), same
actor, same code path, only the library version changed:

| Actor's partition | 3.12.0 (`Scan`) | 3.13.0rc1 (`Query`) | Improvement |
| --- | --- | --- | --- |
| 86 rows (typical) | 1,872.5 RCU / 15 calls | **98.0 RCU / 1 call** | **≈19×** |
| 1,014 rows (list-heavy) | 1,872.5 RCU / 15 calls | **1,027.0 RCU / 9 calls** | ≈1.8× |

Both returned **5** plain properties. The heavy actor paid 1,027 RCU for 5 items
because ~1,009 `list:*` rows sit in the same partition.

## What 3.13 did and did not fix

It removed the **cross-actor** superlinearity — one actor's data no longer
inflates every other actor's reads, and cost is bounded by the caller's own
partition rather than total table size. That was the important part and it
holds. What remains is **within-actor** amplification proportional to that
actor's property-list volume, which for a list-heavy application (the reference
consumer stores user memory as property lists) is the dominant term.

## The ask

Constrain the range key too. `name` is the range key and list rows share the
`list:` prefix, so plain-property reads can exclude them in the key condition
instead of client-side:

- a `name < 'list:'` / `name > 'list:~'` **pair** of range-constrained queries —
  DynamoDB `Query` cannot `OR` on the sort key, which is why it is two, plus a
  PostgreSQL equivalent plus tests. That is the whole reason this was deferred.
- or, better, a deliberate key-prefix scheme (`prop#` / `list#`) so each access
  pattern is a single bounded range query. Larger; a storage-format change.

`fetch_all_including_lists()` legitimately wants the whole partition and must
keep today's behaviour.

Worth checking the equivalent **trust / peer-trustee** paths for the same shape
while in there.

**Decided 2026-08-14** (owner walkthrough): **re-measure against 3.13.0 GA
before designing anything.** The table above is an rc1 snapshot from one
consumer, and which fix shape is right — the two-query patch or the `prop#` /
`list#` key scheme — depends on how dominant the `list:` rows still are. Use the
acceptance recipe below to take the new measurement; it is the same instrument.

## Re-measured against 3.13.0 GA, 2026-08-20

The 2026-08-14 decision asked for this before any design work. Taken with
`ReturnConsumedCapacity` directly against production `AI_properties`
(eu-central-1, 2,739 rows / 18.6 MB), on the reference consumer's own actor:

| Query | rows | RCU |
| --- | --- | --- |
| the actor's **whole partition**, consistent | 1,190 | **254.0** |
| **one list's** range (`output_space`), consistent | 81 | **241.0** |

**The premise holds, and the design question has its answer: `list:` rows are
still overwhelmingly dominant.** ~95% of what a plain-property read costs for
this actor is one list's bytes. This is a *different* actor from the rc1
1,014-row one, so read it as a second data point of the same shape rather than
a like-for-like delta — the amplification survives GA either way.

The second row says something the rc1 table could not: **the byte weight is
concentrated in a few large rows, not spread evenly.** 81 wiki-document rows
cost 241 RCU (~11.9 KB each); the remaining ~1,109 rows in the partition cost
~13 RCU between them. Two consequences for the choice of fix:

- **Either fix solves this item.** Excluding `list:` rows takes the
  plain-property read from 254 RCU to ~13 either way, and the two-query patch
  is much the smaller change.
- **Only the prefix scheme helps the other list costs.** `prop#` / `list#`
  gives each *list* its own bounded range as a first-class key, which is what
  v2 rank storage already needs and currently re-derives from a `BETWEEN` on
  every single call. Given how concentrated the bytes are, that is where the
  remaining money is — see the consumer incident referenced below, where those
  per-list range reads, not this item's partition read, were the whole cost.

**Not the same defect as the 2026-08-19 consumer outage**, which is worth
stating because both are "list reads cost too much". That one was
`dynamodb-known-next.md` item 2: a query already bounded to a single list,
issued once per row. This item is a query not bounded at all, issued once.
Fixing I0 would not have prevented it and does not reduce its residual. See
"Consumer incident 2026-08-19" in that file.

## Acceptance

D7's operation-counter recipe in `docs/migration/v3.13.rst` ("Proving the fixes
actually landed") is the natural acceptance test — patch
`BaseClient._make_api_call` and count consumed capacity per call. The defect is
**invisible without per-call capacity instrumentation**, which is why it
survived the 3.13 validation pass.

## Related

- `thoughts/todo/dynamodb-known-next.md` — item 2 is the adjacent but distinct
  defect (per-**item** N+1 `GetItem`s when iterating one list); this item is the
  per-**partition** read amplification when fetching plain properties. Item 3's
  `consistent_read` audit touches the same call sites.
- `thoughts/todo/subs-list-cache-asymmetry.md` — the other item deferred to 3.14
  from the same triage; that todo already names this one as its sibling.
