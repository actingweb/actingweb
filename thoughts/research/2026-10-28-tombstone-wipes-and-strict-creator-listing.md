# Investigation: a tombstone wiped live vouched actors, and the creator listing failed on index lag and faults

**Date:** 2026-10-28
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the fix is uncommitted in the working tree with the rest of the 3.16 work)
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## Symptom

From `thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory.md`
(sixth run):

- **AW (High):** a vouched actor with a deletion tombstone was deleted and
  recreated at its owner's next sign-in. That covers a stale tombstone on a
  reused fixed id, and a DELETE that stalled; in the second case
  `actor_deleted` fired twice.
- **AX:** on DynamoDB, an index entry for a just-deleted actor failed every
  sign-in for the address, so a squatter could keep the owner's first
  sign-in failing.
- **AY:** a listing that missed the victim swept only what it saw.
- **AZ:** a read fault in the successor step created a second vouched actor
  beside the owner's.
- **BA-BF:** the record a recursive clean reports, factory actors beside a
  vouched one, the create rollback and the bridge's winner, a provider-id
  creator's email, peer-trustee rows of unlisted types, and four copies of
  the marker check.

## Root Cause

- **AW:** entry 35 (fifth batch) read the tombstone before the vouched
  return. Two existing paths leave a tombstone on a live actor:
  - `handlers/root.py` writes it and fires `actor_deleted` before the wipe;
  - `Actor.create` ignores `clear_actor_tombstone`'s result, and
    DynamoDB's `delete_attr` answers True on a fault.
- **AX, AY, AZ:** the sweep and the successor step decided from
  non-strict listings:
  - DynamoDB's `get_by_creator` returns a None entry for an index row whose
    actor is gone;
  - PostgreSQL's returns None on a fault;
  - the code read each of these either as a fault (AX), as nothing missing
    (AY), or as "nothing left" (AZ).
- **BA:** the recursive `return _adopt_actor(...)` dropped the outer
  replacement's summary.
- **BB:** only a replacement swept siblings, and a vouched win never
  triggers one.
- **BC:** the rollback branch returned before unbinding, and the bridge
  accepted any row that loaded.
- **BD:** the email reset only handled creators containing `@`.
- **BE:** `delete_peer_trustee("*")` visits only the types in
  `config.actors`.
- **BF:** four copies of the marker check had drifted apart.

## Hypotheses Rejected

- **Keep entry 35 and confirm the tombstone clear instead.** That would fix
  only one of the two paths. A stalled user DELETE is legitimate, and a
  sign-in that finishes it fires `actor_deleted` a second time. Filed as a
  todo item with both prerequisites.
- **Skip None rows in the non-strict listing** (the sixth verification's
  first suggestion for AX). A None row has no id, so a fault cannot be told
  from index lag. A strict backend read can make that distinction
  (`DoesNotExist` versus any other exception), so the fix went there.

## Fix

See the plan's Iterations entries 39-46. The primitives reused:
- `classify_store` builds on `is_vouched_store`;
- the `strict` keyword follows the pattern already on the trust and
  subscription list `fetch`;
- `get_deletion_status` decides "deleted since listed";
- `set_confirmed` is untouched.

## Evidence

The regression tests are in `tests/test_adoption_sixth_iteration.py`.
`ff6b.py` disabled each fix in place, and each test failed:
- AY: the victim-missing check;
- AZ: the successor's fail-closed;
- AX: DynamoDB's strict `DoesNotExist` skip;
- BA: the `carried` merge;
- BB: the vouched sweep, and the batching;
- BC: the rollback unbind;
- BD: the email expression.

The remaining tests failed with the pre-batch files swapped back in:
- AW: `TestVouchedActorMidDeletion`, with the pre-batch `oauth2.py`,
  `actor.py` and `oauth_session.py`;
- BE: with the pre-batch `actor.py`;
- the bridge winner: with the pre-batch `mcp.py`.

Fast tier: 3063 passed, 23 skipped. Full tier: see the plan.

Scope lock: self-check, over:
- `actor.py`, `oauth2.py`, `oauth_session.py`, `handlers/mcp.py`;
- `db/protocols.py`, the two `db/*/actor.py`, the two
  `db/*/peertrustee.py`;
- `tests/`, `CHANGELOG.rst`, and `docs/` (`migration/v3.16.rst`,
  `reference/hooks-reference.rst`).

That is more than five files; the owner asked for every item.

## Decisions

- **Release:** inside 3.16. New `strict` keywords are on
  `get_by_creator` and on the peer-trustee list `fetch`: a custom backend
  must accept them, and the existing "Breaking: … take `strict`" entry
  covers that.
- **Factory siblings:** removed by any sign-in that proves the address, not
  only by a replacement (entry 42).
- **The tombstone-on-vouched case stays as before 3.16**, filed in
  `thoughts/todo/adoption-fault-and-hygiene-followups.md`.

## Related

- `thoughts/research/2026-10-28-owners-actor-stranded-and-sweep-read-faults.md`:
  the fifth batch, including entry 35, which this reverts.
- `thoughts/todo/db-layer-get-bucket-or-empty.md`: the DB-layer fix that
  would make most per-call `strict`/`loaded` checks unnecessary.
- `thoughts/todo/creator-uniqueness-not-enforced.md`.

## Status

DONE
