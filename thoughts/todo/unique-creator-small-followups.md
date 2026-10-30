# Creator uniqueness: small follow-ups

Low items from thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-2.md
(L8) that Iterations 52-58 of
thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md left:

- **`actor_created` for a kept successor.** When the create fails after the
  swap, the successor is kept unmarked, without `actor_created` or its
  store seeding (`created_at`, `email`). The next sign-in fires only
  `actor_adopted`. Fire `actor_created` from the clean-in-place step when
  the actor has no marker, or document it in the hooks reference.
- **The force-email rewrite under the flag.** It retries, on every load,
  for an actor whose stored email another actor holds: a cancelled
  transaction, a read and a WARNING each time (`actor.py` `get`).
  Remember the refusal, or skip the rewrite when the email is held.
- **The default-creator sweep.** It runs on the create path
  (`actor.py` `create`, the `force_email_prop_as_creator` branch): it loads
  every `creator` actor on each default-creator create. Move it to the
  command.
- **Custom backends with the flag off.** `get_actor` passes
  `unique_creator=` always. Passing it only when it is on would spare
  custom backends with the flag off; the CHANGELOG's Breaking entry covers
  it today.
- **Inline normalisation copies.** `creator.lower() if "@" in creator`
  remains in `actor.py` (`get_from_creator`, `creator_change_pinned`,
  `modify_creator_unvouched`, `modify`) and `handlers/factory.py`. Call
  `normalise_creator`.
- **`#…` addresses with the flag off.** `#team@x.com` is a legal address,
  and `Actor.create` refuses it whether or not the flag is on. Consider
  refusing only with the flag on, or only `#meta#…` and `#dup-`.

From thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-9.md:

- **The SDK rename's binding window.** `ActorInterface.modify_creator`
  without `unvouch` renames, then moves `vouched_creator`
  (`interface/actor_interface.py` `_rebind_vouch`). In between, a sign-in
  for the new address reads the actor as unvouched and cleans it. Writing
  the address first covers email creators (the old one still passes through
  the stored email) but not provider-id creators; either order has a
  window. Application-initiated, milliseconds wide.
- **`clear_pending_email_verification` leaves `email_verification_address`**
  (`oauth2.py`): harmless without a token, and the next link overwrites it.
  Clear it with the token.
- **The restore's log on a fault.** DynamoDB's `conditional_update_attr`
  answers False on a fault too, so `_restore_marker` logs "auth_method
  changed since this creator change wrote it" for an outage. The actor
  stays unvouched either way; tell the two apart with a strict re-read.

From the end-to-end review of the plan (2026-10-30), items the plan
recorded only in its own text:

- **The two-step record move on a DynamoDB rename.** The new record and the
  actor are written in one transaction, the old record released after it,
  so for that moment the freed old creator still answers `CreatorTaken`.
  The pre-implementation review asked for it under Phase 3's failure
  scenarios; document it in the migration guide's "What the flag changes".
- **Unverified: a creator containing `#` in a URL.** A route or template
  that puts the creator in a URL might break on `#`; the reserved prefixes
  reduce the exposure, but no template (the library's or the demo's) was
  checked.
- **Unverified: records edited by hand.** A record pointing at the wrong
  actor id is found only by `report`'s orphan pass; say so in the guide.
- **The iteration-numbered test files.**
  `tests/test_adoption_{fourth,fifth,sixth}_iteration.py` should be named by
  behaviour (from the adoption PR's review; the plan named it out of its
  scope).

