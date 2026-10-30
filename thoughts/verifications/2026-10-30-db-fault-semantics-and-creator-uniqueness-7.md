# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), seventh run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md,
thoughts/research/2026-10-30-creator-record-invariant-audit.md
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 76-77)

**Scope:** Phases 3-4 and Iterations 76-77, plus a security pass over the
branch's sign-in and creator paths. B12 is fixed. Entry 76 does not close
A12, and the same flaw exists in the clean-in-place sign-in, so the plan
keeps bare `status: done` with no `verified:` link.

## Automated Check Results

The full tier ran on 2026-10-30 (`scratchpad/full23.sh`) after the last
code change of 76-77.

- **Browser QA:** not run (`examples/demo/.env` absent).
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed,
  stdin closed, output in the scratchpad) and a fresh-context Claude
  reviewer. Two Mediums (A13, B13); codex found nothing else of Medium or
  higher on the sign-in paths, and no `DbError` folded into absence there.
- **Built-in code review / security review:** not run in this round.
- ruff, format (449 files), pyright: pass, 0/0/0.
- Fast tier: 3270 passed, 23 skipped. `verify_groups`: 51 documented.
- DynamoDB: exit 0, 4386 passed, 37 skipped.
- PostgreSQL: exit 0, 4242 passed, 181 skipped.
- `sphinx-build -W`: succeeded.

## Phase Verification

### Phase 3 - VERIFIED
- `actingweb/maintenance/unique_creators.py:687-698` - the orphan pass's
  separate `try` (entry 77). Correct: `repaired` counted once, a holder
  failure counted as an error with its own message.

### Phase 4 - ISSUES FOUND
- `actingweb/actor.py:862` - entry 76's second `creator_changed` write.
  See A13.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-6.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A12 restore leaves the actor vouched | Still open | entry 76 narrows it; A13 |
| B12 orphan log | Fixed | entry 77; `test_b12_*` |

## Remaining Tasks

- [ ] Replace entry 76 with a mechanism that holds in every order (A13),
  and close B13 the same way.
- [ ] Browser QA once a demo `.env` exists.
- [ ] Re-verify, then `/commit` and open PR 2.

## Issues Found

### A13. Entry 76 does not close A12
**Severity:** Medium
**Description:** `actingweb/actor.py:895` `elif not
store.set_confirmed("auth_method", previous_marker or None):` can still
land after `:862`'s second `creator_changed` write: A re-reads the
original creator, B renames and writes its marker twice, A's restore lands
last and reads back as vouched under the victim's address. `:862-874` also
returns True when its own write is contradicted. The test injected the
restore before the rename only.
**Recommendation:** a mechanism that does not depend on write order.

### B13. Clean-in-place vouches unconditionally while a rename lands
**Severity:** Medium
**Description:** `actingweb/oauth2.py:2501` `if not store.set_confirmed(
"auth_method", f"{provider_name}_oauth2" ...)` writes the vouched marker
last and never re-reads the creator. The attacker owns the actor (it was
squatted under an address they control), signs in as that address, and
sends `PUT /<id>/trust/trustee {"creator": victim, "trustee_root": ...}`
authenticated before the clean's rotation; the rename lands before the
vouch. Final: the victim's address, vouched, the attacker's `trustee_root`
(and on DynamoDB with the flag off a stale handle's save also writes the
old passphrase back, `actingweb/db/dynamodb/actor.py:186-188`). Needs
`force_email_prop_as_creator` off or no stored email. The clean predates
the branch.
**Recommendation:** as A13: the class is "a vouched marker written after a
rename".

## Overall Assessment

77 is correct; 76 is a write-again patch on what is a compare-and-set
problem, and the clean-in-place sign-in has the same flaw. Both need one
mechanism that holds in every order before the branch can be committed.
