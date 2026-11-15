# Verification: one list implementation for properties and attributes, and list diffs that reach a replica (re-run 2)

**Date:** 2026-11-13
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (not pushed)
**Commit:** 65dfad5

Scope: the iteration-1 delta (`f994293..65dfad5`, the plan's Iterations
1-7) in depth, and the branch again through the built-in code review.

## Automated Check Results

- **Browser QA:** not run (the delta changes no page; the web-UI form routes
  are exercised over HTTP by `tests/test_list_diff_publishers.py` and
  `tests/integration/test_list_diff_replica.py`).
- **Second opinion:** outside-voice (codex `exec -s read-only` and a
  fresh-context reviewer) on the delta: 9 findings; built-in `/code-review`
  high on the branch: 10 findings. Security review: not re-run (the delta
  adds no input handling or data access beyond what the first run cleared).
- ruff check, ruff format, pyright: pass (0 errors, 0 warnings).
- `verify_groups.py`: pass.
- `make test-all-parallel`, **DynamoDB**: 7,406 passed, 208 skipped,
  2 xfailed (parallel, on the tree committed as `65dfad5`).
- `make test-all-parallel`, **PostgreSQL**: 7,178 passed, 436 skipped,
  2 xfailed (same).
- docs build (`-W`): pass.
- **Emm's suite on `65dfad5`** (environment 9): PostgreSQL 3 failed / 7,405
  passed / 14 skipped / 179 deselected, DynamoDB lane 3 failed / 54 passed:
  the same failures as the run on `6d1387c` (the baseline's, plus Emm's
  date-dependent `test_trial_state_pure` case).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-13-attribute-list-v2-port.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| OV2 `remove` by value diverges with duplicates | Fixed, with a gap (finding 2, 3 below) | Iteration 1; `tests/test_replica_receiver.py::TestVerificationFindings` |
| OV4 list-scoped resync resets a target-level subscription | Fixed in `request_resync`, still open in `resume_subscriptions` (finding 1) | Iteration 2 |
| OV1 bulk stopped part way announces nothing | Fixed | Iteration 3; `test_a_batch_stopped_part_way_announces_what_landed` |
| CR5 rebuild deletes another target's data | Half fixed (finding 4) | Iteration 4 |
| CR2 refused baseline name loops rebuilds | Fixed | `test_a_refused_list_name_in_a_baseline_is_not_a_failure` |
| OV5 resync fault turns a committed POST into 503 | Fixed (finding 9: the miss may go unrecorded) | `test_a_resync_fault_does_not_fail_a_committed_batch` |
| CR1 `set_list` checks before `clear()` | Fixed | `test_a_baseline_repairs_a_list_in_both_layouts` |
| CR6 unwrap of a one-key object | Fixed at the receiver; the publisher half regresses old receivers (finding U1) | Iteration 4 |
| CR3 converter race | Narrowed (finding 8) | `test_a_late_converter_does_not_recreate_a_row_deleted_since` |
| OV3 async misses not recorded | Documented | CHANGELOG, `request_resync` docstring |
| OV7 list created before the hook | Fixed | `test_a_list_the_post_hook_refuses_is_not_created` (3 routes) |
| OV6 rank-addressed update dropped | Fixed | `test_a_rank_addressed_web_edit_carries_the_position` |
| CR7 pruned batch after a failed rebuild | Changed, not fixed (finding 6) | Iteration 4 |
| OV8, CR8, CR10 | Fixed | Iterations 5, 7 |
| CR9 old-layout probe read | Accepted (todo) | `attribute-list-old-layout-removal.md` |

## Issues Found

Peer-reachable means a peer or REST client can trigger it.

1. **High, peer-reachable.** `resume_subscriptions` still sends a
   subtarget-only resync to whole-target subscriptions, and re-sends the
   whole-target misses `request_resync` records under `target:subtarget`
   (`actingweb/actor.py`, `resync_subtarget = subtarget if subtarget else sub_subtarget`).
2. **Medium, peer-reachable.** A duplicated item's delete delivered twice (an
   overlapping subscription) deletes the surviving copy: a unique match is
   deleted without checking whether the delete was applied
   (`actingweb/remote_storage.py`, `if len(matches) == 1:`).
3. **Medium, peer-reachable.** A delete whose `old_item` is absent is a
   no-op even when the replica drifted (`if not matches: ... "noop": True`).
4. **Medium, peer-reachable.** A `properties` rebuild deletes names another
   target's auto-stored subscription wrote into the shared `remote:<peer>`
   bucket (`actingweb/interface/subscription_manager.py`, the stale sweep).
5. **Medium, peer-reachable.** Revocation cleanup deletes another target's
   names from the same bucket (`actingweb/replica_revocation.py:102`,
   `revoked_replica_names`).
6. **Medium, peer-reachable.** A value-addressed `update` whose `old_item` is
   absent (or ambiguous, none at `index`) overwrites the row at `index`
   instead of reporting out of step (`actingweb/remote_storage.py`, the
   `update` branch).
7. **Medium.** `rebuild_subscription` settles `rebuilt=True` from a fresh
   read, clearing a mark a concurrent callback set after the baseline, and a
   callback applied during the rebuild is overwritten by the older baseline
   (`actingweb/interface/subscription_manager.py`, the final `settle_rebuild`).
8. **Medium.** A deleted list's stored diffs, its `delete_all` included, are
   filtered as objects once the name is no longer a list: an exclusion such
   as `notes/*` withholds the delete (`actingweb/actor.py`, `_names_a_list`
   at serve time).
9. **Low-medium.** A lost mark's fallback leaves `claimed_seq` above
   `last_seq`: redeliveries answer in progress until the lease runs out
   (`actingweb/callback_processor.py`, `_mark_or_owe`).
10. **Low.** A subtarget callback carrying the `{"_list": true}` baseline form
    is unwrapped and stored as a scalar (`actingweb/remote_storage.py`,
    `_wraps_list` used on the callback path).
11. **Low.** The CR7 change keeps a stopped batch's rest pending, but nothing
    drains it before the gap timeout (`actingweb/callback_processor.py`).
12. **Low, peer-reachable.** A bulk batch over 25 whose writes all lost
    still sets `applied` after the loop and resyncs
    (`actingweb/handlers/properties.py`, `recorder.applied = True`).
13. **Low, owner-only.** A web-UI rank-addressed delete of a spanned item is
    an index delete, not a reference (`actingweb/handlers/www.py`).
14. **Low, owner-only.** The `_convert` meta check is check-then-act
    (`actingweb/attribute_list.py`, finding 8 of the outside voice).
15. **Low.** A folded resync fault may leave no miss record when the store
    is down (`_PostListDiffs.register`).
16. **Low, owner-only.** A pre-3.16 attribute list with a hole (a falsy item
    the old `set_attr` deleted) now refuses writes (`_convert` raises
    `ListCorruptionError`); reads raised `IndexError` for the hole before
    too. The tool reports it.
17. **Low (cost).** Old-layout reads load every item row per call
    (`actingweb/attribute_list.py:637`); `list_all_with_rows` skip-scans after
    a prefix read (`actingweb/attribute_list_store.py:140`).
- **U1 (unverified, checked by reading).** The full-state fallback now sends
  a subscription to one property its state bare. The fallback is reached for
  a subscriber that lacks resync, which is mostly a pre-3.16 one, and a
  pre-3.16 receiver applies a bare list diff or object as top-level keys:
  the bare form regresses exactly the receivers the fallback exists for.
- **U2.** A 3.15 receiver gets `delete` by index and ignores `old_item`;
  mixed versions are not described in the migration guide.

## Remaining Tasks

- [ ] Fix 1-8 (peer-reachable Medium and above, or Medium on the rebuild
      path) through `/iterate_plan`; revert the bare fallback (U1); decide
      9-17 (fix the cheap ones, accept the rest with a record).
- [ ] Re-run this verification.

## Overall Assessment

Iteration 1 fixed most of the first verification's findings, but not
cleanly: the resync split covers one caller of two, the value-addressed
delete cannot tell an applied delete from a drifted replica, and the stale
sweeps of the rebuild and the revocation still cross into other targets'
data in the shared replica bucket. Not clean under the stop rule; another
iteration follows.
