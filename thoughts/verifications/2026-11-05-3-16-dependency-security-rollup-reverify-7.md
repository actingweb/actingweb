# Verification: 3.16 dependency-security roll-up (eighth run: the sweep before the row)

**Date:** 2026-11-05
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md
**Contract:** thoughts/reference/trust-row-deletion-invariants.md
**Branch:** release/3.16.0-dependency-security
**Commit:** 5d4a91e

Scope: the delta `d720963..5d4a91e` (Iterations 30-32). Everything before it
was verified by the seven previous runs and has not changed since. The
`verified:` link moves here because this delta is the plan's latest change.

## Automated Check Results

- **Browser QA:** N/A. Nothing a user sees changed.
- **Second opinion:** the outside-voice agent ran two providers on the
  delta, briefed with six questions: recursion and the guard's reset,
  `exclude_peer_id`, the index-owner check, the arm-2 lockout risk, the
  table against the code, and mocks that pass for the wrong reason.
  - codex (`codex exec -s read-only`, run outside the sandbox);
  - a fresh-context Claude reviewer.

  All of their findings are Low; I checked the cited lines. The built-in
  code and security reviews were not run separately, per
  scale-reviews-to-the-delta: the outside voice was briefed on exactly this
  code, security questions included.
- **The Full tier** was run on this tree just before the commit, and
  nothing changed between that run and `5d4a91e`. Exit codes are `make`'s.
  - `ruff check`, `ruff format --check`, pyright: pass (0 errors, 0 warnings).
  - `verify_groups.py`: all 53 groups documented.
  - `make test-all-parallel`, DynamoDB: 5741 passed, 60 skipped, 1 xfailed
    (exit 0).
  - `make test-all-parallel`, PostgreSQL: 5538 passed, 263 skipped,
    1 xfailed (exit 0).
  - `sphinx-build -W`: pass.

## Phase Verification

### Iterations 30-32 (`5d4a91e`): VERIFIED

**Changes verified:**
- `actingweb/trust.py:213-226`: the sweep runs before
  `result = self.handle.delete()`, with `exclude_peer_id=peerid`, and only
  when `registry.sweeping(...)` is False.
- `client_registry.py:724`: "`guard = _SWEEPS.set(_SWEEPS.get() | {(actor_id, client_id)})`",
  reset in a `finally`.
  - The nested `Trust.delete` reads the same client id. Registry ids are
    `mcp_<hex>` and normalise to themselves, so the key matches and no
    second-level sweep starts.
  - FastAPI's executor and async hooks (`hooks.py:583`) copy the context,
    so the guard is set and reset in one context.
- `client_registry.py:483-492`: `indexed_owner`. `Trust.delete` takes the
  owner path only when the index names no other actor. The read is strict,
  so a fault raises before anything changes. Only the server writes the
  index row, at registration (`:136`, `:843`), so no attacker can redirect
  it.
- The refused-delete branch of the sweep records a fault.
- `trust_lookup.py`: arm 2 admits a row with no `established_via` only
  through `legacy_oauth2_row`, and `find_client_trust` takes the actor id
  (`handlers/mcp.py:2593`).
- **No lockout:** the registry's first trust writer (`613cc27`) already set
  `established_via="oauth2_client"` and `baseuri=""`. No row the library
  wrote can hit the new check.

**Tests verified** (security properties named with their assertions):
- **Issue 1:** `TestTrustDeletionConverges`, now 63 cases on three routes.
  `same-row` retries the same peer id. For a sibling fault on the one-row
  routes, it asserts "a sibling fault must leave the route's own row"
  (`state["root"] in left_rows`). On the previous library code 10 cases
  fail: every sibling fault on `same-row` and `one-row`, plus the
  permissions fault on `same-row`.
- **Issue 2:** the `permissions-same-row` cases.
- **Issue 3:** `test_a_legacy_client_credentials_row_with_a_peers_baseuri_is_neither`
  asserts that `find_client_trust(...) is None` for a peer's baseuri, and
  that the own-root row is still found.
- **Issue 4:** `test_a_refused_delete_of_a_listed_row_is_a_fault`
  (`pytest.raises(DbError)`; the other row is still deleted).
- **Issue 5:** `test_a_client_the_index_gives_to_another_actor_is_a_connection`
  (`disable_client` is not called; `revoke_connection_tokens` is).
- **The guard:**
  - `test_the_excluded_row_is_left_and_nested_deletes_see_the_sweep`: the
    excluded row stays, `sweeping` is True inside the sweep and False after
    it.
  - `test_a_nested_delete_inside_a_sweep_does_not_sweep_again`.
  - The depth-2 convergence cases go through the real nested path, so
    unbounded recursion would fail them.
- **Mocks:** every mocked registry in `tests/` sets `sweeping` and
  `indexed_owner` (the outside voice grepped for this).

**Deviations from plan:** none.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-05-3-16-dependency-security-rollup-reverify-6.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The one-row route can't retry after the row went (Medium) | Fixed | `trust.py:213-226`; the `same-row` route; Iteration 30 |
| 2. A step-7 fault skipped the sweep (Medium) | Fixed | the sweep runs before the row and permissions; `permissions-same-row`; Iteration 30 |
| 3. The "one gate" sentence overclaimed (arm 2 was prefix-only) | Fixed | `trust_lookup.py` arm 2; the table's "Which rows name a client"; Iteration 31 |
| 4. A refused sibling delete warned and succeeded | Fixed | `client_registry.py` refused branch; Iteration 31 |
| 5. 3a refused forever with a foreign index | Fixed | `indexed_owner` in `Trust.delete`; Iteration 31 |
| 6. Smaller points (create race, permanent 503, changelog retry wording) | Accepted, written down | table "Known residue"; `CHANGELOG.rst`; Iteration 32 |

## Remaining Tasks

- [ ] Issues 1-4 below: table and test wording only. No code defect
  remains.

## Issues Found

### 1. The table places the hook (step 5) after the steps it precedes
**Severity:** Low
**Description:** at `interface/trust_manager.py:308-316`, "`# Execute lifecycle hook BEFORE deletion`" comes before `delete_reciprocal_trust`. The HTTP handler is the same: `handlers/trust.py:1013` fires the hook, then `:1031` deletes. The real order is 5, 1, 2, 3, 4, 6, 7, 8, 9. The table's row text says "before the core delete", but its position under "Order, per row" says otherwise.
**Recommendation:** move the hook to the top of the table (step 0), or say in its row that it runs before step 1.

### 2. The changelog names the HTTP route; the test calls `delete_relationship`
**Severity:** Low
**Description:** `CHANGELOG.rst`: "retrying the same ``DELETE /<actor>/trust/<rel>/<peer>`` finishes them". The test's `same-row` route calls `trust.delete_relationship(first)`. The handler adds a pre-check of its own (`handlers/trust.py:946-960`) that answers 404 once the row is gone. Below that check the path is the same, so the claim holds. But last run's Issue 1 asked for an HTTP case.
**Recommendation:** add one HTTP `DELETE` case with a sibling fault, or name `delete_relationship` and the handler together.

### 3. The window between reading a row and deleting it now covers the whole sweep
**Severity:** Low
**Description:** at `trust.py:221-226`, the delete of a row loaded at `self.get()` now comes after the sweep. A re-authorisation during that time rewrites the row under the same deterministic peer id, with fresh provider tokens and permissions. The stale delete then removes the refreshed row. Step 4 has already run, so the new `oauth_tokens:<peer>` is left without a row. Those tokens grant nothing there, but they are kept. The same window existed before for steps 4-7; it is wider now.
**Recommendation:** accept it and add it to the table's "Known residue", or run step 4 again after step 7.

### 4. Smaller points
- **A vacuous assertion:** `tests/test_trust_core.py:384`
  "`mock_registry.delete_client.assert_not_called()`". `Trust.delete`
  never calls `delete_client` now. Its comment at `:361`, "Physical delete
  fails (record NOT removed)", no longer describes the test. Assert
  `disable_client` and `revoke_connection_tokens` instead.
- **Malformed index values:** `client_registry.py:492` "`return owner if isinstance(owner, str) and owner else None`".
  On the `actor_deleted` path, a truthy non-string index value used to
  refuse the index delete; it now deletes the row. Only
  `_update_global_index` writes that row, always as a string, so nothing
  produces the case.
- **Not verified, app-triggered:** a `trust_deleted` hook that calls
  `delete_client_connection` for the same client re-enters the sweep. The
  guard stops only `Trust.delete` from sweeping, not the sweep itself.
  This is not new in this delta. Note it in the table beside "Hooks must
  tolerate" a repeated delete.

## Overall Assessment

Iterations 30-32 close both Medium issues from the seventh run. The sweep
now runs before the row, so every route's retry handle is the route's own
row. The `same-row` route catches the old order in 10 cases.

The context-local guard prevents recursion on every path the reviewers
traced, and it is reset in a `finally`. The index-owner check cannot be
steered by an attacker. The arm-2 gate cannot lock out a row the library
wrote. The Full tier is green on both backends.

What remains is wording: the hook's place in the table, the changelog
naming the HTTP route, one more residue entry, and a vacuous test
assertion. None of it blocks the PR. It can be fixed in one small
iteration, or alongside the PR's first review round.
