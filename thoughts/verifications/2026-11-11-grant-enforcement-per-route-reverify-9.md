# Verification: a peer's grant is the answer on every route (re-run 9)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 83648e7 (iterations 66-68 on top of `5a334b5`)

Tenth verification. Scope: `5a334b5..83648e7`, checked against re-run 8's
Issues 1-6.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5099 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6554 / 6350 passed
  (one PostgreSQL parallel timing failure in an untouched test, passing
  alone three times; entry 68).
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `83648e7`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov9/`) and a fresh-context Claude reviewer.
- **Code review** (built-in, high): 9 findings.
- **Security review**: no high-confidence finding; every reader agrees with
  what a standard JSON client parses; notes folded below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-8.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. BOM in one caller | Fixed for reads and the write check | Entry 66; sub-path PUT/DELETE (Issue 3), bytes (Issue 2) |
| 2. Trust PUT bodies | Fixed | Entry 67 |
| 3. Rule types | Fixed at intake; `null` passes, merge not closed (Issue 1) | Entry 67 |
| 4. Owner bytes | Fixed, opened Issue 2 | Entry 66 |
| 5. Docs | Fixed; one sentence overstates (Issue 5) | Entry 67 |
| 6. Tests | Fixed in one file; the literal is back in another (Issue 5) | Entry 67 |

## Remaining Tasks

- [ ] Issues 1-5 (an eleventh iteration batch).

## Issues Found

### 1. A `null` rule list, or one stored another way, still drops base exclusions
**Severity:** Medium
**Description:** the intake check skips a key present with `null`, and
`merge_permissions` replaces the base value with whatever the override
holds (`None`, a string): the trust type's `excluded_patterns` (and
`denied`) stop applying. Rows stored through the Python store API, or
before 3.16, are not checked at all.
**Location:** `actingweb/trust_permissions.py:140`, `merge_permissions`.
**Recommendation:** the merge fails closed (a non-list keeps the base
value); the intake refuses a key present with `null`.

### 2. Undecodable bytes skip the filter and decode leniently on output
**Severity:** Medium
**Description:** bytes holding JSON with one invalid UTF-8 byte are not JSON
to `as_json_object` (strict), then `decode("utf-8", "replace")` hands the
client a valid object, excluded keys included.
**Location:** `actingweb/handlers/properties.py:770`.
**Recommendation:** one decode, strict; undecodable bytes are not sent.

### 3. Writes and reads disagree on BOM text; parsing details
**Severity:** Low
**Description:** sub-path PUT and DELETE parse with `json.loads` (409/404
where a read finds the part); `_client_text` strips every leading BOM where
a client strips one; `_parsed` parses failing JSON-looking text twice.
**Location:** `actingweb/handlers/properties.py:1324`, `:2236`, `:279`;
`actingweb/permission_evaluator.py:353`.

### 4. The owner-visible normalisation is undocumented
**Severity:** Low
**Description:** BOM/UTF-16 text is now parsed for the owner too (stored as
`json.dumps`, read re-serialised, hooks receive a dict).
**Location:** `CHANGELOG.rst`.
**Recommendation:** a **Behavior change:** sentence.

### 5. Wording, duplication, tests
**Severity:** Low
**Description:** the guide says an update "refuses" identity fields (it
ignores and logs them) and that a create sets `updated_at` (it does not);
`notes` and unknown keys are not type-checked; `_CATEGORIES` repeats the
editable fields; the stored-text tests hold an invisible BOM literal
again; the trust PUT comment gives the wrong pre-fix behaviour.
**Location:** `docs/guides/access-control.rst:773`;
`actingweb/trust_permissions.py:115`; `tests/test_grant_stored_text.py:383`;
`actingweb/handlers/trust.py:900`.

## Overall Assessment

The re-run found no high-confidence vulnerability and every reader now
agrees with a JSON client. Two Mediums remain at the merge and the output
decode (Issues 1, 2). An eleventh batch follows; no owner decision is
needed.
