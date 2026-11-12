# Verification: the subscription wire between two actors, recorded as it is today (third run)

**Date:** 2026-11-12
**Plan:** thoughts/plans/2026-11-06-subscription-wire-baseline.md
**Research:** thoughts/research/2026-11-06-subscription-wire-baseline.md (and the spike, thoughts/research/2026-11-07-subscription-wire-spike.md)
**Branch:** release/3.16.0-subscription-wire-baseline (local, eleven commits, not pushed)
**Commit:** c44e4f0

Third verification of this plan. It follows the plan's Iterations 10–16,
committed as `c44e4f0`. No feature document: the plan is test-only. This
run reviews the iteration delta (`7653ea9..c44e4f0`) against the second
verification's eight issues. For the first time it also runs the wire
step on a real Python 3.11 interpreter.

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees.
- **Second opinion:** the outside-voice agent ran **Codex** (`codex exec -s
  read-only`, outside the sandbox) and a **fresh-context Claude** reviewer
  over the delta. The built-in code review and security review were not
  re-run: the delta is test-only (no file under `actingweb/` or
  `examples/` changed) and reviews scale to the delta. Every finding was
  checked against the code (Issues 1–4).
  - Codex confirmed that the task factory accepts 3.11's and 3.14's
    keyword arguments, that `merge_base..HEAD` contains side-branch
    commits and every parent of an octopus merge, and that the xdist
    group keeps `test_003` before `test_004`.
- **Full tier (Python 3.14):**
  - `poetry run ruff check actingweb tests`: pass
  - `poetry run ruff format --check actingweb tests`: pass (557 files)
  - `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings)
  - `poetry run python tests/integration/verify_groups.py`: pass (43
    groups; registry consistent; Wire-Phase trailers match)
  - `make test-all-parallel` (DynamoDB): pass, 6594 passed, 53 skipped,
    1 xfailed (parallel run)
  - `make test-all-parallel` (PostgreSQL): pass, 6391 passed, 256
    skipped, 1 xfailed (parallel run)
  - `sphinx-build -W --keep-going ...`: **fail locally, 22 warnings**.
    All of them come from `.venv311/…/site-packages/sphinx/…/templates`.
    The 3.11 venv made for this verification sits in the repository root,
    and `conf.py` does not exclude it (Issue 5). With `.venv311` added to
    `exclude_patterns` on the command line (`-D`), a fresh build (`-E`)
    passes. CI has no such directory.
- **Python 3.11** (`.venv311`, CPython 3.11.18 from Homebrew, the version
  CI's required contexts run):
  - The wire step as CI runs it (`pytest tests/ -m wire -p
    no:rerunfailures`, sequential): DynamoDB **312 passed** in 271 s;
    PostgreSQL **312 passed** in 92 s. This is the first 3.11 evidence for
    every recording and for the harness.
  - The five files Phase 3 and the iterations tightened
    (`test_subscription_sync_coverage.py`, `test_subscription_flow.py`,
    `test_subscription_baseline_storage.py`,
    `test_property_notifications.py`, `test_trust_flow.py`), on DynamoDB:
    97 passed.
  - Before this run (2026-11-12): the pre-fix drain (`cb63f59`'s
    `_wire.py`) on 3.11 fails with `RecursionError` after its timeout; the
    fixed one passes.
- **Benchmarks:** not run; no list storage or attribute code is touched.

## Phase Verification

Phases 1–4: **VERIFIED** by the first run (`e7df136`), with the second
run's fixes. The delta was read change by change:

- **`tests/integration/_wire.py`**
  - `_run_and_drain` (`:690-725`): matches Iteration 10. It captures tasks
    through the loop's task factory, restores the previous factory in
    `finally`, and runs the timeout in the caller's task. It is correct on
    both interpreters. Two latent edge cases remain (Issues 1 and 3).
  - `_snapshot_stores` (`:440-475`): matches Iteration 15. The ordering is
    weaker than claimed (Issue 2).
- **`tests/integration/verify_groups.py`:** `check_wire_phase` drops a
  merge's files that equal another parent's version (Iteration 12). I
  looked for a way to hide a re-recording through this and found none:
  every commit a non-first parent brings in is in the checked range, or on
  `master`.
- **`test_subscription_sync_coverage.py`:**
  - `test_003` and `test_004` exercise the dead-subscription cleanup
    (Iteration 11). A mutation that skips the library's `sub_obj.delete()`
    turns `test_004` red. B's trust is not checked (Issue 4).
  - `TestSyncSubscriptionBaseline.test_003` asserts the sequence moved by
    four (Iteration 14).
- **`test_subscription_flow.py`:** `test_034`'s guard is an assert
  (Iteration 13). No `if` guard is left in the file's test bodies.
- **`rows.toml`:** the `WD19` reason and the `WD18` and `WD10.import`
  `expected` texts are reworded (Iteration 16). No recording changed.
- **Plan, todo, INDEX:** the Iterations batch 10–16 is present.
  `thoughts/todo/wire-phase-check-in-ci.md` and its `INDEX.md` row still
  stand for the owner's CI decision.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-12-subscription-wire-baseline-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Async drain deadlocks on 3.11 | Fixed | `_wire.py:714` `async with asyncio.timeout(_DRAIN_TIMEOUT):`; the wire step passes 312/312 on 3.11 on both backends; the old drain fails on 3.11 |
| 2. `task_errors` misses early failures | Fixed, but now over-reports | Task factory capture (`_wire.py:708`); the over-report is Issue 1 below |
| 3. `test_004` exercises no cleanup | Fixed | `test_003` deletes only B's row; `test_004` asserts the 404 and A's empty listing; the mutation goes red |
| 4. Trailer check rejects merging master | Fixed | `verify_groups.py` `check_wire_phase`; `test_merging_master_in_does_not_need_master_s_trailers` failed on the old check |
| 5. Conditional assert in `test_034` | Fixed | `test_subscription_flow.py` `assert isinstance(first_data, dict) and "data1" in first_data` |
| 6. `diffs_processed` overstated | Fixed | Sequence +4 asserted; plan Iteration 14 corrects Iteration 3's claim |
| 7. Leftovers sort by random ids | Partly fixed | The id is now only a tie-break, but the content key starts with timestamps (Issue 2) |
| 8. Overstated `WD19` and hoist wording | Fixed | `rows.toml` |

The first verification's open Remaining Tasks: the 3.11 evidence is now
in hand (above). The owner's codex review and the CI trailer decision
remain.

## Remaining Tasks

- [ ] Decide on Issues 1–5 below: a short `/iterate_plan`, or accept.
      All are test-only; none is reachable by a peer.
- [ ] The owner's per-phase codex review before the PR.
- [ ] Owner decision, unchanged: `fetch-depth` for the trailer check in CI
      (`thoughts/todo/wire-phase-check-in-ci.md`).

## Issues Found

### 1. `task_errors` also records failures the action handled itself
**Severity:** Medium (latent: no recording carries `task_errors` today;
not peer-reachable)
**Description:** the task factory captures every task the step creates,
including the ones `asyncio.gather` makes for awaited coroutines. Fanout
gathers its deliveries with `return_exceptions=True` and turns each
exception into a `DeliveryResult` (`actingweb/fanout.py:437-450`). A
delivery the library handled and counted as failed would therefore be
recorded as an unhandled task error. That contradicts the docstring
("production only logs a fire-and-forget task's error"), and a recording
would claim a failure mode the library does not have.
**Location:** `tests/integration/_wire.py:708` (`created.append(task)`),
`:719` (`errors = sorted(`)
**Recommendation:** record only tasks that were still pending when
`action()` returned, plus tasks that failed and whose exception nobody
retrieved. Add a harness test in which the action gathers a failing
coroutine with `return_exceptions=True` and expects no `task_errors`.

### 2. Callback-state leftovers would sort by their timestamps
**Severity:** Low (latent: every store is empty in today's recordings)
**Description:** the content key is the JSON of the stored value with
sorted keys. The values carry wall-clock fields: `claimed_at`
(`callback_processor.py:231`) in a state entry, and `_received_at`
(`:401`) in pending entries. These sort first in the JSON, so the order
follows claim or receipt time. For concurrent deliveries that order is a
race. The harness test uses stub content without timestamps, so it does
not see this.
**Location:** `tests/integration/_wire.py:463-465` (`content =
value.get("data") ...`, `(kind, names.get(peer, peer),
_content_key(content), subid)`)
**Recommendation:** drop `claimed_at`, `_received_at` and `timestamp`
from the key. Give the stub test timestamps that run opposite to the
content order.

### 3. A drain timeout leaves its tasks running and their errors unretrieved
**Severity:** Low (latent)
**Description:** on `TimeoutError`, or when the action raises, the
captured tasks are neither cancelled nor have their exceptions retrieved.
Today `asyncio.run` (the only caller, `_wire.py:594`) cancels whatever is
left on exit, so the only effect is "Task exception was never retrieved"
noise.
**Location:** `tests/integration/_wire.py:714`, `:719` (the error
collection sits after the `try/finally`)
**Recommendation:** in `finally`, cancel unfinished captured tasks and
retrieve their exceptions.

### 4. `test_004` does not check B's side of the trust
**Severity:** Low
**Description:** the docstring says the sync "checks that B still holds
the trust". The test reads only A's trust row, so a regression that
deleted B's row would pass.
**Location:** `tests/integration/test_subscription_sync_coverage.py:194`
(`f"{self.actor_a['url']}/trust/friend/{self.actor_b['id']}"`)
**Recommendation:** also GET B's `/trust/friend/<A>` and expect 200.

### 5. The local 3.11 venv breaks the contract's docs build
**Severity:** Low (local only; CI unaffected)
**Description:** `.venv311` in the repository root holds Sphinx's own
`.rst` templates. `conf.py` excludes `.venv` and `venv` but not other
venv names, so `sphinx-build -W` fails locally with 22 warnings. This is
the same class as the `.claude/worktrees` case, which was fixed in
`conf.py`.
**Location:** `conf.py:78-91` (`exclude_patterns`: `'.venv'`,
`'.venv/**'`, `'venv'`, `'venv/**'`)
**Recommendation:** add `'.venv*'` and `'.venv*/**'` to
`exclude_patterns`, or move the venv out of the repository.

## Overall Assessment

The second iteration fixed what it set out to fix:
- The 3.11 deadlock is gone. The whole wire step passes on a real 3.11
  interpreter on both backends (312/312), which is the first 3.11 evidence
  for every recording.
- `test_004` now exercises and pins the dead-subscription cleanup.
- The trailer check accepts a branch that merges `master` in, without
  opening a way to hide a re-recording.

The Full tier is green on 3.14 on both backends. The only red result, the
local docs build, comes from the venv made for this verification, not from
the branch. No library code changed, and no exposure row exists.

Under the owner's stop rule (clean = no peer-reachable Medium or higher)
this verification is **clean**. All five findings are in test code, and
four of the five are latent: they would only show if a future recording
carried leftovers or task errors. Issue 1 is the one worth fixing before
the PR, because it would make a recording state something false. Issue 5
is a two-line `conf.py` change that keeps the local Full tier usable with
the 3.11 venv. Issues 2–4 are cheap enough to fold into the same pass, or
can be accepted.
