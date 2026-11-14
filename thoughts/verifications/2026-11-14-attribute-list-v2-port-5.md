# Verification: one list implementation for properties and attributes, and list diffs that reach a replica (re-run 5)

**Date:** 2026-11-14
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (not pushed)
**Commit:** 886389f

Scope, by decision (advisor, 2026-11-14): the delta of iterations 4-5 only
(`92a4ae8..886389f`, the plan's Iterations 19-25), with one consolidated
accepted list; no full-branch code review this round. Stop rule: a
peer-reachable Medium in iteration-written code ends the loop and goes to
the owner.

## Automated Check Results

- **Browser QA:** not run (no page changed).
- **Second opinion:** outside-voice (codex `exec -s read-only`, a
  fresh-context reviewer) on the delta: 4 Medium, 2 Low (claude); 3 Medium
  per codex that the reviewer rated Low.
- ruff, pyright, `verify_groups.py`: pass.
- `make test-all-parallel` on `886389f`'s tree: **DynamoDB** 7,457 passed,
  **PostgreSQL** 7,226 passed.
- docs build: pass.
- **Emm's suite on `886389f`** (environment 9): PostgreSQL 3 failed / 7,405
  passed, DynamoDB lane 3 failed / 54 passed: the baseline's failures plus
  Emm's date-dependent `test_trial_state_pure` case, as on every run.
- The rebuild's sequence check runs against the real `Subscription` on
  DynamoDB Local (`TestRealSubscription`); it fails on `7955475` and passes
  now.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-14-attribute-list-v2-port-4.md

| Issue then | Status now |
| --- | --- |
| 1 cached sequence read | Fixed, tested against the real class |
| 2 skipped subtarget sweep | Fixed |
| 3 covering subscription gone / never pushed | Fixed with two mechanisms, one wrong (finding 2 below) |
| 4 scalar arrays read as lists | Fixed at the fetch; one caller bypasses it (1) |
| 5, 6 revocation fallback | Fixed |
| 7 insert clamp | Reverted (the SDK's length is advisory); accepted |
| 8, 9, 10, code review 1, 5, 6, 8, 10 | Fixed; code review 1's rule over-reaches (4), 8's over-marks (3) |

## Issues Found

1. **Medium, peer-reachable.** The sync paths' "every diff was a duplicate,
   fetch a baseline" branch (`subscription_manager.py:1340` and `:2266`)
   reads the subtarget itself, not through `_fetch_and_transform_baseline`,
   so a list's items arrive bare and are stored as a scalar.
2. **Medium, peer-reachable.** Excluding granularity `none` from covering
   (iteration 20) brings the doubled append back: a `none` subscription is
   still polled by `sync_peer` into the same replica.
3. **Medium, operator-triggered.** `--delete-damaged-replicas` owes the list
   to every subscription to the peer; an unrelated subscription's rebuild then
   finds it not carried and deletes it again, and nothing owes it after.
4. **Medium, peer-reachable, liveness.** "Empty subtarget baseline = failed"
   (iteration 23) catches an empty list, a falsy value and a text scalar the
   proxy answers as `{}` or `None`: the rebuild then fails the same way and
   stays owed for ever; a number or boolean raises inside the rebuild.
5. **Low.** The 404-means-gone path: a grant refusal is 403 and does not
   reach it; a missing actor and a read hook hiding the value do (the old
   code overwrote with `{}` there).
6. **Low.** `_owe_covered_rebuilds` runs after the remote and local deletes;
   a trust purge or `Subscription.delete()` bypasses it.
- Codex, rated Low by the reviewer: a folded fault while marking covered
  rebuilds; a stale `known_list` after a list became a scalar array.
- Unverified: a 3.15 publisher's inline bare-array resync; `""` deleting at
  target level when a publisher hook answers `""`.

## Remaining Tasks

- [ ] Owner decisions (below) before any further iteration.

## Overall Assessment

Not clean, and not converging: every finding of this round is in code an
iteration wrote, and each round's mechanisms (the skip, the probe, the
empty-baseline rule, the owed-rebuild markers) opened the next round's
holes. The remaining problems share a root the receiver cannot fix alone:
a subtarget baseline does not say on the wire whether it is a list, an
empty value or a failure, and a replica does not record which subscription
stored a name. Both are wire or storage-model changes that belong to a
decision, not to another iteration. The decisions are in the plan's
"Open decisions" note and in the report to the owner.
