# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), eighth run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-30-creator-record-invariant-audit.md (third addendum part)
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 78-79)

**Scope:** Iterations 78-79 (the vouch bound to its address) and the
security pass of the whole branch. A13 and B13 are closed for provider
sign-ins; the emailed-link proof path and the SDK rename were not adapted
to the binding, so the plan keeps bare `status: done`.

## Automated Check Results

- **Full tier** (`scratchpad/full24.sh`, after 78-79): ruff, format (449
  files), pyright 0/0/0; fast tier 3272 passed, 23 skipped;
  `verify_groups` 51; DynamoDB 4390 passed, 37 skipped; PostgreSQL 4245
  passed, 182 skipped; docs build succeeded.
- **Built-in security review** (the skill, whole branch): nothing above its
  0.8 confidence bar. Below it: enumeration through the 409 (the factory
  already reveals it), `choose_keep` without the creator (operator tool).
- **Second opinion:** Codex (`gpt-5.6-sol`, read-only, unsandboxed, stdin
  closed) and a fresh-context Claude reviewer: A14 (High), B14 (Medium),
  C14 (Low). No vouched-marker write without its address was found; the
  own-email fallback, the trustee handoff, provider-id creators and the
  `force_email_prop_as_creator` rewrite keep their answers.
- **Browser QA:** not run (`examples/demo/.env` absent).

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-7.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A13 restore after the rename | Fixed by binding | entry 78; `TestConcurrentRestore` (both orders, pre-3.16) |
| B13 clean-in-place vouch during a rename | Fixed by binding | entry 78; `TestVouchBoundToItsAddress`; entry 79 for the passphrase |

## Remaining Tasks

- [ ] Fix A14, B14, C14 with tests; re-verify; `/commit`; PR 2.

## Issues Found

### A14. The emailed link vouches the creator at click time, not the address it was sent to
**Severity:** High
**Description:** `actingweb/handlers/oauth_email.py:221` runs the adoption
with `verified_by_email=True` and never compares the actor's creator with
the address the token went to; the clean then binds `existing.creator`
(`actingweb/oauth2.py:2523`). With the default `force_email_prop_as_creator`
off (`actingweb/interface/app.py:76`), a user who signs in through the
email form as A, renames the actor to V over `PUT /<id>/trust/trustee`,
then clicks the link received at A gets the actor vouched for V. The
victim's sign-in for V adopts it as is, with the planted properties. The
clean wipes the attacker's sessions and passphrase, so this plants data
rather than taking over.
**Recommendation:** refuse when the creator is not the address the link
was sent to.

### B14. `ActorInterface.modify_creator` without `unvouch` reads as unvouched after the rename
**Severity:** Medium
**Description:** `actingweb/interface/actor_interface.py:439` `return
self._core_actor.modify(creator=new_creator)` leaves `vouched_creator` on
the old address, so the binding makes the renamed actor unvouched and the
next sign-in for the new address cleans it (tokens, trusts, subscriptions
purged), against the docstring ("the application vouches for
``new_creator``") and the migration guide.
**Recommendation:** move the recorded address with the rename.

### C14. A restore can write a stale marker over a clean that landed meanwhile
**Severity:** Low
**Description:** `actingweb/actor.py:914` `elif not
self._restore_marker(store, previous_marker, original):` writes the old
marker unconditionally; after a clean rotated the passphrase, a stale
handle's change fails (entry 79's condition) and its restore unvouches the
just-cleaned actor. Errs safe, but the next sign-in cleans it again.
**Recommendation:** restore only while the marker reads `creator_changed`.

## Overall Assessment

The binding (78) closes A13 and B13, and the security review found nothing
above its bar. Two flows were not adapted to it: the emailed-link proof
(High: it proves one address and vouched another) and the SDK rename the
application vouches for (Medium: a regression from 78). Both, and C14, are
small.
