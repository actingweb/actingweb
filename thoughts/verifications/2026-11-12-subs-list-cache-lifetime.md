# Verification: per-request actors on the MCP path, and a subscription list that caches empty

**Date:** 2026-11-12
**Plan:** thoughts/plans/2026-11-06-subs-list-cache-lifetime.md
**Research:** thoughts/research/2026-11-05-subs-list-cache-lifetime.md (cost follow-up: thoughts/research/2026-11-06-actor-load-cost-and-email-as-creator.md)
**Branch:** release/3.16.0-subs-list-cache-lifetime
**Commit:** `8f091c5` (range `7929161..8f091c5`: the redraft, Phases 1-3, two phase-review commits)

No feature document; no previous verification.

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees (the MCP
  handler, the actor layer, docs).
- **Second opinion:** outside voice on the whole range, Codex (`codex exec -s
  read-only`, outside the sandbox) and a fresh-context reviewer; the built-in
  code review at high effort; the built-in security review (the diff touches
  MCP authentication). Each phase had its own outside-voice review before
  this; those findings and fixes are in the plan's phase notes and are not
  repeated here. Findings are under Issues Found.
  - Security review: **no findings** (it checked the cached-token path, the
    per-application binding, the trust TTL, the fill/eviction lock, the
    `rewrite_email=False` load, the accessor through a view, the suspension
    clear on create, and the missing-table answer).
  - Code review (high): ten findings; two kept as issues (1, 2), the rest
    folded into Lows or the accepted notes below.
  - Outside voice: four Codex findings, four fresh-context findings; split
    verdicts differ (below).
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (560 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: pass (43 groups
  documented; wire rows registry consistent; the `Wire-Phase` trailers match
  the owners of every changed recording).
- `make test-all-parallel` (DynamoDB): **6681 passed**, 53 skipped, 1
  xfailed, from the parallel run; no failure to re-run.
- `make test-all-parallel` (PostgreSQL): **6477 passed**, 257 skipped, 1
  xfailed, from the parallel run; no failure to re-run.
- `sphinx-build -W --keep-going ...`: pass.
- Wire step on Python 3.11 (`.venv311`, `pytest tests/ -m wire -p
  no:rerunfailures`, sequential), run during Phase 2 on the same library
  code as `011865b`: 320 passed on DynamoDB, 320 on PostgreSQL. Not re-run
  on `8f091c5` (the review commit after it changed `actor.py`'s create and
  delete resets and the DynamoDB `delete_all`; the Full tier above covers
  them on 3.14).
- Gate 3 (the new rows): five sequential runs per backend of `WC6`, `WC7`,
  `WM1`-`WM4`, byte-identical (Phase 2).
- Benchmarks: not run; no phase touched list storage or the attribute layer.

## Phase Verification

### Phase 1: the MCP path builds its actor per request - VERIFIED

**Changes verified:**
- `actingweb/handlers/mcp.py:171` `_load_actor`: `Actor(config=config)` then
  `.get(actor_id=..., rewrite_email=False)`, `actor_module.Actor` read at call
  time. Matches.
- `_actor_cache`, its counters and its comment block are gone (`grep -rnw
  "_actor_cache" actingweb tests` returns nothing).
- `authenticate_and_get_actor_cached`: snapshot before the token-cache read;
  a cached entry is a hit only when `cached_data.get("config") is
  self.config` (`:2337`); the cached branch loads with `create=False`
  (`:2527`), drops the entry and re-snapshots when the row is missing; the
  token fill follows a successful load. Matches the diagram.
- `_trust_cache_get(trust_key, config)` misses another application's entry
  and leaves it (`:203`); `_trust_entry_expired` is shared by the lookup and
  the sweep; `_TRUST_CACHE_TTL: float = _cache_ttl`.
- Fills and evictions under `_cache_generation_lock`, an `RLock` (`:342`):
  added by the Phase 1 review, not in the plan; recorded there.
- `_update_trust_with_client_info` and `_mark_client_peer_approved` use
  `actor.core_actor`; `_race_winner` and the bridge reloads use
  `_load_actor`; a reload with no row answers `None` (`:2581`).
- Prose: `trust.py`, `mcp/invalidation.py`, `runtime_context.py`,
  `oauth2_server/token_manager.py` (two comments, review fix). Matches.

**Tests verified:** `tests/test_mcp_per_request_actor.py` (25), every case
the plan lists, plus three from the review. Against `master`'s handler 19 of
the first 22 fail (plan, Phase 1 notes); the lock test fails with the lock
removed from the cached-branch fill (run during the review).

**Security properties, demonstrated by the tests that pin them:**
- *A cached token never creates an actor*:
  `TestCachedTokenWithoutARow.test_no_tombstone_still_never_creates` asserts
  `create.assert_not_called()` and `Actor(actor_id, cfg).id is None` with no
  row and no tombstone; `test_a_deleted_actor_answers_none_and_drops_the_entry`
  asserts `None`, one storage validation, the entry gone and no row.
- *Entries are bound to the application*:
  `TestOneApplicationPerEntry.test_another_applications_entries_are_misses`
  asserts the other application validated (`server.calls == 1`) and both
  entries still carry the first `Config`;
  `TestPhase1ReviewFixes.test_another_applications_trust_entry_is_a_miss`
  asserts the lookup ran and the entry now carries the second `Config`.
- *A revocation is not undone by a fill in flight*:
  `TestTrustEntries.test_a_revocation_during_the_lookup_leaves_the_trust_unfilled`
  asserts the trust key is absent;
  `TestPhase1ReviewFixes.test_an_eviction_cannot_land_between_a_fills_check_and_write`
  asserts the eviction thread finished after the fill and the key is absent.
- *A positive trust entry expires*:
  `TestTrustEntries.test_a_positive_entry_past_its_ttl_is_resolved_again`
  asserts the resolver ran once and the context carries the new peer id.

**Failure scenarios:** each has its test as listed in the plan (the 503 on
both handlers: `TestFaults.test_an_actor_read_fault_on_a_cached_token_answers_503`;
the resolver bug: `test_a_resolver_bug_on_a_cached_token_answers_none`; the
second snapshot: `test_a_token_that_still_validates_bridges_once_and_is_cached`).

**Deviations from plan:** `_set_mcp_runtime_context` helper; the adoption
test's counter not lifted; the lock (review). All acceptable and recorded.

### Phase 2: the subscription list memo, its sibling, the clean-up, the accessor - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py:3703` `if self.subs_list is None:`, the memo assigned
  only on a real read. Matches.
- `delete_reciprocal_trust` takes keyword-only `_subscriptions` (`:3146`),
  reads per relationship with `strict=False`, resets in a `finally` around
  the block. Matches.
- Resets: `resume_subscriptions`, the three trust methods (method-wide
  `finally`; the outside voice compared the syntax trees: the bodies are
  unchanged), both dead-subscription clean-ups, and (review)
  `create_subscription` and `delete_subscription`. Matches.
- `Actor.delete()` passes `_subscriptions=[]`, wipes subscriptions again,
  then diffs and suspensions (`_wipe_subscription_leftovers`,
  `_wipe_diffs_and_suspensions`, `:1650`); `purge_relationships()` the same
  with `confirmed` False on a fault. Matches.
- `Actor.create(actor_id=...)` clears suspensions inside `if created and
  actor_id:` (`:1238`), **after** the tombstone clear (`:1230`): see Issue 2.
- `get_subscriptions_by_peer()`, `PeerSubscriptions`, the view delegation
  through `_own_rows`, the exports, the handler's hand reset removed, the
  protocol docstring and `delete_all` on the protocol. Matches.
- DynamoDB `delete_all` answers `True` for a missing table (review); see
  Issue 1 for the constructor that runs before it.

**Tests verified:** `tests/test_subscription_list_memo.py` (55). 25 fail on
the old `actor.py`; the six resume and trust-call tests fail with the resets
removed (plan, Phase 2 notes). The accessor through a client view uses a
real client trust row (review fix). Wire rows `WM2`-`WM4` and the
re-recorded `WC6`/`WC7` show what `rows.toml` says (read by the outside
voice and by me: `WM2` B keeps `x = 1` until the second instance writes;
`WM3` B2 gets `y` and `A.suspensions` is `[]`; `WM4` the resume sends the
resync).

**Security property:** *the accessor exposes no other peer's rows through a
view*: `TestByPeer.test_a_view_sees_its_own_keys` asserts a peer view's keys
`== {a}` and a client view's `== {trust_peer, client_id}` against five
peers' rows.

**Deviations from plan:** `delete_all` on the protocol; two `Actor`
helpers; `WM3`'s subscriber set up unrecorded. Acceptable and recorded.

### Phase 3: documentation, changelog and records - ISSUES FOUND

**Changes verified:** the changelog entries (three `CHANGED`, one `ADDED`,
seven `FIXED`, the `Breaking` entry extended for `_subscriptions`), the
migration guide item 23 and its section, the five guide and reference pages,
`docs/contributing/architecture.rst`, the `thoughts/` records. The plan's
greps return nothing (`_actor_cache|invalidate_actor_cache|actor_hits`,
`actor hits|actor loading|cached actor|actor cache`, `rewrite_email`).
Wording that says more than the code: Issues 4 to 7.

**Todos against the plan:** `subs-list-cache-asymmetry.md` deleted with its
`INDEX.md` row; `verify-orphans-subscription-tables.md` exists (its Origin
gains this document, done with this verification);
`mcp-cache-lifecycle-and-revocation.md` updated (constraint, sections 1, 2,
6); `dynamodb-known-next.md` points at the plan; no index row names a
missing file.

**Consumer message:** the plan has none; the consumer-facing text is the
changelog and the migration section, checked above. Emm's suite has not run
on this branch (Remaining Tasks).

## Remaining Tasks

- [ ] Emm's suite on this branch before the PR (Phase 3's last box), run as
      `thoughts/todo/emm-suite-against-master.md` describes. The outside voice
      notes `../actingweb_mcp/api/trust_unified.py:845` and
      `tests/test_trust_relationships_subscription_reads.py` describe the old
      falsy guard; the run shows whether anything depends on it.
- [ ] Issues 1 and 2 before the PR (Medium, under the owner's stop rule).
- [ ] The Lows: fix or accept (owner).
- [ ] The wire step on Python 3.11 again after the iteration.

## Issues Found

### 1. The suspension store's constructor can raise a non-`DbError` inside `create`'s rollback scope (and inside `delete`)
**Severity:** Medium (DynamoDB with auto-creation on, the suspensions table
absent and no `CreateTable` permission). Reachable by a new user's first MCP
sign-in (the bridge creates by explicit id) and by an owner's delete.
**Description:** `get_subscription_suspension(...)` builds the DynamoDB store,
whose constructor runs `ensure_table(SubscriptionSuspension)`
(`db/dynamodb/subscription_suspension.py:54`); `ensure_table` re-raises any
`create_table` error but `ResourceInUseException`
(`db/dynamodb/_ensure.py:104` `if "ResourceInUseException" not in str(e):
raise`). In `create` the call sits inside a `try` whose only handler is
`except DbError:` (`actor.py:1238`, handler below it), so the new row is not
rolled back and the instance stays bound; in `delete` it escapes as a
non-503 error. With the permission present, the first create or delete per
process runs a blocking `CreateTable(wait=True)` inside a request. Before
this branch an actor with no subscribers never built this store. The Phase 2
review's missing-table test patches `query` only, so the constructor path is
untested.
**Location:** `actingweb/actor.py:1238`, `actingweb/actor.py:1658`,
`actingweb/db/dynamodb/subscription_suspension.py:54`
**Recommendation:** turn any exception from building the store or from
`delete_all` into `DbError` (so `create` rolls back and `delete` answers
503), and decide whether `delete_all` should build the store without
`ensure_table` (a missing table holds nothing to delete). Test with
`ensure_table` raising.

### 2. A failed explicit-id create loses the deleted actor's tombstone
**Severity:** Medium (code review); Codex and the fresh-context reviewer rate
the reach Low. The MCP bridge refuses a deleted id before it creates
(`handlers/mcp.py`, the `DeletionStatus.DELETED` check), so the trigger is a
direct `Actor.create(actor_id=...)` whose suspension clear fails; after it,
a cached MCP token on another worker finds no tombstone and the bridge can
create the deleted id again.
**Description:** `deletion.clear_actor_tombstone(self.id, self.config,
strict=True)` (`actor.py:1230`) runs before the suspension clear
(`:1238`); when the clear answers `False`, the rollback removes the row but
cannot restore the tombstone. Before this branch the tombstone clear was the
last step that could fail. `tests/test_subscription_list_memo.py`
`test_a_clear_that_fails_fails_the_create` asserts only that no row exists.
**Location:** `actingweb/actor.py:1230-1243`
**Recommendation:** clear the suspensions first, then the tombstone (both
still after the row is written, so a create under a live actor's id touches
neither); assert in the test that the tombstone is still there after a
failed clear.

### 3. `actingweb-deletions` finishing a deletion whose row is gone skips the new wipes
**Severity:** Low (overlaps the accepted deletion race; Codex rated it
Medium).
**Description:** the `UNFINISHED` path removes only the client index rows
(`actingweb/maintenance/deletions.py:187` "The row is gone; what can remain
is the client index rows the tombstone recorded"). A subscription or diff a
peer inserted after the final wipe, or a suspension a faulted wipe left,
stays, and the tombstone is marked finished.
**Location:** `actingweb/maintenance/deletions.py:185-195`
**Recommendation:** run the actor-wide subscription, diff and suspension
deletes (deletes by actor id) on that path too, and correct the comment.

### 4. The changelog says a cached token with no row "never creates the actor"
**Severity:** Low. **Location:** `CHANGELOG.rst:2240`
**Description:** after the drop the request takes the full path, where the
bridge can create once the token validates against storage
(`test_a_token_that_still_validates_bridges_once_and_is_cached` pins it).
**Recommendation:** "is dropped and validated against storage; only a token
that validates can lead to a create".

### 5. "Every instance the library builds lives for one request" is not exact
**Severity:** Low. **Location:** `CHANGELOG.rst:946-947`
**Description:** the system actor of `trust_type_registry.py:94` is kept
(the plan's What We're NOT Doing names it).
**Recommendation:** add "except the system actor, which has no subscribers".

### 6. "After a trust call that sent a request to the peer" is narrower than the code
**Severity:** Low. **Location:** `CHANGELOG.rst:944`, the migration section
**Description:** the reset is a method-wide `finally`: every call of the three
methods resets, including MCP client-info writes that send nothing. Only an
extra read.
**Recommendation:** "after these trust calls".

### 7. `docs/guides/caching.rst` still shows the removed pattern in a code sample
**Severity:** Low. **Location:** `docs/guides/caching.rst:77`, `:102`
**Description:** "Cached version of authentication with ~1ms response time"
caches the whole authentication result (`'data': result`), actor included:
the pattern 3.16 removes. The Phase 3 greps cannot catch it.
**Recommendation:** rewrite the "Implementation Pattern" sample to cache the
validation result only, or drop it.

### 8. The actor-wide diff wipe reads every diff body, after a redundant per-subscription pass
**Severity:** Low (cost on delete and purge, not correctness).
**Location:** `actingweb/actor.py:1656` `diffs.fetch(actor_id=self.id)`;
`_wipe_subscription_leftovers` (`Subscriptions(...).delete()` sweeps diffs
per subscription first)
**Description:** both backends' `delete()` find the rows again by actor id;
on DynamoDB the per-subscription pass is a query per subscription over all
of the actor's diffs.
**Recommendation:** delete by actor id without the fetch (set the actor id,
or a backend `delete_all(actor_id)`), and delete only the subscription rows
before it.

### 9. The new wire tests have no type hints
**Severity:** Low. **Location:**
`tests/integration/test_wire_queue_and_lifecycle.py:182`, `:202`, `:233`
**Description:** `CLAUDE.md`, Checks: "Type hints are required on all
functions"; the file's older tests have none either.
**Recommendation:** annotate the three (`wire_pair: Any, topology: str ->
None`).

### 10. A PostgreSQL schema without the suspensions migration now fails deletes and explicit-id creates
**Severity:** Low. **Location:**
`actingweb/db/postgresql/subscription_suspension.py:148-163`
**Description:** `delete_all` answers `False` on `UndefinedTable`; DynamoDB
treats a missing table as empty since the review fix. PostgreSQL requires its
migrations at head (the table is `b2c3d4e5f6a7_add_subscription_suspensions`).
**Recommendation:** accept, or mirror the DynamoDB answer for
`UndefinedTable`.

### Accepted by the plan, raised again by the code review (no change proposed)
- The memo is kept fresh by resets at each site that changes it, and a
  subscription created elsewhere during an instance's life is not seen (the
  per-instance rule, `WM1`/`WM2`; Decisions).
- The warm MCP request's actor read blocks the FastAPI event loop
  (Decisions; What We're NOT Doing, "Moving MCP authentication off the event
  loop").
- `_subscriptions` on the overridable `delete_reciprocal_trust` breaks a
  fixed-signature override (Decisions; migration guide).
- Trust deletion reads the list per relationship (What We're NOT Doing,
  "Reusing one list across relationships").

### Unverified notes (outside voice)
- What the orphan row Issue 1 leaves leads to at a later sign-in (no
  `auth_method` marker).
- `purge_relationships()` clears a live actor's suspensions: an adoption
  purge during the owner's own suspended operation could leave its
  `resume_subscriptions` finding no suspension; not checked whether the
  resync is then skipped.

### Split
Codex suggests separate releases for Phase 1 and Phase 2; the fresh-context
reviewer says no split, because Phase 2 is safe only with Phase 1 (the
Overview: "With no instance outliving a request, `Actor.get_subscriptions()`
can memoise an empty list"). I agree with no split: one PR, as planned.

## Overall Assessment

The plan is implemented as written, with deviations that the phase reviews
added and the plan records: the MCP path builds its actor per request, the
two caches are bound to the application and guarded against a racing
revocation, and an actor reads its subscription list once with resets at
every site that changes or invites what it holds. The claimed security
properties are each pinned by a test named above, the security review found
nothing, and the Full tier is green on both backends (DynamoDB 6681,
PostgreSQL 6477).

Not ready for the PR yet. Under the owner's stop rule two Medium issues
remain, both in the new storage calls on `Actor.create(actor_id=...)` and
`Actor.delete()`: a non-`DbError` from the DynamoDB suspension store's table
check that skips the create's rollback (reachable by a first MCP sign-in on
a deployment without that table), and the tombstone cleared before the
suspension clear that can fail. Both have small fixes. The Lows are three
changelog sentences, a stale code sample, the cost of the diff wipe, type
hints, the `actingweb-deletions` resume path, and PostgreSQL's missing-table
answer. Emm's suite still has to run before the PR.
