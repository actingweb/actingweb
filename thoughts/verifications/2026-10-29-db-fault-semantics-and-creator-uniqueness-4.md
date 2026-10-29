# Verification: DB-layer fault contract (Phases 1-2, PR 1), fourth run

**Date:** 2026-10-29
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 8e8b4df (base; Phases 1-2 and Iterations entries 1-29 uncommitted)

Scope: Phases 1-2 and Iterations entries 22-29. Phases 3-4 are not started,
so the plan stays `active` with no `verified:` link.

## Automated Check Results

- **Browser QA:** N/A. No phase changed a page.
- **Second opinion:**
  - **Outside voice.** Codex (`codex exec -s read-only`, unsandboxed;
    re-run with stdin closed after the first attempt stalled) and a
    fresh-context Claude. The brief was to test the reasons on the
    subscription, callback and diff markers, not their presence.
  - **`/code-review high`:** ten findings.
  - **Security review:** nothing at confidence 8. It found that fault
    answers grant no cross-origin read the route's normal answer does not,
    and that the `get_from_creator` fallback cannot steer a sign-in into an
    attacker-controlled actor.
  - Every finding below was re-read against its line in this tree.
- **Full tier** (after entries 22-29):
  - ruff, ruff format (435 files), pyright: pass, 0/0.
  - `verify_groups.py`: 50 groups.
  - DynamoDB `make test-all-parallel`: 4214 passed, 31 skipped. The first run
    had one failure (`TestConditionalDeleteReplay`). It passed 3/3 alone and
    was an isolation bug in that test, fixed in entry 29.
  - PostgreSQL `make test-all-parallel`: 4103 passed, 142 skipped.
  - Docs build: clean.
- **Guard:** 0 violations.

## Phase Verification

### Phases 1-2 - ISSUES FOUND

**Changes verified:** entries 22-29 are in the tree as described.
- E3, F3, G3 and the five bundled items hold.
- A3, B3, C3, D3 and I3 are partly done (see the table).

**Tests verified:** `tests/test_db_fault_fourth_pass.py` (14 tests),
`TestD2CallbackDrain` (3) and `TestHDiffSequence` (1). With this batch's
source edits stripped from a verified backup, 15 of the 18 failed. The D3
test fails when stripped on its own (entry 28).

**Gap in the tests:** no test exercises `strict=False` through the list
wrappers. `TestC2RegisterDiffs` fakes `get_subscription_obj`, not the list
read, which hides B4.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A3: auto-storage fault folded | Partly | It re-raises (`callback_processor.py:433-438`), but its premise that "the publisher redelivers" is false (C4) |
| B3: PostgreSQL diff wedge | Partly | The sequence is kept on a `diff.create` fault. No `UniqueViolation` mapping, a non-atomic increment, and three skip points leave no gap (D4, G4) |
| C3: CORS on fault answers | Partly | The SPA and OAuth2 routes are covered; the factory route's in-handler mapping is not (I4) |
| D3: sequence write after the handlers | Partly | The drain loops fold it; the resync handlers do not, and a quiet subscription stalls (E4) |
| E3: stale pending entries | Fixed | `callback_processor.py:254`, `:338-343`, `:396-401` |
| F3: MCP fault mapping | Fixed | `mcp.py:2957`. A 409 gets the reason "Service Unavailable" (K4) |
| G3: marker-fault answer | Fixed | `actor.py:525-556` |
| H3: guard trusts `except DbError` | Fixed as a mechanism | It checks that a reason exists, not that it is true (F4) |
| I3: provider bookkeeping | Partly | Folded at `oauth2.py:2055` only; three more writes raise (K4) |
| J3 bullets | Mixed | `attribute.py` cache fixed; `decrease_seq`, the `oauth2.py:1809` pre-reads and the suspension query are open, and their todo record is gone (H4) |

## Remaining Tasks

- [ ] A4 and B4 before PR 1 opens: an authorization fallback, and a folding
      mechanism that never folds.
- [ ] Restore the lost todo section (H4).
- [ ] Owner's decision on the subscription and callback path (C4, D4, E4,
      G4); see the assessment.
- [ ] E4-K4 as the decision allows.
- [ ] Phases 3-4 (PR 2).

## Issues Found

### A4. A database fault at startup leaves every worker on the legacy grant for property checks
**Severity:** High (reopens Issue A)
**Description:**
- `actingweb/permission_initialization.py:42-43` re-raises a `DbError`
  from `initialize_registry`. That skips step 2,
  `initialize_trust_permission_store`.
- `interface/app.py:1584` folds the startup fault with
  `# folds DbError: startup init, loads lazily later`. That is false for the
  store: `trust_permissions.py:797-800`
  `if _permission_store is None: raise RuntimeError("Trust permission store not initialized...")`.
- Every later evaluator build raises that `RuntimeError`. It is not a
  `DbError`, so `handlers/properties.py:161-174` takes the
  "fall back to legacy authorization" branch for the life of the process.
- At `8e8b4df` the registry folded every error, so step 2 always ran. Entry
  16 introduced this.

**Recommendation:**
- Run steps 2 and 3 before re-raising step 1's fault, or make
  `get_trust_permission_store` build the store lazily.
- Make the handlers deny, not fall back, on any exception from
  `get_permission_evaluator`.
- Add a test that faults the registry at startup and asserts a DENY
  override still denies.

### B4. `strict=False` through `Trusts`, `Subscriptions` and `Properties` never folds
**Severity:** High (since Phase 1)
**Description:**
- `actingweb/subscription.py:57`, `trust.py:47` and `property.py`
  (`Properties.__init__`) each call `self.fetch()` with the strict default in
  the constructor. A fault raises `DbError` before the caller's
  `.fetch(strict=False)` runs.
- Every display fold Phase 1 added on these wrappers is therefore
  ineffective:
  - `Actor.get_subscriptions(strict=False)`, which serves `register_diffs`
    and the resync;
  - the trust deletion's subscription list (`actor.py:1678`);
  - the two `actor_adopted` summaries (`oauth2.py:2134-2137`, `:2250`).
- **Scenario:** `PUT /<id>/properties/<name>` commits, then `register_diffs`
  reads the subscriptions. A throttle answers 503 for a write that landed, and
  the client's retry duplicates a list append.

**Recommendation:**
- Do not fetch in the constructors; fetch lazily on `.fetch(strict=...)`.
  The callers already call `.fetch()`.
- Add a test that faults the list read through each wrapper.

### C4. The "publisher redelivers" premise behind A3 and D3 is false
**Severity:** High
**Description:**
- `callback_processor.py:434-437` says the 503 "lets the publisher
  redeliver". The publisher does not retry: `actor.py` `_send_callback_sync`
  logs the status and moves on.
- A diff comes back only through `sync_subscription` polling or a gap-timeout
  resync (`subscription_manager.py:1070-1090`).
- When it does, `remote_storage.py:352-366` re-applies it key by key, and a
  list operation (`:402`, `list_attr.append(...)`) is not idempotent. A
  handler that faulted after some side effects is re-applied twice.
- The consumer hooks fold at `handlers/callbacks.py:655, 686`. The legacy
  hooks re-raise (`:700` through `hooks.py:685`), so one callback has two
  error rules.

**Recommendation:** decide the delivery guarantee explicitly (see the
assessment). Under either choice, record `last_seq` for the callbacks that
completed before a fault, and state the guarantee in the hook docs.

### D4. Three diff skip points leave no gap, so a change is lost undetectably
**Severity:** High
**Description:**
- `subscription.py:200`
  `except DbError as e:  # folds DbError: nothing written; diff skipped`
  (the `increase_seq` fault).
- `actor.py:3148` "strict=False: a fault skips diff registration ... (the
  peers' next callback detects the gap)".
- `actor.py:3326` `# folds DbError: one subscriber skipped`.
- In all three no sequence moved, so the next diff is contiguous and the
  subscriber cannot tell a diff is missing. Entry 23's "leaves a gap" holds
  only for the `diff.create` fault.

**Recommendation:** on a skip, advance the sequence on purpose (a detectable
gap) or flag the subscription for resync; correct the three comments.

### E4. A quiet subscription stalls after a D3 fold; the resync handlers keep the D3 shape
**Severity:** Medium
**Description:**
- After `recorded = True` (`callback_processor.py:460`) the gap timeout is
  checked only when a later gap callback arrives (`:346`), so a quiet
  subscription waits indefinitely.
- `_handle_resync_sync` (`:843`) and `_handle_resync` (`:523`) call
  `_update_last_seq` unwrapped after the handler ran.

**Recommendation:** retry the sequence write once before folding, and apply
the same fold in both resync handlers.

### F4. Three marker reasons are false
**Severity:** Medium
**Description:**
- `subscription.py:115` "cleanup after delete committed": `handle.delete()`
  runs later (`:122`), so a recreated subscription inherits stale pending
  entries.
- `handlers/callbacks.py:655, 686` "the sequence state already advanced": the
  handler runs before `_update_last_seq`.

**Recommendation:** correct the order or the reasons. The guard cannot check
truth, so the next verification should keep sampling reasons.

### G4. PostgreSQL diff creates still collide on a racing increment
**Severity:** Medium
**Description:**
- `increase_seq` writes `previous + 1` from a cached read
  (`subscription.py:132-135`).
- Two concurrent writers both write N+1; on PostgreSQL the second
  `diff.create` collides (`db/postgresql/subscription_diff.py:163-176`, no
  `UniqueViolation` mapping) and is logged as "ambiguous", so its change is
  lost without a gap. On DynamoDB it overwrites the first diff.

**Recommendation:** a conditional increment (`seqnr = expected`) on both
backends; map `UniqueViolation` to a definite "taken".

### H4. The guarded-sweep todo section was deleted by entry 28's trim
**Severity:** Medium (record-keeping)
**Description:**
- Entry 21 says its items are in
  `thoughts/todo/adoption-fault-and-hygiene-followups.md` under
  "Fault-contract follow-ups from the guarded sweep". The section does not
  exist.
- Entry 28's trim removed the text from the plaintext-key bullet to the
  benchmarks bullet, and the section sat between them.
- Untracked now:
  - the `_set_state` read-compare-write;
  - the `decrease_seq` window;
  - the ordering windows (O2);
  - the three post-commit folds that lose a side effect;
  - UNKNOWN tombstones proceeding;
  - the suspected `AwProxy` `KeyError`.

**Recommendation:** restore the section, minus the five items entry 28
fixed.

### I4. Fault answers still miss CORS on routes mapped inside the handler
**Severity:** Medium
**Description:** `flask_integration.py:773-775` (the factory handler) maps a
`DbError` with `map_db_error` and returns without `error_cors_headers`; the
factory's JSON normally carries `Access-Control-Allow-Origin`
(`factory.py:136`). The FastAPI twin is the same.
**Recommendation:** apply `error_cors_headers` wherever `map_db_error`
answers, and cover `/`.

### J4. Two post-commit or non-critical paths re-raise
**Severity:** Medium
**Description:**
- `interface/trust_manager.py:187`: `_execute_lifecycle_hook` re-raises for
  `trust_approved`, which fires after the approval committed and the peer was
  told. The client gets a 503, retries, and the hook may run twice.
- `handlers/mcp.py:2396`, `:2824`: `_mark_client_peer_approved` and
  `_update_trust_with_client_info`, both documented "non-critical", now
  re-raise. The MCP authentication path turns that into
  `TokenStoreUnavailable`, failing a request that was otherwise
  authenticated.

**Recommendation:** fold both with their reasons, as the post-commit rule
says.

### K4. Smaller items
**Severity:** Low
- `oauth2.py:2206`, `:2317`, `:1672`: three more `oauth_provider`
  bookkeeping writes fail a sign-in (I3 covered one).
- `subscription_manager.py:824`: public `is_suspended()` answers False on a
  fault.
- `mcp.py:2971-2973`: a 409 is labelled "Service Unavailable".
- `actor.py:542`: the create rollback removes only the row; an ambiguous
  marker write can leave `_internal` attributes under the id.
- `fanout.py:317`: "the in-memory breaker still applies" holds within one
  process only.
- `actor.py:378`: with no vouched actor the ranked prefix is every actor
  (accepted as O), and the pick is read twice.
- `oauth2.py:1805`: a replacement reads the victim's lists three times.
- `handlers/root.py:102`: the HTTP DELETE writes its tombstone and fires
  `actor_deleted` before `Actor.delete`'s pre-reads (AW, known). The
  CHANGELOG's B8 sentence should say it holds for `Actor.delete`, not the
  route.
- Type hints are still missing on the DynamoDB signatures this work changed.

## Overall Assessment

Entries 22-29 fixed what they targeted on the paths they named, the guard
holds at 0, and the security review is clean. PR 1 is still not ready, for
two High findings outside the subscription path:
- **A4:** a startup fault quietly reopens Issue A's legacy-grant fallback.
- **B4:** the `strict=False` display folds on the list wrappers have never
  folded, because the constructors read strictly first.

Both are mechanical to fix and to test.

The other High findings (C4, D4) and most of the Medium ones (E4, F4, G4)
sit in one subsystem: subscription diffs and callback delivery. Each round
there has found the next layer: the fold, then the redelivery premise, then
the gap that is not a gap, then the racing increment. This subsystem has no
stated delivery guarantee, and the fault contract keeps forcing one
implicitly. Two options for the owner:
- **Keep going in PR 1:** define the guarantee (at-least-once with
  idempotent application, or at-most-once with a forced resync on any
  fault), then make the sequence handling conditional and the skips
  detectable. That is design work, not a sweep.
- **Narrow PR 1:** on the subscription-diff and callback path, restore the
  pre-3.16 folding behaviour at the entry points (`register_diffs`,
  `add_diff`, `CallbackProcessor`), keeping strict reads everywhere else.
  File the delivery guarantee as its own plan for 3.16 or 3.17. PR 1 then
  ships the contract where its semantics are settled.

My recommendation is the second. Fix A4, B4, H4, I4 and J4 in the next
iteration, then verify a fifth time.
