---
status: active
---

# Implementation Plan: a v2 list mutation never raises after its item write has committed

**Date:** 2026-09-14
**Research:** thoughts/research/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md
**Branch:** to be created as `fix/3.14.7-list-mutation-committed` from `master` at `adfecc3`

## Overview

Every v2 `ListProperty` mutator commits its item row and then calls
`_v2_touch_metadata()`. The touch's `advisory=True` swallows compare-and-swap
exhaustion only; a backend fault (`DbError`, or PostgreSQL's `RuntimeError` on
the row-creation branch) raises out of a mutation that already happened, so a
caller that retries duplicates its own save, `not_found`s its own delete, or
loses both copies of a move. The class docstring and plan 2026-08-20 already
list "a backend fault after the item write" as tolerated drift; the code stops
at contention. On a list's first mutation the touch is also what creates the
meta row, so a fault there leaves item rows with no meta row: invisible to
`exists()`/`list_all()`/REST, called healthy by `verify()`, and swept as residue
by the next `delete()`/`clear()`/`migrate_to_v2()`.

This plan (1) makes the advisory touch swallow backend faults the way it
already swallows contention, (2) creates the meta row *before* the first item
write so an item row can no longer exist without a meta row through this path
except when a concurrent `delete()` races the first mutation and the
recreation write also faults, (3) makes `verify()` report the orphan state,
and (4) ships it as 3.14.7.

## Decisions Made

- **Existing meta row, backend fault in the advisory touch: swallow, log one
  WARNING, return.** Same treatment CAS exhaustion gets. Matches the class
  docstring (`property_list.py:312-314`), plan 2026-08-20 (`:829-831`,
  `:1341-1353`) and every external precedent the research found (Django
  `on_commit(robust=True)`, Kubernetes advisory warnings, DynamoDB
  `BatchWriteItem` partial success). `ValueError` (unparsable meta row,
  `#`-name ban, scalar-name collision) is semantic and keeps raising.
- **First mutation: write the meta row first.** When `_dispatch_and_stash()`
  read `(None, None)`, the creating mutators (`append`/`extend`/`insert`)
  create the meta row with `create_if_not_exists`, then write the item, then
  run the advisory touch. One extra write on a list's first mutation only. A
  fault on the item write now leaves an empty but *visible* list, which is
  the visible side of "prefer visible failure". Atomic item+meta was rejected
  as a new protocol primitive with 2x WCU on DynamoDB; swallow-and-rely-on-
  repair was rejected because the list stays invisible and sweepable; repair-
  on-read was rejected because it reverses plan 2026-08-29's decision to leave
  orphan rows unattributed.
- **Residual (a `delete()` sweep lands between the meta create and the item
  write, so the touch is back on the creation branch, and *that* write
  faults): swallow with WARNING.** A rare orphan in a window that already
  requires a concurrent `delete()`. Consistent with the first decision; no new
  exception class.
- **Scope: v2 item mutators only.** v1 mutators, `_v2_compact`, `clear()`,
  `delete()` and `migrate_to_v2()` keep their non-advisory shape by recorded
  decision ("there the metadata write IS the operation"). Production is
  all-v2 and new lists are born v2. The v1 residual stays documented.
- **Partial multi-item operations: unchanged, fixed at the root.** With the
  first decision the touch is no longer a cause of a discarded partial result.
  A `DbError` from an item write itself (`create_if_not_exists`,
  `delete_if_value_equals`) still discards it, as any storage fault mid-batch
  does today. No return-type or exception-type change.
- **Adjacent finding (botocore retrying a timed-out conditional write can
  return `False` for a write that landed): separate todo.** Different
  mechanism, different fix shapes. The changelog does not claim retries become
  safe.
- **`verify()` reports the orphan state.** The v2 report gains
  `meta_row_present`, and `healthy` is `False` when item rows exist without a
  meta row. Additive key; the maintenance script never enumerates orphans, so
  no automated consumer changes outcome.
- **Release: 3.14.7 patch with FIXED entries.** No route, hook, kwarg, response
  field, public signature or config option changes. Every consumer-visible
  shift gets a bold **Behavior change** sentence in the changelog.
- **Phasing: one code phase, one docs phase, one release phase.** The
  existing-row swallow and the meta-row-first ordering land together, because
  the second depends on the first for its residual and the tests share one
  fault-injection double.

Amendments accepted during the engineering review (`/plan-eng-review`, report
at the end of this file):

- **The backend-fault swallow is one guard at the touch, not three inside
  `_save_metadata`.** `_v2_touch_metadata()` is the only caller that passes
  `advisory=True` and its docstring already says every caller has committed;
  one `try/except (DbError, RuntimeError)` around its `_save_metadata()` call
  covers the retry read, the CAS write and the creation branch. `_save_metadata`
  keeps its current shape (`advisory` = swallow CAS exhaustion) and only its
  docstrings change.
- **The first-mutation write sequence gets an ASCII diagram**, in this plan
  and in `_v2_create_meta_row()`'s docstring. The module has no diagrams
  today; this sequence has four distinct fault exits.
- **`ListMetadataContentionError` gains a keyword-only `detail: str | None =
  None`.** The lost-create raise says what happened ("metadata row changed
  under a first-mutation create") instead of "sustained contention". Additive,
  defaulted, patch-compatible; the 503 mapping is unchanged.
- **The three creating mutators call a named predicate
  `_dispatch_saw_no_row()`** instead of comparing the stash tuple inline.
- **Eight test gaps added**, including one mandatory regression test (the
  rank-cache invalidation inside `_v2_create_meta_row()` versus the REST bulk
  pass's `len() → append(None) → len()` loop) and two handler-level pins on a
  real backend.
- **One more todo**: `set_description()`/`set_explanation()` still create the
  meta row with an unconditional write, a last-writer-wins window this plan
  narrows but does not close.
- **From the outside voice** (nine findings, all verified against the tree
  and each resolved by an explicit decision): two existing tests in
  `tests/test_v2_append_last_rank.py` change their expectations; the
  residual test drops its stage word; the retry-read fault test gets a
  double that faults `get` only after a CAS loss; the docs check is the
  CI command; `meta_row_present` is computed before `stored or {}`; the
  guide, changelog and Overview are worded to exactly what the code keeps;
  the cost line counts the reads; and **`www.py` gets the
  `ListMetadataContentionError` → 503 mapping in Phase 1**, because the
  lost-create raise is a new pre-write raise on v2 first mutations and the
  browser UI would otherwise turn it into a 500.

## What We're NOT Doing

- Not changing v1 mutators, `_v2_compact`, `clear()`, `delete()` or
  `migrate_to_v2()`. Their post-commit raises (including v1's 503 "retry" on
  `ListMetadataContentionError`) stay as recorded in the class docstring.
- Not adding a typed "committed" exception. Nothing this plan leaves
  un-swallowed on the v2 item paths needs one.
- Not making item+meta atomic (no `TransactWriteItems`, no PostgreSQL
  transaction spanning both rows, no new `DbPropertyProtocol` method).
- Not repairing orphans on read. Bulk readers keep attributing orphan rows to
  no name (plan 2026-08-29 `:513-520`).
- Not fixing the botocore-retry ambiguous-primitive finding. It gets a todo.
- Not changing `set_description()`/`set_explanation()`'s unconditional create.
  They can still overwrite a row the meta-row-first create landed a moment
  earlier (a pre-existing last-writer-wins race on description/explanation and
  a `count_hint` of 0 over 1); the next rank-counting mutation repairs the
  hint. Out of scope for the patch; Phase 2 files it as a todo.
- Not adding a fault-injection seam inside the DynamoDB/PostgreSQL property
  modules. `thoughts/todo/v2-list-access-verification-followups.md:26-28`
  ("`DbError`-on-genuine-fault path untested" at the backend layer) stays open;
  this plan pins the path at the `property_list.py` layer with a fake.
- Not touching `docs/migration/v3.14.rst` (patch release).
- Not changing `www.py` beyond the one `ListMetadataContentionError` mapping
  in its list-item block (see Phase 1). Its other error paths stay as they
  are.

## Phase 1: The advisory touch never fails a committed mutation, and a list's first mutation creates its meta row first

### Changes

**`actingweb/property_list.py`**

*Import:* `from actingweb.db.exceptions import DbError` (not imported today;
the file only imports `get_property` from `actingweb.db`).

*`_v2_touch_metadata()` (`:1251-1321`) — the one guard that makes a
committed v2 mutation unfailable by its bookkeeping:*

- The `self._save_metadata(updates, count_delta=..., advisory=True)` call
  (`:1317-1321`) is wrapped in a single `try/except (DbError, RuntimeError)
  as exc`. On either, log one WARNING and return. Nothing else changes in
  this method's body. This one guard covers every fault site inside
  `_save_metadata`: the retry-attempt read at `:792` (`DbError` from `get`),
  the CAS write at `:911` (`DbError` from `set_if_value_equals`), and the
  creation branch `:794-847` (`_load_metadata()`'s two `get`s raise `DbError`;
  the unconditional `set` at `:846` raises `DbError` on DynamoDB,
  `dynamodb/property.py:401-404`, and returns `False` on PostgreSQL,
  `postgresql/property.py:277-279`, which `_replace_metadata` turns into
  `RuntimeError("list metadata write failed …")` at `:982`). `ValueError` is
  deliberately not caught: `_read_meta_row()`'s unparsable-row `ValueError`
  and `_load_metadata()`'s `#`-name and scalar-collision `ValueError`
  (`:596-612`) are corruption and semantics, and stay visible.
- The WARNING text is distinct from the contention warning at `:925-931` so
  an operator can grep the two apart: "advisory metadata touch hit a backend
  fault after the item write committed ({exc}) -- the mutation this touch
  was recording already succeeded. count_hint may be off by one until the
  next rank-counting mutation or compact(); if the meta row was being
  recreated, it may be absent until the next mutation". Logged with
  `exc_info=True` so the chained backend cause (botocore / psycopg) reaches
  the log. `DbError`'s message already names the operation
  ("database error during property conditional write …"), so no separate
  stage argument is needed.
- After Phase 1's ordering change the creation branch is reached under
  `advisory=True` only for the residual (a `delete()` sweep between the meta
  create and the item write) and for a mutation against orphan rows left by a
  pre-3.14.7 fault. Both are the decision's "swallow with WARNING" case.
- `_save_metadata()` itself (`:694-936`) is not changed in code. Its
  `advisory` docstring (`:759-773`) is corrected: `advisory=True` still means
  "swallow CAS exhaustion", and the sentence "an unconditional write either
  succeeds or raises on a genuine backend fault, which is not a condition to
  swallow either way" is replaced with a pointer to `_v2_touch_metadata()`,
  which is where a backend fault under the advisory touch is swallowed.

*`ListMetadataContentionError` (`:189-217`):* `__init__` gains a keyword-only
`detail: str | None = None`. When given, it replaces the default "is under
sustained contention -- retry the request" clause; the `list_name` and
`actor_id` attributes and the "retry the request" ending are kept so the
handlers' 503 mapping and its test (`tests/test_v2_metadata_cas.py:179-208`)
are unaffected. The docstring gains one paragraph: the exception is also
raised, with a `detail`, by a list's first mutation that lost its
conditional meta-row create to a writer whose row it cannot follow; nothing
has been written in that case, and the 503's "retry" is exactly right.

*New `_dispatch_saw_no_row(self) -> bool`:* returns
`self._pending_meta_read == (None, None)`. One place documents that
`(None, None)` is the stash `_dispatch_and_stash()` leaves for an absent row
(`:419-422`) and that the `_NO_STASH` sentinel never compares equal to it.

*`_replace_metadata()` (`:938-993`):* the `Raises:` section becomes
"`RuntimeError` on PostgreSQL (whose `set` reports a fault as `False`),
`DbError` on DynamoDB (whose `set` raises)" for the unconditional write, and
"`DbError` on either backend" for the conditional one. No code change.

*New `_v2_create_meta_row()` — the meta row is written before a list's first
item.* The sequence and its four fault exits (this diagram also goes into the
method's docstring, and Phase 2's guide subsection reuses it):

```text
append()/extend()/insert() on a list whose dispatch read found NO meta row
──────────────────────────────────────────────────────────────────────────
 _dispatch_and_stash()        read meta ──► (None, None) stashed
        │
        ▼
 _v2_create_meta_row()        _load_metadata() ── ValueError ('#' name,
        │                     (2 reads)             scalar collision) ► raise, nothing written
        │                                        ── DbError            ► raise, nothing written
        │
        ├─ create_if_not_exists(meta) ── DbError  ► raise, nothing written            [exit 1]
        │        ├─ True  ► stash = (meta, bytes just written)
        │        └─ False ► re-read: v2 row     ► stash = (row, raw); continue
        │                            absent / v1 ► ListMetadataContentionError(detail=…)
        │                                          nothing written                    [exit 2]
        ▼
 item write  create_if_not_exists(list:{name}-#rank)
        │        └─ DbError ► raise; meta row exists: list is EMPTY and VISIBLE      [exit 3]
        ▼
 _v2_touch_metadata()   try: _save_metadata(advisory=True)
        │                 attempt 0 CASes on the stashed bytes
        │                 ├─ CAS exhausted         ► WARNING, return (hint drift +1)
        │                 ├─ DbError/RuntimeError  ► WARNING, return (hint drift +1)  [exit 4]
        │                 │    (creation branch only if a delete() swept the row
        │                 │     between create and item write: residual orphan)
        │                 └─ ValueError            ► raise (corruption stays visible)
        ▼
 return   the item write is committed; nothing after it can fail the call
```

```python
def _v2_create_meta_row(self) -> None:
    """A list's first mutation creates its meta row BEFORE its first item
    row, conditionally. Called by _v2_append/_v2_extend/_v2_insert only
    when _dispatch_and_stash() found no row."""
    self._invalidate_cache()
    meta = dict(self._load_metadata())        # '#'-name ban and scalar-
    meta_json = json.dumps(meta)              # collision check run HERE,
    meta_db = get_property(self.config)       # before any item write
    if meta_db.create_if_not_exists(
        actor_id=self.actor_id, name=self._get_meta_property_name(), value=meta_json
    ):
        self._meta_cache = meta
        self._pending_meta_read = (meta, meta_json)   # touch CASes on these bytes
        return
    # Lost the create: another writer made the row in the window.
    parsed, raw = self._read_meta_row()
    if parsed is not None and int(parsed.get("format", 1) or 1) == 2:
        self._meta_cache = parsed
        self._pending_meta_read = (parsed, raw)
        return
    raise ListMetadataContentionError(
        self.name,
        self.actor_id,
        detail="metadata row changed under a first-mutation create",
    )
```

  - `create_if_not_exists` raises `DbError` on a fault on both backends
    (`dynamodb/property.py:588-593`, `postgresql/property.py:626-630`).
    That propagates: nothing has been written, so raising is correct and a
    retry is safe.
  - The re-stash is load-bearing. Without it, the touch's attempt 0 would
    consume the `(None, None)` stash from `_dispatch_and_stash()`, take the
    creation branch, and overwrite the row just created with an
    unconditional `set` — defeating the CAS and any concurrent writer's
    update. With it, attempt 0 conditions on the exact bytes just written.
  - A lost create whose re-read shows no row (created and deleted again) or a
    non-v2 row raises `ListMetadataContentionError` with nothing written. The
    handlers already map that to 503 with `Retry-After`, and a retry is safe
    because no item row exists.
  - `_invalidate_cache()` first, for the same reason the creation branch
    does it (`:806-821`): a retained instance's stale v1 cache must not seed
    the row. `_load_metadata()` then takes its absent-row path and returns a
    clean v2 default (`_create_default_metadata_v2()`, `count_hint: 0`,
    `format_ever_changed: False`).

*`_v2_append()` (`:1481-1533`), `_v2_extend()` (`:1574-1634`),
`_v2_insert()` (`:2034-2066`):* at the top, before any rank read,
`if self._dispatch_saw_no_row(): self._v2_create_meta_row()`.
`_v2_extend` does this only when `items` is non-empty, so `extend([])` on a
never-created list still writes nothing. The rest of each method is
unchanged: item write, rank-cache upkeep, touch. The touch now always finds
the row it is recording against (barring the residual), so its
`count_delta` merges onto the created row's `count_hint: 0`.

*Cost, stated so nobody re-derives it:* a list's first mutation pays one
extra conditional write (the meta create), two extra point reads
(`_v2_create_meta_row()`'s `_invalidate_cache()` + `_load_metadata()`
re-issues the meta `get` and the scalar-collision `get` that
`_maybe_lazy_migrate()` already ran and cached before dispatch, `:1540`,
`:1646`, `:2073`), and its touch becomes a CAS write instead of an
unconditional one. `_invalidate_cache()` also drops the rank cache, so
`insert()` re-reads the rank range on its first mutation, and a caller that
reuses the same instance across the first mutation (the REST bulk pass,
`handlers/properties.py`, which loops `len(list_prop)` /
`list_prop.append(None)`) pays one cold rank-cache reload on that first
mutation only. The invalidation is required: a retained instance whose list
was deleted elsewhere may hold a stale v1 metadata cache that must not seed
the row, and a rank cache describing the dead list that `_v2_append()` would
append the new rank onto. The `#`-name and scalar-collision `ValueError`s
were already raised pre-write by `_maybe_lazy_migrate()`; this change does
not move them.

**`tests/test_v2_append_last_rank.py`** — two existing tests change their
expectations because the meta create is now the first conditional create on
a brand-new list:

- `:196-210` (`test_extend_of_n_items_issues_one_last_rank_read_and_n_creates`):
  `create_call_count == 5` for an `extend` of four (one meta create plus four
  item creates); the docstring says why. `last_in_range_call_count == 1` and
  `range_call_count == 0` are unchanged.
- `:265-300` (the stolen-row test): the injection that fires on the second
  `create_if_not_exists` call moves to the third, so it still lands on item
  "b" as the test's ordering assertions require.

Every other test that counts backend calls was checked for a brand-new list
at its first mutation and is unaffected, because the create path issues no
`get_range` or `get_last_in_range` and the counters that matter reset after
the first mutation: `test_v2_count_hint.py:197-234`,
`test_property_list_integrity.py:603-617`,
`test_v2_cost_library_callers.py:296-346`, the seeded tests in
`test_v2_handle_mutators.py` and `test_v2_value_addressed_reads.py`, and the
`CrashInjectingPropertyDb` tests (all v1-seeded). `tests/test_v2_append_last_rank.py:124`
(`test_the_exact_bulk_handler_shape_terminates`) and `:252`
(`test_extend_of_zero_items_is_a_no_op`) must stay green unchanged: they
pin the two behaviours the reordering is most likely to disturb.

*Other mutators are unchanged.* `__setitem__`, `__delitem__`, `pop`,
`remove`, `delete_by_handle`, `update_by_handle`, `remove_where`,
`update_where` operate on existing items. When they find item rows with no
meta row (orphans from a pre-3.14.7 fault), the touch's creation branch
recreates the row exactly as today, and a fault there is now swallowed.

*Docstrings updated in this phase because the code under them changes:*

- `_v2_touch_metadata()` (`:1292-1312`): the "It DOES create the row when
  absent … `append()` to a list with no metadata row is how a list comes into
  existence" paragraph is rewritten: a list comes into existence through
  `_v2_create_meta_row()` before its first item; the touch's creation branch
  is the fallback for a row that vanished between the two writes (a
  `delete()` race, still "a one-item list rather than nothing") and for
  orphan repair. The `advisory=True` paragraph says contention AND backend
  faults are swallowed, and drops the parenthetical claiming the creation
  branch "never reaches CAS exhaustion … so `advisory` has no effect on it".
- `_dispatch_and_stash()` (`:380-426`): one sentence noting
  `_v2_create_meta_row()` replaces the `(None, None)` stash with the row it
  created, and that `_dispatch_saw_no_row()` is how the creating mutators ask
  about it.
- `_v2_create_meta_row()`: carries the ASCII sequence diagram above, as an
  RST literal block (a `::` paragraph with uniformly indented lines) so a
  run of `──` at column 0 is never parsed as a transition. `conf.py` does
  not autodoc `actingweb.property_list`'s private members today, so Sphinx
  never renders it, but `sphinx-build -W` is Phase 2's gate and the literal
  form costs nothing.
- `_v2_append()`/`_v2_extend()`/`_v2_insert()`: one sentence each on the
  meta-row-first step.
- `ListMetadataContentionError` (`:201-208`): "swallows the same exhaustion
  with one WARNING" becomes "swallows the same exhaustion, or a backend
  fault, with one WARNING" (see the `detail` paragraph above for the rest).

**`actingweb/handlers/www.py`** — the list-item management block
(`:880-1035`, the `POST /{actor_id}/www/properties` form that appends,
updates or deletes one item) gains `except ListMetadataContentionError as e`
before its `except Exception` at `:1031`, responding
`set_status(503, "List metadata contended -- retry")` with
`headers["Retry-After"] = "1"`, the same shape its handle-conflict branches
already use at `:955-958` and `:1003-1006`. The `append` at `:899` is the
site that matters: after this plan a v2 list's first mutation can raise the
lost-create `ListMetadataContentionError` before any write, and the UI
previously turned that into a 500 "Error processing list item". The same
mapping covers the v1 contention raise the UI never mapped (the open bullet
in `thoughts/todo/v2-list-access-verification-followups.md`).

**`tests/test_property_list_integrity.py`** — no change. `FakePropertyDb`,
`_patch_get_property`, `_seed_list`, `_seed_v2_list` are imported by the new
test file.

### New Tests, both unit and integration tests

**New file `tests/test_v2_list_mutation_committed.py`** (module docstring
names this plan). Own autouse `_no_real_sleep` fixture (copied from
`tests/test_v2_metadata_cas.py:87-94`), because the meta `get`-on-retry
case needs the CAS loop to lose once first.

Doubles (all subclass `FakePropertyDb`):

- `_MetaFaultPropertyDb(store, fail_ops, lose_cas_first=0,
  fail_get_after_cas_losses=False)`: raises `DbError` from any op named in
  `fail_ops` (subset of `set`, `set_if_value_equals`, `create_if_not_exists`)
  when `name.endswith("-meta")`; `set_if_value_equals` returns `False` the
  first `lose_cas_first` times before faulting. With
  `fail_get_after_cas_losses=True`, `get` on `-meta` raises `DbError` only
  once at least one CAS loss has been recorded, so the dispatch read and
  `_maybe_lazy_migrate()`'s reads (both pre-write) succeed and the fault
  lands on `_save_metadata`'s retry read (`:792`). A plain `get` fault
  before any CAS loss would raise at `_dispatch_and_stash()` (`:419`),
  before the item write, which is a different (pre-commit) path. Counts
  calls per op. Item rows never end in `-meta`, so the filter hits only the
  meta row.
- `_ItemFaultPropertyDb(store)`: raises `DbError` from `create_if_not_exists`
  when `"-#"` is in `name` (item rows only).
- `_ConcurrentCreatorPropertyDb(store, injected_meta)`: on the first
  `create_if_not_exists` for a `-meta` name, writes `injected_meta` into the
  store and returns `False`.
- `_DeleteAfterCreatePropertyDb(store)`: after a successful
  `create_if_not_exists` on `-meta`, pops the row again (a concurrent
  `delete()` won), and raises `DbError` from the next unconditional `set` on
  `-meta`.
- `_RecordingPropertyDb(store)`: appends `(op, name)` to a shared list for
  every write.

Existing-row tests (seed with `_seed_v2_list`, then set `count_hint` to the
seeded length as `test_v2_metadata_cas.py:254-261` does):

- Parametrized over every v2 mutator — `append`, `extend`, `insert`,
  `__setitem__`, `__delitem__`, `pop`, `remove`, `delete_by_handle`,
  `update_by_handle`, `remove_where`, `update_where` — with
  `fail_ops={"set_if_value_equals"}`: the call does not raise, storage holds
  exactly the expected post-state (checked through a fresh instance's
  `to_list()` and a raw scan of item rows), and exactly one WARNING
  containing "backend fault" was logged on `actingweb.property_list`, with
  `record.exc_info` set and the `DbError` message (its operation name) in the
  text.
- `pop()` returns the popped item and its row is gone.
- `remove_where()` with three matches and a fault on every touch returns all
  three removed items; `update_where()` likewise returns all three pre-update
  values.
- `lose_cas_first=1, fail_get_after_cas_losses=True`: attempt 0 loses its
  CAS, attempt 1's re-read raises, the fault is swallowed and the item is
  stored once (pins the retry-read fault path).
- Drift and repair: after a swallowed fault `count_hint` is stale by one,
  `get_metadata()["length"]` is off by one, `verify()` reports
  `count_hint_drift == -1` and stays healthy, and a fresh instance's `pop()`
  against a clean `FakePropertyDb` restores exactness (mirror of
  `test_failed_advisory_touch_leaves_bounded_drift_that_the_next_count_repairs`).
- Boundary, v1: `_seed_list` then `append()` with
  `fail_ops={"set_if_value_equals"}` raises `DbError` (non-advisory), and the
  item row exists (mirror of
  `test_v1_semantic_length_write_still_raises_on_exhaustion`).
- Boundary, semantic v2 write: `set_description()` on an existing row with
  the same fault raises `DbError`.
- Boundary, corruption: `lose_cas_first=1` and a hook that replaces the meta
  row with non-JSON before the retry read: `append()` raises `ValueError`
  even though the touch is advisory.
- `NotifyingListProperty` over a real `ListProperty` on the faulting fake
  with a `Mock` actor: `append()` calls `register_diffs` once with
  `operation == "append"`; `pop()` returns the item and registers `"pop"`;
  `remove_where()` registers one `"remove"` per removed item.

First-mutation tests (empty store):

- Write-order pin with `_RecordingPropertyDb`: the first `append()` on a
  never-created list records `create_if_not_exists(-meta)`, then
  `create_if_not_exists(-#a0)`, then `set_if_value_equals(-meta)`; the stored
  meta row ends with `count_hint == 1`. `extend([])` records nothing.
- Parametrized over `append`/`extend`/`insert` with
  `fail_ops={"create_if_not_exists"}`: raises `DbError`, and the store is
  empty (no item rows, no meta row).
- `_ItemFaultPropertyDb`: `append()` raises `DbError`; the meta row exists
  with `format == 2`, `count_hint == 0`, `format_ever_changed is False`; a
  fresh instance's `to_list() == []`; `(actor_id, "list:{name}-meta")` is in
  the store (what `PropertyListStore.exists()` keys on).
- `fail_ops={"set_if_value_equals"}` on a never-created list: `append("a")`
  does not raise, the item row and the meta row both exist, `count_hint == 0`
  (drift of one), a fresh instance reads `["a"]`; a second `append("b")` on a
  clean store reads `["a", "b"]` with `count_hint == 1` (the drift persists
  through append-only traffic, as documented), and `pop()` then writes the
  counted truth.
- `_ConcurrentCreatorPropertyDb` injecting a v2 row with
  `description == "theirs"` and `count_hint == 4`: `append()` proceeds, the
  item lands, `description` survives and `count_hint` becomes 5.
- `_ConcurrentCreatorPropertyDb` injecting a v1-shaped row (`length`, no
  `format`): `append()` raises `ListMetadataContentionError`, its message
  contains "first-mutation create" and not "sustained contention", and no
  item row was written.
- `_ConcurrentCreatorPropertyDb` returning `False` without injecting (the
  row was created and deleted again inside the window): same raise, same
  message, nothing written.
- `ListMetadataContentionError("notes", "actor-1")` keeps today's message;
  with `detail="…"` the message carries the detail and still ends in "retry
  the request"; `PropertiesHandler._respond_list_metadata_contended` puts
  the detailed text in the 503 body's `detail` (extends the existing handler
  test pattern at `tests/test_v2_metadata_cas.py:179-208`).
- A `get` fault on `-meta` with no CAS loss recorded (a `FakePropertyDb`
  with `fail_get_on={meta_name}`) on a never-created list: `append()` raises
  `DbError` before any write (the dispatch read faults), and the store is
  empty.
- `_ItemFaultPropertyDb` that faults on the 2nd item only: `extend(["a",
  "b", "c"])` on a never-created list raises `DbError`; a fresh instance
  reads `["a"]`; the meta row exists with `count_hint == 0` (the touch never
  ran); `verify()` reports `meta_row_present is True` (Phase 2) and a drift
  of one.
- **CRITICAL regression pin** (the diff changes existing first-mutation
  behaviour and no existing unit test covers the instance-reuse path): on a
  never-created list, one `ListProperty` instance runs `len(lst) == 0`,
  `lst.append(None)`, `len(lst) == 1`, `lst.append(None)`, `len(lst) == 2`,
  then `lst[1] = "x"` and `lst.to_list() == [None, "x"]`, under
  `@pytest.mark.timeout` (pytest-timeout is a dev dependency). This is the
  `handlers/properties.py` bulk-pass loop shape that hung once when the rank
  cache stopped advancing (`_v2_append()` docstring `:1491-1504`);
  `_v2_create_meta_row()`'s `_invalidate_cache()` is exactly the kind of
  change that could reintroduce it. The existing
  `tests/test_v2_append_last_rank.py:124`
  (`test_the_exact_bulk_handler_shape_terminates`) pins the same shape from
  a warm cache; this pin starts from a never-created list and adds the
  positional write after the appends.
- A name containing `#`, and separately a name colliding with a scalar
  property: `append()` raises `ValueError` and the store gained no row.
- Residual with `_DeleteAfterCreatePropertyDb`: `append("a")` does not
  raise, one WARNING containing "backend fault" is logged (the single guard
  at the touch does not know which branch faulted; the `DbError` text names
  the unconditional write), the item row exists and the meta row does not
  (the documented residual), and `verify()` reports it once Phase 2 lands.
- Existing tests that must stay green unchanged:
  `tests/test_property_list_integrity.py::…::test_concurrent_delete_is_not_undone`
  (`:1717-1754`), all of `tests/test_v2_metadata_cas.py`, all of
  `tests/test_property_list_notifications.py`.

**Handler-level, `tests/test_bulk_list_update_handles.py`** (a new class;
this file already drives `PropertiesHandler` against a real backend through
`_run_handler` and `_post_bulk`, `:75-91`, `:289-345`). Fault injection wraps
the `get_property` factory used by `actingweb.property_list` with a proxy
whose `set_if_value_equals` raises `DbError` for names ending in `-meta` and
delegates everything else to the real backend:

- `PUT /properties/{name}?index=1` with the faulting touch returns 204, the
  item at index 1 is replaced (fresh `to_list()`), and `register_diffs` was
  called once for the list.
- Bulk `POST /properties` with three `update`/`append`/`delete` entries and
  the faulting touch returns 200 with every entry applied and none reported
  raced; the response counts match the number of entries.

**www UI, `tests/integration/test_www_list_corruption.py`** (uses the
`www_test_app` fixture, basic auth, a real backend; the fixture runs uvicorn
in a thread of the pytest process, `tests/integration/conftest.py:550-560`,
so a `mock.patch.object` on `ListProperty` reaches the server; the
direct-handler seam `tests/test_v2_cost_library_callers.py:348-375` drives
the www handler class without HTTP and is the fallback if the patch proves
awkward): a new test creates an actor, patches `ListProperty.append` to
raise
`ListMetadataContentionError(name, actor_id, detail="metadata row changed
under a first-mutation create")`, posts the list-item form for a
never-created list, and asserts 503 with `Retry-After: 1` and no item row or
meta row in storage. A second case with the default message (v1 contention)
asserts the same status.

**Integration, `tests/integration/test_property_list_v2.py`** (runs against
real DynamoDB and PostgreSQL via `DATABASE_BACKEND`):

- A brand-new list's first `append()`, a second brand-new list's first
  `extend()` of three items, and a third's first `insert(0, …)` each leave a
  meta row with `format == 2`, `count_hint == len(list)`,
  `format_ever_changed is False`, empty `description`; `exists()` on the
  actor's property list store is `True`; `verify()["healthy"]` is `True`
  and `count_hint_drift == 0`.
- Regression pin (this already holds on master, because
  `_maybe_lazy_migrate()` runs the check before dispatch; the reordering must
  keep it): a first `append()` to a name that collides with an existing
  scalar property raises `ValueError`, and a `get_range` over the list's v2
  item namespace returns nothing, and no meta row exists.

### Verification

Automated:

- [x] `poetry run pytest tests/test_v2_list_mutation_committed.py tests/test_v2_metadata_cas.py tests/test_property_list_integrity.py tests/test_property_list_notifications.py tests/test_property_list.py tests/test_bulk_list_update_handles.py -v` passes
- [x] `poetry run pytest tests/test_v2_append_last_rank.py -v` passes with the two rewritten expectations
- [x] `poetry run pytest tests/integration/test_property_list_v2.py tests/integration/test_property_list_handle_mutators.py tests/integration/test_post_properties.py tests/integration/test_property_list_notifications.py tests/integration/test_www_list_corruption.py -v` passes on DynamoDB
- [x] Same integration files pass with `DATABASE_BACKEND=postgresql` (env per CLAUDE.md)
- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests` and `poetry run ruff format --check actingweb tests` pass
- [x] `make test-all-parallel` passes (run as `poetry run pytest tests/ -n auto --dist loadgroup` directly against the already-running docker-compose test containers, to avoid tearing down containers this session did not start; 3507 passed, 31 skipped, 0 failed)

Manual:

- [x] `grep -n "backend fault" actingweb/property_list.py` shows the new warning text, and `grep -n "never raises this" actingweb/handlers/properties.py` still finds the handler comment (Phase 2 rewrites it; Phase 1 must not leave it silently wrong for longer than the branch lives)

### Implementation Status: Complete

**Deviations:**
- `_v2_extend()`'s "only when `items` is non-empty" guard needed no in-method
  check: `extend()` already returns before dispatch on an empty `items`, so
  `_v2_extend()` (and its unconditional `_v2_create_meta_row()` call) is never
  reached with an empty batch.
- Running the test suite (including the sandboxed shell in this session)
  requires `dangerouslyDisableSandbox: true` for anything touching the
  DynamoDB Local / PostgreSQL test containers on localhost:8001/5433 or the
  `pytest-rerunfailures` plugin's loopback socket bind — both are blocked by
  the default macOS Seatbelt sandbox. The containers themselves were already
  running (started outside this session) and were left running, not torn
  down.

---

## Phase 2: `verify()` reports the orphan state; every text that contradicts the code is corrected; the adjacent finding gets a todo

### Changes

**`actingweb/property_list.py`**

- `_v2_verify()` (`:2578-2658`): the report gains `"meta_row_present":
  stored is not None`, computed from the `_read_meta_row()` result at
  `:2627` **before** the `stored = stored or {}` at `:2628`, which would
  otherwise make the key always `True`. `healthy` becomes
  `max_rank_length < _V2_RANK_WARNING_LENGTH and not (stored is None and
  length > 0)`. A never-created list (no row, no items) stays healthy. The
  `verify()` docstring (`:2660-2710`, v2 key list in `_v2_verify`'s
  docstring) documents the key and the new `healthy` clause: "item rows with
  no meta row are invisible to `exists()`/`list_all()` and are swept as
  residue by the next `delete()`/`clear()`/`migrate_to_v2()`; the next
  mutation through `ListProperty`, or `compact()`, recreates the row". The
  v1 report shape is unchanged.
- Class docstring (`:303-323`): no wording change needed (it already lists
  the backend-fault term); add one sentence that a v2 mutator that returns
  has committed its item write, and the metadata touch can neither fail it
  nor be the reason it raised.

**`actingweb/handlers/properties.py:797-803`**: the comment "A v2 list's
metadata touch is advisory and never raises this" becomes "A v2 list's
metadata touch is advisory: it swallows contention and backend faults alike,
so a v2 mutation that reaches this handler's `except` did not commit an item
row (the only v2 raise on this path is the pre-write
`ListMetadataContentionError` from a lost meta-row create, which is safe to
retry)".

**`docs/guides/property-lists.rst`**

- `:158-168`: the third drift term becomes "plus one per mutation whose
  advisory metadata touch failed (contention that outlasted its retries, or a
  backend fault after the item write) since the last rank-counting
  mutation".
- New short subsection after the drift bound, "What a returned mutation
  guarantees", worded to exactly what the code keeps:
  - once a v2 mutator returns, its item write is committed, and a fault in
    the metadata bookkeeping can neither fail it nor be the reason it raised;
  - a v2 mutator that raises `DbError`, `RuntimeError` or
    `ListMetadataContentionError` did not commit its item row. Two facts
    about the *meta* row go with that: a raise on a list's first mutation
    may still have created the list (an item-write fault after the meta
    create leaves an empty, visible list, which a retry then appends to);
    and a *return* may, in one rare race (a `delete()` sweep between the
    meta create and the item write, followed by a fault on the recreation
    write), leave the committed item without a meta row, logged as a WARNING
    and reported by `verify()`;
  - a `ValueError` is not covered by that sentence: an unparsable metadata
    row read on a CAS retry, or a scalar property created under the list's
    name between dispatch and the touch, raises after the item write by
    design (corruption and name collisions stay visible), and the REST
    handlers map it to 400;
  - `extend()`, `remove_where()` and `update_where()` are batches: a raise
    part-way through means the earlier items landed, exactly as today;
  - none of this makes retrying a *raised* mutation safe in general, and
    the todo from this phase says why.
- `:182` area (`verify()` keys): document `meta_row_present` and the orphan
  `healthy: False` clause.

**`CHANGELOG.rst`**, under "Unreleased", a FIXED section with three entries in
the house style (what a consumer saw, why, what changed):

1. **A v2 list mutation could raise after its item write had committed.**
   Symptom (retry duplicates a save / `not_found`s a delete / loses a move),
   cause (advisory touch swallowed contention only), fix (backend faults now
   logged at WARNING and swallowed on every v2 item mutator, including
   `pop()` keeping its item, `remove_where()`/`update_where()` keeping partial
   results, and `NotifyingListProperty` still registering its diff).
   **Behavior change:** a v2 mutation whose metadata touch hits a backend
   fault now returns success and logs one WARNING instead of raising; the
   advisory `count_hint` may be off by one until the next rank-counting
   mutation or `compact()`.
2. **A list's first mutation could leave item rows with no meta row.** Fix
   (meta row created conditionally before the first item write; the one
   remaining way to get an orphan is a `delete()` racing the first mutation
   while the recreation write also faults, which is logged and which
   `verify()` now reports).
   **Behavior change:** a fault on the item write of a list's first
   `append()`/`extend()`/`insert()` now leaves an empty, visible list where it
   previously left nothing; a lost meta-row create (another writer created
   the row first and it is not v2) raises `ListMetadataContentionError`
   before any item write, mapped to 503 with `Retry-After`.
   `ListMetadataContentionError` gains a keyword-only `detail` argument
   (default `None`, existing message unchanged) so that raise says what
   happened. The browser UI's list-item form (`/{actor_id}/www/properties`)
   now maps that error to 503 with `Retry-After` too, where it previously
   rendered a 500 "Error processing list item"; that also covers the v1
   contention raise the UI never mapped.
3. **`verify()` called an orphaned v2 list healthy.** **Behavior change:**
   the v2 report gains `meta_row_present`; `healthy` is `False` when item
   rows exist without a meta row.

   Plus one sentence under entry 1: retrying a *raised* mutation is still not
   safe in general, because a timed-out conditional write retried by the SDK
   can report `False` for a write that landed; tracked in
   `thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md`.

**`thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md`** (new):
provenance (found during the 2026-09-14 triage, traced not reproduced), the
mechanism (botocore standard-mode retry of a timed-out `PutItem`/`DeleteItem`;
the retry's `ConditionalCheckFailedException` becomes `False` at
`dynamodb/property.py:588-593` and `:612-617`), the consequences
(`_v2_append` writes the item again under the next rank; `_v2_pop` removes
two items and returns the second; `delete_by_handle`/`update_by_handle`
report `False` for their own write), the two fix shapes (read-back on
`False`, or an idempotency token where one exists), and what has to be
decided first (whether PostgreSQL has an equivalent; whether to reproduce
before fixing).

**`thoughts/todo/meta-row-create-unconditional-for-description-writers.md`**
(new): `set_description()`/`set_explanation()` (`property_list.py:1104-1116`)
create a missing meta row through `_save_metadata`'s creation branch, whose
write is an unconditional `set` (`:846`, `:978-982`). After this plan a first
`append()` creates the row conditionally, so a `set_description()` racing it
can land over the created row and reset `count_hint` from 1 to 0 (the
description is never lost; the next rank-counting mutation repairs the hint).
What it would buy: every meta-row creation conditional, one creation path.
What to decide first: whether the shared creation branch (also used by the
v1 writers with `create_if_absent=False`, and by `clear()`'s replace) should
route through `_v2_create_meta_row()` or grow its own conditional create.
Depends on this plan having landed.

**`thoughts/todo/INDEX.md`**: rows for both new todos under "2. Real, not
urgent".

### New Tests, both unit and integration tests

**`tests/test_v2_list_mutation_committed.py`** (same file as Phase 1), a
`TestVerifyReportsOrphanState` class:

- v2 items seeded with no meta row: `verify()` returns
  `meta_row_present is False`, `healthy is False`, `count_hint is None`,
  `length == 3`.
- A never-created list: `meta_row_present is False`, `healthy is True`,
  `length == 0`.
- A normal v2 list: `meta_row_present is True`, `healthy is True`.
- After the orphan is repaired by `compact()` (or by any mutation),
  `meta_row_present is True`.

**Integration, `tests/integration/test_verify_property_lists_script.py`**:
one test that the maintenance script's output is unaffected by an orphan
under a name it never enumerates (seed item rows directly through the
backend with no meta row; run the script; it reports the other lists as
before and exits 0). Pins the claim in the changelog that no automated
consumer changes outcome.

Docs: `poetry run sphinx-build -W --keep-going . _build/html` (the root
`Makefile` is the Sphinx makefile; this is the command CI runs at
`.github/workflows/tests.yml:543`, and `-W` turns any new autodoc warning
from the rewritten docstrings into a failure).

### Verification

Automated:

- [x] `poetry run pytest tests/test_v2_list_mutation_committed.py tests/integration/test_verify_property_lists_script.py -v` passes
- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run sphinx-build -W --keep-going . _build/html` succeeds, modulo one PRE-EXISTING warning
      (`docs/sdk/authenticated-views.rst:197: unknown document: '/guides/property-lists'`)
      unrelated to this plan and confirmed present before Phase 1's commit too — not fixed here, out of scope
- [x] `make test-all-parallel` passes (run as `poetry run pytest tests/ -n auto --dist loadgroup` directly, same
      reasoning as Phase 1; 3512 passed, 31 skipped, 0 failed)

Manual:

- [x] `grep -rn "never raises this" actingweb/` returns nothing
- [x] `grep -n "backend fault" docs/guides/property-lists.rst actingweb/property_list.py` finds the guide's third term, the class docstring and the warning
- [x] `grep -n "retry" CHANGELOG.rst` under Unreleased shows the "not safe in general" sentence

### Implementation Status: Complete

**Deviation:** the full-suite run surfaced one pre-existing test
(`tests/test_v1_maintenance_scoped_reads.py::TestV2ListsAreUntouched::
test_v2_verify_still_reports_the_same_way`) that asserted `verify()`'s v2
report via exact dict equality. Not anticipated by the plan's test-gap
review. Updated to include the new `meta_row_present: True` key rather than
loosening the equality check, since exact-shape pinning is this test's whole
purpose.

---

## Phase 3: Release 3.14.7

### Changes

Per CLAUDE.md's release process, on the same PR branch:

- `pyproject.toml` `version = "3.14.7"`; `actingweb/__init__.py`
  `__version__ = "3.14.7"`.
- `CHANGELOG.rst`: rename "Unreleased" to `v3.14.7: <date>`, add a new empty
  "Unreleased" above it.
- Delete `thoughts/todo/v2-list-mutation-raises-after-its-write-committed.md`
  and its row in `thoughts/todo/INDEX.md` (the work has landed; this plan and
  its verification are the record). In
  `thoughts/todo/v2-list-access-verification-followups.md`, delete the
  "`www.py` HTML UI has no `ListMetadataContentionError` handler" bullet
  (Phase 1 closes it); the line about the backend-level `DbError` seam
  stays.
- Commit `Release v3.14.7`, push, open the PR (body ends with the session's
  attribution lines), merge when CI is green on both backends, then on
  master: `git pull`, `git tag v3.14.7`, `git push --tags`.

### New Tests, both unit and integration tests

None. The release phase adds no behaviour. The full suite runs in CI on both
backends before merge and again on the tag.

### Verification

Automated:

- [x] `grep -n "3.14.7" pyproject.toml actingweb/__init__.py` shows both files
- [x] `git diff master --stat -- thoughts/todo/` shows the todo deleted and the INDEX row gone
- [ ] CI green on the PR for DynamoDB and PostgreSQL — pending, PR just opened
- [ ] The tag workflow publishes to PyPI and creates the GitHub Release — pending merge + tag

Manual:

- [ ] `pip index versions actingweb` (or the PyPI page) lists 3.14.7 — pending
- [ ] The consumer (`actingweb_mcp`) is told the release closes their
  `list-mutation-reported-failed-after-commit` todo for the reported
  mechanism, and is pointed at the new SDK-retry todo for what it does not
  close — pending

### Implementation Status: In Progress

**Deferred by explicit user choice (2026-09-14):** version bump, CHANGELOG
rename, todo cleanup, and the release commit are done, and the branch is
pushed with a PR opened. Merging the PR, tagging `v3.14.7` on master, and
notifying the consumer are left to the user — those are the shared/
publishing actions the session stopped short of on request.

---

## Evaluation Notes

From `/plan-eng-review` (Codex was unavailable: the installed CLI rejects the
configured model; the outside voice ran as a fresh-context Claude subagent).

### Architecture

- The swallow's boundary was the one design question with two defensible
  answers. Resolved: one guard in `_v2_touch_metadata()`, the single
  `advisory=True` caller, rather than three guards inside `_save_metadata`.
  `_save_metadata` stays byte-identical in code.
- The first-mutation ordering reuses primitives that already exist on both
  backends (`create_if_not_exists`) and the stash mechanism
  `_dispatch_and_stash()` already provides; the only new state is the
  re-stash after a successful create, which is what keeps the touch on the
  CAS path.
- Realistic production failure per new path, and whether the plan covers it:
  a throttled `create_if_not_exists` on the meta row raises before any write
  (covered, safe to retry); a throttled item write after the meta create
  leaves an empty visible list (covered, documented behaviour change); a
  throttled touch leaves a one-item list with hint drift (covered, the
  headline fix); a `delete()` sweep landing between the two writes plus a
  fault on the recreation leaves the residual orphan (covered, WARNING names
  it, `verify()` flags it after Phase 2).
- The lost-create raise reuses `ListMetadataContentionError` so the handlers'
  503 mapping applies unchanged; the message now says what happened.

### Security

- No authentication, authorization or data-exposure surface changes. The
  only new text that can reach a response body is the `detail` clause of the
  503, which carries the list name and actor id exactly as today's message
  does. WARNING logs carry the backend exception chain via `exc_info`, which
  is the same sanitized `DbError` plus the driver's original error that
  already reaches logs on the raise path.

### Scalability

- One extra conditional write per list creation; no per-mutation cost on
  existing lists. One cold rank-cache reload on the first mutation for an
  instance reused across it. No new range queries, no new N+1. The WARNING
  path adds a log record with a traceback under sustained backend trouble,
  which is when the four SDK retries have already been spent.

### Usability

- A library caller's contract becomes statable in one sentence: a v2
  mutator that returns has committed; one that raises has not, with the two
  documented first-mutation exceptions. The guide gets that sentence.
- The consumer's retry-once envelope stops manufacturing duplicates for the
  reported mechanism. The changelog says in plain words that it does not make
  retrying a raised mutation safe in general, and points at the SDK-retry
  todo.
- `verify()`'s new key is additive; `healthy: False` for an orphan is a
  behaviour change and is called out as one.
- The browser UI's list-item form maps the contention error to 503 like the
  JSON handlers, instead of a 500.

### What already exists and is reused

- The advisory swallow in `_save_metadata` (`:924-935`) is the shape the
  fault swallow copies, one level up at the touch.
- `create_if_not_exists` on both backends is the conditional primitive the
  meta-row-first create uses; no new protocol method.
- `_dispatch_and_stash()`'s stash is how the touch CASes on the created
  bytes; the create only rewrites the stash.
- `FakePropertyDb` and its patch helper are the fault-injection seam; the
  new doubles subclass it.
- `_v2_verify` already reads the meta row raw; the new key is computed from
  that read.
- `handlers/properties.py`'s `_respond_list_metadata_contended` and
  `www.py`'s existing 503 branches are the response shapes reused.
- Nothing is rebuilt.

### Failure modes (one per new path)

| Path | Production failure | Test | Handling | User sees |
| --- | --- | --- | --- | --- |
| Touch guard | throttle on the CAS write after the item landed | parametrized x11, handler pins | swallowed, WARNING | success |
| Touch guard, retry read | throttle on the re-read after a CAS loss | retry-read test | swallowed, WARNING | success |
| Meta create | throttle on `create_if_not_exists` | fail-create x3 | raises, nothing written | 500 from `DbError` (as today for any pre-write fault) |
| Meta create lost | two first-writers, row not v2 | v1-row / absent-row tests, www test | `ListMetadataContentionError(detail=)` | 503 + Retry-After (JSON and www) |
| Item write after create | throttle on the item write | item-fault test | raises; empty visible list | 500, list exists and is empty |
| Residual | `delete()` sweep between the writes plus a fault on recreation | residual test, `verify()` test | swallowed, WARNING; `verify()` flags | success; orphan visible to `verify()` |
| `verify()` orphan | none new (read-only) | 4 cases | n/a | `meta_row_present: False`, `healthy: False` |

No critical gaps: every row has a test, handling, and a non-silent outcome.

### Parallelization

Sequential implementation, no parallelization opportunity: every Phase 1
change touches `actingweb/property_list.py` or tests that patch it; Phase 2
edits the docstrings Phase 1 wrote; Phase 3 is the release.

### Implementation tasks (synthesized from the review)

- [ ] **T1 (P1)** — `property_list.py` — one `try/except (DbError, RuntimeError)` in `_v2_touch_metadata`, WARNING with `exc_info`; docstrings. Verify: parametrized mutator tests.
- [ ] **T2 (P1)** — `property_list.py` — `_dispatch_saw_no_row()`, `_v2_create_meta_row()` with the diagram docstring, calls from the three creating mutators. Verify: write-order pin, lost-create tests, regression pin.
- [ ] **T3 (P1)** — `property_list.py` — `ListMetadataContentionError(detail=)`. Verify: message tests, handler 503 body test.
- [ ] **T4 (P1)** — `handlers/www.py` — contention → 503 in the list-item block. Verify: www integration test.
- [ ] **T5 (P1)** — `tests/test_v2_append_last_rank.py` — the two rewritten expectations. Verify: file passes.
- [ ] **T6 (P1)** — `tests/test_v2_list_mutation_committed.py`, `tests/test_bulk_list_update_handles.py`, `tests/integration/test_property_list_v2.py` — every test in Phase 1's list. Verify: Phase 1 commands.
- [ ] **T7 (P2)** — `property_list.py` `_v2_verify` — `meta_row_present` before `or {}`, `healthy` clause. Verify: 4 cases + script integration test.
- [ ] **T8 (P2)** — docs guide, handler comment, class docstring, CHANGELOG. Verify: `sphinx-build -W`, greps in Phase 2.
- [ ] **T9 (P2)** — two new todos + INDEX rows. Verify: `ls thoughts/todo`.
- [ ] **T10 (P2)** — release 3.14.7 per Phase 3.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found (Claude subagent; Codex CLI rejected its model) | 9 findings, all verified, all resolved by decisions D10–D12 |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 12 issues (2 architecture, 2 code quality, 8 test gaps incl. 1 regression, 0 performance), 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CROSS-MODEL:** the outside voice (same model family, fresh context) agreed the code design holds and found nine plan-level defects the section review missed: two existing tests that would break, two specified tests that could not pass, a non-existent docs command, an always-true `meta_row_present`, three over-claims, and a new 500 in the www UI. All nine were verified against the tree and folded in by explicit decision; the www mapping widened Phase 1 by one handler change and one test.
- **VERDICT:** ENG CLEARED — ready to implement (`status: proposed` until implementation starts).

NO UNRESOLVED DECISIONS
