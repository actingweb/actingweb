# Investigation: an owner's unvouched actor left behind a new one, and the sibling sweep reading faults as absence

**Date:** 2026-10-28
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the fix is uncommitted in the working tree with the rest of the 3.16 work)
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## Symptom

From `thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-5.md`:

- **AN** (the code review and this session's reading): an owner whose actor
  predates 3.16 and is not yet backfilled has a squatter's factory actor
  beside it. If the factory actor has the lower id, the owner signs into a
  new, empty actor, and from then on never reaches their own.
- **AO** (outside voice): resuming the backfill from its printed hint skips
  one actor.
- **AP** (outside voice and the code review): under a read fault the sweep
  keeps a factory sibling. Also, a marker read that fails closed leaves the
  owner with no actor at all.
- **AR-AU** (the reviews): smaller variants of the same theme, a value read
  or written without confirming it.

## Root Cause

- **AN:** `get_from_creator` ordered candidates only by "vouched first",
  then lowest id, so among unvouched actors a `factory` one could win. The
  replace path's successor step reused a remaining actor only if it was
  vouched, so the owner's unvouched actor was skipped and a new one created
  (`oauth2.py`, the successor block). After that the new vouched actor won
  every lookup.
- **AO:** the `progress:` line was printed at the top of the loop body,
  before the actor was read and marked (`mark_actors_vouched.py`).
- **AP:**
  - PostgreSQL's `get_by_creator` answers a fault with None.
  - Both backends' `get` answer a fault with None, and DynamoDB's
    `get_by_creator` keeps a failed per-row read as a None entry.
  - `_factory_siblings` read all three as "no sibling" or "deleted since
    listed".
  - It also ran after the victim had been removed.
- **AT:** the vouched branch of `_adopt_actor` returned before the tombstone
  was read. `Actor.delete` wipes `_internal` second to last, so a stalled
  DELETE still reads as vouched.

## Hypotheses Rejected

- **"Sweep factory siblings on a clean too"** (the first draft of AN's test
  expected it). Rejected: the owner's rule removes siblings only on a
  replacement. The factory actor beside a cleaned, now vouched owner is
  inert, because no lookup reaches it.
- **Printing the hint in a `finally`** (the first draft of AO's fix). A
  `finally` also runs on KeyboardInterrupt, which recreates the bug.

## Fix

- **AN:**
  - `actor.py`: `_candidate_rank` orders vouched, then other unvouched or
    unreadable, then `factory`.
  - `oauth2.py`: the successor step cleans a remaining non-factory
    unvouched actor in place, and hands a tombstoned vouched one back
    through `_adopt_actor`.
- **AO:** `mark_actors_vouched.py`: the per-actor body is `_mark_one`, and
  the line is printed after it returns.
- **AP:** `oauth2.py`:
  - `_factory_siblings` is called before any removal;
  - an empty list, a None row, or an id that does not load without a
    tombstone returns None;
  - `_still_factory` re-reads each marker just before its delete.
- **AS:** the clean also resets `trustee_root`; every reset goes through
  `set_confirmed`, the primitive the marker already uses.
- **AT:** `_adopt_actor` reads the tombstone before the vouched return.
- **AU:** `Actor.create` unbinds `id`, `handle` and `store` before returning
  False.
- **AR:** `handlers/mcp.py` loads the winner of a create race.

## Evidence

Each regression test in `tests/test_adoption_fifth_iteration.py` fails with
its source file restored from the pre-iteration backup, and passes with the
fix:

- `TestOwnersActorBesideFactoryOnes::test_sign_in_cleans_the_owners_actor_not_a_lower_factory_one`:
  two sign-ins both return the owner's id, and the owner's property is
  kept.
- `…::test_replacing_a_factory_actor_cleans_the_owners_instead_of_creating`:
  `adopt_actor` on the factory actor returns the owner's id, marked
  `google_oauth2`.
- `TestBackfillResumeHint`: after a KeyboardInterrupt on the second actor,
  the log names only the first as the resume point.
- `TestSweepReadFaults`, 4 tests:
  - a None list leaves the victim in place;
  - an unreadable listed row leaves both actors in place;
  - a sibling vouched since the listing is kept;
  - `removed_sibling_ids` names the swept sibling.
- `TestCleanLeavesNothingOfThePreviousCreator`, 2 tests: `trustee_root` is
  None after a clean, and an unconfirmed token reset leaves the marker
  unset.
- `TestVouchedActorMidDeletion`: a tombstoned vouched actor yields a new id,
  and the old row is gone.
- `TestRefusedCreateUnbinds`: `id`, `handle` and `store` are None, and
  `delete()` is False.
- `TestMcpBridgeCreateRace`: the loser returns the existing actor.
- `TestCreatorPinOnTheConsumerPath`: the interface refuses a pinned change.

Fast tier: 3051 passed, 23 skipped. Full tier: see the plan's Iterations
batch.

Scope lock: self-check. The fix touches:
- `actor.py`, `oauth2.py`;
- `maintenance/mark_actors_vouched.py`, `handlers/mcp.py`,
  `handlers/trust.py`, `oauth2_server/system_actor.py`;
- the docstring in `interface/actor_interface.py` and the comment in
  `interface/integrations/flask_integration.py`;
- `tests/`, `CHANGELOG.rst`, and in `docs/`: `migration/v3.16.rst`,
  `reference/hooks-reference.rst` and `guides/authentication.rst`.

That is more than five files, because the issues are separate; the owner
asked for all of them.

## Decisions

- **Release:** inside the 3.16 (major) release. These items add the
  `actor_adopted` kwarg `removed_sibling_ids`, the public method
  `Actor.creator_change_pinned`, and the pin on the consumer path of
  `modify_creator(unvouch=True)`, none of which has shipped yet.
- **One more read per sign-in:** the vouched path now reads the tombstone.
  That is one point read, accepted in exchange for not handing a sign-in an
  actor that is mid-deletion.

## Related

- `thoughts/research/2026-10-27-sibling-squats-and-create-on-taken-id.md`:
  the sibling rule these items complete.
- `thoughts/todo/creator-uniqueness-not-enforced.md`: still the root cause
  behind siblings.
- `thoughts/todo/adoption-fault-and-hygiene-followups.md`.

## Status

DONE
