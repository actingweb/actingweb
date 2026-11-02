# TODO: adoption rule — remaining fault and hygiene follow-ups

**Status:** Open, approach chosen. Filed 2026-10-27; the owner chose an
approach for every item on 2026-11-02.
`thoughts/plans/2026-11-02-3-16-owner-decided-followups.md` carries J, K, the
callback version check, `find_db_error` and the Flask CORS headers;
`thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md` carries the rest.
**Filed by:** Greger Wedel (with Claude), during the 3.16 adoption work.
**Source:** `thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-2.md`,
Issues H-L, and the later verifications named per item.
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Constraint:** since the fault contract
(`thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`,
Phases 1-2) every backend read and delete raises `DbError` on a fault, and the
integrations answer it with 503. Fixes here let it propagate rather than
catch and fold it.

## What is still owed

- **Tokens issued between the revoke and the purge** (Issue J). The clean
  path revokes before purging, so a token an MCP client obtains inside that
  window survives. Approach: revoke again after `_delete_actor_clients`.
- **UNKNOWN tombstone read** (Issue K). A half-wiped actor whose tombstone
  read faults is cleaned in place and stays tombstoned. Approach: fail
  closed. With the status UNKNOWN and the marker absent, the sign-in answers
  503.
- **Hygiene** (Issue L, the rest):
  - **Summary reads fold:** the replace path's `actor_adopted` summary reads
    (trusts, subscriptions, properties) pass `strict=False`, so a fault
    reports nothing removed. Approach: on a fault the summary reports the
    counts as unknown (`None`) and the log says so; the adoption proceeds.
  - **Lost successor mapping:** if creating the successor raises,
    `actor_adopted` never fires and the old-to-new id mapping is lost.
    Approach: write the mapping into the successor's `_internal` before
    creating it, so the next sign-in that completes the adoption fires
    `actor_adopted` with the right old id.
  - **`purge_relationships`** issues about 4+N list reads where 2 would do.
    Approach: read trusts and subscriptions once each and pass them down.
  - **Redundant cleanup:** on the replace path `delete_client` re-runs token
    and trust cleanup against a deleted actor. Approach: when the actor is
    already deleted, remove only the global client index row.
- **`force_email_prop_as_creator` rewrites an unvouched actor's creator at
  load** (older than 3.16). `Actor.get` copies `store.email` into the
  creator whenever they differ, on every load, before adoption runs; on an
  unvouched actor a sign-in for the real address then keeps the previous
  creator's stored email. Approach: `Actor.get` does not rewrite the creator
  of an unvouched actor; adoption decides.
- **A tombstone on a live vouched actor** (sixth verification, Issue AW;
  the 3.16 attempt to act on it was reverted). Two paths leave one: a
  `DELETE /<id>` whose wipe stalls or raises after `handlers/root.py` wrote
  the tombstone and fired `actor_deleted`, and a create over a fixed id whose
  `clear_actor_tombstone` faulted. The actor stays live and its late writes
  are suppressed for the retention window. Approach, in this order:
  1. confirm the tombstone clear on a fixed-id create (`get_attr_strict`);
     a fault fails the create;
  2. a repeated `DELETE /<id>` finishes the wipe without firing
     `actor_deleted` again;
  3. only then may a sign-in on a tombstoned live actor finish the wipe.

  Sequenced with [resumable actor deletion](resumable-actor-deletion.md).
- **A session at the verification click** (seventh verification, Issue BG).
  The emailed link ends the actor's sessions, and a user whose provider
  supplies no verified address then reaches the free-text form, which
  answers 409 for an address that already has an actor. Approach: the click
  issues the web session or the SPA token, as the OAuth callback would.
  - **Not taken (BV):** letting the free-text form replace a `factory` actor
    a squatter created for the address. The 409 there stays as documented.
- **Low items from the seventh verification**
  (`thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory-2.md`):
  - **BK** (flag off only): the strict DynamoDB `get_by_creator` and the
    sweep do not compare a row's creator with the queried one. Approach:
    drop rows whose normalised creator differs from the query.
  - **BL** (flag off only): two concurrent sign-ins to a vouched actor fire
    `actor_deleted`/`actor_deleted_complete` twice per factory sibling.
    Approach: skip a sibling that is already tombstoned.
  - **BN:** a nested hand-off in `_adopt_actor` drops the incoming
    `carried`. Approach: merge it, with a two-step hand-off test.
  - **BP:** a replacement scans the global SPA token buckets twice.
    Approach: one scan for the victim and its siblings together.
  - **BQ:** `oauth2_spa.py` repeats the resolver's `get_from_creator` →
    `adopt_actor` → `lookup_or_create_actor_by_identifier` in both
    completion paths. Approach: both SPA paths and the web callback call one
    shared helper.
- **Fault-contract follow-ups** (verification
  `thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness.md`,
  Issues N and P):
  - **Revocation cleanup after a fault:** the permission callback stores the
    new permissions, then deletes the revoked peer data through a folding
    list read (`handlers/callbacks.py` `_delete_revoked_peer_data`).
    Approach: delete the revoked data first, with strict reads, then store
    the permissions; a fault answers 503 and the retried callback still sees
    the revocation.
  - **`clear_all_state_for_peer`** folds its bucket read. Approach: strict
    read; a fault raises `DbError`, so the trust deletion answers 503 and is
    retried.
  - **One read-and-classify helper** for `Actor.get_from_creator`,
    `oauth2._factory_siblings` and the successor step, returning the pick
    and the siblings from one read.
  - **Deliberate folds:** `callback_processor` `handler(cb)` errors
    (at-most-once) and the owner's factory sweep swallow `DbError` by
    design. Approach: document both in the hooks reference and the
    fault-contract docs.
  - **`_errors.find_db_error` follows `__context__`:** a bug raised while
    handling a `DbError` answers 503 instead of 500. Approach: follow
    `__cause__` only.
- **Fault-contract follow-ups from the guarded sweep**
  (`thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-2.md`
  and the fourth verification's K4):
  - **The callback version check is not conditional**
    (`callback_processor.py` `_set_state`: read, compare, write); two
    concurrent in-order deliveries can both run the handler. Approach: a
    compare-and-swap with `conditional_update_attr`; the loser skips its
    handler run.
  - **Ordering windows (O2).** Approach: reorder all three, each with a
    fault test:
    - the replacement's pre-reads run before its token revoke;
    - `Actor.delete` reads its lists once, before `actor_deleted`;
    - the OAuth callback and the email-form completion validate before
      writing.
  - **Deliberate post-commit folds that lose a side effect:**
    - `property_store` diff registration. Approach: a fault after the
      property write raises `DbError` (the write stays), so the caller sees
      503 and the subscriber's gap is not silent.
    - `oauth_email` verification-email notification, and the provider-token
      clear at logout (`oauth2_endpoints`, `oauth2_spa`): kept as they are
      by the owner (2026-11-02). They stay folded and logged.
  - **`DeletionStatus.UNKNOWN` proceeds** in `handlers/mcp.py` and
    `oauth2._race_winner`. Approach: fail closed with 503, the same rule
    as K.
  - **DynamoDB `DbSubscription.modify` saves the whole item**, so a
    concurrent `modify` writes back a stale `seqnr`. Approach: an
    `UpdateItem` of only the given fields.
  - **A resync that fails over HTTP loses the suspension window for that
    subscriber** (verification 6, D6). Approach: a per-cycle record of who
    was resynced, so a retry of `resume_subscriptions` re-sends only to the
    ones that missed, and their suspension stays until they succeed.
  - **K4 leftovers**, all four taken:
    - the three remaining `oauth_provider` bookkeeping writes are logged and
      folded instead of failing the sign-in, as plan entry 27 did for the
      first;
    - `SubscriptionManager.is_suspended()` raises `DbError` on a fault
      (Breaking: a CHANGED entry and a migration-guide line);
    - the create rollback also deletes the actor's `_internal` bucket;
    - with no vouched actor, the replacement reads the victim's lists once
      and bounds the ranked creator prefix.
  - **`fanout.py`'s breaker** holds within one process only. Approach:
    correct the comment and say so in the deployment guide. A shared,
    cross-process breaker is not taken.
- **Flask `GET /?format=json` reflects `Origin` with credentials**
  (`handlers/factory.py`; eighth verification, notes). The content is public
  configuration. Approach: keep reflecting the origin, drop
  `Access-Control-Allow-Credentials`, and make FastAPI match.

## Constraint: the second tombstone write is deliberate

The replace path (`oauth2.py`) and `DELETE /<id>` (`handlers/root.py`) write
the deletion tombstone before firing `actor_deleted`, and `Actor.delete`
writes it again. That second write re-stamps `deleted_at` and the TTL
(`deletion.py`), so late-write suppression runs from the wipe, not from before
a possibly long hook. Do not remove it as a duplicate. The owner confirmed
keeping it on 2026-11-02.

## Why it waits

None of these lets an attacker in. J and K need a coinciding backend fault
or a race; the rest is cost and tidiness.
