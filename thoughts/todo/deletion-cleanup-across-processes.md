# Application cleanup when another process finishes a deletion

**Filed:** 2026-11-22, from a consumer's production report on 4.0.0rc2
(`thoughts/research/2026-11-22-emm-4-0-rc2-production-observations.md`,
items 7 and 10). Checked against `master` at `bee0eb5`. Additive; after
4.0.0.

## The two hooks share nothing durable

`actor_deleted` runs once: `finish_deletion` sets `hook_fired` on the
tombstone after it (`deletion_finish.py:176`). A deletion finished later by
another process, or by `actingweb-deletions resume` (which passes
`hooks=None`, `maintenance/deletions.py:254`, and says so in its output),
does not run it again. `actor_deleted_complete` receives the actor id and
the tombstone's `hook_kwargs`, which only the library writes (the reason of
a replacement, `oauth2.py:2101`).

So an application that reads something in the first hook to act on in the
second (the reporting consumer: a payment subscription to cancel) needs its
own durable record. Asked: a tombstone field the first hook can write and
the second receives.

Needs a design: how the hook writes it (a return value, or a call on an
object passed to it), a size limit, and what the operator command does with
it, since it runs no hooks at all.

The reporter's own limits on the ask: such a field would not replace its
record by itself, because `actingweb-deletions resume` runs no hook, the
tombstone expires after 30 days (`DELETION_TOMBSTONE_TTL`), and a provider
token has to be cleared once revoked, which a field the second hook only
receives cannot record. A design that leaves those three open buys the
consumer nothing.

## A cleanup job cannot tell a finished deletion from a pending one

`deletion.read_tombstone` is in the module's `__all__` and in no page of
`docs/`. `get_deletion_status` answers `DELETED` both for a finished
deletion and for one whose wipe has not run; the tombstone's `finished_at`
tells them apart, and `docs/reference/actor-deletion.rst` does not mention
it. A daily cleanup needs that difference.

The approach is a public method that returns a record, not a documented
tombstone shape. A first design (`ActorInterface.get_deletion_record()`
with the states pending, finished and unrecorded) was dropped from
`plans/2026-11-23-emm-4-0-rc2-production-observations.md` before it was
built, because it described the tombstone and not the actor. What a design
has to answer first:

- **A tombstone does not say whether the actor exists.** A live actor can
  carry a reason-less tombstone (`oauth2.py`, the sign-in that leaves a
  vouched actor "untouched"; `maintenance/deletions.py`, "the tombstone of
  a live actor the operator judges stray"), and a deleted actor can have
  none (`deletion.py`, a tombstone write that failed: "Deletion will
  proceed"; or its 30-day retention ended). Define each answer against the
  actor row, or carry the row's presence in the record.
- **"Pending" can be permanent for a finished wipe.** `mark_finished` folds
  a fault after the actor row is gone, leaving a reason, no `finished_at`
  and no TTL. A job that waits for "finished" waits forever.
- **"Finished" does not mean a hook ran.** `finished_at` is written before
  `actor_deleted_complete`, and `actingweb-deletions resume` and a
  programmatic delete fire no hooks. Nothing on the tombstone records the
  completion hook.
- **A reason-less row can be finished** (`finish_unleased` has no
  resumable test), so the precedence is: a truthy `finished_at` first,
  then resumable, then neither. `finished_at` can be present and `None`,
  or unparseable.
- **Whether the record carries the reason.** A replaced actor reads the
  same as a user deletion without it; the security evaluation wanted the
  stored reason and hook kwargs kept out.

Until then the reporting consumer calls `read_tombstone` undocumented.
