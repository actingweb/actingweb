# TODO: adoption rule — remaining fault and hygiene follow-ups

**Status:** Open. Filed 2026-10-27.
**Filed by:** Greger Wedel (with Claude), during the 3.16 adoption work.
**Source:** `thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-2.md`,
Issues H-L. Issues A-G and two L items landed (the plan's Iterations entries
8-13). This file lists only what is still owed.
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## What is still owed

- **Replace path: client rows after a bucket-delete fault** (Issue I,
  Medium).
  - `oauth2._adopt_actor` treats a failed `_delete_actor_clients` as
    non-fatal, on the grounds that the bucket delete already removed the
    client rows.
  - But `buckets.delete()`'s result is ignored (`actor.py`, `Actor.delete`),
    and `Buckets.delete` answers `True` unconditionally (`attribute.py`).
  - So if the bucket delete and the client delete both fail while the row
    delete succeeds, a client that can still authenticate survives, with only
    a log line.
  - Confirm the client rows with `delete_confirmed`. If they are not gone,
    leave the tombstone so the next sign-in resumes.
- **`DELETE /<id>` ignores `Actor.delete() -> bool`** (Issue H).
  `handlers/root.py` answers 204 and fires `actor_deleted_complete` even on a
  PostgreSQL row-delete fault. Return 500 and skip the completion hook. This
  is older than 3.16.
- **Tokens issued between the revoke and the purge** (Issue J). The clean
  path revokes before purging. A token an MCP client obtains inside that
  window survives. Revoke again after `_delete_actor_clients`.
- **UNKNOWN tombstone read** (Issue K). A half-wiped actor whose tombstone
  read faults is cleaned in place and stays tombstoned. When the status is
  UNKNOWN and the marker is absent, fail closed, or clear the tombstone when
  a clean succeeds.
- **Hygiene** (Issue L, the rest):
  - **Duplicate tombstone:** the replace path calls
    `deletion.mark_actor_deleted` before `delete()`, which writes it again.
  - **Non-strict reads:** the replace path's summary reads (trusts,
    subscriptions) are not strict, so a PostgreSQL fault reports nothing
    removed in the hook and the log.
  - **Lost successor mapping:** if creating the successor raises,
    `actor_adopted` never fires and the old-to-new id mapping is lost.
  - **`purge_relationships`** issues about 4+N list reads where 2 would do.
  - **Redundant cleanup:** on the replace path `delete_client` re-runs token
    and trust cleanup against a deleted actor. Only the index row is needed.
  - **Meaning of the return value:** `Actor.delete`'s `True` means "no
    fault", not "a row was removed". Neither backend checks the row count;
    document it or check it.
  - **Missing type hints** on `delete_peer_trustee`, `delete_reciprocal_trust`
    and the DynamoDB list `fetch(..., strict=False)`.
- **`force_email_prop_as_creator` rewrites an unvouched actor's creator at
  load** (found in the fourth verification's iteration; older than 3.16).
  - `Actor.get` copies `store.email` into the creator whenever they differ
    (`actor.py`, the `force_email_prop_as_creator` branch). It does this on
    every load, before adoption runs.
  - On an unvouched actor whose `store.email` the previous creator wrote, a
    sign-in for the real address loads the actor and rewrites its creator to
    that stored email. The clean then keeps that address.
  - The 3.16 clean now sets `store.email` to the creator, which covers the
    case where the pin was off at the clean and turned on later. It does not
    cover the pin being on at load.
  - Skip the rewrite for an unvouched actor, or pass the proven identifier
    into `adopt_actor`.
- **No test for `DbActor.modify` leaving the handle as stored on a failed
  save** (both backends; the change landed in the fourth iteration). It
  needs a backend-specific fault injection (`get_connection` on PostgreSQL,
  `Model.save` on DynamoDB).
- **A tombstone on a live vouched actor** (sixth verification, Issue AW;
  the 3.16 attempt to act on it was reverted).
  - Two paths leave one:
    - a `DELETE /<id>` whose wipe stalls or raises after `handlers/root.py`
      wrote the tombstone and fired `actor_deleted`;
    - a create over a fixed id whose `clear_actor_tombstone` faulted
      (`actor.py` ignores its result, and DynamoDB's `delete_attr` answers
      True on a fault).
  - The actor stays live, and its late writes are suppressed for the
    retention window. Sign-ins return it as is.
  - Confirm the clear on create (`get_attr_strict`). Let a resumed user
    DELETE finish without firing `actor_deleted` a second time. Only then
    can a sign-in safely finish such a wipe.
- **A session at the verification click** (seventh verification, Issue BG).
  - The emailed link ends the actor's sessions. A user whose provider
    supplies no verified address then reaches the free-text form, which
    answers 409 for an address that already has an actor (older than 3.16).
  - The click proves the address, so issue the session or SPA token there,
    as the callback would.
  - Documented in the CHANGELOG, the migration guide and
    `docs/guides/authentication.rst`.
  - The same 409 meets that user when a squatter created a `factory` actor
    for the address first (eighth verification, Issue BV; documented too).
    The alternative is to let the form replace a `factory` actor: the
    emailed link still has to prove the address.
- **Low items from the seventh verification**
  (`thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory-2.md`):
  - **BK:** the strict DynamoDB `get_by_creator` and the sweep do not
    compare a row's creator with the queried one. A stale index after a
    rename can list a (factory) actor under its old creator.
  - **BL:** two concurrent sign-ins to a vouched actor fire
    `actor_deleted`/`actor_deleted_complete` twice per factory sibling. Skip
    a sibling that is already tombstoned.
  - **BM:** `tests/test_adoption_fifth_iteration.py` (`TestSweepReadFaults`,
    the None-listing test) patches `get_by_creator` without `strict`, so it
    passes through a `TypeError` instead of the `seen_exclude` path.
  - **BN:** a nested hand-off in `_adopt_actor` drops the incoming
    `carried`.
  - **BO:** under `unique_creator`, `Actor.create` filters None rows, so a
    faulted DynamoDB row read counts as "no existing actor". Use the strict
    listing.
  - **BP:** a replacement scans the global SPA token buckets twice (victim,
    then siblings), and reads each sibling's marker and row up to three
    times.
  - **BQ:** `oauth2_spa.py` repeats the resolver's `get_from_creator` →
    `adopt_actor` → `lookup_or_create_actor_by_identifier` in both
    completion paths.
- **Benchmarks on a fresh DynamoDB container:** the attribute benchmarks fail
  with `ResourceNotFoundException ... test_attributes` until some other test
  has created the table. The performance fixtures should create the tables
  they use.
- **Flask `GET /?format=json` reflects `Origin` with credentials**
  (`handlers/factory.py:134-141`; eighth verification, notes). Older than
  3.16, and FastAPI already serves the same headers. The content is public
  configuration, so the impact is Low; tighten it to an allowlist or drop
  `Access-Control-Allow-Credentials`.

## Why it waits

None of these lets an attacker in. I and H can leave a disabled client's
index row, or report a delete that did not finish, but only under a
coinciding backend fault. The rest is cost and tidiness.
