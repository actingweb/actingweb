# Verification: 3.16 follow-ups the owner decided (first block), re-run

**Date:** 2026-11-02
**Plan:** thoughts/plans/2026-11-02-3-16-owner-decided-followups.md (all four phases and Iterations entries 1-23)
**Research:** the todo files the plan names (no research document of its own)
**Branch:** release/3.16.0-owner-decided-followups
**Commit:** `73c2b86` reviewed; the fixes from that review (entry 23) are in the commit that adds this document

A re-run after the iteration loop on the first verification. Six review
rounds on the vouched rename did not converge, so the owner asked for an
audit instead of a seventh round. That audit is Iterations entry 21, and the
review of the audit is entry 22. This document records what happened to each
of the first verification's issues, the audit's outcome, and one final
review of everything since `9dca508`.

## Automated Check Results

- **Browser QA:** N/A. No change since the first verification touches a page.
- **Second opinion:** codex (`codex exec -s read-only`, unsandboxed) and a fresh-context Claude on `git diff 9dca508..73c2b86 -- actingweb/`. Codex: one finding, refuted (the poll's sequence read is strict and raises; it does not fold to 0). Claude: one medium and three low, all fixed (entry 23). Checked and fine: the half-open breaker close, the pre-fetch ordering and its 503 on a fault, `_reset_state` raising, the deadlock retry, the poll's `in_flight` break.
- **Audit review** (codex and a fresh-context Claude, scoped to the audited rename at `152bb82`): two high findings and one medium, all fixed in `73c2b86` (entry 22). Each new test fails on `152bb82`.
- `ruff check`, `ruff format --check`, `pyright`: 0 errors, 0 warnings (493 files).
- `tests/integration/verify_groups.py`: 53 groups documented.
- Full tier, DynamoDB (`make test-all-parallel`): **5,330 passed**, 59 skipped, 1 xfailed, 1 setup error: `tests/performance/test_backend_performance.py::TestListPropertyPerformance::test_list_property_append_remove`, "list 'perf_items' extend: too many rank collisions" in its fixture under the parallel run (performance tests are not meant to run in parallel); it passes alone, and no change here touches list storage.
- Full tier, PostgreSQL (`make test-all-parallel` with the PG environment): **5,141 passed**, 249 skipped, 1 xfailed.
- `sphinx-build -W`: pass.
- Scope: everything since `9dca508` is a verification fix, a review fix, a revert or the audit, each with an Iterations entry. Nothing unasked.

## Phase Verification

Phases 1, 2 (apart from the rename) and 4 are unchanged since the first
verification, apart from the fixes listed below. They stay VERIFIED.

### The vouched rename (Phase 2, D8 and Issue 8) - VERIFIED after the audit

The audit wrote down the invariant: after any outcome, a vouched actor is
still vouched for whichever address resolves to it, and the creator, the
stored email, `vouched_creator` and the pending value converge without a
further call. It then walked every point where the rename can stop half-done.

- `actingweb/interface/actor_interface.py` `_rename_vouched`. It reads `_internal` afresh. Step 0 records the current creator as the vouched address when the actor is vouched for it only another way. Then: P (pending), and under the pin E (the email, the commit point), C (the creator), V and X (promotion and removal of the pending value). This matches the table in entry 21 with step 0 from entry 22.
- `_rename_pinned`. A lost acknowledgement of E is re-read strictly (`InternalStore.read_strict`): moved means the rename goes on, not moved means False, and a read fault raises `DbError`. A `modify` that answers False is followed by a fresh load, which counts the rename as landed when a concurrent load already moved the creator. The email is put back only on `CreatorTaken`, or when the fresh load shows another creator.
- Tests (`tests/test_rename_pending_vouch.py`, 33): one per row of the table, plus the fresh store, the email-only vouch and the failed anchor (entry 22), and the seeding race, the stored creator in step 0 and the kept store (entry 23).

The defect the audit found: a request that loaded the actor between E and C
made the rename's own conditional `modify` answer False. The old code then put
the email back, and the next load undid a rename that had landed. It is pinned
by `test_a_load_that_moved_the_creator_first_counts_as_the_rename`, which
fails on `d6527ae`.

### Phase 3: the callback compare-and-swap - VERIFIED

Issues 1-4 are fixed (entries 1-4, 15), and the loop's own regressions were
reverted (entry 16). What remains is recorded as accepted (entry 15) or as
todos (`subscription-subscriber-fault-hardening.md`).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-02-3-16-owner-decided-followups.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Breaker exemption covered the library's own fault 503 | Fixed | entry 1: `X-ActingWeb-Error: callback_in_progress` (`constants.CALLBACK_IN_PROGRESS_CODE`); `tests/test_fanout.py::test_a_fault_503_with_retry_after_still_counts`; entry 15 closes a half-open breaker on that answer |
| 2. A poll stopping at a live claim set the sequence back | Fixed | entry 2: upward-only write, none when `in_flight`; `tests/test_subscription_sync.py::test_the_poll_never_writes_a_lower_sequence` |
| 3. Low-granularity fetch before the duplicate and claim checks | Fixed, with a window accepted | entry 3: `CallbackProcessor.precheck()`; the read-not-claim window is accepted in entry 15 |
| 4. A False sequence write released the claim | Fixed | entry 4; `TestPrecheckAndKeptClaim::test_a_sequence_write_that_answers_false_keeps_the_claim` |
| 5. A failed resync baseline applied `{}` | Reverted to the pre-plan behaviour; todo | entry 5, then entry 16 (the fix could not tell a failed fetch from an empty baseline); `todo/subscription-subscriber-fault-hardening.md` |
| 6. A deadlocked backfill takeover counted as a fault | Fixed | entry 6; `tests/test_property_lookup_races.py::test_a_backfill_takeover_that_deadlocks_is_retried` |
| 7. Changelog rule broken in four entries | Fixed | entry 7, and later wording in entries 17-22 |
| 8. A vouched rename undone by the force-email rewrite | Fixed, then redesigned | entries 8, 14, 17-20, audit 21, 22 |
| 9. Promised tests missing | Fixed except two, accepted | entry 9 (D3 `actor_created` across two sign-ins and PG concurrent first inserts are not added, with the reason given) |
| 10. Hygiene | Fixed, with the twins kept | entry 10 (the sync and async claim paths stay twins; each fix is applied to both) |

Remaining Tasks from the first run: all done. The D12 mint window is in
`todo/resumable-actor-deletion.md`. The `claimed + 1` stall and the lease
sentence are in `todo/subscription-subscriber-fault-hardening.md`. The
`INDEX.md` adoption row is corrected.

## Known limits (added since the first run)

The first run's thirteen limits stand as judged there. The loop added these
accepted items, each recorded in the plan with its reason:

| Limit | Where recorded | Verdict |
| --- | --- | --- |
| The pre-fetch check is a read, not a claim | entry 15 | acceptable: the second delivery answers 503 and a resync recovers |
| The poll's upward-only write reads, then writes | entry 15 | acceptable: both writers are the same subscriber; needs a conditional `DbSubscription.modify` |
| A peer that always answers the in-progress code never trips the breaker | entry 15 | acceptable: a peer can already keep it closed by answering 204 |
| Concurrent renames of one actor are not serialised | entries 20-21, changelog | acceptable as documented (serialise renames of one actor) |
| A `DbError` past the rename's commit point does not say the rename will complete | entry 21, changelog | acceptable: repeating the call is idempotent |
| A stale-vouched actor is vouched again by the rename | entry 22 | intended: without `unvouch` the application vouches |
| No transaction across the actor row and `_internal` | entry 21 | acceptable for 3.16: needs a new backend API |
| Under the pin with no stored email, a rename to a provider id can be undone by a racing sign-in's seeding | entry 23 | acceptable: pre-plan behaviour, narrowed to provider-id targets |

## Remaining Tasks

None for this plan. The deferred work is in the todos the plan names (`subscription-subscriber-fault-hardening.md`, `resumable-actor-deletion.md`, `oauth-email-verified-claim-unchecked.md`), and the adoption and fault-contract block is its own proposed plan (`2026-11-02-3-16-adoption-fault-followups.md`).

## Issues Found

### 1. A rename racing a sign-in's email seeding was silently undone (fixed)
**Severity:** Medium
**Description:** under the pin with no stored email the rename skipped the email write. A vouched sign-in for the old address that loaded the actor before the rename seeded `email := old` after it (`oauth2.py`, `_seed_missing_email` via `set_if_absent`). The next load then moved the creator back.
**Location:** `actingweb/interface/actor_interface.py` (`_rename_vouched`, the `email_led` branch)
**Recommendation:** done in entry 23: under the pin a rename to an address always writes the email.

### 2. Step 0 compared against the handle's cached creator (fixed)
**Severity:** Low
**Description:** a load elsewhere could have moved the creator under the pin, so step 0 was skipped and the current creator lost its only vouch during the rename.
**Location:** `actingweb/interface/actor_interface.py` (`_rename_vouched`, step 0)
**Recommendation:** done: one strict actor-row read.

### 3. A refused rename swapped in an unreadable store; the passphrase was not refreshed (fixed)
**Severity:** Low
**Location:** `actingweb/interface/actor_interface.py` (`_rename_vouched`, `_rename_pinned`)
**Recommendation:** done in entry 23.

## Overall Assessment

Every planned item is implemented. The first verification's ten issues are fixed, except two: Issue 5 is reverted to the pre-plan behaviour and kept as a todo, and parts of Issues 9 and 10 are accepted with their reasons. The Full tier is green on both backends.

The review loop on the vouched rename did not converge until it was audited as one state machine. The stored email under the pin is the commit point, and every row of the table has a test. Each later review found a broken assumption rather than a new race: entry 22, the vouch recorded for the current creator and a fresh store; entry 23, a racing sign-in's email seeding. Each is pinned by a test that fails on the commit before it. This round's findings were in the rename alone, and what remains is recorded as accepted limits. The callback and poll path had no finding in this round beyond one claim that did not hold. The branch is ready for its PR. That PR also carries the PR 167 review fixes, the housekeeping commit and the plan.
