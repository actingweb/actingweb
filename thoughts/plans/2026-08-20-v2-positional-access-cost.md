---
status: active
---

# Implementation Plan: v2 list read cost — the 3.14.0 release

**Date:** 2026-08-20
**Research:**
[`thoughts/research/2026-08-20-v2-positional-access-cost.md`](../research/2026-08-20-v2-positional-access-cost.md)
(the design pass, options A–G),
[`thoughts/research/2026-08-20-v2-cost-in-library-callers.md`](../research/2026-08-20-v2-cost-in-library-callers.md)
(the verification and ownership pass), plus the consumer feedback pass
appended 2026-08-20 to actingweb_mcp's
`thoughts/research/2026-08-20-v2-list-read-cost.md` (items N-1, N-3, F-1 —
each addressed below)
**Branch:** written on `research/v2-positional-access-cost`; implement on a
fresh branch off `master`
**Todo rows closed:** 14, 15, 16, 17, 5, 9c, 9 (INDEX.md §1 and §3), plus
row 9b's CAS residual and the property-list half of `dynamodb-known-next.md`
items 1 and 3

## Update Log

- **2026-08-20 (round 1)**: Consumer feedback pass (actingweb_mcp F-1, N-1,
  N-3) and staff review folded in: Phase 9B added (append's whole-list read
  becomes a last-rank point read), `update_where` diffs moved onto the
  existing `update` operation with `old_item`, the count-hint drift bound
  stated as contract, handle mutators made single-shot, CAS exhaustion typed
  and mapped to 503, the sync-callback fan-out documented, and the
  single-release decision recorded.
- **2026-08-20 (round 2)**: Consumer round-2 feedback: `list_all_with_rows()`
  made public (F-2), `_get_full_state_for_subscription()` added to Phase 3
  (F-6), the drift bound's third term added (a failed advisory touch persists
  in append-only workloads), and the advisory-touch carve-out added to
  Phase 9 so a 503 can never follow a committed v2 item write. Docs coverage
  swept: per-phase docs targets named (`subscriptions.rst`,
  `actingweb-spec.rst`, `authenticated-views.rst`,
  `database-maintenance.rst`, `common-pitfalls.rst`) and a release docs
  checklist added to Phase 14.
- **2026-08-20 (decisions review)**: `list_all_with_rows()`'s rows declared
  an opaque token (the row-name encoding is what the next major's
  `prop#`/`list#` scheme changes); the unconditionally-strong-reads list
  corrected to include `get_last_in_range` (Decisions, Phases 6 and 8); the
  handle-API decision restated as one protocol bump of three methods.

## Overview

The v2 (fractional rank key) list format traded v1's corruption class for a
cost class: every positional access re-derives a fragile handle (a position)
from a stable one (the rank) the storage already has, and re-derivation is a
whole-list range Query. A consumer took a user-visible outage from it on
2026-08-19 — a 10-item delete ran 40.7 s and burned ~1.19M RCU.

This release closes the class rather than shaving it. It exposes the rank as an
opaque handle with conditional mutation, fixes the library's own callers (which
commit the same defect the consumer was told to fix, including through the
*documented* bulk endpoint), stops plain-property reads paying for the actor's
list rows, and corrects the documentation that made the cost invisible three
times running.

Originally scoped as a 3.13.1 patch. Promoted to **3.14.0** because the fix
that actually helps consumers is new public API and new backend protocol
surface, and a patch number cannot honestly carry either.

A consumer feedback pass on this draft (actingweb_mcp, 2026-08-20) and a
staff review against the lambda-like deployment posture then reshaped three
things: appends stop paying the whole-list read (new Phase 9B, feedback F-1),
value-addressed update diffs stay inside the existing peer vocabulary so
≤3.13 peers never silently diverge (Phase 10, feedback N-3), and the
advisory count's drift bound becomes a stated contract a quota check can be
built on (Phase 5, feedback N-1). Dispositions are collected at the end of
the Evaluation Notes.

## Decisions Made

- **Release is 3.14.0, not 3.13.1** — the useful half is new API. A patch
  release could only have carried Phases 1–4, which fix the library's own
  callers and tell the truth in the docs but leave every consumer still
  deleting by position. A staff review proposed carrying Phases 1–4 as an
  immediate 3.13.1 anyway (they include the Phase 2 permission fix); the
  maintainer's decision on 2026-08-20 is that **all fourteen phases ship
  together as 3.14.0** — recorded here so the split is not re-proposed.
- **The full handle API ships, including `update_by_handle`** — so
  `DbPropertyProtocol` changes in **one release** rather than two. (The
  release's full protocol surface is three methods — Phase 8's
  `set_if_value_equals` and `get_last_in_range`, Phase 12's `batch_delete` —
  so a backend implementor tracks a single protocol bump.) The delete half composes
  on both backends today; the update half needs a new conditional-set
  primitive (`db/protocols.py` declares a conditional *create* and a
  conditional *delete* and no conditional set).
- **Handles are v2-only; the value-addressed helpers are universal.**
  `find()`/`find_all()`/`remove_where()`/`update_where()` work on both formats
  (under v1 they do the positional thing internally — no worse than today's v1
  code path). `items_with_handles()`/`delete_by_handle()`/`update_by_handle()`
  raise on a v1 list, naming `migrate_to_v2()`. Universal high-level API,
  honest low-level guarantee: a v1 list has no rank, so a v1 "handle" could
  only be a position wearing a name that promises stability.
- **`remove_where` returns a count and takes `first_only=False`** — consistent
  with `verify(identity_key=...)`, whose existing position is that duplicate
  identities are *detected and reported*, not prevented
  (`property_list.py:1754`).
- **`identity_key` is the parameter name**, reused from `verify()` rather than
  inventing a second word for the same idea.
- **Row 5 takes the two-query range patch**, not the `prop#`/`list#` key
  scheme. The 2026-08-20 re-measurement shows either takes a plain-property
  read from 254 RCU to ~13; the prefix scheme is a storage-format change and a
  second migration one release after v2's. The prefix scheme is refiled for the
  next major, where row 12's legacy-GSI removal is already waiting.
- **`consistent_read` becomes a per-call parameter on the public read methods,
  and no default changes.** Eventual consistency halves read capacity
  (measured 241 → 120.5 RCU), and the application is the only party that can
  say whether a given read may be stale — the risky case is cross-request and
  cross-container ("save, then list in the next request"), which no
  library-internal state can detect. So `to_list()`, `slice()`,
  `to_indexed_list()`, `find()` and `find_all()` take `consistent: bool = True`
  and the caller opts in at the site where it knows what the read is for.
  `_v2_ensure_rank_cache()`, `items_with_handles()` and Phase 8's
  `get_last_in_range` (which feeds `_v2_append` in Phase 9B) are strong
  unconditionally and take no parameter — the library's own conditional
  writes depend on those bytes, and a stale last rank is a mid-list append.
- **No application-level consistency switch and no environment variable.** An
  earlier draft had `with_list_reads()` plus `ACTINGWEB_LIST_STRONG_READS` as
  an escape hatch from a flipped default; with the default unchanged there is
  nothing to escape. It would also have been a DynamoDB-only knob on a
  backend-agnostic API (PostgreSQL ignores it), and a third instance of the
  env-var/builder-method/default three-sources-of-truth pattern that INDEX
  row 12 already files against `use_lookup_table` for cleanup.
- **No instance-level "has written" guard.** It was proposed to make a flipped
  default safe, and it does not work: `property.py:54` mints a fresh
  `ListProperty` per attribute access, so the flag is false on nearly every
  read in a new request. With an explicit per-call parameter it is also
  unnecessary — a caller passing `consistent=False` after writing asked for
  exactly that, and the docstring says so.
- **The library takes the saving nowhere by default.** Not even in its own
  handlers: a REST client that does PUT then GET expects to see its write, so
  an eventually-consistent read in `handlers/properties.py` makes that
  intermittently false. The parameter exists for applications, not for us.
- **The advisory count is a hint, never an address.** v1's stored `length` was
  a corruption source because `range(length)` *addressed* rows from it. The v2
  hint is read by `get_metadata()` and the diff registrar and by nothing that
  resolves a row. `len()` keeps counting ranks.
- **Row 17 ships with the permission-gap fix**, same class, same file.
- **Rows 9c and 9b's CAS residual ship here, because Phase 8 builds the
  primitive they were blocked on.** `whole-list-rewrite-atomicity.md` records
  that no compare-and-swap exists on `DbProperty`, which is why
  `_save_metadata()`'s read-modify-write window was accepted as a known trade
  on PR #127. Phase 8 adds that CAS for `update_by_handle`; closing the window
  then costs a retry loop, not a design. Row 9c's separate deferral reason —
  *"not attempted at the tag point because it changes the hot write path"* — is
  exactly what a feature release exists for.
- **No new PynamoDB `Model` subclasses, on either backend.** `_ensure.py`
  memoizes table existence *per model class*, so each new class is one more
  `DescribeTable` on every container cold start — the per-accessor cost that
  was measured at >1,000 calls/minute in a near-idle deployment and removed in
  3.13. Phase 8's `set_if_value_equals` and Phase 12's `batch_delete` are
  methods on the existing `DbProperty`, operating on the existing
  `Property`/`PropertyLegacy` classes. If an implementation seems to need a new
  model, that is a design signal to stop, not a detail to wave through.
- **The `AWS_DB_AUTO_CREATE_TABLES=false` path stays at exactly zero
  control-plane calls.** It is the posture `db/verify_tables.py` documents as
  recommended for production, and roles in that posture have had
  `DescribeTable` dropped entirely — a regression there is an outage, not a
  slowdown. Phase 1 pins it.
- **The orphan scan ships in `actingweb/maintenance/`, not `db/verify_tables.py`.**
  The 2026-08-14 decision named `verify_tables`, which on reading is
  DynamoDB-only, does table-existence checks rather than row scans, and has no
  rate limiting or checkpointing. `verify_property_lists.py` is the shape a
  full-table sweep needs. The decision's substance — ship it rather than let
  every consumer rewrite it — is unchanged.
- **The orphan scan reports and never deletes.** Classification is the hard,
  dangerous part; `docs/reference/actor-deletion.rst:252-256` explicitly wants
  human review before deletion, and a `--delete` flag invites the cron job that
  same documentation forbids.
- **`clear()`/`delete()` get batched deletes; `remove_where` does not.**
  `BatchWriteItem` cannot express conditions, so it fits an unconditional
  whole-list teardown and not a value-addressed delete. Phase 12 and Phase 10
  therefore use different primitives on purpose.
- **Handle mutations are single-shot conditional writes; only the
  value-addressed helpers retry.** A handle pins the exact stored bytes, so
  there is nothing to re-resolve — a failed condition *is* the answer,
  returned as `False`. The resolve-and-retry loop belongs to
  `remove_where`/`update_where`, which can legitimately re-resolve by value.
  (Staff review: the earlier draft's "reuse `_v2_pop`'s retry shape" wording
  invited a retry loop inside `*_by_handle` that would convert "the row
  changed" into "overwrote the new value" — the bug class the API exists to
  kill.)
- **`update_where` diffs ride the existing `update` operation, extended with
  an `old_item` field.** Consumer feedback N-3: peer replication is live
  production with third-party peers on ≤3.13, so a new operation name — which
  `remote_storage.py` answers with "unknown operation" and a silent skip —
  is a silent-divergence machine. The existing `update` op with the snapshot
  index keeps old peers at today's positional fidelity while 3.14 peers match
  on `old_item`. Details in Phase 10.
- **Append's fix is a last-rank point read (Phase 9B), not a stored
  `last_rank` hint.** Consumer feedback F-1 asked for the append fix and
  flagged the hint hazard themselves; the hint is rejected outright — Phase
  9B records why no fence can make it safe in a mixed-version fleet.
- **Metadata CAS exhaustion is a typed, retryable failure** —
  `ListMetadataContentionError`, mapped to 503 + `Retry-After` by the
  handlers. In lambda-like fleets the contending writers are other
  containers, so no in-process lock can dampen the race: the jittered
  backoff and the bound are the whole mechanism, and the failure must be
  distinguishable from a server fault. Specified in Phase 9.
  [Updated 2026-08-20 round 2] One carve-out: the **advisory** v2 metadata
  touch (`updated_at` + `count_hint`, written after the item row is already
  committed) tolerates exhaustion with a WARNING instead of raising — a 503
  whose entire meaning is "retry" must never follow a committed write the
  retry would duplicate.
- **The advisory count ships with a stated drift bound.** Consumer feedback
  N-1: a consumer enforces a free-tier quota on `get_metadata()["length"]`
  and cannot adopt the saving until the bound is a documented contract rather
  than an implementation observation. Phase 5 states it, and the guide gets
  the boundary-confirm enforcement recipe.
- **`list_all_with_rows()` is public API, not a private helper.** [Updated
  2026-08-20 round 2] Consumer feedback F-2: `list_all()` pays for the full
  partition dump and discards it for *every* caller, and the priming half of
  the pattern (`prime_from_rows()`/`to_list_from_rows()`) is already public
  on `NotifyingListProperty` — withholding the rows would fix the library's
  two callers and leave every consumer with the same bug, reachable only by
  going around `ActorInterface`. The authenticated view does not delegate it
  in 3.14: a cross-list bulk read through the permission view needs per-list
  read filtering, which is its own design. **The rows value is an opaque
  token**: feed it to `prime_from_rows()`/`to_list_from_rows()`, never
  inspect or parse it — the row-name encoding it exposes is exactly what the
  `prop#`/`list#` scheme filed for the next major will change, and a consumer
  who parses it in 3.14 breaks silently there.

## What We're NOT Doing

- **The `prop#`/`list#` key-prefix scheme.** Refiled as a todo for the next
  major version. The measurement says this is where the remaining money is —
  each list would get a bounded range as a first-class key instead of
  re-deriving one from a `BETWEEN` on every call — but it is a storage-format
  change and v2's migration is three weeks old.
- **Making `__getitem__` one query instead of two** (keys-only rank scan +
  point `get` → a single `_v2_load_full()`). Since `keys_only` saves no
  capacity on DynamoDB, this trades a round trip for the whole list's bytes on
  every `lst[i]` — 964 KB per positional read on the consumer's largest list.
  It does not touch the actual defect (O(n) capacity per positional access);
  Phases 8–11 remove the reason to call it at all.
- **Exposing handles over the wire.** Handles are a Python-API concept in
  3.14.0. Making the REST `{"items": [...]}` contract handle-addressed instead
  of index-addressed is a protocol change; Phase 11 uses handles *inside* the
  handler while keeping the index-based contract.
- **Caching `ListProperty` instances per store.** Evaluated and rejected in the
  research (option E): unsafe where it helps, useless where it is safe, because
  `handlers/mcp.py:52` renews a 5-minute actor cache on every access, so a
  cached rank cache could be minutes old in a later request.
- **`ListAttribute`'s v2 port** (row 4). Two reasons, and the second is the
  stronger one. It inherits row 9b's still-open commit-protocol gap, which is
  the sequencing decision taken 2026-08-14. And `remote_storage.py` applies
  peer diffs *into* `AttributeListStore` — Phase 10 already changes the diff
  vocabulary, so porting the receiver's storage format in the same release
  means changing sender and receiver simultaneously. Phase 10 designs the
  handle API so the port can adopt it rather than reinvent it, which is the
  thing that makes doing it next cheap.
- **Crash-atomic `compact()`** — row 9b's main subject. Two designs died under
  adversarial review (a lease-plus-journal whose replay destroys data a plain
  re-run preserves, and a stage-and-flip that silently permutes lists on the
  documented `--repair` → `--migrate` sequence), and the todo says not to
  propose a third without reading them. No viable design is a real reason to
  wait. Phase 9 does close its **residual** — the read-modify-write window on
  the metadata row — because Phase 8 happens to build the CAS that residual was
  missing, and it leaves the next attempt with one fewer prerequisite.
- **`subs_list` cache asymmetry** (row 7). Its one-line guard fix is unsafe
  until the cross-request `Actor` cache question is settled, and that question
  belongs to the MCP cache-lifetime work, not here.
- **The trust and attribute serial delete loops** — the rest of
  `dynamodb-known-next.md` item 1. Different subsystems with no property-list
  dependency; Phase 12 takes only the property-list half.
- **The rest of the `consistent_read` audit** (item 3, 27 sites). Phase 6
  closes `get_range`, the hottest of them by a wide margin. The remaining sites
  are trust lists, attribute buckets and subscriptions.
- **Coalescing bulk-mutation diffs into a `clear` + `extend` snapshot pair.**
  It would cut the sync-callback fan-out (k removed items = k callbacks per
  subscriber) to two callbacks, but a full-state snapshot clobbers concurrent
  appends on the peer replica that per-item `remove` diffs preserve. The
  fan-out is documented with its arithmetic instead — see Phase 10.

---

## Phase 1: Tell the truth, and pin the cold-start `DescribeTable` budget

Two recurrence guards, no production code, shipped first so both are in place
before anything else lands.

The docs half: three separate incidents were caused by comments asserting
cheapness that v2 made false, so the corrected text should be what anyone reads
while the rest of the release is built.

The budget half: this release adds two backend methods and a maintenance
module, and `_ensure.py`'s guarantee — *"at most one check per model class per
process"*, zero when auto-creation is disabled — is keyed on the **model
class**. A new PynamoDB `Model` subclass would therefore cost one extra
`DescribeTable` on every container cold start, and nothing in the suite would
notice: `tests/test_ensure_table.py` exercises the guard with fake models and
never counts calls across the real model set. That is the gap this closes,
before the phases that could widen it.

### Changes

- `docs/guides/property-lists.rst:109-118` — *"two queries per item under v2"*
  reads as a constant factor of 2. The first of those two is a **whole-list**
  Query, so a positional loop is O(n) per item, not O(1). Rewrite to say so,
  with the 2026-08-19 numbers as the concrete case.
- `docs/guides/property-lists.rst:19` — the Basics example's `count = len(notes)`
  sits unannotated directly under the warning. Annotate it; fixing the prose
  while leaving the example is how the misconception survived.
- `docs/guides/property-lists.rst:99-100` — `append()` is presented as the
  primitive with no note that under v2 every append is a whole-list range read
  (`_v2_append` → `_v2_ensure_rank_cache`, always cold because
  `property.py:54` mints a fresh `ListProperty` per attribute access).
- `actingweb/property_list.py:288-289` and `:1105` — *"one keys-only range
  query"* implies a saving that does not exist on DynamoDB.
- `actingweb/db/protocols.py:216` — `keys_only` described as *"a cheaper
  projection read"*. True on PostgreSQL (`db/postgresql/property.py:492-501`
  issues `SELECT name`); false on DynamoDB, where
  `db/dynamodb/property.py:504-514` is a base-table Query with
  `attributes_to_get`. Rewrite as "cheaper on PostgreSQL, no capacity saving on
  DynamoDB", citing the AWS contract: *"requesting a subset of attributes …
  has no impact on the item size calculations."*
- `actingweb/property_list.py:694-726` — `get_metadata()`'s note claims the
  count is *"cheap after the first call, via the cached rank-key range"*, true
  only within an instance the store discards.
- `actingweb/property_list.py:588-630` — `prime_from_rows()`'s docstring
  repeats the same O(1)-sounding "two queries per item" framing.

### New Tests

`tests/test_cold_start_budget.py`, new. It changes no production code and must
pass unmodified at the end of every later phase — a phase that needs it
*edited* has regressed the budget, which is the whole signal.

- Integration: a cold process that boots the app and exercises the property,
  property-list, trust, attribute and subscription paths issues **at most one
  `DescribeTable` per model class in `required_models()`**, asserted against
  that function so adding a model to the library forces a deliberate update
  here rather than a silent one.
- Integration: with `AWS_DB_AUTO_CREATE_TABLES=false` — the posture
  `db/verify_tables.py` calls recommended for production — the same run issues
  **exactly zero** `DescribeTable` and zero `CreateTable`. This is the assertion
  that matters most; the guard already skips `exists()` deliberately so a
  locked-down IAM role never pays or leaks an `AccessDenied` per construction.
- Unit: repeated `get_property(config)` construction — which
  `property_list.py` does on *every* list operation, deliberately, to avoid
  handle conflicts — adds no `DescribeTable` beyond the first.
- Docs build clean (`make -C docs html` or the project's equivalent) with no
  new warnings.

### Verification

- [ ] `poetry run pytest tests/test_cold_start_budget.py tests/test_ensure_table.py -v` passes
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] `poetry run pyright actingweb tests` passes
- [x] Manual: re-read `docs/guides/property-lists.rst` end to end and confirm
      no remaining sentence implies a positional read or a `len()` is cheap

### Implementation Status: Complete

**Notes:** `tests/test_cold_start_budget.py` counts `exists()`/`create_table()`
calls by wrapping each model in `required_models()` with a `mock.patch.object(...,
wraps=...)` spy around `Connection`-level pynamodb model methods, rather than a
botocore `before-call` hook — simpler and sufficient, since `_ensure.py`'s guard
calls `model.exists()`/`model.create_table()` directly. `AWS_DB_AUTO_CREATE_TABLES=false`
asserts zero calls to either. The docs build (`poetry run make html` from repo
root — `docs/Makefile` does not exist; the Sphinx targets live in the root
`Makefile` with `SOURCEDIR = .` resolving against root `conf.py`) is clean with
no warnings. Full suite: 2875 passed (+3 from baseline), 26 skipped, 0 failed.

---

## Phase 2: `AuthenticatedPropertyListStore` — the `TypeError` and the read-check write gap

Row 17, plus something the evaluation pass surfaced in the same class that is
more serious than the bug it was filed for.

### Changes

- `actingweb/interface/authenticated_views.py:252-259` — `create()` and
  `delete()` both resolve through `PropertyListStore.__getattr__` to a
  `NotifyingListProperty` named `"create"` / `"delete"` and then call it:
  `TypeError: 'NotifyingListProperty' object is not callable`, **after** the
  permission check passes. Broken since 2025-12-14 (`30216d1`), no callers, no
  tests, no docs, and exported from `actingweb.interface`. Fix `delete(name)`
  to `getattr(self._store, name).delete()`; **remove** `create()` — lists are
  created lazily on first write, so it has no meaning, and removing an exported
  method that has never worked breaks nobody.
- `actingweb/interface/authenticated_views.py:236-242` — **the gap.**
  `__getattr__` checks only `read` permission and then returns the raw,
  fully-mutable `NotifyingListProperty`. A peer holding read-only permission on
  a list can `append`, `__setitem__` and `__delitem__` through it. Compare
  `AuthenticatedPropertyStore:113-127`, which checks `read`/`write`/`delete`
  per operation — the asymmetry is not intentional, and the separate `write`
  and `delete` checks on `create`/`delete` show the design meant to have
  per-operation checks that `__getattr__` undercuts.
  Fix: return a permission-enforcing proxy that re-checks `write` before each
  mutator and `delete` before `__delitem__`/`clear()`/`delete()`, delegating
  reads after the `read` check already made.
- Docs: cover `AuthenticatedPropertyListStore` where the SDK documents the
  authenticated views (`docs/sdk/authenticated-views.rst` today has no
  section for it): per-operation checks — `read` to read, `write` to mutate,
  `delete` to remove — and that `create()` is gone. Verify no documented
  example calls `create()`.
- This phase must land **before** Phases 10–11: every new mutator added there
  would otherwise be reachable behind a read check the moment it is written.

### New Tests

- Unit: `AuthenticatedPropertyListStore.delete(name)` deletes the named list
  and returns `True`; the removed `create()` is gone from
  `actingweb.interface`'s exports.
- Unit: a read-only auth context can `to_list()` a list and **raises
  `PermissionError`** on `append`, `__setitem__`, `__delitem__`, `clear()` and
  `delete()`.
- Unit: a write-permitted context succeeds on all of the above.
- Regression: the proxy delegates every read method the wrapper exposes, so
  adding a method to `ListProperty` cannot silently make it unreachable —
  assert the proxy's surface against `NotifyingListProperty`'s public methods.

### Verification

- [x] `poetry run pytest tests/test_property_list_notifications.py -v` passes
- [x] `poetry run pytest tests/ -k authenticated -v` passes
- [x] `poetry run pyright actingweb tests` passes
- [x] `poetry run ruff check actingweb tests` passes

### Implementation Status: Complete

**Notes:** The permission-enforcing proxy is `_PermissionEnforcingListView`
(`authenticated_views.py`), constructed by `AuthenticatedPropertyListStore.__getattr__`
after its `read` check. Per the plan's literal wording ("re-checks `write`
before each mutator and `delete` before `__delitem__`/`clear()`/`delete()`"),
`pop()` and `remove()` are gated on `write`, not `delete`, even though they
remove items -- only the three named methods get the `delete` check. New
tests live in `tests/test_authenticated_views.py` (a new
`TestAuthenticatedPropertyListStore` class), not
`test_property_list_notifications.py`, since the existing authenticated-views
test file already has the permission-mocking pattern to reuse and the `-k
authenticated` filter picks it up either way. Running `-k authenticated`
against the full `tests/` tree (rather than scoped to a file) also surfaced
2 unrelated failures in `tests/integration/test_actor_root_redirect.py`
(`-k` substring-matched "unauthenticated"); these fail the same way with or
without this phase's changes when run outside `make test-all-parallel`'s
harness setup (a `MissingSchema: Invalid URL 'None'` from a base-URL fixture
that isn't populated when the file runs standalone) and are absent from the
full-suite run below, so they're a pre-existing test-isolation artifact, not
a regression. Full suite: 2881 passed (+6), 26 skipped, 0 failed.

---

## Phase 3: The library's own callers stop paying the cost

Row 16. The library's handlers commit the exact defect the consumer was told to
fix, including through the *documented* bulk endpoint — so a consumer reaches
the 2026-08-19 shape by following the docs. No new API; every fix shape already
exists in the codebase.

### Changes

**The zero-query fix.** `PropertyListStore.list_all()`
(`actingweb/property.py:31-51`) already calls `fetch_all_including_lists()` —
the full partition dump, item rows included — and discards it.
`handlers/properties.py:463-563` is the pattern that doesn't: derive list names
from `all_rows`, `prime_from_rows()`, then `len()` costs nothing. Add
**public** `PropertyListStore.list_all_with_rows() -> tuple[list[str], dict[str, str]]`
so callers can reuse the dump they already paid for — public, not the
private helper the first draft had, on consumer feedback F-2 (round 2):
`list_all()` pays for the dump and discards it for *every* caller, the
priming half (`prime_from_rows()`/`to_list_from_rows()`) is already
delegated on `NotifyingListProperty` (`interface/property_store.py:311,314`),
and the rows are the only missing piece — without them a consumer's sole
route is `get_property_list(config).fetch_all_including_lists()`, reaching
past `ActorInterface`. Their measured cost of not having it: 672 RCU of
per-list re-reads per `GET /api/outputs` on top of the 254 RCU dump
`list_all()` already paid. Surface it through the store
`actor.property_lists` returns. The docstring states the contract: the rows
are a point-in-time snapshot of the **whole partition** (plain rows
included), stale the moment a mutation lands, and **opaque** — made to be
fed to `prime_from_rows()`/`to_list_from_rows()` and never inspected or
parsed, because the row-name encoding is a storage detail the next major's
`prop#`/`list#` scheme will change (see Decisions). `AuthenticatedPropertyListStore`
does **not** delegate it (see Decisions).

- `actingweb/handlers/www.py:181-184` — one whole-list Query per list property
  to render `f"[List with {n} items]"`, plus one `exists()` GetItem per
  property (`exists()` is a `get()` on `list:{name}-meta`, which the dump
  already contains). Both go to **zero** via the primed rows.
- `actingweb/handlers/trust.py:1175-1180` — same shape on the peer-sharing
  view, once per property name after `list_all()` already enumerated them.
- `actingweb/actor.py:2556-2580` — `_get_full_state_for_subscription()`'s
  all-properties branch (consumer feedback F-6, round 2): `get_properties()`
  (whole partition), then `property_lists.list_all()` (a second
  whole-partition dump), then `list(list_attr)` per list — ~254 + ~254 +
  ~1,150 RCU on the consumer's measured actor. It is the fallback for peers
  that do not support resync (`actor.py:2452-2469`), so lower-frequency than
  the web UI — but unlike `www.py` it sits on a path headless consumers
  actually reach. Same fix verbatim: one `list_all_with_rows()` dump serves
  the scalars, the list names and the primed per-list reads.

**The eagerly-evaluated logging.**

- `actingweb/handlers/www.py:889-891` — Python evaluates an f-string *before*
  calling `logger.debug`, so both `len(list_prop)` calls run in production with
  DEBUG off. Adding one item through the built-in UI costs three whole-list
  reads for one point write. Convert to lazy `%s` logging with a
  `logger.isEnabledFor(logging.DEBUG)` guard, or drop the counts entirely.

**Bounds checks that double a single-item edit.** Do *not* prime these — a
primed snapshot makes the check read stale state, and the positional writes
force their own reload regardless. Delete the check and map the `IndexError`
the write already raises (`property_list.py:846-861`, `:908-923`) onto the
existing 400.

- `actingweb/handlers/www.py:925`, `:956`
- `actingweb/handlers/properties.py:1790`, `:1825`
- `actingweb/handlers/properties.py:636` — PUT-by-index reads `len()` then
  writes positionally, which forces its own reload. The spec branch
  (`index == length` MAY append, `index > length` MUST 404) needs the length,
  so this one keeps a read — but take it from a single `to_indexed_list()` and
  reuse it, rather than `len()` then a forced reload.

**Sites neither research document enumerated.**

- `actingweb/handlers/properties.py:1756` and `:1764` — `len(list_prop) - 1`
  called **twice** after an append, in the documented REST `/items` POST.
  Three whole-list Queries per single-item add, in the API rather than the web
  UI. Compute the index once from the append path.
- `actingweb/interface/property_store.py:356` — `append()` calls
  `len(self._list_prop)` for the diff's index, on top of the `len()`
  `_register_diff` itself makes at `:257`: **two** whole-list Queries per
  notified append. Remove the duplicate here by computing the index once.
  The `:257` call itself cannot be removed in this phase — the count lives in
  `ListProperty` and the wrapper has no cheap way to learn the post-mutation
  length, which is exactly why `:356` calls `len()` in the first place. It is
  Phase 5's, and is listed there.

**The bulk endpoint.** `handlers/properties.py`, the `{"items": [...]}` path
whose docstring at `:798-801` presents it as *the* batch API:

- `:1019` `projected_length = len(list_prop)`
- `:1122` `while len(list_prop) <= index` — evaluates at least once per update
  even when no append happens
- `:1144` and `:1149` `if index < len(list_prop)` / the warning's `len()`

Take one `to_indexed_list()` at the top and track the projected length in
memory (the batch's own semantics already define what the length is at each
step — `:1002-1011` documents them). **≈`2k + 2` → `k + 2`.** The residual `k`
is the forced reload inside `_v2_setitem`/`_v2_delitem`, which only Phase 11
can remove; that is a cheap second edit to the same loop, not a rewrite of this
phase's work.

**Deliberately untouched, so nobody "fixes" them later:**

- `handlers/www.py:1032` — `_ = len(list_prop)` is load-bearing (it triggers
  metadata creation) and runs on a list that is empty by definition, so the
  range Query reads zero items. Add a comment saying so.
- `handlers/properties.py:1163` — the final `to_list()` feeding the post hook
  stays a real read. Deriving `current_items` from an in-memory projection
  changes what a transform-capable hook sees.
- `handlers/properties.py:264`, `:1486` — single-list `count` responses with no
  partition dump in hand. One query each, inherent until Phase 5.

### New Tests

The instrument already exists and needs extending, not building:
`CountingPropertyDb` (`tests/test_property_list_integrity.py:443`) at unit
level, and `mock.patch.object(DbProperty, "get_range", side_effect=AssertionError(...))`
(`tests/test_hot_path_n_plus_one.py:130-140`) at integration level.

- Integration: rendering the www properties overview for an actor with 3 list
  properties issues **zero** `get_range` and **zero** per-list `get` calls
  beyond the single `fetch_all_including_lists()`.
- Integration: the trust peer-sharing view, same assertion.
- Integration: the full-state subscription fallback for an actor with 3 list
  properties issues exactly **one** partition Query and zero per-list
  `get_range` calls, and the payload matches what the per-list reads
  produced before.
- Unit: public `list_all_with_rows()` returns the names and the raw rows;
  priming each list from those rows and then calling
  `len()`/`to_list_from_rows()` issues zero further queries — the
  consumer-shape test, asserted as exact counts.
- Integration: a `{"items": [...]}` batch of *k*=5 updates and 5 deletes issues
  **`k + 2`** `get_range` calls, asserted as an exact number so a regression
  fails rather than degrades.
- Unit: `www.py`'s append path issues no `len()`-driven query at
  `logging.WARNING`.
- Unit: a notified `append` issues one fewer `get_range` than before (the
  duplicate index count is gone). The remaining `_register_diff` read is
  asserted away in Phase 5, not here.
- Regression: out-of-range index on every de-bounds-checked site still returns
  400 with the same message, sourced from the write's `IndexError`.
- Regression: the REST `/items` POST still reports the correct `index` in both
  the diff blob and the 201 body.

### Verification

- [ ] `poetry run pytest tests/test_hot_path_n_plus_one.py -v` passes
- [ ] `poetry run pytest tests/test_property_list.py tests/test_property_list_integrity.py tests/test_property_list_notifications.py -v` passes
- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] `poetry run ruff check actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 4: Plain-property reads stop paying for the actor's list rows

Row 5 (I0). Measured against production on 2026-08-20: an actor's whole
partition is 1,190 rows / **254 RCU**, of which one list's 81 rows are **241
RCU**. A read that returns 5 plain properties pays for all of it.

### Changes

- `actingweb/db/dynamodb/property.py:609-623` — `fetch()` issues
  `Property.query(actor_id)` with no range condition and filters `list:` rows
  client-side. Replace with a **pair** of range-constrained Queries, because
  DynamoDB cannot `OR` on a sort key.
  **The sentinel must be `list;` (0x3B, the byte after `:`), not the `list:~`
  the todo sketches.** `~` is 0x7E, so any list whose *name* begins with a byte
  above `~` — every non-ASCII list name — sorts after `list:~` and would leak
  back into the plain-property result. `name < "list:"` and `name >= "list;"`
  is exact: `"list"` falls in the first, `"listen"` in the second, and every
  `list:*` row in neither.
- `actingweb/db/postgresql/property.py:630-668` — same filter, but **do not**
  use ordering comparisons: PostgreSQL text ordering is collation-dependent and
  a non-C collation does not agree with byte order on punctuation. Use
  `WHERE id = %s AND name NOT LIKE 'list:%%'`, which is collation-proof.
- **Preserve the empty-partition contract.** Today `Property.query()` returns a
  truthy iterator regardless, so `fetch()` returns `{}` — not `None` — for an
  actor whose partition holds only `list:` rows. Two queries must not silently
  turn that into `None`.
- `fetch_all_including_lists()` is unchanged on both backends: it legitimately
  wants the whole partition, and Phase 3 depends on it doing exactly that.
- Check the trust / peer-trustee fetch paths for the same client-side-filter
  shape while in the file.

### New Tests

- Integration (DynamoDB): an actor with 5 plain properties and 200 list item
  rows — `fetch()` returns exactly the 5, and a `Property.query` spy shows the
  list rows were never returned by the API (not merely filtered afterwards).
- Integration (DynamoDB): a list whose **name is non-ASCII** is excluded. This
  is the test that fails under the `list:~` sentinel and passes under `list;`.
- Integration (DynamoDB): a plain property named `list` and one named `listen`
  are both returned.
- Integration (PostgreSQL): the same four cases against the `NOT LIKE` filter,
  including under a non-C database collation.
- Regression: an actor whose partition holds only `list:` rows still gets `{}`
  from `fetch()`, not `None`.
- Regression: `fetch_all_including_lists()` still returns the list rows.

### Verification

- [ ] `poetry run pytest tests/ -k "property" -v` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `make test-all-parallel` passes
- [ ] Manual: the operation-counter recipe in
      `docs/migration/v3.13.rst` ("Proving the fixes actually landed") shows a
      plain-property read on a list-heavy actor dropping from ~254 RCU to ~13
- [ ] `poetry run pyright actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 5: An advisory count, so a count stops costing a whole list

v2 deliberately has no authoritative length — v1's stored `length` is what the
index-integrity work removed. The distinction that makes this safe is that v1's
corruption came from *addressing* rows out of the stored length
(`range(length)`), not from reporting it.

### Changes

- `actingweb/property_list.py:326-341` — add `count_hint` to
  `_create_default_metadata_v2()`. The name is deliberately not `length`: it
  must be impossible to mistake for the v1 field.
- `actingweb/property_list.py:814-843` — `_v2_touch_metadata()` currently calls
  `_save_metadata({})`, which re-reads the stored row and moves only
  `updated_at` (that re-read is load-bearing — it is what stops a cached
  `format` being carried back over a completed migration). Extend it to also
  write `count_hint`: mutations that hold a fresh rank cache write the counted
  truth; `append()`/`extend()` — which after Phase 9B no longer build one —
  merge `count_hint` as the stored value plus their delta, under the same
  fresh read.
- `actingweb/property_list.py:694-726` — `get_metadata()` serves `length` from
  `count_hint` under v2 instead of calling `len(self)`. **This changes a public
  contract**: `get_metadata()["length"]` becomes advisory rather than exact.
  Documented in the docstring, the guide, and the changelog under CHANGED.
- `actingweb/interface/property_store.py:257` — `_register_diff()` takes its
  `length` from the hint. This is the volume site: a whole-list Query per
  notified mutation, doubled on append.
- `actingweb/handlers/properties.py:264`, `:1486` — single-list `count`
  responses served from the hint.
- `actingweb/property_list.py:1689-1753` — `_v2_verify()` reports
  `count_hint_drift` (hint vs counted ranks) as a finding.
- `actingweb/property_list.py:1898-2000` — `_v2_compact()` rewrites the hint
  to the counted truth.
- `actingweb/interface/property_store.py` — `NotifyingListProperty` does not
  currently delegate `get_metadata()` at all (see Phase 8's note). Add it.
- `docs/guides/property-lists.rst` — the drift bound below, stated as
  contract, plus the enforcement recipe consumer feedback N-1 is waiting to
  cite: a quota check trusts the hint while it is strictly below the limit
  and confirms with `len()` once it reaches the limit — the exact read is
  paid at the quota boundary instead of on every save.

**Drift is bounded and self-correcting, not cumulative — and the bound is a
documented contract, not an implementation observation** (consumer feedback
N-1: a free-tier quota is enforced on this number, so "advisory" alone is not
adoptable). Two concurrent appends both read `count_hint = 5` and both write
`6` where the truth is `7`; the next mutation that pays a full rank read sees
`7` and writes `8`. The stated bound: at any moment,
`|count_hint − len()|` is at most the number of mutations in flight against
the list, plus — during a rolling deploy only — the mutations applied by
pre-3.14 writers since the last rank-counting 3.14 mutation
(`_save_metadata()` preserves fields it does not recognise, so a 3.13 writer
carries the hint forward without maintaining it), **plus one per mutation
whose advisory metadata touch failed** (Phase 9's tolerated CAS exhaustion,
or a backend fault after the item write) since the last rank-counting
mutation. The third term is the consumer's round-2 catch: after Phase 9B,
`append()`/`extend()` merge stored-plus-delta and never re-count, so in an
append-only workload — the consumer's `memory_save`/`output_create` shape —
a lost touch persists until a rank-counting mutation
(`insert`/`pop`/`remove`/`__delitem__`) or `compact()`. The boundary-confirm
recipe is robust to it, because `len()` at the limit is exact; the guide
states all three terms and says so. A quiesced list whose touches all landed
is exact. Drift does not accumulate beyond those terms, and it does not
depend on rows 9b/9c's missing CAS being fixed first. `len()` continues to
count ranks and remains exact.

### New Tests

- Unit: `count_hint` tracks `append`/`insert`/`__delitem__`/`pop`/`remove`
  across a mixed sequence, matching `len()` in the single-writer case.
- Unit: `__setitem__` leaves the hint unchanged (it changes no count).
- Unit: a deliberately corrupted hint is reported by `verify()` as
  `count_hint_drift` and repaired by `compact()`.
- Unit: a deliberately corrupted hint is **never** used to resolve a row —
  `to_list()`, `__getitem__` and iteration all still return the true items.
  This is the test that keeps the v1 `length` disaster from returning.
- Unit: with a stale hint written by a simulated concurrent writer, the next
  mutation restores it to the counted truth.
- Unit: a mutation by a simulated pre-3.14 writer (one that preserves
  `count_hint` without maintaining it, as `_save_metadata()`'s merge does)
  leaves drift that the next rank-counting 3.14 mutation repairs — the
  rolling-deploy clause of the documented bound.
- Unit: an append whose advisory touch fails leaves the hint low by one,
  `verify()` reports it as `count_hint_drift`, and the next rank-counting
  mutation repairs it — the third term of the documented bound.
- Unit: `get_metadata()` on a v2 list issues **zero** `get_range` calls.
- Unit: `_register_diff` for a notified append issues zero `get_range` calls.
- Regression: a v2 list whose metadata predates this release (no `count_hint`)
  is handled — `get_metadata()` falls back to counting, the first
  rank-counting mutation writes the hint, and a Phase 9B append on such a
  list leaves the hint absent rather than guessing (it has no rank read to
  count from).
- Regression: v1 lists are untouched; `get_metadata()["length"]` still comes
  from the v1 `length` field.

### Verification

- [ ] `poetry run pytest tests/test_property_list.py tests/test_property_list_integrity.py -v` passes
- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] `poetry run ruff check actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 6: `consistent_read` becomes a per-call parameter

`db/dynamodb/property.py:512` hardcodes `consistent_read=True` with no caller
opt-out. A strongly consistent read of an item up to 4 KB costs one read unit;
an eventually consistent one costs half. Measured on the consumer's 81-row
list: 241 RCU → 120.5 RCU.

The saving is real, but whether a given read may be stale is an application
question, not a library one — so this phase adds the choice and changes no
default. It is the smallest phase here by design; see the Evaluation Notes for
the two larger versions that were cut.

### Changes

- `actingweb/db/protocols.py` — add `consistent_read: bool = True` to
  `DbPropertyProtocol.get_range`, documenting that the default preserves
  today's behaviour and that `False` is only correct where the caller cannot
  have written the rows it is about to read.
- `actingweb/db/dynamodb/property.py:483-519` — pass it through to
  `Property.query`.
- `actingweb/db/postgresql/property.py:492-501` — accept and ignore it with a
  comment (PostgreSQL reads are consistent by construction; the parameter is
  part of the protocol, not a DynamoDB detail leaking upward).
- `actingweb/property_list.py:306-322` — `_v2_load_full()` gains a
  `consistent: bool = True` parameter, passed to `get_range`.
- `actingweb/property_list.py` — `to_list()`, `slice()`, `to_indexed_list()`
  and Phase 7's `find()`/`find_all()` each take `consistent: bool = True` and
  forward it. **No default changes**, so no consumer's semantics change on
  upgrade. The docstrings state what `False` buys (half the read capacity) and
  what it costs (a write that has landed may briefly not be visible), and say
  plainly that the library will not second-guess the choice — passing `False`
  on an instance that just wrote returns what was asked for.
- `__iter__` keeps no parameter — there is nowhere to put one on the iterator
  protocol, and `to_list(consistent=False)` is the spelling for a cheap full
  read.
- `actingweb/property_list.py:288-304` — `_v2_ensure_rank_cache()` stays
  strongly consistent unconditionally and takes no parameter. A stale rank
  feeding a positional write touches the wrong row.
- Phase 7's `items_with_handles()` is the second such place, for the same
  reason — see its entry there. Phase 8's `get_last_in_range` is the third,
  for Phase 9B's append: a stale last rank lands the append mid-list.
- **Nothing in `actingweb/handlers/` passes `False`.** A REST client that does
  PUT then GET expects to see its write, and the built-in handlers are not the
  right place to spend that guarantee on someone else's behalf.
- `docs/guides/property-lists.rst` — a short section on when the parameter is
  worth using, with the measured numbers (241 → 120.5 RCU on an 81-row list) so
  the trade is concrete rather than abstract.

### New Tests

- Unit: `to_list()`, `slice()`, `to_indexed_list()`, `find()` and `find_all()`
  each issue `get_range(consistent_read=True)` by default.
- Unit: each of them issues `get_range(consistent_read=False)` when passed
  `consistent=False`.
- Unit: `items_with_handles()` issues `get_range(consistent_read=True)` and
  accepts no override — the guard Phase 10's conditional writes depend on.
- Unit: `_v2_ensure_rank_cache` is always `consistent_read=True`.
- Regression: no call site under `actingweb/handlers/` passes
  `consistent=False` — asserted by a grep-style test, so a later edit cannot
  quietly spend the guarantee.
- Integration (PostgreSQL): the parameter is accepted, ignored, and results are
  unchanged either way.

### Verification

- [ ] `poetry run pytest tests/test_property_list.py -v` passes
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 7: Value-addressed reads

The read half. `find`/`find_all` are ergonomics rather than cost — a
value-addressed read is already one query via `to_list()` plus an in-memory
scan — but that scan is what every consumer writes by hand, and writing it by
hand is where the index escapes into a later write.

### Changes

- `actingweb/property_list.py` — `find(identity_key, value)` returning the
  first matching item or `None`, and `find_all(identity_key, value)` returning
  every match. One `_v2_load_full()` (or one v1 `to_list()`), matched in
  memory. Universal across formats. `identity_key` reuses `verify()`'s
  parameter name (`property_list.py:1754`).
- `actingweb/property_list.py` — `items_with_handles() -> list[tuple[ListItemHandle, Any]]`
  from one range read. **v2 only**; raises on v1 naming `migrate_to_v2()`.
  **Always strongly consistent**, regardless of Phase 6's default and of the
  application-level switch. A handle carries the raw stored bytes and Phase 10
  conditions its writes on exactly those bytes, so handles read from a stale
  replica fail their condition against rows nobody has touched — Phase 11's
  batch would then report every item as concurrently modified and apply
  nothing. Same rationale `_v2_ensure_rank_cache()` already carries, and it
  must be a comment in the code, not only here.
- `actingweb/property_list.py` — `ListItemHandle`, a frozen dataclass carrying
  the rank **and the exact raw stored string** the read returned. Both are
  required: `db/protocols.py:277-280` states that a conditional write's `value`
  must be the RAW STORED STRING the caller read, not a re-serialization. Its
  `__repr__` must not invite serialization, and it is explicitly not
  wire-stable — a rank is unique only within a **list generation**
  (`property_list.py:2343-2352`: after `delete()` + `append()`,
  `generate_n_keys_between(None, None, n)` is deterministic, so a new list's
  first rank is also `a0`).
- `actingweb/interface/property_store.py` — delegate all three on
  `NotifyingListProperty` (read-only, no diff).
- `actingweb/interface/authenticated_views.py` — the Phase 2 proxy delegates
  them as reads.
- `docs/guides/property-lists.rst` — a section on identity vs position, with
  the handle's generation caveat stated rather than implied.

### New Tests

- Unit: `find`/`find_all` on v2 and on v1 return the same results for the same
  data.
- Unit: `find_all` with duplicate identities returns every match, matching
  `verify()`'s `duplicate_identities` view of the same condition.
- Unit: `find` on a missing key returns `None`; on an item that is not a dict,
  it does not raise.
- Unit: `items_with_handles()` issues exactly one `get_range`.
- Unit: `items_with_handles()` on a v1 list raises with a message naming
  `migrate_to_v2()`.
- Unit: a handle's raw value round-trips byte-identically to what
  `delete_if_value_equals` will require — assert against the stored string, not
  a re-encoding.
- Unit: reachable through `actor.property_lists.<name>` (the allowlist
  regression from Phase 2).

### Verification

- [ ] `poetry run pytest tests/test_property_list.py tests/test_property_list_notifications.py -v` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] `poetry run ruff check actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 8: The conditional-set and last-rank backend primitives

`DbPropertyProtocol` declares a conditional create (`:229`) and a conditional
delete (`:256`) and **no conditional set**. `update_by_handle` needs
compare-and-swap, so this is new backend surface — hence its own phase, ahead
of the API that uses it. Phase 9B needs one more small primitive — the
greatest row in a range — so both protocol additions land here together.

### Changes

- `actingweb/db/protocols.py` — `set_if_value_equals(actor_id, name, expected, value) -> bool`,
  documented against the existing `delete_if_value_equals` contract: `expected`
  must be the RAW STORED STRING; `False` means "held a different value or is
  gone" and both mean *re-resolve and retry*, not failure; `DbError` only on a
  backend fault. Note that a conditional write whose expression evaluates false
  **still consumes write capacity** on DynamoDB, so a retry loop must not be
  written as though losing attempts are free.
- `actingweb/db/dynamodb/property.py` — `UpdateItem` with a
  `ConditionExpression` on the current value; `ConditionalCheckFailedException`
  → `False`, everything else → `DbError`.
- `actingweb/db/postgresql/property.py` — a single atomic
  `UPDATE properties SET value = %s WHERE id = %s AND name = %s AND value = %s`
  with `rowcount == 1`, mirroring the conditional delete at `:552-585`.
- `actingweb/db/protocols.py` — `get_last_in_range(actor_id, lower, upper) -> str | None`,
  returning the NAME of the bytewise-greatest row in `[lower, upper]`, or
  `None`. Unlike `get_range`, whose contract deliberately guarantees no
  ordering, byte-order maximality IS this method's contract on both backends.
  DynamoDB: `Property.query(..., scan_index_forward=False, limit=1)` —
  consumes one item's read capacity, not the range's. PostgreSQL:
  `ORDER BY name COLLATE "C" DESC LIMIT 1` — the collation pin is
  load-bearing, because rank keys mix upper- and lower-case and locale
  collations disagree with byte order on exactly that (`max("Z", "a")` is
  `"a"` bytewise and `"Z"` under en_US), and a wrong maximum here becomes a
  mid-list append in Phase 9B. Same caution family as Phase 4's `NOT LIKE`.
  Always strongly consistent on DynamoDB, with no caller override — it feeds
  Phase 9B's append, and a stale maximum is the same mid-list append by
  another route.
- No lookup-table maintenance: `list:`-prefixed names are structurally excluded
  from indexing by `_should_index_property()` on both backends.

### New Tests

- Unit + integration on **both** backends: succeeds when the stored value
  matches; returns `False` when it differs; returns `False` when the row is
  absent; is atomic against a concurrent writer.
- Unit: a `DbError` is raised for a genuine backend fault and **not** for a
  condition failure — the distinction the whole retry design rests on.
- Unit: the two backends agree on all four outcomes (the parity test
  `delete_if_value_equals` already has).
- Unit + integration on both backends: `get_last_in_range` returns the
  bytewise-greatest name; `None` on an empty range; and the two backends
  agree on a range whose row names cross a `Z`/`a`-style case boundary — the
  test that fails under a locale collation.

### Verification

- [ ] `poetry run pytest tests/ -k "conditional or protocol" -v` passes
- [ ] `poetry run pytest tests/test_cold_start_budget.py -v` passes **unmodified** —
      no new model class was introduced
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 9: Metadata writes become compare-and-swap

Rows **9c** and the residual half of **9b**. Both have been waiting on a
primitive that did not exist —
[`whole-list-rewrite-atomicity.md`](../todo/whole-list-rewrite-atomicity.md)
states it plainly: *"No CAS exists on `DbProperty`. Only `create_if_not_exists`
and `delete_if_value_equals`."* Phase 8 builds exactly that CAS for
`update_by_handle`, so these close as a consequence rather than as new design
work. That is the reason they are in this release and not a later one.

Note what this phase does **not** do: `compact()` is still not crash-atomic.
That is row 9b's main subject and stays open — see "What We're NOT Doing".

### Changes

- `actingweb/property_list.py:416-446` — `_read_meta_row()` returns the raw
  stored string alongside the parsed dict, so a caller can condition a write on
  the exact bytes it read (the contract `db/protocols.py:277-280` requires).
- `actingweb/property_list.py:447-546` — `_save_metadata()` becomes a bounded
  read-merge-CAS-retry loop on Phase 8's `set_if_value_equals`. Today it is a
  plain read-modify-write, so *"a migration that completes inside that gap is
  still reverted"* — raised as a P1 by Codex review on PR #127 and **accepted
  as a known trade** because the primitive was missing. It no longer is.
- `docs/guides/property-lists.rst` §"Concurrency during a whole-list rewrite"
  and the migration guide — both document that window as accepted. Both must be
  updated to say it is closed, or the docs become wrong in the other direction.
- `actingweb/property_list.py` — **row 9c: dispatch on a fresh metadata read,
  not the cache.** Today a `ListProperty` retained across a migration writes a
  v1-shaped row into a list that is now v2; the row is unreachable, `verify()`
  still reports the list healthy, and GA ships only a WARNING
  (`property_list.py:519-537`) which makes it visible without saving the write.
  A mutation already pays a fresh meta read inside `_save_metadata()`, so
  moving that read *before* the dispatch and merging into the dict it returned
  trades one gap for another rather than adding a round trip. The WARNING stays
  as a backstop.
- `actingweb/property_list.py` — **v1's `length` read side.** The 2026-08-15
  plan fixed the write side (`_save_metadata()` names the fields it changes);
  the read side is still open, and v1's `append()`/`insert()` derive the new
  length from `len(self)`, which reads `_meta_cache` — so a retained instance
  can compute a stale absolute value and write it. With CAS available, make the
  v1 length a delta merged under the compare-and-swap rather than an absolute
  computed from a cached view.
- **The retry loop's failure mode is specified, not improvised.** Bounded
  attempts (single digits) with full-jitter exponential backoff; on
  exhaustion raise `ListMetadataContentionError` (new, exported from
  `actingweb`), and `handlers/` map it to **503 with `Retry-After`** — a
  contended row is a retryable condition, not a server fault, and a bare 500
  behind an API gateway sends consumers hunting a bug that is not there. One
  WARNING log with actor and list ids. The sizing assumption to write down in
  the code: in lambda-like fleets the contending writers are other
  containers, so no in-process lock can dampen the race — the jitter and the
  bound are the whole mechanism.
- **The carve-out: an advisory touch never fails a committed mutation**
  (consumer round-2, filed as informational, taken as a design change).
  `_v2_append` writes the item row first and touches metadata second, so a
  raise from the touch propagates *after* the item is committed — and a 503
  whose entire meaning is "retry" then manufactures a duplicate, which a
  consumer cannot guard against in-process on lambda (their idempotency dict
  dies with the container). So `_v2_touch_metadata()`'s advisory write —
  `updated_at` plus `count_hint` on an **existing** meta row — swallows CAS
  exhaustion with one WARNING and the mutation succeeds; the missed
  increment is the third term of Phase 5's drift bound, repaired by the next
  rank-counting mutation or `compact()`. Metadata writes that create the row
  or carry semantic fields — `format` flips, v1's `length` — still raise:
  there the metadata write *is* the operation.

### New Tests

- Unit: a metadata write whose row changed underneath it retries and merges
  onto the new value rather than overwriting it.
- Unit: **the reverted-migration scenario** — an instance held across a
  migration attempts a mutation; the migration's `format: 2` flip survives.
  This is the P1 from PR #127, pinned.
- Unit: a mutation on an instance whose cached format is stale dispatches on
  the fresh format, so no v1-shaped row is written into a v2 list. The
  `foreign_format_rows` count stays zero where today it becomes one.
- Unit: the CAS retry is bounded and raises `ListMetadataContentionError`
  rather than spinning when a row is under sustained contention, and the
  properties handler maps it to 503 with `Retry-After`.
- Unit: a v2 append whose advisory touch exhausts its CAS retries still
  returns success, logs one WARNING, and stores the item exactly once; a
  metadata write carrying `format` still raises on exhaustion — the
  carve-out's boundary, pinned from both sides.
- Unit: v1 `append()`/`insert()` on a retained instance with a stale
  `_meta_cache` no longer writes a stale absolute `length`.
- Regression: the existing metadata-integrity suite
  (`tests/test_property_list_integrity.py`) passes unmodified — this phase
  tightens those guarantees and must not alter them.

### Verification

- [ ] `poetry run pytest tests/test_property_list_integrity.py -v` passes
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] Manual: `docs/guides/property-lists.rst` and the migration guide no
      longer describe the read-modify-write window as an accepted trade

### Implementation Status: Not Started

---

## Phase 9B: `append()` stops paying the whole-list read

Consumer feedback F-1: as originally drafted, this release left `append()` —
the most common list write — opening with `_v2_ensure_rank_cache()`, a
whole-list range Query, on every call (always cold, because `property.py:54`
mints a fresh instance per attribute access). The append needs exactly one
fact from that read: the current **last** rank. Phase 8's
`get_last_in_range` fetches that fact for one item's read capacity.

**The stored-hint design is rejected, and the reason is recorded here so it
is not re-proposed.** The consumer sketched a CAS'd `last_rank` field in the
meta row and flagged the hazard themselves: `create_if_not_exists` detects
only exact-key collision, so a stale-low hint lands an append mid-list
silently. That staleness is not exotic — `_save_metadata()` merges onto a
fresh read and *preserves fields it does not recognise*, so a 3.13 writer in
a mixed fleet carries `last_rank` forward without maintaining it. Every
rolling deploy manufactures the failure, no fence on the 3.14 side can
detect it, and the corruption is silent by the consumer's own analysis. The
point read has no hint to go stale, works in mixed fleets, and adds no
meta-row contention (the hint design serializes every append on a meta CAS).

### Changes

- `actingweb/property_list.py:1004-1030` — `_v2_append()` replaces
  `_v2_ensure_rank_cache(force=...)` with one `get_last_in_range` over the
  item range. The existing collision loop is untouched, and it is what keeps
  the race behaviour byte-for-byte identical to today: rank generation is
  deterministic (`property_list.py:2343-2352`), so two appenders that read
  the same last rank produce the same candidate, `create_if_not_exists`
  rejects the loser, and the retry re-reads the new last rank. The read is
  strongly consistent with no parameter — same rationale as
  `_v2_ensure_rank_cache()`.
- The `extend` path (`:1038`) — same replacement: one last-rank read, then
  `generate_n_keys_between(last, None, n)` and n conditional creates.
- The `_V2_RANK_MAX_LEN` growth check needs only the last rank and is
  unchanged.
- Phase 5 interlock: append/extend no longer hold a rank cache, so their
  `count_hint` contribution is the stored-value-plus-delta merge Phase 5
  already specifies for them; on metadata with no hint they leave it absent
  rather than guessing.
- Cost: an append goes from [whole-list Query] + [conditional Put] +
  [meta read + write] to [one-item Query] + [conditional Put] +
  [meta read + write]. On the consumer's 81-row list the append's range read
  drops from 241 RCU to ~1.

### New Tests

- Unit: `append()` issues **zero** `get_range` and one `get_last_in_range` on
  the uncontended path — exact counts.
- Unit: a rank collision (simulated concurrent writer taking the candidate)
  forces a fresh last-rank read and the retry lands strictly after the
  concurrent writer's rank.
- Unit: `extend()` of n items issues one last-rank read and n conditional
  creates, and iteration order matches insertion order.
- Unit: append to an empty list works (`get_last_in_range` → `None` → first
  rank), and the first rank matches what the rank-cache path produced.
- Regression: v1 `append()` is untouched.
- Integration (both backends): interleaved appends from two instances produce
  a list whose iteration order matches insertion order — the mid-list-append
  regression the stored-hint design would have failed.

### Verification

- [ ] `poetry run pytest tests/test_property_list.py tests/test_property_list_integrity.py -v` passes
- [ ] `poetry run pytest tests/test_cold_start_budget.py -v` passes **unmodified**
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] Manual: the operation-counter recipe shows an append on a large list
      costing a one-item read where 3.13.0 paid the whole list

### Implementation Status: Not Started

---

## Phase 10: Handle mutations and the value-addressed writers

The centrepiece. A *k*-item delete goes from *k* × (2 range reads + a write) to
**1 range read + *k* point writes**, and no index is ever derived — so the
position-vs-storage-index skew that destroyed a neighbour row on 2026-07-19
becomes unrepresentable.

### Changes

- `actingweb/property_list.py` — `delete_by_handle(handle) -> bool` on
  `delete_if_value_equals(name=_v2_item_name(handle.rank), value=handle.raw)`,
  and `update_by_handle(handle, item) -> bool` on Phase 8's
  `set_if_value_equals`. Both v2-only. Both are **single-shot**: a handle
  pins the exact stored bytes, so there is nothing to re-resolve and a failed
  condition *is* the answer, returned as `False`. A retry loop here would
  convert "the row changed" into "overwrote the new value" — the bug class
  this API exists to kill. `_v2_pop`'s resolve → conditional-write → retry
  shape (`property_list.py:1349-1397`) belongs to the value-addressed helpers
  below, which can legitimately re-resolve by value, with a bounded retry
  count.
- `actingweb/property_list.py` — `remove_where(identity_key, value, *, first_only=False) -> int`
  and `update_where(identity_key, value, item, *, first_only=False) -> int`,
  returning the number of rows affected. Built on `items_with_handles()` plus
  the handle mutators under v2; under v1 they locate and use the positional
  path, which is no worse than what v1 code does today — with one rule the
  research never wrote down: a v1 multi-match delete applies its positional
  deletes in **descending index order**, because ascending order shifts every
  later match onto a wrong row (the 2026-07-19 skew in miniature). Pinned by
  a test.
- **No `BatchWriteItem`.** It cannot express conditions (25 items / 16 MB, and
  parallel execution consumes the same write capacity), so a batched delete
  would give up exactly the guarantee `_v2_pop` exists to keep.
  `TransactWriteItems` can express them but is all-or-nothing across 100
  actions / 4 MB, costs two write units per item, and **consumes that capacity
  even when the transaction is cancelled** — so one concurrently-modified row
  makes the whole batch pay twice and accomplish nothing. *k* independent
  conditional point writes is the shape that keeps the guarantee.
- `actingweb/interface/property_store.py` — `NotifyingListProperty` is an
  **allowlist**, not a `__getattr__` passthrough (`:290-400`). Every method
  above needs explicit delegation or it is invisible through
  `actor.property_lists.<name>` — which is how `get_metadata()` is already
  unreachable today. Each mutator also needs its `_register_diff`.
- **The subscription diff vocabulary.**
  `remote_storage.py:382-450`'s `_apply_list_operation` is a closed vocabulary
  that returns `{"error": "unknown operation"}` for anything it does not know,
  so a peer replica silently drops an unrecognised change.
  `remove_where`/`delete_by_handle` map onto the **existing** value-addressed
  `remove` operation (`:441-448`) — emit one `remove` diff per removed item.
  **But that path is dead today and must be repaired first.**
  `NotifyingListProperty.remove()` (`interface/property_store.py:380-382`)
  registers `_register_diff("remove")` with **no `item`**, while
  `remote_storage.py:441` gates on `operation == "remove" and "item" in data`.
  The gate therefore never matches and every `remove` diff falls through to
  `{"error": "unknown operation"}`, so peer replicas already miss every
  `remove()`. Pass `item=value` from `NotifyingListProperty.remove()`. That is
  a pre-existing notification defect fixed here because Phase 10 depends on the
  path working; it also means "old peers keep working" is true only *after*
  this fix, since a 3.13 peer's apply logic is correct and only the diff it
  receives was malformed.
  `update_where`/`update_by_handle` DO have a position to put in an `update`
  diff — the item's index in the strongly-consistent snapshot the handles
  were resolved from. So they emit the **existing** `update` operation
  (`remote_storage.py:397-402`) with `index` and `item`, plus a new optional
  `old_item` field carrying the pre-update value. A ≤3.13 peer applies it
  positionally — exactly the fidelity every positional diff it receives today
  already has — and a 3.14 peer's `_apply_list_operation` prefers a value
  match on `old_item`, falling back to the index when no row matches. No new
  operation name, so no peer ever takes the "unknown operation" silent-skip
  path; consumer feedback N-3 (live third-party ≤3.13 peers under
  auto-subscribe) is what killed the earlier new-vocabulary design, and the
  migration guide's note softens from a version gate to a fidelity note.
- `actingweb/interface/authenticated_views.py` — the Phase 2 proxy gates every
  new mutator behind `write` (and `delete` for `remove_where`).
- **The sync-callback fan-out is a documented cost, not a fixed one.** Each
  registered diff is one callback per subscriber (`actor.register_diffs`),
  and under `with_sync_callbacks()` — the recommended lambda posture — those
  callbacks run synchronously inside the request. A `remove_where` matching
  k items therefore performs k HTTP callbacks per subscriber, behind an API
  gateway timeout of roughly 29 seconds. Coalescing to a `clear` + `extend`
  snapshot pair was considered and rejected (see What We're NOT Doing).
  `docs/guides/property-lists.rst` gets the arithmetic and the guidance:
  size k against the timeout when the list has callback subscribers, and
  `suspend_subscriptions()`/`resume_subscriptions()` exists but suppresses
  the diffs entirely — a replica divergence the application then owns.
- Docs: `docs/guides/subscriptions.rst` — its list-operations table gains the
  new methods' diff mappings, the `update` operation's optional `old_item`,
  and the repaired `remove`-carries-`item` behaviour; the fan-out arithmetic
  lands beside its existing Subscription Suspension section (`:390`), which
  already teaches the suspend-during-bulk pattern the divergence caveat
  applies to. `docs/protocol/actingweb-spec.rst` — the `listproperties`
  subscription section documents `old_item` as an optional diff field.

### New Tests

- Unit: `remove_where` on a 50-item list issues **1** `get_range` and *k*
  point writes — asserted as exact counts.
- Unit: `remove_where(first_only=True)` removes one and returns 1; without it,
  removes all matches and returns the count.
- Unit: `remove_where` matching nothing returns 0 and writes nothing.
- Unit: `delete_by_handle` returns `False` (not an exception) when the row was
  concurrently changed or already deleted, and the list is otherwise unharmed.
- Unit: `update_by_handle` against a concurrently-modified row returns `False`
  and does **not** overwrite the other writer's value.
- Unit: **the generation boundary** — take handles, `delete()` the list,
  `append()` fresh items so ranks restart at `a0`, then attempt
  `delete_by_handle` with the stale handles. Every one must fail. This is the
  test the whole conditional design exists for.
- Unit: `delete_by_handle`/`update_by_handle` on a v1 list raise naming
  `migrate_to_v2()`; `remove_where`/`update_where` succeed on v1.
- Regression: `NotifyingListProperty.remove()` now emits `item` in its diff,
  and `remote_storage._apply_list_operation` applies it instead of returning
  "unknown operation" — the pre-existing defect, pinned so it cannot return.
- Integration: a `remove_where` registers one `remove` diff per removed item
  and a 3.13-era peer replica applies them correctly.
- Integration: an `update_where` registers an `update` diff carrying
  `index`, `item` and `old_item`; a 3.14 peer whose replica indices have
  skewed still applies it to the right item via `old_item`; a receiver
  without `old_item` support applies it positionally at the given index — no
  path reaches "unknown operation".
- Unit: `delete_by_handle`/`update_by_handle` issue exactly **one**
  conditional write and never re-resolve on failure — the single-shot
  contract.
- Unit: v1 `remove_where` with three matches deletes in descending index
  order, and the surviving items are exactly the non-matches.
- Unit: every new method is reachable through `actor.property_lists.<name>`.

### Verification

- [ ] `poetry run pytest tests/test_property_list.py tests/test_property_list_integrity.py tests/test_property_list_notifications.py -v` passes
- [ ] `poetry run pytest tests/ -k "remote_storage or subscription" -v` passes
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] `poetry run ruff check actingweb tests` passes

### Implementation Status: Not Started

---

## Phase 11: The library's own bulk endpoint moves onto handles

Closes the 2026-08-19 shape at its source. The REST contract stays
index-addressed — clients are unaffected — but the handler resolves indices to
handles **once** and mutates by handle.

### Changes

- `actingweb/handlers/properties.py:1113-1147` — replace the
  `pending_updates` / `pending_deletes` positional loops. One
  `items_with_handles()` resolves the whole batch; updates become
  `update_by_handle`, deletes become `delete_by_handle`. **`k + 2` → 1 range
  read + *k* point writes**, and the batch's documented ordering semantics
  (`:1002-1011` — updates first in given order, deletes last in descending
  index order) are preserved by resolving all handles against the pre-batch
  snapshot, which is exactly what those semantics describe. The append-at-length
  case keeps `append()`.
- A conditional write that returns `False` means the row changed under the
  batch. Report it per item in the response rather than failing the whole
  request, matching the endpoint's existing "log and continue" behaviour for
  delete errors (`:1153-1156`). Two race behaviours change on purpose and go
  in the changelog under CHANGED: an update that loses a race is reported
  instead of clobbering the other writer, and a same-batch update + delete
  addressed to the **same index** now applies the update and reports the
  delete as concurrently modified (the delete's condition pins pre-batch
  bytes the update just changed) where 3.13.0 deleted the updated row.
- `actingweb/handlers/properties.py:1790`, `:1825` and `www.py:925`, `:956` —
  the single-item REST and web-UI edit paths move onto the same primitives, so
  a single-item edit is one range read plus one point write instead of two
  whole-list reads plus a write.
- Docs: the bulk-endpoint section of `docs/guides/property-lists.rst`
  (`:296-360`) documents the per-item concurrently-modified reporting and
  the same-index update + delete semantics — the CHANGED entries stated
  where the endpoint is taught, not only in the changelog.

### New Tests

- Integration: a *k*=10 update + 10 delete batch issues **1** `get_range` and
  20 point writes. The 2026-08-19 regression test.
- Integration: with no concurrent writer, all 20 items apply and none is
  reported as concurrently modified — the test that fails if
  `items_with_handles()` is ever allowed to read eventually.
- Integration: batch ordering semantics are unchanged — the same input produces
  the same final list as 3.13.0 does.
- Integration: a row modified concurrently mid-batch is reported in the
  response and the remaining items still apply.
- Integration: a batch with an update and a delete on the same index — the
  update applies and the delete is reported as concurrently modified. The
  named test for the CHANGED entry; 3.13.0 deleted the updated row.
- Regression: every existing bulk-endpoint test passes unmodified.

### Verification

- [ ] `poetry run pytest tests/ -k "properties" -v` passes
- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] Manual: the operation-counter recipe shows a 10-item delete batch costing
      one range read, against the pre-release `2k + 2`

### Implementation Status: Not Started

---

## Phase 12: Whole-list teardown stops being a serial delete loop

Item 1 of [`dynamodb-known-next.md`](../todo/dynamodb-known-next.md), scoped to
its property-list half. `ListProperty.clear()`/`delete()` currently cost
**2 range Queries + 1 meta GetItem + *n* serial point deletes** — a 1,000-item
list is 1,000 serial round trips — and one of those two range Queries is
structurally guaranteed to return nothing.

This is the one delete path where `BatchWriteItem` genuinely applies: clearing
a list is an **unconditional** delete of everything, so the "no conditions on
batch put/delete" limit that rules batching out for Phase 10's `remove_where`
does not bite here.

### Changes

- `actingweb/db/protocols.py` — a `batch_delete(actor_id, names)` method,
  documented with the 25-item chunking and unprocessed-item retry that
  `BatchWriteItem` requires, and with the note that parallel execution
  *"consumes the same number of write capacity units"* — this buys round trips,
  not capacity.
- `actingweb/db/dynamodb/property.py` — implement over PynamoDB's
  `batch_write` context manager, which already chunks at 25 and retries
  unprocessed items with backoff. Verify that against the pinned PynamoDB
  version rather than hand-rolling a second chunk-and-retry layer on top —
  the unprocessed-items test below asserts the *behaviour*, whichever layer
  provides it.
- `actingweb/db/postgresql/property.py` — a single
  `DELETE … WHERE id = %s AND name = ANY(%s)`.
- `actingweb/property_list.py:1166` and `:1210` — `clear()` and `delete()` use
  it. Lookup-row cleanup and property hooks stay per-item; batching covers the
  raw deletes only, which is what the register's note already specifies.
- `actingweb/property_list.py:1120-1165` — **skip the always-empty sweep.**
  `sweep_foreign_format_rows()` reads the meta row and, on a healthy v2 list,
  still range-queries the **v1** byte range, which on an all-v2 fleet cannot
  return anything. The sweep is not gratuitous — its docstring records that
  cross-format residue is invisible to `exists()`/`list_all()` until a new list
  adopts it as its own items — but it is skippable when the list's own metadata
  shows no format change was ever interrupted. Gate it on that, and keep the
  full sweep whenever the metadata cannot rule one out.
- `actingweb/db/dynamodb/property.py` `DbPropertyList.delete()` — the same
  serial loop, same fix. The trust and attribute delete loops named in item 1
  are **out of scope**: different subsystems, no property-list dependency, and
  they keep their place in the register.

### New Tests

- Unit: `clear()` on a 60-item list issues 3 batched writes rather than 60
  point deletes, and the list is empty afterwards.
- Unit: unprocessed items returned by a simulated throttle are retried and the
  list still ends empty — the failure mode that makes naive batching worse than
  a serial loop.
- Unit: a healthy v2 list's `clear()` issues **one** range Query, not two.
- Unit: a list whose metadata shows an interrupted format change still gets the
  full cross-format sweep. The test that keeps the optimisation honest.
- Regression: cross-format residue is still removed in every case
  `tests/test_property_list_integrity.py` already covers — a cleared list must
  be empty in **both** storage namespaces, or an interrupted migration's
  residue gets adopted by the next list created under the same name.
- Integration (PostgreSQL): `ANY(%s)` deletes the same rows as the loop did.

### Verification

- [ ] `poetry run pytest tests/test_property_list.py tests/test_property_list_integrity.py -v` passes
- [ ] `poetry run pytest tests/test_cold_start_budget.py -v` passes **unmodified** —
      PynamoDB's `batch_write` is a method on the existing model, not a new one
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] Manual: deleting a 1,000-item list completes in a fraction of the
      round trips, measured with the operation-counter recipe

### Implementation Status: Not Started

---

## Phase 13: An orphan-row scan operators can trust

Row 9 (DEL5). `Actor.delete()` can leave property, attribute and trust rows
behind, and every consumer that has had such an incident writes the same scan —
the reference consumer already did. The reason to lift it into the library is
not that the scan is hard but that **the classification is not obvious, and
getting it wrong deletes live data**.

**Correcting the recorded decision.** 2026-08-14 said "ship it in
`verify_tables`". Having read that module, it is the wrong host:
`db/verify_tables.py` is DynamoDB-only by construction (it returns exit code 2
for PostgreSQL, on the grounds that Alembic owns schemas there), it issues one
`DescribeTable` per model and never reads a row, and it has no rate limiting,
checkpointing, or dry-run/apply split. An orphan scan is a full sweep of row
*contents* on *both* backends. The right host is
`actingweb/maintenance/verify_property_lists.py`'s shape — backend-agnostic,
`--rps` limited, checkpointed for resume, report-first. The substance of the
decision is unaffected: it ships in the library rather than being rewritten by
each consumer.

### Changes

- `actingweb/maintenance/verify_orphans.py` — new module, CLI conventions
  mirroring `verify_property_lists.py` (`--rps`, `--checkpoint-file`,
  `LOG_LEVEL`, run under the application's own `DATABASE_BACKEND`).
- Enumerate actor ids once, then sweep property rows (`list:`-prefixed rows
  included), attribute rows and trust rows, reporting any whose `actor_id` is
  absent from that set. The four edge cases below are the module's actual
  content and each is a named, tested behaviour rather than a comment:
  1. **Fail closed on an empty or failed actor read.** If the actor-table read
     returns nothing, the answer is an error and exit code 2 — never "every row
     is orphaned", which is the catastrophic reading.
  2. **Reserved ids are reported separately and never as deletable.**
     `_actingweb_`-prefixed ids hold live data; some are real actors
     (`ACTINGWEB_SYSTEM_ACTOR`, `OAUTH2_SYSTEM_ACTOR` in `constants.py:95,98`)
     and some deliberately are not in the actors table at all
     (`DELETED_ACTORS_STORE` at `:104`, the reference consumer's
     `_actingweb_websocket`). Match on the prefix, not on the known names — the
     list is not closed.
  3. **Consistent reads throughout.** An eventually-consistent scan shows a
     seconds-old actor as absent. This is an explicit **NOT-candidate** for
     Phase 6's `consistent=False`, and the code says so where it reads.
  4. **Report only; no `--delete`.** Classification is safe *because*
     `Actor.create()` writes the actor row first and `Actor.delete()` removes
     it last, so an actor mid-create or mid-delete always still has its row.
     That still makes this a point-in-time judgement about rows another process
     may be writing, which is why `docs/reference/actor-deletion.rst:252-256`
     says to run it deliberately, review the output, then delete. Shipping a
     delete flag invites exactly the cron job that documentation forbids. The
     hard and dangerous part is the classification; deleting reviewed ids is
     the operator's own line of shell.
- `docs/reference/actor-deletion.rst:237-256` — §"Finding orphaned rows" opens
  with *"There is no built-in orphan scan yet"*. Replace the write-your-own
  guidance with how to run this, keeping all four cases as the explanation of
  what the tool does and why it refuses to delete.
- The same docs section states the operational envelope, because the
  reference consumer runs a reduced IAM role in lambda-like containers: the
  scan needs table-read permissions (`Scan`/`Query` on the actor, property,
  attribute and trust tables) that a locked-down runtime role deliberately
  lacks — run it under an operator credential, not the application's role;
  and it is a long-running, checkpointed CLI for a persistent shell, not
  something to invoke inside a lambda-like runtime. It classifies orphans
  only — it does not replace `verify_property_lists` or consumer-side
  integrity sweeps, and the doc says which tool answers which question. The
  same envelope lands in `docs/guides/database-maintenance.rst`, the
  maintenance runbook operators already use, alongside its existing
  maintenance-lambda patterns.
- `pyproject.toml` — an `actingweb-verify-orphans` console entry point, and a
  thin `scripts/` wrapper, matching how `verify_property_lists` and
  `migrate_property_lists` already ship (`maintenance/__init__.py` records why:
  *"a tool that only exists in a source checkout is not a remedy for someone
  who installed from PyPI"*).
- **Import nothing at package scope.** `actingweb/maintenance/__init__.py` is
  docstring-only today and must stay that way. Importing anything under
  `actingweb.db.dynamodb` pulls in every model module, and each binds
  `AWS_DB_PREFIX` / `AWS_DB_HOST` / `AWS_DEFAULT_REGION` at class-definition
  time — item 6 of `dynamodb-known-next.md`, which bit the test harness during
  v3.13 development. An operator tool must not be able to freeze a consumer's
  table names by existing. Do the backend imports inside `main()`, as
  `verify_property_lists.py:311` already does.
- Note for whoever implements: `DbActorList.fetch()`
  (`db/dynamodb/actor.py:169`) is a deliberate unpaginated full-table Scan,
  documented as admin-only. That is acceptable here — it is what
  `verify_property_lists` already does — but it is also item 5 of
  `dynamodb-known-next.md`, so this phase inherits that limit rather than
  fixing it, and the module should say so where it calls it.

### New Tests

- Unit: rows belonging to a live actor are never reported.
- Unit: rows whose actor id is absent are reported, per row type (property,
  `list:` property, attribute, trust).
- Unit: **an empty actor set yields an error and zero orphans**, not a full
  table's worth. The catastrophic case, pinned first.
- Unit: a failed actor-table read yields exit code 2, not a report.
- Unit: `_actingweb_`-prefixed ids appear in the reserved section and never in
  the orphan section — including an id not in `constants.py`, so the test
  covers the prefix rule rather than the known names.
- Unit: no code path in the module can delete a row — asserted structurally, so
  a later "helpful" addition fails the suite.
- Integration on both backends: a deliberately orphaned row set is classified
  identically under DynamoDB and PostgreSQL.
- Integration: reads are consistent — a just-created actor's rows are never
  reported as orphaned.

### Verification

- [ ] `poetry run pytest tests/ -k orphan -v` passes
- [ ] `poetry run pytest tests/test_cold_start_budget.py -v` passes
      **unmodified** — importing `actingweb.maintenance` still pulls in no
      backend module
- [ ] `make test-all-parallel` passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … make test-integration` passes
- [ ] `poetry run pyright actingweb tests` passes
- [ ] Manual: run against a scratch deployment with a known orphan and a known
      reserved id, and confirm the two land in different sections

### Implementation Status: Not Started

---

## Phase 14: Release

### Changes

- `pyproject.toml` and `actingweb/__init__.py` → `3.14.0`
- `CHANGELOG.rst` — rename "Unreleased" to `v3.14.0: <date>`, add a fresh empty
  Unreleased. Under **CHANGED**, call out the behaviour changes explicitly:
  `get_metadata()["length"]` and the REST single-list `count` responses are
  advisory under v2, with Phase 5's drift bound stated rather than
  paraphrased; the bulk endpoint's race semantics (a lost update is reported
  per item instead of clobbering, and a same-batch same-index update + delete
  no longer deletes the updated row); `remove()` diffs now replicate to
  peers, where before 3.14 they were silently dropped; and value-addressed
  updates apply value-matched on 3.14 peers, positionally (best-effort) on
  older peers. Read consistency is **not** among them — Phase 6 changes no
  default, and the new `consistent=` parameter belongs under ADDED with the
  measured saving.
- `docs/migration/v3.14.rst` — the upgrade note: what the handle API is for,
  why positional access is the thing to stop doing, the peer-behaviour note
  on value-addressed updates (value-matched on 3.14 peers, positional
  best-effort on older — no version gate), that the metadata
  read-modify-write window documented as accepted in 3.13 is now closed, the
  append cost change (whole-list read → one-item read, Phase 9B), the
  count-hint drift bound with the quota-check recipe, and the
  operation-counter recipe carried forward from `v3.13.rst`. Mention
  `verify_orphans` under tooling, with its IAM and runtime envelope. The
  guide also carries the retry-idempotency note: on a **v1** list a 5xx from
  a mutation may still follow a committed item write (the length write is
  semantic and can fail after the item lands), so retries there should be
  value-checked first — `find()` makes the check one read; under v2 the
  Phase 9 advisory-touch carve-out removes the case.
- **The docs sweep** — every documentation surface this release touches, in
  one checklist. The per-phase bullets above carry the substance; this is
  the completeness check, because three incidents came from docs asserting
  stale cheapness and the release must not ship with any file still
  describing 3.13 behaviour:
  - `docs/guides/property-lists.rst` — Phases 1, 5, 6, 7, 9, 10, 11: cost
    truths, drift bound (all three terms) + quota recipe, `consistent=`,
    identity-vs-position and the handle generation caveat, the closed
    metadata window, fan-out arithmetic, bulk-endpoint race semantics, and a
    "reading many lists cheaply" section on `list_all_with_rows()` that
    states its opaque-rows contract.
  - `docs/guides/subscriptions.rst` — Phase 10: operations table, `old_item`,
    repaired `remove`, fan-out beside Subscription Suspension.
  - `docs/protocol/actingweb-spec.rst` — Phase 10: `old_item` as an optional
    diff field under `listproperties`.
  - `docs/sdk/authenticated-views.rst` — Phase 2: per-operation permission
    semantics for `AuthenticatedPropertyListStore`; `create()` is gone.
  - `docs/reference/actor-deletion.rst` and
    `docs/guides/database-maintenance.rst` — Phase 13: `verify_orphans`, its
    IAM/runtime envelope, which tool answers which question.
  - `docs/migration/v3.14.rst` — new, per the bullet above.
  - `docs/migration/common-pitfalls.rst` — a positional-access entry
    pointing at handles and the value-addressed helpers.
  - `docs/migration/v3.13.rst` — only the operation-counter recipe is
    referenced from the new guide; its historical claims stand unedited.
  - `docs/sdk/developer-api.rst` and `docs/reference/interface-api.rst` —
    extend whichever enumerates the list API with the new methods (verify
    which does rather than assuming; today only `developer-api.rst` mentions
    the list store at all).
  - `actingweb/db/protocols.py` and `actingweb/property_list.py` docstrings —
    Phase 1's corrections plus the contracts for every new method.
- `thoughts/todo/` — delete `library-callers-pay-v2-list-cost.md`,
  `list-delete-by-value-primitive.md`,
  `authenticated-list-store-create-delete-broken.md`,
  `property-fetch-reads-whole-partition.md`,
  `orphan-detection-in-verifier.md`; strike items 1 (property-list
  half), 2 and the row-14 corrections from `dynamodb-known-next.md`, and record
  that item 3's `get_range` sub-item is closed while the other sites stand;
  **add** a todo for the `prop#`/`list#` key-prefix scheme, pointed at the next
  major alongside row 12.
- `thoughts/todo/whole-list-rewrite-atomicity.md` — **keep the file**, and
  rewrite it around what is left. Row 9c's section goes, the CAS-does-not-exist
  constraint goes (it does now), and the P1-accepted-trade note goes. What
  remains is the main subject — crash-atomic `compact()` — with its two dead
  designs, which are the reason the file exists.
- `thoughts/todo/attribute-list-shift-design.md` — update the sequencing note:
  it now also waits on Phase 10's diff-vocabulary change settling, and it can
  adopt the handle API rather than reinvent it.
- `thoughts/todo/INDEX.md` — re-rank; rows 14, 15, 16, 17, 5, 9c and 9 are
  gone, and row 9b is smaller than it was.

### Verification

- [ ] `make test-all-parallel` passes
- [ ] CI green on **both** database backends
- [ ] Docs build clean, and a grep sweep over `docs/` for retired claims —
      "two queries per item", keys-only cheapness, both-peers-on-3.14
      phrasing, "no built-in orphan scan" — returns nothing
- [ ] Both version files match the intended tag exactly
- [ ] `poetry build` succeeds

### Implementation Status: Not Started

---

## Evaluation Notes

Run inline rather than by an agent team, at the user's direction.

### Architecture

**`NotifyingListProperty` is an allowlist, not a passthrough** — and this was
nearly missed. `interface/property_store.py:290-400` enumerates every delegated
method by hand. Any method added to `ListProperty` without a matching entry is
invisible through `actor.property_lists.<name>`, which is the only path the
fluent API offers. The proof it already bites: **`get_metadata()` is not in the
list**, so a public documented method is unreachable through the interface
today. Phases 7 and 10 now carry explicit delegation requirements and a
regression test asserting the proxy's surface, and Phase 5 adds the missing
`get_metadata()`.

**The subscription diff vocabulary is closed on both sides.**
`remote_storage.py:382-450` returns `{"error": "unknown operation"}` for
anything unrecognised, so a new operation makes peer replicas silently diverge.
Resolved in Phase 10 by mapping `remove_where` onto the **existing**
value-addressed `remove` operation and `update_where` onto the existing
`update` operation extended with `old_item` — after consumer feedback N-3
established that live third-party peers on ≤3.13 make any new operation name
a silent-divergence machine. Neither research document raised this.

**The existing value-addressed diff is dead on arrival.**
`NotifyingListProperty.remove()` (`interface/property_store.py:380-382`) emits
no `item`; `remote_storage.py:441` requires one. So every `remove()` on a list
with peer subscribers has been silently failing to replicate — a pre-existing
notification defect nobody had reason to look for, surfaced only because
Phase 10 wanted to build on that path. Repaired in Phase 10 and pinned by a
regression test.

**The metadata write path is contended, and this release stops it being so.**
`_v2_touch_metadata()`'s re-read-then-write exists because a cached `format`
carried back over a completed migration destroys the whole list — the defect
that made 3.13.0 GA. Phase 5 adds a field to that write and its drift analysis
is deliberately written against last-writer-wins, so it stays correct whether
or not Phase 9 lands. Phase 9 then closes the window outright, using the CAS
Phase 8 builds for an unrelated reason. **This adjacency is the single most
valuable thing the scope review found**: two todo rows that had been deferred
for want of a primitive turn out to be sitting one phase away from it, and the
plan orders itself so they fall out rather than being designed.

### Security

**`AuthenticatedPropertyListStore.__getattr__` checks only `read` and returns a
fully-mutable object** (`interface/authenticated_views.py:236-242`). A peer
holding read-only permission on a list can `append`, `__setitem__` and
`__delitem__` through the permission-enforcing view. `AuthenticatedPropertyStore`
does it correctly for simple properties (`:113-127`, per-operation
`read`/`write`/`delete`), and the separate `write`/`delete` checks on this same
class's `create`/`delete` show per-operation checks were intended. This is
pre-existing and not a v2 consequence, but every mutator in Phases 10–11 widens
it, so it was promoted into Phase 2 and Phase 2 now gates the later phases.

**The conditional primitives are parameterised on both backends.**
PostgreSQL's conditional delete (`db/postgresql/property.py:552-585`) uses
bound parameters; Phase 8's `set_if_value_equals` mirrors it. `identity_key`
matching is in-memory dictionary access, so `find`/`remove_where` introduce no
query-construction surface.

**Handles must not leak trust.** A handle carries a rank and raw stored bytes.
Phase 7 makes them non-wire-stable by design and documents the generation
boundary, so an application cannot hand one to a peer and have it address a
row in a later list generation — the failure `property_list.py:2343-2352`
records from the migration rollback.

### Scalability

**The cold-start `DescribeTable` budget is a silent regression risk and now has
an instrument.** `_ensure.py` collapsed the old per-accessor
`if not Model.exists()` pattern — measured at >1,000 `DescribeTable`/minute in
a near-idle production deployment — to at most one check per model class per
process, and to zero when auto-creation is disabled. The memo is keyed on the
**model class**, so the way to lose that quietly is to add one: a new
`Model` subclass for Phase 8's conditional set or Phase 12's batch delete would
cost one more control-plane call on every container start, and the existing
`tests/test_ensure_table.py` would not catch it, because it exercises the guard
with fake models rather than counting calls across the real set. Phase 1 now
pins both numbers, the plan forbids new model classes outright, and Phases 8,
12 and 13 each verify the budget test still passes **unmodified**. The
`AWS_DB_AUTO_CREATE_TABLES=false` case is the one to watch: roles in that
posture have had `DescribeTable` removed from IAM entirely, so a regression
there is an outage rather than a slowdown.

**The biggest unlisted site is on the SDK path, not the web UI.**
`_register_diff` (`interface/property_store.py:257`) calls `len()` on every
diff, and `append()` (`:356`) calls it again — a whole-list Query per notified
mutation, doubled on append, for every application with subscriptions enabled.
Neither research document enumerates it. Phase 3 removes the immediate double
count; Phase 5 removes the read entirely.

**`www.py`/`trust.py` go to zero, not to fewer.** `list_all()` already fetches
the whole partition (`property.py:31-51`) and discards it. Phase 3's fix reuses
that dump, which also removes the per-property `exists()` GetItem. This is a
materially bigger win than row 16's todo records, which pointed at
`www.py:353-354`'s `to_list()`-then-count as the model.

**The 1 MB Query ceiling is close.** The consumer's largest list is 964 KB in
one page — 94% of the limit. Past it, one range read becomes N sequential
queries (correctly; PynamoDB follows `LastEvaluatedKey`), and N then multiplies
against anything per-item. Phases 7–11 remove the per-item multiplier, which is
what makes the ceiling survivable; the ceiling itself belongs to the
`prop#`/`list#` scheme filed for the next major.

**Conditional writes are not free when they lose.** A DynamoDB conditional
write whose expression evaluates false still consumes write capacity, and a
transactional write consumes its capacity even when the transaction is
cancelled. Phase 8's contract and Phase 10's bounded retry are written against
that rather than against "failed attempts cost nothing".

### Usability

**The `list:~` sentinel in row 5's todo is wrong and would have shipped.** `~`
is 0x7E, so any list whose name starts above it — every non-ASCII list name —
sorts after `list:~` and leaks back into the plain-property result. Phase 4
specifies `list;` (0x3B) with a test that fails under the sketched sentinel.
Separately, the PostgreSQL half must not use ordering comparisons at all, since
text ordering is collation-dependent; `NOT LIKE 'list:%'` is collation-proof.

**Phase 6 lost a default flip, an app-level switch and an instance flag, and is
better for it.** Two earlier drafts are worth recording so they are not
reproposed. The first flipped `to_list()` and friends to eventual consistency
and relied on an instance-level "has written" flag to keep read-after-own-write
safe; the flag does not work, because `property.py:54` mints a fresh
`ListProperty` per attribute access, so it is false on nearly every read in a
new request. The second kept the flip and added
`with_list_reads()` plus an env override as the escape hatch — which is a
DynamoDB-only knob on a backend-agnostic API (PostgreSQL ignores it) and a
third instance of the env-var/builder-method/default three-sources-of-truth
pattern INDEX row 12 already files against `use_lookup_table`.

What survives is smaller and answers the question both drafts were dodging:
**only the application knows whether a particular read may be stale**, because
the risky case is cross-request and cross-container. So the choice goes on the
call, defaults to today's behaviour, and the library takes the saving nowhere —
not even in its own handlers, where a REST client doing PUT then GET reasonably
expects to see its write. Consumers who want the 2× ask for it where they can
see what the read is for.

**One contract genuinely changes and is called out.**
`get_metadata()["length"]` becomes advisory under v2. `len()` stays exact, the
drift is self-correcting on the next mutation, `verify()` reports it and
`compact()` repairs it — but it is a public contract change and belongs in the
changelog under CHANGED, not buried.

**The v1 refusal must be actionable.** `items_with_handles()`/`*_by_handle` on
a v1 list raise, and the message names `migrate_to_v2()` — the method that
fixes it — rather than describing an internal format. The universal
`find`/`remove_where` mean an application never *has* to know which format its
list uses.

**`fetch()`'s empty-partition answer is a contract nobody wrote down.** Today
it returns `{}`, not `None`, for an actor holding only `list:` rows, because
`Property.query()` returns a truthy iterator regardless. Two queries would
naturally return `None`. Pinned by a regression test in Phase 4.

### The consumer-feedback and staff-review pass (2026-08-20)

Sources: actingweb_mcp's second measurement pass (their
`thoughts/research/2026-08-20-v2-list-read-cost.md`) and a staff review of
this plan against the lambda-like deployment posture. Dispositions:

**Confirmed: one release.** The staff review proposed shipping Phases 1–4 as
an immediate 3.13.1 (they carry the Phase 2 permission fix with no new API);
the maintainer decided all fourteen phases ship together as 3.14.0.

**F-1 (append is still O(n)) → Phase 9B.** The consumer's traced round trips
were right, and their proposed fix fails in exactly the way they feared: a
stored `last_rank` hint cannot be made safe, because `_save_metadata()`
preserves fields it does not recognise without maintaining them, so every
rolling deploy manufactures the stale-low hint whose failure is a silent
mid-list append. The plan takes the hazard-free version of the same win: a
reverse point read of the last rank (Phase 8's `get_last_in_range`), which
has no hint to go stale, adds no meta-row contention, and keeps the existing
collision-retry semantics unchanged.

**N-1 (quota enforced on an advisory count) → Phase 5 states the bound.**
`|count_hint − len()|` ≤ mutations in flight, plus pre-3.14-writer mutations
during a rolling deploy; exact at quiesce; `len()` always exact. The guide
adds the enforcement recipe — trust the hint below the limit, confirm with
`len()` at the limit — which prices the exact read at the quota boundary
instead of on every save (the consumer's `_check_storage_capacity` shape).

**N-3 (live ≤3.13 third-party peers) → Phase 10 abandons the new diff
operation.** `update_where`/`update_by_handle` emit the existing `update`
operation with the snapshot index plus an `old_item` field: old peers keep
today's positional fidelity, 3.14 peers match by value, and no peer ever
takes the "unknown operation" silent-skip path. The both-sides-on-3.14
constraint is gone from the migration guide.

**Staff findings folded in place:** handle mutators are single-shot
conditional writes, with the retry loop confined to the value-addressed
helpers (Phase 10); metadata CAS exhaustion is `ListMetadataContentionError`
→ 503 + `Retry-After`, with jittered backoff sized for cross-container
contention (Phase 9); the sync-callback fan-out on bulk mutations is
documented with its arithmetic, and snapshot coalescing is recorded as
rejected (Phase 10, What We're NOT Doing); the bulk endpoint's two changed
race behaviours get a named test and CHANGED entries (Phases 11 and 14); v1
`remove_where` deletes in descending index order (Phase 10); PynamoDB's own
`batch_write` chunk-and-retry is verified rather than duplicated (Phase 12);
and `verify_orphans` documents its IAM and runtime envelope (Phase 13).

**Consumer observations needing no plan change:** Phase 3's www/trust wins
are nil for headless consumers (`with_web_ui(enable=False)`) — the REST
`/items` and bulk-endpoint fixes in Phases 3 and 11 are the rows that carry
their numbers; their D5 (MCP batch caps) stays theirs, as their own pass
concluded; and D7 (the 1 MB Query ceiling, at 94% on their largest list)
remains deferred to the `prop#`/`list#` scheme filed for the next major.

### Round 2 (2026-08-20)

The consumer confirmed F-1/N-1/N-3 resolved and independently verified the
Phase 9B rejection reasoning against `property_list.py:539-544`. Three items
remained, all taken, plus one they filed as informational that the plan takes
as a design change:

**F-2 → `list_all_with_rows()` is public** (Phase 3, Decisions). Round 1
under-scoped it: the private helper stopped the library's own callers from
re-buying the dump while leaving consumers — who already hold the priming
half of the API — unable to reach the rows without going around
`ActorInterface`. Their number: 672 RCU of per-list re-reads per
`GET /api/outputs` on top of the dump `list_all()` already paid for.

**The drift bound's third term** (Phase 5). Post-9B appends merge
stored-plus-delta and never re-count, so a failed advisory touch persists in
an append-only workload until a rank-counting mutation or `compact()`. The
bound now has three terms; the boundary-confirm recipe was already robust to
the third, and the guide says so explicitly.

**F-6 → the full-state subscription fallback** (Phase 3).
`_get_full_state_for_subscription()` had the same dump-discard-re-read shape
as `www.py`, on a path headless consumers actually reach
(`actor.py:2452-2469`, peers without resync support), ~1,650 RCU measured.
Fixed with the same primed-rows pattern.

**503-after-committed-write → the advisory-touch carve-out** (Phase 9).
Rather than documenting the duplicate-on-retry hazard, the plan removes it
for v2: an advisory metadata touch that exhausts its CAS retries after the
item row is committed logs a WARNING and the mutation succeeds — a 503 whose
meaning is "retry" must never follow a committed write the retry would
duplicate, and lambda containers make consumer-side idempotency guards
unreliable by construction. The migration guide keeps the idempotency note
for v1, whose length write is semantic and can still fail after the item
lands.

**Their fan-out observation needs no plan change** — a consumer-side batch
cap of min(RCU-safe, callback-safe) where callback-safe scales with
subscriber count is their D5, and the guide's arithmetic is what that cap
computation will cite.

**Docs sweep** (same round, maintainer-directed): per-phase docs targets
were named after surveying `docs/` — `subscriptions.rst` owns the diff
vocabulary and the suspend-during-bulk pattern, `actingweb-spec.rst` the
`listproperties` subscription section, `property-lists.rst:296-360` the bulk
endpoint, and `authenticated-views.rst` has no list-store section at all
today — and Phase 14 gained the release docs checklist plus a
retired-claims grep in its verification.
