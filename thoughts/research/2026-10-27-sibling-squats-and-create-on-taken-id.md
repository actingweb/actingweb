# Investigation: sibling factory actors split a sign-in, and `Actor.create` reported a create that did not happen

**Date:** 2026-10-27
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the fix is uncommitted in the working tree with the rest of the 3.16 work)
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## Symptom

From `thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-4.md`,
Issues Y and AB, found by `/code-review high`:

- **Y:** the factory is open and `unique_creator` is off by default, so
  several `POST /` with one victim's address created F1, F2 and F3. Each
  victim sign-in replaced one of them and created a new actor, so the
  victim's sessions and data spread over V1, V2 and later actors.
- **AB:** on the replace path, a successor whose INSERT failed (a caught
  PostgreSQL fault) was returned as an actor. The callback then issued
  tokens for an id with no row.

## Root Cause

- **Y:** `Actor.get_from_creator` picks the lowest id among duplicates
  (`actor.py`, `candidates.sort(...)`). The replace path removed only the
  actor the lookup returned. Its successor check then landed on the next
  factory sibling, which is unvouched, so it created another actor.
- **AB:** `Actor.create` returned True whatever `self.handle.create()`
  answered. With the id taken or the insert failed, `created` is False,
  but the function went on to write `trustee_root` into that id's bucket,
  fire `actor_created`, and return True.

## Hypotheses Rejected

- **"Delete every unvouched sibling" (the literal reading of the owner's
  first answer).** Rejected with the owner. Actors created before 3.16
  without a provider sign-in are unvouched too, and may be a legitimate
  creator's duplicates that hold data.

## Fix

- **Y:**
  - `actor.py`: `get_from_creator` orders vouched candidates first.
  - `oauth2.py`: the replace path removes every `factory` sibling
    (`_factory_siblings`, `_remove_for_replacement`) before it picks or
    creates the successor.
- **AB:** `actor.py` `create` returns False when `created` is False. The
  marker is written before `trustee_root`, so a rollback removes only the
  row. The system actors load the winner when they lose the creation race.

## Evidence

Regression tests in `tests/test_adoption_fourth_iteration.py`. Each failed
with its fix disabled and passes with it:

- `TestFactorySiblings::test_one_sign_in_replaces_every_factory_sibling`:
  two sign-ins return the same id, and only that actor remains for the
  creator.
- `TestFactorySiblings::test_lookup_prefers_a_vouched_actor_over_a_lower_unvouched_one`.
- `TestCreateOnATakenId`, three tests: False with no hook or write, a raise
  from `ActorInterface.create`, and a rollback that keeps the older buckets.

Full suite: see the plan's Iterations batch after the fourth verification.

Scope lock: self-check, over `actor.py`, `oauth2.py`, the two system-actor
modules, tests, `CHANGELOG.rst` and `docs/`.

Release: `Actor.create`'s return value changes for a taken id. A CHANGED
entry with **Behavior change:** and **Check:** covers it, inside the 3.16
release.

## Related

- `thoughts/todo/creator-uniqueness-not-enforced.md`: the root cause is
  that the database has no unique creator constraint. This fix contains the
  effect.
- `thoughts/research/2026-10-27-creator-rename-and-create-rollback-leave-wrong-vouch.md`.

## Status

DONE
