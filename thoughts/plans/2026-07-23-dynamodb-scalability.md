---
status: done
---

# Implementation Plan: DynamoDB Backend Scalability (v3.13.0)

**Date:** 2026-07-23
**Status:** Implemented (all 8 phases, branch `dynamodb-scalability`; pending PR + release)
**Research:** thoughts/research/2026-07-23-dynamodb-scaling-defects.md (companion measurement doc:
`../actingweb_mcp/thoughts/research/2026-07-23-scaling-review-apigw-lambda-dynamodb.md`)
**Branch:** master (plan written at commit `29783f8`; implement on a feature branch)

## Overview

The DynamoDB backend has two measured superlinear scaling defects (partition-key `Scan`s
costing ~2,036 RCU per property fetch; ~1,396 `DescribeTable` calls/min from un-memoised
existence guards), two design defects (provisioned-throughput defaults on auto-created
tables; the legacy value-keyed GSI decoupled from the lookup-table config), and — found
during plan evaluation — a set of hot-path N+1 read amplifiers that dominate cost once the
scans are fixed. This plan fixes all of them in one minor release (v3.13.0), flips the
reverse-lookup default to lookup-table mode safely (dual-read fallback + backfill script +
loud startup check), and updates every affected doc surface.

## Decisions Made

- **Legacy value GSI (Defect 4)**: Conditional schema + fail-fast — fresh `_properties`
  tables omit the `property-index` GSI in lookup-table mode; legacy path fail-fasts with an
  actionable `RuntimeError` when the index is absent. Full GSI removal deferred to the next
  major release, tracked in `thoughts/todo/`.
- **Default reverse-lookup mode**: Flip `use_lookup_table` default to `True` — aligned with
  what both known consumers already run; the legacy default is broken on pre-GSI tables.
- **Flip safety**: One release with a **dual-read fallback** — on a lookup-table miss, fall
  back to the legacy GSI when it exists (deprecation-logged), plus a loud startup check and
  a shipped backfill script. Fallback removed in the next major.
- **Auto-create control**: `AWS_DB_AUTO_CREATE_TABLES` env var (default true; matches the
  `AWS_DB_PREFIX`/`AWS_DB_HOST` convention — NOT `AW_DB_*` as the research doc once wrote)
  plus fluent `with_dynamodb(auto_create_tables=...)`.
- **Billing**: Auto-created tables always `PAY_PER_REQUEST`; `Meta` capacity units removed
  as dead config; no provisioned-billing knob (IaC owns that case).
- **Release**: Single minor release v3.13.0 with `docs/migration/v3.13.rst`.
- **Lookup-table key redesign (digest-only)**: Replace the `(property_name, value)`
  composite key with a single hash key `lookup_key = sha256(canonical(name, value))`,
  storing `actor_id` and `property_name` as attributes and **never storing the value**.
  Fixes four design weaknesses at once: the low-cardinality hot-partition key (3 property
  names = 3 partition keys, per-partition throughput ceiling on login bursts before
  split-for-heat reacts), the 1024-byte range-key value cap, plaintext PII in key
  material, and (via conditional puts) silent last-writer-wins collisions. Requires a
  **new table** (`_property_lookup_v2`) — DynamoDB cannot change a key schema — with the
  v1 table left intact for library-version rollback. Chosen now because the Phase 8
  backfill will populate this table across all deployments; the format change is trivial
  today (measured prod: 45 rows) and a full re-migration later.
- **Flip fallback chain**: On a v2 lookup miss, fall back to the **v1 lookup table**
  (when it exists — protects the cohort that already adopted lookup mode and has no GSI),
  then the legacy GSI (when it exists). Both fallback tiers deprecation-logged; both
  removed in the next major.
- **N+1 scope**: The eight small hot-path fixes ship in this release (Phase 5). Five larger
  items are deferred to a known-next doc: batch_write for delete loops, general
  `ListProperty.__getitem__` N+1 and `__delitem__` O(N) shift, the 22-site
  `consistent_read` audit, `SubscriptionDiff` seqnr key-format fix, `DbActorList`
  pagination.
- **Lookup-table limits**: Superseded by the digest-only redesign — a fixed-length digest
  key has no value-size limit, so the originally planned 1024-byte validation is dropped.
  Write failures (throttles etc.) still get loud ERROR logging instead of today's silent
  swallow; the "no size limit" doc claim becomes true and is documented accurately.
- **Privacy framing (honest scope)**: Digest-only is pseudonymization, not anonymization —
  low-entropy values (emails) remain dictionary-attackable, and the *properties* table
  still stores values in plaintext regardless. What this removes is the second plaintext
  copy with its own IAM/backup surface. Documented as such; no overclaiming.
- **PostgreSQL**: keeps its relational `(name, value)` lookup format — same database as
  the properties table (no extra exposure surface), and a unique index has none of the
  DynamoDB key problems. Behavioural parity only (contract for misses/non-indexed names).

## What We're NOT Doing

- Removing the legacy `property-index` GSI or the legacy code path (next major; tracked in
  `thoughts/todo/legacy-property-gsi-removal.md`).
- batch_write conversion of delete loops; general `ListProperty` item N+1 / `__delitem__`
  redesign; relaxing `consistent_read=True` anywhere; `SubscriptionDiff` range-key format
  change; `DbActorList.fetch` pagination (all documented in
  `thoughts/todo/dynamodb-known-next.md`).
- Changing the PostgreSQL lookup-table storage format (digest scheme is DynamoDB-only;
  see Decisions).
- Converting existing deployments' tables to on-demand billing (deployer runs
  `aws dynamodb update-table --billing-mode PAY_PER_REQUEST` out-of-band; migration doc
  covers it — **never recreate tables**, the lookup table holds live login rows).
- PostgreSQL performance work beyond keeping the `USE_PROPERTY_LOOKUP_TABLE` /
  `INDEXED_PROPERTIES` handling in `db/postgresql/property.py:38-51,420-434` consistent
  with the DynamoDB changes (same default flip applies to both backends).
- Changes to `actingwebdemo` (separate repo — coordination notes at the end of Phase 8).

---

## Phase 1: Builder config precedence fix (prerequisite bug fix)

Today `ActingWebApp.__init__` hardcodes `_use_lookup_table = False` / `_indexed_properties`
(app.py:78-81) and `_apply_runtime_changes_to_config()` (app.py:190-193) re-applies them on
**every** `with_*()` call behind a dead `hasattr` guard — silently clobbering the
`USE_PROPERTY_LOOKUP_TABLE` / `INDEXED_PROPERTIES` env overrides applied in
`config.py:250-257`. The documented rollback (`configuration.rst:524`) does not reliably
work. This must land before the default flip and is an independent bug fix.

### Changes

- `actingweb/interface/app.py` — make `_use_lookup_table: bool | None = None` and
  `_indexed_properties: list[str] | None = None` sentinel defaults; in
  `_apply_runtime_changes_to_config()` assign only when not `None`; in `get_config()`
  (app.py:1242) omit the kwargs when `None` so `Config` defaults + env overrides are
  authoritative. Resulting precedence: explicit builder call > env var > Config default.
  `with_legacy_property_index()` / `with_indexed_properties()` keep working unchanged.
- `CHANGELOG.rst` — own entry: env overrides for lookup-table settings were silently
  ignored when any `with_*()` method was called after app construction.

### New Tests

- Unit: `USE_PROPERTY_LOOKUP_TABLE=false` (and `=true`) survives a subsequent
  `.with_web_ui()` / `.with_devtest()` call — asserts `config.use_lookup_table`.
- Unit: `INDEXED_PROPERTIES=custom1,custom2` survives builder calls.
- Unit: explicit `with_legacy_property_index(enable=True)` beats the env var (builder wins).
- Unit: no env, no builder call → `Config` default is used (guards the Phase 8 flip).

### Verification

- [x] `poetry run pytest tests/test_property_lookup.py -k "Precedence or Configuration" -v` — 9 passed
- [x] `poetry run pyright` on changed files — 0 errors
- [x] `poetry run ruff check actingweb tests` passes; format clean
- [x] `make test-all-parallel` — 2374 passed, 5 parallel-isolation failures all pass
      sequentially (per CLAUDE.md verification procedure)

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Phase 2: Table-existence memoisation + auto-create control

Collapses 13 per-construction `DescribeTable` guards (measured 1,396/min at idle) to
once-per-process-per-table, adds the missing guards, and makes auto-creation opt-out for
IaC-managed production.

### Changes

- `actingweb/db/dynamodb/_ensure.py` (new) —
  `ensure_table(model)`: double-checked module-level `set[str]` + `threading.Lock`;
  memo key is the **model class** (not `Meta.table_name`) so Phase 7's two Property model
  classes don't collide; `reset_ensure_cache()` test hook; `set_auto_create(bool)` module
  override + `AWS_DB_AUTO_CREATE_TABLES` env read (default true). **When auto-create is
  off, skip `model.exists()` entirely** (not just `create_table`) so roles without
  `dynamodb:DescribeTable` never AccessDenied (S5). Never cache a negative; preserve the
  existing semantics: only `ResourceInUseException` is benign, everything else re-raises
  (swallowing AccessDenied would turn config errors into silent data loss). Log the
  resolved flag value once at first use; `set_auto_create()` warns if `_ensured` is already
  non-empty (called too late).
- Replace the 13 guard blocks with `ensure_table(X)`: `actor.py:143`, `property.py:81/365`,
  `attribute.py:334/401`, `trust.py:431/533`, `subscription.py:157/218`,
  `subscription_diff.py:103/171`, `peertrustee.py:128`, `property_lookup.py:57`.
- Add guards where missing (behaviour change — call out in CHANGELOG):
  `DbPeerTrusteeList.__init__` (peertrustee.py:179) and
  `DbSubscriptionSuspension.__init__` (subscription_suspension.py:48) — today the
  suspension table is **never** auto-created, so first use on a fresh deployment crashes.
- `actingweb/interface/app.py` — new fluent `with_dynamodb(auto_create_tables: bool = True)`
  calling `_ensure.set_auto_create()` via `_apply_runtime_changes_to_config()` (tri-state,
  per Phase 1 pattern). No other knobs in it yet; it is the future home for backend options.
- `actingweb/interface/app.py` (`integrate_flask` / `integrate_fastapi`, near the
  `_initialize_permission_system` call at app.py:1274/1287/1333) — flag-gated **parallel
  pre-warm**: `ThreadPoolExecutor` over `ensure_table` for all auto-created models (after
  Phase 6 the deprecated v1 lookup model is excluded — legacy read-only, never
  auto-created), skipped entirely when auto-create is off. Failures degrade to the lazy path (the surrounding init already
  swallows exceptions, app.py:1345-1355) — keep that property.
- `tests/integration/conftest.py` — call `reset_ensure_cache()` from
  `cleanup_dynamodb_tables()` (:127-161) so in-process table deletion can never leave the
  memo lying; also a fixture pinning `AWS_DB_AUTO_CREATE_TABLES=true` for
  `tests/test_db_protocols.py`-style direct constructions.

### New Tests

- Unit: `ensure_table` calls `Model.exists` at most once per model class across many
  constructions (mock `exists`/`create_table`, count calls); thread-safety smoke test.
- Unit: `reset_ensure_cache()` makes the next call re-check.
- Unit: `AWS_DB_AUTO_CREATE_TABLES=false` → neither `exists()` nor `create_table()` called;
  `with_dynamodb(auto_create_tables=False)` equivalent; env-vs-builder precedence.
- Integration: fresh-prefix deployment auto-creates **all** tables including
  `_subscription_suspensions` and peertrustees via the list wrapper (regression for the
  previously-unguarded models).
- Integration: pre-warm creates all tables at `integrate_flask()` time on a fresh prefix.

### Verification

- [x] `poetry run pytest tests/test_ensure_table.py` — 22 passed
- [x] `poetry run pyright actingweb tests` — 0 errors; `poetry run ruff check` passes
- [x] `make test-all-parallel` — 2399 passed; 2 known-flaky xdist tests pass sequentially
      (same family failed on master pre-change)
- [x] Memoisation verified by unit call-count tests (mocked exists/create_table)

### Implementation Status: Complete

**Implementation note (found the hard way):** importing anything under
`actingweb.db.dynamodb` triggers the package `__init__`, which imports every model
module and permanently freezes `Meta.table_name`/`host` from env. The conftest's
`reset_ensure_cache` import tripped this before the test env was set; fixed by
setting the backend env vars at the top of the session-scoped `setup_database`
fixture. The same hazard applies to consumer code importing db modules before
configuring env — added to the known-next doc (deferred table-name resolution).

---

## Phase 3: scan→query conversions

Each conversion is mechanical (`query()` returns the same `ResultIterator`), and the target
pattern already exists in `attribute.py`/`subscription.py`/`subscription_diff.py`.

### Changes

- `actingweb/db/dynamodb/property.py:381,399` — `Property.scan(Property.id == actor_id)` →
  `Property.query(actor_id)` (`fetch`, `fetch_all_including_lists`).
- `actingweb/db/dynamodb/property.py:418,424` — same in `DbPropertyList.delete()` (the
  delete-scope-critical sites; see tests).
- `actingweb/db/dynamodb/trust.py:455,521` — →
  `Trust.query(self.actor_id, consistent_read=True)`. **`query()` defaults
  `consistent_read=False`** — the kwarg must be passed explicitly and is asserted by test
  (S1). Add `if not self.actor_id: return False` guard to `DbTrustList.delete()`
  (matching `DbPropertyList.delete()` property.py:411-412).
- `actingweb/db/dynamodb/peertrustee.py:49` —
  `PeerTrustee.query(actor_id, filter_condition=PeerTrustee.type == peer_type)`; the
  `count > 1` disambiguation at :56-64 is order-insensitive. `:153,171` → `query(actor_id)`;
  add the `actor_id` guard to `DbPeerTrusteeList.delete()`.
- `actingweb/db/dynamodb/actor.py:162` — leave `Actor.scan()` (intentional list-all); add a
  docstring note: admin-only, O(table), unpaginated.
- Do NOT touch the always-truthy `if self.handle:` checks in the same commit.

Note: results become range-key-sorted (deterministic) for `DbTrustList.fetch` /
`DbPeerTrusteeList.fetch` — check for order-sensitive assertions in integration tests
before merge; treat any as test fixes, not code fixes.

### New Tests

- Integration (delete scope, the critical one): create properties for actors A and B,
  `DbPropertyList(A).delete()`, assert B's properties **and** B's lookup rows intact
  (extends `tests/test_property_lookup.py::test_bulk_delete_preserves_other_actors_lookup_row`).
- Same shape for trust and peertrustee list deletes.
- Unit: trust fetch/delete pass `consistent_read=True` to `query` (mock assert on kwargs).
- Unit: `DbTrustList.delete()` / `DbPeerTrusteeList.delete()` return `False` when
  `actor_id` unset (no fetch first).
- Integration: peertrustee type-filtered fetch returns same results as before.

### Verification

- [ ] `poetry run pytest tests/test_property_lookup.py tests/integration -k "trust or peer or propert" -v`
- [ ] `poetry run pyright actingweb tests`; `poetry run ruff check` — clean
- [ ] `make test-all-parallel` passes
- [ ] Manual (optional, high-value): against DynamoDB Local, confirm via boto debug logs
      that property fetch issues `Query` not `Scan`

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Phase 4: On-demand billing default for auto-created tables

### Changes

- All DynamoDB model `Meta` classes get `billing_mode = PAY_PER_REQUEST_BILLING_MODE`
  (pynamodb constant): `actor.py:38-39`, `property.py:39-40`, `property_lookup.py:27-28`,
  `attribute.py:26-27`, `trust.py:68-69`, `peertrustee.py:18-19`, `subscription.py:20-21`,
  `subscription_diff.py:21-22`, `subscription_suspension.py:26-27`.
- Remove all `read_capacity_units` / `write_capacity_units` from model **and** GSI Metas
  (`property.py:25-26` PropertyIndex, `trust.py:54-55` SecretIndex, `actor.py:24-25`
  CreatorIndex). Do **not** add `billing_mode` to GSI Metas — index kwargs never read it
  (billing is table-level; verified in pynamodb 6.1.0 `connection/base.py:502-517`, which
  strips `ProvisionedThroughput` from table and every GSI when `PAY_PER_REQUEST`).
- `CHANGELOG.rst` — explicit note: affects **newly created** tables only; existing
  provisioned tables (typically `<prefix>_property_lookup`, `<prefix>_peertrustees`) need
  a one-time `aws dynamodb update-table --billing-mode PAY_PER_REQUEST` (allowed once per
  24 h; never recreate).

### New Tests

- Integration: on a fresh prefix against DynamoDB Local, create tables and assert
  `describe_table` reports `BillingModeSummary.BillingMode == "PAY_PER_REQUEST"` and GSIs
  carry no provisioned throughput.

### Verification

- [ ] `poetry run pytest tests/ -k billing -v` passes
- [ ] `poetry run pyright actingweb tests`; `poetry run ruff check` — clean
- [ ] `make test-all-parallel` passes

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Phase 5: Hot-path N+1 and duplicate-read fixes

Post-scan-fix, these dominate: a 50-property GET today is ~1 partition read + 50
strongly-consistent GetItems + 50 accessor constructions, twice-read partitions, and
re-read list metadata.

### Changes

- `actingweb/interface/property_store.py:174-201` — `items()`, `values()`, `to_dict()`
  (and `clear()`'s enumeration) read from one `_core_store.get_all()` result instead of
  re-fetching per key via `self[key]`. `__getitem__`/`__contains__` single-key semantics
  unchanged.
- `actingweb/handlers/properties.py:345,416` — `listall()` performs **one**
  `fetch_all_including_lists()` partition read serving both the simple-property dict and
  the list enumeration (`fetch()` output is a strict subset).
- `actingweb/handlers/properties.py:445-493` + `actingweb/property_list.py:52,71-76` —
  pass already-fetched `list:<name>-meta` rows into `ListProperty` via its existing
  `_meta_cache` slot (kills the per-list meta GetItem); serve `format=full` /
  `metadata=true` item enumeration (handlers/properties.py:447,465) from the same bulk
  read instead of `list(list_prop)`'s per-item GetItems.
- `actingweb/property.py:101-110,162-164 area` — gate the `property_lists.exists(k)`
  list-collision GetItem: on the read path (handlers/properties.py:162-164) only consult
  list metadata when the simple-property read missed; on the write path, check against the
  bulk-known state where available instead of a fresh GetItem per write.
- `actingweb/actor.py:76,225` — drop the eager `InternalStore` construction at :76 (it is
  unconditionally overwritten at :225 for existing actors); make the `_internal` bucket
  load lazy so requests that never touch `store.*` skip the Query entirely.
- `actingweb/db/dynamodb/property.py:418-427` — merge the two delete-path partition reads:
  collect indexed property names during the single delete pass.
- `actingweb/trust_permissions.py:467-495` — cache negative results in
  `TrustPermissionStore.get_permissions` (the `return None` paths at :477/:486 currently
  bypass the cache, costing one GetItem per authorised request).

### New Tests

- Unit: `PropertyStore.to_dict()` with N properties performs exactly one backend fetch
  (spy on `get_all` / `DbProperty.get` call counts).
- Integration: `GET /<actor>/properties` (plain, `?metadata=true`, `?format=full`) returns
  byte-identical JSON to pre-change behaviour (golden-response test with lists + simple
  properties), while backend call counts drop (instrument via patched accessors).
- Unit: negative permission lookup hits the cache on second call.
- Integration: actor with no store access constructs without an attributes Query
  (lazy `InternalStore`).
- Regression: `clear()` still deletes everything including list properties.

### Verification

- [ ] `poetry run pytest tests/ -k "property_store or properties or permission" -v`
- [ ] `poetry run pyright actingweb tests`; `poetry run ruff check` — clean
- [ ] `make test-all-parallel` passes (property handlers are heavily covered — treat any
      failure as a semantics regression, not test brittleness)

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Phase 6: Lookup-table v2 (digest-only) + hardening

The current `(property_name, value)` key design has a low-cardinality hot-partition key
(all email rows under one partition key), a 1024-byte range-key cap its own docstring
denies, plaintext PII in key material, and unconditional last-writer-wins puts. The v2
model replaces the key with a fixed-length digest. DynamoDB cannot alter a key schema, so
v2 is a **new table**; v1 stays intact for rollback and as a Phase 8 fallback tier.

### Changes

- `actingweb/db/dynamodb/property_lookup.py` — new `PropertyLookupV2` model:
  - table `<prefix>_property_lookup_v2`; single hash key
    `lookup_key = sha256_hex(canonical(property_name, value))`. Canonical encoding uses a
    NUL separator (`f"{name}\x00{value}"`) — unambiguous even if a name ever contains
    `#`; this is a **permanent data format**, document it in the module docstring.
  - the value is hashed **verbatim post-write** (same exact-match contract as runtime
    reads; no normalisation, no lowercasing) and **never stored**. Attributes:
    `actor_id`, `property_name` (not PII; needed for stale-row verification tooling and
    per-property row counts).
  - `create()` uses a **conditional put** (`attribute_not_exists(lookup_key)`); on
    condition failure, read the existing row — if `actor_id` differs, log a collision at
    ERROR (actor ids + property name + digest prefix; never any value) instead of today's
    silent overwrite. An explicit `overwrite=True` path serves legitimate value moves via
    `_update_lookup_entry`.
  - `get()`/`delete()` recompute the digest from the caller's (name, value) — same
    single GetItem cost, `consistent_read` still available (base table).
  - keep the v1 `PropertyLookup` model **read-only** (get/delete only) for the Phase 8
    fallback tier and migration verification; mark it deprecated and **exclude it from
    auto-creation** (a missing v1 table is a normal state, caught by the fallback chain —
    fresh deployments never create it).
  - on any write failure (throttle etc.): ERROR log with property name + actor + digest
    prefix (never the value — credential-equivalent per `actor.py:243-246`), replacing
    the silent swallow. No size validation needed — digests are fixed-length, so the
    documented "no size limit" claim becomes true.
- `actingweb/db/dynamodb/property.py` (`_update_lookup_entry`, :236-269): switch writes to
  v2; skip the delete+put entirely when the value is unchanged (removes write
  amplification ahead of the Phase 8 flip); value changes delete the old digest row and
  conditionally put the new one.
- `actingweb/db/dynamodb/property.py:172` — fail-fast: catch the missing-index error from
  `Property.property_index.query(value)` and re-raise as `RuntimeError` (house convention:
  no custom exception hierarchy; `RuntimeError` for runtime-state failures per
  `actor_interface.py:138,244,322`) with the three ways out: (1) switch to lookup-table
  mode + backfill (recommended), (2) add the GSI to the live table via `update-table`
  (noting the 2048-byte write-rejection consequence), (3) `with_indexed_properties([])` if
  reverse lookup is unused. Interpolate table name and prefix only — no ARNs, region, or
  the queried value. Raised at first reverse-lookup call, never at import time.
- `actingweb/db/dynamodb/property.py:152` — enforce the documented contract
  (`app.py:405-407`: only indexed properties may be used with `get_from_property`): in
  lookup mode, a **non-indexed** name no longer falls through to the legacy GSI branch —
  log a warning naming the property and `with_indexed_properties()`, return `None`.
  (Phase 8's dual-read fallback applies only to *indexed* names.)
- `actingweb/db/postgresql/property.py` — mirror the non-indexed-name contract in the PG
  branch (`:158-183` is already an unindexed sequential scan since migration
  `c3d4e5f6a7b8` dropped `idx_properties_value` unconditionally); keep both backends'
  env-fallback blocks (`dynamodb/property.py:92-107,344-359`;
  `postgresql/property.py:38-51,420-434`) in lockstep. Do **not** remove the direct-
  construction env fallback — ~40 test call sites depend on it; add a docstring warning
  and defer removal to the next major (todo doc).
- Docs: `docs/quickstart/configuration.rst:536-541` size table — lookup mode now
  genuinely unlimited (digest key); `docs/reference/security.rst` — pseudonymization note
  (digests, not plaintext, in the lookup table; honest scope: low-entropy values remain
  dictionary-attackable and the properties table itself still stores values in plaintext;
  what v2 removes is the second plaintext copy with its own IAM/backup surface).

### New Tests

- Unit: digest canonicalisation — fixed known-answer test for `lookup_key` (locks the
  permanent data format); names/values containing separators and non-ASCII round-trip.
- Unit: >2048-byte indexed value → lookup write succeeds in v2 (the old limits are gone).
- Unit: collision — two actors, same (name, value): first put wins, second logs collision
  ERROR without overwriting; explicit overwrite path works for value moves.
- Unit: unchanged value re-set → no lookup delete/put issued (call-count spy).
- Unit: write failure (mocked throttle) → ERROR log with digest prefix, never the value.
- Unit: legacy mode + table without GSI → `RuntimeError` with actionable message
  (mock/DynamoDB Local table created without the index).
- Unit: lookup mode + non-indexed name → `None` + warning, and **no** GSI query issued.
- Integration: set indexed property → reverse lookup resolves via v2 GetItem; delete
  property → v2 row gone (digest recomputation on the delete path).
- PG integration: same non-indexed-name contract.

### Verification

- [ ] `poetry run pytest tests/test_property_lookup.py -v` passes
- [ ] `poetry run pyright actingweb tests`; `poetry run ruff check` — clean
- [ ] `make test-all-parallel` passes

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Phase 7: Conditional GSI schema (two Property model classes)

pynamodb builds `_indexes` at class-definition time and caches the connection schema at
first use (`models.py:265-275,1059-1080`); runtime `_indexes` mutation makes
`property_index.query()` raise a bare `KeyError`. Two classes is the robust route.

### Changes

- `actingweb/db/dynamodb/property.py` — split into `PropertyLegacy` (current shape, with
  `property_index = PropertyIndex()`) and `Property` (no GSI), same `Meta.table_name`.
  Selection at accessor level by resolved `use_lookup_table`: lookup mode uses the
  GSI-less class for **table creation**; the legacy read path keeps using the GSI class.
  Reads/writes are shape-identical (the GSI attribute does not change item schema), so no
  data migration — only `create_table` behaviour differs.
- `actingweb/db/dynamodb/_ensure.py` — memo key already the model class (Phase 2); ensure
  the two classes cannot both create the table in one process with different shapes:
  first-wins per `Meta.table_name` at creation time, tracked explicitly.
- Existing tables are untouched (pynamodb never alters live tables) — upgraders keep
  whatever schema they have; only fresh deployments change. Release-note line: fresh
  lookup-mode deployments no longer pay double writes/storage for an unused GSI, and no
  longer inherit its 2048-byte write rejection.
- Docs: `docs/reference/database-backends.rst:371` ("`properties`: GSI on `value` field")
  becomes mode-dependent — describe both shapes.

### New Tests

- Integration (fresh prefix, lookup mode): created `_properties` table has **no** GSIs
  (`describe_table` assert); a >2048-byte property value writes successfully (empirically
  closes the research doc's hedged claim).
- Integration (fresh prefix, legacy mode): table created **with** `property-index`; legacy
  reverse lookup works end-to-end.
- Unit: both classes resolve to the same table name; ensure-cache holds one entry.

### Verification

- [ ] `poetry run pytest tests/ -k "gsi or schema or lookup" -v` passes
- [ ] `poetry run pyright actingweb tests`; `poetry run ruff check` — clean
- [ ] `make test-all-parallel` passes

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Phase 8: Default flip, backfill, migration machinery, docs

Ships last, after every safety mechanism above is in place.

### Changes

- **Flip**: `actingweb/config.py:64` `use_lookup_table` default → `True`. With Phase 1,
  the builder no longer overrides it; `with_legacy_property_index(enable=True)` and
  `USE_PROPERTY_LOOKUP_TABLE=false` both still pin legacy mode (rollback works). The
  `app.py:419` docstring ("When False (default), uses new lookup table") becomes true —
  changelog notes the resolved inconsistency.
- **Three-tier read fallback** (`actingweb/db/dynamodb/property.py:152-181`): in lookup
  mode, an *indexed*-name read tries **v2 → v1 lookup table (if that table exists) →
  legacy GSI (if the index exists on the live table)**; missing-table/missing-index cases
  are caught → `None`. Any fallback **hit** logs a deprecation warning naming the
  backfill script. The v1 tier is what keeps the already-adopted-lookup-mode cohort
  (populated v1 table, no GSI — the measured production shape) logging in between upgrade
  and backfill. Mirror the GSI-tier fallback in `db/postgresql/property.py` (its legacy
  branch is a sequential scan — the deprecation warning is doubly motivated there; PG has
  no v1/v2 split). Behaviour-change changelog line: legacy matching was value-only;
  lookup matching is (name, value) — cross-name collisions the legacy path resolved now
  return `None` once the fallbacks are removed (the fallback chain preserves old
  behaviour meanwhile). All fallback tiers removed in the next major.
- **Loud startup check**: modeled on `_warn_lambda_async_callbacks` (app.py:122) — at
  integration time, lookup mode active AND `_properties` non-empty AND
  `_property_lookup_v2` empty → `logger.error` naming
  `scripts/backfill_property_lookup.py` (message distinguishes "v1 table found — run the
  backfill to migrate to the v2 format, then drop v1" from "no lookup data at all — run
  the backfill"). One cheap probe per table, once per process, behind the ensure-cache;
  skipped when auto-create is off and tables are unreachable.
- **Backfill script**: `scripts/backfill_property_lookup.py` —
  - uses the config-aware factory (`actingweb.db.get_property(config)`), **never** direct
    `DbProperty()` construction (its env fallback can disagree with app config);
  - reads `indexed_properties` from resolved config (env/`INDEXED_PROPERTIES` respected),
    never a hardcoded list;
  - writes the **v2 digest format** — digests computed from stored values **verbatim**
    (no re-encoding, no sanitisation, no lowercasing; runtime lookups are exact-match
    against post-write strings). The properties table is the source of truth; v1 rows are
    never read as input, only optionally counted for the post-migration verification
    report;
  - streaming (never accumulates the table), `--rps` rate limit, parallel
    `scan(segment=i, total_segments=N)`, checkpointed `last_evaluated_key` resume,
    `--dry-run`, idempotent conditional puts (not delete+put);
  - detects and **reports** cross-actor value collisions (actor ids + property name +
    digest prefix, never the value) instead of silently overwriting;
  - prints a completion summary the migration doc's verification step keys off (rows
    written / already-present / collisions), after which the operator may drop the v1
    table;
  - explicitly not modeled on `scripts/migrate_dynamodb_to_postgresql.py:113-127`
    (accumulates unbounded memory).
- **Migration doc**: `docs/migration/v3.13.rst` (conventions per v3.10/v3.11), containing:
  the deployment-state decision tree (legacy-GSI table + implicit default; pre-GSI table;
  explicit legacy; already-lookup-on-v1; fresh), backfill invocation + verification, the
  v1→v2 lookup migration (run backfill → verify counts → drop `_property_lookup` v1; v1
  is derived data, the properties table is the source of truth), the
  `update-table --billing-mode` runbook (once-per-24h; **never recreate** the properties
  table), how to pin legacy mode, optional post-verification GSI drop on existing tables,
  IAM slimming (`CreateTable`/`DescribeTable` droppable with auto-create off; the role
  needs access to the new `_property_lookup_v2` table name — IaC-managed policies with
  per-table ARNs must add it).
- **Docs corrections** (actively-wrong lines): `docs/quickstart/configuration.rst:414,445,
  ~500,511,524` (defaults, rollback, backfill script name),
  `docs/reference/database-backends.rst:371`; soften "auto-creates tables" claims with
  "(configurable; disable in production via `AWS_DB_AUTO_CREATE_TABLES=false`)" at
  `configuration.rst:150,200`, `database-backends.rst:19`, `local-dev-setup.rst:55-60,136`;
  README.rst:202-210 "optional" reverse-lookup wording; document `with_dynamodb()`, the
  env flag, and `AWS_DB_PREFIX` (currently undocumented in configuration.rst); add the
  provisioned→on-demand runbook to `docs/guides/database-maintenance.rst`; one added
  sentence at `docs/contributing/architecture.rst:483-492` (direct construction now
  disagrees with the app default in the more dangerous direction).
- **CHANGELOG.rst** — Unreleased entries for every phase, including the behaviour changes:
  suspension/peertrustee tables now auto-created; deterministic list ordering; billing
  default; the flip + fallback + backfill; the Phase 1 bug fix.
- **thoughts/todo/** (note: singular `todo`, the existing dir) —
  `legacy-property-gsi-removal.md`: next-major removal of PropertyIndex, the legacy code
  path, the dual-read fallback, and the direct-construction env fallback;
  `dynamodb-known-next.md`: the five deferred scalability items with the evaluator's
  file:line inventory (batch deletes incl. `property_list.py:351-390` worst case; list
  `__getitem__`/`__delitem__`; `consistent_read` audit list; `subscription_diff.py:50-60`
  ordering; `DbActorList` pagination; secret-uniqueness eventual-consistency note at
  `trust.py:273-278`; import-time freezing of `Meta.table_name`/`host` from env —
  importing anything under `actingweb.db.dynamodb` binds all models permanently, a trap
  for consumers that configure env after import; consider deferred resolution); the
  GSI-removal doc also covers next-major removal of the v1 lookup model/table and both
  fallback tiers.
- **Demo app coordination** (separate repo, not in this plan's diffs): keep auto-create on;
  add comments in `serverless.yml` (why CreateTable/DescribeTable are needed, how to drop
  them in production) and a commented-out CFN `resources:` block as canonical schema;
  README "demo vs production" note; keep the now-default `with_legacy_property_index(
  enable=False)` line as a teaching artifact. Also note its IAM `table/demo_*` resource
  matches GSI ARNs only by accident of `*` spanning `/`.

### New Tests

- Integration (upgrade simulations, the critical ones — one per cohort):
  (a) legacy-GSI cohort: properties + GSI table shape, no lookup tables → resolves via
  GSI fallback with deprecation warning; after backfill, resolves from v2 without
  fallback. (b) v1-lookup cohort (the measured production shape): properties + populated
  v1 table, **no GSI**, empty v2 → resolves via v1 fallback with deprecation warning;
  after backfill, resolves from v2; v1 drop leaves everything working.
- Integration: backfill script — dry-run counts, resume from checkpoint mid-scan, verbatim
  value fidelity (value with JSON encoding + >1024-byte value skipped-with-report),
  collision reporting, idempotent re-run.
- Unit: startup check fires exactly under (lookup on ∧ properties>0 ∧ lookup==0) and is
  silent otherwise.
- Unit: rollback path — `USE_PROPERTY_LOOKUP_TABLE=false` after flip restores legacy
  behaviour end-to-end (depends on Phase 1).
- Existing suite: `tests/test_property_lookup.py::TestConfigurationIntegration::
  test_config_defaults` updated for the new default (deliberate, called out in review).

### Verification

- [ ] `poetry run pytest tests/test_property_lookup.py tests/integration -v` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors; `poetry run ruff check` passes
- [ ] `make test-all-parallel` passes
- [ ] `poetry run sphinx-build -b html docs _build 2>&1 | grep -i warning` (or the repo's
      docs build target) — no new warnings from edited .rst files
- [ ] Manual: fresh-prefix end-to-end against DynamoDB Local — deploy, write indexed
      property, reverse-lookup, verify no GSI on table, verify PAY_PER_REQUEST

### Implementation Status: Complete (branch `dynamodb-scalability`)

---

## Evaluation Notes

Four parallel evaluations were run against the codebase at `29783f8`; all findings were
verified with file:line evidence before incorporation.

### Architecture
Found the Phase 1 blocker: flipping `config.py:64` alone is a no-op (builder clobbers env
via the dead `hasattr` guard, app.py:190-193) — promoted to its own prerequisite phase.
Confirmed pynamodb 6.1.0 mechanics: `create_table` strips provisioned throughput for table
and GSIs under PAY_PER_REQUEST; GSI-level `billing_mode` is a no-op (dropped from plan);
runtime `_indexes` mutation is fragile → two-model-class approach chosen for Phase 7; memo
key must be the model class. Verified all in-library Db* construction goes through
factories; the direct-construction env fallback is dead code for the library but
load-bearing for ~40 test call sites → kept, removal deferred to next major. PG parity:
lookup table + Alembic migration already exist; PG's legacy branch is already an unindexed
sequential scan (migration `c3d4e5f6a7b8` dropped the value index unconditionally), which
strengthens the flip rationale. Flagged legacy value-only vs lookup (name,value) matching
as a behaviour change → changelog + fallback preserves old semantics until next major.

### Security
Trust `consistent_read` downgraded from auth-bypass to correctness (auth oracle goes
through `Trust.get`/`secret_index`, not the list fetch) — still preserved explicitly with a
kwarg-assert test (query defaults to eventually-consistent). Lookup misses cause silent
`None`, and duplicate-actor risk is consumer-side (`get_by_property` has no in-library
callers) → dual-read fallback + startup check chosen. Lookup writes fail silently
(`LOOKUP_TABLE_SYNC_FAILED` swallow) → Phase 6 loud logging; value never logged
(credential-equivalent). Lookup `value` is a **range key** → 1024-byte cap, half the GSI's
→ Phase 6 validation + docs. `_ensure` must gate `exists()` too, or IAM-hardened roles leak
AccessDenied (with role ARN/account id) into authenticated `str(e)` responses → Phase 2
requirement. Backfill: verbatim values, config-aware factory, config-resolved indexed list,
collision reporting → Phase 8 requirements. Fail-fast message: no ARNs/region/value.

### Scalability
Post-scan-fix, the dominant waste is the property-store N+1 chain (`to_dict` re-reads every
property; double partition read per GET; per-list meta re-reads; collision-check GetItems;
double `InternalStore` bucket Query) → Phase 5. Cold-start residual (~8 serial
DescribeTables) → flag-gated parallel pre-warm in Phase 2. Backfill hard requirements
(resume, rate limit, segments, streaming) → Phase 8; existing migration script rejected as
a template. Five larger items deferred with rationale (see Decisions); negative
permission-cache and duplicate delete-scan promoted into Phase 5.

### Post-evaluation design decision: lookup-table v2 (digest-only)
After the four evaluations, a direct design review of `PropertyLookup` concluded the
`(property_name, value)` key is not scale-safe: three indexed property names means three
partition keys, concentrating all login-path traffic on single partitions (1,000 WCU /
3,000 RCU pre-split ceiling — split-for-heat is reactive and lags burst load); the range
key caps values at 1024 bytes while the docstring claims the opposite; PII lives in key
material where it can never be pseudonymized without a format migration; and puts are
unconditional last-writer-wins. User selected the **digest-only** variant (value never
stored). Because the Phase 8 backfill will populate this table across every deployment,
the format change was pulled into this release — the only moment it is cheap (45 rows in
the measured production table). Consequences propagated into the plan: new
`_property_lookup_v2` table (key schemas are immutable), v1 kept read-only for rollback,
the dual-read fallback became three-tier (v2 → v1 → GSI) to protect the
already-on-lookup-mode cohort whose tables have no GSI to fall back to, and the 1024-byte
validation originally planned for Phase 6 was dropped as obsolete.

### Usability
Deployment-state matrix showed fail-fast (explicit legacy) and flip risk (implicit legacy)
protect disjoint cohorts, leaving the largest cohort uncovered → startup `logger.error`
made mandatory (Phase 8) and dual-read fallback chosen over the two-release split the
evaluator preferred (user decision: single release, made safe). Fluent naming
`with_dynamodb(auto_create_tables=)` + `AWS_DB_AUTO_CREATE_TABLES` per existing
conventions; `RuntimeError` fail-fast (no custom exception hierarchy exists) with the
three-ways-out message drafted in Phase 6. Six actively-wrong doc lines identified and
scheduled with the flip (Phase 8); demo-app guidance recorded as coordination notes.
`thoughts/todo` (singular) confirmed as the tracking location.
