# Verification: a peer's grant is the answer on every route (re-run 6)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 8109f3c (iterations 52-56 on top of `93e654d`)

Seventh verification. Scope: `93e654d..8109f3c`, checked against re-run 5's
Issues 1-7, reviews scaled to the delta.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5083 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6538 / 6335 passed.
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `8109f3c`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov6/`) and a fresh-context Claude reviewer; probes for
  the hook, the bytes and the deep body.
- **Code review** (built-in, high): 10 findings.
- **Security review**: nothing in the delta; one High that predates the
  branch (Issue 1), confirmed against the tree and `master`.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Owner's edit merged | Fixed on the store's current read | Entry 52; a cached read on one path (Issue 4) |
| 2. Read fault fails open | Fixed | Entry 53 |
| 3. List item body | Fixed | Entry 54 |
| 4. GET by URL type; older read | Fixed for the GET and the cleanup | Entry 53; `type_changes` (Issue 3) |
| 5. Plain-text hook | Hook runs; its result is unfiltered (Issue 2) | Entry 54 |
| 6. Consistency | Partly | Entry 54; other routes, bytes (Issues 6, 7) |
| 7. Client tests | Accepted | Entry 55 |

## Remaining Tasks

- [ ] Issues 1-8 (an eighth iteration batch).

## Issues Found

### 1. An owner's override write can target another actor
**Severity:** High (predates this branch; on `master`)
**Description:** `update_permissions` copies any request field that exists
on `TrustPermissions`, including `actor_id`, `peer_id` and `trust_type`;
`_store_permissions_internal` picks the bucket from the object's own
`actor_id`. On a shared host, the owner of actor A with any override can
PUT `{"actor_id": "V", "peer_id": "A", "trust_type": "admin", ...}` to
`/A/trust/<rel>/<peer>/permissions` and write a grant into V's store.
**Location:** `actingweb/trust_permissions.py:730-745`, `:173`, reached from
`actingweb/handlers/trust.py`.
**Recommendation:** only the permission categories and `notes` are editable.

### 2. A plain-text read hook's result reaches a peer unfiltered
**Severity:** Medium
**Description:** the branch added by entry 54 runs the hook without the
exclusion filter that follows it on the JSON branch and the listing (probe:
`ssn` answered). A non-serialisable result is an uncaught 500. The
too-deep owner branch next to it skips the hook.
**Location:** `actingweb/handlers/properties.py:741-757`, `:728`.
**Recommendation:** one text path, with the filter.

### 3. The re-type decides from an older read
**Severity:** Medium
**Description:** `type_changes` compares with `existing`, read earlier; an
overlapping authorisation in between means no write and a code at the other
type.
**Location:** `actingweb/interface/trust_manager.py:690`.
**Recommendation:** use the row `db.get` just read, for the decision and
the cleanup.

### 4. The permissions PUT decides replace-or-merge from the process cache
**Severity:** Medium
**Description:** a stale cache in another process sees a deleted override
as applying and merges its fields back.
**Location:** `actingweb/handlers/trust.py:1504`.
**Recommendation:** read uncached, as the trust PUT does.

### 5. A sub-path PUT onto plain text replaces the whole value
**Severity:** Medium
**Description:** the fallback `res = store`; plain text "has no parts"
(entry 54) and the too-deep case refuses for this reason. A stored JSON
list or scalar is an uncaught `AttributeError`.
**Location:** `actingweb/handlers/properties.py:1316`.
**Recommendation:** 409.

### 6. Overclaim and leftovers
**Severity:** Low
**Description:** "400 on every route" is not true (the permissions PUT,
the async trust twin and others answer 500); the rollback ignores a failed
restore; `old` in the PUT is dead; the GET's guard reads every row.
**Location:** `CHANGELOG.rst`; `actingweb/handlers/trust.py:1102`, `:1366`,
`:1536`; `actingweb/handlers/async_trust.py:59`;
`actingweb/handlers/properties.py:1254`.
**Recommendation:** catch where it is cheap, narrow the sentence; log; drop;
one-row read.

### 7. Bytes
**Severity:** Low
**Description:** `json.loads` decodes with `surrogatepass`; the new decode
is strict, so such bytes skip the filter.
**Location:** `actingweb/permission_evaluator.py:317`.
**Recommendation:** `surrogatepass`.

### 8. Read hooks see the wrong sub-path; tests
**Severity:** Low
**Description:** `hook_path` is computed after `del path[0]`, dropping the
first segment. The trust PUT's stale-override path has no test; a 201 on
the edit is undocumented.
**Location:** `actingweb/handlers/properties.py:771`.
**Recommendation:** compute it first; test; document.

### Noted, not filed
- A list item that is a JSON string holding deep text is a string value:
  the item's own unit (as re-run 5's note on nested text).

## Overall Assessment

The delta's own fixes hold apart from the hook filter. The security review
turned up a cross-actor write that predates the branch (Issue 1), the most
serious finding of the re-runs, and squarely this plan's subject. An eighth
batch follows; no owner decision is needed.
