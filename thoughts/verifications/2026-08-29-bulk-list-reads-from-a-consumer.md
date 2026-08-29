# Verification: scoped bulk list reads, and the attribute-bucket cache

**Date:** 2026-08-29
**Plan:** thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md
**Research:** thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md
**Branch:** `docs/scoped-bulk-list-reads`
**Commit:** `0e58ab2` (PR #139, "Release v3.14.3")

Scope: all seven phases of the plan, plus the review comments on PR #139.

## Automated Check Results

- **Ruff check:** Pass (`poetry run ruff check actingweb tests` — all checks passed)
- **Ruff format:** Pass (357 files already formatted)
- **Pyright:** Pass (0 errors, 0 warnings, 0 informations)
- **Sphinx** (CI invocation: `sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build`): Pass
- **Pytest, unit** (`tests/ --ignore=tests/integration -n auto`, DynamoDB Local): Pass — 2,361 passed, 23 skipped (3:17)
- **Pytest, integration, DynamoDB** (`tests/integration`, sequential): Pass — 911 passed, 8 skipped (1:30)
- **Pytest, integration, PostgreSQL** (`tests/integration`, sequential, `DATABASE_BACKEND=postgresql` against the port-5433 test container): Pass — 903 passed, 16 skipped (0:32)

Note: the unit suite cannot run inside the Claude Code sandbox — `pytest-rerunfailures`
binds a localhost socket at configure time and the sandbox denies it
(`PermissionError: Operation not permitted` in `pytest_configure`). It ran outside
the sandbox. This is an environment quirk, not a branch problem.

## PR #139 review comments

Fetched from GitHub at verification time. CI on the PR is fully green: tests on
both backends (Python 3.11 × dynamodb, postgresql), type-check, Documentation Build,
claude-review, codecov patch/project.

Two automated reviewers ran; no human review yet.

- **claude-review** (GitHub Action): pass, no findings posted.
- **Codex** (chatgpt-codex-connector, reviewed `0e58ab2`): **one P2 finding**, inline
  at `actingweb/attribute.py:151` — *"Invalidate bucket authority when a deletion
  fails."* Evaluated below; it is **valid** in a narrow case and recorded as Issue 1.

**Evaluation of the Codex P2.** `Attributes.delete_attr()` (`attribute.py:257-266`)
deletes the cached entry from `self.data` *before* calling the backend, and the new
falsy branch of `set_attr()` (`:182-190`) pops it likewise. Phase 6c then makes an
absent key on a loaded bucket authoritative (`:150-151`). So if the bucket was loaded
and the backend delete **fails**, the cache says "absent" while storage still holds the
row, and `get_attr()` returns `None` for the rest of that instance's life instead of
point-reading and recovering as it did before this PR.

How reachable: on PostgreSQL the falsy `set_attr` returns `False` on a caught
exception (`db/postgresql/attribute.py`, the `except` after the `DELETE`), so the
failure is real and reportable. On DynamoDB the falsy branch swallows every
exception and returns `True` (`db/dynamodb/attribute.py:156-164`), so a failed delete
was already invisible to the caller before this PR and the cache already disagreed
with storage there — Phase 6 only removes the accidental re-read. The plan's own
security note says no long-lived `Attributes` sits on an authz path today, and the
CHANGELOG already flags the loss of the first-miss re-read as the behaviour change,
so this is a correctness edge, not a security regression. It does deserve the
three-line fix Codex suggests.

## Phase Verification

### Phase 1: DynamoDB attribute buckets stop matching by bare prefix — VERIFIED

**Changes verified:**
- `actingweb/db/dynamodb/attribute.py:74-82` — `get_bucket()` queries
  `startswith(bucket + ":")` **and** skips rows where `t.bucket != bucket`. Matches plan.
- `actingweb/db/dynamodb/attribute.py:320-331` — `delete_bucket()` carries both
  changes before `t.delete()`. Matches plan.
- Both docstrings point at `delete_by_chain()` and the subscription-suspension guard,
  as the plan asked.

**Tests verified:**
- `tests/test_attribute.py::TestDbAttributeBucketIsolation` — 7 mocked cases: prefix
  sibling on get/delete, `remote:abc`/`remote:abcd` on get/delete, colliding composite
  key on get/delete, and a query-carries-the-delimiter assertion. Meaningful.
- `tests/integration/test_db_attribute_buckets.py` — 10 cases, both backends (also
  hosts Phase 6's integration case).

**Deviations from plan:** the plan's "ambiguous composite key" test was rewritten
around a primary-key collision (both pairs produce the same `bucket_name` row), as the
plan's own deviation note records. Acceptable — and the backend upsert divergence it
exposed is filed at `thoughts/todo/attribute-upsert-bucket-drift.md` (INDEX row 24).

### Phase 2: the three v1 list methods stop dumping the partition — VERIFIED

**Changes verified:**
- `actingweb/property_list.py:2752-2758` (`verify()`), `:3032-3038` (`compact()`),
  `:3227-3235` (`migrate_to_v2()`) — each is `get_property(self.config).get_range(lower,
  upper, consistent_read=True)` over `_v1_bounds()`, with no `or {}`. Matches plan.
- `actingweb/property_list.py:21` — `get_property_list` import removed entirely.
- `actingweb/property_list.py:2799` — `foreign_format_rows` now comes from
  `_v2_item_names_in_range()` (keys-only range read). Deviation explained in the
  plan: v2 rows sort below `_v1_bounds()`'s lower bound, so the scoped read cannot
  see them. Correct and necessary.

**Tests verified:**
- `tests/test_v1_maintenance_scoped_reads.py` — 14 functions (parametrised to 18):
  two AST guards (no `fetch_all_including_lists` call in the module; name not
  imported), every-range-read-strongly-consistent, `DbError` propagates from all three
  with the list untouched, digit-suffixed sibling does not perturb the report, lazy
  migration issues scoped reads. Meaningful.
- `tests/test_property_list_integrity.py` — 27 obsolete `get_property_list`
  monkeypatches removed; the tests now go through `FakePropertyDb.get_range`.
- `tests/integration/test_property_list_migration.py` — `compact()` on a damaged v1
  list, both backends.

### Phase 3: `get_prefix()` on the property protocol — VERIFIED

**Changes verified:**
- `actingweb/db/protocols.py:247-315` — protocol method with the ordering,
  `keys_only`, `consistent_read`, no-normalization and under-read notes; `Raises: DbError`.
- `actingweb/db/dynamodb/property.py:530-572` — native `begins_with`; query loop is
  inside the `try` so PynamoDB's lazy iterator faults are wrapped in `DbError`; falsy
  prefix returns `{}`.
- `actingweb/db/postgresql/property.py:525-597` — `starts_with(name, %s)` with bound
  parameters, no `LIKE`, no `COLLATE "C"` bounds; falsy prefix returns `{}`.

**Tests verified:**
- `tests/test_db_property_get_prefix.py` — 11 unit cases (forwarding of
  `keys_only`/`consistent_read`, `DbError` on fault, both backends).
- `tests/integration/test_db_property_range.py` — prefix cases added, including the
  non-ASCII `étag` prefix, `_`/`%` literals, NFD-vs-NFC, empty prefix, and byte-identical
  key sets across backends.

### Phase 4: `list_prefix_with_rows()` and `rows_for()` — VERIFIED

**Changes verified:**
- `actingweb/property.py:8-62` — `rows_for()` attributes rows via the exact `-meta`
  name, `_V1_INDEX_RE`, and `_V2_RANK_MARKER` + `_v2_is_rank`; candidate prefixes
  sorted longest-first. Lives in the encoding owner, not `interface/`. Matches plan.
- `actingweb/property.py:163-248` — `list_prefix_with_rows()`: `ValueError` on empty
  prefix, `get_prefix(prefix=f"list:{prefix}", consistent_read=False)`, `DbError`
  propagates. Name derivation (`row_name[5:-5]` on `-meta` rows) is identical to
  `list_all_with_rows()`.
- `actingweb/interface/property_store.py:562-579` — interface mirror.
- Cost-contrast pointer added to both `list_all_with_rows()` docstrings.

**Tests verified:**
- `tests/test_list_prefix_with_rows.py` — 20 cases including the
  `consistent_read=False` acceptance gate, `memory`/`memory_`/`memory-old` semantics,
  `ValueError` naming `list_all_with_rows()`, `DbError` not swallowed, `rows_for()`
  with `foo`/`foo-old`/`foo-5` and the legacy `#`-named sibling, and the
  lost-meta-row parity case with `list_all_with_rows()`.
- `tests/integration/test_property_lists_advanced.py` — end-to-end on both backends,
  non-ASCII list name included.

### Phase 5: the authenticated store gets real bulk readers — VERIFIED

**Changes verified:**
- `actingweb/interface/authenticated_views.py:347-366` — collision set
  `_PROPERTY_LIST_STORE_METHOD_NAMES` computed from `vars()` of both stores; resolves
  at import to `{exists, list_all, list_all_with_rows, list_prefix_with_rows}`.
- `:451-457` — `__getattr__` raises `AttributeError` on collision; never resolves to
  the unauthenticated store's bound method.
- `:460-499` — `_permitted()`: one `evaluate_bulk_property_access()` call,
  `ALLOWED`/`NOT_FOUND` permitted, `None` (→ drop-all) on evaluator or
  `get_permission_evaluator()` error. The no-accessor / no-config early return
  matches `_check_permission()` exactly, so the bulk path is neither looser nor
  stricter than the single-list path.
- `:506-557` — `list_all()`, `list_all_with_rows()`, `list_prefix_with_rows()`, all
  routed through `_filtered()` → `rows_for()`. `ValueError`/`DbError` propagate.
- Log-volume note in the class docstring, as planned.

**Tests verified:**
- `tests/test_authenticated_bulk_list_reads.py` — 19 functions (parametrised to 24).
  The bypass guard is asserted directly (a sentinel planted on
  `store.list_all_with_rows`, `__getattr__` must raise rather than return it, `:182-186`);
  the collision set is re-derived independently; the `foo` (denied) / `foo-old`
  (allowed) case checks `to_list_from_rows()` returns real contents; no denied name in
  any message or in this module's log records; evaluator error → `([], {})`.
- `tests/test_authenticated_views.py` — 54 tests unchanged.

### Phase 6: a loaded attribute bucket becomes authoritative — VERIFIED

**Changes verified:**
- `actingweb/attribute.py:110-123` — `_bucket_loaded = True` only when the backend
  returned a dict (or there is no backend); `None` leaves it `False`. Docstring records
  the corrected DynamoDB-fault premise.
- `actingweb/attribute.py:143-150` — `get_attr()` returns `None` early for a name
  absent from a loaded bucket, so the miss path no longer pollutes `self.data`.
- `actingweb/attribute.py:182-196` — `set_attr()` pops the key on `not data`
  (`{}`/`[]`/`""`/`0`/`False`/`None`), mirroring the backends' falsy-delete.
- No backend edit, as decided.

**Tests verified:**
- `tests/test_attribute_bucket_authority.py` — 18 functions (parametrised to 28):
  faulting backend leaves the flag `False` and `get_attr` still reads through;
  DynamoDB-shape empty bucket sets the flag; PostgreSQL-shape empty bucket does not;
  zero backend calls after load; no pollution; the falsy-delete matrix;
  absent-vs-null distinguishable; `delete_attr` on a loaded bucket; `InternalStore`
  unchanged.
- `tests/integration/test_db_attribute_buckets.py` asserts
  `_bucket_loaded is (backend != "postgresql")` after loading an empty bucket — the
  divergence is pinned, not hidden.
- `tests/test_attribute.py` passes unchanged.

### Phase 7: documentation, changelog, release — VERIFIED

**Changes verified:**
- `docs/guides/property-lists.rst` — "All of them" / "One namespace of them" recipes
  plus the "When the scoped read actually pays" sub-section carrying the 1,363.5-vs-
  1,361.0 contrast, the caller-side latency note, and the no-snapshot-isolation note.
  Renders clean under `-W`.
- `CHANGELOG.rst` — `v3.14.3: August 29, 2026` with a fresh empty "Unreleased" above
  it; Phases 1 and 2 lead; the Phase 5 `__getattr__` change and Phase 6 carry
  `**Behavior change**` markers.
- `pyproject.toml:3` and `actingweb/__init__.py:31` both read `3.14.3`.
- `thoughts/todo/scoped-bulk-list-reads.md` deleted; INDEX row 22 gone; rows 23
  (`glob-to-regex-anchoring-gaps.md`) and 24 (`attribute-upsert-bucket-drift.md`)
  added; `prop-list-key-prefix-scheme.md` repointed at the plan.
- No leftover TODO/FIXME/print/breakpoint in the `actingweb/` or `tests/` diff.

## Remaining Tasks

- [ ] Tag `v3.14.3` on the merge commit once PR #139 is merged with CI green on both
  backends (release-process step, not code work).
- [ ] `thoughts/todo/glob-to-regex-anchoring-gaps.md` (INDEX row 23) — deliberately
  deferred by the plan.
- [ ] `thoughts/todo/attribute-upsert-bucket-drift.md` (INDEX row 24) — found during
  Phase 1, deliberately deferred.
- [ ] Fix the Codex P2 (Issue 1): invalidate `_bucket_loaded` when a backend delete
  returns `False`, with a test — ideally as a Phase 6 fix-up in PR #139 before tagging.
- [ ] Document the authenticated bulk readers and the method-name collision in
  `docs/sdk/authenticated-views.rst` (Issue 3).
- [ ] Backend alignment of `get_bucket()`'s empty-vs-fault `None` contract — the plan
  says "filed to `thoughts/todo/`" in Phase 6 but no dedicated todo file exists
  (Issue 2).

## Issues Found

### Issue 1: a failed backend delete on a loaded bucket leaves a stale authoritative miss (Codex P2)
**Severity:** Medium
**Description:** `Attributes.delete_attr()` and the falsy branch of `set_attr()` remove
the cached entry before the backend call. If the backend then returns `False`
(PostgreSQL does on a caught exception; DynamoDB swallows and returns `True`), the
loaded bucket now asserts absence and `get_attr(name)` returns `None` for the lifetime
of the instance, where before this PR the cache miss triggered a point read that
recovered the value. Narrow — needs a loaded bucket *and* a backend fault during
delete — and not on an authz path today, but a genuine regression of the recovery
behaviour on PostgreSQL.
**Location:** `actingweb/attribute.py:150-151` (the early return), `:182-190`
(`set_attr` falsy pop), `:257-266` (`delete_attr`).
**Recommendation:** In both delete paths, if the backend returns `False`, set
`self._bucket_loaded = False` (simplest and fail-safe: the next `get_attr` re-reads),
and add a unit test with a faulting `delete_attr` after `get_bucket()`. Reply to /
resolve the Codex thread once landed.

### Issue 2: Phase 6's "aligning the backends' empty-vs-fault contract" was not filed as its own todo
**Severity:** Low
**Description:** The plan (Phase 6a) and `actingweb/attribute.py`'s docstring both say
the PostgreSQL `get_bucket()` empty-bucket-returns-`None` divergence is "filed
separately" to `thoughts/todo/`. Only two todos were filed (rows 23, 24) and neither is
this one. The integration test pins the divergence, so nothing is silently wrong; the
pointer is just dangling.
**Location:** `actingweb/attribute.py:98-102`, plan Phase 6a.
**Recommendation:** Add a short `thoughts/todo/attribute-get-bucket-empty-vs-none.md`
(one backend edit + flipping the `_bucket_loaded is (backend != "postgresql")`
assertion) and an INDEX row, or drop the "filed separately" wording.

### Issue 3: `docs/sdk/authenticated-views.rst` does not document the Phase 5 bulk readers
**Severity:** Low (documentation)
**Description:** The branch's only hand-written docs change is `docs/guides/property-lists.rst`;
the reference pages are `automodule` and pick up the new docstrings automatically. But
the page that documents `AuthenticatedPropertyListStore` — "Property List Access" in
`docs/sdk/authenticated-views.rst` — says nothing about `list_all()` /
`list_all_with_rows()` / `list_prefix_with_rows()` now working through the view
(denied lists pruned from both `names` and `rows`, drop-all on a permission-system
error), nor about the behaviour change that a list named after a store method
(`exists`, `list_all`, `list_all_with_rows`, `list_prefix_with_rows`) now raises
`AttributeError` through the view. The page even explains the removed `create()`'s
`__getattr__`/`TypeError` failure — the same bug Phase 5 fixed for the bulk readers —
so a reader would expect it to say so. Optional extras: a cross-reference from the new
`property-lists.rst` recipes to the authenticated behaviour, and a short "a loaded
bucket is authoritative for the instance's lifetime" note in
`docs/sdk/attributes-buckets.rst`, which today exists only in the CHANGELOG.
**Location:** `docs/sdk/authenticated-views.rst:123-175`.
**Recommendation:** Add a short bulk-read example and the collision note to that
section; small enough to ride in PR #139.

## Overall Assessment

The implementation is complete and matches the plan in every phase, including the
four substantive deviations the plan records (the `foreign_format_rows` extra read,
the composite-key collision rewrite, the one-directional A6 invariant, and the
corrected Phase 6a premise) — each was checked in code and each is the right call.
Every gate is green locally and on CI for both backends: ruff, ruff format, pyright,
sphinx `-W`, 2,361 unit / 911 DynamoDB / 903 PostgreSQL integration tests, all
matching the plan's final numbers exactly. The new tests are the load-bearing kind:
the `__getattr__` bypass guard plants a sentinel and asserts it is never returned,
the AST guards make the removed partition dump unreachable rather than merely untested,
and the "fails today" claims were each demonstrated against pre-change code.

Two things want attention before the tag. First, the Codex P2 (Issue 1) is a real
edge on PostgreSQL — a failed delete on a loaded bucket now leaves a stale
authoritative miss — and the fix is small: when the backend returns `False` from
`delete_attr()` / falsy `set_attr()`, clear `_bucket_loaded` (or restore the entry),
plus one test. It is small enough to ride in this PR as a Phase 6 fix-up commit
before the bump; if it is deferred instead, it should be a todo, not forgotten.
Second, the Phase 6 "filed separately" pointer for the backend empty-vs-`None`
alignment has no todo behind it (Issue 2, Low). Neither blocks a merge on safety
grounds; both are cheaper to close now than after 3.14.3 is tagged.

## Addendum (same day): issues 1–3 fixed on the branch

All three issues above were addressed on `docs/scoped-bulk-list-reads` after this
document was written, as uncommitted changes on top of `0e58ab2`:

- **Issue 1 (Codex P2):** `Attributes._unload_after_failed_delete()` added;
  `delete_attr()` and the falsy branch of `set_attr()` call it when the backend
  returns `False`, dropping the entry and clearing `_bucket_loaded` so the next read
  goes through. Tests: `test_a_failed_delete_does_not_leave_a_stale_authoritative_miss`
  (parametrised over both paths; both **fail** against the pre-fix code) and
  `test_a_confirmed_delete_keeps_the_bucket_authoritative`. CHANGELOG's Phase 6 entry
  now lists it as the third supporting correction. The Codex thread on PR #139 has not
  been replied to or resolved.
- **Issue 2:** `thoughts/todo/attribute-get-bucket-empty-vs-none.md` filed as INDEX
  row 25; the "filed separately" sentence in `Attributes.get_bucket()`'s docstring now
  names it.
- **Issue 3:** `docs/sdk/authenticated-views.rst` gained a "Bulk reads" sub-section
  under "Property List Access" covering the three readers, both-halves filtering,
  drop-all on error, and the method-name-collision `AttributeError`.

Re-checked after the fixes: ruff check / ruff format clean, pyright 0 errors, sphinx
`-W` clean, `tests/test_attribute_bucket_authority.py` + `tests/test_attribute.py`
72 passed, `tests/integration/test_db_attribute_buckets.py` 10 passed (DynamoDB), and
the `-k "oauth or token or attribute or authenticated"` unit subset 551 passed. The
full suites were not re-run after the addendum; the change is confined to
`actingweb/attribute.py`.
