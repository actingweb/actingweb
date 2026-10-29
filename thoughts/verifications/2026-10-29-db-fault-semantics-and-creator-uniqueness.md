# Verification: DB-layer fault contract (Phases 1-2, PR 1)

**Date:** 2026-10-29
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 8e8b4df (base; all Phase 1-2 work uncommitted)

Scope: Phases 1-2 only (PR 1). Phases 3-4 (PR 2) are not started, so the
plan keeps `status: active` and gets no `verified:` link from this document.
There is no feature document.

## Automated Check Results

- **Browser QA:** N/A. No phase changed a page.
- **Second opinion:**
  - outside-voice ran Codex (`codex exec -s read-only`, unsandboxed) and then
    a fresh-context Claude read of the diff; 12 findings.
  - `/code-review high` ran over the working tree; 10 findings.
  - A focused security review found nothing at confidence 8 or above. Its one
    candidate, at confidence 4, is the MCP listing fail-open (Issue B below).
  - Every finding kept below was re-read against the cited line in this tree.
- **Full tier** (run verbatim, one run at a time):
  - ruff, ruff format (428 files), pyright: pass, 0/0.
  - `verify_groups.py`: 50 groups.
  - DynamoDB `make test-all-parallel`: 4166 passed, 31 skipped.
  - PostgreSQL `make test-all-parallel`: 4055 passed, 142 skipped.
  - Docs build (`sphinx-build -W`): clean.
- **Benchmarks** (`-m benchmark`, alone): 15 passed, 2 failed. The two
  attribute benchmarks fail with `ResourceNotFoundException ... test_attributes`
  on the fresh container the full tier's `down -v` leaves. That is the
  pre-existing item "Benchmarks on a fresh DynamoDB container" in
  `thoughts/todo/adoption-fault-and-hygiene-followups.md`, not a regression.
  No attribute timings were obtained this run.

## Phase Verification

### Phase 1: The fault contract - ISSUES FOUND

**Changes verified:**
- Both backends raise `DbError` on a fault, and `strict=False` folds it:
  - actor: `actingweb/db/dynamodb/actor.py` `get`, `get_by_creator`, `create`,
    `modify`, `delete`, `DbActorList.fetch`, and the PostgreSQL equivalents;
  - attribute: `get_bucket` (the `try` now covers the iteration), `get_attr`,
    `get_attr_strict`, `set_attr`/`delete_attr`, `delete_bucket`, the bucket
    list;
  - trust, peer-trustee, subscription and diff single gets and list fetches;
  - property lookups and reverse lookups, and the property list fetches.
  This matches the plan.
- PostgreSQL `DbProperty.set` and `DbPropertyList.delete` no longer catch
  inside the transaction; `TestPostgresPropertyRollback` asserts no commit.
- `actingweb/db/protocols.py`: the module docstring states the contract once,
  and the four texts the plan named are fixed. `DbPropertyLookup` has no
  protocol class, which the plan's notes record.
- `actingweb/interface/integrations/_errors.py`, plus app-level handlers in
  Flask (`register_error_handler`) and FastAPI (`add_exception_handler`).
- `actingweb/attribute.py`: strict by default; `InternalStore` folds.
- The display callers in the plan's list pass `strict=False`.

**Tests verified:**
- `tests/test_db_fault_contract.py`: 76 tests. Every listed read is covered on
  both backends (fault raises, `strict=False` folds), as are absence, deletes
  of absent rows, conditional-delete replay, expiry and the wrapper.
- `tests/test_db_fault_http.py`: 503 with `Retry-After: 5` and the fixed
  body, with no actor id and no traceback, for library and consumer routes on
  Flask and FastAPI; 409 for `CreatorTaken`.
- The folding tests the plan named are rewritten.

**Deviations from plan:**
- Writes raise on both backends, not just modify/delete. This is acceptable
  and recorded in the plan.
- The except-site sweep was not complete. The plan asked for "every
  handler-level `except Exception` in both integrations that sits on a
  request path", and its notes list the sites taken. But catch-alls one
  frame further in still fold a `DbError` into 401, 500 or "allow"
  (Issues A, C, D, H, J).

### Phase 2: Callers B1-B11 and BR/BS - ISSUES FOUND

**Changes verified:**
- B1-B11: each row's read now raises, and the plan's notes name the re-raise
  sites. `Actor.delete` reads its trust and subscription lists before
  `deletion.mark_actor_deleted` (B8). `fanout` skips the delivery when breaker
  state cannot be read (B11).
- BR:
  - `actingweb/actor.py` `get_from_creator` raises
    `DbError("actor marker read", ...)` for an unreadable marker in the
    prefix;
  - the successor step in `actingweb/oauth2.py` creates a successor only when
    every remaining actor is `replace`.
- BS:
  - `get_by_creator(ids_only=True)` on both backends;
  - `get_from_creator` reads in id order up to the first vouched actor, plus
    `SWEEP_LIMIT`;
  - `_factory_siblings` takes the listing and the classes it is passed.
- Docs: a Breaking CHANGED entry and FIXED entries B1-B11, BR and BS in
  `CHANGELOG.rst`; "Fault contract" in `docs/migration/v3.16.rst`; "Fault
  Contract" in `docs/reference/database-backends.rst`.

**Tests verified:**
- `tests/test_db_fault_callers.py`: 11 tests, one per B row, each injected at
  the backend's lowest seam (`seam_fault`). All eleven fail at `8e8b4df`
  (copied into a worktree there) and pass here.
- `tests/test_adoption_bounded_reads.py`:
  - BR fails at `8e8b4df`;
  - the BS read count was 61 actor reads and 81 marker reads at `8e8b4df`,
    and is 12 and 42 now;
  - BU's three cases and the BS past-the-cap fault pass on both trees
    (coverage, not fixes).

**Deviations from plan:**
- The successor step keeps one ids-only re-list (the race check). Acceptable
  and recorded.
- The class map can go stale on the create side, under the existing "two
  concurrent first sign-ins" limitation. Recorded.
- B3 changed the evaluator to raise instead of DENIED without checking what
  its callers do with the raise. This is a defect (Issue A).

### Failure Scenarios

The plan promised these; each was checked against the code.

| Plan scenario | Promised handling | Status |
| --- | --- | --- |
| Default flip on a hot read answers 503 | the mapping and its tests | Partly. `test_db_fault_http.py` covers the integrations' own sites; inner catch-alls still answer 401/500 (C, D, H, J) |
| Custom backend without `strict` | migration checklist | Present (`docs/migration/v3.16.rst`, "Custom database backends") |
| A missed display caller answers 503 | full tier and grep | Holds for the full tier; the grep classification is in the plan's notes |
| A conditional delete swept into "absent counts" | exemption and replay tests | `TestConditionalDeleteReplay` passes on both backends |
| B7 skip; the peer retries | 503 and the queue untouched | Holds for a fault on the first read only; a fault mid-drain loses buffered callbacks (Issue K) |
| B8 reorder | tombstone written after the reads | Holds in `Actor.delete`. The callers that write their own tombstone and fire `actor_deleted` first undo it: the HTTP DELETE (AW, known) and `_remove_for_replacement` (Issue L) |
| BS ids-only listing lag | AZ rule fails closed | `test_victim_missing_from_the_listing_fails_closed` and the rewritten `TestSweepReadFaults` pass |

## Security property demonstrated

- **Fail closed on an unreadable marker:**
  `TestBRUnreadableMarker.test_lookup_fails_closed_and_never_strands_the_vouched_actor`
  asserts `pytest.raises(DbError)`, and that both actors remain with their
  classes unchanged.
- **No secret rotation on a read fault (B1):**
  `TestB1OAuthTrustUpsert` asserts the trust list is byte-identical after the
  fault.
- **No actor id in a 503 body:** `_assert_unavailable` in
  `tests/test_db_fault_http.py` checks the body equals `UNAVAILABLE_BODY` and
  that `ACTOR_ID not in text`.
- **Not demonstrated, and false:** that a permission-store fault denies
  (Issue A).

## Remaining Tasks

- [ ] Issues A-D before PR 1 opens. A is an authorization regression.
- [ ] Issues E-P through `/iterate_plan`, or explicitly accept them.
- [ ] Narrow or fulfil the CHANGELOG and migration-guide promise that a fault
      "answers 503" (Issue J).
- [ ] Re-run the attribute benchmarks on a warmed container.
- [ ] Phases 3-4 (PR 2).

## Issues Found

### A. A permission-store fault now grants what an explicit DENY override refuses
**Severity:** High (authorization regression introduced by this diff)
**Description:** Phase 2 made the four `permission_evaluator` catch-alls
re-raise `DbError` instead of returning `PermissionResult.DENIED`. Their
callers catch `Exception` and fall back to the legacy access list:
- `actingweb/handlers/properties.py:164` "# Fall back to legacy authorization
  on errors" (also `:1818`, `:2001`);
- `actingweb/handlers/methods.py:72`;
- `actingweb/handlers/actions.py:72`;
- `actingweb/interface/hooks.py:442` "return True  # Allow on errors to
  maintain compatibility".

The legacy access list grants `friend` peers `properties`, `methods` and
`actions` (`config.py`). Before this diff the evaluator answered DENIED on a
fault.
**Scenario:** a `friend` peer has an override that denies writing `secret/*`.
The attributes table (where overrides live) throttles while the trusts table
answers. `evaluate_property_access` raises `DbError`, and `properties.py:164`
falls back to `check_authorisation`, which allows the write.
**Location:** `actingweb/permission_evaluator.py` (the four re-raises), plus
the callers above.
**Recommendation:** re-raise `DbError` ahead of each caller's catch-all (503),
or deny there. Add a test that injects a permission-store fault against a
DENY override and asserts 503, not 200.

### B. MCP list responses include denied items during a fault
**Severity:** Medium
**Description:** `actingweb/handlers/mcp.py:1298` `except Exception as e:`
"# Fail-open on evaluation errors to avoid hard lockouts". The same pattern
is in the resources and prompts lists. These catch the evaluator's new
`DbError`, so `tools/list`, `resources/list` and `prompts/list` list hidden
items. Single-item calls still fail closed.
**Recommendation:** add `except DbError: raise` (or skip the item) in the
three loops.

### C. A token-store fault still answers 401 on the SPA and OAuth2 bearer path
**Severity:** Medium
**Description:** `actingweb/auth.py:364` `except Exception as e:
logger.error(f"Error during OAuth2 token validation: {e}"); return False`
wraps `_check_spa_token` (`:290`), so the new re-raise at `:418` is caught one
frame up. The async path has the same at about `:541`. A partial outage
(attributes table throttled, trusts table fine) answers 401 and signs SPA
users out. The CHANGELOG says this no longer happens.
**Recommendation:** re-raise `DbError` at both sites.

### D. The MCP bearer path answers 401 with `WWW-Authenticate`, and caches a negative trust
**Severity:** Medium
**Description:** `actingweb/handlers/mcp.py:2376-2381` re-raises only
`TokenStoreUnavailable` and returns None for any other exception, which the
callers at `:820` and `:951` turn into 401 plus `WWW-Authenticate`. The
strict actor load in `_get_or_create_actor_cached` now raises a plain
`DbError`. `_lookup_mcp_trust_relationship` (`:2569`) also folds `DbError` to
None, which `_trust_cache_put` caches as a negative entry for 10 s.
**Scenario:** during a throttle, MCP clients restart OAuth, or get -32003
errors and empty tool lists for 10 s.
**Recommendation:** add `except DbError: raise` at `:2380` and `:2569`.

### E. The state-selected OAuth callback swallows `DbError` from `adopt_actor` and goes on to look up or create
**Severity:** Medium
**Description:** `actingweb/handlers/oauth2_callback.py:554` `except Exception
as e: logger.warning(... "will lookup/create by identifier"); actor_instance = None`.
`adopt_actor` now raises `DbError` (its "never raises" docstring was removed
in this diff). A fault after `_remove_for_replacement` has deleted the actor
runs a second lookup on half-changed state in the same request, instead of
answering 503. Both reviewers found this.
**Recommendation:** `except DbError: raise` ahead of `:554`.

### F. The browser OAuth callback completes sign-in without the trust (B1 undone there)
**Severity:** Medium
**Description:** `actingweb/handlers/oauth2_callback.py:645` "# Don't fail the
OAuth flow - just log the error" catches the `DbError`
`create_oauth2_trust_relationship` now raises. The login succeeds with no
trust row.
**Recommendation:** re-raise `DbError` there.

### G. The email-form completion turns a fault into a failed sign-in after the session is consumed
**Severity:** Medium
**Description:** `actingweb/oauth_session.py:385` `except Exception as e:
logger.error(f"Error completing OAuth session: {e}"); return None` wraps the
lookup, the adoption and the store writes. A `DbError` becomes a 500 "Failed
to create actor" after the single-use session is gone, not a 503.
**Recommendation:** re-raise `DbError`. Note in the migration guide that the
user must restart the sign-in.

### H. `add_diff` no longer rolls back the sequence, and `register_diffs` stops part-way
**Severity:** Medium
**Description:** `actingweb/subscription.py:183` "# If diff creation failed,
rollback the sequence increment" runs only when `diff.create()` returns
False. Both backends now raise. The sequence is incremented with no diff
stored, the exception leaves `Actor.register_diffs` partway through its
subscribers, and a property write that already committed answers 503. This
contradicts the new comment at the `get_subscriptions(strict=False)` call,
which says a fault "skips diff registration ... instead of failing the write".
**Scenario:** of three subscribers, the second's diff write throttles. It
sees a sequence gap, the third is never notified, the client retries the
write, and the first gets a duplicate diff.
**Recommendation:** catch `DbError` around `diff.create`, roll back the
sequence and return False; keep `register_diffs` going over the rest.

### I. Actor.create's unique-creator passphrase match returns an actor with no row handle on DynamoDB
**Severity:** Medium (both known consumers run `unique_creator` on)
**Description:** `actingweb/actor.py:459` `self.handle = in_db` relies on
`get_by_creator` having loaded a row into `in_db.handle`. On DynamoDB the
consistent listing now reads through `Actor.get` (the model) and never sets
`self.handle`, which the old per-row `self.get()` did. A later
`modify()`/`delete()` on that instance returns False without a word.
**Recommendation:** load the matched row (`in_db.get(actor_id=c["id"])`)
before binding it. Phase 3 removes this path when the flag is on; until then
it is live.

### J. Handler modules outside the integrations still answer 500, and one puts the `DbError` text in the status line
**Severity:** Medium
**Description:** catch-alls in `handlers/oauth2_endpoints.py`
(`:199`, `:315`, `:469`, ...: registration, authorize, token) and in
`www.py`, `properties.py`, `meta.py`, `methods.py` and `actions.py` turn a
`DbError` into 500 without `Retry-After`. `actingweb/handlers/www.py:1186`
`self.response.set_status(500, f"Error processing property: {str(e)}")` puts
the `DbError` text, which can say "for actor <id>", in the status line. The
CHANGELOG's "DbError → 503" is therefore overstated.
**Recommendation:** sweep these modules (re-raise or `map_db_error`), or
narrow the CHANGELOG and migration-guide wording to the routes that were
swept.

### K. A fault while draining the callback queue loses buffered callbacks (B7)
**Severity:** Medium
**Description:** `actingweb/callback_processor.py:667`
`self._remove_pending(peer_id, subscription_id, next_seq)` runs before
`_set_state` inside the drain loop. If a later write raises, N+1 is already
gone from pending while state and `last_seq` have not moved. The peer
retries only N.
**Recommendation:** write state first and remove the drained entries in one
write afterwards, and test a fault in the middle of the drain.

### L. The replacement fires `actor_deleted` and writes the tombstone before `Actor.delete`'s strict reads
**Severity:** Medium
**Description:** `actingweb/oauth2.py:1784`
`deletion.mark_actor_deleted(actor_id, config)` and the `actor_deleted` hook
run before `victim.delete(notify_peers=False)`, whose new first step is the
strict trust and subscription reads. A fault there leaves the hook fired and
the tombstone set with nothing deleted. The next sign-in finishes the wipe
and fires `actor_deleted` again. This is the HTTP DELETE's AW shape on the
adoption path.
**Recommendation:** read the lists before the tombstone and the hook, or
record it with AW in the follow-ups todo.

### M. A post-create store write that faults leaves an actor that was never announced
**Severity:** Low
**Description:** `actingweb/actor.py:545` `self.store.trustee_root = trustee_root`
now raises `DbError` after the row and marker are persisted, so
`actor_created` never fires and a client retry creates a second actor.
**Recommendation:** use `set_confirmed` and roll back as the marker path does,
or file it.

### N. Two cleanup reads fold silently
**Severity:** Low
**Description:** `attribute_list_store.py` `list_all()` (`strict=False`)
feeds `CallbacksHandler._delete_revoked_peer_data`, so a fault leaves revoked
data with a success answer. `callback_processor.py:547`
`clear_all_state_for_peer` (`strict=False`) leaves state behind. The plan
listed both as display reads; they are cleanups.
**Recommendation:** read strictly at the cleanup callers, or log the skip.

### O. The BS bound holds only after a vouched actor
**Severity:** Low (accepted in the plan)
**Description:** `actingweb/actor.py:376`: with no vouched actor, every id is
in the prefix and read. The plan's pre-implementation review accepted this
for the default path, bounded by the next-major exit. Recorded so the next
verification does not rediscover it.

### P. Hygiene
**Severity:** Low
- `actingweb/db/dynamodb/trust.py:481` and
  `actingweb/db/dynamodb/subscription.py:207` `def _fetch(self, actor_id):`
  have no type hints, which `CLAUDE.md` requires on all functions.
- The read-then-classify loop exists three times (`get_from_creator`,
  `_factory_siblings`, the successor step), and the pick and the siblings are
  read twice.
- `callback_processor.py:681` (`handler(cb)` errors) and the owner's sweep at
  `oauth2.py:2045` swallow `DbError` by design. Note them in the docstrings.
- `_errors.find_db_error` follows `__context__`, so a bug raised while
  handling a `DbError` answers 503 instead of 500. This is unverified as a
  practical problem.

## Overall Assessment

The fault contract itself is implemented as planned on both backends.
`DbError` raises, `strict=False` folds, deletes confirm, and conditional
deletes are exempt. It is tested thoroughly: 87 new contract and HTTP tests,
eleven B-row tests that fail on the old code, and both full suites green.
BR and BS hold, with reads on the vouched path down from 61/81 to 12/42.

It is not ready for a PR. The sweep re-raised `DbError` where it was added
but did not check one frame up. As a result the permission evaluator's old
fail-closed DENIED became a raise into callers that fail open (Issue A), an
authorization regression a throttle can trigger. Several auth and OAuth
wrappers also still fold a fault into 401 or 500, which contradicts the
CHANGELOG's promise (C, D, E, F, G, J). Fix A-D, and decide on E-L, through
`/iterate_plan`, then verify again before `/commit` and PR 1. The plan stays
`active` (Phases 3-4 remain) and gets no `verified:` link from this run.
