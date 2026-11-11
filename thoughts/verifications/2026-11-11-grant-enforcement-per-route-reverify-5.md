# Verification: a peer's grant is the answer on every route (re-run 5)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 93e654d (iterations 48-51 on top of `3715b53`)

Sixth verification. Scope: `3715b53..93e654d`, checked against re-run 4's
Issues 1-8, reviews scaled to the delta.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5078 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6533 / 6330 passed.
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `93e654d`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov5/`) and a fresh-context Claude reviewer.
- **Code review** (built-in, high): 10 findings.
- **Security review**: no high-confidence vulnerability (a prefix such as a
  BOM cannot get JSON text past the filter for `str`); five correctness
  notes, folded below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Sub-path PUT overwrote the property | Fixed | Entry 48; the list item PUT (Issue 3) |
| 2. Cleanup compared with the approved type | Fixed | Entry 49; the pre-write read (Issues 2, 4) |
| 3. Owner's edit and views | Views fixed; the edit widens (Issue 1) | Entry 49 |
| 4. Bodies 500 | Fixed for properties, methods, actions | Entry 48; other routes (Issue 6) |
| 5. GET catch too broad | Fixed | Entry 50; plain text sub-path and hook (Issue 5) |
| 6. Cost and consistency | Fixed | Entry 50; the two client tests (Issue 7) |
| 7. Tests | Fixed | Entries 48-50; the edit test misses its bug (Issue 1) |
| 8. Warning text | Fixed | Entry 50 |

## Remaining Tasks

- [ ] Issues 1-7 (a seventh iteration batch).

## Issues Found

### 1. The owner's edit of an override that does not apply turns its other fields on
**Severity:** High
**Description:** `update_permissions` starts from the stored override and
changes only the named fields; re-stamping `trust_type` with the row's type
makes every other field of the stale override apply (e.g. a former
`mcp_admin` client's `tools: *` under `mcp_client`) although the owner was
shown only the defaults. The test checks only `trust_type`.
**Location:** `actingweb/handlers/trust.py:1051-1060`, `:1503-1505`;
`actingweb/trust_permissions.py:727-737`.
**Recommendation:** replace a stale override with a fresh one holding only
the owner's edit; test that a field outside the edit is not carried.

### 2. A read fault in the pre-write cleanup fails open
**Severity:** Medium
**Description:** a `DbError` reading the override returns None ("nothing
left"), so the "no code when a stale override of the approved type remains"
gate does not fire.
**Location:** `actingweb/interface/trust_manager.py:505`, `:698`.
**Recommendation:** an unknown result refuses the re-type.

### 3. A list item can be stored from a body nested beyond the parser
**Severity:** Medium
**Description:** `PUT /properties/<list>?index=` stores such a body as
text; list values are not walked by the filter, so it reaches other peers.
**Location:** `actingweb/handlers/properties.py:1064`.
**Recommendation:** 400, as the property PUT.

### 4. The permissions GET decides by the URL's type; the pre-clean by an older read
**Severity:** Low
**Description:** `GET /trust/<type>/<client>/permissions` compares the
override with the path's type, not the row's (it does not check they
agree); the pre-write cleanup compares with the type read earlier
(`existing`), not the row it reads.
**Location:** `actingweb/handlers/trust.py:1366`;
`actingweb/interface/trust_manager.py:694`.
**Recommendation:** the row's type in both.

### 5. A plain-text property ignores the sub-path and the read hook
**Severity:** Medium (pre-existing, next to entry 50)
**Description:** a direct GET of plain text answers the whole text for any
sub-path and never runs the read hook, while the listing runs it: a hook
that withholds `email` hides it from the listing but not from `GET
/properties/email`.
**Location:** `actingweb/handlers/properties.py:728-730`.
**Recommendation:** 404 for a sub-path; run the hook on plain text with the
same refuse-on-None rule.

### 6. Consistency
**Severity:** Low
**Description:** the PUT parses its body two or three times (dead
`RecursionError` branches); other routes' body parses still answer 500 on a
body beyond the parser (callbacks, subscriptions, resources, trust);
`as_json_object` skips bytes that start with a BOM or are UTF-16, which
`json.loads(bytes)` reads; `_parsed` and `as_json_object` overlap.
**Location:** `actingweb/handlers/properties.py:1227`, `:1267`, `:272`;
`actingweb/permission_evaluator.py:313`.
**Recommendation:** reuse the parsed body; 400 everywhere; decode bytes
before the prefix check.

### 7. Two client tests
**Severity:** Low
**Description:** `is_client_peer` (prefix) and `_is_client_row` (prefix or
`established_via`) disagree for a client row without the prefix.
**Location:** `actingweb/trust_permissions.py:104`;
`actingweb/permission_evaluator.py:384`.
**Recommendation:** accepted with a reason in the plan: only the prefixed
rows are created and re-typed by a client authorisation, so only they can
hold an override for another type; documented.

### Noted, not filed
- The developer view parses before the "no snapshot" return (a cost, and
  a too-deep value reads `None` there): kept, it is the rule.
- Nested JSON text inside a JSON value is the value's text, filtered as a
  string: no change.

## Overall Assessment

The fixes of re-run 4 hold. The owner-edit path still turns an unapplied
override's other fields on (Issue 1, High), and one fault path fails open
(Issue 2). A seventh batch follows; no owner decision is needed.
