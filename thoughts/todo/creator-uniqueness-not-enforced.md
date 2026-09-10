# TODO: Creator uniqueness is not enforced, only logged

**Status:** Open. Split out 2026-09-10 from
`thoughts/plans/2026-09-10-oauth-email-form-writes-to-existing-actors.md`
(Phase 3, Decision 5: "Duplicate creators: log, do not constrain").
**Filed by:** Greger Wedel (with Claude), during 3.14.5.
**Record:** the plan above and
`thoughts/verifications/` once the plan is verified hold the shipped half —
`Actor.get_from_creator()` now logs a WARNING (creator + sorted candidate
ids) when more than one actor shares a creator. This file says only what is
still owed.
**Severity:** Low today, real. Creation is check-then-create: a lookup by
creator followed by an unconditional put, with no unique constraint backing
it on either database. Two concurrent OAuth logins (or two concurrent
`POST /oauth/email` free-text submissions before this plan's 409 refusal)
racing the same new creator can both pass the "does not exist" check and
both create an actor. `Actor.get_from_creator()` resolves the resulting
duplicate silently to the lowest id.

## What is still owed

- **PostgreSQL:** a unique index on `lower(creator)` (or on `creator` plus a
  documented case-normalisation rule — the two lookup paths already
  disagree on this, see the ``docs/quickstart/configuration.rst`` note this
  plan added).
- **DynamoDB:** no unique-constraint primitive exists on the actor table as
  currently keyed; needs either a marker-item transaction (create the actor
  row and a `creator -> actor_id` marker item in one `TransactWriteItems`
  call, conditioned on the marker not existing) or a design note explaining
  why that is not worth it for this table's write pattern.
- **Backfill decision for existing duplicates.** The WARNING this plan
  shipped makes existing duplicates visible in logs for the first time;
  decide what happens to actors already sharing a creator before a unique
  index can be added (a unique index cannot be created over data that
  violates it).
- Whether enforcement is opt-in (a `with_unique_creator()` toggle, mirroring
  the existing config flag referenced in
  `docs/guides/authentication.rst`) or unconditional.

## Constraints inherited from the 3.14.5 plan

- The WARNING added in Phase 3 costs no extra DB read (the candidates are
  already in memory from `get_by_creator`) and is not throttled — a
  once-per-process flag would hide a second duplicate pair and make log
  assertions order-dependent. Keep both properties in whatever enforcement
  replaces it.
- `get_by_creator`'s own N+1 (`AllProjection` GSI query, then a consistent
  `GetItem` per candidate) is pre-existing and out of scope here too.
