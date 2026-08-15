---
status: done
---

# Implementation Plan: List metadata integrity and rewrite convergence

**Date:** 2026-08-15
**Supersedes (same day, never implemented):** a lease-row design and a
stage-and-flip design, both cut under adversarial review — see "Designs cut"
**Todos:** `thoughts/todo/migrate-to-v2-needs-a-claim.md` (closed by an accepted
trade), `thoughts/todo/v2-compact-staged-commit.md` (deferred to 3.14, re-filed
as `thoughts/todo/whole-list-rewrite-atomicity.md`)
**Prior plan in this thread:** `thoughts/plans/2026-08-08-property-list-index-integrity.md`
**GA scoping:** `thoughts/todo/INDEX.md` §0
**Branch:** master (not yet cut)

## Overview

Three rounds of adversarial review of two candidate designs for crash-safe
whole-list rewrites produced one finding far more severe than the crash windows
they set out to close, and it needs no new design at all: **a concurrent
`append()` can write stale cached metadata back over a completed migration,
reverting the format flip and destroying the entire list.** This plan lands that
fix, plus the convergence bugs the same reviews surfaced, and defers `compact()`
crash atomicity to 3.14 with the design constraints now on file.

The deferred half is not being abandoned quietly: rc6 already documents the
`compact()` crash window honestly, the damage it describes is *visible* in the
data, and `verify()` catches it. That is a materially better position than
shipping a design that failed review twice under GA time pressure.

## Decisions Made

- **Ship the metadata fix, defer the atomicity fix.** The stale-metadata
  write-back is total silent loss on ordinary traffic and is closed by a
  contained change. `compact()`'s crash window is documented, visible, and
  detectable. Fixing the second badly is worse than deferring it.

- **Row 1 (`migrate_to_v2()` needs a claim) is closed by an accepted trade.**
  Two concurrent migrations already resolve to clean list-granularity
  last-writer-wins — step 3 clears the v2 range before writing, so the loser's
  snapshot does not mix with the winner's. What row 1 objects to is that the
  winner can be the *older* snapshot. We accept that: Phase 1 removes the
  **unbounded** variant of the window (the stale cache), the existing double-read
  at `property_list.py:1908-1929` holds the rest to two adjacent queries, and the
  residue is documented rather than locked.

- **No mutual exclusion, no lease, no journal, no namespace marker.** Each was
  designed and cut; see below.

- **`length` stays authoritative for v1 and absent for v2.** Several reviewed
  failures traced to `length` being an absolute value merged into metadata by a
  writer that computed it against a different view. Phase 1 constrains who may
  write it rather than changing what it means.

### Designs cut

Recorded because this repo keeps what it decided against, and because both
failures constrain the 3.14 work.

**A lease row (`list:{name}-lock`) as claim plus recovery journal.** Cut: both
candidate journal payloads destroy data that today's journal-less re-run
preserves. v1 — sources `[1,2,3,4]`, targets `0..3`, rows `1:b 2:c 3:d 4:e`;
write `0:=b`, write `1:=c`, crash; resume re-reads sources → `[c,c,d,e]`, **`b`
destroyed**, where a re-run today yields `[b,c,c,d,e]` with the duplicate
visible. v2 — the "rank ∈ `generate_n_keys_between(None,None,n)`" classifier
deletes every uncopied row for a list built by repeated `insert(0,…)`, and where
old ranks *are* in the target set (why the nudge branch at :1659-1672 exists) it
keeps stale rows as authoritative and silently permutes the list.

**Stage-and-flip (build a copy in an inactive namespace, commit with one
metadata write).** Its core claim held — single-runner crash atomicity, clean v2
crash matrix at all four steps, re-run convergence, and the rank-collision retry
loop becomes unnecessary. Cut on three findings:

1. *No concurrency required.* Alternating slots mean a compacted list **rests**
   on the scratch marker, so `--repair` leaves about half of all repaired v1
   lists at `{format:1, item_marker:"%"}`. `migrate_to_v2()`'s commit never
   writes `item_marker` → `{format:2, item_marker:"%"}`, and surviving `%{i}`
   rows read as v2 items (`_v2_is_rank("0")` is True — digits are base62)
   sorting `0,1,10,11,2,…`: **silently permuted, `verify()` reports healthy.**
   The exact failure the lease design was rejected for.
2. *New invisible failure on the default backend.* `fetch_all_including_lists`
   is a paginated DynamoDB `Query`, not a snapshot. Sort order puts the scratch
   range first and `-meta` last, so one dump can miss the staged rows and pick
   up the flipped marker: `GET /properties/<list>` returns **200 with an empty
   array**, single writer. Today the same skew yields duplicates — visible, and
   caught by `verify()`. PostgreSQL is immune (single `SELECT`, one MVCC
   snapshot). **This rules out any scheme that stores "which namespace is live"
   in the item partition**, which is the most valuable constraint the review
   produced.
3. *Cache-derived namespaces.* Making the marker come from `_meta_cache` turns a
   stale cache from a wrong-format problem into a wrong-namespace one: `len()` →
   0, `to_list()` → `[]` with no error, `append()` into a dead namespace.

## What We're NOT Doing

- **`compact()` crash atomicity** — deferred to 3.14, re-filed with all three
  reviews' constraints as `thoughts/todo/whole-list-rewrite-atomicity.md`.
  rc6's documentation of the window stands.
- **Mutual exclusion between whole-list rewrites.** A concurrent write during an
  operator rewrite can still be lost. The docs' existing "run repair when the
  actor is not taking writes" advice stays and gains a sentence on what is and
  is not excluded.
- **A CAS / `conditional_update` primitive on `DbProperty`.** Needed only by the
  cut designs. Precedent exists at `db/protocols.py:925-950`
  (`DbAttributeProtocol.conditional_update_attr`) if 3.14 wants it.
- **`ListAttribute`** — INDEX row 4, decided to sequence after this thread. 3.14.

---

## Phase 1: Stop stale metadata from being written back

The most severe finding across all reviews, previously unfiled.

During a migration, a concurrent `append()` calls `_load_metadata()` (cached v1
dict, no `format` key), increments `length`, and `_save_metadata()` writes that
dict back unconditionally at `property_list.py:405-407` — **reverting the
migration's `format: 2` flip.** Metadata then says format 1 while every real item
lives in v2 rows nothing reads, and migration's step 6 deletes the v1 rows. Total
silent loss. `clear()` and `delete()` have the same shape: a cleared list
resurrects with all its items. The window is one round trip for a fresh
`ListProperty` and **unbounded** for any instance an application retains, because
`_meta_cache` clears only on an explicit `_invalidate_cache()`.

### Changes

- `actingweb/property_list.py` — `_save_metadata()` (:396-410) becomes
  read-modify-write against a **fresh** read of the meta row, merging only the
  fields the caller names. `format` is never carried from a cached dict.
- `actingweb/property_list.py` — audit all 11 call sites (:512, :524, :660, :723,
  :809, :882, :917, :933, :1229, :1774, :1964); convert each to naming the fields
  it changes. The read-modify-write ones are the v1 mutation paths (:723, :809,
  :882, :1229) and `_v2_touch_metadata` (:660).
- `actingweb/property_list.py` — `_v2_touch_metadata()` (:646-660) round-trips
  the whole cached dict to bump `updated_at`; make it a fresh-read-merge or drop
  it if nothing depends on the bump.
- `actingweb/property_list.py` — `migrate_to_v2()` aborts if the meta row has
  **vanished** mid-run (list deleted concurrently) rather than recreating it from
  `_create_default_metadata_v2()` at :1961.
- `actingweb/property_list.py` — `_invalidate_cache()` (:412-414) also clears
  `_v2_rank_cache` (:207). The two are already semantically coupled and nothing
  enforces it.

**Known residual, stated rather than hidden:** v1 `append()` derives its new
`length` from `len(self)` (:860), which reads `_meta_cache`, not storage. So a
retained instance can still write a stale absolute `length`. Phase 1 fixes the
write side; the read side is bounded by the same quiesce advice the docs already
carry, and is re-filed with the 3.14 work.

### New Tests

- Unit (fake DB, `tests/test_property_list_integrity.py` style): interleave a
  cached-v1 `append()` against a completed migration; assert metadata still reads
  `format: 2` and no item is lost.
- Unit: the same interleaving for `clear()` and `delete()`; a cleared list stays
  cleared.
- Unit: a `ListProperty` retained across operations does not resurrect its cached
  `format` on a later operation.
- Unit: `migrate_to_v2()` against a list whose meta row was deleted mid-run
  refuses rather than recreating metadata.
- Unit: `_invalidate_cache()` clears both caches.
- Integration (both backends): concurrent `append()` + `migrate_to_v2()`.

### Verification

- [x] `poetry run pytest tests/test_property_list_integrity.py tests/test_property_list.py -v` passes
- [x] `poetry run pytest tests/integration -k property_list -v` passes on both backends
- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests` passes

### Implementation Status: Complete

**Deviations and notes.**

- **`_save_metadata()` kept its name and gained a sibling.** It is now
  `_save_metadata(updates, *, remove=(), create_if_absent=True)` — merge into a
  fresh read. The wholesale write it used to be lives on as
  `_replace_metadata(meta)`, documented as usable only by a deliberate reset
  (`clear()`) or by a caller that derived the dict from a read it just did
  (migration's step 5). Keeping the safe form under the name callers reach for
  is the point: adding a *new* safe method would have left the footgun as the
  default.
- **Absent-meta-row policy is per-caller, not global** (`create_if_absent`).
  The v1 length writers (`append`, `insert`, `__delitem__`, `__setitem__`,
  `compact`) SKIP the write when the row is gone: an absent row means a
  concurrent `delete()` won, and merging a stale length there recreates the
  list. `set_description`/`set_explanation`/`_v2_touch_metadata` still create,
  because that is the list-creation path and the whole purpose of the touch.
- **`clear()` and `delete()` now re-read the format before dispatching**, which
  the plan did not list. Both branches end in a wholesale metadata write, so a
  stale v1 cache over migrated storage put `_create_default_metadata()` over a
  live v2 list's meta row while its rows stayed put — the same format revert
  this phase exists to kill, arriving through the replace path rather than the
  merge path. Two point reads, two methods; not generalised to other mutations.
- **The vanished-meta-row abort had to roll back step 4.** By the time step 5
  discovers the row is gone, the full v2 rank set is already written. Returning
  there left v2 rows with no meta row: invisible to `exists()`/`list_all()`, and
  read as items by the next list created under that name. The abort now deletes
  the rows it wrote and returns `reason: "deleted_concurrently"`, which
  `migrate_actor()` reports without counting as a refusal (the `else` branch
  would otherwise have labelled it `"rename required"` and blocked checkpointing
  forever).
- **A metadata write now refreshes the instance's cache as a side effect**,
  because it caches what it read. So a retained stale instance is wrong for at
  most one mutation rather than indefinitely. Falls out of the fix; the test
  pins it.
- The known residual (v1 `append()`/`insert()` deriving `length` from
  `len(self)`, which reads the cache) is unchanged and is now recorded in the
  `ListProperty` class docstring as well as in
  `thoughts/todo/whole-list-rewrite-atomicity.md`.

---

## Phase 2: Make interrupted rewrites converge on re-run

Independent of Phase 1; either can land first.

Both format-changing rewrites leave permanent residue after a crash, because the
re-run early-returns before reaching its own cleanup — and `migrate_to_v2()`'s
docstring claims the opposite.

### Changes

- `actingweb/property_list.py` — **new** `sweep_foreign_format_rows()`: a
  bounded, shape-filtered range read for the *other* format's rows, deleting
  what it finds and returning the count. One primitive serves all four call
  sites below. It must be a `get_range()`, **not** a
  `fetch_all_including_lists()` partition dump — the script deliberately avoids
  those (`migrate_property_lists.py:202-205`, "~13 partition dumps per actor").
  v1 rows are bounded by `[list:{name}-0, list:{name}-:]` (`:` is 0x3A, just past
  `9`); v2 rows by the existing `_v2_bounds()`. Each needs its own shape filter —
  `^\d+$` on the suffix for v1, the existing `_v2_is_rank()` for v2 — or the
  sweep deletes a sibling list's rows, the hazard `_v2_item_names_in_range()`'s
  docstring (:889-896) exists to prevent.
- `actingweb/property_list.py` — `migrate_to_v2()`'s `already_v2` early return
  (:1863-1864, :1929) calls it before returning. Today a crash after step 5
  leaves `list:{name}-{i}` rows forever: the re-run returns at :1863 and never
  reaches step 6.
- `actingweb/maintenance/migrate_property_lists.py:212-213` — **the load-bearing
  one.** `migrate_actor()` does `if already_v2: continue`, so after an
  interrupted migration the list reads format 2 and the bulk script skips it
  entirely, never calling `migrate_to_v2()` at all. Under `--migrate`, the
  `already_v2` branch must call `sweep_foreign_format_rows()` rather than
  `continue`. Without this the fix above is unreachable from the path operators
  actually run, and this phase's manual verification would fail while its unit
  test passed.
- `actingweb/property_list.py:1812-1815` — the docstring states a re-run
  "finishes the cleanup safely". It does not. Fix with the behaviour.
- `actingweb/maintenance/migrate_property_lists.py` — `downgrade_to_v1()`'s
  `not_v2` early return (:321-322) calls it before returning. This half is
  already reachable: re-running `--downgrade` does invoke `downgrade_to_v1()`.
- `actingweb/property_list.py` — `clear()` (:905) and `delete()` (:935) call it
  too, so both sweep **both formats'** namespaces regardless of the list's
  current `format`. A crashed rewrite is exactly the state where the current
  format does not tell you which rows exist; today a deleted list's cross-format
  residue resurrects inside a freshly created list of the same name, because
  `exists()`/`list_all()` key off the meta row (`property.py:20-52`) and report
  the list absent.
- `actingweb/property_list.py` — `verify()` reports cross-format residue
  informationally: present in the report but **not** counted against `healthy`,
  matching v2's informational duplicate reporting (`_v2_verify`, :1432-1444), not
  v1's, where duplicates do fail `healthy` (:1577-1579).

### New Tests

- Unit: `sweep_foreign_format_rows()` leaves a legacy sibling list's rows alone
  in both directions — a list named `foo-5` while sweeping `foo`'s v1 range, and
  a legacy `#`-named sibling while sweeping `foo`'s v2 range.
- Unit: crash `migrate_to_v2()` after the metadata flip; re-run; assert v1 rows
  are gone and the list is healthy.
- **Script-level:** crash a migration, then run `migrate_actor()` (not
  `migrate_to_v2()` directly) and assert the residue is swept. This is the test
  that would have caught the `already_v2: continue` gate.
- Unit: crash `downgrade_to_v1()` after the metadata flip; re-run; assert v2 rows
  are gone.
- Unit: delete a list carrying cross-format residue, recreate it under the same
  name, assert the new list is empty. Pins the resurrection trace.
- Unit: `verify()` reports cross-format residue without failing `healthy`.
- Integration (both backends): interrupted migrate, then the bulk script's
  re-run, converges.

### Verification

- [x] `poetry run pytest tests/test_property_list_integrity.py -v` passes
- [x] `poetry run pytest tests/integration -k "property_list or migrate" -v` passes on both backends
- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] Manual: interrupted a real `migrate_to_v2()` at the format flip against
  dynamodb-local, then re-ran `migrate_actor(migrate=True)` — the bulk script's
  path, not the method directly. Output: `swept 4 v1 row(s) left by an
  interrupted migration`; list intact, description preserved,
  `foreign_format_rows` back to 0

### Implementation Status: Complete

**Deviations and notes.**

- **`sweep_foreign_format_rows()` takes no argument.** "Foreign" is defined as
  *not the format the stored metadata row currently reports*, which makes one
  parameterless primitive serve all four call sites: migration's `already_v2`
  path sweeps v1, downgrade's `not_v2` path sweeps v2, and `clear()`/`delete()`
  get both namespaces because their existing native branch already handles the
  format the list is in. When there is no meta row at all, both are swept.
- **The format is re-read from storage inside the sweep, always.** This is
  load-bearing rather than defensive: a stale v1 cache over v2 storage would
  classify every live row as foreign and delete the list. Tested.
- **v1 needed a range read that did not exist.** `_v1_bounds()` (`-0` to `-:`)
  plus `_v1_item_names_in_range()` with the `^\d+$` suffix filter the plan
  specified. The filter is not cosmetic: a sibling list named `foo-5` stores
  `list:foo-5-0`, which sorts inside list `foo`'s range. Both sibling hazards
  (`foo-5` for v1, legacy `foo-#bar` for v2) have regression tests. The
  now-existing v1 range read is recorded in the 3.14 todo, whose constraint
  list said one would have to be built.
- **`downgrade_to_v1()`'s `not_v2` return gained a `swept_v2_rows` key**, which
  changed one existing integration assertion (`test_downgrade_v1_list_is_a_noop`
  compared the dict exactly). Updated, with the reason.
- `verify()` reports `foreign_format_rows` in both formats. The v1 path counts
  it from the partition dump it already has; only the v2 path pays an extra
  (keys-only) range read.
- Both convergence tests were confirmed non-vacuous by neutering the fix and
  watching them fail — including the script-level one, which is the test that
  would have caught the `already_v2: continue` gate.

---

## Phase 3: Documentation and todo closure

### Changes

- `docs/migration/v3.13.rst` and `docs/guides/property-lists.rst` — the rc6
  warning boxes about `compact()` not being crash-safe **stay accurate and stay
  put**. Add one sentence to each saying what is and is not excluded during a
  rewrite, so nobody reads the other fixes as making quiescing unnecessary.
- `docs/reference/` or the property-lists guide — document the accepted
  last-writer-wins trade for concurrent whole-list rewrites (row 1's decision).
- `CHANGELOG.rst` — Unreleased entry covering Phases 1 and 2. Phase 1 warrants
  prominence: it is a total-loss bug on ordinary traffic.
- `thoughts/todo/migrate-to-v2-needs-a-claim.md` — delete once the accepted-trade
  reasoning is in `docs/`.
- `thoughts/todo/v2-compact-staged-commit.md` — delete; superseded by
  `thoughts/todo/whole-list-rewrite-atomicity.md`.
- `thoughts/todo/INDEX.md` — rows 1 and 2 out, the new atomicity todo in, §0
  retiered.

### Verification

- [x] Docs build clean (`-W`, matching CI)
- [x] Full sequential suite passes (see Implementation Summary)

### Implementation Status: Complete

**Deviations and notes.**

- The last-writer-wins trade went into `docs/guides/property-lists.rst` under a
  new "Concurrency during a whole-list rewrite" heading, not `docs/reference/` —
  it belongs next to the `compact()` warning box a reader has just been through,
  and the guide is where the repair/migration workflow already lives.
- The migration guide's addition names the boundary explicitly: nothing excludes
  a concurrent write, so the quiesce advice stands; what is now guaranteed is
  that such a write cannot change the list's storage format.
- `thoughts/todo/INDEX.md` numbering is deliberately **not** re-flowed after
  removing rows 1 and 2. Too many rows cite each other by number for renumbering
  to be a cheap edit, so the gap is explained in the header instead. §0's "Gates
  GA" tier is retitled rather than deleted — it records why the release was held
  and what was accepted in exchange, which a git log does not.
- Two dangling links to the deleted todos were repaired
  (`property_list.py`'s `_v2_compact()` docstring and
  `thoughts/todo/attribute-list-shift-design.md`). The references inside
  `thoughts/verifications/2026-08-09-*` were left alone: a verification is a
  dated record of what was true when it was written.

---

## Evaluation Notes

Five review passes fed this plan: four evaluators (architecture, security,
scalability, usability) against the lease design, and one adversarial pass
against stage-and-flip. Findings that died with their design are recorded under
"Designs cut" rather than here.

**Carried into this plan:** the stale-metadata write-back (Phase 1, from the
security pass); the re-run non-convergence of both format-changing rewrites and
the resurrect-on-recreate trace (Phase 2, from the adversarial pass);
`_invalidate_cache()` not clearing `_v2_rank_cache` (Phase 1).

**Carried into the 3.14 todo:** the DynamoDB pagination constraint; the
`length`-as-absolute-value problem; the need for CAS if any commit protocol is
attempted; v1's lack of a range read and the `^\d+$` shape filter a v1 range
sweep would need.

**Confirmed clean and worth not re-deriving:** `list:`-prefixed rows are not
reachable or forgeable through any client-facing API (blocked at
`handlers/properties.py:184` and `property.py:84-91`); `list:`-prefixed names are
never written to the lookup table on either backend; `_v2_is_rank()` is the sole
and sufficient defence against legacy `#`-named siblings; PostgreSQL's
`name COLLATE "C"` puts byte order, not locale collation, in force for range
reads. One asymmetry noted and deferred: `PropertyStore.__setattr__`
(`property.py:93-121`) has no `list:` guard where `__setitem__` does.

---

## Implementation Summary

**Completed:** 2026-08-15
**All phases:** Complete
**Test status:** All passing — **2794 passed, 26 skipped, 0 failed** (full
sequential suite on dynamodb-local, 7m44s), plus the property-list and
migration-script suites re-run on **postgresql** (44 passed). `pyright` 0
errors, `ruff check` clean, `sphinx-build -W` clean.

**Gate substitution, stated deliberately:** CLAUDE.md names
`make test-all-parallel` as the pre-commit gate; the full **sequential** run was
used instead. CLAUDE.md itself treats sequential as the stricter isolation gate
(it is what a parallel failure gets re-verified against), and this change alters
metadata writes on every list mutation, where a cross-test isolation artefact
would be exactly the wrong thing to be chasing. Full-suite PostgreSQL coverage
is CI's job; the plan's both-backends requirement was met on the property-list
subsets.

### Deviations from Plan

Each phase carries its own "Deviations and notes" block; the four that changed
what shipped, rather than only how:

1. **`_save_metadata()` split in two.** The plan asked for it to become
   read-modify-write. It did — and the wholesale write it used to be survives as
   `_replace_metadata()`, needed by `clear()`'s deliberate reset and by
   migration's format flip. The safe form keeps the name callers reach for.
2. **Absent-meta-row policy is per-caller** (`create_if_absent`), not one rule.
   The v1 length writers skip the write (an absent row means a concurrent
   `delete()` won); the creation paths still create. `_v2_touch_metadata()` sits
   on the creating side because under v2 there is no separate creation step —
   `append()` to a list with no meta row is how a list comes into existence.
3. **`clear()`/`delete()` re-read the format before dispatching**, which the
   plan did not list. Both end in a wholesale metadata write, so a stale v1
   cache produced the same format revert through the replace path that Phase 1
   closes on the merge path.
4. **The vanished-meta-row abort had to roll back step 4.** Returning at step 5
   left a full v2 rank set with no meta row — invisible to `exists()`/
   `list_all()`, and adopted as items by the next list of that name.

Smaller: `verify_property_lists.py` gained one INFO line so cross-format residue
is reachable from the sweep an operator actually runs (`verify()` reporting it
is not enough when the script short-circuits on `healthy`);
`downgrade_to_v1()`'s `not_v2` return gained `swept_v2_rows`, which changed one
existing assertion.

### Learnings

- **The plan's list of 11 `_save_metadata()` call sites was the whole audit, and
  it was right.** Converting each one to name its fields is what surfaced that
  four of them (the v1 length writers) had a *different* correct answer for the
  absent-row case than the other seven. A blanket "read-modify-write" would have
  fixed the format revert and left the delete-resurrection in place.
- **Fixing the library method was the easy half; the operator path was the
  point.** `migrate_to_v2()`'s `already_v2` sweep is unreachable from
  `actingweb-migrate-property-lists` without the corresponding change to
  `migrate_actor()`'s `if already_v2: continue`. The plan flagged this as "the
  load-bearing one" and it was: with only the library fix, the unit test passes
  and the manual verification fails.
- **Both convergence tests were checked by neutering the fix and watching them
  fail** — including the script-level one. Worth the two minutes: a test that
  asserts residue is absent passes trivially if the setup never created any.
- **The fix costs one point read per list mutation, and that was not in the
  plan's accounting.** Reading the metadata row before merging is the whole
  mechanism, so it cannot be optimised away without a compare-and-set primitive
  neither backend exposes (`db/protocols.py` has only `create_if_not_exists`
  and `delete_if_value_equals`). Measured effect on the suite was inside the
  noise, but it is a hot-path round trip on every `append()`, and it is now
  stated in the CHANGELOG rather than left for someone to discover in a
  capacity graph. Row 5 (`property-fetch-reads-whole-partition`) is the
  existing item where per-call read cost gets re-measured against GA; this
  belongs in that measurement.
- **The 3.14 todo's constraint list is now one item shorter.** It said v1 has no
  range read and that a sweep would need a `^\d+$` shape filter. Phase 2 built
  both (`_v1_bounds()`, `_v1_item_names_in_range()`), so a third atomicity
  design inherits them rather than having to build them first. The todo has been
  updated to say so, along with the `length`-read-side residual Phase 1 left.
