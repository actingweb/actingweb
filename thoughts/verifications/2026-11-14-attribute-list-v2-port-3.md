# Verification: one list implementation for properties and attributes, and list diffs that reach a replica (re-run 3)

**Date:** 2026-11-14
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (not pushed)
**Commit:** 7f3f9f4

Scope: the iteration-2 delta (`a3434fe..7f3f9f4`, the plan's Iterations
8-13) in depth, and the branch again through the built-in code review.

## Automated Check Results

- **Browser QA:** not run (no page changed; the form routes are covered over
  HTTP).
- **Second opinion:** outside-voice (codex `exec -s read-only`, second run;
  a fresh-context reviewer) on the delta: 12 findings. Built-in
  `/code-review` high on the branch: 10 findings.
- ruff check, ruff format, pyright: pass.
- `verify_groups.py`: pass.
- `make test-all-parallel`, **DynamoDB**: 7,423 passed, 208 skipped,
  2 xfailed; **PostgreSQL**: 7,193 passed, 438 skipped, 2 xfailed (both
  before a format-only change; the unit suite after it: 5,863 passed).
- docs build: pass.
- Emm's suite: last run on `65dfad5` (the baseline's failures plus its own
  date-dependent test); not re-run for this delta, which changes no shape a
  consumer reads.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-13-attribute-list-v2-port-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1 resume's subtarget-only resync | Fixed for `request_resync`; `resume_subscriptions` kept (its rows are other plans'); whole-target misses kept off the subtarget key | Iteration 8 |
| 2, 3 value-addressed delete | Fixed with a length check, which an overlap plus traffic still defeats (findings 1, 5 below) | Iteration 9 |
| 4, 5 other targets in the shared bucket | Fixed by not sweeping / not evaluating, which leaves deleted names (finding 3) and turns revocation off (finding 6) | Iteration 10 |
| 6 update overwrote by index | Fixed; duplicates updated by handle now rebuild each time (finding 11) | Iteration 9 |
| 7 rebuild settles over a concurrent change | Partly: a callback at or below the baseline's sequence still applies twice (finding 4) | Iteration 11 |
| 8 deleted list's `delete_all` withheld | Fixed, too wide (finding 9) | Iteration 12 |
| 9 lost mark's claim | Fixed (unverified overlap noted below) | Iteration 11 |
| 10, 12, 13 | Fixed | Iterations 12, 13 |
| 11 kept pending | Reverted by decision | Iteration 11 |
| U1 bare fallback | Reverted | Iteration 12 |
| 14-17 | Accepted | Iteration 13 |

## Issues Found

Outside voice (OV) and code review (CR); peer-reachable marked.

- **OV5 (medium, design, peer-reachable).** Overlapping subscriptions (a
  whole-target and a subtarget subscription to one peer) store every diff
  twice; `append`, `insert`, `extend`, `pop` have no second-delivery guard,
  and the iteration-9 length and no-op rules are partial cover that OV1 and
  OV2 defeat. Remedy: store a subtarget subscription's diffs only when no
  whole-target subscription to the peer stores them.
- **OV1 (medium, peer-reachable).** A delete delivered again after an append
  in between deletes the surviving duplicate (`remote_storage.py`,
  `if len(values) != length + 1:`).
- **OV2 (medium, peer-reachable).** An update on duplicates delivered twice
  overwrites the other copy (`if len(matches) == 1:` before the no-op).
- **OV3 (medium, peer-reachable).** With another target's subscription, a
  rebuild keeps a scalar the dropped batch deleted (no sweep), and settles.
- **OV4 (medium, peer-reachable).** A callback at or below the baseline's
  sequence applied after the baseline applies twice; the rebuild compares
  only `recorded > sequence`.
- **OV6 (low-medium).** Revocation cleanup is off for a peer with another
  target's subscription, undocumented.
- **OV7 (low).** Under steady traffic every rebuild stays owed (one baseline
  a minute).
- **OV8 (low).** `request_resync` can erase a whole-target miss record that
  `resume_subscriptions` wrote.
- **OV9 (low).** `_carries_no_items` passes a scalar with keys from
  `{list, operation, length, index}` and nested values past a sub-path
  exclusion (`actor.py`, `_carries_no_items`).
- **OV10 (low).** Concurrent v2 writers make the exact lengths wrong: a
  rebuild, no corruption. Accepted.
- **OV11 (medium, peer-reachable).** `update_by_handle`/`update_where` on
  duplicates (no index) goes out of step every time.
- **CR1 (medium, peer-reachable).** A negative or past-the-end SDK
  `insert`/`__setitem__`/`__delitem__` index is sent raw and the receiver
  treats it as out of step.
- **CR2 (medium, peer-reachable).** A subtarget-level baseline that is a JSON
  array (subscribe, sync) is stored as a wrapped scalar, not a list.
- **CR3 (medium).** Revocation cleanup no longer covers subtarget-level
  subscriptions (the removed `_delete_revoked_peer_data` deleted lists
  matching revoked patterns for any subscription).
- **CR4 (medium).** The sync paths' resync handler ignores `failed` and the
  owed lists, so a failed baseline settles an owed rebuild.
- **CR5 (low, owner-only).** A `ListAttribute` instance that settled the old
  layout keeps it after another process converts. Accepted (instances are
  per access in the store).
- **CR6 (low-medium).** `repair_keys`/`sweep_span_orphans` remove items but
  announce `metadata`, which the receiver ignores.
- **CR7, CR9 (low, cost).** Serve-time `exists()` per subscriber; per-key
  `_list_exists`. Accepted.
- **CR8 (low).** Value-addressed applies read twice and write by position.
  Accepted once OV5 removes the overlap.
- **CR10 (low).** The PostgreSQL `create_attrs_if_not_exist` docstring says
  it creates the others; it rolls back. Docstring.
- **U (unverified).** The lost-mark fallback may lower a live claim another
  delivery took.

## Remaining Tasks

- [ ] Iterate: OV5 (decision change), OV3, OV4, OV6, OV8, OV9, OV11, CR1,
      CR2, CR3, CR4, CR6, CR10, U; record the accepted ones.
- [ ] Re-run this verification.

## Overall Assessment

Not clean: the per-operation tolerance for a second delivery is the wrong
level, and three fixes of iteration 2 interact (no sweep plus a pruned
batch). The remedy for the overlap is to store one subscription's diffs per
name, not to keep refining the heuristics.
