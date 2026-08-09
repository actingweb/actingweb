# Verification: Property-list index integrity — fixes, repair, and fractional-key storage

**Date:** 2026-08-09
**Plan:** thoughts/plans/2026-08-08-property-list-index-integrity.md
**Research:** thoughts/research/2026-08-07-property-list-index-integrity.md,
thoughts/research/2026-08-08-property-list-index-integrity-review.md
**Branch:** feature/property-list-index-integrity
**Commit:** 55311a0

All five phases were verified. Every automated check was re-run in this
session rather than taken from the plan's own Implementation Status notes.

## Automated Check Results

- **Ruff (check):** Pass — `poetry run ruff check actingweb tests scripts`,
  all checks passed.
- **Ruff (format):** Pass — `ruff format --check actingweb tests scripts`,
  323 files already formatted.
- **Pyright:** Pass — `poetry run pyright actingweb tests scripts`, 1 error,
  which is `scripts/migrate_db.py:113` `Import "dotenv" could not be
  resolved`. Confirmed pre-existing and unrelated: the import is identical on
  `master` (`git show master:scripts/migrate_db.py`) and the file is not
  touched by this branch (`git diff --stat master...HEAD -- scripts/migrate_db.py`
  is empty).
- **Pytest (DynamoDB, full suite):** Pass — `make test-all-parallel`:
  **2706 passed, 26 skipped** in 102s. Exactly matches the plan's claim.
- **Pytest (PostgreSQL, integration):** Pass — `tests/integration/` with
  `DATABASE_BACKEND=postgresql` against the compose `postgres-test`
  container: **813 passed, 18 skipped** in 30s. Exactly matches the plan's
  claim.
- **Alembic:** Pass — from `actingweb/db/postgresql/` (where `alembic.ini`
  lives) against the test container: `alembic upgrade head` applied the chain
  through `d4e5f6a7b8c9 → e5f6a7b8c9d0`, `alembic downgrade -1` reverted that
  revision cleanly, and `alembic upgrade head` re-applied it; `alembic
  current` ends at `e5f6a7b8c9d0 (head)`.
- **Docs build:** Pass — `sphinx-build -W --keep-going -b html .` from the
  repo root (`conf.py` lives at the root, not in `docs/`): `build succeeded`,
  zero warnings-as-errors.
- **Debug residue:** Clean — no `TODO`/`FIXME`/`XXX`/`breakpoint()`/`pdb`/
  stray `print()` in any added line across `actingweb/`, `scripts/`,
  `tests/`.

## Phase Verification

### Phase 1: Error handling + `insert()` fix (P0) — VERIFIED

**Changes verified:**

- `actingweb/db/exceptions.py:1-17` — `DbError` present, message sanitized to
  `"database error during {op} for actor {id}"`, docstring states the
  absence-vs-fault distinction. Exported from `actingweb/db/__init__.py`
  (`__all__` includes `"DbError"`).
- `actingweb/db/dynamodb/property.py:180-208` — `get()` catches
  `pynamodb.exceptions.DoesNotExist` (base class, per the plan's documented
  deviation) → `None`; every other exception → `raise DbError(...) from e`.
  Both the `handle.refresh()` branch and the fresh `Property.get()` branch.
- `actingweb/db/dynamodb/property.py:175-179` and `:363-371` — the
  cached-handle guard is present on **both** `get()` and `set()`: a handle
  whose `(id, name)` disagrees with the arguments is discarded before use.
  This is the fix for the class-level stale-handle bug.
- `actingweb/db/dynamodb/property.py:393-396` — `handle.save()` wrapped in
  `DbError`.
- `actingweb/db/postgresql/property.py:133-135` — `get()` raises `DbError`
  instead of log-and-return-`None`; the no-row path still returns `None`
  (`:132`). `set()` keeps its bool contract with the docstring amended to say
  callers MUST check it (`:277-279`).
- `actingweb/property_list.py` — every `set()` call site checks the return
  value and raises `RuntimeError`: `append` (`:723`), `__setitem__`
  (`:569`), `__delitem__` (`:622`, `:640`, `:651`), `insert` (`:980`,
  `:996`), `clear` (`:770`), `delete` (`:805`, `:812`), `_save_metadata`
  (`:291`).
- `actingweb/property_list.py:967-1001` — `insert()`'s v1 path now uses a
  fresh `get_property(self.config)` per read/write, with an inline comment
  recording the DynamoDB overwrite bug it fixes.
- `actingweb/db/protocols.py:131-132, 225, 252` — docstrings document the
  `DbError`-on-fault contract for `get()`, `get_range()` and
  `create_if_not_exists()`.
- `actingweb/handlers/properties.py` — **zero** `str(e)` interpolations
  remain in the file (verified by grep); all five sites the plan named
  (including the fifth it omitted) return generic messages.

**Tests verified (all pass, all have teeth):**

- `tests/test_property_list_integrity.py::TestDeleteReadFailurePropagates` —
  a fake whose `get()` raises `DbError` mid-shift; asserts propagation AND
  that the successor row and stored length are untouched.
- `::TestWriteFailureRaisesRuntimeError` — three cases (append / setitem /
  delitem) asserting `RuntimeError` and unchanged metadata length.
- `::TestCrashInjectionResidue` — documents the residual v1 crash window.
- `tests/integration/test_db_property_handle.py` — one `DbProperty`
  instance serving row A then row B correctly.
- `tests/integration/test_property_lists_advanced.py` — `insert(0, …)` and
  `insert(1, …)` into a ≥3-item list with full content assertions.

**Deviations from plan:** the four recorded in the plan's own notes
(`DoesNotExist` base class, the fifth `str(e)` site, the metadata-write
`RuntimeError` wording, test file placement). All are correct as argued; the
`DoesNotExist` base-class choice in particular is strictly more correct given
`PropertyLegacy` handles can reach that code path.

### Phase 2: Repair and detection — VERIFIED

**Changes verified:**

- `actingweb/property_list.py:1074-1139` — v1 `verify()` uses one
  `fetch_all_including_lists()` partition read and the anchored pattern
  `^list:{re.escape(name)}-(\d+)$`; reports `stored_length`,
  `readable_count`, `missing_indices`, `orphan_indices`,
  `adjacent_duplicates`, `healthy`. Indices only — never item values.
- `actingweb/property_list.py:1223-1288` — v1 `compact()` rewrites survivors
  densely, skips writes where the target row already holds the right value,
  deletes through `max(stored_length-1, *orphan_indices)`, preserves
  `description`/`explanation`/`created_at` (it mutates the loaded meta rather
  than calling `_create_default_metadata()`), and returns the pre-write
  report. Duplicates left intact and reported, as decided.
- `actingweb/property_list.py:251-264` — `_load_metadata()` raises
  `ValueError` on unparsable JSON and on non-dict JSON, with a comment
  explaining why self-healing would orphan every row. The "no metadata row"
  path keeps default-create behaviour.
- `actingweb/interface/property_store.py:326-330, 380-387` —
  `NotifyingListProperty.verify()` (no diff) and `.compact()` (registers a
  `"metadata"` diff, staying inside the spec's closed operation vocabulary).
  Nothing added to `PropertyListStore`, so no list name is shadowed.
- `scripts/verify_property_lists.py` — dry-run by default, `--repair` gates
  `compact()`, per-list report including duplicate suspects.

**Tests verified:**

- `tests/integration/test_property_list_repair.py` — hole/orphan detection,
  `compact()` closing holes while preserving description/explanation/
  created_at, duplicate-residue left intact, `pop()` working again after
  repair.
- `tests/test_property_list_integrity.py::TestUnparsableMetadataRaises` —
  both invalid-JSON and non-dict-JSON cases, each asserting the stored row is
  **untouched** (no `length: 0` write).
- `tests/integration/test_verify_property_lists_script.py` — sweep smoke
  tests plus the checkpoint round-trip.

**Deviations from plan:** as recorded — `verify()`/`compact()` were v1-only
at this point (correct; v2 didn't exist yet), and the script sweeps actors via
`get_actor_list(config).fetch()` rather than segmented scan (correct; there is
no segmented-scan primitive for the actor list on either backend).

### Phase 3: Fail-fast reads + `/items` storage-index contract — VERIFIED

**Changes verified:**

- `actingweb/property_list.py:40-59` — `ListCorruptionError(IndexError)`
  carrying `list_name` and `index`; message contains names and indices only.
- `actingweb/property_list.py:500-501` — `__getitem__` raises
  `ListCorruptionError` for an in-range missing row, plain `IndexError` for
  genuine out-of-range. `to_list()`/`slice()`/`to_list_from_rows()` no longer
  swallow `IndexError`, so they inherit the right exception type.
- `actingweb/property_list.py:882-902` — `to_indexed_list()` with a docstring
  that documents the v1 (identity == position) vs v2 (identity == rank)
  split.
- `actingweb/handlers/properties.py:50-70` — module-level
  `_write_list_corrupted_response()` emitting `409` with
  `{"error": "list_corrupted", "list", "detail", "remedy": "compact"}`;
  thin `_respond_list_corrupted()` wrappers on both handler classes.
  Catches present at `:247` (named GET item), `:318` (named GET),
  `:565` (listall, all three format branches wrapped), `:1148` (bulk POST),
  `:1279` (list DELETE), `:1631` (`/items` GET).
- `actingweb/handlers/properties.py:636-646` — the PUT `?index=N` padding
  loop is gone; `index > length` → **404**, `index == length` → append,
  otherwise bounds-checked replace. Matches the spec, as the plan's own
  correction noted.
- `actingweb/handlers/properties.py:1078-1121` — bulk POST classify-then-
  two-pass: updates first in given order, deletes last in **descending**
  index order, with the semantics documented in both the method docstring
  (`:795-806`) and inline.
- `actingweb/handlers/properties.py:1626-1643` — `/items` GET returns
  `{"items": [{"index": i, "item": …}], "count": n}` via
  `to_indexed_list()`.
- `actingweb/handlers/www.py:363-369` — `ListCorruptionError` renders an
  inline notice, ordered before the generic `except Exception`.
- `actingweb/interface/integrations/flask_integration.py:386-401` — the
  `/items` GET/POST route is registered before the `<path:name>` catch-all.
- `actingweb/actor.py:2528-2535, 2566-2574` — resync catches
  `ListCorruptionError`: the single-subtarget branch returns `{}` (the
  request *is* that list), the all-lists branch `continue`s so other lists
  still resync.

**Tests verified:**

- `tests/test_property_list_integrity.py::TestFailFastReads` — six cases
  including the important negative one
  (`test_getitem_out_of_range_raises_plain_index_error_not_corruption`),
  which is what makes the new exception type meaningful rather than a
  blanket rename.
- `tests/integration/test_property_list_http_contract.py` — `/items` shape,
  update/delete round-trips, 409 on every serving path, the bulk-POST
  mixed-index delete regression, PUT-beyond-length 404.
- `tests/integration/test_flask_items_route_parity.py`,
  `tests/integration/test_www_list_corruption.py`, and the resync coverage in
  `test_property_list_repair.py`.

**Deviations from plan:** the six recorded in the plan's notes, all verified
present and correctly argued (notably: 404 not 400 for PUT beyond length,
`__getitem__` being the one method that needed changing, and docs updated in
this phase rather than deferred).

### Phase 4: v2 storage format — fractional rank keys — VERIFIED

**Changes verified:**

- `pyproject.toml:50` — `fractional-indexing = "^0.1.3"` as a required
  dependency; also present in `docs/requirements.txt` (needed by the
  autodoc build).
- `actingweb/db/protocols.py:185-253` — `get_range()` and
  `create_if_not_exists()` on the protocol, with the inclusive-bounds and
  sentinel-upper contract spelled out.
- `actingweb/db/dynamodb/property.py:483-522` — `get_range()` via
  `Property.name.between()` (PynamoDB auto-paginates), `attributes_to_get`
  honouring `keys_only`, consistent read, faults wrapped in `DbError`. The
  docstring records *why* `between()` and not `>=`/`<`.
- `actingweb/db/postgresql/property.py:474-517` — range comparison with
  `COLLATE "C"` on **both** the `>=` and `<=` operands (not just an ORDER BY,
  which would have left the WHERE clause collation-dependent). No `LIKE`, so
  no metacharacter surface — this is what closes the `%`-named-list
  cross-property read the security review flagged.
- `actingweb/db/*/property.py` `create_if_not_exists()` — DynamoDB
  `save(condition=Property.id.does_not_exist())` mapping
  `ConditionalCheckFailedException` → `False`; PostgreSQL
  `INSERT … ON CONFLICT DO NOTHING` + `rowcount == 1`. Both share a
  `_serialize_property_value()` helper that returns `None` for
  would-be-empty values so a conditional create can't silently become a
  delete.
- `actingweb/db/postgresql/migrations/versions/e5f6a7b8c9d0_*.py` — revision
  chain `d4e5f6a7b8c9 → e5f6a7b8c9d0`, metadata-only `ALTER … TYPE TEXT`,
  downgrade back to `VARCHAR(255)` documented as intentionally failing on
  over-long names. `schema.py` updated to `Text` so autogenerate won't
  propose reverting it.
- `_should_index_property()` on both backends additionally excludes
  `name.startswith("list:")`.
- `actingweb/property_list.py` v2 core: `_format()`/`_is_v2()` dispatch
  (`:120-132`), item rows at `list:{name}-#{rank}` with bounds
  `("list:{name}-#", "list:{name}-$")` (`:149-158`), per-instance rank cache
  (`:160-174`) shared by mutations, one-range-query `_v2_load_full()`
  (`:176-187`), `__len__` from the cached range (`:432-433`), `__iter__`
  materialising via one query rather than N `__getitem__` calls (`:671-672`),
  single-write `_v2_delitem` (`:580-600`), conditional-write
  `_v2_append`/`_v2_insert` with the 180-char cap (`:675-700`, `:916-948`),
  `prime_from_rows()`/`to_list_from_rows()` v2 variants (`:322-352`).
- `_v2_touch_metadata()` (`:509-523`) is called from all four v2 mutation
  entry points — the fix for the append-only-list-is-invisible bug the plan
  records as caught by the test run.
- Name validation lives in `_load_metadata()` (`:225-232`) and fires only on
  the no-metadata-row (new list) path, so pre-existing `#` names stay
  readable.

  **Correction (same day, after PR review):** I originally recorded here
  that the byte-range isolation argument holds. It does not, and I checked
  too narrow a set of cases. `-` (0x2D), digits (0x30+) and the `m` of
  `-meta` do all sort above the `$` (0x24) sentinel, so a v2 list's own v1
  rows, its meta row, and differently-named siblings are excluded — but a
  **legacy list whose name contains `#`** is not. `list:foo-#bar-0`, a row
  of a pre-existing list named `foo-#bar`, sorts inside
  `["list:foo-#", "list:foo-$"]` and was therefore read, and deleted, as if
  it belonged to a v2 list named `foo`. The name ban only binds new lists,
  and migration deliberately refuses `#` names, so such lists persist by
  design. Caught by the Codex review on PR #121 and fixed after this
  verification — see the addendum at the end of this document.

**Tests verified:**

- `tests/integration/test_property_list_v2.py` — full behavioural parity
  against a plain Python list, run per-backend via `DATABASE_BACKEND`.
- `tests/test_property_list_integrity.py::TestV2ConditionalWriteCollision` —
  a `StaleReadPropertyDb` that hides one row on the first `get_range()`,
  forcing a **real** collision; asserts ≥2 range calls, the final list
  contents, and that the pre-existing row was not overwritten. This is a
  genuine retry-path exercise, not a mock assertion.
- `::TestV2RankCapAndCompact` — builds a real over-cap bisection pair,
  asserts the clean `RuntimeError`, asserts the list is **unchanged**, then
  that `compact()` rebalances.
- `::TestV2QueryCountGuard` and `tests/test_hot_path_n_plus_one.py` — the
  latter now patches `DbProperty.get_range`/`.get` to raise if called after
  priming (a hard zero-query assertion, not a call-count heuristic) and adds
  `test_to_list_is_one_range_query` on a 20-item list.
- `tests/integration/test_db_property_range.py` — bounds, keys-only, the
  sibling-prefix isolation case (`list:foo-x-#…` must not leak into `foo`),
  and conditional-create collision.

**Deviations from plan:** all recorded ones verified present and sound. The
`get_range()` inclusive-upper change is genuinely forced by DynamoDB's
KeyConditionExpression rule and is unobservable given the sentinel; the
fresh-reread retry (rather than jitter) is strictly better than what the plan
specified.

### Phase 5: Migration v1→v2, docs, release — VERIFIED

**Changes verified:**

- `actingweb/property_list.py:1290-1420` — `migrate_to_v2()` implements the
  plan's six steps **plus** the added step 3 (clear leftover v2-range rows
  before writing fresh ones), which is what makes a re-run convergent when
  the v1 list changed length between attempts. Refusal on `#` names logs and
  returns `{"migrated": False, "reason": "name_contains_hash"}` with the list
  still serving v1. Step 5 re-reads the meta row so
  description/explanation/created_at survive.
- `actingweb/property_list.py:1422-1449` — `_maybe_lazy_migrate()` bounded at
  50 items, failures logged and swallowed. Wired into exactly `append`,
  `insert`, `__setitem__`, `__delitem__` (verified by reading each method's
  first statement); `extend`/`pop`/`remove` inherit it by delegation. No read
  path calls it.
- `actingweb/property_list.py:415-419` — `get_metadata()` dispatches to
  `len(self)` for v2 (the plan-recorded bug where it returned 0 for every
  non-empty v2 list).
- `scripts/migrate_property_lists.py` — dry-run default, `--migrate`,
  `--downgrade ACTOR_ID/LIST_NAME` as a script-local function, refusal
  reporting, checkpoint/rate-limiter shapes matching the verify script.
- **Both scripts' checkpoint fix is present and correct:**
  `scripts/verify_property_lists.py:233` and
  `scripts/migrate_property_lists.py:306` both construct
  `Checkpoint(args.checkpoint_file if <mutating flag> else None)`, so a
  dry-run leaves no checkpoint for the follow-up run to skip past.
- `scripts/verify_property_lists.py:126-186` — format dispatch on
  `report.get("format") == 2` for both logging and the repair gate; the v1
  `report["missing_indices"]`/`["orphan_indices"]` indexing is inside the v1
  branch only. All six direct `report["…"]` sites in `property_list.py`
  (`:1253`, `:1276` in `compact()`; `:1351`, `:1404`, `:1418`, `:1419` in
  `migrate_to_v2()`) are inside v1-only code paths reached after an
  `_is_v2()` dispatch, and
  `migrate_property_lists.py:163`'s is on a v1 report by construction.
- `docs/guides/property-lists.rst` — the "Storage Format (v1 / v2)" section,
  the migration paths, and a warning box that now includes the **Order
  matters** paragraph (roll the app back *before* running `--downgrade`,
  because a ≤50-item downgraded list is a lazy-migration candidate again).
- `CHANGELOG.rst` — `Unreleased` empty at the top, `v3.13.0rc5: August 9,
  2026` below it with a leading note and explicit breaking-change callouts.
- Version files: `pyproject.toml:3` and `actingweb/__init__.py:1` both
  `3.13.0rc5`. They match each other; the tag is a post-merge step.
- `thoughts/todo/attribute-list-shift-design.md` created;
  `thoughts/todo/property-list-delete-leaves-holes.md` deleted.

**Tests verified:**

- `tests/integration/test_property_list_migration.py` — 17 tests including
  both idempotency scenarios. `test_rerun_after_v1_mutation_between_attempts_is_convergent`
  is the one that matters and it exercises the real scenario (interrupted
  migration → v1 mutation → re-run), not just kill-and-retry.
- `tests/integration/test_migrate_property_lists_script.py::TestMainCommandLineWorkflow`
  and the equivalent in `test_verify_property_lists_script.py` — these call
  `script.main()` with a patched `sys.argv` and assert the dry-run leaves
  **no** checkpoint file and that the follow-up `--migrate`/`--repair` run
  actually does the work. Read in full; they would fail without the fix.
- Lazy-trigger coverage spans all four call sites, the 50/51 boundary,
  read-paths-never-migrate, and failed-migration-doesn't-fail-the-mutation.

**Deviations from plan:** all recorded ones verified. The added step-3
cleanup and the per-actor (rather than segmented-scan) script model are both
improvements on what the plan specified.

## Remaining Tasks

> **Superseded later the same day** — every item below except the post-merge
> release checklist was resolved after this section was written. See the
> addendum at the end of this document; this list records the state at the
> time of verification, per the snapshot convention.

- [ ] **Phase 1 manual repro** (`reverify_real_dynamo.py` scenarios 1–2).
      **Cannot be run as written**: the harness does not exist anywhere in
      the repository or its git history — it was a scratch file from the
      research session. See "Issue 3" below for the explicit
      accept-or-reconstruct decision this needs from the maintainer.
- [ ] **Phase 3 manual**: `docs/guides/property-lists.rst` examples exercised
      by hand against a running dev app (FastAPI and Flask). Not done in this
      session. The examples are illustrative snippets, not doctested, so
      nothing automated substitutes. The Flask `/items` route specifically has
      only an in-process `test_client()` parity test, never a live server —
      that is the one worth ten minutes of manual confirmation before merge.
- [ ] **Release checklist** (CLAUDE.md): version files match (verified);
      CI green on both backends and tagging the master merge commit happen
      after human review — post-merge by design, not an omission.
- [ ] Consider the two findings below (bulk-POST padding; `/items` POST 409).

## Issues Found

### Issue 1: Bulk `POST /properties` still pads with unbounded `append(None)`

**Severity:** Medium
**Location:** `actingweb/handlers/properties.py:1081-1083`
**Description:** Phase 3 removed the unbounded padding loop from the PUT
`?index=N` path, calling it out in the code comment as "both a DoS vector and
a spec violation". The identical loop survives in the bulk list-item POST
path:

```python
while len(list_prop) <= index:
    list_prop.append(None)
```

The batch validator (`:1042-1062`) checks only that `index` is an `int` and
`>= 0` — there is no upper bound. A caller with write permission on the
property can POST `{"notes": {"items": [{"index": 100000000, "x": 1}]}}` and
drive 100 million individual database writes from a single request. Under v2
each of those is also a conditional write plus a metadata touch.

This is pre-existing behaviour, not introduced by this branch — but the plan
identified the pattern, fixed one of its two occurrences in this same cycle,
and the CHANGELOG advertises the PUT bounds rule as a hardening change, which
makes the surviving copy easy to mistake for already-fixed.

**Recommendation:** apply the same rule as PUT — reject `index > len(list_prop)`
in the validation loop with a 400 (bulk POST has no 404-vs-400 spec
constraint), or at minimum cap the padding. Either is a small change to the
validation loop already at `:1042-1062`.

### Issue 2: `/items` POST does not return the structured 409

**Severity:** Low
**Location:** `actingweb/handlers/properties.py:1698-1811`
**Description:** The plan's Phase 3 named "`/items` GET/POST" among the paths
that must catch `ListCorruptionError` and return 409, and `CHANGELOG.rst`
lists `GET/POST /properties/<name>/items` among those paths. The GET has the
catch (`:1631`); the POST does not — its only handler is the trailing
`except Exception` (`:1806`), which would render a corruption as a generic
500 "Error processing list item".

Practically unreachable today: none of the three POST actions (`add`,
`update`, `delete`) traverses a read path that raises — `append()`,
`__setitem__` and v1 `__delitem__` never do, and the bounds checks use
`len()`, which reads metadata only. So this is a documented-contract vs
implementation mismatch rather than an observable bug.

**Recommendation:** add the two-line `except ListCorruptionError as e:
self._respond_list_corrupted(name, e); return` before the generic handler at
`:1806`, so the contract holds if a future action ever reads items.

### Issue 3: Phase 1's manual verification item cannot be run as specified

**Severity:** Low (process, not code)
**Location:** thoughts/plans/2026-08-08-property-list-index-integrity.md:153
**Description:** Commit 55311a0 deliberately left this item unchecked and
addressed the decision to whoever reviews before merge. Verifying it now:
`reverify_real_dynamo.py` exists neither in the working tree nor anywhere in
git history (`git log --all --diff-filter=A -- '*reverify_real_dynamo*'` is
empty) — it was a research-session scratch harness. Re-running it therefore
means reconstructing it first.

**Recommendation:** accept the automated coverage as the substitute, and say
so explicitly rather than leaving the box ambiguous. The two bug classes the
repro targeted are covered by real regression tests that were confirmed to
have teeth in this pass:
`tests/test_property_list_integrity.py::TestDeleteReadFailurePropagates`
(injected read error raises and does not destroy the successor) and
`tests/integration/test_property_lists_advanced.py` +
`tests/integration/test_db_property_handle.py` (insert into a non-empty list;
one handle serving two rows). That is a strictly more durable substitute than
a one-off script — it just is not the same act, which is why this is the
maintainer's call and not mine.

### Non-issue, noted for the record

`scripts/verify_property_lists.py:283-287` unlinks the checkpoint file
without gating on `--repair`, unlike `migrate_property_lists.py:299-301`
which gates on `--migrate`. Harmless: the unlink only fires when the sweep
found zero unhealthy lists and zero errors, in which case there is nothing
left for a resumed repair run to do. Worth knowing about only if the unlink
condition is ever loosened.

Also noted: `actingweb/handlers/www.py:279, 842, 982, 1125` still interpolate
`str(e)` into 500 messages on list paths. The plan scoped the sanitization to
`handlers/properties.py`, and the exception these paths can now newly see —
`DbError` — is sanitized by construction (`"database error during {op} for
actor {id}"`), so no backend internals leak. Not a defect against the plan;
mentioned so a future pass knows these sites exist.

## Overall Assessment

The implementation is complete and matches the plan, and the plan's own
Implementation Status notes are accurate — every numeric claim I re-checked
(2706/26 on DynamoDB, 813/18 on PostgreSQL, clean ruff/pyright/sphinx)
reproduced exactly, and every deviation the notes record is present in the
code and correctly argued. The parts most likely to be wrong in work of this
shape — the conditional-write retry loop, migration idempotency across an
interrupted attempt, and the two scripts' `main()` checkpoint lifecycle — all
have regression tests that exercise the real failure, not a mock of it. I read
those tests rather than trusting their names, and they have teeth.

Where this verification fell short is recorded in the addendum below: I
re-derived the bytewise range-isolation argument the whole v2 design rests on
and concluded it held, having checked only same-list and
differently-named-sibling rows. A PR review found the case I missed — a legacy
list whose *name* contains `#` — which was a live data-loss path. Three other
concurrency-and-interruption defects came from the same review. The lesson is
narrow and worth naming: I verified the isolation argument against the cases
the code's own comment enumerated, which is not the same as verifying it
against the input space.

Two code findings, neither a blocker. The `/items` POST 409 gap (Issue 2) is
a contract-vs-implementation mismatch with no reachable trigger today — a
two-line fix worth taking because the CHANGELOG already claims it. The
bulk-POST padding loop (Issue 1) is the one I would fix before merge: it is
the same unbounded-write DoS the plan explicitly identified and fixed on the
PUT path in this very cycle, and leaving one of two copies standing is the
kind of thing that reads as intentional six months from now. Both are small,
localized changes in a file this branch already touches heavily.

The remaining question is procedural, not technical: Phase 1's manual DynamoDB
repro cannot be run without reconstructing a harness that no longer exists,
and Phase 3's live-app docs walkthrough was not done. My recommendation is to
accept the automated coverage for the former (explicitly, in writing) and to
spend ten minutes on the latter for the Flask `/items` route in particular,
since its only coverage is an in-process test client rather than a live
server. Neither blocks the merge on its own.

---

## Addendum: PR #121 review round (same day, after the verification above)

The verification above inspected commit `55311a0`. Everything below happened
after it, on the same branch, and is recorded here rather than in a second
verification document because it is the same thread of work — but the
`verified:` link on the plan points at the state I actually inspected, not at
these fixes.

CI on PR #121 was green on both backends (2689/2617 passed, no flakes) and an
automated Codex review raised five P1 comments. Four were real and are fixed;
one is real and is deliberately not fixed. My own two findings above are also
fixed. Dispositions:

| # | Comment | Disposition |
|---|---|---|
| C | Legacy `#`-named sibling lists fall inside a v2 list's range | **Fixed** |
| A | `migrate_to_v2()` trusts cached metadata | **Fixed** |
| D | Positional v2 set/delete act on a stale rank cache | **Fixed** |
| E | Both bulk scripts checkpoint actors that did not succeed | **Fixed** |
| B | `_v2_compact()` exposes new rows before retiring old ones | **Declined, documented, todo filed** |
| Issue 1 | Bulk-POST unbounded `append(None)` padding | **Fixed** |
| Issue 2 | `/items` POST returns 500 not 409 on corruption | **Fixed** |

### C — legacy `#`-named sibling isolation (data loss)

The most serious of the five, and the one this verification wrongly cleared
(see the correction in the Phase 4 section above). A pre-existing list named
`foo-#bar` stores rows inside the byte range a v2 list named `foo` reads, so
`foo` returned the sibling's items as its own, and `foo.clear()`,
`foo.delete()` and migrating `foo` deleted the sibling's rows.

Byte range alone cannot separate them, so isolation now also requires the key
after the `#` marker to be a well-formed rank. Rank keys are pure base62;
every v1 row name ends in `-{digits}` or `-meta`, and `-` is not in that
alphabet, so the check is exact rather than heuristic. Applied at all six
consumers of the range: `_v2_ensure_rank_cache`, `_v2_load_full`,
`prime_from_rows`, `to_list_from_rows`, `_v2_item_names_in_range` (the
destructive one) and `migrate_to_v2`'s step-3 clear. `prime_from_rows` and
`to_list_from_rows` match row names in Python over a bulk partition dump
rather than issuing a range query, and needed the same filter — easy to miss.

Covered by `TestV2LegacyHashSiblingIsolation` (5 tests: reads, primed reads,
`clear()`, `delete()`, migration). All five fail against the pre-fix code.

### A — `migrate_to_v2()` trusting cached metadata (data loss)

`_is_v2()` read a possibly-cached metadata dict. If another instance migrated
the list after that cache was populated, migration proceeded down the v1 path,
`verify()` saw every index as a hole, and step 3 deleted the now-authoritative
v2 rows before writing an empty list over them. Metadata is now invalidated
and re-read before the decision, and the meta row is read once more —
directly, not through the cache — immediately before the first destructive
write, since the gap between the two spans two partition reads. Covered by
`TestMigrateToV2StaleMetadata`, which fails against the pre-fix code.

### D — stale rank cache on positional mutations (data loss)

`_v2_setitem`/`_v2_delitem` resolved a position through a per-instance rank
cache that can be arbitrarily old. After another writer inserts an item
earlier in the list, position `i` names a different row than the cache says,
so the wrong item was overwritten or deleted, with no missing-row retry to
catch it. Both now force a fresh rank read. `append`/`insert` deliberately
keep using the cache: their conditional writes bound the effect to where an
item lands, never to destroying a different one. Covered by
`TestV2StaleRankCacheOnPositionalMutation`, which fails against the pre-fix
code.

### E — checkpoint masking (silent under-reporting)

Both bulk scripts marked an actor done regardless of outcome, so an actor with
an errored or refused list (migration) or one still unhealthy after `--repair`
(verification) was skipped by the next run, which then saw no problems,
deleted the checkpoint and exited 0. Only fully successful actors are
checkpointed now; a refused `#`-named list keeps its actor out of the
checkpoint until an operator renames it, which is the intended nag. Covered by
one new test per script, both of which fail against the pre-fix code.

While adding them, both files' `main()` tests turned out to be
parallel-fragile for an unrelated reason: `main()` sweeps every actor in a
database shared with other xdist workers, so its exit code depended on
unrelated actors' lists. They passed by luck. All four now patch the actor
listing to the test's own actor, which keeps argparse, the sweep loop and the
checkpoint lifecycle under test while making the outcome deterministic.

### B — `_v2_compact()` crash window (declined, with reasons)

Correct as reported: `compact()` writes every item under its new rank before
retiring any old row, so a crash in between leaves both copies readable, and
re-running does not recover — it treats all `2n` rows as genuine items.

Not fixed, because the obvious fix is worse. The reviewer's implied
alternative — retire each old row as its replacement is written — trades a
detectable failure for an undetectable one. Targets are always `a0, a1, …`
while existing ranks may sort anywhere (a list built by repeated `insert(0, …)`
has ranks below `a0`), so renaming item 0 to `a0` and immediately deleting its
old row puts item 0 *after* items 1..n-1. A crash there leaves a silently
permuted list that `verify()` reports as healthy. Duplicate residue at least
shows up in the data.

A genuinely recoverable protocol (most likely a compaction journal row) is a
design change, not a patch. The window is now documented in `_v2_compact()`'s
docstring and in `docs/guides/property-lists.rst` — including how an operator
tells stale copies apart — and the redesign is filed as
`thoughts/todo/v2-compact-staged-commit.md`. Reachability is low: under v2,
`compact()` is an operator-invoked rank rebalance, not on any request path.

### Issue 1 — bulk-POST index bound

The first attempt (bound every index against the pre-batch length) was wrong
and the existing intra-batch-ordering test caught it: a batch legitimately
populates an empty list with indices `0, 1, 2, 3`. The bound is now a running
projection over the updates in request order — an index may address an
existing item or append at exactly the length the list will have when that
update runs — and it is checked during validation, so an out-of-bounds index
rejects the batch before anything is written.

### Verification of the fixes

- `ruff check` / `ruff format --check` clean; `pyright` unchanged (same single
  pre-existing `scripts/migrate_db.py` dotenv error).
- Every new regression test was run against the pre-fix code and confirmed to
  fail: 5/5 for C, 1/1 for A, 2/2 for D, 1+1 for E.
- Full parallel suite on DynamoDB: **2719 passed, 26 skipped**.
  `tests/integration/` on PostgreSQL: **818 passed, 18 skipped**.
- `sphinx-build -W --keep-going` clean after the docs edits.

### The two manual checklist items, now closed

Both plan checkboxes the earlier commit deliberately left open are now
resolved, and the plan records how:

- **Phase 1's DynamoDB repro** — closed by explicit acceptance. The harness
  does not exist to re-run (confirmed against the full git history), and the
  regression tests that replaced it were verified to fail against the pre-fix
  code.
- **Phase 3's live-app walkthrough** — actually done, not accepted. A live
  Flask server and a live uvicorn/FastAPI server (real HTTP, not the
  in-process test clients the suite uses) against dynamodb-local, walking
  every REST example in `docs/guides/property-lists.rst`: 23 checks per
  integration, all passing.

  It earned its keep: the guide documented every operation on a list but
  never how to *create* one over REST, and `POST /items` against a
  non-existent list is a 404 — so the documented flow could not be followed
  end to end. Fixed by adding the `{"_type": "list"}` creation example. The
  automated suite could not have caught this; its fixtures create lists
  through a helper, so the gap is invisible from inside the tests.

### Second review round: a seventh consumer, in the emergency downgrade tool

After the fixes above were pushed, both reviewers were re-triggered explicitly
— neither re-runs on a push (`claude-code-review.yml` is configured
`types: [opened]`, and Codex needs an `@codex review` mention). The re-review
prompt asked directly whether a seventh consumer of a v2 list's storage range
existed, since the whole isolation argument had already been wrong once.

It did. `downgrade_to_v1()` in `scripts/migrate_property_lists.py` deleted the
v2 rows by computing `_v2_bounds()` and issuing its own raw `get_range()`,
bypassing `_v2_item_names_in_range()` and therefore the rank-shape filter. The
cleanup loop deletes every row it is handed, so `--downgrade <actor>/foo` on an
actor that also has a legacy list named `foo-#bar` silently deleted that
sibling's items and metadata — the identical failure mode as the original
finding, reintroduced by a call site outside `property_list.py`.

Now routed through the filtered helper. Covered by
`test_downgrade_does_not_delete_a_hash_named_sibling_list`, confirmed to fail
against the pre-fix code.

Two things worth drawing out of this, since it is the second time the same
argument failed:

- **My exhaustiveness claim was scoped to a file, and I did not say so.** The
  fix and the addendum above both say "all six consumers of the range". That
  was true of `actingweb/property_list.py` and false of the repository —
  `scripts/` reaches into the same private helpers with a `noqa: SLF001`
  escape hatch, which is exactly the kind of call site a within-module audit
  does not see. A grep for `_v2_bounds|get_range(` across `actingweb` **and**
  `scripts` finds it immediately; that is the check I should have run and did
  not. Re-run now: three consumers in `property_list.py` (all filtered) and no
  others.
- **Asking the reviewer to attack a specific claim worked better than asking
  it to review.** The finding came back against the exact question posed. The
  generic review of the same code an hour earlier did not surface it.

The re-review also independently re-derived and confirmed the three arguments
it was asked to challenge: the shape filter is exact rather than merely
sufficient (`PropertyStore` rejects any key starting with `list:`, closing the
crafted-scalar-property path around it); the `insert`/`append` versus
`setitem`/`delitem` asymmetry is structural, since the former write
conditionally and can only misplace; and the `_v2_compact()` trade holds. It
added one observation now recorded in the todo — a crashed compact roughly
doubles the reported length, which is a coarser but far more reliable signal
than the adjacent-duplicate heuristic, since an item's old and new ranks need
not sort adjacently.

Codex had not re-reviewed at the time of writing.
