# A resumable, idempotent actor deletion

`Actor.delete` is a multi-step wipe behind a deletion tombstone: trusts,
subscriptions, properties, attribute buckets and finally the actor row, each
a separate write. A wipe that stalls or raises part-way leaves a
half-deleted actor, and several adoption follow-ups are symptoms of that one
cause (`thoughts/todo/adoption-fault-and-hygiene-followups.md`: H, I, J, K
and AW, among them the UNKNOWN tombstone read and the vouched actor carrying
a stalled tombstone).

Recorded by thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
("Not doing": the deletion wipe as a root cause), which left it for its own
plan.

What a plan for it would settle:
- a deletion job that can be resumed from the tombstone and is safe to run
  twice (each step idempotent, the row removed last);
- who resumes it: the next sign-in today finishes a stalled replacement, a
  `DELETE /<id>` retry, or a scheduled sweep;
- with `unique_creator`, when the creator is freed: the record goes only
  with the row, so a user who deletes their account and signs up again at
  once is refused while the wipe runs (the plan's unverified notes).
