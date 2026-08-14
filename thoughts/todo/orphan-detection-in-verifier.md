# Orphan-row detection in the offline verifier (DEL5)

**Origin:** DEL5 in
`thoughts/research/2026-07-26-actor-deletion-semantics-and-orphan-writes.md`;
deferred in `thoughts/research/2026-07-26-actor-deletion-triage.md` (DEL1–DEL4
landed in v3.13.0rc2, DEL5 did not) and listed there under "Not done".
**Severity:** Low, purely additive. Nothing is broken; this is a tool that does
not exist.

## What it is

`python -m actingweb.db.verify_tables` already exists and runs offline with the
operator's own credentials. An orphan-row check is its natural companion:
enumerate actor ids, then report attribute / property / trust rows whose
`actor_id` is absent.

Every consumer that has ever had a DEL1/DEL3 incident needs this, and each will
otherwise write their own scan — the reference consumer already did.

**Decided 2026-08-14** (owner walkthrough): **ship it in `verify_tables`**
rather than leaving each consumer to write their own. The reasoning is below —
the classification is not obvious, and getting it wrong deletes live data.

## Why it is worth lifting rather than leaving to consumers

The classification has four edge cases that are **not obvious**, and getting any
of them wrong deletes live data:

1. **An empty actor set must yield zero orphans.** If the actor-table read fails
   or returns nothing, "every row is orphaned" is the catastrophic reading.
2. **System actors must be excluded unconditionally.** The reference consumer
   has `_actingweb_websocket` holding live registry data under an id
   deliberately absent from the actors table; `_actingweb_oauth2` and
   `_actingweb_system` exist as real actors. Any reserved-prefix id should be
   reported **separately**, never as deletable.
3. **Reads must be consistent.** An eventually-consistent scan can show a
   seconds-old actor as absent.
4. **Keep it out of automated jobs.** Today's ordering is what makes
   classification safe: `Actor.create()` writes the actor row **first** and
   `Actor.delete()` removes it **last**, so an actor mid-create or mid-delete
   always still has its row. If that ordering ever changes (it was proposed as
   DEL1 preference #2 and **rejected**, deliberately), a mid-deletion actor's
   rows briefly classify as orphaned. Fine for a tool an operator runs on
   purpose; not fine on a cron.

Those four are already written into `docs/reference/actor-deletion.rst`
§"Finding orphaned rows" — they were documented precisely so they would not be
lost when the code was deferred. **Start there, not from scratch.**

## Related

- `thoughts/research/2026-07-26-actor-deletion-triage.md` — DEL1 (tombstone),
  DEL2, DEL3, DEL4 all landed in rc2; the "discriminating question" section
  records why the actor row still goes last, which is edge case 4's premise.
