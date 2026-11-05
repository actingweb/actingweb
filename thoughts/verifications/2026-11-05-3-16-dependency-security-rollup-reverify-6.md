# Verification: 3.16 dependency-security roll-up (seventh run: the deletion table after Iterations 25-29)

**Date:** 2026-11-05
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md
**Contract:** thoughts/reference/trust-row-deletion-invariants.md
**Branch:** release/3.16.0-dependency-security
**Commit:** 7fec12f

Scope: the delta `0f6ee12..7fec12f` (Iterations 25-29). The earlier phases
and iterations were verified by the six previous runs and are unchanged.
The `verified:` link moves here because the delta is the plan's last change.

## Automated Check Results

- **Browser QA:** N/A. Nothing a user sees changed.
- **Second opinion:** the outside-voice agent ran two providers on the
  delta: codex (`codex exec -s read-only`) and a fresh-context Claude
  reviewer. I re-checked findings 1, 2 and 5 below against the code. The
  built-in code and security reviews were not run separately, per
  scale-reviews-to-the-delta: the outside voice was briefed on exactly this
  code, with five security questions.
- **The Full tier, on `7fec12f`:**
  - `ruff check`, `ruff format --check`, pyright: pass (0 errors, 0 warnings).
  - `verify_groups.py`: all 53 groups documented.
  - `make test-all-parallel`, DynamoDB: 5714 passed, 60 skipped, 1 xfailed
    (exit 0).
  - `make test-all-parallel`, PostgreSQL: 5511 passed, 263 skipped,
    1 xfailed (exit 0).
  - `sphinx-build -W`: pass.

  The first combined run printed `tail`'s exit codes, not `make`'s, and no
  counts. The two backend runs above were repeated alone, one after the
  other, with `make`'s exit codes.

## Phase Verification

### Iterations 25-29 (`7fec12f`): ISSUES FOUND

**Changes verified:**
- `actingweb/trust.py:442-460`: `Trust.create` clears the peer id's custom
  permissions when no row exists, and raises `DbError` when it cannot. The
  outside voice and I found no library path that writes permissions before
  the row exists. The PUT handlers (`handlers/trust.py:814`, `:1194`) run on
  a live row, and `TrustManager.create_or_update_oauth_trust`
  (`trust_manager.py:609-629`), the only direct `DbTrust.create`, clears them
  itself.
- `client_registry.py:363`, `disable_client` passes `strict=True`, and at
  `:436-438` a `TokenStoreUnavailable` raises `DbError` before any row goes.
- `client_registry.py:458-469` deletes the index row first, then the client
  row, and a partial delete returns None. On a retry, `delete_confirmed`
  treats an absent index row as gone, and the ownership check at `:403`
  reads the client row (`client_owned_by`), so every route converges.
- `oauth_client_manager.py:170-176`: the not-found path finishes the
  deletion of a client whose row is still in this actor's bucket.
- `trust_lookup.py:25-36`: `legacy_oauth2_row` is used by
  `Trust._oauth2_client_id` (`trust.py:276`) and by arm 3 of
  `client_trusts_for_deletion`. Arm 2 does not use it (Issue 3).
- `client_registry.py:762-782`: the sweep counts any exception as a fault
  and raises `DbError`. The branch at `:747-750` still only warns
  (Issue 4).

**Tests verified:**
- `TestTrustDeletionConverges::test_a_fault_at_any_step_raises_and_a_retry_finishes`
  (`test_trust_oauth_integration.py:1070`), 42 cases:
  - it asserts the raise, and that the faulted row stays for depth-1 steps
    3-6 (`:1101`);
  - for 3a it asserts `client_owned_by` (`:1103`);
  - at the end it asserts that the rows, access tokens, refresh token,
    provider tokens and permissions are gone (`:1116-1131`), and that the
    owner's client and client row are gone (`:1133-1139`).
- `TestPeerRowPermissionResidue` (`:1146`): a re-created peer row does not
  inherit leftover permissions (`:1179`), and re-creating a live row keeps
  them (`:1211`). This demonstrates the High fix from the last run (Issue 2
  then).
- Unit tests: `test_a_disable_with_a_row_left_is_not_a_success`,
  `test_a_token_store_fault_stops_the_owners_disable`
  (`test_client_connection_deletion.py:370`, `:398`);
  `test_a_legacy_row_with_a_peers_baseuri_is_not_the_clients`,
  `test_a_client_row_whose_index_row_went_is_deleted_by_its_owner`
  (`test_client_trust_lookup.py:126`, `:296`);
  `test_delete_client_fails_while_its_client_row_stays`
  (`test_mcp_token_store_faults.py:268`).

**Deviations from plan:** none outside the iterations' scope.

The test's "one-row" route (`:1060-1066`) deletes every row of the client
in a loop, so it is the client route. No case models the HTTP one-row
route, which answers 404 once its row is gone (Issue 1).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-05-3-16-dependency-security-rollup-reverify-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Step 3a goes on after a token-store fault; a partial disable counts as success | Fixed | `client_registry.py:436-438`, `:458-469`; Iteration 26 |
| 2. Leftover permissions come back on a re-created peer row (High) | Fixed | `trust.py:442-460`; `TestPeerRowPermissionResidue`; Iteration 25 |
| 3. The convergence test's setup hides an ordering regression | Fixed for the client and every-row routes | Iteration 27: three rows, one-row owner, faults by peer id, pre-assertions. The one-row HTTP route is still not modelled (Issue 1) |
| 4. The legacy origin gate breaks on a root change and disagrees with `trust_lookup` | Fixed for `Trust` and arm 3 | `trust_lookup.py:25`; arm 2 is still prefix-only (Issue 3) |
| 5. Step 8 can be skipped silently | Mostly fixed | `client_registry.py:762-782`; the warn-only branch remains (Issue 4) |
| 6. The table's steps 2 and 5 claim more than the code does | Fixed | table steps 2 and 5, "Known residue" |
| 7. The permission cache is per process with no TTL | Accepted, filed | `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` section 7; table "Scope of the rules" |
| 8. Smaller points (owner-path fence, 404 as deleted, prefix check) | Fixed or recorded | `disable_tokens` target; table step 1; "Remote-DELETE skip" residue |

## Remaining Tasks

- [ ] Issues 1 and 2 below: the one-row route's retry after a fault at
  step 7 or step 8.
- [ ] Issues 3-6: table wording, and the one warn-only branch.

## Issues Found

### 1. On the one-row route, a fault after the row delete cannot be retried
**Severity:** Medium
**Description:** rule 2 says that what a raise leaves behind "grants
nothing and is reachable some other way". Step 8's row admits that
leftover connection siblings "still authorise a new login".

On `DELETE /<actor>/trust/<rel>/<peer>`, a sibling fault raises 503 after
the route's own row is gone (`trust.py:238`). The retry answers 404 and
never sweeps again. The sibling stays until someone deletes it by its own
peer id, and nothing tells the user it exists. For an owner the leftover is
inert (the client is gone). For a connection it is not. The every-row and
client routes re-read the rows and converge, and those are the only routes
the test exercises (see Phase Verification).

**Location:** `actingweb/trust.py:211-241`; table step 8, "Retry reaches it
by".
**Recommendation:** run the sweep on the one-row route's 404 path when the
peer id names an OAuth2 client, or before the row delete. Otherwise, state
the gap in the table as a breach of rule 2, not a residue. Add a one-row
HTTP case to the convergence test.

### 2. A fault at step 7 skips step 8, and the table doesn't say so
**Severity:** Medium
**Description:** `trust.py:230`: "`raise DbError("trust permissions delete", self.actor_id)`".
It raises inside the same `try`, before the sweep at `:238`, so one
permission-store fault leaves every connection sibling in place. On the
every-row routes the retry sweeps them. On the one-row route it hits
Issue 1. The table's step 7 mentions only the leftover permissions.
**Recommendation:** run the sweep even when step 7 raises (in a `finally`,
or before the permission delete), then raise the first fault. Add a
`permissions` case with siblings on the one-row route.

### 3. The "one gate" sentence overclaims: arm 2 is prefix-only
**Severity:** Low
**Description:** `trust_lookup.py:69-71`: "`legacy_prefixed = via is None and (peer_id.startswith("oauth2:") or ...`".
Arm 2 (client-credentials shape) does not call `legacy_oauth2_row`, and
`find_client_trust` uses the same arm.

The table says "`Trust` and the sweep's `client_trusts_for_deletion` both
use that one gate". The disagreement shows on one row: a pre-3.4
`oauth2_client:<n>:<n>` row with a peer's baseuri. The sweep takes it and
the resolver authorises it, but `Trust` refuses it. Arm 1 (`_tagged`,
`:52-54`) has no origin check either, while the table says a tagged row
names a client only "with an OAuth2 `established_via`".
**Recommendation:** make arm 2 call `legacy_oauth2_row`, or word the table
to say exactly which arms use it.

### 4. One sweep branch still warns and succeeds
**Severity:** Low
**Description:** `client_registry.py:747-750`: "`logger.warning(f"Failed to delete trust relationship {peer_id} ...`".
The branch runs when `delete_relationship` returns False and the row is
still listed (a refused remote DELETE). The table's step 8 says "any
exception counts as a fault". This is not an exception, so the sweep ends
in success with a live row. Only a tagged row without an OAuth2 prefix
reaches it.
**Recommendation:** record a fault there.

### 5. Step 3a's retry does not converge when the index names another owner
**Severity:** Low
**Description:** `client_registry.py:396`: "`if owner and actor_id and owner != actor_id:`" returns None, and `trust.py:171` then raises.

Take a client row in Y's bucket that names Y, while the index names X.
The code anticipates such a row ("copied, restored", `:489`). Every
`Trust.delete` of Y's row for that client then answers 503, and
`Actor.delete` of Y is blocked too. This predates the delta, but table
row 3a now claims the retry converges.

The outside voice also flagged an unverified case: a `TokenStoreUnavailable`
that never clears would block the strict owner path for good.
**Recommendation:** in `Trust.delete`, treat a row whose index names
another owner as a connection, or record the exception in the table.

### 6. Smaller points
- **The create race:** `trust.py:449` reads, clears and then creates as
  three separate steps. Suppose two creates for the same peer id race. The
  owner writes restrictive permissions between them, and the second create
  clears them. Only an insert-if-absent closes this. It is theoretical,
  since two near-simultaneous trust requests for one peer would both be
  pending approval, but the table should say so.
- **A permanent 503:** the sweep now wraps a non-store exception (a bug or
  a malformed row) in `DbError`, so `OAuth2ClientManager.delete_client`
  answers 503 on every retry where it used to answer success. That is
  rule 1 working as intended, but such a row needs an operator, and the
  log line is the only pointer to it.
- **Changelog wording:** "a retry finishes it" (registry `delete_client`)
  holds only when `actor_id` is passed. Without it, a client whose index
  row went is "not found". `OAuth2ClientManager` always passes it.

## Overall Assessment

Iterations 25-29 fix what the sixth run found:
- the High permission residue on re-created peer rows;
- the strict owner disable;
- both client rows confirmed gone, index first;
- one gate for legacy rows on `Trust` and arm 3.

The convergence test now has the setup and checks it lacked. The table now
describes the code for steps 1-6 and 9, and the Full tier is green on both
backends.

Two Medium issues remain, and they share a cause. A fault after the row
delete is retried by re-reading the rows, which the every-row and client
routes do, but the HTTP one-row route does not. A fault at step 7 also
skips step 8. Together, a single transient fault on a one-row delete can
leave token-less connection rows that the table's rule 2 does not allow.
The fix is small: run the sweep despite a step 7 fault, and re-run it on
the 404 path. The test needs a one-row HTTP route to show it. The Low
items are table wording and one warn-only branch. Fix Issues 1 and 2
before the PR. The rest can go in the same iteration.
