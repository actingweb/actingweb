# Verification: a peer's grant is the answer on every route (re-run 4)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 3715b53 (iterations 43-47 on top of `e4fc267`)

Fifth verification. Scope: `e4fc267..3715b53`, checked against re-run 3's
Issues 1-8, reviews scaled to the delta.

## Automated Check Results

- **ruff / format / pyright**: pass, 0 errors, 0 warnings.
- **verify_groups.py**: pass.
- **Unit**: 5071 passed.
- **DynamoDB / PostgreSQL, `make test-all-parallel`**: 6525 / 6322 passed.
- **Docs**: build succeeded with `-W`.
- **Wire recordings**: none changed.
- **Emm's suite** on `3715b53`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures.
- **Browser QA:** not re-run (no page change).
- **Second opinion:** outside-voice agent, codex (unsandboxed, output in the
  session scratchpad `ov4/`) and a fresh-context Claude reviewer.
- **Code review** (built-in, high): 10 findings.
- **Security review**: no high-confidence vulnerability; it confirmed every
  enforcement path for a client goes through the inert-override rule;
  three correctness notes, folded below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Beyond-parser GET skips sub-path and hooks | Fixed for stored text | Entry 44; a hook's returned text (Issue 5) |
| 2. Re-type rollback races | Fixed by decision (inert override) | Entry 43; the cleanup and the owner's edit path (Issues 2, 3) |
| 3. Beyond-parser paths disagree | Fixed for reads | Entry 44; writes now overwrite (Issue 1), bodies 500 (Issue 4) |
| 4. Hook `-32000` → 403 | Fixed | Entry 45 |
| 5. Fork, cancel | Fixed | Entry 46 (the fork test does not fork: accepted, `register_at_fork` cannot be inspected) |
| 6. Late `TrustReplaced` | Fixed | Entry 46; the message's claim about the next sync (Issue 8) |
| 7. Tests that do not show their bug | Fixed for the deadlock | Entry 46; new gaps (Issue 7) |
| 8. `None` as withheld | Fixed with `withheld()` | Entry 44 |

## Remaining Tasks

- [ ] Issues 1-8 (a sixth iteration batch).

## Issues Found

### 1. A sub-path PUT over text beyond the parser replaces the whole property
**Severity:** High (data loss)
**Description:** the merge falls back to `res = store` on `RecursionError`,
so `PUT /properties/notes/public/x` over such a stored `notes` writes
`{"public": {"x": ...}}` over everything, answering 204; the owner too;
and since entry 44 a non-admin peer with no exclusion reaches it (it was
403).
**Location:** `actingweb/handlers/properties.py:1269-1273`, `:415`.
**Recommendation:** refuse a sub-path write into a value the parser cannot
read (409), for everyone; test with a non-admin peer.

### 2. The override cleanup compares with the approved type, not the row's
**Severity:** Medium
**Description:** two overlapping authorisations (A then B): A's cleanup,
running after B wrote B back, deletes a valid B override (B ≠ A); the
client gets B's full defaults. A later approval of a stale override's type
re-activates it (a failed cleanup earlier).
**Location:** `actingweb/interface/trust_manager.py:487`.
**Recommendation:** remove an override whose type differs from the row's
current type (read fresh), before the write as well as after; refuse
only when a stale override of the approved type cannot be removed.

### 3. The owner's grant API edits and shows an inert client override as live
**Severity:** Medium
**Description:** `update_permissions` keeps the stale `trust_type`, so the
owner's narrowing answers 200 and is never applied; `GET
/trust/.../permissions`, `GET /permissions/<peer>` and the web UI flag show
the inert override as effective.
**Location:** `actingweb/trust_permissions.py:699-727`;
`actingweb/handlers/trust.py:690`, `:1046`, `:1353`, `:1484`;
`actingweb/handlers/permissions.py:111`; `actingweb/handlers/www.py:881`.
**Recommendation:** an edit for a client writes the row's type; the
display paths apply the same rule as the evaluator.

### 4. Bodies nested beyond the parser answer 500
**Severity:** Low
**Location:** `actingweb/handlers/properties.py:1217`, `:1257`;
`actingweb/handlers/methods.py`, `actions.py`;
`actingweb/interface/integrations/fastapi_integration.py:492`.
**Recommendation:** 400.

### 5. The direct GET's catch is too broad, and misses a hook's text
**Severity:** Low
**Description:** the outer `except RecursionError` also catches one raised
by a read hook, `drop_excluded` or `json.dumps`, and hands the owner the
raw unhooked value; a hook returning text beyond the parser reaches a peer
on the direct GET (the listing checks it).
**Location:** `actingweb/handlers/properties.py:739-760`.
**Recommendation:** parse in its own `try`; check the hook's result.

### 6. Cost and consistency in the evaluator and the beyond-parser rule
**Severity:** Low
**Description:** a client with an override costs one or two extra row
reads per check (`_is_unapproved` read it already); the rule identifies a
client by prefix while `_is_client_row` also counts `established_via`;
`beyond_parser` parses a JSON-looking value and the caller parses it again
(docstrings still promise no parse); the cleanup reads the store on every
authorisation.
**Location:** `actingweb/permission_evaluator.py:325`, `:945-973`;
`actingweb/actor.py:4025`; `actingweb/interface/authenticated_views.py:208`.
**Recommendation:** pass the row down; one client test; parse once and
reuse; check the cached override first.

### 7. Tests miss the changed lines
**Severity:** Low
**Description:** the beyond-parser PUT case uses the admin, which returns
before the changed line; no evaluator test reads the row
(`relationship=None`); nothing covers the sub-path merge, the views', the
diff's and the full state's beyond-parser checks, or the FastAPI
passthrough.
**Recommendation:** a non-admin peer with no exclusion; a real-row
evaluator test; unit tests for each check.

### 8. Smaller
**Severity:** Low
**Description:** the late-`TrustReplaced` warning claims the peer's next
sync re-creates subscriptions (no code shows it); the views return the
value before the beyond-parser check when the snapshot is missing.
**Location:** `actingweb/interface/subscription_manager.py:1724`, `:2821`;
`actingweb/interface/authenticated_views.py:205`.
**Recommendation:** state only what happened; check first.

### Noted, not filed
- Codex: clients recognised only by `established_via` escape the rule —
  not reachable by a re-type (the re-type builds the `oauth2_client:` peer
  id); folded into Issue 6 as a consistency fix.
- Codex: the full state returns list keys before the check — list state is
  a list, never text; no change.
- The integration re-type test mocks the store (a smoke test, entry 43).

## Overall Assessment

The inert-override decision closed the rollback races and the security
review found every client path honours it. Not clean: entry 44's
write-side change turned a refusal into a silent overwrite of a whole
property (Issue 1, High), and the owner's own path for a client's override
contradicts the evaluator (Issues 2, 3). A sixth batch follows; no owner
decision is needed for it.
