# Verification: a peer's grant is the answer on every route (re-run 8)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 5a334b5 (iterations 62-65 on top of `78c8e6d`)

Ninth verification. Scope: `78c8e6d..5a334b5`, checked against re-run 7's
Issues 1-6; the security review swept every peer read path for JSON text.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5093 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6548 / 6345 passed
  (a first run with `updated_at` stamped changed 97 wire rows in that field
  only; the stamp was dropped, entry 64).
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `5a334b5`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov8/`; nothing of Medium) and a fresh-context Claude
  reviewer.
- **Code review** (built-in, high): 8 findings.
- **Security review**: one Medium (Issue 1), below the high bar.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-7.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. JSON text on the text branch | Fixed on that branch only | Entry 62; the other paths (Issue 1) |
| 2. Failed restore | Fixed | Entry 63 |
| 3. SECURITY check | Fixed | Entry 63; wording (Issue 5) |
| 4. Edges | Fixed | Entry 63; `null` and the trust PUT body (Issue 2) |
| 5. Uncached-read test | Fixed | Entry 63 |
| 6. Accepted | Accepted | Entry 64 |

## Remaining Tasks

- [ ] Issues 1-6 (a tenth iteration batch).

## Issues Found

### 1. The BOM handling lives in one caller
**Severity:** Medium
**Description:** `as_json_object` (str) and `_parsed` do not read JSON text
behind a byte-order mark, or JSON that is UTF-16 once its UTF-8 bytes are
decoded (what `response.json()` does); only the direct read's text branch
strips the mark. The write check (`_touches_excluded`, the views') lets a
peer overwrite or delete such a value holding an excluded part; diffs, the
full state, the listing and the views send it unfiltered (as a string
value).
**Location:** `actingweb/permission_evaluator.py:324`;
`actingweb/handlers/properties.py:274`, `:412`, `:752`.
**Recommendation:** parse a string as a client parses its UTF-8 bytes, in
the helpers, for every caller.

### 2. Trust PUT bodies
**Severity:** Medium (regression)
**Description:** `"permissions": null` (what the trust GET returns for a row
without an override) is now 400, so a client echoing the GET loses its
approval; a body that is not an object is a 500.
**Location:** `actingweb/handlers/trust.py:898`, `:914`.
**Recommendation:** `null` is no change; a non-object body is 400.

### 3. Grant values are not type-checked
**Severity:** Low
**Description:** `{"properties": {"excluded_patterns": "private/*"}}` is
stored; the merge replaces the base list with the string, which the filter
ignores, so the type's base exclusions stop applying.
**Location:** `actingweb/trust_permissions.py:748`.
**Recommendation:** categories are objects; their pattern and operation
keys are lists of strings; 400 otherwise.

### 4. Owner bytes
**Severity:** Low
**Description:** a text property held as bytes answers 404 to the owner
(`json.dumps(bytes)`).
**Location:** `actingweb/handlers/properties.py:767`.

### 5. Documentation
**Severity:** Low
**Description:** the access-control guide's PUT example sends
`created_by`/`updated_at`; the changelog says "the store sets
`created_by`" where the grant API does.
**Location:** `docs/guides/access-control.rst:743`; `CHANGELOG.rst:19`.

### 6. Tests
**Severity:** Low
**Description:** no trust-PUT case for a non-object `permissions`; no
permissions-PUT case for a wrong path type; the BOM test holds an invisible
literal; the integration DELETE's list case passes before its fix.

## Overall Assessment

The delta's fixes hold where they were made; the BOM rule was made in one
caller rather than the shared helpers (Issue 1), and one regression came
with the body checks (Issue 2). A tenth batch follows; no owner decision is
needed.
