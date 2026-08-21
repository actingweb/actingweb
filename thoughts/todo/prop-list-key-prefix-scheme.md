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
