# Reverse-lookup: stale owners, a stale-handle race, one bad value

Found by the Phase 1 outside-voice review of
`thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md`; not fixed in
3.16.0 because each needs a design of its own.

1. **A lookup row held by an actor that no longer has the value is a
   "collision" forever.** `DbPropertyLookup.delete` and `_delete_lookup_entry`
   are best-effort, so a throttled delete leaves a stale row. The next actor to
   set that value is written unindexed (`LOOKUP_COLLISION`), cannot sign in by
   it, and `actingweb-property-lookup backfill` reports the same collision and
   never marks the name. Fix: on a conflict read the owner's property row and,
   when it no longer holds the value, take the row over with a conditional
   overwrite (backfill and the runtime path both).
2. **A stale-handle race on the same actor and name** (two concurrent `set()`
   calls both read `old_value=x`) leaves the lookup row of the losing value.
   `_write_indexed` checks only the lookup owner. Fix: condition the property
   put on the value read, or compare the stored value on reverse lookup.
3. **PostgreSQL backfill: one over-long value aborts the pass.** A value over
   about 2.7 KB breaks the btree row limit on `property_lookup`; the pass faults
   at the same batch on every run. Fix: catch per batch, report the actor and
   name, skip the row.
