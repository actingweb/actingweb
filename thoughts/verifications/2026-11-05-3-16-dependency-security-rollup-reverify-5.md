# Verification: 3.16 dependency-security roll-up (sixth run: the trust-row deletion contract)

**Date:** 2026-11-05
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md
**Contract:** thoughts/reference/trust-row-deletion-invariants.md
**Branch:** release/3.16.0-dependency-security
**Commit:** 89b777d

Scope, as agreed with the owner: the delta since the fifth verification,
`000c270..89b777d`. That is:
- `75b7fb6`, Iterations 21-23;
- `89b777d`, Iteration 24: the invariant table and `TestTrustDeletionConverges`.

They are checked against the two rules the table states. The earlier phases
are unchanged and were verified in the previous runs.

## Automated Check Results

- **Browser QA:** N/A. Nothing a user sees changed.
- **Second opinion:** two providers ran through the outside-voice agent,
  briefed with the table, the test and the routes the test does not
  exercise:
  - codex (`codex exec -s read-only`);
  - a fresh-context Claude reviewer.

  I re-checked the two High findings against the code
  (`client_registry.py:428`, and the three `delete_permissions` callers).
  The built-in code and security reviews were not run separately, per
  scale-reviews-to-the-delta: this pass was briefed on exactly this code.
- **The Full tier** was run on `89b777d`'s tree just before this
  verification; the tree is unchanged since apart from one plan line:
  - `ruff check`, `ruff format --check`, pyright: pass (0 errors, 0 warnings).
  - `verify_groups.py`: all 53 groups documented.
  - `make test-all-parallel`, DynamoDB: 5686 passed, 60 skipped, 1 xfailed.
  - `make test-all-parallel`, PostgreSQL: 5483 passed, 263 skipped, 1 xfailed.
  - `sphinx-build -W`: pass.

## Phase Verification

### Iterations 21-23 (`75b7fb6`): VERIFIED

- **Bulk deletion** re-reads a row whose delete returned False
  (`actor.py`, `delete_reciprocal_trust`). The regression test raises
  `DbError` on the old code.
- **`Trust.delete` order:** `disable_client` or the revocation, then the
  provider tokens, then the row, then the permissions and the sweep. The
  eviction runs in a `finally`. All of this matches Iteration 22.
- **The new checks:**
  - the legacy origin gate (`baseuri`);
  - `fence_unread`;
  - `delete_peer_trustee` accepting a 404.

  These are present as described; the issues they raise are below.

### Iteration 24 (`89b777d`): ISSUES FOUND

- **The table:** it is present and matches the code order, but some of its
  outcomes overstate what the code does (Issues 1, 2, 5 and 6).
- **The test:** the 22 cases exist, each fault is asserted to have fired,
  and 13 of them fail on `d26c0b2`. Its two-row, single-process, OAuth2-only
  setup hides some cases (Issue 3).
- **The unconditional permission delete is correct:** `set_attr(data=None)`
  returns True for an absent attribute and raises on a fault on both
  backends (`db/dynamodb/attribute.py:239-250`,
  `db/postgresql/attribute.py:376-404`).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-05-3-16-dependency-security-rollup-reverify-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A False from the delete fails bulk deletion | Fixed | Iteration 21; `test_bulk_deletion_passes_a_row_an_earlier_rows_cleanup_removed` |
| 2. The owner's 503 left the retry a 404 | Fixed | Iteration 22; `disable_client` before the row |
| 3. Eviction skipped on a raise | Fixed | `finally` in `Trust.delete` |
| 4. Permission clear missed the shared cache | Fixed, and widened in Iteration 24 (the cached "none" no longer gates the delete) | `trust.py:229`, `trust_manager.py:624` |
| 5. Pre-3.4 peer rows pass the origin gate | Fixed, with a new edge case (Issue 4) | `trust.py:282` |
| 6. `delete_permissions` result ignored | Fixed | raises on False |
| 7. Stale changelog clause | Fixed | `CHANGELOG.rst` |
| 8. First-pass bucket read fault was silent | Fixed on the connection path; swallowed on the owner path (Issue 1) | `token_manager.py:1739` |
| 9. Smaller points | Fixed, two accepted | Iteration 23 |

## Remaining Tasks

- [ ] Issues 1-3 before the PR: correct the table, fix the permission
  leftovers, and strengthen the test.
- [ ] Issues 4-8: fix them, or accept each in the table with a sentence.

## Issues Found

### 1. Step 3a goes on after a token-store fault; the table says it raises
**Severity:** Medium
**Description:** `client_registry.py:428`: "`except TokenStoreUnavailable as e:` ... deleting the client anyway".
- The table (step 3a) says "`DbError`, row and client stay".
- The code logs the fault, deletes the client and answers success. Access
  tokens it could not revoke live out their 1 h TTL.
- The new `fence_unread` raise is lost on this path too.

The effect is limited: once the rows are gone, MCP refuses a token with no
trust row (`handlers/mcp.py:1181`). But the table and the code disagree.
The test can't see it, because in the owner scenario the `revoke` fault
fires on the sibling's step 3b.

Both reviewers also found the related partial-disable case
(`client_registry.py:459`, "that is enough to disable it"). If either the
client row or the index row is confirmed gone, the call counts as success.
The other row then stays behind:
- **The index row stays:** an index row whose client row is gone.
- **The client row stays:** the client is still listed, and the client
  manager's not-found path (`oauth_client_manager.py:173`) never deletes
  that bucket row.

**Recommendation:** decide whether step 3a raises. Either way, write the
table to match. On the not-found path, also delete the actor's own bucket
row.

### 2. Permissions left by a fault are not harmless for peer rows
**Severity:** High
**Description:** the table's step 7 and its "Known residue" claim that
leftover permissions grant nothing, and are cleared when "A new OAuth2 row
with the same peer id clears them first". That holds only for OAuth2 rows.
`delete_permissions` is called from exactly three places:
- `trust.py:229`;
- `trust_manager.py:624`, OAuth2 creation only;
- `handlers/trust.py:1242`.

A peer's trust has a stable peer id (the peer's actor id). The failure
goes like this:
1. An owner deletes a friend trust to remove its wide custom grants.
2. The permission delete faults after the row is gone (503).
3. The peer later asks for trust again, and the owner approves.
4. The new row inherits the old grants.

Before `d26c0b2`, the permissions were deleted before the row, so this
case could not arise.

**Location:** `actingweb/trust.py:220-230`. Trust creation and approval for
peers: `actor.py` `create_reciprocal_trust`, and the trust POST handler.

**Recommendation:** clear the custom permissions on every trust row
creation, not only OAuth2, and add a peer row to the convergence test.

### 3. The test's setup hides an ordering regression
**Severity:** Medium
**Description:** `test_trust_oauth_integration.py:918` "`assert len(peer_ids) == 2`" and the retry loop that checks only the end state.

If `disable_client` moved back after the row delete, the `disable` fault
would remove row 1 and leave the client live. The retry would then reach
row 2, which is still owned, disable the client, and pass. With one row,
the client would stay live with no retry handle.

Other gaps:
- No pre-assertions show the tokens or provider tokens existed.
- No refresh token or chain is created.
- `sibling_row` is "the second `DbTrust.delete` call", not a predicate on
  the sibling's peer id.
- Two rows can't tell "try every row, then raise" from "raise at the
  first fault".
- The `permissions` skip depends on row order, which PostgreSQL does not
  guarantee.

**Recommendation:**
- add a single-row owner case;
- after the raise, assert that for steps 3-6 the faulted row still exists;
- add pre-assertions and a refresh token;
- match the sibling by peer id;
- use three rows with the fault on the middle one;
- skip the residue by the faulted peer id, not by index.

### 4. The legacy origin gate breaks when `config.root` changes, and disagrees with `trust_lookup`
**Severity:** Medium
**Description:** `trust.py:282`: "`if prefix not in OAUTH2_SOURCES or baseuri not in ("", own_uri)`".
- A pre-3.4 OAuth2 row written with the old root (fqdn or protocol
  changed since) no longer names its client. Deleting it then skips
  steps 3 and 8: an owner's client stays live, and tokens stay unrevoked.
- `trust_lookup._oauth2_origin` (`trust_lookup.py:32`) still admits that
  row by its prefix alone.

**Recommendation:** have one gate, in `trust_lookup`, and compare by the
path suffix `/<actor_id>`, as `is_self_deletion` does.

### 5. Step 8 can be skipped silently
**Severity:** Low
**Description:** `client_registry.py:770` "`# Don't raise - client deletion can continue`" folds any non-`DbError` exception. `:700` returns when the actor isn't found. Either way `Trust.delete` answers success while a sibling row is live.
**Recommendation:** re-raise, or wrap the exception in `DbError`.

### 6. The table's steps 2 and 5 claim more than the code does
**Severity:** Low
**Description:**
- **Step 2:** the store results are ignored. `actor.py:2104` "`sub_obj.delete()`" is one; the others are the remote-peer, profile, capabilities and peer-permission deletes. A backend that answers False instead of raising lets the row go.
- **Step 5:** `handlers/trust.py:1024` logs any non-`DbError` hook exception and answers 204. The table says "as the hook does".
- **Step 5's route:** it is not only the one-row route. The sibling sweep calls `delete_relationship`, so the every-row routes fire the hook for sibling rows too.

**Recommendation:** write what the code does, or check the returns.

### 7. The permission cache is per process with no TTL
**Severity:** Low
**Description:** `trust_permissions.py:494`, "a cached None is a hit". After a delete and a re-create in worker A, worker B keeps serving its cached grants. This predates the delta. The table's rule 2 is true only within one process.
**Recommendation:** state the limit in the table, and file it with the MCP cache-lifecycle todo.

### 8. Smaller points
- **The fence on the owner path:** `fence_unread` has no convergence case,
  and on the owner path it is swallowed (Issue 1).
- **404 as deleted:** the table doesn't mention that `delete_peer_trustee`
  now treats a 404 as deleted.
- **The prefix check:** `actor.py:2029`'s prefix-only "is_oauth2_trust"
  check differs from the origin gate. Only legacy rows can reach it
  (`is_valid_peer_id` blocks new ones), so its effect is Issue 4's.

## Overall Assessment

The code in this delta does what Iterations 21-24 say, and all nine issues
from the fifth verification are fixed. The new test found and fixed a real
bug. This run is different in kind from the earlier ones: the main findings
are not new fault windows in `Trust.delete`. They are places where the
table claims more than the code or the test proves. Leftovers counted as
harmless are harmless only for OAuth2 rows (Issue 2, High), step 3a's fault
outcome is misstated (Issue 1), and the test's two-row setup can't see an
ordering regression (Issue 3).

Before the PR, the next `/iterate_plan` should do three things:
- correct the table to what the code does;
- fix Issue 2 by clearing permissions on every trust creation;
- strengthen the test as Issue 3 recommends.

Issues 4-8 are small, and each can be fixed or accepted in the table. The
table is now what reviews check against, so it must be exactly true.
