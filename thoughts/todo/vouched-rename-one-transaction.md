# The vouched SDK rename is several writes, not one transaction

**Plan:** `thoughts/plans/2026-11-06-email-as-creator-at-write-time.md` (proposed, for 3.16). The plan supersedes this file,
which is deleted when the plan lands; where the two disagree, the plan wins.

**Status:** Open, not urgent. Recorded 2026-11-02 by the audit of
`ActorInterface.modify_creator` (vouched) in
`thoughts/plans/2026-11-02-3-16-owner-decided-followups.md`, Iterations
entries 21-23, where the state table and the reasons each limit was accepted
live.
**Filed by:** Greger Wedel (with Claude).

## What is left

The rename moves up to four values in order: `vouched_creator_pending`, the
stored email (under `force_email_prop_as_creator`, the commit point), the
creator (the actor row), then `vouched_creator`. The actor row and `_internal`
are in different tables, and no write spans them, so these limits remain:

- **Concurrent renames of one actor are not serialised.** The email of one can
  end up with the creator of the other, and a sign-in between them can find
  the actor unvouched. Documented: serialise renames of one actor.
- **A `DbError` past the commit point does not say the rename will complete.**
  The next load, or calling it again, finishes it; the caller cannot tell
  "not renamed" from "renamed later" without reading the actor.
- **Under the pin with no stored email, a rename to a provider id** (no
  address, so no email is written) can be undone by a racing sign-in that
  seeds the email from the old creator.
- **Restoring an email that was absent is a read, then a delete:** the
  backends have no delete-if-equal.

## What would close it

One transactional write of the actor row and the `_internal` rows: DynamoDB
`TransactWriteItems` across the two tables, and one PostgreSQL transaction.
That is a new `DbActor` method on both backends (a rename that also writes
named `_internal` attributes, conditioned on the creator). A per-actor rename
lock would close the first item only.

None of these lets an address nobody vouched for take an actor; each is a
rename that ends on a different application-chosen address, or a rename that
reports a fault and completes later.
