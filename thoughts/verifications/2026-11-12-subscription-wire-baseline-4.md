# Verification: the subscription wire between two actors, recorded as it is today (fourth run)

**Date:** 2026-11-12
**Plan:** thoughts/plans/2026-11-06-subscription-wire-baseline.md
**Research:** thoughts/research/2026-11-06-subscription-wire-baseline.md (and the spike, thoughts/research/2026-11-07-subscription-wire-spike.md)
**Branch:** release/3.16.0-subscription-wire-baseline (local, thirteen commits, not pushed)
**Commit:** 9819084

Fourth verification of this plan, after Iterations 17–20 (`9819084`).
There is no feature document: the plan is test-only. This run reviews
the delta `36a72c8..9819084` against the third verification's five
issues and repeats the Full tier, plus the wire step on Python 3.11.

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees.
- **Second opinion:** the outside-voice agent ran **Codex** (`codex exec -s
  read-only`, outside the sandbox) and a **fresh-context Claude** reviewer
  over the delta.
  - Each finding kept below was checked against the code.
  - One was rejected: Codex warned that `.venv*` could hide a root
    document named that way, but no such path exists.
  - The built-in code review and security review were not re-run. The
    delta touches only the test harness, one test and `conf.py`; reviews
    scale to the delta.
- **Full tier (Python 3.14):**
  - `poetry run ruff check actingweb tests`: pass
  - `poetry run ruff format --check actingweb tests`: pass (557 files)
  - `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings)
  - `poetry run python tests/integration/verify_groups.py`: pass (43
    groups; registry consistent; Wire-Phase trailers match)
  - `make test-all-parallel` (DynamoDB): pass, 6596 passed, 53 skipped,
    1 xfailed (parallel run)
  - `make test-all-parallel` (PostgreSQL): pass, 6393 passed, 256
    skipped, 1 xfailed (parallel run)
  - `sphinx-build -E -W --keep-going ...`: pass, fresh environment, with
    `.venv311` present (Iteration 20)
- **Python 3.11** (`.venv311`, CPython 3.11.18):
  - The wire step as CI runs it (`pytest tests/ -m wire -p
    no:rerunfailures`, sequential): DynamoDB 314 passed in 281 s;
    PostgreSQL 314 passed in 92 s.
  - `test_subscription_sync_coverage.py` on PostgreSQL: 13 passed.
- **Benchmarks:** not run; no list storage or attribute code is touched.

## Phase Verification

Phases 1–4: **VERIFIED** by the earlier runs. This run read the delta:

- **`tests/integration/_wire.py`**
  - `_run_and_drain` matches Iteration 17. An error is recorded only when
    nobody retrieved it, cancelled tasks are not errors, and on a timeout
    or a raising action it cancels and cleans up.
    - The two new tests failed on the previous drain and pass on 3.14
      and 3.11.
    - Production's fire-and-forget sites catch and log their own errors
      inside the task, and nothing under `actingweb/` uses
      `add_done_callback`. Today's code therefore has no failure that the
      `_log_traceback` check would miss.
  - `_without_clock` and `_content_key` match Iteration 18. Other random
    values remain in the key (Issue 1).
- **`test_subscription_sync_coverage.py`:** `test_004` reads the trust on
  both sides (Iteration 19). It checks the status only (Issue 4).
- **`conf.py`:** `.venv*` and `.venv*/**` are excluded (Iteration 20).
  This is outside the plan's test-only scope, and named as such in the
  plan entry.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-12-subscription-wire-baseline-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. `task_errors` records handled failures | Fixed | `_wire.py` `_run_and_drain` (the `_log_traceback` check); `test_failures_the_action_handled_are_not_task_errors` |
| 2. Callback-state leftovers sort by timestamp | Partly fixed | Clock fields are stripped (`_wire.py:443` `_CLOCK_FIELDS`); a nonce and the ids remain (Issue 1 below) |
| 3. A timed-out drain leaves tasks running | Fixed | `_wire.py:742-749`; `test_a_timed_out_drain_cancels_what_is_still_running`; two edge cases remain (Issues 3 and 5) |
| 4. `test_004` ignores B's trust | Fixed | `test_subscription_sync_coverage.py` reads both sides |
| 5. `.venv311` breaks the local docs build | Fixed | `conf.py` `exclude_patterns`; the fresh `-E -W` build passes |

## Remaining Tasks

- [ ] Owner: accept Issues 1–5 below as they stand, or fold the
      three-line fix for Issue 1 into the PR. All are test-only and Low.
- [ ] The owner's per-phase codex review before the PR.
- [ ] Owner decision, unchanged: `fetch-depth` for the trailer check in
      CI (`thoughts/todo/wire-phase-check-in-ci.md`).

## Issues Found

### 1. Store leftovers can still sort by a random nonce or id
**Severity:** Low (latent: every store is empty in today's recordings)
**Description:** Iteration 18 strips the clock fields from the sort key,
but the stored values carry other random values:
- **A nonce:** every callback-state write adds one
  (`actingweb/callback_processor.py:197` `written = {**new_state,
  "nonce": uuid.uuid4().hex}`, and `:346`).
- **Actor and subscription ids:** pending entries hold the callback
  wrapper with both (`actingweb/fanout.py:535-540` `"id":
  self._actor.id, ... "subscriptionid": subscription_id`).

Two leftovers that otherwise tie would sort by these values, so their
order would change from run to run. The stub test does not carry them.
**Location:** `tests/integration/_wire.py:443` (`_CLOCK_FIELDS =
frozenset({"claimed_at", "_received_at", "timestamp"})`)
**Recommendation:** also drop `nonce`, `id` and `subscriptionid` from the
key (rename the set to the fields that vary per run), and add them to the
stub rows.

### 2. A timeout now hides the error of the task that caused it
**Severity:** Low (diagnostics only)
**Description:** on a timeout, cleanup retrieves every done task's
exception and then raises `TimeoutError`. Retrieving the exception stops
asyncio from logging "never retrieved", and that log was the only trace
of a crash that left another task waiting.
**Location:** `tests/integration/_wire.py:749` (`task.exception()  #
retrieved: no "never retrieved" noise`)
**Recommendation:** attach the failed tasks' exception names to the
re-raised error (`exc.add_note(...)`).

### 3. Tasks created during cleanup are not cancelled
**Severity:** Low
**Description:** the leftover list is built once, but the task factory
stays installed until `finally`. A task that a cancelled task's cleanup
starts is captured but never cancelled. The test's docstring promises
that nothing is "left to run into a later step". Today the only caller,
`asyncio.run`, cancels it at shutdown.
**Location:** `tests/integration/_wire.py:742` (`leftover = [t for t in
created if not t.done()]`)
**Recommendation:** loop the cancel until no new task appears, or restore
the factory first.

### 4. `test_004` checks that the trust exists, not its state
**Severity:** Low
**Description:** a regression that flipped `approved` or `verified` on
either side would still answer 200.
**Location:** `tests/integration/test_subscription_sync_coverage.py:200`
(`assert response.status_code == 200`)
**Recommendation:** also assert `approved` and `verified` in the body.

### 5. A second cancellation interrupts the cleanup
**Severity:** Low
**Description:** a second cancellation during `await
asyncio.wait(leftover, timeout=1.0)` (a second Ctrl-C) skips the
retrieval loop. The only effect is "never retrieved" noise.
**Location:** `tests/integration/_wire.py:746`
**Recommendation:** accept as is.

## Overall Assessment

The third iteration closed Issues 1 and 3–5 of the third verification
and narrowed Issue 2.
- The drain no longer reports failures the library handled.
- It cancels what it was waiting for when it gives up.
- `test_004` reads both sides of the trust.
- The local docs build passes with the 3.11 venv present.

The Full tier is green on 3.14 on both backends. The wire step passes on
a real 3.11 interpreter on both backends (314/314). No library code
changed, and no exposure row exists.

The verification is **clean** under the owner's stop rule. Every finding
is Low and in test code. Issues 1 and 3 can only show once a recording
carries store leftovers or a drain times out, and none does today. The
review has now looked at these few harness lines four times, and each
pass finds a smaller edge case in the same code. The plan is ready for
the owner's codex review and the PR. Issue 1's three-line fix can ride
along if the owner wants it.
