# Verification: 3.16 follow-ups the owner decided (first block)

**Date:** 2026-11-02
**Plan:** thoughts/plans/2026-11-02-3-16-owner-decided-followups.md (all four phases and the five review-fix commits in its Implementation Summary)
**Research:** the todo files the plan names (no research document of its own)
**Branch:** release/3.16.0-owner-decided-followups
**Commit:** `9dca508`

The owner asked for the known limits to be investigated and judged; that is the
section "Known limits" below.

## Automated Check Results

- **Browser QA:** N/A. No phase touches a page; the changed responses (CORS on `/?format=json`, the callback 503) are JSON and are driven through both integrations by tests.
- **Second opinion:** codex (`codex exec -s read-only`, unsandboxed) and a fresh-context Claude on `git diff 445dcf8..9dca508`. Seven findings; two block (Issues 1 and 2). Each phase had already had its own codex round (recorded in the plan).
- **Built-in code review (high, no `--fix`):** ten findings, folded below (Issues 1, 3, 4, 5, 6, 10).
- **Built-in security review:** no finding at the reporting bar. One note below it (Apple's unsigned form-post `user` JSON merged into `user_info`, `handlers/oauth2_callback.py:368`, older than this branch).
- **Scenario-to-test mapping** (codebase-analyzer): every planned change exists; ten promised tests are missing or partial (Issue 9).
- **Known-limits assessment** (a fresh-context agent, read-only): see "Known limits".
- `ruff check`, `ruff format --check`, `pyright`: 0 errors, 0 warnings (493 files).
- `tests/integration/verify_groups.py`: 53 groups documented.
- Full tier, DynamoDB (`make test-all-parallel`): **5,285 passed**, 58 skipped, 1 xfailed.
- Full tier, PostgreSQL (`make test-all-parallel` with the PG environment): **5,094 passed**, 249 skipped, 1 xfailed.
- `sphinx-build -W`: pass.
- Benchmarks (`pytest tests/performance -m benchmark`, alone, DynamoDB): 23 passed after Phase 4 and after its review round (run during implementation, not re-run here).
- Scope: `git diff --stat 445dcf8..HEAD -- actingweb/` lists 19 files, each named by a phase or a recorded review note. Nothing unasked.

## Phase Verification

### Phase 1: Contract fixes - VERIFIED

**Changes verified:**
- D1 `db/dynamodb/trust.py:479-480`, `subscription.py:241-242`, `subscription_diff.py:175-176` return `[]`.
- D9 `interface/integrations/_errors.py:75,123` follow `__cause__` only.
- D10 `handlers/factory.py:137` answers `*` with no credentials.
- D2 `oauth2.py:1283` one fetch, derivations at `:1323,:1338`, the memo on the provider `:312,:354-373` (a recorded deviation), the shim reads it `:955-956`.

**Tests verified:** `tests/test_dynamodb_empty_actor_fetch.py`, `tests/test_db_fault_http.py` (500 on a bug without `from`, `__context__` mapping), both CORS tests, `tests/test_oauth2_github_emails_once.py`. Each regression failed with its fix stashed (recorded in the plan).

**Deviations:** the memo's home (accepted). The 500 test covers `except DbError` on Flask and `except Exception` on FastAPI, not both forms on both; Google's zero-request case is not asserted (Issue 9).

### Phase 2: Sign-in and uniqueness - VERIFIED, with Issue 8

**Changes verified:** D11 `oauth2.py:2534-2539` raises before the passphrase rotation at `:2547`; D12 `:2570` revokes again after `:2567`; D3 `_seed_missing_email` `:2265` through `set_if_absent` `:2288`, called at `:2329` and `:2502`; D4 `actor.py:355-371`; D5 sweep removed (`actor.py:677-680`), command at `maintenance/unique_creators.py:452,840,848,905`; D8 `oauth2.py:1711,1738-1740`, `interface/actor_interface.py:466-491`, cleared by the clean at `oauth2.py:2602`.

**Security property, demonstrated:** the rename window is closed for both creator types by `tests/test_rename_pending_vouch.py::TestRenameWindow::test_both_creators_read_vouched_during_the_rename[email|provider-id]`, which asserts `seen == {"old": True, "new": True}` from inside the rename; with `actor_interface.py` stashed it fails. The fail-closed K is `tests/test_adoption_unknown_and_revoke.py::TestUnknownDeletionStatus::test_a_clean_in_place_refuses_and_changes_nothing`, asserting `pytest.raises(DbError)` and the passphrase, marker and trusts unchanged.

**Deviations:** D5's own record-aware rename; the D3 tests live in `test_adoption_unknown_and_revoke.py`; the D12 test checks the call order, not a minted token (all recorded). Missing: D4 "holder equal to this actor", D3 "`actor_created` fired once over both sign-ins", D11 parametrised with `creator_changed` rather than `email_verified == "false"` (Issue 9).

### Phase 3: The callback check as a compare-and-swap - ISSUES FOUND

**Changes verified:** `callback_processor.py` `_cas_state` `:171-216` (nonce, strict re-read, a landed retry counts), `_claim` `:218-232` with the batch's last sequence, `_live_claim` and the 60-second lease `:71-78,:234-246`, `IN_PROGRESS` `:35`, release on `DbError` `:596-598`, the growing resync version `:342-350`; the callback 503 (`handlers/callbacks.py:417`), `SubscriptionSyncResult.in_flight` (`interface/subscription_manager.py:159`), the breaker exemption (`fanout.py:520`).

**Security/integrity property, demonstrated:** a single handler run under two concurrent deliveries on the real store, `tests/integration/test_callback_processor_concurrency.py::test_two_concurrent_deliveries_run_the_handler_once` (asserts `runs == [1]`, results PROCESSED and IN_PROGRESS); with the processor stashed it fails.

**Issues:** the breaker exemption swallows the library's own fault 503 (Issue 1); the poll writes its lower sequence after stopping at a claim (Issue 2); the low-granularity fetch runs before the duplicate and claim checks (Issue 3); a False sequence write releases the claim (Issue 4); a failed resync baseline fetch still applies `{}` (Issue 5).

### Phase 4: Reverse lookup - VERIFIED, with Issue 6

**Changes verified:** DynamoDB `db/dynamodb/property.py:294-335` (consistent read, conditioned writes, one budget), `_write_indexed` takeover `:473-489`, `_heal_lookup` `:372-377`, one-transaction delete `:522-573`, owner-conditioned releases (`delete_if_owner`, `property_lookup.py:272`, used at `property.py:587,957`), `take_over` `:212` with the actor-gone branch; PostgreSQL `db/postgresql/property.py:291-402` (`FOR UPDATE`, first-insert retry, deadlock retry with backoff), `claim_in_transaction` and `owner_holds_in_transaction` (`db/postgresql/property_lookup.py:19,101`, owner row locked by key); backfill `maintenance/property_lookup.py:475-516,823-912`.

**Security property, demonstrated:** a takeover never takes a row from an owner that holds the value. DynamoDB: `tests/test_property_lookup_races.py::TestStaleOwner::test_an_owner_that_reacquires_during_the_takeover_keeps_the_row` (asserts `_lookup(x) == a`). PostgreSQL: `test_a_takeover_waits_for_the_owners_write_in_flight` (two connections; asserts the takeover waited and `_lookup(x) == a`); it failed on the first implementation, which is how the predicate-in-`WHERE` defect was found. A late release cannot undo a takeover: `TestReleaseAfterTakeover::test_a_late_release_leaves_a_row_taken_over_meanwhile` (fails on the pre-review code).

**Deviations:** module functions instead of a `DbPropertyLookup.take_over` method (not recorded in the plan; acceptable); no advisory lock; codes read by offset (both recorded). Missing: D15 "stale handle holding x with z stored, then `set(x)`", PostgreSQL concurrent first inserts, an owner-read fault test per backend (Issue 9). Issue 6 (backfill deadlock).

## Known limits

The plan records thirteen limits. Each was checked against the code, for how it is reached, what the user sees, and whether it regresses 3.15.1 or the pre-plan tree (`445dcf8`).

| # | Limit | Reached by | Consequence | Regression? | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | The claim's lease is not renewed, compares clocks across processes, and a 3.15 instance overwrites the claim row | a handler over 60 s (not on Lambda behind API Gateway, capped at 29 s), clocks skewed over 60 s, a rolling deploy | the batch is applied twice; logged only when a release loses | no: before, every concurrent delivery could double-apply | acceptable as documented |
| 2 | A sequence-write fault after the handlers keeps the claim, which expires | a store fault on the subscription row at that instant | auto-storage re-applies after 60 s; ERROR "Sequence write ... faulted" | no: 3.15.1 and pre-plan re-ran on the next poll | acceptable as documented (one line in the subscriber-hardening todo) |
| 3 | `claimed + 1` arriving during a claim waits in pending | bursty writes fanned out concurrently: fairly common | delayed, not lost; a quiet subscription stalls until a poll; DEBUG only | no: the gap branch had the same shape | **acceptable, needs a todo**: the plan's "the next in-order arrival" is optimistic, since the gap branch never drains pending; the winner should drain `claimed+1..` after its sequence write |
| 4 | A low-granularity diff is deleted by the subscriber's fetch | a failed delivery of one | with auto-storage the next poll applies the baseline; without it (hook-only consumers) the diff is lost silently | no: 3.15.1 applied an empty diff and advanced | acceptable as documented, **but** Issue 3 is the part that is fixable |
| 5 | The resync reset is unconditional; the winner's sequence write is not conditioned | a publisher or application resync during a live claim | `last_seq` can end below the baseline; diffs in between re-applied | no | acceptable as documented |
| 6 | PostgreSQL writers swapping values deadlock | two writers of one value within about a second | about 1 s per deadlock, then `DbError` after three (`PROPERTY_WRITE_RACE_EXHAUSTED`), rolled back | new with the takeover's locking, bounded and loud | acceptable as documented |
| 7 | A stored `""` reads as "no value" on DynamoDB | only a write from outside the library | every `set()` of that property 503s; delete is a silent no-op (not in the plan's note) | no library path | acceptable as documented (a three-line fix when convenient) |
| 8 | With the flag off, D11's 503 after a replacement leaves siblings out of the retry's summary | flag off, a factory sibling, and an UNKNOWN read together | the summary is incomplete; per-sibling `actor_deleted` hooks fired | no: before, UNKNOWN cleaned in place | acceptable as documented |
| 9 | D12: a grant that loaded before the second revoke and writes after survives | two consecutive sub-second races by the previous creator | a token for the unproven creator survives; not logged | no: pre-plan's window was wider | **acceptable, needs a todo**: the plan says `todo/resumable-actor-deletion.md` holds it, and it does not |
| 10 | Two concurrent `modify_creator` renames share the pending slot | the application racing itself on one actor | the actor is cleaned in place (WARNING) | narrowed | acceptable as documented (the docs say serialise) |
| 11 | Before `enable`, the default-creator move is a read then a rename | a first sign-in for that address at that instant | two actors share it; `enable` refuses, `report` lists them | no | acceptable as documented |
| 12 | D3's seeding pins the creator under the flag | intended | `PUT trust/trustee` to another address answers 400 | intended behaviour change, in the changelog | acceptable as documented |
| 13 | DynamoDB backfill: the first current holder takes a stale row | two current holders of a stale value | both backends report the collision and leave the name unmarked | new, not silent | acceptable as documented |

**Limits not on the plan's list:** Issues 1-5 and 8 below were found by this verification and are not limits the plan accepted; Issues 1 and 2 are regressions introduced by the plan's own review rounds.

## Remaining Tasks

- [ ] Fix Issues 1 and 2 before the PR; Issues 3-8 in the same `/iterate_plan` pass.
- [ ] Add the missing tests (Issue 9).
- [ ] `thoughts/todo/resumable-actor-deletion.md`: a bullet for D12's mint-path window (limit 9).
- [ ] `thoughts/todo/subscription-subscriber-fault-hardening.md`: bullets for limit 3 (drain `claimed+1..` after the sequence write) and the lease sentence for limit 2.
- [ ] `thoughts/todo/INDEX.md:51`: the adoption row still names J, K and the callback check.

## Issues Found

### 1. The breaker exemption also covers the library's own database-fault 503
**Severity:** High
**Description:** `fanout.py:520` "`elif status == 503 and response.headers.get("Retry-After"):`" returns without `cb.record_failure()`. Every transient `DbError` answer carries `"Retry-After": RETRY_AFTER_SECONDS` (`interface/integrations/_errors.py:102`). A subscriber running this library whose store is down never trips the publisher's breaker; a half-open breaker that gets this answer stays half-open (`fanout.py:127-128`). Introduced in `b8ca5c3`; the changelog's "a 503 without it still counts" never applies to a library subscriber.
**Location:** `actingweb/fanout.py:520`
**Recommendation:** exempt only the in-progress answer, marked distinctly (an `X-ActingWeb-Error` code or body code the fault 503 does not use), and count every other 503.

### 2. A poll that stops at a live claim can set the sequence back
**Severity:** High
**Description:** after `if result == ProcessResult.IN_PROGRESS: ... break` (`interface/subscription_manager.py:1093-1097`, and the async twin near `:1973`), the poll still writes `sub_obj.handle.modify(seqnr=max_sequence)` unconditionally (`:1237`). The claiming callback writes `seqnr = claimed` through `_update_last_seq` (`callback_processor.py:299`). If the callback commits first, the poll's lower write lands after it: `last_seq` drops below `claimed_seq`, redeliveries answer IN_PROGRESS until the lease ends and then run the handler again (the double apply D13 set out to stop), and the next sequence reads as a gap. Before the break, both paths wrote the same value.
**Location:** `actingweb/interface/subscription_manager.py:1237` (and its async twin)
**Recommendation:** write the sequence only upward (conditioned on the stored value being lower), or skip the poll's final write when `in_flight`.

### 3. The low-granularity fetch runs before the duplicate and claim checks
**Severity:** Medium
**Description:** `handlers/callbacks.py:584-603` fetches the diff, and a non-200 answer now returns `_callback_retry_later` (503) before `process_callback_sync` decides DUPLICATE or IN_PROGRESS (`:748`). A redelivery of an already applied sequence (its diff deleted by the first fetch, `handlers/subscription.py:598`) therefore answers 503 every time instead of 204; and a delivery inside a live claim deletes the diff with its fetch before learning it must not process it, so a released claim loses the data on a quiet subscription.
**Location:** `actingweb/handlers/callbacks.py:584`
**Recommendation:** check `sequence <= last_seq` (204) and a live claim (503) before the fetch.

### 4. A sequence write that answers False releases the claim and re-runs the handlers at once
**Severity:** Medium
**Description:** the `recorded is False` branch calls `_release_claim(..., last_seq)` (`callback_processor.py:650`, sync twin `:1010`), so the next poll runs the batch again immediately; the `DbError` branch just above keeps the claim for exactly that reason (at-most-once). Added in `6554c76`.
**Location:** `actingweb/callback_processor.py:650`
**Recommendation:** keep the claim on that branch too, as the fault branch does.

### 5. A failed resync baseline fetch still applies an empty baseline
**Severity:** Medium
**Description:** the resync branch of `_process_subscription_callback_internal` falls back to `callback_data = {}` on a fetch failure (`handlers/callbacks.py:557`), then `_handle_resync` clears pending, resets state and moves the sequence to the resync's: the "sequence advances past data never applied" defect this plan fixed for low granularity. Older than the plan.
**Location:** `actingweb/handlers/callbacks.py:557`
**Recommendation:** answer 503 and process nothing, as the low-granularity branch now does.

### 6. A deadlock in the PostgreSQL backfill's takeover counts as a fault
**Severity:** Low
**Description:** `_pg_take_over_one` catches every exception as `stats.fault()` (`maintenance/property_lookup.py:908-912`), including `DeadlockDetected`/`SerializationFailure` against a live writer, which the runtime retries. The name stays unmarked until the operator reruns.
**Location:** `actingweb/maintenance/property_lookup.py:908`
**Recommendation:** retry the row's transaction on those two errors before counting a fault.

### 7. The changelog rule is broken in four entries
**Severity:** Low
**Description:** the plan's rule gives every change against 3.15.1 a **Behavior change:** sentence. The D13 entry (`CHANGELOG.rst:1144`, a 503 where there was a 204), the D2 entry (`:1173`) and the D1 entry (`:1185`, `None` to `[]` in prose) have none. The D12 sentence (`:103-106`) says a token obtained during the clean "does not outlive it", while the plan records limit 9.
**Location:** `CHANGELOG.rst:103,1144,1173,1185`
**Recommendation:** add the sentences; reword D12 to the window it closes.

### 8. A vouched SDK rename can be undone by the force-email rewrite
**Severity:** Medium (to confirm with a test)
**Description:** `_rename_vouched` renames through `Actor.modify(creator=...)` (`interface/actor_interface.py:479`), which does not move `store.email`; under `force_email_prop_as_creator` the next `Actor.get` rewrites the creator back to the stored email (`actor.py:400-417`) unless another actor holds it. Older than the plan, but D3's seeding gives more actors a stored email, and the D3 behaviour-change sentence names only `PUT trust/trustee`. Traced, not run.
**Location:** `actingweb/interface/actor_interface.py:479`
**Recommendation:** write a test; then either move `store.email` with a vouched rename to an address, or document it beside the D3 sentence.

### 9. Promised tests that are missing or partial
**Severity:** Low
**Description:** from the mapping: the bug-without-`from` 500 in both forms on both frameworks; Google's zero `/user/emails` requests; D4 with a holder equal to this actor; D3 `actor_created` once over two sign-ins; D11 with `email_verified == "false"`; a lost gap-timeout CAS not resetting `last_seq`; a handler raising after the claim; D15 stale handle with `set(x)`; PostgreSQL concurrent first inserts; an owner-read fault per backend.
**Location:** the plan's New Tests sections
**Recommendation:** add them in the iteration, each failing before its fix where one exists.

### 10. Hygiene
**Severity:** Low
**Description:** `_condition_failed` is never called (`db/dynamodb/property.py:17`; `delete_if_owner` repeats it inline); `_set_state`'s `expected_version` branch is dead (`callback_processor.py:332`, both callers pass `None`); the claim logic is duplicated in the async and sync paths (`callback_processor.py:~470-660` and `~830-1020`), so Issues 2 and 4 need two fixes; a takeover reads the owner's actor twice (`db/dynamodb/property_lookup.py:239` and `owner_holds`). The plan's "older than 3.16 and not widened here" for the `email_verified` gap is not exactly true: D3 seeds `user_info["email"]` for a provider-id creator (`oauth2.py:2262`), rarely reachable.
**Location:** as cited
**Recommendation:** remove the dead code; share the claim core; pass the actor read through; correct the plan line.

## Overall Assessment

Every planned item is implemented, the security properties the plan claims (the rename window closed for both creator types, the fail-closed K, no takeover from a live owner, a takeover a late release cannot undo) are each pinned by a test that fails on the old code, and the Full tier is green on both backends (DynamoDB 5,285, PostgreSQL 5,094). Phases 1, 2 and 4 are sound.

The callback work is not ready to merge. The review rounds that extended D13 introduced two regressions: the breaker no longer trips on a subscriber whose store is down (Issue 1), and a poll that stops at a live claim can set the sequence back and bring the double apply back (Issue 2). Issues 3-5 are smaller holes in the same path. Of the thirteen known limits, eleven are acceptable as documented and two need a todo line (3 and 9); none is a regression against 3.15.1 or the pre-plan tree. Recommended next step: `/iterate_plan` on Issues 1-8, then a re-verification, before the PR.
