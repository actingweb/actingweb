# Creator uniqueness: small follow-ups

Low items left by the 3.16 uniqueness verifications
(thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-2.md
L8 and -9, and the end-to-end review of
thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md). The
single-action rows landed with thoughts/plans/2026-11-02-3-16-small-followups.md.
The owner chose an approach for each row below on 2026-11-02;
thoughts/plans/2026-11-02-3-16-owner-decided-followups.md carries them.

- **`actor_created` for a kept successor.** When the create fails after the
  swap, the successor is kept unmarked, without `actor_created` or its store
  seeding (`created_at`, `email`), and the next sign-in fires only
  `actor_adopted`. Found on planning: the OAuth successor is pre-marked, so
  the reachable gap is the store seeding after `actor_created`. Approach: a
  vouched sign-in seeds a missing `store.email`; `actor_created` is not fired
  again.
- **The force-email rewrite under the flag.** It retries on every load for
  an actor whose stored email another actor holds: a cancelled transaction,
  a read and a WARNING each time (`actor.py` `get`). Approach: read the
  `creators` record first and skip the rewrite quietly when another actor
  holds the email.
- **The default-creator sweep.** It runs on the create path (`actor.py`
  `create`, the `force_email_prop_as_creator` branch) and loads every
  `creator` actor on each default-creator create. Approach: move it to
  `actingweb-unique-creators` (report and resolve). **Behavior change:** a
  create no longer cleans leftover default-creator actors.
- **The SDK rename's binding window.** `ActorInterface.modify_creator`
  without `unvouch` renames, then moves `vouched_creator`
  (`interface/actor_interface.py` `_rebind_vouch`); in between, a sign-in for
  the new address reads the actor as unvouched and cleans it. Approach: a
  `vouched_creator_pending` value written before the rename and promoted
  after it, accepted by the vouch check, so neither creator type has a
  window.
