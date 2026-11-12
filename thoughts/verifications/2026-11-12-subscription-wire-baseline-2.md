# Verification: the subscription wire between two actors, recorded as it is today (re-run after iteration)

**Date:** 2026-11-12
**Plan:** thoughts/plans/2026-11-06-subscription-wire-baseline.md
**Research:** thoughts/research/2026-11-06-subscription-wire-baseline.md (and the spike, thoughts/research/2026-11-07-subscription-wire-spike.md)
**Branch:** release/3.16.0-subscription-wire-baseline (local, nine commits, not pushed)
**Commit:** cb63f59

Second verification of this plan, after the plan's Iterations 1–9
(`6f83e69`). No feature document: the plan is test-only. This run reviews
the iteration delta (`bdcf8c5..cb63f59`) against the previous verification's
issues. Phases 1–4 were verified in full by the first run and are not
re-read, except where the iteration touched them.

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees.
- **Second opinion:** the outside-voice agent ran **Codex** (`codex exec -s
  read-only`, outside the sandbox) and a **fresh-context Claude** reviewer
  over the iteration delta. The built-in code review and the security
  review were not re-run. The delta is test-only (`git diff
  bdcf8c5..cb63f59 -- actingweb examples` is empty), and reviews scale
  to the delta (owner rule). Seven findings came back, and each was checked
  against the code (Issues 1–3 and 5–8 below). I confirmed Issue 1
  independently: CPython 3.11's `wait_for` source and a simulation.
- `poetry run ruff check actingweb tests`: pass
- `poetry run ruff format --check actingweb tests`: pass (557 files)
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings)
- `poetry run python tests/integration/verify_groups.py`: pass (43 groups
  documented; wire rows registry consistent; Wire-Phase trailers match)
- `make test-all-parallel` (DynamoDB): pass, 6590 passed, 53 skipped, 1
  xfailed (parallel run)
- `make test-all-parallel` (PostgreSQL): pass, 6387 passed, 256 skipped,
  1 xfailed (parallel run)
- `sphinx-build -W --keep-going ...`: pass
- The wire step as CI runs it (`pytest tests/ -m wire -p no:rerunfailures`,
  sequential): DynamoDB 308 passed in 220 s; PostgreSQL 308 passed in 95 s.
  The count was 298; the 10 new tests are `WD4` ×2 and the harness tests.
- All of the above ran on Python 3.14. None ran on 3.11, and Issue 1 is a
  3.11-only failure.
- Benchmarks: not run; no list storage or attribute code is touched.

## Phase Verification

Phases 1–4: **VERIFIED** by the first run (`e7df136`); see the previous
document. The iteration changed them as follows. Each change was read in
the diff.

- **Phase 1 harness** (`tests/integration/_wire.py`):
  - `_snapshot_stores` (`:440`) and `snapshot(..., stores=)`: matches
    Iteration 4. Codex checked that
    `get_subscription_diff_list(config).fetch(actor_id=...)` returns all of
    an actor's diffs on both backends. The `state:`/`pending:<peer>:<subid>`
    keys match `actingweb/callback_processor.py:105-111`.
  - `_hoist_callbacks` (`:649`): matches Iteration 5.
  - The sort key: matches Iteration 6.
  - `_snapshot_replica`'s length: matches Iteration 6.
  - `_run_and_drain`: the timeout and `task_errors` match the plan's
    words, but it is **broken on Python 3.11** (Issue 1) and records only
    some failing tasks (Issue 2).
- **Phase 1 gate** (`tests/integration/verify_groups.py`):
  - Owners are read at the merge base, merges are included, git runs from
    `_REPO`, the base is the newer of `origin/master` and `master`, and a
    parse error is reported: all match Iteration 1.
  - A branch that merges `master` in is wrongly flagged (Issue 4).
- **Phase 1 rows:**
  - `WD4` is new.
  - Re-recorded: `WD19` (one step), `WC5`–`WC7` (stores), `WL12.target`
    (length).
  - `rows.toml` gives each a dated `reason` and an `expected` that matches
    the bytes.
  - `WD10.import`'s recording is unchanged.
- **Phase 2:** the coverage table credits `WD4` for
  `TestCallbackSequencing` (Iteration 7).
- **Phase 3 tests:**
  - Iterations 2, 3 and 8 are in place: the baseline-storage test runs to
    the end, `found_lover` is a real assert, the lookup loops require
    exactly one match, and the `Location` read is strict.
  - Three claims are overstated (Issues 3, 5 and 6).
- **Phase 4 docs:** the README, `testing.rst` and the `rows.toml` header
  state the new trailer rule consistently.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-12-subscription-wire-baseline.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Baseline-storage test returns early | Fixed | `test_subscription_baseline_storage.py`: the id comes from the listing, a real list is created, `sync_peer` runs, and scalars, items and the profile are asserted (Iteration 2) |
| 2. Deletion rows blind to leftovers | Fixed, with a gap | `_wire.py:440` `_snapshot_stores`, on for `WC5`–`WC7`. Every recorded store is empty, so detection rests on the reverted mutation (Iteration 4). The ordering of leftovers is unstable (Issue 7) |
| 3. Tightened tests that cannot fail | Partly fixed | Guards, loops, `found_lover` and `test_017` are fixed. `test_004` is still named for a cleanup it never exercises (Issue 3). The `diffs_processed == 4` claim is overstated (Issue 6). One conditional assert remains (Issue 5) |
| 4. Wire-Phase check bypassable | Fixed | `verify_groups.py` reads owners at the merge base, includes merges and runs git from `_REPO`; a new false positive comes with it (Issue 4) |
| 5. Timing-sensitive WD19, WD18, WD10.import | Fixed, wording overstated | `WD19` posts in one step. `WD18` and `WD10.import` hoist (`test_wire_delivery.py:254`, `test_wire_peer_paths.py:219`). "Any runner" overstates the fix (Issue 8) |
| 6. Sort key ignores target and granularity | Fixed | `_sort_callback_runs` key |
| 7. `_run_and_drain` timeout and errors | Regressed | The timeout deadlocks on 3.11 (Issue 1); failed tasks are recorded only if still pending (Issue 2) |
| 8. WL12 read_error hides later steps | Fixed | `WL12.target` records the length, 1 to 6 |
| 9. No row for held callbacks draining | Fixed | `WD4`. Not timing-sensitive: sequence 1 = `last_seq + 1` skips the gap check (`callback_processor.py:486-499`) |
| 10. Duplicate assert, Location read | Fixed | `test_property_notifications.py` (Iteration 8) |
| 11. No type hints on test functions | Accepted as-is, owner's call | Plan Iteration 9 |
| 12. `wait_for_quiet` | Accepted (note) | Unchanged; `settle=` and the hoist cover the two rows |

The previous Remaining Tasks:
- The deviations (a) skips as asserts and (b) dropping `WC8` were
  accepted by the owner.
- (c) The trailer check stays local; `thoughts/todo/wire-phase-check-in-ci.md`
  and its `INDEX.md` row exist.
- Still open: the 3.11 evidence (now with a known failure, Issue 1) and
  the owner's codex review before the PR.

## Remaining Tasks

- [ ] `/iterate_plan` on Issue 1 before the PR: CI's required 3.11
      contexts would fail. Issues 2–4 are cheap and worth fixing in the
      same pass; Issues 5–8 at the owner's discretion.
- [ ] The first PR run is the first Python 3.11 evidence for every
      recording.
- [ ] The owner's per-phase codex review before the PR.
- [ ] Owner decision, unchanged: `fetch-depth` for the trailer check in CI
      (`thoughts/todo/wire-phase-check-in-ci.md`).

## Issues Found

### 1. The async drain deadlocks on Python 3.11
**Severity:** High (blocks CI's required 3.11 contexts; not peer-reachable)
**Description:** on 3.11, `asyncio.wait_for` wraps `drain()` in a task of
its own (3.11's `Lib/asyncio/tasks.py`, `wait_for`: `fut =
ensure_future(fut, loop=loop)`; 3.12 rewrote it on `asyncio.timeout`).
That task is not `current`, so `drain()` finds itself among the pending
tasks and gathers itself. It never finishes. The step raises
`TimeoutError` after 30 s, and on cancellation it raised `RecursionError`
in the simulation. Local runs are 3.14, which is why everything is
green here.
- **Affected:** `WD5` (both topologies), and the harness tests
  `test_an_async_step_waits_for_the_tasks_it_left_on_the_loop` (`:437`)
  and `test_an_async_steps_failing_task_is_recorded_not_raised` (`:570`).
- **Not affected:** `WD18` and `WD10.import`, which use HTTP, not an
  async step.
- **Evidence:** a simulation of 3.11's `wait_for` semantics on 3.14 printed
  `FAILED: RecursionError` after the timeout. No 3.11 interpreter is
  installed here.

**Location:** `tests/integration/_wire.py:682` (`t for t in
asyncio.all_tasks() if t is not current and not t.done()`), `:690`
(`await asyncio.wait_for(drain(), _DRAIN_TIMEOUT)`)
**Recommendation:** use `async with asyncio.timeout(_DRAIN_TIMEOUT):`
(3.11+) around the loop, in the caller's task. Alternatively, exclude
`asyncio.current_task()` inside `drain()`.

### 2. `task_errors` misses a task that failed before the drain looked
**Severity:** Medium (test only)
**Description:** the drain sees only tasks that are not done. If the action
awaits anything after spawning a task that then fails, the task is
already done and filtered out. The step records a clean result, and the
error appears only as "Task exception was never retrieved" on stderr. The
fix for Issue 7 therefore covers only tasks still pending when the action
returns, and its harness test covers only that case.
**Location:** `tests/integration/_wire.py:682` (`... and not t.done()`)
**Recommendation:** snapshot `asyncio.all_tasks()` before `action()`, and
collect `.exception()` from every new task, done or not. Sort the error
names.

### 3. `test_004` is still named for a cleanup it never exercises
**Severity:** Medium (test only)
**Description:** `test_004_sync_cleans_dead_subscription_preserves_trust`
now asserts that `sync_peer` had nothing to do: `test_003`'s delete had
already removed A's side. A regression in the dead-subscription cleanup
would pass. The previous Issue 3 is relabelled, not closed.
**Location:** `tests/integration/test_subscription_sync_coverage.py:176`
(`# B's delete in test_003 already removed A's side of the dead`)
**Recommendation:** leave A holding a dead subscription (delete only B's
row) and assert that `sync_peer` removes it. Otherwise rename the test
and record the cleanup gap.

### 4. The trailer check flags a branch that merges `master` in
**Severity:** Low (local gate; it rejects a correct history, never accepts
a wrong one)
**Description:** a merge commit is diffed against its first parent. When a
branch merges `master` in, recordings that `master` re-recorded show as
changed by the merge. The merge then needs a trailer naming their owner,
and it cannot name more than one. Confirmed in a scratch repository:
`master` re-records `X.json` under `Wire-Phase: p:1`, the branch merges
`master`, and the check reports `<merge>: changes X.json and must carry
exactly one 'Wire-Phase: <plan>:<phase>' trailer (has 0)`. A rebase
avoids it.
**Location:** `tests/integration/verify_groups.py:295-299` (`"diff",
"--name-status", "--no-renames", f"{commit}^1", commit`)
**Recommendation:** for a merge, skip a file whose content equals its
version on the second parent: it was taken from there unchanged, and
only a conflict resolution is the merge's own change. Add a scratch-repo
test.

### 5. One conditional assert is left in `test_subscription_flow.py`
**Severity:** Low
**Description:** Iteration 3 says every guard is now unconditional, but one
still skips its assert.
**Location:** `tests/integration/test_subscription_flow.py:874` (`if
isinstance(first_data, dict) and "data1" in first_data:`)
**Recommendation:** make it an assert, after checking it holds on both
backends.

### 6. `diffs_processed == 4` does not show that a sync stored anything
**Severity:** Low
**Description:** Iteration 3 says this assert makes "a sync that stores
nothing" fail. The counter counts `ProcessResult.PROCESSED`, whatever the
handler stored, and the test asserts that the list is empty.
**Location:** `tests/integration/test_subscription_sync_coverage.py:378`
(`assert result.diffs_processed == 4, result`)
**Recommendation:** correct the plan's wording, or assert a stored value.

### 7. Leftovers in `stores` would sort by random ids
**Severity:** Low (latent: every store is empty today)
**Description:** diffs and callback-state entries are sorted by the raw
subscription and peer ids, before the normaliser names them. If two
leftovers ever appear, their order changes between runs. The row would
then flake instead of showing a stable diff.
**Location:** `tests/integration/_wire.py:464` (`key=lambda d:
(str(d["subscriptionid"]), d["sequence"] or 0)`), `:451` (`for key in
sorted(bucket or {}):`)
**Recommendation:** sort by the names from `Scenario.names`.

### 8. Two overstated claims: "any runner", and the hoist
**Severity:** Low (note)
**Description:**
- `WD19`'s six posts still have to fall within 2 s of the first, and
  `WD4`'s two must too. The `reason`'s "inside the gap timeout on any
  runner" overstates this; the dependence is much smaller than before.
- `_hoist_callbacks` makes `WD18` and `WD10.import` identical whether a
  callback lands during or after the method request. A regression that
  sent the callback synchronously inside the request would therefore not
  show in them.

**Location:** `tests/integration/wire/rows.toml` (`WD19` `reason`);
`tests/integration/_wire.py:649`.
**Recommendation:** word `WD19`'s reason as "one step, no snapshot between
posts". Note the hoist's blind spot in `WD18`'s `expected`.

## Overall Assessment

The iteration closed most of what the first verification found:
- The gate is no longer bypassable.
- The baseline-storage test runs to the end.
- The cleanup rows read the stores directly.
- `WD4` records the drain over HTTP.
- `WD19` no longer snapshots between its posts.

The Full tier is green on both backends on 3.14, and the wire step passes
sequentially on both (308 / 308). No library code changed, and no finding
is reachable by a peer.

It is not ready for the PR. Issue 1 is a regression the iteration
introduced: the drain's new timeout deadlocks on Python 3.11, which CI
requires, so `WD5` and two harness tests would fail on the first PR run.
It is a one-line fix (`asyncio.timeout`). Issues 2 and 3 are Medium
test-quality gaps: a fix and a test that still claim more than they
check. Run `/iterate_plan` on Issues 1–3 (and the cheap Lows 4–7), then
verify again.
