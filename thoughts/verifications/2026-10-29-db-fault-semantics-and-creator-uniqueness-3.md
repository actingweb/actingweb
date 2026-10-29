# Verification: DB-layer fault contract (Phases 1-2, PR 1), third run

**Date:** 2026-10-29
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 8e8b4df (base; Phases 1-2 and Iterations entries 1-21 uncommitted)

Scope: Phases 1-2 and Iterations entries 10-21, the guarded sweep. Phases
3-4 are not started, so the plan stays `active` with no `verified:` link.

## Automated Check Results

- **Browser QA:** N/A. No phase changed a page.
- **Second opinion:**
  - **Outside voice.** Codex (`codex exec -s read-only`, unsandboxed) found
    one finding; a fresh-context Claude found eleven more. Its brief was
    narrowed to swallows the guard cannot see.
  - **`/code-review high`:** ten findings.
  - **Security review:** nothing at confidence 8, and nothing at MEDIUM.
    It read every `# folds DbError` marker on the auth, permission,
    adoption, MCP, token, logout and callback paths in context.
  - Every finding below was re-read against its line in this tree.
- **Full tier** (run after entries 10-21; only `thoughts/` files changed
  since):
  - ruff, ruff format (434 files), pyright: pass, 0/0.
  - `verify_groups.py`: 50 groups.
  - DynamoDB `make test-all-parallel`: 4198 passed, 31 skipped.
  - PostgreSQL `make test-all-parallel`: 4087 passed, 142 skipped.
  - Docs build: clean.
- **Guard** (`tests/test_db_fault_guard.py`): 0 violations.
- **Sweeps for what the guard cannot see** (outside voice):
  - no `contextlib.suppress` outside `actingweb/db/`;
  - no `return` or `break` in a `finally`;
  - the fire-and-forget tasks are HTTP-only;
  - `fanout`'s `gather(return_exceptions=True)` counts exceptions as
    failures.

## Phase Verification

### Phases 1-2 - ISSUES FOUND

**Changes verified (entries 10-21):**
- The guard enumerates every broad handler. The classification left 0
  violations, and the security review found every fold on a security path
  either free of database access or after the decision committed.
- A2: the hook runners re-raise (`interface/hooks.py`), and all five
  `oauth_success` callers re-raise ahead of their catch-alls. In
  `oauth2_spa.py` the cookies are set only after the hook.
- B2: the MCP dispatchers answer a `DbError` with a 503 JSON-RPC body that
  carries no fault text.
- C2, F2, J2, K2, N2: fixed as entered.
- G2 holds in the integrations; the MCP dispatchers bypass it (F3).
- H2 covers part of the cross-origin routes (C3).
- D2 and E2 are partly fixed; see A3, B3 and E3.

**Tests verified:** `tests/test_db_fault_guard.py`,
`tests/test_db_fault_third_pass.py` (12) and
`tests/test_oauth2_state_key_read_fault.py` (3) pass. With their fixes
stripped, 10 of the 12 and 2 of the 3 failed (entries 14 and 20).

## Previous Verification

**Previous:** thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A2: hook fault signs the user in | Fixed | `interface/hooks.py` lifecycle and property runners; `oauth2_callback.py`, `oauth2_spa.py`, `oauth_email.py` re-raise |
| B2: MCP bodies carry `DbError` text | Fixed; maps every fault to 503 (F3) | `handlers/mcp.py:992`, `:1963`; `async_mcp.py:149` |
| C2: `register_diffs` stops part-way | Fixed | `actor.py:3311` |
| D2: drain loses callbacks | Partly | Prune after the sequence write landed. Prune-on-read did not, and the raise after the handlers runs them twice (A3, D3) |
| E2: sequence rollback | Partly | The cache restore holds. The guarded rollback is still a read-then-write, and on PostgreSQL a lost reply after the diff commit wedges the subscription (B3, E3) |
| F2: PostgreSQL duplicate create answers 503 | Fixed | `db/postgresql/subscription.py`, `peertrustee.py` |
| G2: permanent errors answer 503 | Fixed in the integrations | `_errors.is_permanent`; bypassed on MCP (F3) |
| H2: no CORS on an SPA 503 | Partly | Covers `/oauth/spa/*` and `/oauth/logout` only (C3) |
| I2: create rollback incomplete | Not fixed, not filed | `actor.py:520` (G3) |
| J2: OAuth2 state key overwritten | Fixed | Entry 14 |
| K2: trust-type registry folds | Fixed | `trust_type_registry.py` re-raises |
| L2, M2, O2 | Filed | Follow-ups todo, "guarded sweep" section |
| N2: `CreatorTaken` wording | Fixed | `CHANGELOG.rst`, docs, docstring |
| P2: JSON-RPC `str(e)` | Fixed for `DbError` | Re-raised ahead of it; `str(e)` remains for non-DB errors |

## Remaining Tasks

- [ ] A3 and B3 (data loss or a wedged subscription on the callback and
      diff path) before PR 1 opens.
- [ ] C3-F3 in the same iteration; they are small and in files already
      touched.
- [ ] G3 (I2): fix or file.
- [ ] Decide on the five bundling candidates (see the Overall Assessment).
- [ ] Phases 3-4 (PR 2).

## Issues Found

### A3. The library's own auto-storage write is folded as "consumer handler, at-most-once"
**Severity:** High (a lost diff, silently)
**Description:**
- `actingweb/callback_processor.py:699`, and the async twin at `:411`:
  `except Exception as e:  # folds DbError: consumer handler is at-most-once by design; the state already advanced`.
- The handler built in `actingweb/handlers/callbacks.py:611-621` first runs
  the library's auto-storage (`store.apply_callback_data(cb.data)`), which
  now raises `DbError` on a fault. The fold logs it, `_update_last_seq`
  moves past the diff, and the publisher gets PROCESSED.
- The subscriber's mirrored copy has lost the diff, and nothing triggers a
  resync.
- The marker's reason is false: `last_seq` had not advanced, so a re-raise
  would have been safe.

**Recommendation:** re-raise `DbError` from the handler call in the
processor. Fold only around the application's hooks
(`callbacks.py:655, 686`), which keep their at-most-once semantics.

### B3. On PostgreSQL, a diff commit whose reply was lost wedges the subscription
**Severity:** High
**Description:**
- `actingweb/subscription.py` `add_diff` treats a `DbError` from
  `diff.create` as "not written" and rolls the sequence back.
- `actingweb/db/postgresql/subscription_diff.py:189`
  (`except Exception as e: raise DbError(...)`) has no `UniqueViolation`
  mapping.
- If the commit landed and the reply was lost, the next `add_diff` reuses
  N, collides on the primary key, and rolls back again. Every later diff
  fails.

**Recommendation:** treat a `DbError` from `diff.create` as ambiguous and
leave the gap (the subscriber resyncs) instead of rolling back; map
`UniqueViolation` in the PostgreSQL diff create as F2 did for subscriptions.

### C3. SPA CORS on a 503 misses three SPA routes and the other cross-origin JSON routes
**Severity:** Medium
**Description:** `actingweb/interface/integrations/_errors.py:133-135`
`return path.startswith("/oauth/spa/") or path == "/oauth/logout"`.
- The SPA handler also serves `/oauth/session`, `/oauth/revoke` and
  `/oauth/config` (`flask_integration.py:252-260`,
  `fastapi_integration.py:853-866`).
- `/oauth/email` in JSON mode, `/oauth/token`, `/oauth/register` and the
  factory JSON also send CORS headers normally.
- During a throttle a cross-origin SPA polling `/oauth/session` sees a
  network error, not the 503.

**Recommendation:** include the three SPA routes. Use the wildcard headers
on the routes that already send them, or attach the headers by handler
rather than by prefix.

### D3. The callback sequence write raises after the handlers ran, so a retry runs them again
**Severity:** Medium
**Description:**
- `actingweb/callback_processor.py:170-171` `except DbError: raise` was added
  for D2. It runs after the handler loop.
- The 503 makes the publisher resend N. `last_seq` is still N-1, so the
  handlers run again for N and every drained entry.
- Before, the write folded and the callback answered PROCESSED. The markers
  promise at-most-once delivery.

**Recommendation:** after the handlers have run, log a sequence-write fault,
still prune the drained entries, and answer PROCESSED. Or record the
sequence before running the handlers. State the delivery guarantee in the
hook docs either way.

### E3. Stale pending entries are not pruned on read
**Severity:** Medium
**Description:** `callback_processor.py:422-426` and `:710-714` prune only
after a successful sequence write. If the prune itself faults, the retry is a
DUPLICATE and never prunes. The stale entries count toward `max_pending` and
feed `_check_gap_timeout` until a later drain passes them. D2's
"prune on read" did not land.
**Recommendation:** filter entries at or below `last_seq` in `_get_pending`.

### F3. MCP answers every `DbError` as a retryable token-store fault, with no cause in the log
**Severity:** Medium
**Description:**
- `actingweb/handlers/mcp.py:992`, `:1963` and `async_mcp.py:149` call
  `_token_store_unavailable_response`.
- That function logs "MCP token store unavailable during authentication" and
  sets `Retry-After`, so G2's permanent-error 500 is bypassed. A 400 KB item
  written through an MCP tool is retried forever.
- The log blames authentication and carries no cause.

**Recommendation:** answer through `_errors.db_error_answer` and
`log_db_error` in a JSON-RPC body; keep the fixed text.

### G3. A marker fault and a `trustee_root` fault answer differently (I2, unfiled)
**Severity:** Low
**Description:**
- `actingweb/actor.py:520` `if not self.store.set_confirmed(...)` turns a
  marker-write fault into False, so the factory answers 400/403. A
  `trustee_root` fault answers 503.
- A failed row removal in either rollback is logged and swallowed (`:529`,
  `:564`).
- Neither is in the follow-ups todo.

**Recommendation:** let a marker `DbError` raise like the `trustee_root` one,
or file it.

### H3. The guard trusts any `except DbError` clause, even one that folds
**Severity:** Medium (a gap in the method)
**Description:** `tests/test_db_fault_guard.py:96-99`. Twenty
`except DbError` clauses in the tree do not raise, for example
`fanout.py:361`, `actor.py:3311` and `property_list.py:1361`. The guard
checks none of them, so a future `except DbError: return None` on a
permission path would pass.
**Recommendation:** require a marker or an ending `raise` on `except DbError`
clauses too.

### I3. A vouched sign-in fails on the provider bookkeeping write
**Severity:** Low
**Description:** `actingweb/oauth2.py:2052` `store.oauth_provider = ...` now
raises `DbError` on a write fault, so a returning user's sign-in answers 503
although nothing the login needs failed.
**Recommendation:** fold this one write, after the vouch check, with a marker.

### J3. Smaller items
**Severity:** Low
- `actingweb/subscription.py:171`: the guarded rollback is still a
  read-then-write. It is filed; the window stays open without a conditional
  write.
- `actingweb/attribute.py:120`: `InternalStore` caches before the write. Filed
  as M2.
- `actingweb/actor.py:376`: the ranked prefix reads each candidate twice and
  builds a fresh store for the pick. Accepted as O, with redundant reads to
  trim.
- `oauth2.py:1809`: the replacement's pre-reads are thrown away and
  `Actor.delete` reads again. Filed as O2.
- `actor.py:2537`: the marker on `is_subscription_suspended` names one
  caller; the public `is_suspended()` answers False on a fault.
- `mcp.py:1057`: the marker says "initialize needs no DB", but the body
  authenticates and writes client info.
- `handlers/meta.py:18-20` and `root.py:69`: `InternalStore` display reads
  answer an empty `trustee_root` on a fault.
- `oauth_session.py:215` and `oauth_state_store.py:176`: a conditional-delete
  fault reads as a lost race (400/expired). Both fail closed; reuse
  `consume_once`'s re-read.
- Type hints are missing on `subscription.py:303` `fetch` and on the
  untyped DynamoDB backend signatures touched by this work.

## Overall Assessment

The guarded sweep did what the last run asked. Every broad handler in the
library is classified, the guard pins that at 0, and the security review
found no fail-open on any auth, permission, sign-in, token or MCP path. A2,
B2, C2, F2, J2 and K2 are fixed, with tests that failed without them.

PR 1 is still not ready, for two High findings on the callback and diff path:
- A3: one fold whose reason was wrong loses a mirrored diff without a word.
- B3: one rollback that assumes a faulted write did not land can wedge a
  PostgreSQL subscription for good.

The method now works: these sit in code the guard already lists. But the
outside voice's verdict is right, and H3 is its mechanical form: the guard
proves a reason exists, not that it is true.

Recommended next iteration, one batch:
- **The callback/diff path:** A3, B3, D3, E3.
- **Small follow-ons in files already touched:** C3, F3, H3, I3, and G3 (fix
  or file).
- **The five bundling candidates** from today's evaluation, if the owner
  agrees: the two maintenance tools exiting 0 on an unreadable store, the
  trust-type registry's default types not retried after a fault,
  `InternalStore`'s cache-before-write (M2), `get_from_creator`'s fallback
  when its pick vanishes (L2), and the plaintext key log.

Then a fourth verification, with the outside voice briefed to test the
reasons on the markers along the subscription, callback and diff path.
