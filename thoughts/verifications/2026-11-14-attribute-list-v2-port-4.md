# Verification: one list implementation for properties and attributes, and list diffs that reach a replica (re-run 4)

**Date:** 2026-11-14
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (not pushed)
**Commit:** 7955475

Scope: the iteration-3 delta (`60c7ca7..7955475`, the plan's Iterations
14-18) in depth, and the branch again through the built-in code review.

## Automated Check Results

- **Browser QA:** not run (no page changed).
- **Second opinion:** outside-voice (codex `exec -s read-only`, a
  fresh-context reviewer) on the delta: 10 findings; built-in `/code-review`
  high on the branch: 10 findings.
- ruff, pyright, `verify_groups.py`: pass.
- `make test-all-parallel` on `7955475`'s tree: **DynamoDB** 7,438 passed
  (one parallel failure, `test_verification_fetch.py::test_a_full_pool_refuses_at_once`,
  passed three times sequentially), **PostgreSQL** 7,209 passed.
- docs build: pass.
- **Emm's suite on `7955475`** (environment 9): PostgreSQL 3 failed / 7,405
  passed, DynamoDB lane 3 failed / 54 passed: unchanged (the baseline's, plus
  Emm's date-dependent `test_trial_state_pure` case).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-14-attribute-list-v2-port-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| OV5 overlap (and OV1, OV2) | Fixed by storing one subscription per name; the skip has holes (2, 3 below) | Iteration 14; `WD15` |
| OV3 dropped batch's deletes | Fixed for whole-target subscriptions; read at any level (8) | Iteration 15 |
| OV4 callback during the rebuild | Fix ineffective: cached read (1) | Iteration 15 |
| OV6, CR3 revocation scope | Fixed; the fallback deletes too much / reports too little (5, 6) | Iteration 17 |
| OV8, OV9, OV11, CR1, CR4, CR6, CR10, claim note | Fixed | Iterations 16, 18 |
| CR2 subtarget array baseline | Fixed by a guess that misreads scalar arrays (4) | Iteration 16 |

## Issues Found

1. **High, peer-reachable.** The rebuild's "recorded changed" check reads a
   `Subscription` built before the baseline, whose `get()` serves a cached
   copy: the check never fires, and "never backwards" writes the baseline's
   sequence over a later one (`subscription_manager.py`, `current =
   sub_obj.get() or {}`; `subscription.py:27-29`).
2. **High.** A skipped subtarget rebuild still adds its subtarget to the
   stale names and deletes the covering subscription's copy
   (`elif sub.subtarget and not sub.resource and sub.subtarget not in carried`).
3. **Medium.** The skip counts a whole-target subscription with granularity
   `none` (never pushed to), and the covered subscription's data is lost when
   the covering one is deleted; nothing rebuilds it.
4. **Medium, peer-reachable.** A scalar whose value is an array is stored as
   a list at subscribe and resync, then loops rebuilds; the callback handler
   has its own wrap (code review 3); a probe would need to fail safe (code
   review 4).
5. **Medium.** The shared-bucket revocation fallback reports nothing when the
   grant changed without dropping a pattern.
6. **Medium, peer-reachable.** The fallback deletes scalars too, which 3.15
   did not: another target's scalars matching a dropped `*`.
7. **Medium, peer-reachable.** The insert clamp hides a short replica the
   diff's `length` would reveal.
8. **Low, peer-reachable.** `_deleted_names` reads a subtarget-level diff's
   keys as replica names.
9. **Low.** A skipped resync settles an owed rebuild; the plan said it does
   not (wording).
10. **Codex.** `request_resync` keeps a whole-target record after sending
    that subscriber a full resync; a later resume then sends it a
    subtarget-only resync.
- **Code review:** 1 an empty subtarget baseline (a failed fetch) deletes the
  replica's list and settles; 2 = 8; 3, 4 = 4; 5 an item the replica cannot
  store is an error, not out of step; 6 the converter counts a pre-3.16
  sibling `<name>-#...`'s rows as stray and refuses for ever; 7 the
  converter's check-then-act (accepted before); 8 `--delete-damaged-replicas`
  leaves a partial list to the next append; 9 read cost (accepted); 10 the
  revocation docstrings say whole-target only.

## Remaining Tasks

- [ ] Iterate on 1-10 and code review 1, 5, 6, 8, 10.
- [ ] Re-run this verification.

## Overall Assessment

Not clean. Finding 1 is a regression of iteration 3 that its test double hid
(the double re-read where the real class caches); the skip of iteration 14
has two holes (a subtarget sweep, a covering subscription that goes away);
the array-baseline fix traded one misread for another.
