# A `prop#`/`list#` key-prefix scheme for the property partition (next major release)

**Created:** 2026-08-21 (v3.14 development)
**Trigger:** the next major version bump

Filed from the "Scalability" evaluation notes in
`thoughts/plans/2026-08-20-v2-positional-access-cost.md`: "the 1 MB Query
ceiling is close... the ceiling itself belongs to the `prop#`/`list#` scheme
filed for the next major."

## The problem this doesn't fix, and why it's next-major rather than now

Plain properties and every list's rows (`list:<name>-<rank>`) share one
DynamoDB partition, keyed on `actor_id`. 3.14's Phase 4
(`property-fetch-reads-whole-partition`, now closed) stopped plain-property
reads from paying for the list rows sharing that partition by using a
range-constrained query instead of a client-side filter — but the rows are
still in the **same partition**, so an actor with enough list data still
approaches DynamoDB's per-partition 1 MB Query response ceiling. The
consumer's largest list measured at 964 KB in one page — 94% of the limit.
Past it, `get_range` correctly follows `LastEvaluatedKey` into N sequential
queries, and N then multiplies against anything per-item — which is exactly
what 3.14's Phases 7–11 worked to remove the multiplier on, not to raise the
ceiling itself.

A `prop#<name>` / `list#<name>` (or similar) key-prefix split — giving list
storage its own partition space, separate from plain properties, possibly
per-list rather than per-actor — would raise or remove the ceiling instead of
just amortizing what's under it. That's a storage-key-layout change: every
row this library has ever written uses the current scheme, so it needs a
migration path (mirroring the v1→v2 `format` migration's shape: dual-read
during a transition, `migrate_to_v2()`-style explicit per-list conversion,
`verify_property_lists.py`-style sweep for stragglers) rather than a patch.
That's why it waits for a major version.

## Scope, roughly

1. Design the new key scheme itself — decide whether list rows move to a
   fully separate DynamoDB partition key (not just a range-key prefix under
   the same partition, which doesn't move the 1 MB ceiling) or a separate
   table entirely; the two have different migration and cost tradeoffs.
2. A migration primitive analogous to `migrate_to_v2()`/`downgrade_to_v1()`,
   with the same crash-recovery discipline that migration needed (see
   `thoughts/todo/whole-list-rewrite-atomicity.md` for what "changing where a
   list's rows live" gets wrong if done without one).
3. PostgreSQL needs the equivalent analysis — its per-row-count characteristics
   differ from DynamoDB's per-partition byte ceiling, so the case for moving
   PostgreSQL's `properties` table layout at all should be argued
   independently rather than assumed to follow DynamoDB's reasoning.
4. Sequence after `thoughts/todo/legacy-property-gsi-removal.md` (row 12) —
   both are next-major, both touch property storage layout, and doing the
   legacy-GSI removal first means the new scheme is designed against the
   *final* lookup-table-only shape rather than one that still has to carry
   the legacy fallback tiers.

## A second motivation: out-of-band per-item payload (added 2026-08-29)

Filed from `thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md`,
which measured a consumer's partition and found **66.3% of it is embedding
payload no page renders**.

Most of that is already answerable without a key change. Of the 66.3%, the
`output_embeddings_*` sidecar is 49.8%, and a *scoped* bulk read simply
excludes it — that is `thoughts/todo/scoped-bulk-list-reads.md` item A, which
is a 3.14.x patch and needs nothing from this scheme.

What survives is the other **16.7%: vectors stored inside `memory_*` item
bodies** (90.6% of all `memory_*` bytes are vector). No range read can reach
that, because those bytes are inside rows the page *does* render — you cannot
exclude part of a row.

And a consumer-side sidecar does not fix it either. That experiment has already
been run: outputs moved their vectors out of item bodies into
`output_embeddings_*`, and those rows landed in the **same partition**, which is
why they still cost 678 RCU on every whole-partition dump. **Relocating bytes
within a partition does not reduce what a partition read costs.** That is the
same insight as this file's 1 MB-ceiling argument, arriving from the cost side
rather than the limit side.

So the scheme has a second requirement beyond raising the ceiling: **a way for a
list to carry large per-item payload out of band**, so bulk and range reads over
the item bodies do not pay for it. Whether that is a separate partition per
list, a payload-carrying row class excluded from bulk reads by key shape, or a
separate table, is exactly the §1 design decision above — this adds a
constraint it has to satisfy, not a new mechanism.

Worth noting for sequencing: the consumer's need is real now but not blocked on
this. Scoped bulk reads take it from 1,361 RCU to 686 in a patch release; this
scheme is what would take the remaining ~17% off, and it can wait for the major
bump as planned.
