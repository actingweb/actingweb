# Verification: a peer's grant is the answer on every route (re-run 2)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-10
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 6f2becd (iterations 28-36 on top of `0cef4d6`)

Third verification. Scope: `0cef4d6..6f2becd`, checked against re-run 1's
Issues A-K, with reviews scaled to the delta. The phases were verified in
the first document and are not re-walked.

## Automated Check Results

- **ruff check / ruff format --check / pyright**: pass, 0 errors, 0
  warnings.
- **verify_groups.py**: pass (57 groups, wire rows registry consistent).
- **Unit**: 5054 passed before the guard marker on `_put_type_back`
  (`test_no_broad_except_folds_a_db_fault_unmarked` caught it); passes
  after.
- **DynamoDB, `make test-all-parallel`**: 6507 passed, 60 skipped, 1
  xfailed.
- **PostgreSQL, `make test-all-parallel`**: 6304 passed, 263 skipped, 1
  xfailed.
- **PostgreSQL, sequential**: not re-run (no storage change in the delta;
  the known `test_callback_processor_concurrency` failure is `master`'s).
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `6f2becd` (library worktree at `6f2becd`, `emm-3-16`
  unchanged, environment 9): PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed. The same five baseline failures; no new one.
- **Browser QA:** not re-run; the only page change is which errors reach
  the refusal page (covered over HTTP by
  `tests/test_oauth2_confirm_refusal.py`).
- **Second opinion:** outside-voice agent, codex (`codex exec -s
  read-only`, unsandboxed) and a fresh-context Claude reviewer; two
  findings reproduced (prune recursion at 1500 deep; the hook bridge
  deadlocking with a 2-worker pool).
- **Code review** (built-in, high): 10 findings.
- **Security review** (scoped to the delta): no high-confidence
  vulnerabilities; two correctness notes (owner-set override type removed
  at re-consent; the notice's Bearer secret), folded below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-10-grant-enforcement-per-route-reverify-1.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A. Stuck re-type | Fixed, with new edges | Entry 28; the stale-override rule removes deliberate overrides (Issue 4) and races an owner's write (Issue 5); the rollback is unconditional (Issue 6) |
| B. Async `sync_peer` hook order | Fixed in order; the bridge can deadlock | Entry 29; Issue 3; a re-paired row is still deleted (Issue 7) |
| C. Deep values in the filter | Partly open | Entry 30; no-exclusion prune recursion (Issue 1), `null` instead of withheld (Issue 2), REST parses (Issue 8) |
| D. Absent-row cleanup window | Accepted | Entry 35, invariants note |
| E. Bulk `items` hook refusal | Fixed for that path | Entry 31; the same class on a plain POST key (Issue 9) |
| F. Application targets | Decided (approval only) | Entry 35, test and guide |
| G. Confirmation JSON | Fixed | Entry 32; `server_error` answers 400 (Issue 10) |
| H. Secret written with the approval | Fixed for the URL | Entry 33; the header still carries the old secret (Issue 11) |
| I. Refused JSON-RPC 200 | Fixed | Entry 34; the 403 travels as handler state (Issue 13) |
| J. Duplication | Fixed for those two | Entry 29, 34; a third copy of the hook loop (Issue 13) |
| K. Type hint | Fixed | Entry 35 |

## Remaining Tasks

- [ ] Issues 1-13 below (a fourth iteration batch).
- [ ] Decision on Issue 4 (what counts as a client's stale override).

## Issues Found

### 1. No exclusion, deep value: the diff is silently dropped
**Severity:** Medium
**Description:** `_diff_part` calls the recursive `_prune_emptied` even when
`drop_excluded` returned the value unwalked; ~1500 levels raise
`RecursionError`, which `filter_subscription_blob` turns into "no diff".
Reproduced.
**Location:** `actingweb/actor.py:4033` (`return _prune_emptied(value, kept)`), `:4148`.
**Recommendation:** skip the prune with no exclusion (or make it
iterative); test `_diff_part` and `filter_subscription_blob` at 1500 deep.

### 2. "Withheld" is sent as `null`
**Severity:** Medium
**Description:** the full-state fallback, the REST listing and the direct
read put `None` where a too-deep value was; a full-state `{"settings":
null}` wipes the subscriber's copy, the listing shows the name with null.
**Location:** `actingweb/actor.py:4276`; `actingweb/handlers/properties.py:735`, `:823`.
**Recommendation:** leave the key out (full state, listing); a direct read
of one is refused rather than answered `null`; test each.

### 3. The hook bridge can deadlock the default executor
**Severity:** Medium
**Description:** the delete holds a default-pool thread blocked on
`run_coroutine_threadsafe(...).result()` (no timeout) while the coroutine
hook may need a default-pool thread (`*_async` calls use `to_thread`).
With concurrent revocations ≥ the pool size, everything waits. Reproduced
with a 2-worker pool. A loop shutting down also leaves `.result()` waiting.
**Location:** `actingweb/interface/hooks.py:1374-1376`;
`actingweb/interface/subscription_manager.py` (`sync_peer_async`).
**Recommendation:** run that delete on a thread outside the default pool
and bound the wait; test with a saturated default pool.

### 4. Any override for another type is "stale" (decision needed)
**Severity:** Medium
**Description:** `_stale_client_override` deletes, at every
re-authorisation, an override whose `trust_type` differs from the
approved type, including one an application or owner set deliberately
(`create_permission_override(..., trust_type=...)`,
`update_permissions` accepts `trust_type`). The user approved that type,
so it is not a widening past consent, but the owner's narrowing is gone
silently. Also one uncached read per re-authorisation.
**Location:** `actingweb/interface/trust_manager.py:700`, `:731`.
**Recommendation:** see the question to the owner.

### 5. The stale check and the delete are separate reads
**Severity:** Medium
**Description:** an owner's permissions PUT between `_stale_client_override`
and `_drop_client_override` is deleted.
**Location:** `actingweb/interface/trust_manager.py:731`, `:745`.
**Recommendation:** compare and delete on the same read (re-read right
before the delete), per the Issue 4 decision.

### 6. The rollback overwrites the type unconditionally
**Severity:** Low
**Description:** two concurrent authorisations: B writes T2 and drops the
override, A's drop fails and A writes T0 back over B's T2.
**Location:** `actingweb/interface/trust_manager.py:516`.
**Recommendation:** put back only while the row still holds the type this
call wrote.

### 7. `sync_peer` deletes a row re-paired after the probe
**Severity:** Low
**Description:** neither twin passes `expected_secret`; a re-pair between
the "gone" probe and the delete loses its new row, and `trust_deleted`
fires for it.
**Location:** `actingweb/interface/subscription_manager.py:1654`, `:2730`.
**Recommendation:** pass the secret the probe used.

### 8. REST parses still raise on text too deep for the parser
**Severity:** Low
**Description:** `_parsed`, the direct GET and the listing's `json.loads`
(and `actor.py:4098`) catch `ValueError` only; such a stored value answers
500 for every reader and every peer write to it.
**Location:** `actingweb/handlers/properties.py:273`, `:703`, `:791`;
`actingweb/actor.py:4098`.
**Recommendation:** route through `as_json_object`.

### 9. A hook refusing a later POST key leaves subscribers stale
**Severity:** Medium
**Description:** the same class as re-run 1 Issue E, on a plain POST: keys
written before the refused one are stored but no diff is registered.
**Location:** `actingweb/handlers/properties.py:1984`, `:1604`, `:1443`.
**Recommendation:** register `pair` on `_HookDenied`, then answer 403;
test through the route.

### 10. A server failure completing a confirmation answers 400
**Severity:** Low
**Location:** `actingweb/handlers/oauth2_endpoints.py:759`.
**Recommendation:** `server_error` (and a missing error) is 500.

### 11. The approval notice authenticates with the old secret
**Severity:** Low
**Description:** pre-existing, now inconsistent with entry 33: the URL
follows the new secret, the `Authorization` header does not.
**Location:** `actingweb/actor.py:2084`.
**Recommendation:** `secret or this_trust["secret"]`; assert the header.

### 12. Changelog leads
**Severity:** Low
**Description:** the template fallback's 500 (every web UI template) and
the JSON-RPC 403 have no bold **Behavior change:** sentence.
**Location:** `CHANGELOG.rst`; `actingweb/interface/integrations/flask_integration.py:1507`.
**Recommendation:** add them.

### 13. Cleanups
**Severity:** Low
**Description:** `drop_excluded` walks a value twice (`_deeper_than`, then
`_drop`); `execute_lifecycle_hooks_for_loop` is a third copy of the hook
loop's error policy; the JSON-RPC 403 travels as `self._jsonrpc_refused`;
tests call helpers rather than routes (bulk refusal), check only the URL
(notice), and nothing covers `template_fallback_status`.
**Location:** `actingweb/permission_evaluator.py:774`;
`actingweb/interface/hooks.py:1363`; `actingweb/handlers/methods.py:241`.
**Recommendation:** one depth-bounded walk; one hook loop with a per-hook
runner; return the status with the result; route-level tests.

## Overall Assessment

The third batch closed A, B (ordering), E (bulk), G, H (URL), I, J and K,
all checks are green and Emm's suite is unchanged. It is not clean: the
depth handling covers the exclusion path but not the plain one (Issue 1,
reproduced) and turns "withheld" into `null` (Issue 2); the async hook
bridge can deadlock under load (Issue 3, reproduced); and the stale
override rule needs a decision (Issue 4). Not ready to merge until 1-3, 5,
9 and the Issue 4 decision land, with route-level tests.
