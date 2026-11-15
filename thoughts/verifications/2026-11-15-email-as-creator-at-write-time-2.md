# Verification: "creator equals stored email" enforced where the email is written (re-run 2)

**Date:** 2026-11-15
**Plan:** thoughts/plans/2026-11-06-email-as-creator-at-write-time.md
**Research:** thoughts/research/2026-11-06-actor-load-cost-and-email-as-creator.md
**Branch:** release/3.16.0-email-as-creator-at-write-time (not pushed)
**Commit:** `515f09a`

Scope: the plan's Iterations entries 1-6 (after the first verification) and
the narrow check of them. Everything else is as the first verification
found it.

## Automated Check Results

- **Browser QA:** N/A (no UI phases).
- **Second opinion**, narrow, on the iteration diff (codex and a
  fresh-context reviewer): one High (the eviction decided "vouched for the
  address" through the stored email, which an application can write during
  a handoff), two Medium (a holder classified, then renamed unconditioned;
  the eviction committed before the handback's retry), three Low. The High,
  one Medium and two Lows are fixed in the same commit; the rest are
  accepted (below). No regression in fixes 3 to 5.
- ruff, ruff format, pyright: clean. `verify_groups.py`: pass.
- `make test-all-parallel` on the final tree: **DynamoDB** 7,601 passed,
  211 skipped, 2 xfailed; **PostgreSQL** 7,372 passed, 440 skipped,
  2 xfailed.
- Docs build: pass.
- The handback tests on their own after the narrow-check fixes:
  `TestTheEmailWriteMeetsAHeldAddress`, 8 passed on each backend.
- **Emm's suite on `515f09a`** (environment 9; the library worktree at
  `515f09a`; `creator-to-email` dry run first: 1 scanned, nothing to move,
  the marker already written): **PostgreSQL** 3 failed, 7,405 passed,
  14 skipped, 179 deselected; **DynamoDB lane** 3 failed, 54 passed. The
  `a98690a` baseline's failures by name, nothing new or gone. Logs:
  `../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-515f09a.log`.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-15-email-as-creator-at-write-time.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A trustee handoff stranded by an anonymous create | Fixed (owner: the handback frees an unvouched holder) | `actingweb/actor.py` `_evict_for_handback`; `tests/integration/test_unique_creator_states.py` `test_a_handback_frees_the_address_from_an_unvouched_holder`, `test_a_vouched_holder_still_answers_conflict`, `test_an_email_written_during_the_handoff_evicts_nothing`, `test_an_actor_with_no_recorded_address_evicts_nothing`, `test_a_holders_other_email_is_kept` |
| 2. The write path's vouch check, marker-only | Fixed (owner: bound to the current creator) | `actingweb/creator_sync.py` `is_vouched_store(fresh, current)`; `tests/test_creator_follows_email.py::TestTheLoad::test_a_direct_creator_change_is_not_undone` |
| 3. Four docs claims not exactly true | Fixed | `docs/migration/v3.16.rst` "The creator follows the stored email"; `CHANGELOG.rst` CHANGED |
| 4. A same-creator write lowercased a mixed-case creator | Fixed | both backends' `rename_creator`; `tests/integration/test_rename_creator.py::TestLegacyMixedCase` |
| 5. A dry run released stale records | Fixed | `_holder(..., repair=apply)`; `test_a_stale_holder_does_not_block` |
| 6. The SDK rename's read-back checked only the creator | Fixed | `actingweb/interface/actor_interface.py`; `test_a_fault_on_a_rename_to_the_same_creator_is_not_success` |
| 7. `marker=None`; the linked write's cost | Accepted as-is (recorded in the plan) | Phase 2 notes |
| 8. `_holder` without a return type | Fixed | `actingweb/maintenance/email_as_creator.py` |

## Security property demonstrated

**A handback evicts only for the address a sign-in proved:**
`test_an_email_written_during_the_handoff_evicts_nothing` writes another
address into the handed-off actor's stored email and asserts the handback
to it raises `CreatorTaken` and leaves its holder holding it;
`test_a_handback_frees_the_address_from_an_unvouched_holder` asserts the
handback to the recorded address renames a `factory` and an
`email_unverified` holder to its `#dup-` value.

## Remaining Tasks

- [ ] Note for Emm's adoption work (not a library change): its role needs
      `dynamodb:ConditionCheckItem`.
- [ ] Open the PR.

## Issues Found

None open at Medium or above. Accepted, Low, recorded in the plan's
Iterations entry 1: the eviction commits before the handback's retry (an
address taken again in between leaves the holder renamed and the handback
answering 409, logged); after a deliberate `Actor.modify(creator=X)`, an
application that writes the email `X` and then `Y` moves the creator to `Y`.

## Overall Assessment

Clean by the stop rule: no peer-reachable finding at Medium or above
remains, the narrow check's High is fixed with a test that pins it, the
Full tier is green on both backends, and Emm's suite shows only its
baseline. Ready for the PR.
