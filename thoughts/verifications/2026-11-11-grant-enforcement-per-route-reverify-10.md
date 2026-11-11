# Verification: a peer's grant is the answer on every route (re-run 10)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 426addb (iterations 69-71 on top of `83648e7`)

Eleventh verification. Scope: `83648e7..426addb`, checked against re-run 9's
Issues 1-5.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5103 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6558 / 6355 passed.
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `426addb`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov10/`) and a fresh-context Claude reviewer; both
  rate Issue 1 High.
- **Code review** (built-in, high): 10 findings, the same two at the top.
- **Security review**: no high-confidence finding; its note 2 is Issue 1.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-9.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Malformed rules drop base exclusions | Fixed for exclusion keys; widened allow keys and categories (Issue 1) | Entry 69 |
| 2. Lenient bytes decode | Fixed for peers; the owner too (Issue 2) | Entry 70 |
| 3. Writes vs reads; BOMs | Fixed; DELETE test does not show it (Issue 3) | Entry 70 |
| 4. Behavior change line | Fixed; it overstates delete hooks (Issue 3) | Entry 70 |
| 5. Wording, tests | Fixed; one guide sentence is wrong (Issue 3) | Entry 70 |

## Remaining Tasks

- [ ] Issues 1-3 (a twelfth iteration batch).

## Issues Found

### 1. "Keep the trust type's value" widens malformed allow keys and categories
**Severity:** High
**Description:** keeping the base is fail-closed only for the exclusion
keys (`excluded_patterns`, `denied`). For `operations`, `allowed` and
`patterns`, and for a whole category that is not an object, the base is
the trust type's wider grant; a malformed override (stored before the
intake check, through the store API, or a shorthand list such as
`methods: ["x"]` or `tools: []`) used to deny and now grants it.
**Location:** `actingweb/trust_permissions.py:863`, `:897`, `:908`.
**Recommendation:** a malformed allow key is `[]`; a malformed category is
an empty rule (deny), except the `properties` shorthand list, which is
normalised; exclusion keys keep the base. Tests with a wider base.

### 2. The owner's undecodable bytes are a 404
**Severity:** Low
**Location:** `actingweb/handlers/properties.py:757`.
**Recommendation:** decode strictly for a peer only.

### 3. Leftovers
**Severity:** Low
**Description:** the sub-path DELETE test runs on what the PUT rewrote; the
changelog says delete hooks receive the object (they get the text); the
merge warning repeats on every evaluation; the `_parsed` bytes re-parse is
dead; the guide's "other keys are stored" is wrong for top-level keys; the
evaluator hard-codes the category list; a redundant list test in the union
merge.
**Location:** `tests/test_grant_edges.py:525`; `CHANGELOG.rst`;
`actingweb/trust_permissions.py:868`, `:877`;
`actingweb/handlers/properties.py:290`; `docs/guides/access-control.rst:778`;
`actingweb/permission_evaluator.py:1036`.

## Overall Assessment

Re-run 9's fix took "keep the base" for fail-closed in every case; it is
only for exclusions (Issue 1, High). A twelfth batch follows; no owner
decision is needed.
