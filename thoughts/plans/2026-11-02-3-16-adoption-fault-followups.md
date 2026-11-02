---
status: proposed
---

# Implementation Plan: 3.16 adoption and fault-contract follow-ups

**Date:** 2026-11-02
**Research:** `thoughts/todo/adoption-fault-and-hygiene-followups.md`; the owner's decisions were taken on 2026-11-02. They were recorded first in `thoughts/plans/2026-11-02-3-16-owner-decided-followups.md`, which keeps the first block.
**Branch:** its own `release/3.16.0-...` branch, cut after the first block's PR merges. One PR, a commit per phase.

## Overview

The second block of the owner-decided 3.16 follow-ups. It touches the sign-in and deletion paths throughout and has one Breaking change (`is_suspended`). Phases, tests and the evaluation passes come when `/create_plan` (or `/update_plan`) completes it.

## Decisions Made (owner, 2026-11-02)

- **AW (a tombstone on a live vouched actor):** detect first, then finish. Three steps, in order:
  1. Confirm the tombstone clear on a fixed-id create (`get_attr_strict`). A fault fails the create.
  2. A repeated `DELETE /<id>` finishes the wipe without firing `actor_deleted` again.
  3. Only then may a sign-in on a tombstoned live actor finish the wipe.

  Sequence this with `todo/resumable-actor-deletion.md`.
- **BG (the session at the verification click):** the click issues the web session or the SPA token, as the OAuth callback would. The form-replaces-factory alternative (BV) is not taken.
- **The `force_email_prop_as_creator` rewrite at load:** `Actor.get` does not rewrite the creator of an unvouched actor; adoption decides.
- **The lost successor mapping:** write the old-to-new mapping into the successor's `_internal` before creating it. The next sign-in that completes the adoption fires `actor_adopted` with the right old id.
- **The summary reads:** on a fault, the `actor_adopted` summary reports the counts as unknown (`None`), not 0, and the log says so. The adoption still proceeds.
- **`purge_relationships`:** read trusts and subscriptions once each, and pass them down.
- **The redundant replace-path cleanup:** when the actor is already deleted, `delete_client` removes only the global client index row.
- **BN:** a nested hand-off merges the incoming `carried`. Add a two-step hand-off test.
- **BK** (flag off): the strict `get_by_creator` and the sibling sweep drop rows whose normalised creator differs from the query.
- **BL** (flag off): the sweep skips a sibling that is already tombstoned.
- **BP:** a replacement scans the SPA token buckets once, for the victim and its siblings together.
- **BQ:** both SPA completion paths and the web callback call one shared resolve-adopt-or-create helper.
- **The revocation cleanup after a fault:**
  - The permission callback deletes the revoked peer data first, with strict reads, and stores the new permissions after.
  - A fault answers 503, so the retried callback still sees the revocation.
- **`clear_all_state_for_peer`:** strict read. A fault raises `DbError`, so the trust deletion answers 503 and is retried.
- **One read-and-classify helper** for `Actor.get_from_creator`, `oauth2._factory_siblings` and the successor step. It returns the pick and the siblings from one read.
- **The deliberate folds** (`callback_processor` `handler(cb)` at-most-once, and the owner's factory sweep) are documented in the hooks reference and the fault-contract docs.
- **O2 ordering windows**, all three reordered, each with a fault test:
  - the replacement's pre-reads run before its token revoke;
  - `Actor.delete` reads its lists once, before `actor_deleted`;
  - the OAuth callback and the email-form completion validate before writing.
- **The post-commit folds:** diff registration only.
  - A fault after the property write raises `DbError`; the write stays.
  - The caller sees 503, so the subscriber's gap is not silent.
- **`DeletionStatus.UNKNOWN`:** fail closed in `handlers/mcp.py` and `oauth2._race_winner` too, answering 503. That is the same rule as K.
- **DynamoDB `DbSubscription.modify`:** an `UpdateItem` of only the given fields, so it never writes back a stale `seqnr`.
- **The resync failure:** keep a per-cycle record of which subscribers were resynced. A retry of `resume_subscriptions` re-sends only to the ones that missed, and their suspension window stays until they succeed.
- **The K4 leftovers, all four chosen:**
  - **The three remaining `oauth_provider` bookkeeping writes:** a failure is logged and folded, so it does not fail the sign-in, as plan entry 27 did for the first one.
  - **`SubscriptionManager.is_suspended()`:** it raises `DbError` on a fault. **Breaking**, so it needs a CHANGED entry and a migration-guide line.
  - **The create rollback:** it also deletes the actor's `_internal` bucket.
  - **A replacement with no vouched actor:** read the victim's lists once, and bound the ranked creator prefix.
- **`fanout.py`'s breaker:** correct the comment (per process), and say so in the deployment guide. Shared breaker state is not taken.

## What We're NOT Doing

- **The post-commit folds for the verification email and the logout provider-token clear:** the owner kept them as they are. They stay in the adoption todo.
- **BV (the free-text form replacing a factory actor):** not chosen.
- **A shared, cross-process fan-out breaker:** not chosen.

## Phases

To be written by `/create_plan`, with the evaluation passes.
