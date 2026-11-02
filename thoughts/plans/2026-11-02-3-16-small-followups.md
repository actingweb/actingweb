---
status: active
---

# Implementation Plan: 3.16 small follow-ups (no owner input needed)

**Date:** 2026-11-02
**Research:** none of its own. The todo files are the research for this plan, and each item names the one it comes from:
`thoughts/todo/postgres-unit-tests-need-integration-schema.md`,
`thoughts/todo/mcp-token-manager-hygiene-followups.md`,
`thoughts/todo/permission-path-unbounded-caches.md`,
`thoughts/todo/property-lookup-stale-owner-and-races.md` (item 3),
`thoughts/todo/unique-creator-small-followups.md` (the single-action rows),
`thoughts/todo/adoption-fault-and-hygiene-followups.md` (the single-shape rows),
`thoughts/todo/v2-list-access-verification-followups.md` (the tests).
Code sites were re-pinned against `a3c4c36` on 2026-11-02.
**Branch:** `release/3.16.0-small-followups`. One PR after the last phase, one commit per phase, no version bump. 3.16.0 stays untagged.

## Overview

The owner asked for more items in 3.16. This plan takes the follow-ups whose todo already names a single fix, so none of them needs an owner decision. Each one is a test-infrastructure gap, a small correctness fix, a fix for unbounded memory or wasted cost, or a missing test.

Two changes are visible to consumers or operators:
- **The PostgreSQL backfill** no longer aborts on one over-long value. It reports the value as unindexable and leaves the name unmarked.
- **`modify_trust_and_notify_async`** actually notifies the peer. Until now a `KeyError` stopped it every time.

Every item that needs a choice stays in its todo, and "What We're NOT Doing" lists it.

## Decisions Made

- **D1 PostgreSQL schema for unit tests**: a session-scoped autouse fixture in `tests/conftest.py` that runs only when `DATABASE_BACKEND=postgresql`.
  - **Connection:** it connects with raw `psycopg`, not `actingweb.db.postgresql.connection`, so it builds no pool. It reads `PG_DB_*` with the same defaults as `tests/integration/conftest.py:189-193` (localhost:5433, actingweb_test).
  - **Lock and head check:** it takes `pg_advisory_lock` and compares `public.alembic_version` with the script head. A missing `alembic_version` table (`UndefinedTable`, a fresh database) counts as behind. When the schema is behind, it runs `poetry run alembic upgrade head` with `PG_DB_PREFIX` removed and `PG_DB_SCHEMA=public` set in the subprocess environment. It unlocks in `finally`.
  - **On DynamoDB** it returns before importing psycopg or alembic.
  - **Why this works:** root session fixtures run before the integration `setup_database`, and `tests/conftest.py:75` orders unit tests first. The integration fixture keeps its per-worker prefixed schema and its `close_pool()`.
  - **Effect on runs:** CI already migrates `public` (`.github/workflows/tests.yml:209`), so there the fixture only sees head and returns. The local `make test-all-parallel` on PostgreSQL does not migrate (`Makefile:58`), which is the gap the todo describes.
  - **Not in scope:** rows left in `public` by earlier runs are not cleaned. That is the same as CI today, and `make test-all-parallel` resets the containers with `down -v`.
  - *Deduced, not confirmed.*
- **D2 Over-long lookup values on the PostgreSQL backfill**:
  - **Failure handling:** when a batch `INSERT` fails with `psycopg.errors.ProgramLimitExceeded` (SQLSTATE `54000`, the btree row limit on `property_lookup`'s primary key), roll that batch back and re-insert its id range (`p.id > after AND p.id <= upto`) one row at a time, each under a savepoint.
    - A row refused with `54000` goes to a new **`unindexable`** category. Any other error is a fault, as today.
    - Fallback inserts count in `stats.written`.
    - All SQL uses `%s` placeholders.
    - The value never appears in output, only `value_bytes=N`.
  - **Reporting:** `BackfillStats` gains `unindexable: dict[str, list[str]]` and `unindexable_count`. `completed_names()` excludes those names, as it does for collisions, so the name stays unmarked and the command exits 1. Two outputs show it:
    - each skipped row gets its own log line, `UNINDEXABLE (value too long to index) property=… actor=… value_bytes=N`;
    - the summary gains `unindexable=N`.
  - **Next step for the operator:** the closing message names one way out: shorten or remove that property on that actor, then re-run (idempotent). It also says why marking the name complete is not offered. Every later write of that property on that actor fails: the unchanged-value path still inserts the lookup row (`db/postgresql/property.py:330-338`) and raises `DbError`, so marking the name would hide a lasting write failure. The DynamoDB-only "delete the checkpoint file" line does not appear for this cause. A new category beats reusing `collision`, whose message says two actors share a value (`property_lookup.py:885-889`), which is the wrong advice here.
  - **Dry run:** the existing missing-row query (`property_lookup.py:668-675`) also counts rows with `octet_length(p.value) > 2600` and reports them as "may be unindexable". That reuses its scan, and the collision `GROUP BY` excludes those rows so none is counted twice. The real limit applies to the compressed index tuple (about 2,704 bytes, including the name), so the raw size is only a hint. The dry run says "may", and the count changes neither the exit status nor `completed_names()`. Only a `54000` on the insert itself counts as unindexable.
  - **The runtime write path is unchanged:** on PostgreSQL, setting an indexed property to such a value already raises `DbError` (`db/postgresql/property.py:314-348`, fail closed). That limit is documented, not changed (see What We're NOT Doing).
  - *Deduced, not confirmed.*
- **D4 Async trust-approval notification** (`actor.py` `modify_trust_and_notify_async`):
  - **The bug:** the method builds `AwProxy(peer_target={"baseuri", "secret"})`, but `aw_proxy.py:78` reads `peer_target["id"]`. The `KeyError` is folded into "Not able to notify peer async", so the method has never notified a peer. It is a documented public method (`docs/sdk/async-operations.rst:29`), so making it do what its documentation says is a bug fix, not a behaviour choice.
  - **The fix:** delegate to the sync method, `return await asyncio.to_thread(self.modify_trust_and_notify, ...)` with the same arguments. That gives the same behaviour by construction:
    - a `POST trust/{relationship}/{self.id}` (`actor.py:1430`), the verb the receiver handles as a peer-approval notification (`handlers/trust.py:614-629`), where the old code sent `PUT`;
    - the old `baseuri` and the optional bearer header (`actor.py:1415`);
    - the sync method's `DbError` re-raise and `False` on other errors around `dbtrust.modify` (`actor.py:1386-1405`), which the async copy lacked.

    It also deletes the duplicated body. `asyncio.to_thread` copies context variables, so request correlation survives.
  - **Who sees the change:** nothing in the library calls this method; it exists only at its definition (`actor.py:1444`). Consumers that call it directly will now notify their peers, which runs those peers' `trust_fully_approved_remote` hook (`handlers/trust.py:670-692`).
- **D5 Bounded permission-path caches**:
  - **The type:** `BoundedDict(OrderedDict)` in `actingweb/_bounded_cache.py`, behind an `RLock`. It evicts the least recently used entry past `maxsize`, and `get` and `__getitem__` refresh recency. Subclassing keeps `== {}` and plain dict use working; `tests/test_peer_capabilities.py:797,865` compare with `{}`.
  - **The atomic read:** it adds one method, `lookup(key) -> tuple[bool, value]`. All four stores' check-then-index reads switch to it:
    - `trust_permissions.py:489`
    - `peer_profile.py:171`
    - `peer_permissions.py:258,306`
    - `peer_capabilities.py:553`

    The switch closes the window where another thread evicts the key between `in` and `[]`. It also keeps `trust_permissions.py:505`'s cached `None` (no override stored) a hit, where `.get()` would read it as a miss.
  - **Bound:** `maxsize=4096` per store, per process. *Deduced, not confirmed*: four times `_PATTERN_CACHE_MAX_ENTRIES = 1024`, because keys are (actor, peer) pairs, and about 16k small objects in all. Above 4096 live pairs the cache degrades to reading through to the store, which is correct, only slower.
  - **No TTL:** none of the stores has one today.
  - **Cost, accepted:** every hit now takes an uncontended `RLock` and does a `move_to_end`, a few microseconds on a path whose miss costs a database read. FIFO eviction would avoid writing on reads but would evict hot pairs. LRU is the precedent (`permission_evaluator.py:105`).
- **D6 `summarize_payload` guards**: wrap the eager sites in `if logger.isEnabledFor(<the line's level>):`, the pattern at `auth.py:344`. There are 16 DEBUG sites and one INFO site, `actor.py:1745-1747`, which gets an INFO guard. The guard matters most in the per-subscriber callback senders (`actor.py:2569-2573`, `2626-2630`); its test drives that path.
- **D7 Inline creator normalisation**: call `normalise_creator` at the copies in `actor.py` (`get_from_creator` 438, `creator_change_pinned` 854, `modify_creator_unvouched` 897, `modify` 960) and at `handlers/factory.py:254`.
  - `modify` keeps its `creator and` guard: the helper maps `None` to `""`, which would turn "no change" into an empty creator.
  - `factory.py` keeps `.strip()` before the call.
  - The `own_email.lower()` comparisons are not changed.
- **D8 `_restore_marker` log**: when the conditional update answers False, re-read `auth_method` with `get_attr_strict` and compare its `data`. The call returns a record or `None`.
  - If the value differs or the row is absent, the method logs the existing "changed since" warning.
  - On a `DbError`, or when the value is still `creator_changed`, it logs "could not restore auth_method (store fault)".
  - It returns False either way.
- **D10 `clear_pending_email_verification`** (`oauth2.py:1583`): also clear `email_verification_address`, the row in `unique-creator-small-followups.md`. The verify handler falls back from it to the stored email (`handlers/oauth_email.py:221`). Its token is gone at that point, so clearing it only removes leftover state, as `handlers/oauth_email.py:256` already does on the other path.
- **D9 Test-file renames** (`git mv`). Only dated `thoughts/` snapshots reference these files, and they keep the old names:
  - `test_adoption_fourth_iteration.py` → `test_adoption_siblings_and_clean.py`
  - `test_adoption_fifth_iteration.py` → `test_adoption_owner_actor_and_sweep_faults.py`
  - `test_adoption_sixth_iteration.py` → `test_adoption_strict_listing_and_rollback.py`

## What We're NOT Doing

- **The "duplicate tombstone" hygiene item.** The architecture evaluation showed the second write is deliberate.
  - `handlers/root.py:97-104` documents it, and `deletion.py:132-135` re-stamps `deleted_at` and the TTL. The retention window therefore runs from the wipe, not from before a possibly long `actor_deleted` hook.
  - Removing it saves one write and shortens late-write suppression.
  - The row is removed from the adoption todo, with that constraint recorded.
- **Changing the PostgreSQL runtime refusal of indexed values over about 2.7 KB** (`DbError` today). Turning that into a 400 or a skipped index is a contract choice. It is documented in the CHANGELOG and `docs/quickstart/configuration.rst`.
- **Owner decisions in `unique-creator-small-followups.md`:**
  - `actor_created` for a kept successor: fire it, or document it.
  - `#…` addresses with the flag off: the todo says "Consider".
  - Passing `unique_creator=` only when the flag is on: a contract choice, and the Breaking entry covers it.
  - The SDK rename's binding window: either order leaves a window.
  - Moving the default-creator sweep: it changes the create path.
- **Owner decisions in `adoption-fault-and-hygiene-followups.md`:**
  - J, K, AW and BG: multi-option fixes.
  - `find_db_error`'s `__context__`: which exceptions answer 503 is a contract choice.
  - Flask CORS: an allowlist, or drop credentials.
  - The callback version check, the ordering windows and the post-commit folds: each needs a design.
  - BK to BQ: design or cost work across the sign-in paths.
  - `purge_relationships` and the redundant replace-path cleanup: cost work on the deletion path, worth its own review.
- **GitHub `/user/emails` called twice** (`github-emails-api-called-twice.md`): this goes back to the owner.
  - The todo forbids a cache that straddles requests.
  - The outside voice showed the only path that calls both methods builds its authenticator per request (`handlers/oauth2_callback.py:153,280,1416`), while the long-lived authenticator (`oauth2_server/oauth2_server.py:65`) calls only `get_primary_email` (`:373`).
  - A correct fix is request-local: memoise on the per-request authenticator, or fetch once at the two callback sites (`oauth2_callback.py:388-407`, `1083-1097`). Choosing where it lives, and whether a failure is reused, is a design choice.
  - The finding goes into the todo, which stays.
- **Reverse-lookup items 1 and 2:** the todo says each needs a design.
- **The bulk-count note in `v2-list-access-verification-followups.md`:** the todo says to revisit it only on a consumer report.
- **The `#` in a creator URL check:** there is nothing to change.
  - No template or handler builds a URL path from the creator; it is display only, for example `actingweb/templates/aw-actor-www-root.html:8`.
  - Query strings go through `urlencode`, which escapes `#`.
  - The row is removed from the todo as checked.
- **Item 2 of `mcp-token-manager-hygiene-followups.md`:** a note, not work. The SPA and MCP refresh ladders share only `single_use.consume_once`, and `2026-09-27-refresh-grace-setting.md` kept them separate on purpose. The todo file is deleted with item 1.

## What Already Exists

- `actingweb/db/creator_rules.py:32` `normalise_creator`: D7.
- `actingweb/auth.py:344`, the `isEnabledFor` guard: D6.
- `actingweb/permission_evaluator.py:36,105`, the 1024 bound with an LRU: the precedent for D5.
- `actingweb/maintenance/property_lookup.py:389-423` `BackfillStats`, with `completed_names` at `:419`: D2 extends it.
- `tests/integration/conftest.py:189-193,413-440`: the PostgreSQL defaults and the alembic subprocess that D1 copies.
- `actingweb/db/dynamodb/_ensure.py:73` `ensure_table`: the performance fixture.
- `actingweb/db/protocols.py:1267` `get_attr_strict`: D8.
- `tests/test_property_list_integrity.py:31,171`, `FakePropertyDb` and `_patch_get_property`, and the raising fakes in `tests/test_v2_list_mutation_committed.py:68-131`: the seam for the list fault tests.
- `tests/test_db_fault_contract.py:186`: the PostgreSQL model for the DynamoDB `modify` test.
- `tests/test_trust_creator_rename.py:243-300`: the existing `_restore_marker` tests. D8 extends them.
- `tests/integration/test_subscription_baseline_storage.py:145-212`: a real subscription sync into `RemotePeerStore`, the template for the replica test.

## Phase 1: Test infrastructure that stands on its own

### Changes

- `tests/conftest.py`: the D1 fixture, `_postgresql_unit_schema`, and its helper `ensure_postgresql_schema() -> bool` (True when it migrated).
- `tests/performance/conftest.py` (new): a module-scoped autouse fixture that calls `ensure_table(Attribute)` on DynamoDB (the static `set_attr`/`get_attr` the benchmarks call never ensure it; the property and actor constructors already do), and does nothing on PostgreSQL.

### New Tests, both unit and integration tests

- `tests/test_postgresql_unit_schema.py`, PostgreSQL only:
  - With `subprocess.run` patched, a schema already at head makes `ensure_postgresql_schema()` return False without running the subprocess.
  - A missing `alembic_version` table counts as behind.
  - With the head comparison forced to "behind", it runs the subprocess once. The subprocess environment has no `PG_DB_PREFIX` and has `PG_DB_SCHEMA=public`, which is the regression for running the migration against the wrong schema.
- Manual check: the unit command with `--ignore=tests/integration`, run serially on a fresh PostgreSQL database, passes. The todo recorded 44 failures for it.

### Failure Scenarios

- **Two xdist workers migrate `public` at once:** the advisory lock serialises them, and the second worker sees head. Covered by the parallel Full tier on a fresh PostgreSQL database.
- **The alembic subprocess fails** (bad environment, database down): `check=True` raises at session start with alembic's stderr.
- **A developer's shell sets `PG_DB_PREFIX`:** it is removed from the subprocess environment. Covered by the test above.
- **The benchmarks run on a fresh DynamoDB container:** the fixture creates the tables. Manual check: a benchmark run on a fresh container.

### Verification

- [ ] Fast tier
- [ ] The serial unit command on a fresh PostgreSQL database: 0 failures
- [ ] `pytest tests/performance -m benchmark -p no:rerunfailures` on a fresh DynamoDB container: no `ResourceNotFoundException`
- [ ] Full tier before commit

### Implementation Status: Not Started

---

## Phase 2: Small correctness fixes

### Changes

- `actingweb/maintenance/property_lookup.py`: D2. That covers the batch fallback, `BackfillStats.unindexable`, the dry-run count, the log line, the summary field and the closing message.
- `actingweb/oauth2.py`: D10.
- `actingweb/actor.py`:
  - D4: `modify_trust_and_notify_async` delegates to `modify_trust_and_notify` through `asyncio.to_thread`;
  - D8: the `_restore_marker` re-read.

### New Tests, both unit and integration tests

- **Backfill** (`tests/test_property_lookup_command.py`, PostgreSQL only):
  - A value of 4,000 random, incompressible bytes (hex of `os.urandom`, so PostgreSQL's compression cannot shrink it under the limit) among normal rows: `--apply` writes the normal rows, counts the long one as `unindexable`, leaves the name unmarked and exits 1. The closing message names the one way out and does not say "two actors".
  - The dry run reports "may be unindexable" and does not count that row as a collision. Its exit status is unchanged by that count: 0 when there are no collisions.
  - A non-`54000` error inside a batch is still a fault.
  - The regression: before the change the pass faults and writes nothing after the bad batch.
- **Async approval** (`tests/test_trust_approve_notify_async.py`, new; `requests.post` mocked):
  - Approving an unapproved trust sends one `POST <baseuri>/trust/<rel>/<self.id>` with `{"approved": true}` and the bearer secret. This is the regression: before the fix the `KeyError` stops it and nothing is sent.
  - An unchanged approval sends nothing.
  - The early returns (no `relationship` or `peerid`, no matching trust) answer False.
  - A `DbError` from `dbtrust.modify` propagates.
  - The async method returns what the sync method returns, for the same arguments.
- **`_restore_marker`** (`tests/test_trust_creator_rename.py`):
  - A fake `conditional_update_attr` returns False and `get_attr_strict` raises `DbError`. The test asserts the "store fault" log and no "changed since" log.
  - A re-read still `creator_changed` (the update faulted) gives the same "store fault" log.
  - The existing `test_r8_a_clean_that_landed_meanwhile_is_not_restored_over` gains a `caplog` assertion for "changed since".
- **`clear_pending_email_verification`:** the address is cleared together with the token.

### Failure Scenarios

- **The per-row fallback faults part way through:** a non-`54000` error becomes `stats.fault()`, as a batch fault does now, and the committed rows stay. Covered by the fault test.
- **The async approval goes to a peer that is down:** the sync method's handling applies: the trust is saved, and the failure is logged and visible in `last_response_code`. Covered by the parity test.
- **`asyncio.to_thread` runs a blocking call in the default executor:** the same blocking I/O the sync method does, now off the event loop, which is the point of the async variant.

### Verification

- [ ] Fast tier
- [ ] Full tier before commit

### Implementation Status: Not Started

---

## Phase 3: Hygiene

### Changes

- **Debug-log guards (D6):**
  - `actingweb/actor.py`: 188, 241, 1747 (INFO), 2267, 2286, 2573, 2630
  - `actingweb/aw_proxy.py`: 251, 314, 552, 656
  - `actingweb/handlers/oauth2_endpoints.py`: 284, 294
  - `actingweb/interface/integrations/fastapi_integration.py`: 744, 1447, 2190, 2625
- **Bounded caches (D5):** `actingweb/_bounded_cache.py`, used in four stores. Each store's reads change to `lookup()`:
  - `actingweb/trust_permissions.py`
  - `actingweb/peer_profile.py`
  - `actingweb/peer_permissions.py`
  - `actingweb/peer_capabilities.py`
- **Creator normalisation (D7):** `actingweb/actor.py` and `actingweb/handlers/factory.py`.
- **Type hints:**
  - `actor.py`: `delete_peer_trustee`, `delete_reciprocal_trust` and `delete_reciprocal_trust_async`;
  - `db/dynamodb/trust.py`: `get` and `fetch`;
  - `db/dynamodb/subscription.py`: `get` and `fetch`;
  - `db/dynamodb/subscription_diff.py`: `get` and `fetch`;
  - `db/dynamodb/peertrustee.py`: `get`;
  - `db/dynamodb/attribute.py`: the `strict=` signatures at 88, 131, 158, 571 and 595.
- **Test-file renames (D9):** the three adoption test files.

### New Tests, both unit and integration tests

- `tests/test_bounded_cache.py`:
  - eviction drops the least recently used entry;
  - `get`, `__getitem__` and `lookup` refresh recency;
  - `lookup` of a cached `None` is `(True, None)`, and of a missing key `(False, None)`;
  - `pop`, `clear` and `== {}` behave as on a dict;
  - eight threads calling `lookup`, set and evict on one small cache raise no `KeyError`, and `len <= maxsize` holds.
- `tests/test_permission_cache_bounds.py`:
  - each store's `_cache` is a `BoundedDict`;
  - `TrustPermissionStore` with a cached negative entry does not re-read the store;
  - an evicted entry is reloaded on the next read.
- `tests/test_debug_payload_guard.py`: with DEBUG off, `summarize_payload` is patched to raise. A subscription callback send (`_send_callback_sync`) and an `aw_proxy` request still succeed.
- `factory.py`: a create with `"  Alice@X.com "` still yields the creator `"alice@x.com"`. The existing creator suite pins the other copies.

### Failure Scenarios

- **Eviction races a read:** `lookup` is one locked call, and a miss reads through to the store. Covered by the thread test and the reload test.
- **A replaced copy differed from the helper:** only `factory.py`'s strip and `modify`'s `None` guard differ, and both are kept. Covered by the strip test and the existing suite.

### Verification

- [ ] Fast tier
- [ ] pyright 0 errors with the new hints
- [ ] Full tier before commit

### Implementation Status: Not Started

---

## Phase 4: Missing tests, docs, changelog, todos

### Changes

- **Tests:**
  - `tests/test_db_fault_contract.py`: on DynamoDB, a non-conditional `PutError` and a generic exception from `Model.save` in `DbActor.modify` each raise `DbError` and leave the handle's creator and passphrase as stored.
  - `tests/test_property_list_fault_reads.py` (new):
    - a `FakePropertyDb` subclass whose `get_range` or `get_prefix` raises `DbError`;
    - v2 iteration, indexing and `find` (through `to_list`) on a v2 list raise `DbError` instead of answering empty;
    - a spanned list's `get_prefix` fault raises too.
  - `tests/integration/test_property_list_v2.py`: two `ListProperty` handles on one list append alternately ten times, and iteration order equals insertion order. It runs on both backends through CI.
  - `tests/integration/test_list_diff_peer_replica.py` (new, its own xdist group, modelled on `test_subscription_baseline_storage.py`):
    - the publisher's `remove_where` and `update_where` diffs, delivered through a real subscription, leave the subscriber's `RemotePeerStore` equal to the source;
    - a spanned item's diff is skipped with its warning.
  - `tests/integration/XDIST_GROUPS.md`: a row for the new group.
- **Docs:**
  - `docs/migration/v3.16.rst`, "What the flag changes once enabled":
    - the DynamoDB rename's two-step record move: the old creator answers `CreatorTaken` until its record is released;
    - a hand-edited record pointing at the wrong actor shows up only as an orphaned record (`mismatch`) in `report` (`maintenance/unique_creators.py:376-389`).
  - `docs/quickstart/configuration.rst`: on PostgreSQL a large indexed value may exceed the index row limit (about 2.7 KB after compression). Writing it then raises `DbError`, and the backfill reports existing ones as unindexable.
- **`CHANGELOG.rst`, Unreleased, FIXED.** Each entry follows the `### Changelog` style: a bold symptom, the cause, the new behaviour, and what to check.
  - The backfill: **Behavior change:** it commits the other rows, reports `unindexable` and exits 1 where it used to abort. It also says that the actor cannot write that property until the value is shortened.
  - The async approval: **Behavior change:** callers of `modify_trust_and_notify_async` now notify the peer, which runs `trust_fully_approved_remote` there.
  - `email_verification_address` is cleared with its token.
  - The permission caches: unbounded growth on long-lived workers, now at most 4096 entries per store, LRU.
- **Todos** (`thoughts/todo/` and `INDEX.md`). `github-emails-api-called-twice.md` stays, with the request-local finding added:
  - Delete these files and their rows:
    - `postgres-unit-tests-need-integration-schema.md`
    - `mcp-token-manager-hygiene-followups.md`
    - `permission-path-unbounded-caches.md`
  - Trim these:
    - `property-lookup-stale-owner-and-races.md` to items 1 and 2;
    - `unique-creator-small-followups.md` to the five decision rows plus the unverified-records row, if it is not covered by the docs;
    - `adoption-fault-and-hygiene-followups.md` without the done rows. The tombstone row is replaced by its constraint.
    - `v2-list-access-verification-followups.md` to the bulk-count note.

### Failure Scenarios

- **The replica test is slow or flaky under xdist:** it has its own group, and `verify_groups.py` checks that the group is documented.

### Verification

- [ ] Fast tier
- [ ] `poetry run python tests/integration/verify_groups.py`
- [ ] Full tier, including sphinx `-W`

### Implementation Status: Not Started

---

## Evaluation Notes

### Architecture
- **The duplicate tombstone write is deliberate** (`handlers/root.py:103-104`; `deletion.py:132-135` re-stamps `deleted_at` and the TTL). The item is dropped and moved to What We're NOT Doing, with its constraint recorded.
- **BoundedDict check-then-index race:** the stores read with `in` and then `[]` (`peer_profile.py:171-172` and the three others), which can race with eviction. Fixed with an atomic `lookup()`. A subclass of `OrderedDict` keeps `tests/test_peer_capabilities.py:797` (`== {}`) working.
- **D1's prefix wording was backwards:** the integration fixture *sets* `PG_DB_PREFIX` (`tests/integration/conftest.py:366`). The root fixture now removes it from its subprocess environment, uses raw psycopg, and uses the integration defaults.
- **D4's no-secret path** (`aw_proxy.py:543`) no longer matters: D4 now delegates to the sync path. The method has no caller in the library, which the changelog states.

### Security
- **D3 cache safety** findings are moot: D3 is out of scope.
- **D4** now delegates to the sync path, so it sends the same request, to the same address, with the same secret handling.
- **D7:** `modify`'s `creator and` guard is kept. The helper does not make any comparison newly case-insensitive.
- **D2:** placeholders only, and the value never appears in output.

### Scalability
- **D6 site levels:** `actor.py:1745-1747` logs at INFO and gets an INFO guard. The per-subscriber callback sites are the ones whose cost grows with load, and the guard test drives one of them.
- **D2 fallback scope:** limited to the failing batch's id range. The dry-run size check folds into the existing missing-row query, which avoids another full scan (`properties` has no value index since `c3d4e5f6a7b8`).
- **D5:** the bound is per process. Above 4096 pairs the cache degrades to read-through.
- **D1:** the lock is released in `finally`, and a DynamoDB run returns before any import.

### Usability
- **D2 categories:** reusing "collision" gave the wrong advice, so `unindexable` is a separate category with its own next step and no checkpoint line.
- **The runtime limit for over-long indexed values on PostgreSQL** is documented, not changed.
- **D4's changelog names the `trust_fully_approved_remote` hook.**
- **Changelog entries** follow the project style, with Behavior change sentences.
- **The public tombstone flag is gone** with D5's removal, so there is nothing new to misuse.

### Tests and code quality
- **`find` reads through `to_list`**, and spanned items use `get_prefix`. The fault fake covers both.
- **The async approval test mocks `requests.post`** (after the outside voice, D4 delegates). The regression fails before the fix, and the early returns are added.
- **The `_restore_marker` tests extend `tests/test_trust_creator_rename.py`** instead of duplicating its "changed since" case.
- **The replica test gets its own xdist group:** there is no shared subscription group (`XDIST_GROUPS.md:25-61`).
- **D5's tests are trimmed** to type checks plus the cached-negative and reload behaviour, with no per-store eviction repeats.

### Outside voice
Providers: codex (read-only, outside the sandbox) and a fresh-context Claude. What changed:
- **D2:**
  - The PostgreSQL limit applies after compression, so the test uses incompressible data, and the dry run and docs say "may".
  - Marking a name with an unindexable value would hide a lasting write failure (`db/postgresql/property.py:330-338`), so the only exit offered is to shorten the value.
  - The dry-run estimate no longer affects the exit status or eligibility.
- **D3 is removed from scope and goes back to the owner.** It contradicted its own todo's rule against straddling requests, and the long-lived authenticator never calls both methods (`oauth2_server/oauth2_server.py:373`).
- **D4 now delegates to the sync method** (`asyncio.to_thread`). That removes both documented differences and the missing `DbError` handling around `dbtrust.modify` (`actor.py:1386-1405`). Fixing beats deprecating, because the method is documented public API (`docs/sdk/async-operations.rst:29`).
- **D1:** a missing `alembic_version` table counts as behind. Leftover rows in `public` are out of scope; that matches CI.
- **D5:** the lock cost per hit is stated and accepted.
- **D8:** the code compares the record's `data`, and a missing row counts as changed.
- **D10** now has its own number.
- **The performance fixture** ensures only `Attribute`.
- **Not adopted:**
  - Deferring D7, D9 and the type hints. They are rows the todos list as owed, they are mechanical, and the owner asked for no-input items.
  - Moving every `actor.py` edit into one phase. The phases are grouped by risk, and the edits do not conflict.

### Unverified notes
- Under `--dist loadgroup` a worker's unit tests may run after its integration `setup_database` has set `PG_DB_PREFIX` in the process (`tests/integration/conftest.py:366`), so those tests use the prefixed schema, not `public`. That is already true today and works in CI, because each schema is migrated. D1 does not change it.
- **Whether `to_list` on a v1 list reads through `get_range`:** not checked. The list fault test names the v2 format it covers.
