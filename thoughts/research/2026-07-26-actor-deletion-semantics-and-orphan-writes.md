# Actor deletion semantics: a consumer cannot write a correct "actor is gone" guard

**Date:** 2026-07-26
**Input:** production investigation in the `actingweb_mcp` consumer
(eu-central-1, DynamoDB backend, `AWS_DB_PREFIX=AI`), running
`actingweb==3.13.0rc1`
**Library state at time of writing:** `3.13.0rc1` released; rc2 in progress in
the working tree (`actor.py`, `subscription_suspension.py`, docs)
**Companion doc:** `2026-07-25-v3.13.0rc1-consumer-feedback.md` (D1–D9, I0–I3 —
the 3.13 scaling migration). This doc is deliberately separate: different
subject, and it carries a request for **rc2**.
**Consumer status:** the consumer's release is **gated on rc2 shipping DEL1**.
Their guard is designed against it and will not ship before it exists.

Findings are numbered `DEL1`–`DEL5`. Every claim below cites a `file:line` in
this repository's working tree, or a measured production number.

---

## Summary

Two defects combine so that **no consumer can write a correct guard of the form
"do not write for an actor that has been deleted"**:

- **DEL1** — `Actor.delete()` removes the actor row **last**, so
  `ActorInterface.get_by_id()` keeps returning a live actor for the entire
  duration of the wipe. Existence checks fail **open** exactly during the window
  where they matter.
- **DEL2** — `get()` returns `None` for both "does not exist" and "the read
  failed". So the same check that fails open mid-deletion also fails **closed**
  on a throttle, which for a paid-subscription webhook means silently not
  granting access to a customer who paid.

There is no ordering of those two failure modes a consumer can choose that is
safe. DEL1 pushes toward "check more aggressively"; DEL2 makes aggressive
checking dangerous.

**Measured consequence.** 4 rows in the consumer's production `AI_attributes`
table (2 actor ids × `service:service_type` + `subscription:metadata`) belong to
accounts that were fully deleted. They were written by a Stripe
`subscription.deleted` webhook, arriving in response to the cancellation the
consumer's own `actor_deleted` hook had just issued, while the actor row still
resolved. `canceled_at` on both rows is `2026-07-13T20:26:31Z` / `:32Z`. Their
contents are the *full* subscription metadata, not the bare
`{status, canceled_at}` a post-wipe write would produce — i.e. the handler read
the actor's data, the wipe ran, and the handler wrote it back.

A further 228 rows under 114 phantom ids in the same table came from the
consumer's own test bug (calling webhook handlers with an actor id that was
never created). That is the consumer's fault, not the library's — it is included
here only because it is the cleanest available demonstration of **DEL3**.

---

## DEL1 — Deletion fails open; there is no deletion tombstone

**Severity: high.** This is the one the consumer is gating their release on.

`Actor.delete()` (`actingweb/actor.py:427-452`) wipes in this order:

1. `delete_peer_trustee(shorttype="*")` — :432
2. `property_list.delete()` — :438
3. subscriptions — :439-441
4. trusts, incl. reciprocal — :442-449
5. `attribute.Buckets(...).delete()` — :450-451
6. `self.handle.delete()` — **:452, the actor row, last**

So for the whole of steps 1–5, `DbActor.get()` still returns a row,
`CoreActor.get()` still populates `self.id`
(`actingweb/actor.py:233-245`), and `ActorInterface.get_by_id()` still returns
an `ActorInterface` (`actingweb/interface/actor_interface.py:157-162`). A
consumer's "is this actor still there?" check answers **yes** while the actor's
data is being erased underneath it.

That window is not theoretical. It is seconds wide for an actor with a real
property set, and it is *entered deliberately* by the documented pattern: the
`actor_deleted` lifecycle hook is where a consumer cancels an external
subscription, and cancelling triggers an asynchronous provider webhook that
arrives right back into the window. Both production rows above were created this
way.

**Reproduction.** With the DynamoDB backend and a consumer that (a) registers an
`actor_deleted` hook which calls an external API whose callback writes actor
attributes, and (b) guards that callback with
`ActorInterface.get_by_id(actor_id, config) is None` — delete an actor with a
non-trivial property set. The callback lands during steps 2–5, passes the guard,
and writes attribute rows that survive the wipe. Cheaper synthetic version: call
`Actor.delete()` in one thread and assert `ActorInterface.get_by_id()` is not
`None` after `buckets.delete()` has run.

**Proposal (in preference order).**

1. **A library-owned deletion tombstone written before the wipe begins**, with a
   documented read path — e.g. `Actor.is_deleted(actor_id)` or a tri-state (see
   DEL2). A tombstone is strictly better than "check whether the actor exists"
   for consumers, because it is *positive* evidence: a consumer can then treat a
   failed tombstone read as "proceed", which is the safe direction (see DEL2).
   It must live outside the deleted actor's own key space — a marker in the
   actor's own attribute bucket is destroyed by the very wipe it is meant to
   describe (the consumer has this exact pattern in their own code and it does
   not survive deletion).
   - **TTL must exceed provider retry windows.** Stripe retries a failed webhook
     for up to 3 days; other providers are similar. A tombstone that expires in
     an hour reopens the hole. ≥ 7 days is a reasonable default; the consumer's
     `AI_attributes` table already has DynamoDB TTL enabled on
     `ttl_timestamp`, so an attribute-backed tombstone needs no new
     infrastructure.
2. **Additionally, delete the actor row first** (move :452 to the top, keeping
   the in-memory `self.handle` for the remaining steps, which key off
   `self.id` and separate tables). This makes existence checks fail *closed*
   instead of open and costs nothing. It is hardening, not a substitute for (1):
   it turns the window from "reports live" into "reports missing", which is
   indistinguishable from a read failure until DEL2 is fixed.
3. Whichever is chosen, **state the contract in the docs**: what a consumer may
   assume about `get_by_id()` during and after deletion.

**Backend note.** In PostgreSQL only `property_lookup` carries
`ondelete="CASCADE"` to `actors.id`
(`actingweb/db/postgresql/schema.py:59-73`); `attributes`, `properties`,
`trusts`, `subscriptions` and the rest do not. So row-first deletion cannot rely
on cascade to do the wipe on either backend, and the explicit steps must still
run. Worth confirming the fix behaves identically on both.

---

## DEL2 — `get()` collapses "not found" and "could not determine"

**Severity: high — this is a correctness bug, not an ergonomics request.**

`DbActor.get()` on DynamoDB catches bare `Exception` and returns `None`
(`actingweb/db/dynamodb/actor.py:59-62`) — no log line at any level. The comment
says `# PynamoDB DoesNotExist exception`, but the clause also swallows
`ProvisionedThroughputExceededException`, request timeouts, credential errors
and `TableDoesNotExist`. `CoreActor.get()` turns the `None` into
`self.id = None` (`actingweb/actor.py:246-249`), and
`ActorInterface.get_by_id()` turns that into `None`
(`actingweb/interface/actor_interface.py:157-162`).

PostgreSQL has the same collapse, though it at least logs:
`actingweb/db/postgresql/actor.py:55-57`.

So a consumer receives `None` and cannot tell "this actor was deleted" from
"DynamoDB throttled me". Every guard of the form *skip this work if the actor no
longer exists* therefore also skips the work on a transient infrastructure
failure — silently, since nothing is logged on the DynamoDB path.

**Why this is severe rather than cosmetic.** The consumer's concrete case: a
Stripe `customer.subscription.created` / `invoice.payment_succeeded` webhook for
a paying customer. A guard that skips on `None` yields: skip the entitlement
write → return HTTP 200 → Stripe never retries → **the customer has paid and
never gets access**, with no error anywhere. The consumer discovered this while
designing the guard and inverted their whole approach because of it (see
"What the consumer is doing meanwhile"). Any other consumer writing the obvious
guard has the same bug and no way to know.

**Proposal.** Either:

- let infrastructure errors propagate (narrow the `except` to `DoesNotExist` /
  the PostgreSQL not-found case) so callers can fail loudly and let the provider
  retry; or
- expose a tri-state — `LIVE` / `DELETED` / `UNKNOWN` — ideally on the same call
  that answers DEL1's tombstone question.

At minimum, log the swallowed exception on the DynamoDB path; a silent `None`
from an infrastructure fault is undiagnosable from the outside. If the current
behaviour is deliberate for backward compatibility, please say so in the docs
next to `get_by_id()`, because the natural reading of "returns None if not
found" is that it means what it says.

---

## DEL3 — Actor-scoped writes have no referential integrity, and nothing says so

**Severity: medium (docs, plus an optional strict mode).**

`Attributes.set_attr()` (`actingweb/attribute.py:117`) is an unconditional
put on `(actor_id, bucket_name)`. Writing attributes for an `actor_id` that has
never existed — or that was deleted an hour ago — succeeds and creates rows.
There is no `require_actor` option and no statement in the docs that the actor
store has no referential integrity.

114 of the consumer's 117 orphan ids came from exactly this: a test fixture
generated `test-actor-<epoch>` ids without creating actors, and passing them to
code that wrote attributes left permanent rows. That is a consumer bug, but it
is a consumer bug the library's API shape invites: a store named "actor
attributes", reached through an object constructed with `actor_id=`, reads as
actor-scoped in the referential sense, not merely in the key-prefix sense.

**Proposal.** Document it plainly ("attribute and property writes do not
validate that the actor exists; an unknown `actor_id` creates rows that nothing
will clean up"). Optionally offer a strict mode for consumers who would rather
pay a read. The docs change is the valuable half — a consumer who knows this
writes their own guard; a consumer who assumes otherwise accumulates orphans
invisibly for months, which is what happened here (Feb–Mar 2026, found July).

---

## DEL4 — No post-wipe lifecycle event

**Severity: medium.**

`handlers/root.py:72-88` fires `actor_deleted` (:84) and *then* calls
`myself.delete()` (:86). There is no event after the wipe completes.

This forces consumers into DEL1's window by design. The hook is the only place
where the actor's data is still readable, so it is the only place a consumer can
learn *what* to clean up externally (e.g. read the stored subscription id in
order to cancel it). But acting there means the external side effect's
asynchronous callback races the wipe. There is nowhere to put "do this once the
actor is definitely gone".

**Proposal.** Add an `actor_deleted_complete` (name bikesheddable) event fired
after `myself.delete()` returns, receiving at least the `actor_id` — it cannot
receive a live `ActorInterface`, which is the point. Consumers can then split
the work: read what they need in `actor_deleted`, act in
`actor_deleted_complete`. That eliminates the race at the source for the common
"cancel an external subscription on deletion" pattern, independently of DEL1.

If a post-wipe hook is undesirable, documenting the ordering explicitly ("the
hook runs before any data is removed; the actor remains resolvable throughout")
would at least let consumers reason about it. Today the ordering has to be read
out of the source.

---

## DEL5 — Orphan detection belongs in the offline verifier

**Severity: low, purely additive.**

rc2 is already adding an offline table verifier
(`python -m actingweb.db.verify_tables`, per `2026-07-25-rc2-triage.md`) that
runs with an operator's own credentials. An orphan-row check is a natural
companion: enumerate actor ids, then report attribute / property / trust rows
whose `actor_id` is absent. Every consumer that has ever had a DEL1/DEL3
incident needs this, and each will otherwise write their own scan.

The consumer is implementing one; the classification is worth lifting because
its edge cases are not obvious:

- **An empty actor set must yield zero orphans.** If the actor-table read fails
  or returns nothing, "every row is orphaned" is the catastrophic reading.
- **System actors must be excluded unconditionally.** The consumer has
  `_actingweb_websocket` holding live registry data under an id that is
  deliberately not in the actors table; `_actingweb_oauth2` and
  `_actingweb_system` exist as real actors. Any id with the reserved prefix
  should be reported separately, never as deletable.
- **Reads must be consistent.** An eventually-consistent scan can show a
  seconds-old actor as absent. (Note the ordering interaction with DEL1:
  because `Actor.create()` writes the actor row first and `Actor.delete()`
  removes it last, an actor mid-create or mid-delete always still has its row —
  so *today's* ordering is what makes orphan classification safe. If DEL1 is
  fixed by moving the row deletion first, a mid-deletion actor's remaining rows
  will briefly classify as orphaned. That is fine for an operator tool run
  deliberately, but it is a reason to keep such a sweep out of any automated
  job, and worth a sentence in the docs.)

---

## What the consumer is doing meanwhile

Recorded so you can see which library behaviour is load-bearing for them, and so
nothing here is blocked on you being convinced:

- **Release gated on rc2 with DEL1.** No workaround shipped. Notably they
  *considered* an app-side tombstone and rejected it — it would leave every
  other consumer exposed and create a workaround to unwind later.
- **Their webhook guard keys on the tombstone (positive deletion evidence), not
  on actor absence** — precisely because of DEL2. A failed tombstone read
  proceeds to write (worst case: one orphan row, which their sweep finds); only
  a confirmed tombstone suppresses the write. If rc2's tombstone API can be read
  in a single point read, please say so — they budgeted for that.
- An absence-based check survives in exactly one place: their
  `subscription.deleted` handler, where skipping is a downgrade and therefore
  harmless.
- They are fixing their own DEL3 exposure (test fixture writing attributes for
  ids that were never actors) and adding a hard refusal that stops their test
  suite from ever pointing at the production table set again.

## What they will re-verify on rc2

Useful as an acceptance list, since it is the same surface that broke:

1. A deleted actor is reported deleted (or absent) by the documented call
   **throughout** the wipe, not just after it.
2. A tombstone outlives a 3-day provider retry window.
3. An infrastructure failure during that check is distinguishable from
   "deleted" — and does **not** present as "deleted".
4. Replaying a `customer.subscription.updated` for a deleted actor writes zero
   attribute rows.
5. Replaying `customer.subscription.created` for a **live** actor with the
   tombstone store made unreachable **still** writes the entitlement. This is
   the DEL2 regression test, and it is the one that matters most to them
   commercially.
