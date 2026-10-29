# Investigation: the creator rename and the create rollback could leave an actor with the wrong vouch

**Date:** 2026-10-27
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the fix is uncommitted in the working tree with the rest of the 3.16 work)
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## Symptom

`thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-3.md`
reported these as Issues M, N, O and P. They came from the outside-voice
review and `/code-review high`, not from an incident.

- **M:** a squatter could rename a `factory` actor to the victim's address.
  The victim's sign-in then cleaned the actor instead of replacing it, and
  the squatter's data stayed in the victim's account.
- **N, O:** a rename that failed, or ran against an unreadable `_internal`
  bucket, could leave the owner's own actor marked for a clean.
- **P:** on DynamoDB, a create over a live actor whose read had faulted
  could end with the rollback wiping that actor.

## Root Cause

- **M:** `handlers/trust.py` wrote `creator_changed` whatever the previous
  marker was. `creator_changed` is not in `REPLACE_AUTH_METHODS`, so a
  `factory` actor was downgraded from replace to clean.
- **N:**
  - DynamoDB's `modify` raises on a failed save
    (`db/dynamodb/actor.py`, `self.handle.save()`), so the restore line was
    never reached.
  - The restore was a plain write.
  - PostgreSQL's False fell through to 204.
- **O:** the handler read `store.email` and `store.auth_method` without
  `store.loaded`. A PostgreSQL bucket fault reads both as None, so the pin
  was skipped, and a restore wrote `auth_method = None`.
- **P:** `DbActor.create` checks `self.get()` first, and `get()` answers
  None on any fault. The put that followed was unconditional. The 3.16
  rollback (`self.delete()` on a marker fault) then deleted the live
  actor's data.

## Hypotheses Rejected

- **"The PostgreSQL insert can overwrite too."** Rejected: the primary key
  refuses it, and `create` answers False.
- **"`Actor.create` answers False when the backend refuses."** Rejected: it
  answers True whatever `created` is. That is older than 3.16 and is filed
  in `thoughts/todo/adoption-fault-and-hygiene-followups.md`.

## Fix

- `actingweb/handlers/trust.py`: a new `_change_creator`:
  - answers 500 on an unloaded bucket;
  - keeps a marker in `REPLACE_AUTH_METHODS`;
  - on a failed `modify` (raised or False), restores the marker with
    `set_confirmed` and answers 500;
  - runs before `trustee_root` is written.
- `actingweb/attribute.py`: `set_confirmed(k, None)` deletes and confirms,
  a failed write is reported, and a load fault does not raise.
- `actingweb/db/dynamodb/actor.py`: the insert is conditional
  (`Actor.id.does_not_exist()`), reusing the pattern in
  `db/dynamodb/property.py`.
- `actingweb/actor.py`: a rollback delete that fails is logged.
- Related, from the same verification: the clean's `email_verified` clear
  is confirmed (`oauth2.py`).

## Evidence

Regression tests. Each one failed with its fix file swapped back and passed
with it restored:

- `tests/test_trust_creator_rename.py::TestRenameFaults`:
  - `test_factory_actor_keeps_its_marker` asserts the marker is `factory`
    after the rename;
  - `test_failed_modify_answers_500_and_restores_the_marker[raises|false]`
    asserts 500, creator unchanged, marker `google_oauth2`;
  - `test_unreadable_internal_bucket_answers_500`;
  - `test_refused_rename_does_not_write_trustee_root`.
- `tests/test_adoption_write_faults.py::TestThirdIterationFaults::test_create_over_a_live_actor_whose_read_faults_leaves_it_intact`
  asserts the live actor's creator and marker survive.

Both backends run them, since the faults are injected at the backend class.
Full suite: see the plan's Iterations batch after the third verification.

Scope lock: self-check. The paths are the handler, the attribute layer, the
DynamoDB actor backend, `actor.py`, their tests, `CHANGELOG.rst` and
`docs/`.

Release: no route, hook, kwarg or response field is added. The rename can
now answer 500 where it answered 204 or raised. This ships in the same
release as the rest of 3.16, so it needs no separate patch.

## Related

- `thoughts/research/2026-10-27-adoption-writes-and-deletes-reported-done-on-fault.md`:
  the same class, one step further. Every write that decides a vouch is now
  confirmed, including the restores and the deletes.

## Status

DONE
