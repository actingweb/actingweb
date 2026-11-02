# Creator uniqueness: small follow-ups

Low items left by the 3.16 uniqueness verifications
(thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-2.md
L8 and -9, and the end-to-end review of
thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md). Each
needs an owner decision; the single-action rows landed with
thoughts/plans/2026-11-02-3-16-small-followups.md.

- **`actor_created` for a kept successor.** When the create fails after the
  swap, the successor is kept unmarked, without `actor_created` or its
  store seeding (`created_at`, `email`). The next sign-in fires only
  `actor_adopted`. Decide: fire `actor_created` from the clean-in-place step
  when the actor has no marker, or document it in the hooks reference.
- **The force-email rewrite under the flag.** It retries, on every load,
  for an actor whose stored email another actor holds: a cancelled
  transaction, a read and a WARNING each time (`actor.py` `get`).
  Decide: remember the refusal, or skip the rewrite when the email is held.
- **The default-creator sweep.** It runs on the create path
  (`actor.py` `create`, the `force_email_prop_as_creator` branch): it loads
  every `creator` actor on each default-creator create. Moving it to the
  command changes what the create path does.
- **Custom backends with the flag off.** `get_actor` passes
  `unique_creator=` always. Passing it only when it is on would spare
  custom backends with the flag off; the CHANGELOG's Breaking entry covers
  it today. A contract choice.
- **`#…` addresses with the flag off.** `#team@x.com` is a legal address,
  and `Actor.create` refuses it whether or not the flag is on. Consider
  refusing only with the flag on, or only `#meta#…` and `#dup-`.
- **The SDK rename's binding window.** `ActorInterface.modify_creator`
  without `unvouch` renames, then moves `vouched_creator`
  (`interface/actor_interface.py` `_rebind_vouch`). In between, a sign-in
  for the new address reads the actor as unvouched and cleans it. Writing
  the address first covers email creators (the old one still passes through
  the stored email) but not provider-id creators; either order has a
  window. Application-initiated, milliseconds wide.

