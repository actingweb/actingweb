# Investigation: the 3.16 adoption rule took an unconfirmed write or delete as done

**Date:** 2026-10-27
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the fix is uncommitted in the working tree with the rest of the 3.16 work)
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## Symptom

`thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-2.md`
reported this as Issues A and B. It came out of the outside-voice and code
reviews, not from an incident. Under a backend fault, a sign-in could report
an adoption that did not happen:

- **DynamoDB:** a squatter's SPA session survived a clean that was logged as
  complete.
- **PostgreSQL:**
  - a new OAuth actor could be created without its marker, and its next
    sign-in would wipe it;
  - a clean could fire `actor_adopted` with the actor still unvouched;
  - a creator rename could answer 204 and leave the actor vouched.

## Root Cause

The first iteration (`thoughts/research/2026-10-27-adoption-reads-postgresql-fault-as-empty.md`)
made the rule require reads that the backend answered. It never asked the
same question of writes and deletes, and each backend hides one of the two:

- **DynamoDB** `delete_attr` → `set_attr(data=None)` runs `item.delete()`
  inside `except Exception: pass` and returns `True`
  (`db/dynamodb/attribute.py:182-191`). `revoke_all_tokens(strict=True)`
  counted that `True` as confirmation (`oauth_session.py`).
- **PostgreSQL** `set_attr` answers a caught fault with `False`.
  `InternalStore.__setattr__` discards the result (`attribute.py`,
  `self.__dict__["_db"].set_attr(name=k, data=v)`). That is how every
  `auth_method` write was made:
  - `Actor.create`;
  - the clean path in `oauth2._adopt_actor`;
  - `handlers/trust.py`.

## Hypotheses Rejected

- **"DynamoDB's delete raises like its reads."** Rejected. The reads raise;
  the plain delete is wrapped. `single_use.delete_confirmed` already exists
  because of this (its docstring says so), and `client_registry.delete_client`
  uses it.
- **"`set_attr` raises on PostgreSQL."** Rejected. It returns `False`; only
  DynamoDB's `save()` raises.

## Fix

- `actingweb/attribute.py`: `InternalStore.set_confirmed(k, v)`, a write
  followed by a strict read-back (`get_attr_strict`). It returns `False` on a
  fault or a mismatch.
- `actingweb/actor.py` `create`: the marker goes through `set_confirmed`. If
  it does not land, the new actor is deleted and `create` returns `False`.
- `actingweb/oauth2.py`: the clean path's vouched marker goes through
  `set_confirmed`; on failure the sign-in fails closed.
- `actingweb/handlers/trust.py`: `creator_changed` is written and confirmed
  before the creator changes. If it cannot be, the request answers 500.
- `actingweb/oauth_session.py`: in strict mode each token is deleted through
  `single_use.delete_confirmed`.

## Evidence

- Regression tests in `tests/test_adoption_write_faults.py`. Each reproduces
  one backend's fault shape at the seam, so it runs on either backend:
  - `TestSwallowedTokenDelete::test_unconfirmed_session_delete_fails_the_adoption`
  - `TestMarkerWriteFault::test_actor_is_not_created_without_its_marker`
  - `TestMarkerWriteFault::test_clean_in_place_fails_when_the_vouched_marker_does_not_land`

  All three failed with their fix disabled and pass with it.
  `tests/test_trust_creator_rename.py::TestUnpinnedCreator::test_marker_write_fault_refuses_the_rename`
  covers the rename the same way.
- Full suite: see the plan's Iterations entry 13.
- Scope lock: none. The fix spans the storage seam and three callers, inside
  the scope the owner approved (Issues A-G).

## Related

- The same class as the read-side record above. The PostgreSQL backend reports
  faults as values on reads and writes; the DynamoDB backend does the same on
  the plain delete. Code that acts on a write or delete having happened should
  confirm it (`set_confirmed`, `delete_confirmed`), not trust the return.
- `thoughts/todo/db-layer-get-bucket-or-empty.md` covers the older read sites.

## Status

DONE
