# Verification: 3.16 dependency-security roll-up (fifth run)

**Date:** 2026-11-05
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** see the plan's `**Research:**` line; the delta also follows
thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md
**Branch:** release/3.16.0-dependency-security
**Commit:** d26c0b2

Scope: the delta since the fourth verification, `722cd3e..d26c0b2`:
- `ec62ca6`, Iterations 14-16;
- `1f1879a`, the two audits, research only;
- `d26c0b2`, Iterations 17-20: the client-deletion fixes D1 and D3-D8, and
  the investigation of D2.

This run also records what happened to each of the fourth verification's
eight issues. The earlier phases are unchanged outside this delta and were
verified in the previous runs.

## Automated Check Results

- **Browser QA:** N/A. No phase in the delta changes anything a user sees.
- **Second opinion:** two providers ran through the outside-voice agent, on
  the diff range with a list of the fixes already made in Iteration 20:
  - codex (`codex exec -s read-only`) found 2 issues;
  - a fresh-context Claude reviewer found 7.

  I re-checked the High one and the Mediums I kept against the tree (below).
  The built-in code review was not run separately: per
  scale-reviews-to-the-delta, this pass and the Iteration 20 review already
  cover the same code.
- `ruff check`: pass.
- `ruff format --check`: pass, 519 files.
- `pyright`: 0 errors, 0 warnings.
- `verify_groups.py`: all 53 groups documented.
- `make test-all-parallel`, DynamoDB: 5661 passed, 60 skipped, 1 xfailed.
- `make test-all-parallel`, PostgreSQL: 5458 passed, 263 skipped, 1 xfailed.
- `sphinx-build -W`: pass.

## Phase Verification

### Iterations 14-16 (`ec62ca6`): VERIFIED

**Changes verified:**
- `creators=` is required and passed explicitly.
  - Five callers pass `"none"`: `db/dynamodb/property.py:387,455,497,554`
    and `property_lookup.py:262`.
  - The creator writes pass `"guarded"` or `"unguarded"`:
    `dynamodb/actor.py:300,358,418,779,808,839`.
- `interface/oauth_client_manager.py:173`: the not-found retry now ends the
  connection.
- The doc fixes are in place: `v3.16.rst:276,742,884`,
  `configuration.rst:43`, `database-backends.rst:577` and
  `mcp-applications.rst:514`.

### Iterations 17-20 (`d26c0b2`): ISSUES FOUND

**Changes verified:**
- D1, a disconnect no longer deletes another actor's client:
  - `trust.py:151-169` checks ownership and revokes before the row delete;
  - `trust.py:214-225` routes the owner and a non-owner apart;
  - `client_registry.py:360-378` has the `delete_client` guard;
  - `client_registry.py:457-492` adds `client_owned_by`,
    `revoke_connection_tokens` and `delete_client_connection`.
- The remote-peer route is closed:
  - `trust.py:21-36`: `is_valid_peer_id` refuses the OAuth2 prefixes;
  - `trust.py:254-276`: the origin gate.

  The second-opinion probe checked every place a peer id comes in
  (`actor.py:1678,1808,1931`, `handlers/trust.py:421`) and found none that
  bypasses the check.
- D5: `_extract_client_id_from_peerid` accepts every `OAUTH2_SOURCES`
  prefix.
- D6 and D7: the side stores are deleted right after the row
  (`trust.py:186-208`), and `trust_manager.py:608-616` clears stale
  permissions before a new row.
- D8: the token sweep runs a mark-first pre-pass.
- The actor-deletion index check is in `client_registry.py:328-343`.

**Tests verified:**
- `tests/test_client_connection_deletion.py` has 13 tests covering the
  routing, the ordering, the guard, the origin gate, the peer-id refusal
  and the chain pre-pass.
- `tests/integration/test_trust_oauth_integration.py:725,778` hold the two
  end-to-end cases. Both failed on the old code.

**Deviations from plan:** none unrecorded. D2 is filed as a todo with its
reasoning (Iteration 19).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-04-3-16-dependency-security-rollup-reverify-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. `guarded=True` default on property transactions | Fixed | Iteration 14; `creators="none"` at the five callers |
| 2. verify-orphans listed as calling `iter_rows` | Fixed | `v3.16.rst:742` |
| 3. The retry after a fault answered "not found" | Fixed | `oauth_client_manager.py:173`; `test_a_retry_after_a_trust_fault_finishes_the_leftover_rows` |
| 4. "raised after them" did not hold on the cascade path | Fixed in code by `d26c0b2` (the cascade no longer folds); the changelog sentence is now stale (new Issue 7) | `trust.py:214-225` |
| 5. Exempt creators left out | Fixed | `v3.16.rst:276,884`, `configuration.rst:43` |
| 6. "Only `Config()` code meets it" was too strong | Fixed | `database-backends.rst:577` |
| 7. An async Flask hook returns its coroutine's repr | Documented | `mcp-applications.rst:514` |
| 8. Garbled changelog clause | Fixed | `CHANGELOG.rst:1582` |

## Remaining Tasks

- [ ] Issue 1 before the PR.
- [ ] Issues 2-5: fix, or accept in the plan with a sentence each.
- [ ] Issues 6-9: small. Fix them alongside the others.
- [ ] `thoughts/todo/client-deletion-leaves-other-actors-connections.md`
  (D2) is filed with an `INDEX.md` row and stays open as designed.

## Issues Found

### 1. Bulk relationship deletion raises when a sibling sweep already removed a row in its list
**Severity:** High
**Description:**
- `actor.py:2207-2210`: "`if not dbtrust.delete(): ... raise DbError("trust delete", self.id)`" (new in `d26c0b2`).
- On both backends, `Trust.delete()` returns False when the row is already
  gone. `Trust.delete` calls `self.get()`; if that finds no row, the handle
  is None. Then `db/dynamodb/trust.py:435` ("`if not self.handle: return
  False`") and `db/postgresql/trust.py:611` return False.
- `delete_reciprocal_trust()` reads its list of relationships once.

**Failure scenario:**
1. An actor holds two rows of one client, for example a tagged row and a
   legacy `oauth2:` row (`trust_lookup.py:101`), or an owner's registration
   row plus the row from authorizing its own client.
2. The cleanup for row 1 runs `_delete_client_trust_relationship`, which
   deletes row 2.
3. The loop then reaches row 2 in its stale list, gets False, and raises.
4. The caller gets a 503 and the rest of the actor's relationships are
   skipped.

This affects `Actor.delete`, `purge_relationships` and
`TrustManager.delete_all_relationships`. The same raise fires when a peer's
reciprocal DELETE lands between the list read and the delete. I confirmed
by hand that a missing row returns False. The Iteration 20 rule treated
False as "not deleted", but on these backends it means "already gone".

**Location:** `actingweb/actor.py:2207-2210`

**Recommendation:** on False, re-read the row strictly and raise only if it
still exists; otherwise continue. Add a regression test with two rows of
one client deleted in bulk.

### 2. The owner path's 503 leaves the client live with no retry through the same route
**Severity:** Medium
**Description:** `trust.py:214-217`: "`if owner: if not registry.delete_client(...): raise DbError("OAuth2 client deletion", ...)`". This runs after `self.handle.delete()`.

**Failure scenario:**
1. An owner disconnects its own SDK client's row.
2. `delete_client` cannot confirm the deletion, so the caller gets 503.
3. The retried DELETE on the trust route answers 404, because the row is
   already gone.
4. The client, its index row and the owner's tokens stay live.

The provider-token raise at `:207-208` has the same shape. The orphaned
`oauth_tokens:<peerid>` (for example a Google refresh token) stays until
the next reconnect overwrites it (codex).

**Location:** `actingweb/trust.py:203-217`

**Recommendation:** for an owner, disable the client before the row delete,
just as the non-owner path revokes first. Alternatively, delete the provider
tokens before the row, since they grant no access here.

### 3. MCP cache eviction is skipped when `Trust.delete` raises after the row is gone
**Severity:** Medium
**Description:** `trust.py:232-234` (`evict_caches_for_actor`) runs only if
nothing above it raised: neither the side-store deletes nor the owner
branch. After a 503 in that window, a warm process keeps serving the cached
actor and trust list (up to 300 s) for a row that no longer exists.

**Location:** `actingweb/trust.py:186-234`

**Recommendation:** evict in a `finally` once `result` is True.

### 4. Clearing permissions misses the singleton cache that permission checks read
**Severity:** Medium
**Description:**
- The new code builds a fresh store instance in two places:
  - `trust.py:195`, "`permission_store = TrustPermissionStore(self.config)`";
  - `trust_manager.py:616`.
- `permission_evaluator.py:167` reads `get_trust_permission_store(config)`,
  a singleton with its own `BoundedDict` cache and no TTL
  (`trust_permissions.py:101`).

So after a delete, the old custom grants stay cached in that process. A
reconnect with the same deterministic peer id is then evaluated against
them until eviction or a restart. The fresh instance is older than this
delta (`actor.py` used it before), but the new comment at
`trust_manager.py:608-612` promises a fresh start, and the cache breaks it.

**Location:** `actingweb/trust.py:195`, `actingweb/interface/trust_manager.py:616`

**Recommendation:** use `get_trust_permission_store(config)` in both
places, and test that a reconnect evaluates with the defaults.

### 5. Pre-3.4 peer rows pass the origin gate
**Severity:** Low
**Description:** `trust.py:271`: "`via in OAUTH2_SOURCES or (via is None and prefix in OAUTH2_SOURCES)`".

Peer rows have been stamped `established_via="trust"` only since 3.4. So a
row planted through `POST /trust` before then, with an `oauth2_client:` peer
id, has `None` and still names a client. Its peer can delete it with its own
secret and trigger the revoke-and-sweep. Exploiting this needs a pre-3.4
plant.

**Recommendation:** also require an empty `baseuri` (OAuth2 rows have none),
or report such rows in the changelog's **Check:**.

### 6. `delete_permissions()` result ignored
**Severity:** Low
**Description:** `trust.py:196-197`. Both backends raise on a fault, so
False only means the row is missing. This is low in practice (codex).

**Recommendation:** raise on False for consistency with the provider-token
delete.

### 7. The older client-deletion changelog entry says the cascade logs the fault
**Severity:** Low
**Description:** `CHANGELOG.rst:1585-1586`: "when the deletion started from a
trust-row delete, that cascade logs it". Since `d26c0b2` that path raises.

**Recommendation:** drop the clause, or say the fault is raised there too.

### 8. The token sweep's pre-pass skips an unreadable bucket silently
**Severity:** Low
**Description:** `token_manager.py:1737`: "`(self._snapshot_bucket(actor_id, bucket) or {})`".

If the first snapshot faults and the second succeeds, chains are marked per
token after the snapshot. The fence is then weaker, and nothing logs it.

**Recommendation:** count a failed first-pass read as unconfirmed, or at
least log it.

### 9. Smaller points
- **`delete_peer_trustee` can't finish.** At `actor.py:1273-1277`, a
  `DbError` from `delete_reciprocal_trust` after the remote delete leaves
  the local rows behind. On a retry the remote answers 404, which the code
  reads as "unwilling". This is older than the delta, but the new raise
  makes it reachable.
- **Dead code.** `Trust._is_oauth2_client_trust` (`trust.py:238`) is now
  unused.
- **A stale docstring.** `TrustManager.delete_all_relationships`
  (`trust_manager.py:323`) still says `delete_reciprocal_trust` deletes the
  permissions; `Trust.delete` does now.
- **Adoption with a mismatched client row.** `_delete_actor_clients`
  without `actor_deleted` (`oauth2.py:2011-2015`) raises `DbError`
  permanently for a bucket row whose index names another actor; the
  `actor_deleted` path skips that case. This is an edge case.

## Overall Assessment

The delta does what Iterations 14-20 say. All eight issues from the fourth
verification are fixed or documented. D1 is closed: a non-owner can no
longer delete a client, and a remote peer can no longer plant or overwrite
an OAuth2 row. D2 is correctly placed as server-local and filed. Both
backends are green.

One regression needs fixing before the PR. Iteration 20 made a False from
`Trust.delete()` raise, but on both backends False means the row is already
gone. Bulk deletion of an actor whose rows include two rows of one client
now fails with 503 every time (Issue 1). Issues 2-4 are on the same fault
paths: retries that can't reach the leftovers, eviction skipped on a raise,
and a permission cache the clear doesn't reach. Another `/iterate_plan`
should take Issues 1-4 together, with a regression test each.
