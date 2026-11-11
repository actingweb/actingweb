# Verification: a peer's grant is the answer on every route (re-run 7)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 78c8e6d (iterations 57-61 on top of `8109f3c`)

Eighth verification. Scope: `8109f3c..78c8e6d`, checked against re-run 6's
Issues 1-8; the security review also swept every grant-storage write path.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5089 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6543 / 6340 passed
  apart from the wire test that pins a read hook's path, which caught a
  change entry 58 then reverted (entry 61); the file passes on both.
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `78c8e6d`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov7/`) and a fresh-context Claude reviewer (it ran
  httpx on a BOM body).
- **Code review** (built-in, high): 10 findings.
- **Security review**: no high-confidence finding in the delta or in the
  sweep of every grant write path (no other route takes an override's
  identity from a request).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-6.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Cross-actor override write | Fixed (sweep clean) | Entry 57; operators not told about planted grants (Issue 3) |
| 2. Plain-text hook unfiltered | Fixed for objects | Entry 58; JSON text (Issue 1) |
| 3. Re-type from an older read | Fixed | Entry 59 (an unconditional write remains: accepted, entry 43) |
| 4. Edit from the cache | Fixed | Entry 59; no test on that path (Issue 5) |
| 5. Sub-path PUT on text | Fixed | Entry 60; the DELETE next to it (Issue 4) |
| 6. Overclaim, leftovers | Fixed | Entry 60 |
| 7. Bytes | Fixed | Entry 60 |
| 8. Hook path; tests | Hook path kept (pinned contract) | Entries 58, 61 |

## Remaining Tasks

- [ ] Issues 1-6 (a ninth iteration batch).

## Issues Found

### 1. JSON text on the text branch reaches a peer as an object, unfiltered
**Severity:** Medium
**Description:** stored text that is JSON behind a byte-order mark, or a
read hook returning object text, is written raw with `Content-Type:
application/json`; the filter walks only objects. A client (httpx, the
library's own async proxy) reads it as the object, excluded keys included.
**Location:** `actingweb/handlers/properties.py:722-756`.
**Recommendation:** for a peer, read such text as JSON (BOM stripped) and
filter it as the object.

### 2. A failed restore is reported as a failed edit
**Severity:** Low
**Description:** the trust PUT's new override stays when the trust write
and the restore both fail; the caller gets 400/404 and the grant applies.
**Location:** `actingweb/handlers/trust.py:1108`.
**Recommendation:** 500 naming it.

### 3. The SECURITY entry does not ask operators to check planted grants
**Severity:** Low (documentation)
**Description:** overrides written into another actor before the fix keep
applying; the entry has no "what to check".
**Location:** `CHANGELOG.rst:11-19`.
**Recommendation:** a check: review the overrides on shared hosts.

### 4. Edges next to the fixes
**Severity:** Low
**Description:** a sub-path DELETE on a JSON scalar or list answers 500; a
`permissions` body that is not an object answers 500; the create path
takes `created_by` from the body and nothing stamps `updated_at`; the
permissions PUT reads every trust row to check one.
**Location:** `actingweb/handlers/properties.py:2226`;
`actingweb/handlers/trust.py:1500`, `:1525`;
`actingweb/trust_permissions.py:897`.
**Recommendation:** 404/400; the store owns its bookkeeping; one-row read.

### 5. No test for the permissions PUT's uncached read
**Severity:** Low
**Recommendation:** a stale cache on that path.

### 6. Accepted
- `store_permissions` keys on the object's own identity: every caller
  builds it from the URL or the row (the sweep); an assertion would only
  guard future callers.
- A sub-path write through a scalar child replaces that child: inside the
  path the writer may write (pre-existing).
- The re-type's write is unconditional (no conditional store; entry 43).

## Overall Assessment

The sweep found no other identity hole; the delta's own fixes hold. One
Medium remains at the edge between the server's view of a value and the
client's (Issue 1). A ninth batch follows; no owner decision is needed.
