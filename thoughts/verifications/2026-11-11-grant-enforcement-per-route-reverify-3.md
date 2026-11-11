# Verification: a peer's grant is the answer on every route (re-run 3)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** e4fc267 (iterations 37-42 on top of `6f2becd`)

Fourth verification. Scope: `6f2becd..e4fc267`, checked against re-run 2's
Issues 1-13, reviews scaled to the delta.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5068 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6520 / 6317 passed
  after the one test whose premise entry 37 changed was given an override
  (plan entry 42); that file passes on both backends.
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `e4fc267`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in
  the session scratchpad `ov3/`) and a fresh-context Claude reviewer.
- **Code review** (built-in, high): 10 findings.
- **Security review**: no high-confidence vulnerability; one Medium below
  the bar (Issue 1), two correctness notes.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-10-grant-enforcement-per-route-reverify-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. No exclusion, deep diff dropped | Fixed | Entry 39 |
| 2. Withheld sent as `null` | Fixed for parsed values | Entry 39; text beyond the parser is uneven (Issue 1, 3) |
| 3. Hook bridge deadlock | Fixed | Entry 38; fork safety and cancel semantics (Issue 7) |
| 4. Stale-override rule | Decided, implemented | Entry 37; races remain (Issue 2) |
| 5. Check and delete separate | Narrowed, not closed | Issue 2 |
| 6. Unconditional rollback | Narrowed, not closed | Issue 2 |
| 7. Re-paired row deleted | Fixed | Entry 38; the late `TrustReplaced` after cleanup (Issue 6) |
| 8. REST parses raise | Fixed | Entry 39; paths now disagree (Issue 3) |
| 9. Later POST key refused | Fixed | Entry 40 |
| 10-12. Status, secret, changelog | Fixed | Entry 41 |
| 13. Cleanups | Fixed, one regression | Entry 41; `-32000` detection (Issue 4) |

## Remaining Tasks

- [ ] Issues 1-8 (a fifth iteration batch).

## Issues Found

### 1. Text beyond the parser skips sub-path and read hooks on a direct GET
**Severity:** Medium
**Description:** the `TOO_DEEP` branch writes the whole stored text before
the sub-path walk and the `get` hook; a peer granted only
`notes/public/*` (no exclusion) reads all of `notes`; a hook's redaction or
404 never runs. It failed closed (500) before.
**Location:** `actingweb/handlers/properties.py:711`.
**Recommendation:** one rule for text beyond the parser: never sent to a
peer (any path), the owner reads it as plain text is read.

### 2. The re-type rollback can widen a concurrent authorisation (decision taken)
**Severity:** Medium
**Description:** two authorisations re-typing to the same type: one's
failed drop re-reads the other's write, sees "its" type and puts the old,
wider type back; the read-then-delete of the override and the
read-then-write of the rollback are not atomic, and the store has no
conditional write to make them so. An unreadable override reads as none.
The removal log claims a removal when nothing was removed.
**Location:** `actingweb/interface/trust_manager.py:488`, `:493`, `:540`, `:546`, `:752`.
**Recommendation:** owner decision 2026-11-11: a client row's override
whose `trust_type` differs from the row's type is inert in the evaluator;
the re-type changes the type and deletes the old override as cleanup, with
no rollback.

### 3. Text beyond the parser is handled differently on each path
**Severity:** Low
**Description:** a write is refused with no exclusion stated
(`properties.py:408`), a diff blob that cannot be parsed is dropped
whatever the grant (`actor.py:4104`) while a no-exclusion `_diff_part`
sends the text, the developer view sends it with no exclusion, the listing
lists it as a string. Every simple GET parses twice; the listing re-parses
per key. No handler test uses text beyond the parser (the depth that
reaches it differs between Python 3.11 and 3.14).
**Location:** `actingweb/handlers/properties.py:408`, `:711`, `:819`;
`actingweb/actor.py:4104`; `actingweb/interface/authenticated_views.py`.
**Recommendation:** with Issue 1's rule; parse once; handler tests with a
200,000-deep string.

### 4. A method hook's own `-32000` answers 403
**Severity:** Medium
**Description:** the code-based detection also matches a non-JSON-RPC hook
result carrying that code (the start of JSON-RPC's server-error range).
**Location:** `actingweb/handlers/methods.py:243`.
**Recommendation:** check only JSON-RPC answers, whose top-level `error` is
always the library's.

### 5. Hygiene in the revocation executor and hooks
**Severity:** Low
**Description:** the process-wide executor is not reset in a forked child;
a cancelled coroutine hook that swallows the cancellation keeps running
(undocumented).
**Location:** `actingweb/interface/subscription_manager.py:463`;
`actingweb/interface/hooks.py:1392`.
**Recommendation:** reset at fork; document the cancel semantics.

### 6. A `TrustReplaced` after the cleanup ran is logged as harmless
**Severity:** Low
**Description:** the conditional row delete can lose to a re-pair after the
hooks fired and subscriptions went (the remaining window of the deletion
invariants); the log says "the new row is kept" at INFO.
**Location:** `actingweb/interface/subscription_manager.py:1706`, `:2798`.
**Recommendation:** WARNING naming what ran.

### 7. Tests that do not show their bug
**Severity:** Low
**Description:** the deadlock test's helper wires only the sync delete, so
on the old code it fails by wiring, not by deadlock; the changed
integration test passes on the code before its fix (a smoke test).
**Location:** `tests/test_revoked_trust_detection.py`;
`tests/integration/test_oauth2_trust_binding.py:461`.
**Recommendation:** wire the async delete as the old code used it; say
what the integration test covers.

### 8. `drop_excluded`'s `None` overloads JSON null
**Severity:** Low
**Description:** each caller repeats the "filtered is None and value is not
None" test.
**Location:** `actingweb/permission_evaluator.py:229`.
**Recommendation:** accepted for now with a helper (`withheld(value,
filtered)`) used by every caller; a distinct sentinel would touch every
response path again.

## Overall Assessment

The fourth batch closed re-run 2's issues on their tested paths and Emm's
suite is unchanged. The remaining defects are at the edges the fixes
themselves opened: text nested beyond the parser (Issues 1, 3) and the
re-type's rollback under concurrency (Issue 2, now decided). Not clean;
a fifth batch follows.
