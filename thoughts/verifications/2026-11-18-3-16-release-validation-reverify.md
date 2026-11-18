# Verification: validating the release after 3.15.1 (4.0.0rc1), re-run

**Date:** 2026-11-18
**Plan:** thoughts/plans/2026-11-15-3-16-release-validation.md
**Research:** thoughts/research/2026-11-18-3-16-release-validation.md
**Branch:** release/3.16.0-release-validation
**Commit:** `5c94b0b` plus the uncommitted iterations 1 and 2
(`thoughts/plans/2026-11-15-3-16-release-validation.iterations.md`)

The previous run's scope stands (all four phases, every AC); this run checks
what the iterations changed and re-runs the checks the delta warrants.

## Automated Check Results

- **Browser QA:** N/A for this delta (no page changed since the previous
  run's walk).
- **Second opinion:** outside-voice on the iteration diff (`git diff HEAD --
  actingweb tests CHANGELOG.rst`), codex (`codex exec -s read-only`) and a
  fresh-context claude: 5 findings (Issues 1 to 5 below).
- **Code review / security review:** not re-run (the delta is one function's
  deadline and two tests; no authorization or input path changed).
- `ruff check`, `ruff format --check`, `pyright`: pass, 0 errors.
- `tests/integration/verify_groups.py`: consistent.
- `make test-all-parallel` (DynamoDB): 8,163 passed, 0 failed, 212
  skipped, 2 xfailed.
- `make test-all-parallel` (PostgreSQL): 7,935 passed, 0 failed, 440
  skipped, 2 xfailed.
- `sphinx-build -W ...`: build succeeded.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-18-3-16-release-validation.md
**Iterations since:** entries 1 and 2

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The awaited notification got a fresh budget (Medium) | Fixed within one context; the cross-context case is Issue 1 below | `actingweb/trust_permissions.py` (`_Deadline.for_request(...).remaining()`), `tests/test_trust_permissions_unit.py::test_store_permissions_async_shares_the_request_deadline`, seen failing first; iterations entry 1 |
| 2. The sign-in callback's hook call was untested (Medium) | Fixed | `tests/test_spa_trust_type.py::test_the_callback_asks_the_hook_before_it_writes_the_trust` fails with the call in `get()` bypassed (`create_trust.assert_not_called()`); iterations entry 2 |
| 3. The budget covers only the async path (Low) | Still open | unchanged |
| 4. `decide_trust=None` runs the hooks (Low) | Still open | unchanged |
| 5. A hook meets `client_id=None` on sign-in (Low) | Still open | unchanged |
| 6. A storage fault in a hook fails the sign-in; the changelog says otherwise (Low) | Still open | unchanged |
| 7. The actor interface left the guarded block (Low) | Still open | unchanged |
| 8. "Behavior change: none" for the hybrid-only token (Low) | Still open | unchanged |
| 9. The guide's URL points at `latest` (Low) | Still open | unchanged |
| 10. Smaller code findings (Low) | Still open | unchanged |
| 11. The factory accepts a creator longer than its form allows (Low) | Still open | unchanged |
| 12. The "Add property" icon (Low) | Still open | unchanged |

## Acceptance Criteria

Unchanged from the previous run (all pass). The iterations add tests to
two Spec Delta statements; no AC changed.

## Remaining Tasks

- [ ] The rc pass, including 3.15.1 on PostgreSQL at `a7b8c9d0e1f2`
  (`thoughts/todo/rc-pass-against-real-consumers.md`).
- [ ] Context7 after the stable tag.
- [ ] The issues below and the Lows still open from the previous run.

## Issues Found

### 1. The shared deadline is shared only within one `contextvars` context
**Severity:** Medium
**Description:** the deadline is created at its first use
(`actingweb/callback_sender.py:146-149`, `end =
request_context.get_delivery_deadline()` … `set_delivery_deadline(end)`),
and the FastAPI integration runs a sync handler in a copy of the context
(`actingweb/interface/integrations/fastapi_integration.py:659` `ctx =
contextvars.copy_context()`). A deadline started inside that copy is not
seen by the request task, or the reverse, so one request can still spend
about twice the budget when both a sync handler's callbacks and an awaited
`store_permissions_async` run in it. The changelog's "the same per-request
deadline as the request's callbacks" is true only within one context. The
copy is the callback sender's existing design; the iteration's wording is
new.
**Location:** `CHANGELOG.rst` (the `store_permissions_async` FIXED entry),
`actingweb/trust_permissions.py` docstring
**Recommendation:** start the deadline when the request context is set
and a budget is configured, so every copy shares it; or narrow the wording
to "within the same context".

### 2. No test fails if the partly-spent case goes back to a fresh budget
**Severity:** Medium
**Description:** the new test covers a spent deadline; the budget test sets
no request id, so `left == budget` there. Replacing `left` with the budget
in the `wait_for` would reopen the previous Issue 1 with every test green.
**Location:** `actingweb/trust_permissions.py` `await
asyncio.wait_for(_notify_with_error_handling(), left)`
**Recommendation:** a test with a request id and 0.2 s left of a 5 s
budget, asserting the call returns in under a second.

### 3. The "no deadline yet" path is not tested
**Severity:** Low
**Description:** the test pre-seeds the deadline; nothing shows that a
deadline the notification starts is then shared by later callbacks.
**Location:** `tests/test_trust_permissions_unit.py`
`request_context.set_delivery_deadline(time.monotonic() - 0.1)`
**Recommendation:** a test with a request id and no deadline, asserting
`get_delivery_deadline()` is set afterwards.

### 4. The cut cannot interrupt the synchronous trust read
**Severity:** Low
**Description:** `trust.get()` inside the notification blocks the loop, so
`wait_for` fires only after it returns.
**Location:** `actingweb/trust_permissions.py` `trust_info = trust.get()`
**Recommendation:** say the cut applies to the peer exchange, or read the
trust off the loop.

### 5. The sign-in test checks the redirect only when no hook declines
**Severity:** Low
**Description:** the declining cases assert that no trust is written but
not that the sign-in completed.
**Location:** `tests/test_spa_trust_type.py`
`assert webobj.response.status_code in (200, 302)` (no-hook case only)
**Recommendation:** assert the same completion for all three cases.

## Spec Merge

- `thoughts/specs/trust-permissions.md` - TPM-3 updated by iterations
  entry 1 (the request's deadline); Untested now names Issues 1 and 2 of
  this run.
- `thoughts/specs/oauth-client-registration.md` - OCR-4 gains the
  callback-level test (entry 2); its wiring item left Untested.
- The delta was merged by the previous run (`spec_merged: 2026-11-18`).

## Overall Assessment

The two Medium issues of the previous run are addressed: the sign-in
callback's hook call is now covered by a test that fails without it, and
the permission notification counts against the request's deadline instead
of a fresh one. The Full tier is green on both backends. What the
iteration added is narrower than its wording: the deadline is shared
within one context only (the callback sender's own design), and the
partly-spent case has no test. Neither is a regression against 3.15.1,
which had no bound at all; both are small. The recommendation before the
PR is one more iteration: a test for the partly-spent deadline, the
changelog and docstring narrowed to "within the same context" (or the
deadline started with the request context), and the sign-in test's
completion asserted in all three cases.
