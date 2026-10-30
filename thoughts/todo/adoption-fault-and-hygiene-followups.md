# TODO: adoption rule — remaining fault and hygiene follow-ups

**Status:** Open. Filed 2026-10-27.
**Filed by:** Greger Wedel (with Claude), during the 3.16 adoption work.
**Source:** `thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-2.md`,
Issues H-L. Issues A-G and two L items landed (the plan's Iterations entries
8-13). This file lists only what is still owed.
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Constraint:** since the fault contract
(`thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`,
Phases 1-2) every backend read and delete raises `DbError` on a fault, and the
integrations answer it with 503. Fixes here should let it propagate rather
than catch and fold it.

## What is still owed

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
  - **Summary reads fold:** the replace path's `actor_adopted` summary
    reads (trusts, subscriptions, properties) pass `strict=False` by design,
    so a fault reports nothing removed in the hook and the log.
  - **Lost successor mapping:** if creating the successor raises,
    `actor_adopted` never fires and the old-to-new id mapping is lost.
  - **`purge_relationships`** issues about 4+N list reads where 2 would do.
  - **Redundant cleanup:** on the replace path `delete_client` re-runs token
    and trust cleanup against a deleted actor. Only the index row is needed.
  - **Missing type hints** on `delete_peer_trustee`, `delete_reciprocal_trust`
    and the DynamoDB trust and subscription list `fetch(..., strict=True)`.
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
- **No DynamoDB test for `DbActor.modify` leaving the handle as stored on a
  failed save** (the change landed in the fourth iteration). PostgreSQL's is
  in `tests/test_db_fault_contract.py`; DynamoDB needs `Model.save` to raise.
- **A tombstone on a live vouched actor** (sixth verification, Issue AW;
  the 3.16 attempt to act on it was reverted).
  - Two paths leave one:
    - a `DELETE /<id>` whose wipe stalls or raises after `handlers/root.py`
      wrote the tombstone and fired `actor_deleted`;
    - a create over a fixed id whose `clear_actor_tombstone` faulted
      (`actor.py` ignores its result; since 3.16 the delete raises on a
      fault, so check where the create path swallows it).
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
    rename can list a (factory) actor under its old creator. Holds with
    `unique_creator` off only: with it on, the lookup reads the `creators`
    record and there is no sweep.
  - **BL:** two concurrent sign-ins to a vouched actor fire
    `actor_deleted`/`actor_deleted_complete` twice per factory sibling. Skip
    a sibling that is already tombstoned. Holds with `unique_creator` off
    only: with it on there are no siblings to sweep.
  - **BN:** a nested hand-off in `_adopt_actor` drops the incoming
    `carried`.
  - **BP:** a replacement scans the global SPA token buckets twice (victim,
    then siblings).
  - **BQ:** `oauth2_spa.py` repeats the resolver's `get_from_creator` →
    `adopt_actor` → `lookup_or_create_actor_by_identifier` in both
    completion paths.
- **Fault-contract follow-ups** (verification
  `thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness.md`,
  Issues N and P):
  - **Revocation cleanup after a fault:** the permission callback stores the
    new permissions, then lists the peer's cached lists to delete revoked
    ones (`handlers/callbacks.py` `_delete_revoked_peer_data`, through
    `attribute_list_store.list_all`, which folds). A fault there leaves the
    revoked data, and a 503 would not help, because the retried callback sees
    no revocation. Run the cleanup before storing, or record the pending
    revocation.
  - **`clear_all_state_for_peer`** folds its bucket read, so trust deletion
    during a throttle leaves callback state behind (logged at ERROR).
  - **One read-and-classify helper:** `Actor.get_from_creator`,
    `oauth2._factory_siblings` and the successor step each load a row and
    classify its marker, and the pick and the siblings are read twice.
  - **Deliberate folds to document:** `callback_processor` `handler(cb)`
    errors (at-most-once) and the owner's factory sweep (`oauth2.py`, "the
    owner is in") swallow `DbError` by design.
  - **`_errors.find_db_error` follows `__context__`:** a bug raised while
    handling a `DbError` answers 503 instead of 500.
- **Fault-contract follow-ups from the guarded sweep**
  (`thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-2.md`,
  the per-file classification of `tests/test_db_fault_guard.py`'s sites, and
  the fourth verification's K4). Plan entry 28 fixed the creator fallback,
  the `InternalStore` write order, the registry retry and the maintenance
  exit codes; entry 32 retired the sequence rollback.
  - **The callback version check is not conditional**
    (`callback_processor.py` `_set_state`: read, compare, write). Two
    concurrent in-order deliveries can both pass and run the handler twice.
    Use `conditional_update_attr`. This is older than 3.16.
  - **Ordering windows on the sign-in and replace paths (O2):**
    - the replacement revokes tokens before its pre-reads;
    - `Actor.delete` re-reads the lists after `actor_deleted` fired;
    - the OAuth callback and the email-form completion raise after their
      store writes.
  - **Deliberate post-commit folds that lose a side effect:**
    - `property_store` diff registration (since entry 32 a skipped
      subscriber gets a gap where the store allows one);
    - `oauth_email` verification-email notification (the email may not be
      sent);
    - the provider-token clear at logout (`oauth2_endpoints`, `oauth2_spa`),
      where the token can stay behind while the logout reports success.
  - **`DeletionStatus.UNKNOWN` proceeds** in `handlers/mcp.py` and
    `oauth2._race_winner` (`!= DELETED`). This is by design per
    `deletion.py`, and related to K above.
  - **Possible pre-existing bug:** `actor.py`
    `modify_trust_and_notify_async` builds
    `AwProxy(peer_target={"baseuri", "secret"})`, but `AwProxy.__init__`
    reads `peer_target["id"]`. The `KeyError` is caught, so the async peer
    notification looks like it always fails. Not reproduced.
  - **The property handlers fall back to the legacy grant on a non-`DbError`
    from the evaluator** (`handlers/properties.py`, "Fall back to legacy
    authorization on errors"). Older than 3.16, and since entry 30 no
    database fault reaches it; denying would be the fail-closed choice.
  - **DynamoDB `DbSubscription.modify` saves the whole item**, so a
    concurrent `modify` of another field writes back a stale `seqnr`. Only
    the subscriber's own rows still pass `seqnr` through `modify`; the
    publisher uses `increment_seq`.
  - **A resync that fails over HTTP loses the suspension window for that
    subscriber** (verification 6, D6). `_callback_subscription_resync`
    returns False on a network failure; the suspension stays lifted, no diff
    is stored at the allocated number on the resync-capable path, and a
    retry of `resume_subscriptions` resends to every subscriber at a new
    sequence (storing another fallback diff each time). A per-cycle record
    of who was resynced would let a retry resend only to the ones that
    missed it. Older than 3.16 in kind; the returned count is the only
    signal, now documented.
  - **K4 leftovers:**
    - three more `oauth_provider` bookkeeping writes fail a sign-in
      (`oauth2.py` vouched successor, after the marker landed, after
      `actor_created` fired); plan entry 27 folded one;
    - public `SubscriptionManager.is_suspended()` answers False on a fault;
    - the create rollback removes only the row, so an ambiguous marker
      write can leave `_internal` attributes under the id;
    - `fanout.py`'s "the in-memory breaker still applies" holds within one
      process only;
    - with no vouched actor the ranked creator prefix is every actor, and a
      replacement reads the victim's lists three times;
    - type hints are still missing on the DynamoDB signatures this work
      changed.
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

None of these lets an attacker in. J and K need a coinciding backend fault
or a race; the rest is cost and tidiness.
