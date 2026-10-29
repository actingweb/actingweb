# Verification: DB-layer fault contract (Phases 1-2, PR 1), second run

**Date:** 2026-10-29
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 8e8b4df (base; all Phase 1-2 work and Iterations entries 1-9 uncommitted)

Scope: Phases 1-2 and Iterations entries 1-9. Phases 3-4 are not started, so
the plan stays `active` and gets no `verified:` link.

## Automated Check Results

- **Browser QA:** N/A. No phase changed a page.
- **Second opinion:**
  - outside-voice ran Codex (`codex exec -s read-only`, unsandboxed) and then
    a fresh-context Claude read.
  - `/code-review high` ran over the working tree.
  - A focused security review traced every new re-raise one frame up and
    found nothing at confidence 8 or above.
  - Every finding below was re-read against its line in this tree.
- **Full tier** (run verbatim after entries 1-9):
  - ruff, ruff format (431 files), pyright: pass, 0/0.
  - `verify_groups.py`: 50 groups.
  - DynamoDB `make test-all-parallel`: 4182 passed, 31 skipped.
  - PostgreSQL `make test-all-parallel`: 4071 passed, 142 skipped.
  - Docs build: clean.
- **Benchmarks:** not re-run. The previous run's attribute-table failure
  (fresh container) is a known pre-existing item, and entries 1-9 do not
  touch list storage.

## Phase Verification

### Phases 1-2 - ISSUES FOUND

**Changes verified (entries 1-9):**
- **Entry 1 (A):**
  - `actingweb/handlers/properties.py` re-raises `DbError` ahead of the
    legacy fallback in all three permission checks and both bulk filters;
    the same is in place in `methods.py`, `actions.py`,
    `interface/hooks.py` `_check_hook_permission`, `authenticated_views.py`
    and the MCP list and item gates.
  - The security review confirmed that every caller of these checks sits
    outside any `try`.
- **Entry 2 (C-G):** `auth.py` (both OAuth2 checks), the MCP bearer path
  (`TokenStoreUnavailable`), `oauth2_callback.py` and
  `oauth_session.complete_claimed_session` re-raise.
- **Entries 3-7:**
  - H: `Subscription.add_diff` rolls back on a raise;
  - I: `Actor.create` re-reads the matched row;
  - K: the drain removes entries after `_set_state`;
  - L: `_remove_for_replacement` pre-reads the lists;
  - M: a `trustee_root` fault rolls the create back.
- **Entry 8 (J):** 25 handler 5xx catch-alls re-raise.
- **Entry 9 (P):** type hints on the two `_fetch` helpers.

**Tests verified:**
- `tests/test_db_fault_permissions.py` (7 tests); six fail with the handler
  and hook files stashed.
- `tests/test_db_fault_auth_paths.py` (4 tests); all four fail with the C,
  D and G re-raises removed.
- `tests/test_db_fault_partial_state.py` (5 tests); all five fail with the
  entry 3-7 edits reversed.
- E, F and the entry-8 sweep have no dedicated tests, as the plan entries
  say.

**Deviations from plan:** none beyond those recorded in the Iterations
entries.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A: permission fault falls back to the legacy grant | Fixed | Entry 1; `tests/test_db_fault_permissions.py`. A further ALLOW path through the hook runner remains (new Issue A2) |
| B: MCP lists show denied items | Fixed at the filter, not at the wire | The re-raise reaches `mcp.py:992` and answers JSON-RPC `-32603` with the `DbError` text (B2) |
| C: SPA/OAuth2 bearer answers 401 | Fixed | `auth.py` re-raises at both `_check_oauth2_token` catch-alls |
| D: MCP bearer answers 401, negative trust cached | Partly | The validated path converts to `TokenStoreUnavailable`; the cache-hit trust lookup at `mcp.py:2282` sits outside that `try` and reaches `mcp.py:992` (B2) |
| E: state-selected callback falls through | Fixed | `oauth2_callback.py:557` |
| F: callback completes without the trust | Partly | It now raises, but after the actor was created and its tokens written (O2) |
| G: email form returns a failed sign-in | Partly | It now raises, but after up to five store writes (O2) |
| H: diff sequence not rolled back | Partly | Rolled back now, but the rollback is an absolute write and the in-memory sequence drifts (E2); other strict reads still abort `register_diffs` (C2) |
| I: unique-creator match has no row handle | Fixed | `actor.py:462` |
| J: handler catch-alls answer 500 | Partly | The MCP dispatchers and the JSON-RPC method handlers were not swept (B2, P2) |
| K: drain loses buffered callbacks | Partly | Removal now follows the state write, but still precedes the handler and `_update_last_seq`, and runs one read-modify-write per entry (D2) |
| L: hook and tombstone before the strict reads | Partly | `Actor.delete` re-reads after the hook; tokens are revoked before the pre-reads (O2) |
| M: unannounced actor after a store fault | Partly | A failed row removal in the rollback is swallowed, and a marker fault answers 400/403 where a `trustee_root` fault answers 503 (I2) |
| N: cleanup reads fold | Filed | `thoughts/todo/adoption-fault-and-hygiene-followups.md` |
| O: BS bound only after a vouched actor | Accepted | Plan, pre-implementation review |
| P: hygiene | Type hints fixed; the rest filed | Entry 9; follow-ups todo |

## Remaining Tasks

- [ ] A2 and B2 before PR 1 opens: A2 is the remaining ALLOW path, and B2
      puts actor ids in MCP response bodies.
- [ ] Decide the approach to C2-I2. The per-site sweep has needed a further
      frame in each of the last two runs (see the assessment).
- [ ] J2, a pre-existing key overwrite in the same fault class, as its own
      fix (`/fix_bug`) or a todo.
- [ ] Phases 3-4 (PR 2).

## Issues Found

### A2. A fault inside an `oauth_success` hook signs the user in
**Severity:** High (sign-in gate fails open)
**Description:**
- The lifecycle hook runner swallows every exception:
  `actingweb/interface/hooks.py:774`
  `except Exception as e: logger.error(f"Error in lifecycle hook for {event}: {e}")`.
  The result stays `None`.
- The sign-in paths read `None` as accepted:
  - `actingweb/handlers/oauth2_callback.py` (`oauth_valid = True`, `:659`);
  - `oauth_email.py:567` and `oauth2_spa.py:1033, 1205`:
    `oauth_valid = bool(result) if result is not None else True`.
- Since Phase 1, an application hook that checks an allowlist through
  `Attributes.get_attr` or a property list raises on a fault where it used to
  read `None` and reject.
- The property hook runners (`hooks.py:636/651`, `:1047/1064`) have the same
  shape: a faulting GET redaction hook returns the unredacted value.

**Scenario:** an app's `oauth_success` hook rejects addresses outside
`allowlist` (an `Attributes` bucket). During a throttle the hook raises, the
runner logs it, and the login is accepted.
**Recommendation:** re-raise `DbError` in the lifecycle and property hook
runners, so the request answers 503. Add a test with an `oauth_success` hook
that raises `DbError` and assert the callback does not sign in.

### B2. MCP's outer dispatch turns every fault into JSON-RPC -32603 with the `DbError` text
**Severity:** Medium
**Description:**
- `actingweb/handlers/mcp.py:992`
  `except Exception as e: ... -32603, f"Internal error: {str(e)}"` wraps the
  whole method dispatch, and so does `async_mcp.py:149`.
  `mcp.py:1941` ("Resource read failed: {str(e)}") is the same.
- The cache-hit trust lookup (`mcp.py:2282`) raises a bare `DbError` outside
  the `TokenStoreUnavailable` conversion.
- Calls still fail closed, but answer HTTP 200 with
  "database error during <op> for actor <id>" in the body, with no 503 and no
  `Retry-After`.

**Recommendation:** answer `_token_store_unavailable_response` for a
`DbError` at these dispatchers.

### C2. `register_diffs` still stops part-way through its subscribers
**Severity:** Medium
**Description:** entry 3 covers only `add_diff`. Three other strict reads in
the loop still abort it:
- `actor.py:3152` `sub_obj = self.get_subscription_obj(`;
- the trust read at `:2182`;
- `_filter_subscription_data_by_permissions`, which re-raises since entry 1
  (`:2486`).

A write that already committed answers 503, and subscribers already notified
get duplicates on the client's retry.
**Recommendation:** catch `DbError` per subscriber in the loop, log it and
continue.

### D2. The callback drain can still lose or duplicate callbacks
**Severity:** Medium
**Description:**
- `callback_processor.py:399-400` and `:680-681` remove drained entries one
  at a time, each a read-modify-write, before the handler runs and before
  `_update_last_seq`.
- A fault on the second removal, or a crash before `_update_last_seq`, leaves
  `last_seq` behind with the entries gone.
- `_update_last_seq` (`:166-172`, `except Exception ... return False`) folds
  `DbError`, and the caller answers success.
- The version check (`:195-201`) is a read-compare-write, not a conditional
  write. That predates 3.16.

**Recommendation:** remove all drained entries in one write after
`_update_last_seq` succeeds; prune entries at or below `last_seq` on read;
let `_update_last_seq` raise `DbError`.

### E2. The diff-sequence rollback can corrupt the sequence
**Severity:** Medium
**Description:**
- `subscription.py:131-133`: `increase_seq` bumps the cached sequence before
  `modify`. On a fault the object stays one ahead of storage, and the next
  `add_diff` skips a number.
- `decrease_seq` (`:151-152`) writes an absolute value and can overwrite a
  concurrent increment.
- On PostgreSQL a reused `seqnr` collides with the diff primary key
  `(id, subid_seqnr)` and wedges the subscription. On DynamoDB it overwrites
  the other diff.

**Recommendation:** restore the cached value when `modify` raises, and make
the decrement conditional on the stored value.

### F2. A racing duplicate subscription or peer-trustee create answers 503 on PostgreSQL
**Severity:** Medium
**Description:** `actingweb/db/postgresql/subscription.py:179` and
`peertrustee.py:181` wrap every exception, a `UniqueViolation` included, as
`DbError`. A duplicate used to answer False. Retries keep answering 503.
`DbActor.create` already maps `UniqueViolation` to False.
**Recommendation:** map `UniqueViolation` to False in both, with a test.

### G2. Permanent errors are answered 503 with Retry-After
**Severity:** Medium
**Description:**
- `_errors.db_error_answer` maps every `DbError` to 503.
- Some backend errors are not transient:
  - a DynamoDB item over 400 KB (`ValidationException` wrapped as
    `DbError("attribute set")`);
  - an indexed value over PostgreSQL's btree limit in
    `_update_lookup_entry_in_transaction`.
- A well-behaved client retries a request that will never succeed.

**Recommendation:** classify validation and size errors as a
non-retryable subclass (answered 4xx or 500), or leave them unwrapped.

### H2. A 503 from an SPA endpoint carries no CORS headers
**Severity:** Medium
**Description:** the app-level handlers
(`flask_integration.py` `_db_error_response`,
`fastapi_integration.py` `_db_error_response`) set only `Retry-After`. Entry
8's three `oauth2_spa.py` re-raises used to answer a 500 that a cross-origin
SPA could read. Now the browser reports a network error.
**Recommendation:** apply `spa_cors_headers` in the handlers for
`/oauth/spa/*`.

### I2. The create rollback is incomplete and inconsistent
**Severity:** Medium
**Description:**
- `actor.py:561-565`: a failed row removal in the `trustee_root` rollback is
  swallowed (`except Exception`, and a False result is ignored), so the
  unannounced actor can survive.
- `actor.py:520`: `set_confirmed` swallows a marker fault, so the same fault
  answers 400/403 from the factory but 503 when it hits `trustee_root`.

**Recommendation:** log a failed removal as the marker path does and leave
the tombstone for the next attempt; let a marker `DbError` raise like the
`trustee_root` one.

### J2. A fault reading the OAuth2 state key overwrites it (pre-existing)
**Severity:** Medium (predates this change)
**Description:** `actingweb/oauth2_server/state_manager.py:231`
`except Exception as e: logger.debug(...)` then generates and stores a new
`oauth2_state_encryption_key`. The property read already raised `DbError` at
`8e8b4df`. A throttle invalidates every MCP authorization in flight. This is
the same fault class, but outside Phases 1-2's list.
**Recommendation:** re-raise `DbError` before generating a key; fix through
`/fix_bug` with its own test.

### K2. The trust-type registry folds a fault into "no type"
**Severity:** Low (security review, confidence 4)
**Description:** `actingweb/trust_type_registry.py:206` `get_type`
(`except Exception` → `return None`), and the same at `:153` and `:232`.
A None type makes the evaluator answer NOT_FOUND, and the handlers take the
legacy fallback. It is reachable only on a registry cache miss after a
startup fault.
**Recommendation:** re-raise `DbError` in `get_type` and `_get_system_actor`.

### L2. `get_from_creator` gives up when its pick vanishes
**Severity:** Low
**Description:** `actor.py:390` loads only `best`. If that actor is deleted
between the ranking and the load, the call returns False. The old loop moved
on to the next candidate, so a sign-in can create a new vouched actor beside
an unvouched one.
**Recommendation:** fall back to the next-ranked candidate.

### M2. `InternalStore` keeps a value its failed write never stored
**Severity:** Low
**Description:** `attribute.py:119` sets `__dict__[k]` before `set_attr`,
which now raises. `Attributes` repairs its cache on a failed write;
`InternalStore` does not.
**Recommendation:** write first and cache after.

### N2. `CreatorTaken` documentation runs ahead of the code
**Severity:** Low
**Description:** nothing raises `CreatorTaken` in PR 1, but the CHANGELOG
says it answers 409. The docstring says the factory answers it with 403,
while the factory's catch-all maps it through `map_db_error` to 409.
**Recommendation:** say in the CHANGELOG that it is raised once uniqueness
is enforced (PR 2). Phase 3 sets the factory's own 403 handler ahead of the
mapping.

### O2. Fault ordering on the sign-in and replace paths
**Severity:** Low
**Description:**
- `oauth2.py:1779` revokes the victim's tokens before the entry-6
  pre-reads.
- `Actor.delete` re-reads the lists after the hook (`actor.py:735-738`).
- F and G raise after their store writes (`oauth2_callback.py:583-592`,
  `oauth_session.py:370-377`).

These are narrow windows with recoverable outcomes, since the user signs in
again.
**Recommendation:** pass the pre-read lists into `Actor.delete`; record the
rest in the follow-ups todo.

### P2. JSON-RPC method errors carry `str(e)`
**Severity:** Low
**Description:** `actingweb/handlers/methods.py:345` and
`async_methods.py:267` `"data": str(e)`.
**Recommendation:** use a fixed message for `DbError`.

## Overall Assessment

Entries 1-9 fixed what they targeted. Issue A's legacy-grant fallback is
closed and pinned by tests, and C, E and I are fixed. Both backends pass the
full tier.

PR 1 is still not ready:
- A2 is a second ALLOW path. Phase 1's strict reads make an application's
  sign-in hook raise where it used to read None, and the hook runner turns
  the raise into "accepted".
- B2 leaks actor ids in MCP bodies.

The pattern behind both runs' findings is the method. Each `except DbError:
raise` was checked one frame up, and the next run found the frame above that:
the evaluator, then its callers, then the hook runner, then the MCP
dispatcher. The code review's altitude note says the same. There are about 60
catch-alls today, and any new one undoes the contract without a word.

Before another per-site iteration, the owner should choose the approach:
- **Keep sweeping per site**, with A2 and B2 now and C2-I2 next.
- **Narrow `DbError` at the source.** Make the outermost runners (hook
  runners, MCP dispatch, the integrations) the only places that handle it,
  and add a lint test that fails on an `except Exception` in `actingweb/`
  with no `DbError` clause ahead of it.

Either way, J2 is a separate pre-existing bug and should go through
`/fix_bug`.
