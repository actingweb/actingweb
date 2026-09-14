# Verification: a v2 list mutation never raises after its item write has committed (3.14.7)

**Date:** 2026-09-14
**Plan:** thoughts/plans/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md
**Research:** thoughts/research/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md
**Branch:** fix/3.14.7-list-mutation-committed
**Commit:** a34561b (the review-fix commit this verification also covers; the
plan's own work is 994f986 → 085384e, PR #146)

This verification covers Phases 1 and 2 in full and the code-side of Phase 3
(version bump, changelog rename, todo bookkeeping). Merge, tag, PyPI publish
and consumer notification are user actions the plan explicitly deferred; they
are outside what this document verifies and its Phase 3 boxes stay open.

It also picks up the two review comments left on PR #146 and records what was
done about them (see "Review comments actioned").

## Automated Check Results

- **gstack /review:** Ran the preamble, the scope check and a manual critical
  pass over the full diff against `origin/master` (merge base `adfecc3`).
  The Review Army specialist dispatch and the adversarial subagent/Codex
  passes were not run (autonomous session; the diff is one library module
  plus tests, and two external reviewers had already read it). Scope Check:
  **CLEAN** -- every changed file traces to a plan phase; no out-of-scope
  changes. Open findings: none after this session's fixes (three
  informational findings, all fixed: the `meta_row_present` wording, the
  implicit `RuntimeError`-subclass invariant at the touch's `except`, and
  three broken sibling-file links in the two new todos).
- **gstack /qa:** N/A -- no frontend phases. The one UI-adjacent change
  (`www.py` 503 mapping) is covered end-to-end by
  `tests/integration/test_www_list_corruption.py:81` against a running
  uvicorn.
- **Ruff:** Pass (`ruff check actingweb tests` and `ruff format --check`,
  377 files already formatted).
- **Pyright:** Pass -- 0 errors, 0 warnings, 0 informations.
- **Pytest (this session, after the review fixes):** Pass -- 131 passed on
  `tests/test_v2_list_mutation_committed.py`,
  `tests/test_v1_maintenance_scoped_reads.py`,
  `tests/test_v2_append_last_rank.py`, `tests/test_v2_metadata_cas.py`,
  `tests/test_property_list_notifications.py`,
  `tests/test_bulk_list_update_handles.py`. The full parallel suite was not
  re-run here: the review fixes touch only docstrings, a comment and prose.
- **Pytest (CI on PR #146 at 085384e, both backends):** Pass.

  | Backend | Collected | Passed | Failed | Flaky |
  | --- | --- | --- | --- | --- |
  | dynamodb | 3526 | 3495 | 0 | 0 |
  | postgresql | 3526 | 3386 | 0 | 0 |

  Codecov: all modified lines covered; project coverage +0.10%.
- **Sphinx (`sphinx-build -W --keep-going`):** exits non-zero on exactly one
  warning, `docs/sdk/authenticated-views.rst:197: unknown document:
  '/guides/property-lists'`, which predates this branch (confirmed by the
  plan against `adfecc3`) and is unrelated. No warning from any docstring
  or guide text this plan touched, before or after the review fixes.

## Phase Verification

### Phase 1: The advisory touch never fails a committed mutation; a list's first mutation creates its meta row first - VERIFIED

**Changes verified:**

- `actingweb/property_list.py:22` -- `DbError` imported, as planned.
- `actingweb/property_list.py:190-228` -- `ListMetadataContentionError`
  gains keyword-only `detail: str | None = None`; the default message is
  byte-identical to before, the detailed form keeps "retry the request",
  `list_name`/`actor_id` attributes unchanged. Matches plan.
- `actingweb/property_list.py:446` -- `_dispatch_saw_no_row()` returns
  `self._pending_meta_read == (None, None)`. Matches plan.
- `actingweb/property_list.py:1284-1379` -- `_v2_touch_metadata()` wraps its
  single `_save_metadata(advisory=True)` call in `except (DbError,
  RuntimeError)`, logs one WARNING with `exc_info=True` and the exception
  text, and returns. `ValueError` deliberately not caught. The WARNING text
  contains "backend fault" and is distinct from the contention warning at
  `:954-965`. Matches plan. This session added a comment at `:1361`
  documenting that `ListMetadataContentionError` is a `RuntimeError`
  subclass and why the clause is nonetheless safe (see review comments).
- `actingweb/property_list.py:1542-1608` -- `_v2_create_meta_row()`:
  `_invalidate_cache()`, `_load_metadata()`, conditional
  `create_if_not_exists`, re-stash on success, re-read on loss, adopt a v2
  row, else raise `ListMetadataContentionError(detail=...)`. Body matches
  the plan's listing line for line; the ASCII diagram is in the docstring
  as an RST literal block.
- `actingweb/property_list.py:1650`, `:1742`, `:2191` -- the guard
  `if self._dispatch_saw_no_row(): self._v2_create_meta_row()` at the top
  of `_v2_append`, `_v2_extend`, `_v2_insert`. Matches plan.
- `actingweb/property_list.py:793-803`, `:997-1002` -- `_save_metadata`
  `advisory` docstring and `_replace_metadata` `Raises:` corrected as
  planned; no code change in either.
- `actingweb/handlers/www.py:1031-1035` -- `except
  ListMetadataContentionError` before `except Exception`, 503 with
  `Retry-After: 1`, inside the list-item block's `try`. Matches plan.
- `tests/test_v2_append_last_rank.py:209`, `:284-287` -- `create_call_count
  == 5` and the stolen-row injection moved to call 3, both with comments
  explaining the meta-row create. Matches plan.

**Tests verified** (`tests/test_v2_list_mutation_committed.py`, 951 lines,
read in full):

- `TestExistingRowSwallowsBackendFault::test_touch_fault_on_an_existing_row_is_swallowed`
  -- parametrized over all eleven mutators; asserts no raise, exact
  post-state through a fresh instance, exactly one WARNING with `exc_info`
  set and the `DbError` operation text. Meaningful.
- `pop` return value, `remove_where`/`update_where` partial results,
  retry-read fault after one CAS loss (`lose_cas_first=1,
  fail_get_after_cas_losses=True`), drift bounded and repaired by `pop()`.
  All present and match the plan's spec.
- `TestBoundaries` -- v1 semantic write still raises `DbError` (and the
  item row is present), `set_description()` still raises, corruption
  `ValueError` still raises after a CAS loss. All present.
- `TestFirstMutationWriteOrder` -- write-order pin (meta create, item
  create, meta CAS; `count_hint == 1`), `extend([])` records nothing.
- `TestFirstMutationFaults` -- meta-create fault x3 leaves an empty store;
  item-write fault leaves an empty visible list with `format == 2`,
  `count_hint == 0`, `format_ever_changed is False`; CAS fault on a
  never-created list lands the item with drift and the next append on a
  clean store works; `extend` faulting on item 2 leaves `["a"]` with
  drift -1; `#`-name and scalar-collision `ValueError` before any write.
- `TestFirstMutationLostCreate` -- v2 winner adopted (`description`
  survives, `count_hint` 4 → 5), v1 winner raises with "first-mutation
  create" and no item row, vanished winner raises, error messages and the
  handler's 503 body `detail`.
- `TestTheExactBulkHandlerShapeFromANeverCreatedList` -- the mandatory
  regression pin, under `@pytest.mark.timeout(5)`.
- `TestResidualOrphan` -- `_DeleteAfterCreatePropertyDb`: no raise, one
  WARNING, item row present, meta row absent.
- `TestNotifyingListPropertyStillRegistersDiffs` -- append/pop/remove_where
  diffs registered despite the swallowed fault.
- `tests/test_bulk_list_update_handles.py:707` -- PUT `?index=1` returns
  204 with the item replaced; bulk POST applies update/append/delete with
  no "concurrently modified" warning. Real backend, faulting proxy on
  `set_if_value_equals` for `-meta` names.
- `tests/integration/test_property_list_v2.py:210` -- first
  append/extend/insert leave `format == 2`, exact `count_hint`, healthy
  `verify()`; scalar-collision regression pin.
- `tests/integration/test_www_list_corruption.py:81` -- detailed and
  default `ListMetadataContentionError` both map to 503 + `Retry-After: 1`;
  the detailed case also asserts no meta row in storage.

**Deviations from plan:**

- `_v2_extend()` has no in-method "non-empty items" guard; `extend()`
  returns before dispatch on an empty batch (recorded in the plan; verified
  by `test_extend_of_zero_items_on_a_never_created_list_records_nothing`).
  Acceptable.
- The bulk handler test asserts status 201, not the plan's 200; 201 is what
  `_post_bulk` actually returns. Acceptable.
- The PUT handler test does not assert `register_diffs` was called, and the
  www test does not assert the absence of an *item* row (it asserts the
  meta row's absence, and `append` is mocked so no item write is possible).
  Both pins are covered at the unit layer
  (`TestNotifyingListPropertyStillRegistersDiffs`, the lost-create tests).
  Acceptable; noted so nobody reads the plan's list as the test's contents.

### Phase 2: `verify()` reports the orphan state; texts corrected; todos filed - VERIFIED (with one doc fix applied)

**Changes verified:**

- `actingweb/property_list.py:2804` -- `meta_row_present = stored is not
  None` computed **before** `stored = stored or {}`. `:2820-2824` -- key
  emitted; `healthy` gains `and not (not meta_row_present and length > 0)`.
  Matches plan.
- `actingweb/property_list.py:340-346` -- class docstring gains the "a v2
  item mutator that RETURNS has committed" sentence. Matches plan.
- `actingweb/handlers/properties.py:798-808` -- the "never raises this"
  comment rewritten as planned; `grep -rn "never raises this" actingweb/`
  returns nothing.
- `docs/guides/property-lists.rst:158-199` -- third drift term reworded;
  "What a returned mutation guarantees" subsection present with the five
  planned bullets.
- `docs/guides/property-lists.rst:217-229` -- `meta_row_present` paragraph.
  **Was wrong as committed** (see Issues Found, fixed in a34561b).
- `CHANGELOG.rst` -- three FIXED entries with bold "Behavior change"
  sentences and the "not safe in general" sentence pointing at the SDK-retry
  todo. Entry 3 clarified in a34561b.
- `thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md`,
  `thoughts/todo/meta-row-create-unconditional-for-description-writers.md`,
  two rows in `thoughts/todo/INDEX.md` under "Real, not urgent". Present
  with the planned content. **Three links were broken** (see Issues Found,
  fixed in this session).
- `thoughts/todo/v2-list-access-verification-followups.md` -- the `www.py`
  bullet deleted; the backend-seam bullet kept.

**Tests verified:**

- `TestVerifyReportsOrphanState` -- orphan (`meta_row_present False`,
  `healthy False`, `count_hint None`, `length 3`), never-created
  (`meta_row_present False`, `healthy True`, `length 0`), normal list,
  and repair by `compact()`. All four planned cases present. The
  never-created case is what exposed the docstring error.
- `tests/test_v1_maintenance_scoped_reads.py:379` -- exact-shape pin gains
  `meta_row_present: True` (recorded deviation; correct handling of an
  exact-equality test).
- `tests/integration/test_verify_property_lists_script.py:298` -- an orphan
  under an unenumerated name leaves the sweep's checked/unhealthy/errored
  counts unchanged and its row untouched.

**Deviations from plan:** none beyond the recorded
`test_v1_maintenance_scoped_reads.py` update.

### Phase 3: Release 3.14.7 - CODE SIDE VERIFIED, RELEASE STEPS OPEN

**Changes verified:**

- `pyproject.toml:3` and `actingweb/__init__.py:31` both read `3.14.7`.
- `CHANGELOG.rst` -- "Unreleased" renamed to `v3.14.7: September 14, 2026`
  with a fresh empty "Unreleased" above it.
- The plan's "delete `thoughts/todo/v2-list-mutation-raises-after-its-write-committed.md`"
  step had nothing to delete: that file never existed on `master` (the
  inbound report was triaged straight into research). Not a defect, but
  the two new todos linked to it as a sibling file, which was.
- Release commit `45b2cf6 Release v3.14.7`; PR #146 open; CI green on both
  backends (table above).

**Open (user actions, by the plan's recorded deferral):**

- [ ] Merge PR #146 after re-checking CI on the two commits pushed by this
      session
- [ ] On `master`: `git pull`, `git tag v3.14.7`, `git push --tags`
- [ ] Confirm the tag workflow published 3.14.7 to PyPI and created the
      GitHub Release
- [ ] Tell the `actingweb_mcp` consumer the release closes their
      `list-mutation-reported-failed-after-commit` todo for the reported
      mechanism, and point them at
      `thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md` for
      what it does not close

## Review comments actioned

PR #146 carried two reviews when this verification started:

1. **Codex, P2, `docs/guides/property-lists.rst:218`** -- "Correct the
   documented meaning of meta_row_present". Confirmed against the code: the
   guide and the `_v2_verify` docstring said `meta_row_present` is `True`
   for a never-created list, but `:2804` computes `stored is not None`,
   which is `False` there, and
   `TestVerifyReportsOrphanState::test_a_never_created_list_is_not_an_orphan`
   pins `False`. The code and the test agree with the plan's Phase 2 test
   spec; the prose was the error. **Fixed in a34561b:** both texts and the
   CHANGELOG entry now say the key is physical presence, that the orphan
   state is `meta_row_present is False and length > 0`, and that `healthy`
   encodes exactly that combination.
2. **Claude reviewer, non-blocking** -- `ListMetadataContentionError`
   subclasses `RuntimeError`, so `except (DbError, RuntimeError)` at
   `property_list.py:1361` depends on `_save_metadata(advisory=True)` never
   raising it. Confirmed: the exhaustion path at `:954-965` returns under
   `advisory=True` and the raise at `:966` sits behind that return. An
   explicit re-raise was rejected because it would reintroduce the
   raise-after-commit this plan fixes. **Fixed in a34561b:** a comment at
   the `except` names the dependency and the intended outcome if it ever
   changes.

## Remaining Tasks

- [ ] The four Phase 3 release steps listed above (user).
- [ ] Optional, out of scope for the patch: the pre-existing
      `docs/sdk/authenticated-views.rst:197` broken `:doc:` reference that
      keeps `sphinx-build -W` red. Not filed as a todo here; it is a
      one-line fix whenever someone next touches that page.

## Issues Found

### `meta_row_present` documented as `True` for a never-created list
**Severity:** Medium (consumer-facing contract text contradicted the code)
**Description:** The guide and the `_v2_verify` docstring described the key
as "`False` iff item rows exist with no meta row ... `True` ... INCLUDING a
never-created list with zero items". The code returns `False` for a
never-created list. A consumer following the text would classify every
absent list as an orphan.
**Location:** `docs/guides/property-lists.rst:217`,
`actingweb/property_list.py` (`_v2_verify` docstring), `CHANGELOG.rst`
entry 3.
**Resolution:** Fixed in a34561b as described above. No code change: the
code and the test already implemented the plan's intent.

### Implicit invariant at the touch's `except`
**Severity:** Low
**Description:** `except (DbError, RuntimeError)` would also swallow
`ListMetadataContentionError`; safe today only because
`_save_metadata(advisory=True)` returns instead of raising it.
**Location:** `actingweb/property_list.py:1361`
**Resolution:** Comment added in a34561b. No behaviour change.

### Broken links in the two new todos
**Severity:** Low
**Description:** Both new todos linked to
`v2-list-mutation-raises-after-its-write-committed.md` as a sibling file in
`thoughts/todo/`; that file never existed. One also said the changelog
entry was under "Unreleased" after Phase 3 had renamed it.
**Location:** `thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md:4`,
`:39`; `thoughts/todo/meta-row-create-unconditional-for-description-writers.md:4`
**Resolution:** Repointed at
`../plans/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md`
and the wording corrected, in the commit that carries this document.

## Overall Assessment

The implementation is complete and matches the plan closely enough that
every deviation is a recorded, acceptable one. The library change is
confined to `property_list.py` plus one handler mapping; the behaviour the
research asked for (a v2 mutator that returns has committed, one that
raises has not, with the two documented first-mutation exceptions) is
implemented, tested at the unit, handler and integration layers on both
backends, and stated in the guide and changelog in the same words the code
keeps. CI on the PR is green on DynamoDB and PostgreSQL with no flakes.

What needed attention before merging was prose, not code: the
`meta_row_present` contract text contradicted the implementation, and two
todos linked to a file that does not exist. Both are fixed on the branch.
The release steps the plan deferred to the user (merge, tag, publish,
notify the consumer) are the only work left.
