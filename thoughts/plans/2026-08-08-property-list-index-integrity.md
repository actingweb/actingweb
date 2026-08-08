---
status: active
---

# Implementation Plan: Property-list index integrity — fixes, repair, and fractional-key storage

**Date:** 2026-08-08
**Research:** thoughts/research/2026-08-07-property-list-index-integrity.md,
thoughts/research/2026-08-08-property-list-index-integrity-review.md
**Branch:** master (work branches off per phase or as one feature branch)
**Release vehicle:** 3.13.0 rc series (3.13.0rc5)

## Overview

`ListProperty` corrupts data: its delete/insert shift loops are interruptible
multi-write sequences over a stored length counter, backend error-swallowing
turns transient faults into silent data destruction, and `insert()` on DynamoDB
destroys data on every call into a non-empty list. This plan fixes the error
handling and `insert()` bug, adds repair/detection, converges reads on
fail-fast, fixes the `/items` REST contract, and replaces the storage format
with fractional (rank) keys so that delete/insert become single writes with no
shift loop, no stored counter, and no crash or concurrency window.

## Decisions Made

All settled with the maintainer (recorded in the 2026-08-08 review doc and this
planning session):

- **`insert()` fix — both halves**: fresh handles at the call site AND the
  DynamoDB backend honours `name` against the cached handle, plus protocol
  docstring clarification. The hot-path objection was retired (one key
  comparison).
- **Reads converge on fail-fast**: holes raise, matching `ListAttribute`'s
  documented contract. Repair (`compact()`) ships before the read change.
- **Scope — everything in one cycle**: error handling, repair, fail-fast,
  `/items` contract, and the fractional-key migration. The zero-padding
  waypoint is skipped (buys little; see review doc).
- **`compact()` duplicate policy**: repairs holes (provably content-safe),
  reports duplicate residue, never rewrites duplicates silently.
- **`/items` index space — storage indices** on both read and write.
- **`ListAttribute` — follow-up cycle**: not migrated here; gets a todo.
- **Release — fold into the 3.13.0 rc series** as 3.13.0rc5.
- **PostgreSQL prefix reads use range comparison, not LIKE**
  (`name >= 'list:{n}-#' AND name < 'list:{n}-$'`, `COLLATE "C"`): eliminates
  the metacharacter authorization bypass without banning `%`/`_` in list names
  (which would break existing names like `run_records`). Only `#` is banned.
- **Keep the meta row** in v2 (existence/discovery/description/explanation +
  `format` marker); only the stored `length` stops being authoritative.
- **v2 caches the sorted rank-key list per instance**; `to_list`/`__iter__`
  are one range query. Rank ordering is compared bytewise in Python on both
  backends (no SQL-collation dependence).
- **Lazy migration bounded to ≤ 50 items, mutation paths only**; larger lists
  migrate via the bulk script. Migration order: write v2 rows → flip meta →
  delete v1 rows; ranks are derived deterministically from v1 indices so
  interrupted or concurrent migrations are idempotent and convergent.
- **Corruption error contract**: structured 409 with a `compact` remedy hint;
  backend exception text never reaches HTTP bodies.
- **Downgrade after migration is unsupported** (documented loudly); the bulk
  script provides an emergency `--downgrade` converter.

## What We're NOT Doing

- **`ListAttribute` format migration** — same shift design exists in
  `attribute_list.py:286-389`; deferred to a follow-up cycle
  (`thoughts/todo/attribute-list-shift-design.md` created in Phase 5). Its
  exposure is lower: fail-fast reads, `RuntimeError`-wrapped writes, internal
  callers only.
- Zero-padded integer keys (Decision 3.4) — dominated; see review doc.
- DynamoDB transactions — unavailable at the sizes that corrupted (100-action
  cap vs 403 needed).
- Sentinel values at holes, or a `strict=` compatibility flag.
- Online rank rebalancing — a length cap plus `compact()` rewrite suffices.
- An HTTP repair endpoint — repair is library API + operator script only.
- Changing the subscription diff wire format — positions stay the public
  semantic; `remote_storage.py:343-420` keeps working unchanged.
- Auditing scalar-property callers that ignore `set()` returning `False`
  outside the list code paths (noted for a future pass).

---

## Phase 1: Error handling + `insert()` fix (P0)

Silent-corruption paths: backend read errors must stop masquerading as "row
absent", write failures must stop no-oping, and `insert()` must stop reusing a
stale handle.

### Changes

- `actingweb/db/exceptions.py` (new) — `DbError(Exception)` with a sanitized
  message (`"database error during {op} for actor {id}"`), original exception
  chained via `raise ... from e`. Exported from `actingweb/db/__init__.py`.
- `actingweb/db/dynamodb/property.py`
  - `get()` (`:144-158`): both branches catch only `Property.DoesNotExist`
    (→ `None`); any other exception is wrapped in `DbError` and raised. Applies
    to the `handle.refresh()` branch and the fresh `Property.get()` branch.
  - `get()`/`set()`: if `self.handle` is set and
    `(str(handle.id), str(handle.name)) != (actor_id, name)`, discard the
    handle and take the fresh path. This fixes the class-level cached-handle
    bug and, together with the `get()` fix, closes the silent delete-skip in
    the `set(value=None)` path (`:306-310`).
  - `set()`: wrap `handle.save()` exceptions in `DbError`.
- `actingweb/db/postgresql/property.py`
  - `get()` (`:63-101`): backend exceptions raise `DbError` instead of
    log-and-return-`None`. No-row remains `None`.
  - `set()` (`:230-307`): keeps the bool contract (protocol-compatible), still
    logs; callers now check it.
- `actingweb/property_list.py`
  - Every `set()` call site (append `:377`, `__setitem__` `:296`,
    `__delitem__` `:321,338,346`, `insert`, `clear` `:402`, `delete`
    `:420,426`, `_save_metadata` `:137`) checks the return value and raises
    `RuntimeError("list item write failed for '{name}'[{index}]")` on `False`.
  - `insert()` (`:483-523`): replace the three `self._db` uses (`:497,502,514`)
    with fresh `get_property(self.config)` instances, matching every other
    method and `ListAttribute.insert()` (`attribute_list.py:543-641`).
- `actingweb/db/protocols.py` (`:115-171`) — docstrings: `get()` returns
  `None` **only** for absence and raises `DbError` on backend failure; `set()`
  returns `False` only on failure; cached `handle` must never override the
  `(actor_id, name)` arguments.
- `actingweb/handlers/properties.py` — the four `str(e)` interpolation sites
  (`:637`, `:1026`, `:1065`, `:1697`) log the exception and return a generic
  message (backend internals must not reach HTTP bodies once errors propagate).

### New Tests

- `tests/test_property_list_integrity.py` (new, unit): dict-backed fake
  patching `actingweb.property_list.get_property` (the pattern proven in the
  research harness — NOT the existing config-attribute mock):
  - a fake whose `get()` raises `DbError` mid-shift → `__delitem__` propagates
    and does NOT decrement length / destroy the successor (regression for the
    read-swallow path);
  - a fake whose `set()` returns `False` → `append`/`__setitem__`/
    `__delitem__` raise `RuntimeError`, metadata length unchanged (regression
    for the PostgreSQL write-swallow tail-hole);
  - interrupted-delete residue assertions (crash-injection fake) documenting
    the remaining crash window ahead of Phase 4.
- `tests/test_db_property_handle.py` (new, unit): a `DbProperty` whose handle
  points at row A must serve `get`/`set` for row B correctly (both backends'
  fakes; DynamoDB integration variant below).
- Integration (both backends): `insert(1, x)` and `insert(0, x)` into a
  **non-empty** (≥3 item) list — full content assertion including the last
  element (the current tests at
  `tests/integration/test_property_lists_advanced.py:160,212` run zero shift
  iterations); DynamoDB regression: one `DbProperty` instance, `get` name A
  then `set` name B, assert both rows correct.

### Verification

- [ ] `poetry run pytest tests/test_property_list_integrity.py tests/test_db_property_handle.py -v` passes
- [ ] `poetry run pytest tests/ -v` (unit) passes
- [ ] `make test-integration` passes on DynamoDB; same suite with `DATABASE_BACKEND=postgresql` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests && poetry run ruff format --check actingweb tests`
- [ ] Manual: re-run the research repro (`reverify_real_dynamo.py` scenarios 1-2) against the fixed code — insert must produce the correct list; injected read error must raise, not corrupt

### Implementation Status: Complete

**Deviations / notes:**
- `get()`'s `DoesNotExist` catch uses the PynamoDB base
  `pynamodb.exceptions.DoesNotExist` rather than `Property.DoesNotExist`
  specifically — PynamoDB generates a distinct `DoesNotExist` subclass per
  `Model`, and `self.handle` can hold a `PropertyLegacy` instance (set by
  `get_actor_id_from_property()`'s legacy-GSI fallback), so catching only
  `Property.DoesNotExist` would let a legitimate absence on a
  `PropertyLegacy` handle get wrapped as `DbError` instead of returning
  `None`. Catching the shared base is strictly more correct and covers the
  same cases the plan's citation intended.
- A fifth `str(e)` site (`handlers/properties.py`, list-property DELETE,
  originally `:1192`) was sanitized alongside the four the plan named — same
  pattern, same rationale ("backend internals must not reach HTTP bodies"),
  evidently a plan omission rather than a deliberate exclusion.
- `RuntimeError` messages for the `_save_metadata`/`delete()` meta-row write
  checks use `"list metadata write failed for '{name}'"` rather than
  reusing the `[{index}]` suffix verbatim from the plan's quoted item-write
  message — an index isn't meaningful for the metadata row.
- New tests landed as `tests/test_property_list_integrity.py` (unit, dict-backed
  fake) and `tests/integration/test_db_property_handle.py` (integration, not
  `tests/test_db_property_handle.py` as drafted) — PostgreSQL needs its
  migrated schema, which only the `tests/integration/` session fixtures
  provision; DynamoDB self-creates its table on construction so the
  asymmetry only shows up under PostgreSQL. The insert()-into-non-empty-list
  regression was added to the existing
  `tests/integration/test_property_lists_advanced.py` instead of a new file.
- Verified: full suite green on both backends (2630 passed / 26 skipped on
  DynamoDB via `make test-all-parallel`; 2542 passed / 97 skipped on
  PostgreSQL excluding `tests/performance/`, whose 5 failures were confirmed
  pre-existing on master via `git stash` — unrelated to this phase).
  `pyright` and `ruff` clean.

---

## Phase 2: Repair and detection

Repair must exist before reads fail fast (Phase 3) and before migration
(Phase 5) compacts as its first step.

### Changes

- `actingweb/property_list.py`
  - `verify() -> dict` (read-only): via one partition fetch
    (`get_property_list(config).fetch_all_including_lists()`) and the anchored
    pattern `^list:{re.escape(name)}-(\d+)$` (exact digits — immune to the
    `foo`/`foo-bar` name-prefix ambiguity), report: `stored_length`,
    `readable_count`, `missing_indices`, `orphan_indices` (rows ≥ length),
    `adjacent_duplicates` (heuristic), `healthy: bool`. Docstring warns the
    report contains item values only in no case — indices only.
  - `compact() -> dict`: rewrites surviving rows densely, preserves
    `description`/`explanation`/`created_at` (unlike today's
    `clear()`+`extend()` which wipes them via `_create_default_metadata`,
    `:407`), recomputes `length`, deletes orphan rows, returns the `verify()`
    report it acted on. Holes are repaired; adjacent duplicates are left
    intact and reported (settled policy — duplicate residue always means a
    destroyed item; rewriting would bless it).
  - `_load_metadata()` (`:102-126`): unparsable or non-dict metadata now
    raises `ValueError` instead of silently writing a fresh
    `length: 0` default that orphans every row. The "no metadata row" path
    (new list) keeps its current default-create behaviour.
- `actingweb/interface/property_store.py` — `NotifyingListProperty.verify()`
  and `.compact()` pass-throughs. `compact` registers a diff with
  `operation: "metadata"` and the new length — the spec's diff `operation`
  vocabulary is a closed enumeration (`docs/protocol/actingweb-spec.rst:2630`:
  append/insert/update/delete/pop/extend/clear/remove/delete_all/metadata), so
  no new operation name may be introduced; `metadata` signals subscribers to
  re-read. No methods are added to `PropertyListStore` itself (avoids
  shadowing list names via `__getattr__`, `:396-406`).
- `scripts/verify_property_lists.py` (new) — sweeps all actors' lists using
  the scan/rate-limit/checkpoint machinery patterns from
  `scripts/backfill_property_lookup.py:20-25,55-102,159-188`; dry-run by
  default, `--repair` invokes `compact()` on unhealthy lists, always prints a
  per-list report (including duplicate suspects, which `--repair` never
  touches).

### New Tests

- Integration (both backends): punch holes/orphans via direct DB row writes
  (the technique validated in the research harnesses), then:
  - `verify()` reports exact `missing_indices`/`orphan_indices`;
  - `compact()` closes holes, preserves `description`/`explanation`/
    `created_at`, removes orphans, corrects `length`;
  - `compact()` on a duplicate-residue list leaves both rows and reports;
  - `pop()` works again after `compact()` on a trailing-hole list (the
    permanent-wedge case from the research).
- Unit: `_load_metadata` raises on unparsable metadata; existing rows
  untouched (no `length: 0` write).
- Script: smoke test against the test backend (invoke `main()` with dry-run,
  assert report format).

### Verification

- [ ] `poetry run pytest tests/ -v` passes (unit)
- [ ] `make test-integration` (DynamoDB) and PostgreSQL variant pass
- [ ] `poetry run pyright actingweb tests scripts` — 0 errors
- [ ] `poetry run ruff check actingweb tests scripts`
- [ ] Manual: run `scripts/verify_property_lists.py` against a dynamodb-local
      seeded with a punched hole; confirm detection, then `--repair`, then a
      clean re-run

### Implementation Status: Complete

**Deviations / notes:**
- `verify()`/`compact()` operate on v1-format lists only (the only format
  that exists before Phase 4 introduces v2). No format dispatch was needed
  yet.
- `scripts/verify_property_lists.py` sweeps actors via `get_actor_list(config).fetch()`
  (an unpaginated full scan, same limitation `DbActorList.fetch()` already
  has on both backends) rather than the segmented/paginated scan machinery
  `backfill_property_lookup.py` uses for the *properties* table — there is
  no equivalent segmented-scan primitive for the actor list on either
  backend. Rate limiting and a resumable actor-id checkpoint were kept
  (simpler shape: a persisted "done" set rather than per-segment
  `last_evaluated_key`, since the outer loop here is over actors, not
  DynamoDB partitions).
- New tests: `tests/test_property_list_integrity.py` (unit, unparsable-metadata
  cases added to the existing Phase 1 file), `tests/integration/test_property_list_repair.py`
  (verify/compact behavioural coverage), `tests/integration/test_verify_property_lists_script.py`
  (script smoke test, imports the script module directly rather than
  shelling out — same pattern `tests/test_lookup_migration.py` uses for
  `backfill_property_lookup.py`).
- Verified: full suite green on both backends (2639 passed / 26 skipped on
  DynamoDB; 2551 passed / 97 skipped on PostgreSQL excluding
  `tests/performance/`). `pyright` and `ruff` clean. Manual verification
  against dynamodb-local: seeded a list, punched a hole, confirmed
  `verify()` reports it, `--repair` fixed it, and a clean re-run reported
  nothing further.

---

## Phase 3: Fail-fast reads + `/items` storage-index contract

Requires Phase 2 (repair exists). Converts silent skew into a structured,
actionable error, and makes the REST contract self-consistent.

### Changes

- `actingweb/property_list.py`
  - New `ListCorruptionError(IndexError)` carrying list name + index (message
    sanitized: names/indices only).
  - `to_list()` (`:433-445`), `slice()` (`:447-469`), `to_list_from_rows()`
    (`:165-186`): remove the `except IndexError: continue` compaction; missing
    rows raise `ListCorruptionError`. JSON-parse fallback behaviour is
    unchanged. Docstrings converge on `attribute_list.py:473-492`'s contract.
  - `to_indexed_list() -> list[tuple[int, Any]]` added (storage indices; under
    fail-fast identical to `enumerate(to_list())`, but it is the documented
    REST-facing accessor and stays correct under v2).
- `actingweb/handlers/properties.py`
  - Catch `ListCorruptionError` in every list-serving path (named GET `:243`,
    listall `:496-516`, `/items` GET/POST, PUT) → **409** with body
    `{"error": "list_corrupted", "list": name, "detail": str(e),
    "remedy": "compact"}`.
  - `/items` GET (`:1525-1529`): response becomes
    `{"items": [{"index": i, "item": ...}], "count": n}` via
    `to_indexed_list()`.
  - `/items` POST update/delete (`:1637,1642,1672,1677`): unchanged index
    semantics — now provably consistent (bounds check, storage, and the GET
    response all agree once holes cannot be observed).
  - Bulk POST (`:937-1028`): partition the batch — apply updates first (all
    indices interpreted against the pre-batch state), then deletes in
    descending index order. Document the semantics in the handler docstring.
  - PUT `?index=N` padding loop (`:597-598`): replace with the
    spec-mandated semantics (`actingweb-spec.rst` "List Property PUT"):
    `index == length` MAY create (append); `index > length` MUST return 404.
    This removes the unbounded `append(None)` padding (a DoS vector AND a
    spec violation today) — stricter than the previously considered
    cap-at-len+1000, and it is what the protocol requires. Breaking-change
    note in CHANGELOG.
- `actingweb/handlers/www.py` (`:351-352`): wrap `to_list()` in
  `try/except ListCorruptionError` → render an inline corruption notice
  instead of a 500.
- `actingweb/interface/integrations/flask_integration.py` — add the
  `/<actor_id>/properties/<name>/items` GET/POST route for parity with
  FastAPI (`fastapi_integration.py:1007-1008`), dispatching with `items=True`
  like the existing property routes (`:386-388` pattern).
- `actingweb/actor.py` (`:2508-2568`): wrap the full-state list iteration in
  `try/except ListCorruptionError` → log and skip that list in resync rather
  than aborting the whole subscription pass.

### New Tests

- HTTP integration (FastAPI + the new Flask route):
  - `/items` GET returns the indexed-pair shape; `count` matches.
  - `/items` POST `action=update` and `action=delete` round-trip correctly
    (first-ever HTTP tests for these branches).
  - Punch a hole → GET `/items`, GET `/properties/{name}`, and listall
    `format=full` all return 409 with the structured body; after `compact()`
    they return 200.
  - Bulk POST with multiple deletes at mixed indices deletes exactly the
    intended pre-batch items (regression for the intra-batch skew).
  - PUT `?index=` beyond the cap → 400.
- Unit: `to_list`/`slice`/`to_list_from_rows` raise `ListCorruptionError` on a
  hole (fake-backed); `to_indexed_list()` shape.
- www integration: holed list renders the notice, not a 500.
- Resync: actor full-state build with one holed list still emits the other
  lists.

### Verification

- [ ] `poetry run pytest tests/ -v` and `make test-integration` (both backends) pass
- [ ] `poetry run pyright actingweb tests` — 0 errors; `ruff` clean
- [ ] Manual: `docs/guides/property-lists.rst` examples exercised by hand
      against a running dev app (FastAPI and Flask)

### Implementation Status: Complete

**Deviations / notes:**
- Confirmed against `docs/protocol/actingweb-spec.rst` ("List Property PUT",
  line 1040): `index > length` returns **404**, not the 400 the New Tests
  bullet said — that line was residue from the abandoned cap-at-len+1000
  design (advisor caught this before writing the test).
- `__getitem__` is the one method not named in the plan's Changes list that
  needed to change: it now raises `ListCorruptionError` (an `IndexError`
  subclass) specifically when an in-range row is missing from storage, vs
  plain `IndexError` for genuine out-of-range access. `to_list()`/`slice()`/
  `to_list_from_rows()` simply stopped catching `IndexError` around
  `self[i]` (mirroring `attribute_list.py:473-492`'s existing pattern) —
  they inherit the right exception type from `__getitem__` rather than
  needing their own corruption detection.
- `_write_list_corrupted_response()` is a module-level function in
  `handlers/properties.py`, not a single method — `PropertiesHandler` and
  `PropertyListItemsHandler` are separate classes with no shared base for
  this, so each gets a thin instance-method wrapper delegating to it.
- Bulk POST intra-batch fix implemented as classify-then-two-pass
  (`pending_updates`/`pending_deletes` lists, updates applied first in
  given order, deletes applied last in descending index order) rather than
  literal partitioning — same effect, avoids a second list comprehension.
- Added a `ListCorruptionError` catch (409) to the list-DELETE hook path
  and the fifth already-sanitized handler site from Phase 1 — not
  explicitly named in the plan's list-serving-paths enumeration, but same
  rationale (a corrupted list must not surface as a raw 500).
- Flask route parity (`/items` GET/POST) required only the route
  registration — `base_integration.py`'s `get_handler_class()` already
  dispatched `items=True` to `PropertyListItemsHandler`; only FastAPI had
  the route wired.
- New tests: unit fail-fast/`ListCorruptionError` coverage and
  `to_indexed_list()` shape added to `tests/test_property_list_integrity.py`;
  HTTP contract tests (`/items` shape, update/delete round-trips, 409
  everywhere, bulk-POST skew regression, PUT 404) in the new
  `tests/integration/test_property_list_http_contract.py`; Flask route
  parity in `tests/integration/test_flask_items_route_parity.py` (Flask's
  in-process `test_client()`, not a live server thread — no such harness
  existed for Flask, and building one to match the FastAPI
  uvicorn-in-a-thread fixture was out of scope for a parity smoke test);
  www corruption notice in `tests/integration/test_www_list_corruption.py`;
  resync skip-only-the-corrupted-list coverage added to
  `tests/integration/test_property_list_repair.py`.
- `docs/guides/property-lists.rst` updated now (GET `/items` shape, the
  404-vs-append PUT rule, the 409 corruption contract) rather than
  deferred to Phase 5 — the REST contract changed in this phase, so the
  docs would otherwise describe behavior that no longer exists.
- Verified: full suite green on both backends (2656 passed / 26 skipped on
  DynamoDB; 2568 passed / 97 skipped on PostgreSQL excluding
  `tests/performance/`). `pyright` and `ruff` clean. `tests/test_hot_path_n_plus_one.py`
  (the primed-list query-count pin) still passes unchanged.

---

## Phase 4: v2 storage format — fractional rank keys

New lists stop using dense integers + stored length. Delete/insert become
single conditional writes; order is derived from key sort; length is counted.

### Changes

- `pyproject.toml` — add `fractional-indexing` (httpie port of
  rocicorp/fractional-indexing, CC0) as a required dependency.
- `actingweb/db/protocols.py` + both backends — new protocol method
  `get_range(actor_id, lower, upper, keys_only=False) -> dict[str, str]`
  (sorted bytewise by name):
  - `actingweb/db/dynamodb/property.py`: `Property.query(actor_id,
    Property.name.startswith(prefix))` (precedent:
    `db/dynamodb/subscription_suspension.py:74-77`); PynamoDB auto-paginates.
  - `actingweb/db/postgresql/property.py`: `WHERE id = %s AND name >= %s AND
    name < %s ORDER BY name COLLATE "C"` — range comparison, **no LIKE**, no
    escaping surface. Final ordering is re-sorted in Python (bytewise) in the
    caller so both backends share one ordering source of truth.
- `actingweb/db/postgresql/migrations/` — new Alembic revision:
  `properties.name` `VARCHAR(255)` → `TEXT` (metadata-only alter; removes the
  binding rank-length constraint, `schema.py:52`).
- `actingweb/property_list.py`
  - Format dispatch on meta `"format"` (absent/`1` → v1 paths as hardened in
    Phases 1-3; `2` → v2 paths). Meta row stays at `list:{name}-meta`
    (existence checks `property.py:20-25` and discovery
    `handlers/properties.py:440-443` keep working); v2 meta has no
    authoritative `length`.
  - v2 item rows: `list:{name}-#{rank}`; prefix bounds
    `("list:{name}-#", "list:{name}-$")` (`$` = `#`+1, bytewise).
  - Per-instance sorted rank-key cache: loaded by one keys-only `get_range` on
    first need; maintained locally by mutations (append/insert know the rank
    they wrote; delete drops one entry). `to_list()`/`__iter__`/`slice()` are
    served from ONE full `get_range` (never per-item queries — the len()-in-
    loop call sites at `handlers/properties.py:597,992,1014` and the iterator
    at `property_list.py:33` must not regress; also drop the `len()` from the
    debug log at `handlers/properties.py:187`).
  - Mutations: `append` = rank after last + conditional write; `insert(i)` =
    rank between neighbours + conditional write; `__setitem__(i)` = overwrite
    the i-th key; `__delitem__(i)`/`pop` = single row delete; `remove` = find +
    single delete; `clear`/`delete` = ranged row deletes + meta. Conditional
    writes: DynamoDB `save(condition=Property.id.does_not_exist())`;
    PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` + rowcount check; on
    conflict, regenerate the rank with jitter and retry (bounded retries).
  - Rank-length cap: 180 chars → `RuntimeError` advising `compact()` (which
    under v2 rewrites with evenly redistributed ranks — rebalancing).
  - List-name validation: **new** lists reject `#` in the name
    (`ValueError` from `ListProperty` creation and mirrored in
    `interface/property_store.py`); existing lists are untouched until
    migration (Phase 5 refuses offenders).
  - `prime_from_rows`/`to_list_from_rows` (`:147-186`): v2 variants hydrate
    the rank-key cache and items from the bulk partition dump (row-name prefix
    match in Python), preserving the primed-path invariant pinned by
    `tests/test_hot_path_n_plus_one.py:110-146`.
  - `verify()`/`compact()` v2 variants (verify = count/order/rank-length
    report; compact = rank rebalance rewrite).
- `actingweb/db/dynamodb/property.py` + `db/postgresql/property.py` —
  `_should_index_property()` additionally excludes names starting with
  `list:` (belt-and-braces so lookup-table sync can never touch item rows).

### New Tests

- Full v2 behavioural suite (unit fake + integration on both backends):
  append/extend/getitem/setitem/delitem/insert/pop/remove/index/count/iter/
  to_list/slice/clear/delete/metadata — mirroring Python list semantics.
- Cross-backend ordering: the same operation sequence yields the same order on
  DynamoDB and PostgreSQL (bytewise rank sort).
- Conditional-write collision: force a rank collision (two writers, same
  neighbours) → retry produces distinct keys, both items present.
- Crash-residue test: kill a v2 delete after its single write → list is fully
  consistent (the entire point).
- Interleaved mutation test: two instances alternating append/delete → no
  corruption (the Phase-independent stale-cache scenario from the review doc,
  now passing under v2).
- Rank cap: repeated bisection insert until cap → clean error; `compact()`
  rebalances; inserts work again.
- Name validation: creating list `foo#bar` raises; existing v1 list named
  `foo#bar` still readable.
- `tests/test_hot_path_n_plus_one.py`: rewrite the list-priming invariants
  for v2 (primed list serves `to_list` with zero extra queries) — rewrite,
  not delete.
- Query-count guard (unit, counting fake): one `to_list()` = 1 range query;
  `/items` POST add flow ≤ 3 queries total.

### Verification

- [ ] `poetry run pytest tests/ -v`, `make test-integration`, PostgreSQL variant — all pass
- [ ] Alembic migration applies cleanly (`alembic upgrade head`) and downgrades
- [ ] `poetry run pyright actingweb tests` — 0 errors; `ruff` clean
- [ ] Manual: performance sanity vs v1 — `to_list()` on a 200-item list against
      dynamodb-local (expect one query, not 200 GetItems)

### Implementation Status: Complete

**Deviations / notes (sub-step 1 of 4 — `get_range()`/`create_if_not_exists()`):**

- Landing Phase 4 as 4 separate commits within this phase (protocol +
  backends → Alembic migration → `property_list.py` v2 rewrite → full
  verification), each independently green, rather than one large commit —
  the storage-format rewrite has enough surface area that per-step
  verification catches problems closer to their cause.
- `get_range()`'s bound semantics changed from the plan's `[lower, upper)`
  (exclusive upper) to `[lower, upper]` (**inclusive** upper). DynamoDB's
  `KeyConditionExpression` rejects two separate comparisons on the same key
  (`>=` AND `<` errors with "KeyConditionExpressions must only contain one
  condition per key") — only `between()` (inclusive-inclusive),
  `begins_with`, or a single comparison are legal. Callers (the v2 list
  format) choose `upper` as a delimiter sentinel (`$`) that can never equal
  a real row name, so inclusive-vs-exclusive at that boundary is
  unobservable. PostgreSQL uses `<=` to match, plus `COLLATE "C"` on BOTH
  sides of the range comparison (not just `ORDER BY`, which the plan
  mentioned) — a non-C database default collation affects the `>=`/`<=`
  comparison operators too, not only result ordering, so without it the
  WHERE clause itself could silently return the wrong rows on a
  non-C-collation deployment.
- Added `DbPropertyProtocol.create_if_not_exists()` as a distinct method
  rather than a `set()` kwarg — `set()` is an upsert on PostgreSQL
  (`ON CONFLICT DO UPDATE`) and is called from 15+ sites; a conditional-only
  variant needed a separate method rather than a behavior-changing flag on
  the existing one.
- `_should_index_property()` on both backends now also excludes any name
  starting with `list:` (belt-and-braces; list names were already never
  configured as indexed properties, but this makes it structurally
  impossible for lookup-table sync to touch list storage rows regardless of
  configuration).
- New tests: `tests/integration/test_db_property_range.py` (both backends) —
  range bounds, sibling-list-prefix isolation (`list:foo-#...` vs
  `list:foo-x-#...`), keys-only mode, and conditional-create collision
  behavior.
- Verified: `ruff`, `pyright` (0 errors), `make test-integration-fast`
  (DynamoDB, 786 passed) and the PostgreSQL equivalent (776 passed) both
  green.

**Deviations / notes (sub-step 2 of 4 — Alembic migration):**

- New revision `e5f6a7b8c9d0` (head: `d4e5f6a7b8c9` → `e5f6a7b8c9d0`) widens
  `properties.name` `VARCHAR(255)` → `TEXT` via a metadata-only
  `ALTER COLUMN ... TYPE TEXT` (no table rewrite). `downgrade()` reverses to
  `VARCHAR(255)` and will fail loudly (Postgres raises on the implicit
  truncation check) if any row's name exceeds 255 chars at downgrade time —
  by design, an operator downgrading a schema underneath live v2 rank keys
  needs that failure, not silent truncation.
- Also updated `actingweb/db/postgresql/schema.py`'s SQLAlchemy `Property.name`
  column to `Text` (was `String(255)`) — this model is autogenerate-comparison
  metadata only (raw psycopg3 is the real read/write path), but leaving it
  stale would make a future `alembic revision --autogenerate` propose
  reverting this migration.
- Verified manually against the `postgres-test` container: fresh
  `alembic upgrade head` runs the full chain including this revision;
  `\d properties` confirms `name` is `text`; `alembic downgrade -1` reverts
  it to `character varying(255)`; `alembic upgrade head` re-applies cleanly.
  `ruff`/`pyright` clean on the new file and `schema.py`.

**Deviations / notes (sub-step 3 of 4 — `property_list.py` v2 rewrite):**

- **Format decision:** every brand-new list (no existing meta row) is now
  created as v2. This is what "New lists stop using dense integers" in the
  plan means concretely — there is no opt-in flag. Existing v1 lists are
  completely unaffected and keep using the hardened v1 code paths from
  Phases 1-3 indefinitely (migration is Phase 5). This had a real
  consequence: every Phase 1-3 test that built a fresh list via `.append()`
  and then punched a v1-shaped hole (`list:{name}-{index}`) into it now
  needed to seed a v1 list explicitly first (a small `_seed_v1_list()`
  helper writing the meta row + dense-integer item rows directly) — those
  bug classes are structurally v1-only, so the tests are still valid and
  necessary, they just can no longer rely on "any freshly created list is
  v1." Updated: `tests/integration/test_property_list_repair.py`,
  `tests/integration/test_verify_property_lists_script.py`,
  `tests/integration/test_www_list_corruption.py`,
  `tests/integration/test_property_list_http_contract.py`'s corruption
  test, and one unit assertion in `tests/test_property_list.py` that
  checked the v1-shaped `length` key in fresh metadata.
- **Real bug caught by that same test run, not by design review:** v2
  mutations (append/insert/setitem/delitem) initially never persisted the
  metadata row — v1 gets this "for free" because every v1 mutation writes
  `length` into metadata as a side effect, but v2 has no length to write,
  so nothing forced the meta row to exist. `PropertyListStore.exists()`,
  property/list name-collision detection, and `list_all()` all key off
  that row, so a list that was only ever appended to (never
  `set_description()`ed) was invisible to all three. Fixed with
  `_v2_touch_metadata()`, called from all four v2 mutation entry points —
  costs one extra write per mutation, same profile as v1's per-mutation
  metadata write, not the effectively-free operation I'd originally
  assumed. Caught by `tests/integration/test_property_list_collision.py`
  and `test_property_lists_advanced.py` failing on the first real-backend
  run, not anticipated during design.
- **`get_range()` bound semantics** (established in sub-step 1) hold up
  the whole isolation argument: verified by direct test
  (`test_range_excludes_sibling_list_with_shared_prefix` in
  `test_db_property_range.py`, sub-step 1) that a list literally named
  `foo-x` doesn't leak into list `foo`'s range query, which is exactly why
  `#` has to be banned in list names (a list named `foo-#x` WOULD leak into
  `foo`'s range, since `#` sorts below the `$` upper-bound sentinel
  regardless of what follows it).
- **Conditional-write retry uses fresh-reread, not random jitter.** The
  plan says "regenerate the rank with jitter and retry"; the actual
  implementation re-reads the current rank-key state on each retry
  (`force=True`) and generates a new candidate from that fresh state —
  deterministic, not randomized. A second writer's completed write is
  exactly what a fresh read reveals, so this resolves the plan's target
  race (two writers computing the same candidate from the same stale read)
  without introducing nondeterminism into what's otherwise a fully
  deterministic algorithm. Pinned by
  `TestV2ConditionalWriteCollision` in `tests/test_property_list_integrity.py`
  (a `StaleReadPropertyDb` fake that returns a stale snapshot on exactly
  the first `get_range()` call, forcing a real collision to exercise the
  retry path deterministically).
- **`_v2_compact()`'s rebalance-retry bug, found by its own integration
  test, not by design review:** the first implementation retried a
  collision by bisecting between the *last successfully written rank* and
  the next target boundary — both fixed for the duration of one item's
  retry loop, so `generate_key_between()` regenerated the exact same
  (still-colliding) candidate every attempt and exhausted retries into a
  "rank collision storm" error. Fixed by bisecting between the
  *just-failed candidate* and the same upper boundary each retry, which
  strictly converges toward the boundary instead of repeating. Caught by
  `TestV2RankRebalanceIntegration::test_compact_after_many_inserts_shrinks_ranks`
  (62-item list, one item's target rank collides with another item's
  not-yet-renamed row — a real, not contrived, collision during rebalance).
- **`to_indexed_list()`** needed no code change — its existing
  `list(enumerate(self.to_list()))` implementation was already written
  anticipating exactly this divergence (storage identity vs. position),
  per its Phase 3 docstring. Updated only the docstring to describe the
  now-real v1/v2 split instead of a hypothetical future one.
- **List-name validation lives solely in `ListProperty._load_metadata()`**,
  not "mirrored in `interface/property_store.py`" as the plan's Changes
  section suggested — traced both `NotifyingListProperty` and
  `interface/property_store.py::PropertyListStore.__getattr__` and
  confirmed they're pure delegating wrappers with no independent
  name-handling logic that could bypass the check in `ListProperty`, so a
  second enforcement point would be redundant, not defense-in-depth.
- **`handlers/properties.py`** needed no dispatch-related changes at all —
  every call site that holds a `list_prop` across multiple `len()`/mutation
  calls already does so via ONE local variable per request (not
  reconstructed per loop iteration), and the `format=full`/`format=short`/
  `metadata=true` listall branches already call `prime_from_rows(all_rows)`
  before `len()`/`to_list_from_rows()` — both of which the plan flagged as
  at-risk call sites turned out to already satisfy the "no query blowup"
  invariant once `prime_from_rows()` and `__len__`/`to_list()` were made
  v2-aware. Only removed one `len()` call from a debug log line (per the
  plan's explicit callout) since it eagerly warmed the query cache purely
  for logging.
- New tests: `tests/integration/test_property_list_v2.py` (new — full
  behavioral parity against a plain Python list, negative indexing,
  `verify()` shape, name validation, interleaved-mutation stale-cache
  self-healing, rank-rebalance-after-many-inserts, run against both
  backends via the existing `DATABASE_BACKEND` convention — running the
  same file per-backend IS the cross-backend-ordering pin, rather than a
  single test comparing both backends side by side); new classes in
  `tests/test_property_list_integrity.py` (`TestV2NewListDefaultsAndValidation`,
  `TestV2QueryCountGuard`, `TestV2ConditionalWriteCollision`,
  `TestV2RankCapAndCompact` — unit-level, dict-backed fake extended with
  `get_range()`/`create_if_not_exists()`); `tests/test_hot_path_n_plus_one.py`
  extended (not replaced) with a real query-count assertion for priming
  (patches `DbProperty.get_range`/`.get` to raise if called after
  `prime_from_rows()`) and a dedicated one-range-query-per-`to_list()`
  guard on a 20-item list.
- Verified: `ruff`, `ruff format`, `pyright` (0 errors) on `actingweb/`
  and `tests/`; full `pytest tests/ -m "not slow"` on DynamoDB (2673
  passed, 26 skipped); `tests/integration/` on PostgreSQL (784 passed, 18
  skipped) — PostgreSQL run scoped to `tests/integration/` per CLAUDE.md's
  documented procedure (the top-level `tests/*.py` files with
  `[postgresql]` parametrization depend on migration setup that isn't
  triggered outside that scope; this is pre-existing test-harness scoping,
  not something Phase 4 changed).

**Deviations / notes (sub-step 4 of 4 — post-commit review fix):**

- **`scripts/verify_property_lists.py` had a real bug the sub-step 3 test
  suite didn't catch:** it indexed v1-shaped keys
  (`report['stored_length']`, `report['missing_indices']`,
  `report['orphan_indices']`) directly in its unhealthy-list logging,
  outside the `try/except` that wraps only `verify()` itself -- an
  unhealthy v2 list (whose report has no such keys) would raise an
  uncaught `KeyError` and crash the sweep. The gap existed because the
  sub-step 3 test suite retrofitted `test_verify_property_lists_script.py`
  to seed v1 lists (matching the "any freshly created list is v1" fix
  described in sub-step 3's notes) without ever adding a v2 list back in
  -- every test actor in that file had zero v2 lists, so the blind spot
  was structural, not incidental. Caught by a fresh advisor review after
  the sub-step 3 commit, not by CI. Fixed: `sweep_actor()` now dispatches
  logging and the repair gate on `report.get("format") == 2`; v2's repair
  gate is "not healthy" (rank length in the warning zone) rather than
  v1's "has missing_indices or orphan_indices" (a concept that doesn't
  exist under v2 -- structurally, a v2 list cannot have holes or orphans).
  New tests: `test_v2_lists_swept_alongside_v1_without_crashing` (mixed
  v1+v2 actor, proves no cross-format crash and the v1 repair outcome is
  unaffected) and `test_v2_unhealthy_list_repaired_by_rank_rebalance`
  (seeds a 141-char rank directly -- computed once via
  `fractional_indexing.generate_key_between()` outside any `ListProperty`
  calls, since reaching that length through real `insert()` calls would
  take ~700 sequential DB round-trips -- then confirms the sweep detects
  it as unhealthy and `--repair` rebalances it).
- Re-verified after the fix: `ruff`/`pyright` clean;
  `tests/integration/` full pass on both DynamoDB (796 passed) and
  PostgreSQL (786 passed).

---

## Phase 5: Migration v1→v2, docs, release

### Changes

- `actingweb/property_list.py` — `migrate_to_v2() -> dict`:
  1. Refuse if the name contains `#` (log operator-actionable error, keep
     serving v1) or if metadata is unparsable (Phase 2 raises anyway).
  2. `verify()`; holes → compact-in-flight (migration reads surviving rows in
     order); duplicates migrated as-is and reported.
  3. Generate N evenly distributed ranks deterministically from the v1
     positions (idempotent: re-running writes identical rows).
  4. Write all v2 rows (plain puts — determinism makes overwrites
     convergent), verify the v2 row count.
  5. Flip the meta (`format: 2`, drop `length`) with a fresh meta read.
  6. Delete v1 item rows (idempotent cleanup; deferred-safe — v2 readers
     ignore v1 rows).
  A crash at any point leaves either v1 authoritative (steps 1-4) or v2
  authoritative with harmless leftover v1 rows (step 6), both re-runnable.
- Lazy trigger: v1 lists with `length <= 50` migrate at the top of mutation
  methods only (never on read paths — reads run under read-only permission,
  `handlers/properties.py:1506`, `www.py:181-182`). Larger lists stay v1
  (fully functional via the hardened v1 paths) until the script runs.
- `scripts/migrate_property_lists.py` (new) — bulk migration with the
  `backfill_property_lookup.py` machinery (parallel scan segments, rate
  limiter, checkpointing); `--dry-run` default; reports refused names and
  duplicate residue; `--downgrade <actor>/<list>` emergency v2→v1 converter
  (documented as emergency-only).
- Documentation:
  - `docs/guides/property-lists.rst` — v2 format note, `/items` GET response
    shape, 409 corruption contract, `verify()`/`compact()`, migration guide
    (upgrade steps, "downgrade after migration is unsupported" warning box).
  - `docs/reference/` handler docs regenerated where they describe `/items`.
  - `CHANGELOG.rst` — Unreleased entries for all phases (breaking-change
    callouts: fail-fast reads, `/items` GET shape, backend errors now raise).
- `thoughts/todo/attribute-list-shift-design.md` (new) — the deferred
  `ListAttribute` work, referencing both research docs.
- `thoughts/todo/property-list-delete-leaves-holes.md` — deleted (resolved).
- Release: version bump to `3.13.0rc5` in `pyproject.toml` +
  `actingweb/__init__.py`, CHANGELOG rename per CLAUDE.md release process, tag
  after merge.

### New Tests

- Migration integration (both backends): small list end-to-end (lazy trigger
  on append), 200-item list via script path; REST behaviour identical before
  and after (same `to_list`, same `/items` responses).
- Idempotency: kill migration after step 4, re-run → identical result; run
  two migrations concurrently (sequenced interleaving via fakes) → convergent.
- Holed v1 list migrates to a clean v2 list (hole closed); duplicate residue
  migrates with duplicates preserved + reported.
- Refusal: v1 list named `a-#x` is refused, keeps working as v1, sweep script
  reports it.
- Downgrade: v2 → `--downgrade` → v1 list readable by v1 paths, content
  identical.
- Lazy-bound: a 51-item v1 list is NOT migrated by a mutation; a 50-item one
  is.

### Verification

- [ ] `make test-all-parallel` passes (full suite, per CLAUDE.md)
- [ ] `make test-integration` sequential on DynamoDB AND PostgreSQL passes
- [ ] `poetry run pyright actingweb tests scripts` — 0 errors; `ruff` clean
- [ ] Docs build clean (`sphinx-build` per docs CI)
- [ ] Manual: full upgrade rehearsal against dynamodb-local — seed v1 lists
      (incl. one holed, one 200-item, one named `a-#x`), upgrade, run sweep +
      migrate scripts, verify REST behaviour and reports
- [ ] Release checklist from CLAUDE.md (version files match, CI green on both
      backends, tag from master merge commit)

### Implementation Status: Not Started

---

## Protocol Compliance

Checked against `docs/protocol/actingweb-spec.rst` (the ActingWeb protocol
spec). The plan does **not** change the REST protocol:

- **`/items` is not in the spec.** The spec addresses list items by path index
  (`/properties/notes/0`, spec table at `:966-973`) and appends via POST to
  the list property itself (`:1025-1038`). The `/items` endpoint with
  `action` bodies is an implementation extension (FastAPI-only today), so
  changing its GET response shape is not a protocol change. The guide must
  keep documenting it as an extension, not spec behaviour.
- **Delete re-indexing contract preserved.** The spec REQUIRES that after
  deleting an item, "Subsequent items MUST be re-indexed to maintain a
  contiguous sequence" (`:1054-1070`). v2 satisfies this observably —
  positions are derived from rank sort, so indices are always contiguous
  `0..n-1`; the storage change is invisible at the protocol level (and makes
  the implementation honour this MUST more reliably than the shift loop does).
- **Diff vocabulary unchanged.** The subscription diff `operation` field is a
  closed enumeration (`:2626-2634`); the plan emits only in-vocabulary
  operations (`compact` reports as `metadata`). `list`/`operation`/`length`
  REQUIRED fields keep their semantics; `length` is computed post-operation
  under v2 exactly as the spec requires.
- **Response shapes unchanged** for `GET /properties` (`_list`/`count`
  markers), `?format=full`, `?format=short`, `?metadata=true`, and the
  `/metadata` endpoint (`count` becomes counted-not-stored — same observable
  field).
- **Two pre-existing spec deviations are *fixed*, not introduced, by this
  plan:** the PUT beyond-length padding (spec: MUST 404; today: unbounded
  `append(None)`) becomes spec-compliant in Phase 3, and the `count`
  divergence between listall views on a holed list disappears under
  fail-fast + repair.
- **Implementation-defined extension, documented as such:** the 409
  corruption response. The spec mandates 200 + array for list GET but does
  not contemplate a corrupted store; 409 is used because the spec already
  associates it with conflict states (`:1015-1023`). Documented in the guide
  as outside the spec.
- **Pre-existing tensions, out of scope (noted, unchanged):** the spec's
  all-or-nothing requirement for `POST /properties` (`:940-947`) is not met
  by the existing bulk list-item POST (partial application on error), before
  or after this plan; and path-based item addressing
  (`/properties/notes/0`) vs the implementation's `?index=N` query form
  predates this work.

## Evaluation Notes

Four-perspective evaluation ran before this plan was written (security and
scalability by sub-agents; architecture and usability inline after the agents
hit the account spend limit).

### Architecture

v1/v2 dispatch lives inside `ListProperty` (branch on meta `format`) — matches
how every construction site obtains lists (`property.py:54-66`,
`interface/property_store.py:396-406`). Subscription diff wire format is
untouched; `remote_storage.py:343-420` consumes positional diffs and continues
to work. Migration ranks are deterministic functions of v1 indices, making
interrupted/concurrent migration convergent without a lock. Phase 1's
raise-on-backend-error is a library-wide semantic change for property reads
(scalar paths at `property.py:162,180` included) — accepted as correct
(absence ≠ error), wrapped in sanitized `DbError`, and covered by the full
integration suite on both backends.

### Security

Blocker found and resolved by design: PostgreSQL `LIKE` on user-controlled
list names (names reach `ListProperty` unvalidated from URL paths,
`handlers/properties.py:1497,1533`) would let a list named `%` read every v2
list of the actor across per-property permission boundaries — v2 therefore
uses range comparison with no pattern language. Legacy names containing `#`
defeat the prefix-collision proof → migration refuses them (validation at
create time alone cannot cover pre-existing names). Backend exception text is
sanitized before the four `str(e)` handler sites. Lazy migration triggers only
on write-permission paths, adding no privilege. Rank-length cap prevents
adversarial list-wedging at the key-size limits (PG's 255-char name column is
also widened). Lookup-table sync gets a `list:` exclusion guard.

### Scalability

Two blockers resolved in the design: (1) `len()` appears inside loops
throughout the handlers (`handlers/properties.py:597,992,1014`, iterator at
`property_list.py:33`) — v2 mandates the per-instance rank-key cache and
single-query `to_list`/`__iter__`, otherwise counting a 200-item list per
`len()` call would be a severe RCU/latency regression; with it, reads improve
40-100× (one paginated query vs ~200 sequential consistent GetItems). (2) The
meta row must survive v2 — `exists()` (`property.py:20-25`) and list discovery
(`handlers/properties.py:440-443`) depend on it. Also: Python-side bytewise
rank ordering (SQL collations disagree with DynamoDB byte order), append does
not reintroduce a per-write meta update, lazy migration is bounded (a 202-item
lazy migration inside a Lambda request is the original kill scenario), and
the bulk script reuses the proven backfill machinery.

### Usability

`/items` GET shape change is low-impact (only POST is documented,
`docs/guides/property-lists.rst:129`; zero GET tests existed) and the indexed
shape matches the listall `_list`/`count` conventions. Corruption becomes a
structured 409 with a remedy instead of a raw 500 (backend text never leaks —
Flask/FastAPI only genericize *escaped* exceptions, not caught-and-
interpolated ones). `verify()`/`compact()` are reachable through
`actor.property_lists.foo` via `NotifyingListProperty`; nothing is added to
`PropertyListStore` so no list name gets shadowed. Operators: upgrading
requires nothing (lazy migration covers small lists; the script is for large
deployments); half-migrated states are fully functional; downgrade after
migration is unsupported and documented loudly, with an emergency converter in
the script.
