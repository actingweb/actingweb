---
status: done
verified: thoughts/verifications/2026-11-05-3-16-dependency-security-rollup-reverify-4.md
---

# Implementation Plan: 3.16 roll-up: dependency security upgrade and the small bounded follow-ups

**Date:** 2026-11-04
**Research:** none of its own. The todo files are the research for this plan, and
each item names the one it comes from:
`thoughts/todo/unique-creator-direct-config-auto-create.md`,
`thoughts/todo/dynamodb-known-next.md` (item 4),
`thoughts/todo/spa-logout-refresh-rotation-race.md`,
`thoughts/todo/logout-mcp-token-with-spa-refresh-cookie.md`,
`thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`,
`thoughts/todo/mcp-cache-lifecycle-and-revocation.md` (sections 4 and 7).
The dependency upgrade is the uncommitted diff on the branch. Code sites were
pinned against `8bbaa88` on 2026-11-04 by four read-only lookups, five
evaluators and the outside voice (Codex and a fresh-context Claude).
**Branch:** `release/3.16.0-dependency-security`. One PR after the last phase,
one commit per phase, no version bump. 3.16.0 stays untagged.

## Overview

The owner reviewed the 3.16 scope on 2026-11-04 and asked for one more roll-up
before the release: the dependency security upgrade already on the working
tree, plus every open todo that is small, bounded and needs no new storage
primitive. The owner confirmed each item that day and took the decisions that
were open (the creators-table shape on both backends, the logout-race fix and
its reach, the mixed-logout rule, the `callback` type contract); they are
recorded below.

Four changes are visible to consumers or operators:

- **A process that builds a bare `Config()` with creator uniqueness on fails
  closed on both backends** when `actingweb-unique-creators enable --apply`
  has not run: on DynamoDB the constructor no longer creates an empty
  `<prefix>_creators` table, on PostgreSQL the first enforced create probes
  for the `ux_actors_creator` index. Either way the create raises `DbError`
  (503 through the integrations) with an ERROR that names the command,
  instead of claiming the creator against nothing.
- **A token chain revoked while a refresh rotation is in flight stays
  revoked**, on the SPA ladder, the MCP ladder and the actor-deletion
  finisher. The rotation revokes what it minted.
- **An MCP-token logout touches nothing of the SPA session**: it revokes the
  MCP chain only and clears no cookie.
- **FastAPI answers `resources/read` exactly as Flask does**: the same body,
  `mimeType`, hook arguments and URI matching.

Everything that needs a design or a new cross-table primitive stays out, and
"What We're NOT Doing" names it.

## Decisions Made

- **D1 Dependency upgrade**: commit the working-tree diff as it stands
  (`pyproject.toml` `pyjwt = "^2.15"`, `poetry.lock`, `docs/requirements.txt`,
  the SECURITY changelog entry, `thoughts/todo/drop-python-3-11-after-eol.md`
  with its `INDEX.md` row). Two corrections to the entry at `CHANGELOG.rst:9-29`:
  - the lock also moves `python-discovery` 1.6.0 to 1.9.4 (a `virtualenv`
    dependency, development only); the line at `:26` names it beside
    `filelock` and `virtualenv`, so the entry stays exactly true;
  - the **Check** sentence gains the consumer's self-remedy: v3.15.1 ships
    the same unverified decode (`handlers/oauth2_spa.py`, `verify_signature:
    False`) with a `^2.14` floor, so a deployment on 3.15.1 closes the
    advisory today with `pip install -U "pyjwt>=2.15"`, no library release
    needed. The runbook allows no 3.15.2 (master carries 3.16; a tag off
    master fails the workflow), and the owner holds one PR for this roll-up
    (2026-11-04), so the sentence is the remedy until 3.16.0 is tagged.

  `oauthlib` 4.0.1's breaking changes are on the provider side; the library
  imports only `WebApplicationClient` and `generate_token`
  (`actingweb/oauth2.py:19-20`), and the OAuth2 suites exercise both. That
  is what the fast tier proves; nothing more is claimed.
- **D2 Creators uniqueness fails closed on both backends** (owner,
  2026-11-04: option (a) on DynamoDB; the PostgreSQL probe for symmetry).
  **[Updated 2026-11-04]** On DynamoDB an enforced write also requires the
  backfill-complete item (read once per process, positive only), because the
  `check_ready()` prewarm leaves an empty table behind; see Iteration 1:
  - **DynamoDB:** remove `if unique_creator: ensure_table(Creator)` from
    `actingweb/db/dynamodb/actor.py:575-576`; `ensure_table(Actor)` stays.
    The two remaining creators of the table are deliberate and unchanged: the
    `check_ready()` prewarm (`actingweb/interface/app.py:1540-1544`, through
    `required_models(unique_creator=True)` at
    `actingweb/db/verify_tables.py:77-80`) and `enable --apply`
    (`actingweb/maintenance/unique_creators.py:1014-1015`). "A fresh
    deployment starts once, which creates the tables and stops" stays true
    for `integrate_*`; it is the bare-`Config()` path that changes. Nothing
    in `enable`, `report` or `resolve` depends on the constructor: every
    `Creator` read there guards `Creator.exists()` itself (`:336-337`,
    `:634-635`, `:677-678`), and `grep create_table\(` in `actingweb/` finds
    only `_ensure.py:97` and `unique_creators.py:1015`.
  - **No new DynamoDB fault mapping.** Every claim (create, rename, replace)
    goes through `_run_transaction` (`actingweb/db/dynamodb/actor.py:546-569`).
    PynamoDB wraps every botocore error as `TransactWriteError` with
    `cancellation_reasons == []` for anything but a cancelled transaction, so
    a missing table has no `ConditionalCheckFailed` code and both `except`
    clauses end in `raise DbError(op)`; the only `False` from `create` is
    `_actor_exists` after a `ConditionalCheckFailed` (`:317-324`).
    `_release_record` (`:471-494`) keeps logging a missing table at ERROR
    without raising: a release after a delete is best-effort by design.
  - **An ERROR that names the remedy, both backends.** The 503 the
    integrations answer is `temporarily_unavailable` with `Retry-After`
    (`interface/integrations/_errors.py:110-117`; `ResourceNotFoundException`
    is not a permanent code at `:45-51`) and the fault log names only
    `actor create`. So the claim site logs, once per occurrence, before
    raising: *"Creator uniqueness is on but `<prefix>_creators` does not
    exist (DynamoDB) / the `ux_actors_creator` index is missing
    (PostgreSQL), so the actor create was refused. Run
    `actingweb-unique-creators enable --apply`, or call
    `ActingWebApp.check_ready()` before creating actors; see
    docs/migration/v3.16.rst, 'Creator uniqueness'."* On DynamoDB the
    detection is `is_resource_not_found(e)`
    (`actingweb/db/dynamodb/property_lookup.py:85-92`) inside
    `_run_transaction`'s `except`. The 503 contract itself is not changed
    (making a missing table permanent is a decision for every path).
  - **PostgreSQL:** there is no creators table; enforcement is the partial
    unique index `ux_actors_creator` that only `enable` builds
    (`actingweb/db/postgresql/actor.py:35-43`, `unique_creators.py:984-991`),
    and a create without it is a plain `INSERT` that lands the duplicate
    (`:205-230`: `CreatorTaken` fires only on a `UniqueViolation` naming the
    index). So the same misconfiguration answered 503 on one backend and a
    silent duplicate on the other. Fix: `_creator_index_present() -> bool`
    in `actingweb/db/postgresql/actor.py`, the `pg_index`/`pg_class` validity
    query `unique_creators.py:945-953` runs, cached **positive only** in a
    module global (a fault or an absent index is re-probed next time), with
    `reset_index_probe()` for the fixtures. `create()`, `_modify_unique`'s
    equivalent and `replace_creator_holder` call it when
    `self.unique_creator and not is_exempt(creator)` and raise
    `DbError("creator uniqueness index missing")` after the ERROR above. The
    constructor stays free: `Actor(actor_id, config)` is how every read
    starts, and a read-only process must not pay a probe. One query per
    process on the first enforced write. `missing_enforcement`'s PostgreSQL
    branch (`unique_creators.py:945-953`) imports the db-layer probe instead
    of keeping its own copy of the query (maintenance → db is the existing
    import direction).
  - **System actor bootstrap:** `oauth2-system` is in `SYSTEM_CREATORS`, not
    `EXEMPT_CREATORS` (`actingweb/db/creator_rules.py:22,26,38-40`), so
    `ensure_oauth2_system_actor` (`oauth2_server/system_actor.py:63-69`,
    `except DbError: raise` at `:93-94`) also fails closed on such a store.
    Consistent; the docs sentence says "creating an actor, including the
    OAuth2 system actor bootstrap", so a 503 on the first MCP client
    registration is explained.
  - **Test tiers:** the shared `test_` stores hold deliberate duplicate
    creators (`tests/_lookup_probe.py:69-81`), which is why the readiness
    probe is stubbed session-wide. Two more session-scoped autouse fixtures:
    on DynamoDB, `_creators_table` in `tests/conftest.py` beside
    `_postgresql_unit_schema` runs `ensure_table(Creator)` once (today the
    table exists there only because the constructor made it; confirmed
    dependant `tests/test_actor_created_fires_once.py:98-119`; the
    integration workers get it from the harness prewarm); on PostgreSQL, the
    index cannot be built over duplicates on **either** tier (the per-worker
    integration schema comes from alembic, which deliberately excludes the
    index), so `_stub_pg_creator_index_probe` lives in `tests/_lookup_probe.py`
    beside `_stub_unique_creator_probe` and is imported by **both**
    `tests/conftest.py` and `tests/integration/conftest.py:23-26`, exactly as
    the readiness-probe stub is today, with a `real_pg_index_probe` fixture
    for the tests about it. Both new fixtures guard on `DATABASE_BACKEND` the
    way `_postgresql_unit_schema` does, so a DynamoDB run imports no psycopg.
    Session scope is right: an integration-only run never loads the root
    conftest (`tests/_lookup_probe.py:11-14`), a full run has frozen the
    `test` prefix at collection anyway, and a function-scoped fixture would
    run after `unique_creator_store` renamed `Creator.Meta.table_name` and
    create a `uc_` table that `wipe_store` then deletes.
  - **Integration tier:** `wipe_store` (`tests/integration/_isolated_store.py:134-167`)
    keeps recreating only `Actor`; it and `enable_enforcement` (`:170-177`)
    call `reset_index_probe()` beside `reset_ensure_cache()`, or a cached
    positive outlives the index it saw. A `fresh_store` test that creates an
    enforced actor before `enable` now gets `DbError` on both backends.
    Confirmed from reading: `test_unique_creator_states.py:235-243`
    (`test_disable_finishes_a_partial_run`), which should seed with `_raw_row`
    (`:78`) so the actor exists without a claim and `enable --apply` still
    backfills it; most of `test_unique_creators_command.py` seeds with the
    flag off (`:34-37,40-55`) and survives. The run enumerates the rest
    (Phase 1 verification).
  - `actingweb/maintenance/deletions.py:80-88` builds an enforced `DbActor`
    (default on) and only releases records; unchanged in behaviour.
  - **Docs:** `docs/migration/v3.16.rst:258-263` ("Direct `Actor.create` …
    callers … Nothing to do otherwise") is false after this and is rewritten;
    `:855-857` and `docs/quickstart/configuration.rst:43` change "should
    call" to "must call" and gain: *"Without it, with uniqueness on and
    `enable --apply` not yet run, every actor create, including the OAuth2
    system actor bootstrap, raises `DbError` (`database error during actor
    create`, 503 through the integrations, and retrying does not clear it)
    on both backends. Run `actingweb-unique-creators enable --apply` first,
    or call `check_ready()`, which names the command."*
    `getting-started.rst:192-198`, `mcp-quickstart.rst:73` and
    `p2p-quickstart.rst:123` stay true for `integrate_*`.
  - **`report` on a missing table:** `_dynamodb_records`
    (`unique_creators.py:336-337`) returns silently when the table is
    absent, so on the exact store this item is about `report` prints nothing.
    It logs *"the DynamoDB table `<name>` does not exist; run `enable
    --apply`"* instead. (The plan's earlier claim that `report` lists the
    stale record is true only once the table exists.)
- **D3 Fleet enumeration for the operator commands:**
  - `DbActorListProtocol` (`actingweb/db/protocols.py:212-226`) gains
    `iter_rows(*, consistent: bool = False, rate_limit: float | None = None)
    -> Iterator[dict[str, Any]]`, yielding `{"id", "creator"}` rows as they
    are read. Additive and keyword-only: a minor-safe protocol change
    (`tests/test_db_protocols.py:54-57` picks it up; both real implementers
    gain it; no other implementer exists outside two test fakes, below).
    `fetch()` keeps its signature and list result.
  - DynamoDB (`actingweb/db/dynamodb/actor.py:584-606`):
    `Actor.scan(attributes_to_get=["id", "creator"], consistent_read=consistent,
    rate_limit=rate_limit)`, the shape `unique_creators.py:197-207` uses;
    PynamoDB pages the scan lazily. A fault raises `DbError("actor list
    scan")` from wherever the iteration is. `fetch()` gains
    `attributes_to_get=["id", "creator"]`: fewer wire bytes and no
    `passphrase` in memory, **not** fewer read units (Scan is charged on bytes
    scanned; the changelog must not claim a cost saving).
  - PostgreSQL (`actingweb/db/postgresql/actor.py:434-471`): keyset pages,
    `SELECT id, creator FROM actors WHERE id > %s ORDER BY id LIMIT %s` with
    a module constant `_ITER_PAGE = 1000`, **one `with get_connection()` per
    page, released before the `yield`** (a generator abandoned mid-sweep must
    not hold a pooled connection; `PG_POOL_MAX_SIZE` is 10). `actors.id` is
    the primary key (`migrations/versions/3307e3616c5e_…py:31`), so each page
    is a btree range scan. `consistent` and `rate_limit` are accepted and
    ignored; the docstring says reads are read-committed **per page**, not a
    fleet snapshot (an actor created, deleted or renamed between pages can
    appear in neither or both), which every caller below tolerates.
  - `actingweb/maintenance/mark_actors_vouched.py:143-158`: inside the
    existing `try`, collect `(id, creator)` from
    `iter_rows(consistent=True, rate_limit=args.rate_limit)`, applying the
    `--creator` and `--start-after` filters **at collection time**, then the
    existing `sorted(...)` loop. Collecting before the loop keeps the exit-2
    contract exactly ("nothing was scanned" when the list could not be read)
    and the `--start-after` resume contract (sorted ids). Memory is about
    220 MB per million actors (two short strings and a tuple each), down from
    about 350 MB for the dict rows today; the migration guide states it.
    Consistent reads: the command writes the scanned `creator` back
    (`:107-108`), the same reason `enable` forces them (`unique_creators.py:1279-1280`);
    a seconds-old actor it missed would be cleaned at its first sign-in. New
    flag `--rate-limit` (DynamoDB read capacity units per second, ignored on
    PostgreSQL), the name `actingweb-unique-creators` uses
    (`unique_creators.py:1225-1230`), with help text that says the scan is
    strongly consistent and so costs twice the read units of an eventual
    one, because `--help` shows only the docstring's first paragraph
    (`:209`). The dead `isinstance(rows, list)` check (`:153-154`) and the
    stale docstring line "PostgreSQL answers a fault with `False`"
    (`:139-141`) go.
  - `actingweb/maintenance/verify_property_lists.py:498` and
    `migrate_property_lists.py:505` iterate `iter_rows()` directly
    (eventually consistent: their loops use only `actor["id"]` at `:519` /
    `:527`, classify list rows per actor afterwards, and resume from a
    per-actor checkpoint). **No new flag**: both already have `--rps` for
    the per-list rate, and a second throttle beside it would confuse. Their
    "No actors found" early return (`:506-508`, `:513-515`) becomes a counter
    after the loop. A fault mid-sweep stops the sweep where it is, keeps the
    checkpoint, and exits with the same code 2 their fetch fault uses today
    but a message naming how many actors were handled and that a re-run
    resumes from the checkpoint. Their integration fakes
    `_OneActor.fetch` (`tests/integration/test_migrate_property_lists_script.py:305-309`,
    `test_verify_property_lists_script.py:372-376`) gain `iter_rows`.
  - `actingweb/maintenance/verify_orphans.py:227-236` routes through
    `iter_rows(consistent=True)`: its docstring's reason for a hand-rolled
    consistent scan is exactly what the method provides. `unique_creators.py`'s
    `_dynamodb_actor_rows` (`:197-207`) keeps its own scan: it is the one
    command every operator runs on upgrade, and the swap buys nothing it does
    not already have.
  - `tests/test_adoption_write_faults.py:108-116,201-208` patch
    `actingweb.db.get_actor_list` (the lazy import at `mark_actors_vouched.py:143`
    keeps the seam) and set `fetch`; they move to an `iter_rows` that raises
    on first pull. `iter_rows` cannot be a `PG_READS` row in
    `tests/test_db_fault_contract.py` (a generator does not raise until
    iterated and has no `strict`); it gets two dedicated tests (Phase 3).
- **D4 A revoked chain stays revoked under a concurrent rotation: a
  chain-revoked marker written before every sweep, and a post-mint check in
  every rotation** (owner, 2026-11-04; shape 1 of the todo with the marker
  anchor, extended to the MCP ladder and the deletion finisher):
  - **One ladder-neutral helper pair in `actingweb/single_use.py`**, beside
    `revoke_chain_confirmed` which both stores already share
    (`oauth_session.py:1089`, `token_manager.py:25`):
    `mark_chain_revoked(config, actor_id, bucket, chain_id)` writes
    `set_attr(actor_id, bucket, name=chain_id, data={"revoked_at": now},
    ttl_seconds=CHAIN_REVOKED_MARKER_TTL)` and raises `StoreFault` on a
    `False` or an exception; `chain_revoked(config, actor_id, bucket,
    chain_id) -> bool` reads with `get_attribute(config).get_attr_strict`
    (the db-layer strict read `try_mark_refresh_token_used` uses at
    `oauth_session.py:814-816`, never the `Attributes` wrapper whose
    instance cache "treats a loaded dict as authoritative about absence",
    `attribute.py:359-360`) and raises `StoreFault` on a read fault.
    `CHAIN_REVOKED_MARKER_TTL = 300` in `actingweb/constants.py` with the
    other token constants, asserted positive. `set_attr`, not
    `create_attr_if_absent`: inside one request the marker-present branch's
    own cleanup never writes it again (point deletes, below), but the theft
    branch and a logout of a chain may both run and the later write must not
    be refused.
  - **SPA:** bucket `_CHAIN_REVOKED_BUCKET = "spa_revoked_chains"` beside
    the two token buckets (`oauth_session.py:39-40`), partition
    `OAUTH2_SYSTEM_ACTOR`. `revoke_token_chain` (`:1094-1114`) calls
    `mark_chain_revoked` **inside its existing `try`/`finally`** before
    `revoke_chain_confirmed`, so eviction stays unconditional; a `StoreFault`
    is `TokenStoreUnavailable` and **nothing is swept**. The theft branch
    (`handlers/oauth2_spa.py:910-914`) and `/oauth/revoke` go through the
    same method. `_handle_refresh_token` (`:959-979`): after both mints and
    before `session_generation.guard`, `chain_revoked(...)` for the consumed
    token's `chain_id`; present → the two minted rows are removed with two
    point `delete_confirmed` calls (`single_use.py:197-221`) and the answer
    is the 401 `invalid_grant` the generation mismatch gives; a read fault →
    the same two deletes, then `_store_unavailable()` (the contract
    `session_generation.guard` has, `session_generation.py:115-141`).
    `revoke_minted` (`:961-968`) becomes those two point deletes for the
    generation guard as well: today it calls `revoke_session`, which on a
    chain-tagged row runs a second full sweep (and would write the marker a
    second time); the minted tokens never left the server, were never
    validated and never cached, so a point delete is the right size, and it
    keeps "one `delete_by_chain` per logout" true on every path. That is
    safe on the generation-mismatch branch because every `bump` caller sweeps
    the actor's tokens itself right after (adoption at `oauth2.py:3042-3049`
    and `:3083-3086`, the finisher after this plan), so the old chain's other
    rows do not depend on the rotation's lazy sweep. A chain-less legacy
    token (no `chain_id`) skips the check.
  - **MCP:** bucket `mcp_revoked_chains` under the user's actor partition
    (MCP chains live there, `token_manager.py:779-781`). `_revoke_chain`
    (`:716-784`) calls `mark_chain_revoked` **before its first
    `_snapshot_bucket` read** (`:761`, the sweep's first read of the chain),
    inside its `try`; a `StoreFault` is `TokenStoreUnavailable` as its sweep
    fault already is. `refresh_access_token` (`:325`, mints at `:496-507`)
    calls `chain_revoked` after both mints beside `_generation_still_matches`
    (`:924`); present → the two minted rows are point-deleted and the method
    returns `None` (the endpoint's `invalid_grant`); a read fault → the two
    deletes, then the existing store-unavailable answer.
  - **Deletion finisher:** `finish_deletion` (`actingweb/deletion_finish.py:196`)
    sweeps SPA chains through `_revoke_all_actor_tokens` with no chain
    anchor, so it writes no marker, and nothing bumps the actor's session
    generation before it (adoption does, `oauth2.py:3042,3083`). A rotation
    whose consume preceded that sweep mints after it and the pair survives
    until the actor row goes. Fix: `session_generation.bump(actor_id, config)`
    (`session_generation.py:71`) directly before `_revoke_all_actor_tokens`;
    the rotation's existing generation guard then revokes what it minted.
    `bump` raises `DbError` when the new value cannot be confirmed
    (`session_generation.py:80-101`), which the finisher's existing fault
    path already handles (the lease is released and the run is retried);
    nothing in the attribute write path suppresses writes to an actor under
    deletion, so the bump lands while the tombstone and the lease are held.
  - **Why this closes the window on both backends.** The marker write is
    acknowledged before the sweep's first read; the rotation's two
    `set_attr` writes are acknowledged before its strict marker read. On
    DynamoDB a strongly consistent read reflects every write whose success
    response arrived before the read started, so a rotation that reads the
    marker absent wrote both rows before the marker put succeeded, hence
    before the sweep's consistent Query (`db/dynamodb/attribute.py:562-566`),
    which deletes them; a rotation that reads it present deletes its own
    rows. On PostgreSQL `set_attr` is one statement plus an explicit commit
    (`db/postgresql/attribute.py:426-454`), `get_attr_strict` one `SELECT`
    (`:320-333`), the sweep one `DELETE` (`:808-818`), the pool sets nothing
    but `search_path` (`db/postgresql/connection.py:100-107`), and
    read-committed per-statement snapshots give the same chain. The claim is
    exactly true for a rotation whose marker read happens while the marker
    is readable: 300 s plus the 3600 s `TTL_CLOCK_SKEW_BUFFER` both strict
    reads honour (`db/dynamodb/attribute.py:206-207`,
    `db/postgresql/attribute.py:337-338`), and a rotation is one request. The
    theft branch is correct too: both holders lose, the documented theft
    semantics (`oauth_session.py:1039-1042`).
  - **Why fail closed on a marker write fault.** Today's fault answer is
    also a 503 with the tokens kept (`oauth2_spa.py:903-907`), so this is not
    weaker. The alternative, "sweep anyway, then 503", cannot be completed by
    the retry: `revoke_session` reads the presented row first
    (`oauth_session.py:1177-1202`) and returns `None` once the sweep removed
    it, so no marker is ever written for that chain. The marker write and
    the sweep hit the same partition, so a fault on one rarely spares the
    other.
  - **Lifetime and reaping.** The marker only has to outlive an in-flight
    rotation whose consume preceded the sweep (a request); after the sweep
    every refresh row of the chain is gone, so no later rotation of that
    chain reaches the check, and a present marker on a dead chain is
    harmless. A sequential second logout of the same chain never reaches
    `revoke_token_chain` (the presented row is gone), so nothing "refreshes"
    the marker. **DynamoDB** reaps by native TTL, which is an operator step
    the library does not perform (`docs/reference/database-backends.rst:259-261`);
    without it the bucket grows one row per revocation and nothing watches
    it (`CHAIN_SCAN_WARN_ROWS` counts the token buckets only), so the TTL
    inventory at `:268-270` lists both marker buckets and D4's docs name the
    prerequisite. **PostgreSQL**: `purge_expired_tokens`
    (`oauth_session.py:1299-1301`) and the MCP purge
    (`token_manager.py:1905-1915`) add their marker bucket; a marker is
    purge-eligible after 65 min (300 + 3600), the purge runs at most once an
    hour per process and only from a token request, so after the last token
    request expired markers stay until the next one; at N revocations an hour
    the bucket holds about 1.1 N to 2.1 N rows, served by the partial
    `idx_attributes_ttl`. And `delete_expired` on PostgreSQL swallows a fault
    and returns 0 (`db/postgresql/attribute.py:771-773`), so the only reaper
    there reports a fault as "nothing expired"; it raises `DbError` instead.
    Its callers (`oauth_session.py:1297-1304`, `token_manager.py:1878,1905`)
    are checked and each folds the exception with a WARNING; `1878` is
    wrapped if it does not.
  - **Cost.** One `set_attr` per chain revocation (logout, `/oauth/revoke`,
    theft, MCP revoke) and one more strict point read per refresh: DynamoDB
    3 → 4 reads, PostgreSQL 2 → 3 (its CAS is a single `UPDATE`), writes
    unchanged at 3. A refresh fires once per access-token lifetime
    (`SPA_ACCESS_TOKEN_TTL = 3600`), not a hot path. The marker row shares
    the system-actor partition the token rows already use. One combined read
    is not possible: the generation row lives under the actor's partition,
    the marker under the system actor's, and the protocol has no batch read.
    The two tests that pin one `delete_by_chain` per logout
    (`tests/test_oauth_session.py:950-967`,
    `tests/test_oauth2_spa_logout_revokes_chain.py:341-357`) stay true.
- **D5 An MCP-token logout and an SPA session are separate** (owner,
  2026-11-04: "a SPA login is from a user; an MCP login is from an AI agent
  on behalf of a user"):
  - `_handle_mcp_token_logout` (`handlers/oauth2_endpoints.py:1211-1238`)
    returns `clear_cookies: []`; the route builds its cookie list from that
    key (`:1022-1025`) and `cleared_cookies` in the body becomes `[]`
    (`:1046-1048`), a response-shape change the changelog names.
    `_handle_provider_token_logout` (`:1133-1134`) keeps routing an `aw_`
    token there and, when `refresh_tokens` is non-empty, logs at DEBUG that
    SPA refresh tokens were presented and ignored (that method is the only
    site that still holds them). The response shape stays the same for every
    logout, "Successfully logged out" included (owner, 2026-11-04: keep the
    shape, document it); `redirect_url` stays for the same reason. No library
    flow stores an MCP token in the `oauth_token` cookie
    (`handlers/oauth2_callback.py:822-837`, `handlers/oauth_email.py:1097-1105`),
    so clearing nothing leaves no browser session the MCP token authenticated.
  - Docs that become false and are rewritten: `docs/guides/spa-authentication.rst:980-1010`
    (logout), `:1608` ("Revoke the session's refresh-token chain and clear
    its cookies"), `:1622-1636` (both-tokens case and the `cleared_cookies`
    example; a second example for an MCP token with `[]`),
    `docs/reference/security.rst:99`. Sentence: *"An MCP access token (an AI
    agent's login, not the user's) ends only that MCP chain: an SPA refresh
    token sent beside it is ignored and logged, `cleared_cookies` is `[]` and
    no `Set-Cookie` is sent; the browser session ends when the user logs out
    of the SPA."*
- **D6 Subscription `callback` is a bool, enforced on both backends**
  (owner, 2026-11-04): `isinstance` guards **before any I/O** in `create`
  (`if not isinstance(callback, bool)`) and `modify` (`if callback is not None
  and not isinstance(callback, bool)`, its default is `None`), placed before
  the handle check and before `create`'s pre-read, on both backends
  (`actingweb/db/dynamodb/subscription.py:101-121,180-217`,
  `actingweb/db/postgresql/subscription.py:97-187,198-255`), raising
  `TypeError(f"subscription callback must be a bool{' or None' if modifying
  else ''}, not {type(callback).__name__}; it is a boolean column on both
  backends: pass callback=True for a subscription that delivers callbacks")`.
  The value is never echoed (on the path the todo describes it is a URL). A
  mistyped call is a programming error, not a store fault, so it must not
  read as a 503; the integrations answer their fixed 500 body
  (`flask_integration.py:1012`, `fastapi_integration.py:1843`) and the text
  reaches the log only. PynamoDB 6.1.0 coerces by truthiness
  (`BooleanAttribute.serialize`), so a URL was stored as `True`; PostgreSQL
  surfaced it as a `DbError` wrapping the cast error. Every library caller
  passes a bool literal or omits it (`actor.py:2428`,
  `interface/subscription_manager.py:718`, `authenticated_views.py:683-689`),
  and the POST handler never reads `callback` from the request
  (`handlers/subscription.py:225-263,459-487`), so no request can trigger it.
  The DynamoDB signatures gain the type hints PostgreSQL's have
  (`callback: bool = False`, `callback: bool | None = None`); the protocol
  docstrings (`protocols.py:1004-1014,1046-1065`) say the contract. The
  todo's title is stale: the performance tests already pass `callback=True`
  (`tests/performance/test_backend_performance.py:375,403`).
- **D7 `resources/read` is resolved and formatted once, for both handlers.**
  The async path (`handlers/async_mcp.py:460-523`) diverges from the sync
  path (`handlers/mcp.py:1923-1986`) in four ways:
  1. a dict body is `str(result.get("content", result))` instead of
     `json.dumps(result, indent=2)` (`async_mcp.py:503-505`, `mcp.py:1964`);
  2. `mimeType` is read from `mimeType`, a key the decorator never writes,
     default `text/plain` (`async_mcp.py:516-518`), instead of `mime_type`,
     default `application/json` (`mcp.py:1977-1979`,
     `actingweb/mcp/decorators.py:130,154`), so FastAPI always answered
     `text/plain`;
  3. the `uri_pattern` regex fallback (`mcp.py:1936-1943`) is missing, so a
     resource declared only by pattern resolves on Flask and not on FastAPI;
  4. the hook arguments differ: sync passes the request `params`
     (`mcp.py:1951`) and never the extracted template variables; async passes
     only the variables (`async_mcp.py:477-485`), which
     `tests/integration/test_mcp_resource_regression.py:320-344` pins on
     FastAPI.

  Fix: one resolver `resolve_resource(uri, resources) -> (hook, metadata,
  variables) | None` in `actingweb/mcp/uri.py` (its docstring already says
  "Shared by the sync and async MCP handlers", `:3-4`) with the template
  match and the `uri_pattern` fallback; both handlers call the hook with
  `{**params, **variables}` (adds the variables on Flask, restores `uri` on
  FastAPI, keeps every existing test); one formatter
  `format_resource_read_result(result, uri, metadata)` in `handlers/mcp.py`
  beside `format_call_tool_result` (`:637`; `async_mcp.py:13-17` already
  imports from there, same direction, no cycle). The sync behaviour is the
  formatting contract (it reads the decorator's real key). **Behavior change
  for FastAPI deployments:** a dict resource body becomes indented JSON,
  `mimeType` becomes the declared type (`application/json` when undeclared),
  a hook sees `uri` in its arguments again, and `json.dumps` raises
  `TypeError` on a non-serialisable value (a `datetime`) where `str()` did
  not: such a hook now answers the generic error instead of a Python repr.
  Two error-path differences are recorded, not changed: sync re-raises
  `DbError` (`mcp.py:1985-1986`) where async answers `_db_fault_response`
  (`async_mcp.py:524-525`), and sync wraps the template match in a
  try/except (`:1928-1933`); the shared resolver takes the sync shape for
  the match and leaves the fault answer to each handler's existing wrapper.
  No doc states the contract; `docs/guides/mcp-applications.rst` gains one
  paragraph after `:497`: *"What the hook returns decides the
  `resources/read` body: a `dict` is sent as indented JSON with the
  decorator's `mime_type` (`application/json` by default); a `str` is sent
  as it is; a `dict` with a `contents` key is passed through unchanged. Flask
  and FastAPI answer identically."*
  **[Updated 2026-11-04, Iteration 13]** The doc now says a `str` carries
  the decorator's `mime_type`, and that the integrations answer a
  successful read identically while their error messages differ and Flask
  needs a synchronous hook.
- **D8 Exact-match client deletion.** **[Updated 2026-11-04]** Arm 3
  accepts every source trust creation writes (`oauth2`, `oauth2_client`,
  `oauth2_interactive`), gated on OAuth2 origin; see Iteration 2.
  **[Updated 2026-11-04, Iteration 6]** Deletion removes every row the three
  arms match (`client_trusts_for_deletion`), not the first; arm 3 needs
  exactly three segments; `find_client_trust` lost `legacy_segment_match`
  and is the resolver's single-row answer only.
  **[Updated 2026-11-04, Iteration 11]** Every row is tried before the
  first `DbError` is raised, and a row an earlier row's `Trust.delete`
  cascade already removed counts as deleted. `_delete_client_trust_relationship`
  (`actingweb/oauth2_server/client_registry.py:591-668`) matches with
  `pattern in peer_id or peer_id.endswith(client_id)` (`:631`) and deletes
  the first hit, so deleting client A can take an unrelated row of the same
  actor whose peer id happens to contain A's id. The authentication resolver
  (`handlers/mcp.py:2592-2681`) is exact: arm 1 `oauth_client_id ==
  client_id`, arm 2 the reconstructed `{source}:{normalized}:{normalized}`
  peer id for legacy rows without the field, gated on `established_via`.
  Fix: `find_client_trust(trusts, client_id, *, legacy_segment_match=False)`
  in a new `actingweb/oauth2_server/trust_lookup.py` (imports nothing from
  the package or the handlers, so no cycle; `client_registry.py:14-19`
  imports `attribute`, `config`, `client_text`, `constants`, `db.exceptions`,
  `secret_compare`). Arms 1 and 2 as the resolver has them; a third,
  deletion-only arm (`legacy_segment_match=True`) mirrors
  `Trust._extract_client_id_from_peerid` (`actingweb/trust.py:205-223`): the
  peer id starts with `oauth2_client:`, has three or more segments, its
  **last segment equals** `client_id` exactly, and the row has no
  `oauth_client_id`. That keeps deleting the real-email legacy rows
  (`oauth2_client:<email>:<client_id>`) today's `endswith` catches, without
  a substring match. The resolver calls the helper with the default and
  keeps its behaviour and its warning; the deletion path passes `True` and
  deletes only the row returned. The detection-only invariant check
  (`mcp.py:2702-2707`) stays. Both deletion callers are bound to the
  caller's own actor (`interface/oauth_client_manager.py:167-181`,
  `trust.py:139-145`), and `oauth_client_id` is written only by library code,
  so the helper cannot be steered by a client-chosen value. Correction to the
  todo: the cascade in `Trust.delete()` is triggered by the peer-id shape
  (`trust.py:136-137,205-223`), not by the `oauth_client_id` column.
- **D9 Todo bookkeeping, in Phase 3:** delete
  `unique-creator-direct-config-auto-create.md`,
  `spa-logout-refresh-rotation-race.md`,
  `logout-mcp-token-with-spa-refresh-cookie.md` and
  `benchmark-subscription-tests-pass-url-to-boolean-callback.md` with their
  `INDEX.md` rows; remove sections 4 and 7 from
  `mcp-cache-lifecycle-and-revocation.md` and item 4 from
  `dynamodb-known-next.md` (its `INDEX.md` row says "seven items"; it becomes
  six and names them). `drop-python-3-11-after-eol.md` and its row land in
  Phase 1 as part of D1.
- **D10 Changelog** (owner, 2026-11-04): every entry under `Unreleased`,
  project style, a bold symptom first. D2 edits the existing unshipped 3.16
  entries in place (`CHANGELOG.rst:564-566` "starts once (which creates the
  tables and stops)" gains "under `integrate_*`"; `:580-581` gains the
  consequence sentence; `:599-603` gains "and a process that builds `Config()`
  directly no longer creates that table, nor claims without the index on
  PostgreSQL: its creates raise `DbError` until `enable --apply` has run").
  D4 goes under **SECURITY** (it fixes a 3.15.1-shipped logout guarantee;
  precedent `:337`). D5, D6, D7 and D8 go under **FIXED**, each with a
  **Behavior change:** sentence (D5: `cleared_cookies` is `[]` on an MCP
  logout; D6: a non-bool raises; D7: the FastAPI shape; D8: none, the legacy
  rows keep being deleted). The 3.16 `ADDED` entry for
  `actingweb-mark-actors-vouched` (`:1268-1280`) and the migration guide's
  command section (`docs/migration/v3.16.rst:201-252`) are edited in place
  for `--rate-limit`, the consistent scan and the memory figure, since
  neither has shipped; `mark_actors_vouched.py:44-45` says the same.

## Decisions Deferred

None.

## What We're NOT Doing

- **The `subs_list` cache guard and the MCP actor-cache lifetime**
  (`thoughts/todo/subs-list-cache-asymmetry.md`): the guard is unsafe until
  the cache decision is made; its own plan.
- **The `ListAttribute` v2 port** (`attribute-list-shift-design.md`): needs a
  migration shape for existing replicas and a sequencing call; its own plan,
  and it reverses a recorded 2026-11-01 scope decision, which that plan must
  say.
- **An actor-scoped conditional write and the one-transaction vouched
  rename** (`vouched-rename-one-transaction.md`, the consumer's register item
  11): a new cross-table primitive on both backends; its own plan.
- **Registration expiry and CIMD** (`dcr-registrations-and-client-trust-rows-never-expire.md`,
  the CIMD row of `mcp-oauth-connector-conformance-followups.md`): deferred
  by the owner on 2026-11-01 to a plan of its own; not reopened here.
- **Landing D1 as its own PR first, or pulling the 3.16.0 tag forward** (the
  outside voice's release-split question): the owner asked for one roll-up
  PR on 2026-11-04 and holds the tag; D1's **Check** sentence carries the
  consumer's self-remedy meanwhile.
- **Revoking SPA refresh tokens on the MCP logout path**, or an `ignored`
  field in its response: rejected by D5. The two logins are separate and the
  response shape stays uniform.
- **Sweeping twice, or re-reading the consumed row** for the logout race:
  neither closes the window on DynamoDB (the sweep deletes its anchor last;
  a second read only moves the window).
- **Chain-less legacy SPA refresh tokens** (minted before 3.15.1) rotate
  into chain-less tokens and skip the marker check; that window closes by
  itself within `SPA_REFRESH_TOKEN_TTL` (two weeks) of the 3.15.1 upgrade.
  `revoke_all_tokens` (`oauth_session.py:922`) has no library caller.
- **Making a missing DynamoDB table a permanent (500) fault** in
  `_errors.py:45-51`: a contract decision for every path, not only creators;
  the ERROR line is the remedy here.
- **A `chain_id` GSI** (`dynamodb-chain-id-gsi.md`): the marker row is keyed
  by chain but does not index the token buckets; the trigger (the scan
  WARNING) has not fired.
- **A paginated public `fetch()` or a cursor API**: `fetch()` keeps its
  contract for the protocol and its documented callers; `iter_rows` is the
  streaming form. `actor.Actors` (`actingweb/actor.py:4082-4100`) has no
  caller and is left alone.
- **A checkpoint file or a `--consistent` flag for `mark-actors-vouched`**:
  `--start-after` with sorted ids is its documented resume contract, and the
  command vouches from what it reads, so consistency is not optional there.
- **A read throttle on the two property-list sweeps**: they have `--rps`; a
  second throttle in different units beside it would confuse, and their
  actor scan is eventually consistent and projected.
- **`ensure_table`'s `exists()` outside its `try`**
  (`actingweb/db/dynamodb/_ensure.py:95`): a DescribeTable fault propagates
  raw from every constructor today, not only for `Creator`; a separate
  contract question.
- **Stopping the prewarm from creating `creators`**: the documented
  first-start sequence depends on it, and the readiness probe refuses to
  serve until `enable` has run.
- **Coercing `callback`** on either backend: rejected by D6.
- **The async `tools/call` and `prompts/get` paths**: identical to sync by
  construction (shared `format_call_tool_result`) and by inspection.
- **Unifying the two handlers' `resources/read` fault answers** (`DbError`
  re-raised vs `_db_fault_response`): each handler's existing wrapper owns
  that; recorded in D7.
- **Switching `_check_trust_client_invariant` to the exact helper**: it is
  detection-only and logs; not a deletion.
- **MCP batch receive, dual-era, `/sessions`, the SDK-retry ambiguity, the
  unconditional meta-row create, subscriber fault hardening, the output
  schema bridge**: each needs a decision its todo says is missing.

## What Already Exists

- `actingweb/db/dynamodb/actor.py:546-569` `_run_transaction`: maps every
  transaction failure, including a missing table, to `DbError`; D2 adds the
  ERROR line there and changes nothing else.
- `actingweb/maintenance/unique_creators.py:945-953` the index validity
  query and `:197-207,1225-1233` the projected, rate-limited, consistent
  `Actor.scan` with the `--rate-limit` wording: D2's PostgreSQL probe and D3
  copy them.
- `actingweb/db/dynamodb/property_lookup.py:85-92` `is_resource_not_found`:
  D2's DynamoDB detection.
- `actingweb/db/dynamodb/_ensure.py:110-118` `reset_ensure_cache`: the
  precedent for `reset_index_probe`.
- `actingweb/maintenance/property_lookup.py:976-993` `_pg_batches_conn`: the
  keyset page shape for PostgreSQL (D3 uses one connection per page instead
  of the caller-held one).
- `actingweb/session_generation.py:71-155` `bump`, `guard`, `_revoke`: the
  post-mint check that revokes what it minted, and the bump the finisher
  gains (D4).
- `actingweb/single_use.py:197-284` `delete_confirmed`,
  `revoke_chain_confirmed`: the point delete and the shared sweep the marker
  helpers sit beside (D4).
- `actingweb/deletion.py:115-183` `write_actor_tombstone`: a marker row in
  a dedicated bucket under a system store with a TTL; the precedent for D4's
  marker.
- `actingweb/oauth_session.py:1270-1304`, `token_manager.py:1891-1918`
  `purge_expired_tokens`: the PostgreSQL reapers D4's buckets join.
- `actingweb/handlers/mcp.py:637` `format_call_tool_result`: the shared
  formatter D7 mirrors; `actingweb/mcp/uri.py:10` `match_uri_template`: the
  shared matcher D7's resolver wraps.
- `actingweb/handlers/mcp.py:2592-2681` `_lookup_mcp_trust_relationship`:
  arms 1 and 2 become D8's helper; `actingweb/trust.py:205-223`
  `_extract_client_id_from_peerid`: arm 3's shape.
- `tests/test_oauth2_spa_logout_revokes_chain.py:40-139` `Env`: both token
  stores on one double, `logout(cookies=...)`, `refresh()`;
  `test_logout_after_a_rotation_ends_the_rotated_chain` (`:237-247`) is the
  sequential case, already present.
- `tests/mcp_token_double.py:62-108`: `write_faults`, `faulty_buckets`
  (strict reads only, which is the discriminator D4's read-fault test needs),
  `purges`, `enforce_ttl` + `advance()`.
- `tests/test_oauth2_logout_mcp_tokens.py:20-31` `_rotated()`,
  `tests/mcp_oauth_server_helpers.py:32-78` `make_server`/`make_handler`:
  the MCP rotation seams (D4, D5).
- `tests/test_mcp_fail_closed_authorization.py:30-139` `FakeTrust`,
  `FakeTrustManager`, `TestExactResolverMatching`: the resolver's own tests
  D8's helper tests sit beside.
- `tests/test_mcp_resource_read_permissions.py:112-191`
  `TestSyncAsyncResourceReadParity`: returns booleans today; D7 makes it
  compare whole `contents`. `tests/test_mcp_uri_template.py:41-91`
  `TestLegacyUriPatternDispatch`: the sync `uri_pattern` case D7 mirrors
  for async.
- `tests/test_db_fault_contract.py:154-158,245-263,326-374`: the PostgreSQL
  `get_connection` fault seam, the `_FakeConnection` and `_faults_mid_page`
  shapes for D3's fault tests.
- `tests/test_cold_start_budget.py:38-49` `clean_ensure_state`: the
  reset-around pattern D2's unit tests need.
- `tests/integration/_isolated_store.py:110-177` the table-name swap with
  its mandatory restore, `wipe_store`, `enable_enforcement`;
  `tests/_lookup_probe.py:69-91` the probe stub and its opt-out fixture: the
  seams D2's fixtures sit beside.

## Phase 1: Dependencies and the fail-closed creators uniqueness

### Changes

- `pyproject.toml`, `poetry.lock`, `docs/requirements.txt`: as on the
  working tree (D1).
- `CHANGELOG.rst` Unreleased: the dependency SECURITY entry gains
  `python-discovery` and the self-remedy **Check** sentence (D1); the three
  3.16 uniqueness entries are edited in place (D10).
- `thoughts/todo/drop-python-3-11-after-eol.md` and its `INDEX.md` row: as on
  the working tree.
- `actingweb/db/dynamodb/actor.py`: remove the `Creator` ensure at
  `:575-576`; the constructor docstring says who creates the table; the
  ERROR line in `_run_transaction` on `is_resource_not_found` (D2).
- `actingweb/db/postgresql/actor.py`: `_creator_index_present()`,
  `reset_index_probe()`, the guard and ERROR in `create`, the rename path
  and `replace_creator_holder` (D2).
- `actingweb/maintenance/unique_creators.py:336-337`: `report` logs the
  missing table (D2).
- `tests/conftest.py`: the session-scoped `_creators_table` fixture
  (DynamoDB). `tests/_lookup_probe.py`: `_stub_pg_creator_index_probe` and
  `real_pg_index_probe`, imported by `tests/conftest.py` and
  `tests/integration/conftest.py:23-26` like the existing stubs.
- `actingweb/maintenance/unique_creators.py:945-953`: `missing_enforcement`
  uses the db-layer probe (D2).
- `tests/integration/_isolated_store.py`: `reset_index_probe()` in
  `wipe_store` and `enable_enforcement`.
- `tests/integration/test_unique_creator_states.py:235-243` and any other
  `fresh_store` test the run exposes, on either backend: `_raw_row`, an
  explicit `Creator.create_table` / index build, or an expected `DbError`,
  per the test's intent.
- `thoughts/todo/unique-creator-direct-config-auto-create.md`: deleted with
  its `INDEX.md` row (its answer is complete here).
- `docs/migration/v3.16.rst:258-263,855-859`, `docs/quickstart/configuration.rst:43`:
  the fail-closed consequence on both backends (D2).

### New Tests, both unit and integration tests

- Unit, DynamoDB, with `clean_ensure_state` and `Creator.Meta.table_name`
  swapped to a unique absent name and restored in `finally`:
  `DbActor(unique_creator=True)` creates no table (`Creator.exists()` stays
  False) and `create(...)` for a fresh creator raises **`DbError`
  specifically** (not `CreatorTaken`), with the ERROR line naming the table
  and the command in `caplog`; with the flag off the constructor still
  creates only `Actor`.
- Unit, PostgreSQL, with `real_pg_index_probe` and the validity query
  patched to "absent": `create(...)` with the flag on raises `DbError` after
  the ERROR line and writes no row; with the index reported present it
  inserts; an exempt creator is never probed; a probe fault is not cached
  (the next call probes again).
- Unit, DynamoDB: `deletions.make_config()` default builds an enforced
  config whose `get_actor(config)` creates no creators table.
- Integration (`unique_creator` group), both backends: on `fresh_store`
  after `wipe_store`, `Actor(config).create(...)` with the flag on raises
  `DbError`, and after `enable_enforcement` it succeeds and records the
  creator. On DynamoDB, `report` against the missing table logs the
  missing-table line.
- The dependency change is covered by the existing `jwt_bearer` and OAuth2
  suites; the fast tier is the test.

### Failure Scenarios

- **A worker on a backfilled store** (table and marker present; index
  present): unchanged, claims succeed. Covered by the enforced-store suites.
- **A worker on a store where `enable` never ran**: every actor create,
  the OAuth2 system actor bootstrap included, raises `DbError`; the
  integrations answer 503; the ERROR names the table or index and the
  command. The operator runs `enable --apply`. Covered by the new tests.
- **A PostgreSQL process that cached "index present" and then the index is
  dropped** (`disable`): the next create runs the plain INSERT until the
  process restarts. `disable` is an operator action that also turns the flag
  off in the deployment; the fixtures reset the probe. Recorded, accepted.
- **`actingweb-deletions finish` on such a store**: the actor is deleted,
  the record release logs at ERROR and does not raise. Unchanged path.
- **A describe fault on `Actor`'s table** still propagates raw from the
  constructor (`_ensure.py:95`): unchanged, named in What We're NOT Doing.
- **A unit run on a fresh DynamoDB Local** without the fixture would fail
  with `ResourceNotFoundException`; the fixture runs before any test.
  Covered by running the unit command on a fresh container.

### Verification

- [x] Fast tier
- [x] Unit command on a fresh DynamoDB Local container (`down -v`, then up)
- [x] `grep -rnE "Creator\.create_table|ensure_table\(Creator|required_models" actingweb tests`
  names only the prewarm, `enable`, the fixture and tests that create it on
  purpose
- [x] Full tier on both backends before the commit

### Implementation Status: Complete

### Implementation notes (Phase 1)

- **The remedy message is shared** through
  `creator_rules.missing_enforcement_message(what)`, so both backends log
  the same sentence with the missing piece named.
- **The DynamoDB ERROR does not call `DescribeTable`.** The first draft
  confirmed with `Creator.exists()` that the missing table was `creators`.
  Review: a runtime role without `DescribeTable` (which the 3.16 changelog
  allows) would swallow the line. Now `is_resource_not_found(e)` alone
  triggers it; every transaction in `_run_transaction` writes `Actor`
  (ensured by the constructor) and `Creator`. A unit test patches
  `Creator.exists` to raise and still sees the line.
- **PostgreSQL raises `DbError(op)`**, so the text is `database error during
  actor create` (`actor modify`, `actor replace holder`) exactly as the docs
  quote it; the plan's `DbError("creator uniqueness index missing")` would
  have made the documented message false. An INVALID index is refused too
  (the probe caches only `valid`), and the ERROR says "missing or INVALID".
- **The probe cache is keyed by schema name**, not one boolean: the
  integration tier moves `PG_DB_PREFIX` per module.
- **The index query lives in the db layer** as
  `postgresql.actor.creator_index_state()`;
  `unique_creators.postgresql_index_state()` now delegates to it (kept as
  the seam the command tests patch). `enable` and `disable` call
  `reset_index_probe()` themselves after a build or drop, not only the
  fixtures.
- **The creator rename on PostgreSQL** (`DbActor.modify` with a new
  non-exempt creator) is guarded like create; a passphrase-only modify is
  not probed.
- **`report` logs the missing table at WARNING** (from `_dynamodb_records`,
  so `enable`'s collect logs it too).
- **The integration tier exposed only the test the plan named**
  (`test_disable_finishes_a_partial_run`, now seeded with `_raw_row`). The
  other `fresh_store` tests seed with the flag off or go through `enable`
  first. On PostgreSQL the session stub hides the probe; the new
  `TestFailClosedBeforeEnable` requests the real one.
- **`_creators_table` runs on every backend**, not on DynamoDB only: the
  first PostgreSQL Full run failed six unit tests that pin
  `database="dynamodb"` whatever the run's backend
  (`test_actor_created_fires_once.py`, `test_config_bound_singletons.py`,
  `test_db_fault_callers.py::TestB4UniqueCreatorCreate`). On a PostgreSQL
  run it is best-effort (no DynamoDB Local fails only those tests). The
  PostgreSQL stub keeps its backend guard.
- **Verification:** fast tier on a fresh DynamoDB Local (`down -v`, then up)
  green; the grep names only the prewarm, `enable`, the fixture and the
  tests that build the table on purpose; Full tier green on both backends
  (DynamoDB 5564 passed, PostgreSQL 5369 passed), docs build and
  `verify_groups` green.

---

## Phase 2: Logout

### Changes

- `actingweb/constants.py`: `CHAIN_REVOKED_MARKER_TTL = 300` and its
  invariant.
- `actingweb/single_use.py`: `mark_chain_revoked`, `chain_revoked` (D4).
- `actingweb/oauth_session.py`: `_CHAIN_REVOKED_BUCKET`; the marker write in
  `revoke_token_chain` inside its `try`; `purge_expired_tokens` purges the
  bucket (D4).
- `actingweb/handlers/oauth2_spa.py:959-979`: the post-mint marker check
  before `session_generation.guard`; `revoke_minted` becomes two
  `delete_confirmed` calls (D4).
- `actingweb/oauth2_server/token_manager.py`: the MCP marker bucket; the
  write in `_revoke_chain`; the check in `refresh_access_token` beside
  `_generation_still_matches`; the purge list (D4).
- `actingweb/deletion_finish.py:196`: `session_generation.bump` before
  `_revoke_all_actor_tokens` (D4).
- `actingweb/db/postgresql/attribute.py:771-773`: `delete_expired` raises
  `DbError` on a fault; its three callers checked for a fold (D4).
- `actingweb/handlers/oauth2_endpoints.py:1133-1134,1211-1238`: the DEBUG
  line for ignored SPA refresh tokens; `clear_cookies: []` on the MCP path;
  docstrings (D5).
- `docs/guides/spa-authentication.rst` (four sites), `docs/reference/security.rst:99`,
  `docs/reference/database-backends.rst:259-270` (TTL prerequisite and
  inventory); `CHANGELOG.rst`: SECURITY entry for D4, FIXED entry for D5.

### New Tests, both unit and integration tests

- `tests/test_oauth2_spa_logout_revokes_chain.py`, **the interleaving
  test**: `mock.patch.object(OAuth2SPAHandler, "_generate_actingweb_token",
  wrapper)` where the wrapper, on its first call only, runs
  `env.logout(headers=bearer(old_access))` and then the real method. The
  consume has landed, the logout sweeps the consumed refresh row and the old
  access row, then both mints land. Before the fix: 200 with two live
  chain-tagged rows. After: 401 `invalid_grant`, no row in either token
  bucket with that `chain_id`, the marker row present. The one-sweep pin is
  **not** asserted inside this test.
- Same file: the marker is written before the first `delete_by_chain` (order
  recorded through a wrapped `set_attr` and the wrapped sweep); a marker
  write fault (`write_faults` on the new bucket) answers 503 and deletes no
  row; a marker read fault (`faulty_buckets` on the new bucket, which faults
  strict reads only, so a folding implementation of `chain_revoked` fails
  this test) during a refresh removes both minted rows and answers 503; a
  chain-less legacy refresh token skips the check and still rotates; the
  generation-mismatch path now leaves no chain row and performs no sweep
  (`revoke_minted` is two point deletes); `env.store.purges` shows
  `_CHAIN_REVOKED_BUCKET` in the list `purge_expired_tokens` passes.
- `tests/test_oauth2_spa_refresh_rotation.py`: the theft branch writes the
  marker; `/oauth/revoke` writes it.
- `tests/test_mcp_refresh_rotation.py`: the MCP mirror of the interleaving
  test, seam `_create_access_token_from_refresh` running `revoke_token(old
  access)` once before the real method: before the fix the rotation returns
  a live pair; after it returns `None` and the actor's two MCP buckets hold
  no row of the chain. `_revoke_chain` writes the marker before its sweep;
  the MCP purge list includes the bucket.
- `tests/test_deletion_finish*.py`: `finish_deletion` bumps the actor's
  session generation before `_revoke_all_actor_tokens` (order spy), and a
  refresh stamped with the old generation after the finisher ran answers 401
  with nothing minted left (the existing guard tests cover the mechanism).
- `tests/test_oauth2_logout_mcp_tokens.py`: an MCP Bearer token with an SPA
  `refresh_token` cookie and a body `refresh_token`: 200, the MCP chain
  revoked, both SPA rows live, `cleared_cookies == []`, no `Set-Cookie`
  expiry, the DEBUG line present; `make_handler`
  (`tests/mcp_oauth_server_helpers.py:72`) gains a `cookies` kwarg.
- `tests/test_db_fault_contract.py`: PostgreSQL `delete_expired` raises
  `DbError` under `_pg_down`; `purge_expired_tokens` folds it to 0 with a
  WARNING.
- `tests/integration/test_spa_chain_revocation_backend.py`
  (`spa_chain_revocation_backend` group): after `revoke_token_chain` the
  marker row is readable with a TTL on both backends; on PostgreSQL
  `get_attribute(config).delete_expired(now_epoch=now + CHAIN_REVOKED_MARKER_TTL
  + TTL_CLOCK_SKEW_BUFFER + 1, buckets=[_CHAIN_REVOKED_BUCKET])` removes it
  and the same call with the real `now` does not (`purge_expired_tokens`
  takes no clock, so the reaper itself is tested through the double).

### Failure Scenarios

- **Marker write fails on logout or MCP revoke**: 503 with `Retry-After`,
  no row deleted, cookies kept; the client retries. Covered above.
- **Marker read fails during a refresh**: minted rows point-deleted, 503, the
  client keeps the consumed token as its retry handle inside the grace
  (existing contract). Covered above.
- **A point delete of a minted row faults** (marker-present or
  generation-mismatch branch): the row is an undelivered orphan that its TTL
  reaps; the client got 401 and holds nothing. Logged by `delete_confirmed`'s
  caller; accepted.
- **DynamoDB TTL not enabled on the attributes table**: both marker buckets
  grow one row per revocation and nothing warns. Documented prerequisite,
  same as every token row today.
- **PostgreSQL purge faults**: `delete_expired` raises, the caller logs a
  WARNING and retries next interval; markers wait, and strict reads hide
  expired ones meanwhile. Covered by the fault test.
- **The finisher's bump faults**: `DbError` into the finisher's existing
  fault path; the deletion is retried under a new lease. Covered by the
  existing finisher fault tests plus the order spy.
- **An MCP client sends a logout with no cookies**: unchanged.

### Verification

- [x] Fast tier
- [x] `tests/integration/test_spa_chain_revocation_backend.py` and
  `tests/integration/test_mcp_refresh_rotation_backend.py` on both backends
- [x] Full tier on both backends before the commit

### Implementation Status: Complete

### Implementation notes (Phase 2)

- **The MCP race seam revokes through the consumed refresh token**, not the
  old access token. On the MCP ladder the old access row is removed at
  consume time, before the mint, so `revoke_token(old access)` cannot reach
  the chain; the consumed refresh row still names it. Both race tests fail
  with `chain_revoked` stubbed to `False` (checked) and pass with it.
- **The theft-branch and `/oauth/revoke` marker tests live in
  `tests/test_oauth2_spa_logout_revokes_chain.py`**, not
  `test_oauth2_spa_refresh_rotation.py`: its `Env` already has `revoke()`
  and `refresh()`.
- **`_minted_removals` and `_remove_minted`** were extracted in
  `token_manager.py` so the marker branch and the generation guard share
  the same point removals (rows and their index entries). On the SPA side
  `revoke_minted` is two `delete_confirmed` calls; a failure logs at ERROR.
- **`maintenance/deletions.py` is a fourth `delete_expired` caller** the
  plan did not list; it already folds. `token_manager.py:1878` folds too, so
  nothing was wrapped.
- **The finisher's `bump`** sits after `_lease_keeper` and before the sweep,
  inside the existing `try`, so a `DbError` releases the lease and nothing
  is swept (test added beside the order spy).
- **Minor-release items** (the addendum's rule; 3.16.0 is already a minor):
  the logout response field `cleared_cookies` changes value on an MCP
  logout, and `delete_expired` on PostgreSQL now raises.
- Two existing tests changed for the new bucket: the MCP purge list count
  (7 to 8) and a store double in `test_mcp_revocation_evicts_caches.py`
  that lacked `set_attr`.
- The docs grep for other MCP-logout cookie claims found only
  `docs/migration/v3.15.rst:100`, which is historical and still true.
- **Verification:** fast tier green; the two backend integration files
  green on both backends; Full tier green (DynamoDB 5583 passed, PostgreSQL
  5388 passed), docs build and `verify_groups` green.

---

## Phase 3: Operator enumeration, hygiene, todo cleanup

### Changes

- `actingweb/db/protocols.py:212-226`: `iter_rows` (D3);
  `:1004-1014,1046-1065`: the `callback` contract (D6).
- `actingweb/db/dynamodb/actor.py:584-606`, `actingweb/db/postgresql/actor.py:434-471`:
  `iter_rows`; DynamoDB `fetch()` projects `id` and `creator` (D3).
- `actingweb/maintenance/mark_actors_vouched.py`: collection through
  `iter_rows(consistent=True, rate_limit=...)` with the filters applied
  there; `--rate-limit`; docstring and dead-code cleanup (D3).
- `actingweb/maintenance/verify_property_lists.py`, `migrate_property_lists.py`:
  iterate `iter_rows()`; the counter; the mid-sweep fault message (D3).
- `actingweb/maintenance/verify_orphans.py:227-236`: route through
  `iter_rows(consistent=True)` (D3).
- `actingweb/db/dynamodb/subscription.py`, `actingweb/db/postgresql/subscription.py`:
  the `callback` guards and the DynamoDB type hints (D6).
- `actingweb/mcp/uri.py`: `resolve_resource`; `actingweb/handlers/mcp.py`:
  `format_resource_read_result`, the sync path uses both;
  `actingweb/handlers/async_mcp.py:460-523`: uses both, hook arguments
  `{**params, **variables}` (D7).
- `actingweb/oauth2_server/trust_lookup.py` (new): `find_client_trust`;
  `actingweb/handlers/mcp.py:2592-2681` and
  `actingweb/oauth2_server/client_registry.py:591-668` call it (D8).
- `docs/guides/mcp-applications.rst` (the contract paragraph, D7);
  `docs/migration/v3.16.rst:201-252` and `CHANGELOG.rst:1268-1280` edited in
  place for `--rate-limit`, the consistent scan and the memory figure (D3);
  FIXED entries for D6, D7, D8 (D10).
- Todos and `INDEX.md` per D9.

### New Tests, both unit and integration tests

- `tests/test_db_fault_contract.py`: PostgreSQL, `list(DbActorList().iter_rows())`
  under `_pg_down` raises `DbError`, and a `_FakeConnection` that serves one
  page and faults on the second raises after the first row; DynamoDB, in
  `TestDynamoReadFaults`, `Actor.scan` patched with `_faults_mid_page([row])`:
  the first `next()` yields the row, the second raises `DbError`.
- `tests/test_actor_list_iter_rows.py` (new), both backends, in the fast
  tier: `_ITER_PAGE` monkeypatched to 2, five seeded actors deleted in
  `finally`; each seeded id appears exactly once with only `id` and
  `creator`, PostgreSQL in sorted order (lowercase hex ids, so collation is
  not a factor); DynamoDB passes `attributes_to_get`, `consistent_read` and
  `rate_limit` through (spy on `Actor.scan`); `fetch()` still returns the
  full list and passes `attributes_to_get`; the PostgreSQL generator holds
  no connection between pages (pool stats before and after a partial
  iteration).
- `tests/test_adoption_write_faults.py:108-116,201-208`: moved to the
  `iter_rows` seam; a raise before the first row is exit 2 with nothing
  scanned. `tests/test_mark_actors_vouched.py`: `--rate-limit` parses and
  reaches `iter_rows`; the `--creator` filter at collection time; the sorted
  order and `--start-after` tests unchanged.
- `tests/integration/test_verify_property_lists_script.py`,
  `test_migrate_property_lists_script.py`: the `_OneActor` fakes gain
  `iter_rows`; a mid-sweep fault keeps the checkpoint and exits 2 with the
  resume message.
- `tests/test_subscription_callback_type.py` (new), fast tier, both backend
  classes: `create(callback="https://…")` and `modify(callback="x")` raise
  `TypeError` naming `str` and not the value, with no `get_connection` or
  `save` call; `modify(callback=None)` is accepted. One integration case in
  `tests/integration/test_trust_create_defaults.py`'s style: `create(callback=True)`
  stores `True` on both backends.
- `tests/test_mcp_resource_read_permissions.py`: the parity class compares
  whole `result["contents"][0]` for a dict result declaring
  `mime_type="application/x-test"`, a dict result declaring none
  (`application/json`), a str result, a `contents` passthrough, a templated
  resource (the hook sees `uri` and the variables on both), and a resource
  declared only by `uri_pattern` (`AsyncMCPHandler` run of `legacy://v`
  beside `TestLegacyUriPatternDispatch`). Every unit resource today declares
  `text/plain`, so a test on `make_hooks()` alone would not discriminate.
  No existing test asserts the async body or `mimeType`; this class is the
  regression test.
- `tests/test_client_trust_lookup.py` (new), beside the resolver's tests,
  with `FakeTrust`/`FakeTrustManager` and the lazy `Actor`/`ActorInterface`
  imports patched: the decoy alone (`oauth2_client:evilclient-A:evilclient-A`
  against client `A`) is **not** deleted (today it is, via `endswith`); the
  decoy plus the exact row (by `oauth_client_id`) deletes exactly the exact
  row; a real-email legacy row (`oauth2_client:user@example.com:mcp_abc`, no
  `oauth_client_id`) is deleted by arm 3 on the deletion path and **not**
  returned by the resolver's default call; the resolver returns the same
  row as before for every `TestExactResolverMatching` input.

### Failure Scenarios

- **A scan fault mid-sweep in the property-list tools**: the sweep stops,
  the checkpoint keeps what was done, exit 2 with the resume message.
  Covered above.
- **A scan fault before the first row in `mark-actors-vouched`**: exit 2,
  nothing scanned. Covered above.
- **A PostgreSQL generator abandoned mid-sweep**: no connection held.
  Covered by the pool-stats test.
- **A consumer passing `callback="true"`**: `TypeError` propagates out of
  the handler chain (no site converts it to `False`), the integrations
  answer their fixed 500, the log names the parameter and the type. Covered
  by the type test.
- **A FastAPI consumer that parsed the old `text/plain` dict body, or
  returned a non-serialisable value**: the Behavior change sentence names
  both; the parity test pins the shape.
- **Two clients whose ids collide as substrings**: the decoy survives; the
  legacy real-email row still goes. Covered above.

### Verification

- [x] Fast tier
- [x] `poetry run actingweb-mark-actors-vouched --dry-run --rate-limit 50`
  against the test store: progress lines and the summary as before
- [x] Full tier on both backends before the commit
- [x] `thoughts/todo/INDEX.md` rows match the files in `thoughts/todo/`

### Implementation Status: Complete

### Implementation notes (Phase 3)

- **The property-list sweeps pull rows with `next()`** inside a loop, so a
  fault on the first pull still says "nothing scanned" and a fault later
  names how many actors were read and that a `--repair`/`--migrate` re-run
  resumes from the checkpoint. The checkpoint is now built before the first
  row (it only reads an existing file), and "No actors found" is decided
  after the loop.
- **`verify_orphans`** routes its DynamoDB id set through
  `dynamodb.actor.DbActorList().iter_rows(consistent=True)` directly (the
  function takes no config); the PostgreSQL branch is unchanged.
- **The `callback` guard is one helper**, `actingweb/db/_validation.py`
  `check_subscription_callback`, called first in both backends' `create`
  and `modify`. The integration case is a new file,
  `tests/integration/test_subscription_callback_backend.py` (both flags,
  both backends), in the shape of `test_trust_create_defaults.py`.
- **`resolve_resource` returns `(method_name, hook, metadata, variables)`**;
  the method name is what the hook is called with. The async handler keeps
  its own fault answers (`_db_fault_response`, "Resource read failed"), the
  sync one re-raises `DbError`, as recorded in D7. `uri_pattern` is set on
  the metadata by hand in the parity test, as in
  `TestLegacyUriPatternDispatch`: the decorator has no parameter for it.
- **`find_client_trust`** keeps the resolver's debug line through the
  caller (which arm matched). The deletion path deletes the one row it
  returns; the cascade in `Trust.delete()` back into client cleanup is the
  existing path and was not changed.
- **Minor-release items** (3.16.0 is already a minor): the protocol method
  `DbActorListProtocol.iter_rows`, the CLI flag `--rate-limit` on
  `actingweb-mark-actors-vouched`, the `TypeError` contract on
  `DbSubscription.create`/`modify`, and the FastAPI `resources/read`
  response shape.
- **Existing tests moved to the `iter_rows` seam**: the two
  `TestBundledMaintenanceExitCodes` cases in
  `test_db_fault_fourth_pass.py` (the "folded `False`" case became a
  part-way fault test, since `iter_rows` has no folding form) and the two in
  `test_adoption_write_faults.py`.
- **Todos (D9):** sections 4 and 7 of `mcp-cache-lifecycle-and-revocation.md`
  and item 4 of `dynamodb-known-next.md` were removed without renumbering
  the rest, because code and other todos cite them by section number; the
  `INDEX.md` rows name the sections left.
- **Verification:** fast tier green; `actingweb-mark-actors-vouched
  --dry-run --rate-limit 50` against the DynamoDB test store prints its
  progress and summary lines as before (`scanned=455 ... errors=0`), and
  `--help` shows the consistent-scan note; Full tier green (DynamoDB 5616
  passed, PostgreSQL 5421 passed), docs build and `verify_groups` green;
  every `thoughts/todo/` file has an `INDEX.md` row and no row dangles.

---

## Release

One PR from `release/3.16.0-dependency-security` to `master` after Phase 3,
three commits. CI on both backends. No version bump; 3.16.0 stays untagged.
Phases 1 and 3 both edit `actingweb/db/dynamodb/actor.py` and
`CHANGELOG.rst`; one branch, one commit per phase, so only line numbers
shift.

## Evaluation Notes

### Architecture
- **D7 had a fourth divergence**, the hook arguments (`mcp.py:1951` passes
  `params`; `async_mcp.py:477-485` passes only the template variables, pinned
  on FastAPI by `tests/integration/test_mcp_resource_regression.py:320-344`).
  Folded: `{**params, **variables}` on both, and the whole match block lifted
  into `mcp/uri.py` instead of adding the `uri_pattern` fallback a second
  time.
- **Two integration fakes** with only `fetch()` would raise `AttributeError`
  once the sweeps call `iter_rows` (`test_migrate_property_lists_script.py:305-309`,
  `test_verify_property_lists_script.py:372-376`). Folded into Phase 3.
- **D8 orphaned real-email legacy rows** that today's `endswith` deletes.
  Folded as the deletion-only segment-exact arm 3.
- **The MCP ladder has the same race** (`token_manager.py:393-511`,
  `_revoke_chain` at `:716`). Owner included it (2026-11-04); the helpers
  live in `single_use.py`, parameterised by partition.
- **D2 fixture scope**: the evaluator first recommended function scope, then
  withdrew it (`tests/_lookup_probe.py:11-14`: an integration-only run never
  loads the root conftest; a function-scoped fixture would create a `uc_`
  table after the rename). Session scope kept, reasoning recorded in D2.
- D2's unit tests need `reset_ensure_cache()` around the swap (`_ensure.py:80-81`
  memoises per class); folded. D8's module creates no import cycle;
  `client_registry.py:14-19` import list corrected. D7's import direction is
  already async → sync.

### Security
- **D4 holds on both backends**; the plan now names the db-layer strict read
  (`get_attribute(config).get_attr_strict`, not the cached wrapper), rests
  the DynamoDB argument on the strongly-consistent-read guarantee, and states
  the marker's readable span. The theft branch is correct (both holders
  lose).
- **The marker-present branch via `revoke_session` ran a second full sweep**
  and a second marker write, and an inner fault left orphan rows; it also
  made the plan's own interleaving and read-fault tests fail for unrelated
  reasons. Folded: two point `delete_confirmed` calls, for the generation
  guard too, with the justification recorded in D4.
- **Fail closed on a marker write fault** is the only order the retry can
  complete; recorded in D4.
- **D2**: `_run_transaction` raises `DbError` for a missing table (PynamoDB
  wraps every botocore error, `cancellation_reasons == []`); tests assert
  `DbError` specifically. The OAuth2 system actor bootstrap also fails
  closed; the docs sentence names it.
- **D5** leaves no browser session the MCP token authenticated (no flow
  stores an MCP token in `oauth_token`). **D6** echoes no value. **D8**
  cannot be steered; both deletion callers are actor-bound.
- Residuals named under What We're NOT Doing: chain-less legacy tokens,
  `revoke_all_tokens` has no caller.

### Scalability
- **Consistent reads are opt-in-shaped**: justified for `mark-actors-vouched`
  (it writes the scanned creator back) and pure cost for the two sweeps,
  which use only ids. Folded: the sweeps read eventually consistent with no
  new flag; the `fetch()` projection is documented as saving memory and wire
  bytes, not read units.
- **D4 reads per refresh**: DynamoDB 3 → 4, PostgreSQL 2 → 3 (its CAS is one
  `UPDATE`), writes unchanged; one combined read needs a batch primitive the
  protocol lacks. Recorded in D4.
- **PostgreSQL marker rows**: purge-eligible after 65 min, about 1.1 N to
  2.1 N rows at N revocations an hour, served by `idx_attributes_ttl`;
  DynamoDB sweeps are prefix-scoped so markers never inflate
  `CHAIN_SCAN_WARN_ROWS`. Recorded.
- **`mark-actors-vouched` memory**: about 220 MB per million actors (from
  about 350); filters applied at collection time. Recorded; the migration
  guide states the figure.
- D2 changes no cold-start budget count (`required_models()` excludes
  `Creator` by default). D7's `json.dumps` is no new cost class on the async
  path; its `TypeError` on non-serialisable values is in the Behavior change
  sentence.

### Usability
- **D2's operator experience** was a retryable 503 and a log naming only
  `actor create`. Folded: the ERROR line naming the table or index and the
  command, on both backends; `report` says the table is missing;
  `v3.16.rst:258-263` ("Nothing to do otherwise") rewritten; "should call"
  becomes "must call" with the consequence spelled out.
- **Changelog placement**: D2 edits the unshipped entries in place rather
  than adding a FIXED entry; D4 under SECURITY on the `:337` precedent
  (owner, 2026-11-04).
- **`--rate-limit`** is right beside `actingweb-unique-creators`; on the two
  sweeps it would sit beside `--rps` in different units, so they get no new
  flag. The consistent-scan note lives in the flag's help string because
  `--help` shows only the docstring's first paragraph.
- **D5 docs**: three more sentences become false (`spa-authentication.rst:1608,1622-1636`,
  `security.rst:99`); folded with the proposed wording. The response keeps
  "Successfully logged out" (owner: keep the shape, document it).
- **D6** wording proposed and adopted (type, never the value); the plan's
  "500 with the message" corrected to "the message reaches the log";
  DynamoDB type hints added.
- **D7** has no doc stating any contract; one paragraph added to
  `mcp-applications.rst`.

### Tests and code quality
- **The interleaving test as drafted could not reach the mint**: the sweep
  deletes the refresh row before the wrapped refresh consumes it, and both
  double hooks fire at the wrong position. Folded: the seam is a wrapper on
  `_generate_actingweb_token` (SPA) and `_create_access_token_from_refresh`
  (MCP) that runs the revocation once between the consume and the mints; the
  "mirror" test already exists (`:237-247`) and is not duplicated; the
  one-sweep pin is not asserted inside the race test.
- **D7's parity test would not discriminate** on `make_hooks()` (every unit
  resource declares `text/plain`); folded with explicit mime types and whole
  `contents` comparison. The "tests to update" sentence had nothing to act
  on and is replaced.
- **`iter_rows` cannot be a `PG_READS` row**; two dedicated fault tests
  instead. The dead `isinstance` check and the stale docstring go; the
  sweeps' mid-fault exit code is specified.
- **D2 unit fixture shape** (swap, reset, mandatory restore) and the
  `_raw_row` seeding for `test_disable_finishes_a_partial_run` folded.
- **D6** guards before any I/O; the type test is a fast-tier unit test, not
  behind `aw_app`.
- **D8** decoy test made deterministic (decoy alone, then decoy plus exact).
- **Sizing**: the 1001-row seed replaced by a monkeypatched page size; no
  `--rate-limit` on the sweeps.
- **D4 purge test** cannot drive `purge_expired_tokens` past a TTL on a real
  backend; folded: `delete_expired(now_epoch=...)` directly on PostgreSQL,
  the reaper's bucket list through the double's `purges`. The "second logout
  refreshes the marker" claim was wrong (a second logout never reaches
  `revoke_token_chain`) and is removed.

### Outside voice
Providers: Codex (`codex exec -s read-only`, outside the sandbox, relaunched
once with stdin closed) and a fresh-context Claude. What changed:
- **The deletion finisher sweeps SPA chains with no fence**
  (`deletion_finish.py:196`; no `session_generation.bump` anywhere in the
  finisher). Owner included it (2026-11-04): one `bump` before the sweep.
- **The advisory is live in v3.15.1 and the release-split question was
  unanswered.** The owner holds one PR; the SECURITY entry's **Check**
  sentence now carries the zero-code consumer remedy (`pip install -U
  "pyjwt>=2.15"`, allowed by the `^2.14` floor). Recorded under What We're
  NOT Doing.
- **D2 was DynamoDB-only**: the same bare-`Config()` process on PostgreSQL
  inserted the duplicate silently. Owner chose the once-per-process index
  probe (2026-11-04); the unit tier stubs it because the shared schema holds
  deliberate duplicates and cannot carry the index.
- **PostgreSQL `delete_expired` swallows faults and returns 0**
  (`postgresql/attribute.py:771-773`), so the only reaper of the marker
  bucket reported a fault as "nothing expired". Folded: it raises `DbError`;
  the callers fold it with a WARNING.
- **"PostgreSQL reads are consistent"** was the wrong word for keyset pages
  in separate transactions; the docstring says read-committed per page.
- **DynamoDB native TTL is an operator step** and the docs' TTL inventory
  did not list the marker buckets; folded into the Phase 2 docs.
- **`report` lists nothing when the table does not exist**; the sentence is
  corrected and `report` logs the missing table.
- **Two hand-rolled copies of the projected consistent scan remained**
  (`verify_orphans.py:227-236`, `unique_creators.py:197-207`);
  `verify_orphans` routes through `iter_rows`, `unique_creators` keeps its
  own (the upgrade command, no deliverable benefit from the swap).
- **A PostgreSQL generator could hold a pooled connection across yields**;
  one connection per page, released before the yield.
- **PostgreSQL marker reclamation is traffic-dependent**; one sentence in
  D4.
- Not adopted: Codex's "release workflow conflict" on the branch name
  (`release/<version>-<slug>` is the project's minor-PR branch shape and the
  held tag is recorded owner policy).

### Advisor pass (after the outside voice)
- The PostgreSQL index-probe stub was wired into the root conftest only,
  which the integration tier never loads; moved to `tests/_lookup_probe.py`
  and imported by both conftests, with backend guards.
- The MCP marker write is placed before the first `_snapshot_bucket` read,
  not merely before `revoke_chain_confirmed`.
- Point deletes on the generation-mismatch branch are safe because every
  `bump` caller sweeps the actor's tokens itself (`oauth2.py:3042-3049,3083-3086`,
  the finisher); recorded in D4.
- `bump` raises `DbError`, and no write path suppresses writes to a
  tombstoned actor; recorded in D4.
- `missing_enforcement` reuses the db-layer index probe; `unique_creators`
  keeps its own actor scan.

### Unverified notes
- The exact PynamoDB exception class for a missing table inside
  `TransactWriteItems` was read from the installed source, not run; both
  `except` clauses end in `DbError` regardless.
- `oauthlib` 4.0.1's provider-side-only breaking changes are not provable
  from this tree; the suite proves the two client-side imports work.
- The full list of `fresh_store` tests that create an enforced actor before
  `enable`, on either backend, needs the Phase 1 run.
- D8: `_delete_client_trust_relationship` → `delete_relationship` →
  `Trust.delete()` cascades back into client cleanup (`trust.py:136-137`);
  existing behaviour, but the helper's single-row delete should be checked
  for re-entrancy on that path during implementation.
- Whether `token_manager.py:1878` already folds a `delete_expired` exception
  was not read; Phase 2 checks and wraps if not.

## Implementation Summary

**Completed:** 2026-11-04
**All phases:** Complete (three commits on `release/3.16.0-dependency-security`)
**Test status:** All passing. Full tier on both backends after each phase;
the last run had DynamoDB 5616 passed and PostgreSQL 5421 passed, with the
docs build, `verify_groups`, ruff and pyright at 0 errors and 0 warnings.

### Deviations from Plan
- PostgreSQL's missing-index refusal raises `DbError(op)` (the plan said
  `DbError("creator uniqueness index missing")`), so the documented
  `database error during actor create` is exactly true. An INVALID index is
  refused too.
- The DynamoDB remedy ERROR does not confirm the missing table with
  `DescribeTable`, which the runtime role may lack.
- `_creators_table` runs on every backend (best-effort on PostgreSQL),
  because several unit tests pin `database="dynamodb"`.
- The MCP race test revokes through the consumed refresh token; the old
  access row is gone by the time the mint runs.
- The theft and `/oauth/revoke` marker tests live in
  `test_oauth2_spa_logout_revokes_chain.py`.
- The property-list sweeps' "folded `False`" test became a part-way-fault
  test; `iter_rows` has no folding form.
- Todo sections were removed without renumbering, since they are cited by
  number.
- After the 2026-11-04 verification (Iterations 1-5): DynamoDB checks the
  backfill item, not only the table; arm 3 covers every OAuth2 source; a
  resource hook's `uri` is reserved; a resumed finish with the row gone
  does not bump.
- After the re-verification (Iterations 6-9): client deletion removes every
  row of the client; the probe logs its fault and reads once per refusal;
  pattern resources are documented as getting no variables (behaviour
  unchanged); a registration warning for a variable named `uri` was not
  added.
- After the third verification (Iterations 10-13): the client-deletion
  entry is hardening, not a fix of lost permissions; the deletion loop
  survives a cascade and a fault on one row; unguarded creator-record
  repairs get their own missing-table ERROR; the 503 for a missing
  enforcement and the Flask/FastAPI error differences are documented,
  not changed.
- After the fourth verification (Iterations 14-16): `_run_transaction`
  takes a required `creators` context, so property transactions no longer
  report missing creator enforcement; a client-manager retry after a
  trust-row fault sweeps the leftover rows. The wider client-deletion
  lifecycle is audited separately, not iterated here (owner's call,
  2026-11-04).
- After the client-deletion audit (Iterations 17-19, owner's request
  2026-11-04): deleting a trust row ends one actor's connection and
  deletes the client only for its owner (D1); the audit's Medium findings
  D3-D8 are fixed or shown inert; D2 was investigated against the
  protocol and left as documented follow-up work. An outside-voice review
  of that change (Iteration 20) found that a remote peer could reach the
  same cascade through `POST /trust` with an OAuth2-shaped peer id;
  peer-supplied ids now refuse the OAuth2 prefixes.

### Learnings
- `make test-all-parallel` ends with `docker compose down -v`, so the next
  direct unit run needs the containers started again; a "Could not connect"
  wave after a `make` run is that, not a regression.
- An unattended Full tier must leave the tree alone: the PostgreSQL run and
  the docs build read the working tree after the DynamoDB run.
- Importing anything under `actingweb.db.dynamodb` imports every model and
  freezes its table name under the `AWS_DB_PREFIX` of that moment, so a
  session-scoped test fixture must not import it before the integration
  conftest has set the worker prefix.
- "Table exists" and "enforced" differ on DynamoDB: the startup prewarm
  creates the creators table before it refuses to start.
- Not done here, and not filed: nothing. The PR opens after the
  verification, per the one-PR-per-plan rule.
- "First match" and "every match" are different contracts: authorisation
  wants one row, deletion wants all of them. One function with a flag
  served both and hid that the deletion stopped early.
- A side-effecting delete can recurse: `Trust.delete` deletes the client
  again, so a test fake that deletes only the named row misses both the
  cascade's benefit (Issue 3 of the third verification) and its cost (a
  later delete finds nothing). Model the cascade when testing a loop over
  rows it can reach.
- A row that *connects* an actor to a client is not ownership of the
  client. Ownership is "the client's row is in my own `mcp_clients`
  bucket", which needs no global index read, so a missing index row cannot
  promote a connection to an owner.


## Iterations

### 2026-11-04, after verification thoughts/verifications/2026-11-04-3-16-dependency-security-rollup.md

#### 1. DynamoDB enforced writes require a backfilled creators table, not just an existing one

**Category**: Verification fix (Issue 1, High)

**What changed**: An enforced DynamoDB create, creator rename or holder
replacement now reads the creators table's backfill-complete item once per
process (cached positive only, keyed by table name) and raises `DbError(op)`
with the remedy ERROR ("is not backfilled" or "does not exist") when it is
absent. The read lives in a new module, `actingweb/db/dynamodb/_backfill_probe.py`
(`creators_backfill_state`, `creators_backfilled`, `reset_backfill_probe`);
`unique_creators._backfill_state` delegates to it, and `disable` resets it.
The transaction-time ERROR no longer blames `creators` alone (Issue 8): it
names both tables and `AWS_DB_PREFIX`.

**Files affected**:
- `actingweb/db/dynamodb/_backfill_probe.py` (new) — the state read and the positive cache
- `actingweb/db/dynamodb/actor.py` — `_require_creators_backfill` before the create, rename and replace transactions; the constructor docstring; the ERROR wording
- `actingweb/maintenance/unique_creators.py` — `_backfill_state` delegates; `disable` resets the probe; the no-op `reset_index_probe()` after an index build is gone (Issue 11)
- `tests/_lookup_probe.py`, `tests/conftest.py`, `tests/integration/conftest.py` — `_stub_dynamodb_backfill_probe` (function-scoped, every backend) and `real_dynamodb_backfill_probe`
- `tests/integration/_isolated_store.py` — `wipe_store` resets the probe
- `tests/test_unique_creator_fail_closed.py` — an empty, unbackfilled table refuses create and replace (nothing written, ERROR names it), a backfilled one claims with one probe read; a rename against it is refused and an exempt rename is not probed
- `tests/integration/test_unique_creator_states.py` — `TestFailClosedBeforeEnable` uses the real probe on both backends; `test_the_prewarmed_empty_table_still_refuses`

**Rationale**: D2's DynamoDB check only noticed a missing table. The
`check_ready()` prewarm (`interface/app.py:1580`) creates `creators` empty
before it refuses to start, so after an existing fleet's documented first
start a bare-`Config()` worker claimed creators against no records: the
deleted todo's scenario, and the docs promised a `DbError`. Checking the
backfill item makes DynamoDB mean "enforced", as PostgreSQL's index-validity
probe already does. The stub is function-scoped because importing anything
under `actingweb.db.dynamodb` imports every model, whose table names freeze
at import, and a session fixture ran before the integration conftest set the
worker prefix (the first attempt failed `isolated_store` with "unexpected
table name").

#### 2. Client deletion finds real-email legacy rows of every OAuth2 source

**Category**: Verification fix (Issues 2 and 9; part of 11)

**What changed**: Arm 3 of `find_client_trust` (deletion only) accepts a
peer id whose first segment is any source trust creation writes (`oauth2`,
`oauth2_client`, `oauth2_interactive`), not only `oauth2_client:`. It is
gated on OAuth2 origin as arm 2 is (`established_via` in that family, or
none with such a prefix), and the last segment must equal the client id as
given or normalised. `normalize_client_id` is now the one copy of the
normaliser; `TrustManager.create_or_update_oauth_trust` calls it.

**Files affected**:
- `actingweb/oauth2_server/trust_lookup.py` — `OAUTH2_SOURCES`, `normalize_client_id`, `_oauth2_origin`, the widened and gated arm 3
- `actingweb/interface/trust_manager.py` — peer-id creation uses `normalize_client_id`
- `tests/test_client_trust_lookup.py` — every source deleted (four cases), a peer-protocol lookalike skipped in favour of the real row, the shared normaliser; the old case that pinned `oauth2:` rows as kept now uses a non-OAuth2 prefix

**Rationale**: creation writes `{established_via or "oauth2"}:<email>:<client>`
(`interface/trust_manager.py:465,485`), and the old `endswith` deleted every
such row. Accepting only `oauth2_client:` left `oauth2:` and
`oauth2_interactive:` rows alive, with their permissions, after their
client was deleted. The resolver's default call is unchanged.

#### 3. Resource hook arguments: variables win over params, `uri` is reserved

**Category**: Verification fix (Issues 3 and 4)

**What changed**: `actingweb/mcp/uri.py` gains `resource_arguments(params,
variables, uri)` = `{**params, **variables, "uri": uri}`, used by both
handlers. The D7 changelog entry now names the FastAPI `content`-key
unwrap that went away, the Flask-side change (hooks receive the variables),
the splat risk and the reserved `uri`; `mcp-applications.rst` says the same.

**Files affected**:
- `actingweb/mcp/uri.py` — `resource_arguments`
- `actingweb/handlers/mcp.py`, `actingweb/handlers/async_mcp.py` — call it
- `tests/test_mcp_resource_read_permissions.py` — `test_uri_is_reserved_and_variables_win_over_params` (`shadow://{uri}/{id}` read with a client `id` param: both handlers pass `{"uri": request uri, "id": "7"}`)
- `CHANGELOG.rst`, `docs/guides/mcp-applications.rst`

**Rationale**: the verification suggested `{**variables, **params}`. That
order would let a client param replace a template variable after the
permission check judged the URI it came from (read `notes://1`, allowed,
with `id=2`), so the variables keep precedence and only `uri` is pinned
to the request.

#### 4. A resumed finish with the actor row gone writes no generation; the PostgreSQL probe docstring says what it caches

**Category**: Verification fix (Issues 6 and 7)

**What changed**: `finish_deletion` bumps the session generation only when
it is not a resume or the actor row still exists. The PostgreSQL
`DbActor.__init__` docstring states that a positive probe is kept for the
process's life, so a worker keeps writing without the index if an operator
drops it while the worker runs.

**Files affected**:
- `actingweb/deletion_finish.py` — the guarded bump (one strict actor read, on a resume only)
- `actingweb/db/postgresql/actor.py` — the docstring
- `tests/test_deletion_finish.py` — `test_a_resume_with_the_actor_row_gone_writes_no_generation` (`bump.assert_not_called()`, `current(...) is None`)

**Rationale**: a resume whose actor row is already gone returns from
`actor.delete()` before `Buckets.delete()`, so the bump's row was an orphan
nothing reaps. Nothing can mint for that actor anyway: its row is gone.

#### 5. Test hygiene

**Category**: Verification fix (Issues 10 and 11)

**What changed**: type hints on the new integration test functions; the
duplicated `_only_this_actor` stub is one helper,
`tests/integration/_actor_list_stub.only_this_actor`, used by both
property-list script tests.

**Files affected**:
- `tests/integration/_actor_list_stub.py` (new)
- `tests/integration/test_migrate_property_lists_script.py`, `tests/integration/test_verify_property_lists_script.py` — import it
- `tests/integration/test_subscription_callback_backend.py` — annotations

**Rationale**: CLAUDE.md requires type hints on every function; two copies
of a stub of the new `iter_rows` contract would drift.

#### Accepted, not changed: the finisher fence and unstamped tokens (Issue 5)

A never-adopted SPA refresh (no generation stamp) whose consume preceded the
finisher's sweep and whose guard runs only after `actor.delete()` removed
`_internal` compares `None == None` and keeps its pair. Accepted: the
window needs the mint to straddle both the client sweep and the wipe, the
pair is for an actor whose row is gone (every token validation loads the
actor), and it works again only if the same id is re-created. Closing it
needs a deletion check in every refresh guard, a read on the hot path for a
deleted-actor edge.

### 2026-11-04, after verification thoughts/verifications/2026-11-04-3-16-dependency-security-rollup-reverify.md

#### 6. Client deletion removes every row of the client

**Category**: Verification fix (Issues 1, 6 and 7)

**What changed**: `trust_lookup.py` splits the arms into predicates.
`find_client_trust(trusts, client_id)` (arms 1 and 2, the resolver) keeps
its single-row answer and loses `legacy_segment_match`. The new
`client_trusts_for_deletion(trusts, client_id)` returns every row arm 1,
2 or 3 matches, in row order, and `_delete_client_trust_relationship`
deletes each one (a `DbError` still propagates, any other fault is logged
per row). Arm 3 now needs exactly three peer-id segments, and its docstring
says its origin gate is wider than arm 2's on purpose and must not be
reused for authorisation.

**Files affected**:
- `actingweb/oauth2_server/trust_lookup.py` — predicates, `client_trusts_for_deletion`, docstrings
- `actingweb/oauth2_server/client_registry.py` — deletes every match
- `tests/test_client_trust_lookup.py` — `test_a_tagged_row_and_a_legacy_row_of_one_client_are_both_deleted`, `test_the_segment_arm_needs_exactly_three_segments`; the arm-3 cases call the new function
- `CHANGELOG.rst` — the client-deletion FIXED entry names the second row and the behaviour change

**Rationale**: arm 1 always won, so an upgraded actor's legacy `oauth2:`
row survived beside the deleted tagged `oauth2_client:` row with its
permissions. **[Corrected 2026-11-04, Iteration 10]** Not for generated
`mcp_` ids: deleting the tagged row ran `Trust.delete`, which deletes the
client again (`trust.py:136,166`), and that nested call removed the legacy
row. The change is hardening: deletion no longer depends on the cascade,
which cannot extract a non-`mcp_` client id. A client-less legacy peer id keeps `:` unescaped, so "three or
more segments" could match one whose identifier ended in a client id. The
resolver's answer is unchanged: the same two arms in the same order, pinned
by `test_the_default_matches_the_resolver` and the `find_client_trust(...)
is tagged` assertion in the new two-row test.

#### 7. The backfill probe logs its fault and reads once per refusal

**Category**: Verification fix (Issues 2 and 3)

**What changed**: `_backfill_probe.cached_backfill_state()` replaces
`creators_backfilled()`. It answers "complete" from the cache, or reads
once. `_require_creators_backfill` branches on that one state. A read fault
logs an ERROR with the table, the fault and "check that the runtime role has
dynamodb:GetItem on <table>" before it raises `DbError(op)`.
`creators_backfill_state()` remembers a "complete" answer, so the
`check_ready()` read also spares the first enforced write its read. The
test stubs patch `cached_backfill_state`.

**Files affected**:
- `actingweb/db/dynamodb/_backfill_probe.py` — `cached_backfill_state`, cache seeding, module docstring corrected (Issue 8)
- `actingweb/db/dynamodb/actor.py` — `_require_creators_backfill`
- `tests/_lookup_probe.py` — the stub and the real-probe fixture
- `tests/test_unique_creator_fail_closed.py` — `test_a_probe_read_fault_is_refused_with_a_logged_reason`, `test_a_refusal_reads_the_marker_once_and_check_ready_seeds_the_cache`
- `CHANGELOG.rst` — the D2 entry names the read-fault refusal and its ERROR

**Rationale**: a role without `GetItem` on the creators table got 503s
that no retry clears, traced only as "database error during actor create".
Two reads per refusal could disagree with each other and cost a second
round-trip; the startup check's read was thrown away.

#### 8. DynamoDB docstrings: the cache caveat and the likely missing table

**Category**: Verification fix (Issues 4 and 5)

**What changed**: the DynamoDB `DbActor.__init__` docstring states that a
positive probe is kept for the process's life, so a worker that saw the
item keeps claiming after `disable --apply` empties the table (a silent
duplicate), and that every worker restarts with the flag off before
`disable`. The transaction-time ERROR names the actor table first ("check
AWS_DB_PREFIX") and the creators table second ("deleted since this process
saw it backfilled"), since the probe now reports a missing creators table
itself.

**Files affected**:
- `actingweb/db/dynamodb/actor.py` — the constructor docstring, `_log_missing_creators_table` docstring and message

**Rationale**: PostgreSQL's docstring carried the caveat and DynamoDB's,
where the consequence is worse, did not. The ERROR pointed at the less
likely table.

#### 9. Doc accuracy and test hints

**Category**: Verification fix (Issues 8 and 9)

**What changed**: the `unique_creators._backfill_state` cross-reference
names `_backfill_probe.creators_backfill_state`. `mcp-applications.rst` and
`resource_arguments` say that a `uri_pattern` match gets no variables, so
its hook must read judged values from `uri`, and that a variable named
`uri` is dropped without a warning. The `resources/read` test hooks and
helpers are annotated.

**Files affected**:
- `actingweb/maintenance/unique_creators.py`, `actingweb/mcp/uri.py`, `docs/guides/mcp-applications.rst` — docs
- `tests/test_mcp_resource_read_permissions.py` — annotations; `isinstance` narrows the async handler

**Rationale**: returning a pattern's named groups would change what
existing pattern hooks receive; narrowing the doc sentence keeps behaviour
and makes it true. The verification marked the registration warning
optional.

### 2026-11-04, after verification thoughts/verifications/2026-11-04-3-16-dependency-security-rollup-reverify-2.md

#### 10. Changelog accuracy: marker-fault statuses and the client-deletion claim

**Category**: Verification fix (Issues 1, 3 and 12a)

**What changed**: the chain-revocation entry says logout, `/oauth/revoke`
and the SPA endpoint answer a marker write or read fault with 503 and
`Retry-After`, and `/oauth/token` with 500 `server_error`
(`TokenStoreUnavailable`, the MCP endpoint's existing answer to a store
fault, as `v3.15.rst` documents; its theft response writes a marker too).
It also says that `delete_expired`'s
callers fold the fault with a WARNING in the token purges and a printed
line in `actingweb-deletions`. The client-deletion entry no longer says a
second row "kept its permissions": the cascade removed it for generated
`mcp_` ids, and the entry now describes direct deletion as hardening. It
names the two-segment `oauth2_client:<client_id>` row as no longer deleted
(Issue 12b, accepted: the resolver already ignored it). Iteration 6's
rationale carries a correction note.

**Files affected**:
- `CHANGELOG.rst` — both entries
- `actingweb/db/postgresql/attribute.py` — the comment on the caller fold

**Rationale**: the code was right and the entries were not; a consumer
reading "503" would have built retry logic for a status `/oauth/token`
never sends.

#### 11. The deletion loop survives a cascade and a fault on one row

**Category**: Verification fix (Issues 5 and 6)

**What changed**: when `delete_relationship` answers False, the loop reads
the relationships again (`TrustManager.relationships` re-reads the store
on every access, no cache); a row that is gone (an earlier row's cascade took
it) logs INFO "already deleted" instead of the WARNING. A `DbError` on one
row is logged and kept, the remaining rows are still deleted, and the first
fault is raised after the loop.

**Files affected**:
- `actingweb/oauth2_server/client_registry.py` — the loop
- `tests/test_client_trust_lookup.py` — `_CascadingTrustManager` models `Trust.delete`'s cascade; `test_a_row_the_cascade_already_deleted_logs_no_failure`, `test_a_fault_on_one_row_still_deletes_the_others_then_raises` (both fail without the change); the two-row test's docstring corrected

**Rationale**: the client row and its index are gone before this loop
runs, so a retry cannot find rows a stopped loop left; and a WARNING for a
deletion that worked trains operators to ignore it.

#### 12. Unguarded creator-record repairs get their own missing-table ERROR

**Category**: Verification fix (Issue 4)

**What changed**: `DbActor._run_transaction` takes `guarded: bool = True`;
`release_stale_record`, `record_for_actor_as_read` and `move_stale_record`
pass `guarded=False`. On an unguarded path a missing table logs "A creator
record repair needs a table that does not exist: either <actors> or
<creators>", naming the prefix check and `enable --apply`, without the
"most likely" preference or the "actor write was refused" remedy text.

**Files affected**:
- `actingweb/db/dynamodb/actor.py` — the flag, the three callers, the log helper and its docstring
- `tests/test_unique_creator_fail_closed.py` — `test_an_unguarded_record_repair_names_both_tables_neutrally`
- `tests/integration/test_unique_creator_states.py` — the `_run_transaction` wrapper forwards keyword arguments

**Rationale**: `resolve --apply` against a missing creators table was told
the actor table was the likely one.

#### 13. Docs: custom backends, creator changes, accepted differences

**Category**: Verification fix (Issues 2, 7, 8, 9, 10, 11, 12e)

**What changed**:
- The v3.16 custom-backend list names `DbActorList.iter_rows` (and the
  four commands that call it), the bool `callback` on subscription
  `create`/`modify`, and `delete_expired` raising on a fault (Issue 2).
- The fail-closed passages in `v3.16.rst` (two) and `configuration.rst`
  say "every actor create and creator change (a rename, a holder
  replacement)", and name each change's `DbError` message (Issue 7).
- Issue 8 accepted, documented: `database-backends.rst` names the one
  non-retryable refusal that still answers 503 (missing enforcement) and
  why only direct `Config()` code meets it. A 500 would need a new
  `DbError` subclass and an integration change for a state `check_ready()`
  already prevents at startup.
- Issue 9: `security.rst` names the resumed-deletion exception to the
  generation bump.
- Issues 10 and 11 accepted, documented: `mcp-applications.rst` says the
  integrations answer a successful read identically and names the
  differing error messages and Flask's synchronous hook; a `str` result is
  labelled with the decorator's `mime_type`. Changing either is a
  behaviour change outside a verification fix.
- Issue 12e: `attributes-buckets.rst` says every trust row of the client.
- Issues 12c (an email containing `:`) and 12d (the raw exception in the
  probe log, consistent with existing logs) accepted as-is.

**Files affected**:
- `docs/migration/v3.16.rst`, `docs/quickstart/configuration.rst`, `docs/reference/database-backends.rst`, `docs/reference/security.rst`, `docs/guides/mcp-applications.rst`, `docs/sdk/attributes-buckets.rst`

**Rationale**: every remaining finding was a statement the code did not
match; where changing the code was the larger risk, the statement now
matches the code.

### 2026-11-04, after verification thoughts/verifications/2026-11-04-3-16-dependency-security-rollup-reverify-3.md

The last iteration on this plan. The owner chose to close the
verify-iterate loop here and audit the client-deletion lifecycle as
separate work, since the loop's findings had moved into code older than
the branch.

#### 14. A required creator context for `_run_transaction`

**Category**: Verification fix (Issue 1)

**What changed**: `guarded: bool = True` became a required
`creators: Literal["guarded", "unguarded", "none"]`. The three enforced
actor writes pass "guarded", the three record repairs pass "unguarded",
and the five property transactions (`property.py:387,455,494,552`,
`property_lookup.py:261`) pass "none". For "none", the missing-table ERROR
names the transaction and the prefix check, not the creators table or
`enable --apply`. `_log_missing_creators_table` was renamed
`_log_missing_table`. The DynamoDB fault-reporting audit found that the
"guarded" branch did the same thing: it named the actor table as most
likely missing and then gave only the creator remedy. It now gives each
candidate its own remedy (check the prefix for the actor table, `enable
--apply` for the creators table), and no longer goes through
`missing_enforcement_message`.

**Files affected**:
- `actingweb/db/dynamodb/actor.py`, `property.py`, `property_lookup.py`: the argument and every caller
- `tests/test_unique_creator_transactions.py`: direct calls pass "guarded"
- `tests/test_unique_creator_fail_closed.py`: `test_a_property_transaction_on_a_missing_table_names_no_creator_remedy`, `test_a_guarded_write_gives_each_candidate_table_its_own_remedy`

**Rationale**: a missing properties table logged "Creator uniqueness is on
… Run `actingweb-unique-creators enable --apply`", even with uniqueness
off. That bug predates the branch, but Iteration 12's docstring claimed
otherwise. Making the argument required means a new caller has to choose.

#### 15. A client-manager retry finishes a faulted deletion

**Category**: Verification fix (Issues 3 and 4)

**What changed**: when `OAuth2ClientManager.delete_client` finds no client,
it now runs `_delete_client_trust_relationship(self.actor_id, client_id)`
before answering False. A deletion that faulted on a trust row after the
client row was gone (503) is therefore finished by its retry. The sweep
only touches this actor's rows for that client id. The changelog says
where the first fault goes: to the client-deletion caller, or into the
cascade's log when the deletion began with a trust-row delete. The loop's
comment is corrected to match.

**Files affected**:
- `actingweb/interface/oauth_client_manager.py`: the not-found path
- `actingweb/oauth2_server/client_registry.py`: the comment
- `tests/test_client_trust_lookup.py`: `test_a_retry_after_a_trust_fault_finishes_the_leftover_rows`
- `CHANGELOG.rst`: the client-deletion entry

**Rationale**: the integrations answer the fault as retryable, and the
retry used to answer "not found", leaving the trust row and its
permissions in place. Reordering the deletion so trust rows go before the
client row would leave a faulted client able to authenticate. That is a
design question for the audit.

#### 16. Doc accuracy

**Category**: Verification fix (Issues 2, 5, 6, 7, 8)

**What changed**:
- The custom-backend list names the three commands that call `iter_rows`,
  and says verify-orphans supports only DynamoDB and PostgreSQL (Issue 2).
- The fail-closed passages say "for a non-exempt creator" (Issue 5).
- `database-backends.rst` says a table or index removed after startup
  answers the same 503 (Issue 6).
- `mcp-applications.rst` says an `async def` hook on Flask is not awaited
  and returns its repr (Issue 7).
- The garbled changelog clause is fixed (Issue 8).

**Files affected**:
- `docs/migration/v3.16.rst`, `docs/quickstart/configuration.rst`, `docs/reference/database-backends.rst`, `docs/guides/mcp-applications.rst`, `CHANGELOG.rst`

**Rationale**: each sentence now matches the code.

### 2026-11-04, after the client-deletion audit thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md

The owner asked for D1 to be fixed, D2 to be investigated against the
distributed protocol, and the Medium findings to be fixed here. This is
more than a typical iteration, but it stays on the branch at the owner's
request.

#### 17. Deleting a connection never deletes another actor's client (D1, D3, D4, D5, D7, D8)

**Category**: Bug fix (security)

**What changed**:
- `Trust.delete` reads the row's client from `oauth_client_id`, else from
  a peer id `<source>:…:mcp_…` with any `OAUTH2_SOURCES` prefix (D5).
- It asks `registry.client_owned_by(actor, client)`, a strict read of the
  actor's own `mcp_clients` row. The owner deletes the client as before.
  Any other actor calls `revoke_connection_tokens` *before* the row delete
  (a fault raises `DbError` and leaves the row), then deletes its other
  rows of the client.
- A failed `delete_client` or sibling sweep raises instead of being folded
  (D4).
- `delete_client` refuses an `actor_id` that differs from the registration's
  owner.
- `delete_client_connection(actor, client)` revokes and sweeps one
  connection; `OAuth2ClientManager`'s retry path uses it (D3).
- `_revoke_matching_tokens` snapshots once to mark every chain it reaches
  revoked, then snapshots again and deletes (D8). A chain whose marker
  cannot be written keeps its tokens and counts as unconfirmed.
- `delete_reciprocal_trust` deletes `oauth_tokens:<peer_id>` after the row,
  for any OAuth2-sourced row (D7).

**Files affected**:
- `actingweb/trust.py`: routing, `_oauth2_client_id`, the wider peer-id parse
- `actingweb/oauth2_server/client_registry.py`: owner guard, `client_owned_by`, `revoke_connection_tokens`, `delete_client_connection`
- `actingweb/oauth2_server/token_manager.py`: the marking pre-pass
- `actingweb/interface/oauth_client_manager.py`: retry path
- `actingweb/actor.py`: provider-token delete; `is_oauth2_trust` covers every OAuth2 source
- `tests/test_client_connection_deletion.py` (new):
  - routing tests: owner vs connection, revoke before the row, fault keeps the row, a failed client deletion raises
  - client-id resolution, including the legacy `oauth2:` row
  - the owner guard
  - chain markers before removal, and an unmarkable chain keeps its tokens
- `tests/integration/test_trust_oauth_integration.py`: `test_deleting_a_connection_keeps_another_actors_client`, which asserts that X's client loads with owner X, Y's token no longer validates, Y's rows and provider tokens are gone, and X's row stays. It fails on the old code.
- `tests/test_trust_core.py`, `tests/test_client_trust_lookup.py`: assertions moved to the new internals
- `CHANGELOG.rst` (SECURITY entry); `docs/sdk/attributes-buckets.rst`, `docs/guides/oauth2-setup.rst` (the old "pass the user's actor" advice inverted), `docs/reference/security.rst`
- `thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md`: disconnect no longer removes a registration

**Rationale**: a client's index row is global, and any row deletion
removed it, so one user's disconnect (or a deliberate one) disabled the
client for everyone. Before this change, D8's minted pair was not inert:
the shape-B peer id is deterministic, so a re-authorization would revive a
chain the sweep missed.

The audit's D3 window (two faults leaving an hour of access) is now
bounded by the row staying in place: the revocation runs before the row
delete, and its fault answers 503 with the row as the retry handle.

#### 18. Permissions after the trust row (D6)

**Category**: Bug fix (security)

**What changed**: `delete_reciprocal_trust` deletes the row, then its
custom permissions, then provider tokens. A row that `Trust.delete`
reports as not deleted is skipped and counted, and the call answers False
instead of ignoring the result.

**Files affected**:
- `actingweb/actor.py`
- `tests/integration/test_trust_oauth_integration.py`: `test_a_fault_before_the_row_delete_keeps_its_permissions` injects a `DbError` in the peer-profile cleanup and asserts the row and its `patterns` survive. It fails on the old code.

**Rationale**: deleting permissions first meant a fault in between left a
live row on its trust type's defaults, which can be wider. The residual
risk is now a stale permission row, left when a fault lands after the row
delete, which a later row with the same peer id inherits. That row would
carry the same user's own earlier settings for the same client, which is
the lesser risk.

#### 19. D2 investigated: a client's connections are local to its server

**Category**: Investigation (no code change)

**Finding**: the actingweb protocol has no remote counterpart for an OAuth2
client connection.
- A DELETE on a trust URI "will terminate the relationship"
  (`docs/protocol/actingweb-spec.rst:652`), and that relationship belongs
  to one actor.
- MCP authentication is implementation-defined (`:1360`).
- `delete_reciprocal_trust` sends no remote DELETE for an OAuth2-sourced
  row (`is_oauth2_trust`).
- The authorize callback resolves the user by email in this server's own
  store (`oauth2_server/oauth2_server.py:390`), so every connection row is
  on a local actor.
- A user on another ActingWeb server would register and authorize against
  that server's own registry, with a different client id.

So D2 is intra-server only: a client registered under actor X and
authorized by local actor Y keeps Y's row and tokens when X deletes it.
After D1, dynamically registered clients have no deleter at all, so D2
concerns SDK-created clients (`OAuth2ClientManager.create_client`).

**Exposure today**:
- Y's access tokens stay valid for up to an hour: validation does not check
  that the client exists (`token_manager.py:296-332`).
- Y's refresh and code grants stop at once, because `load_client_strict`
  fails.
- After that, Y's row is inert, though it is still listed and still
  deletable by Y.

**Options, not taken here**:
1. Have token validation check that the client still exists. This is one
   extra load per uncached validation (the token cache is 300 s), and the
   load can fault.
2. Write a (client → actors) index at authorize time, so that deleting a
   client can reach every connection.

Option 1 closes the hour without new state. Option 2 also removes the
inert rows. Either is a design change for its own plan.

#### 20. Review fixes: peer-supplied OAuth2 ids, ownership, side stores

**Category**: Bug fix (security)

**What changed**: an outside-voice review (codex and a fresh Claude
context) of Iterations 17-18, before they were committed, found these:
- **High.** `POST /<actor>/trust/<rel>` is unauthenticated, and its peer id
  allows `:`. A peer could create `oauth2_client:x:mcp_<id>`, then DELETE
  it, and so drive the client cascade on any actor. Iteration 17 had also
  widened the accepted prefixes. The old code had the same hole, worse:
  it deleted the client globally. Because a trust create overwrites a row,
  a peer that knew a user's email and client id could also replace that
  user's real row. Fixes:
  - `is_valid_peer_id` refuses the three OAuth2 prefixes.
  - `Trust._oauth2_client_id` reads a client only from a row with an
    OAuth2 `established_via` (or none, with an OAuth2 prefix: the legacy
    rows), the resolver's `_oauth2_origin` gate. Peer rows record
    `"trust"`.
- **Medium.** `client_owned_by` now compares the row's `actor_id`.
  `delete_client` uses it when `_load_client` finds no index row. On actor
  deletion, an index row is deleted only when it names the deleted actor.
- **Medium.** The permission and provider-token deletes moved from
  `delete_reciprocal_trust` into `Trust.delete`, right after the row and
  before the client cleanup that can raise. A new OAuth2 row with a reused
  peer id starts without stale permissions
  (`create_or_update_oauth_trust`). Each delete runs only when a row exists,
  so no "failed to delete" ERROR is logged on every connect.
- **Medium.** A local trust row that `Trust.delete` reports as not deleted
  raises `DbError` instead of returning False, which `Actor.delete` and
  `purge_relationships` ignored before their bulk delete.
- **Low.** The `deletion_finish.py` comment now says the MCP sweep marks
  chains. The changelog says the manager keeps its owner check, and no
  longer claims that every legacy `oauth2:` row authorises.

Accepted as-is:
- The marker pre-pass costs two more bucket snapshots per revocation.
- Legacy tokens without a `chain_id`, and a chain that starts from a code
  exchange during the sweep, are not fenced. A code exchange reads no
  marker; that window is the remaining part of D8.

**Files affected**:
- `actingweb/trust.py`: `is_valid_peer_id`, the origin gate, side-store deletes
- `actingweb/actor.py`: raise on a failed local delete; side-store deletes removed
- `actingweb/oauth2_server/client_registry.py`: ownership compares `actor_id`; the guard without an index row; actor-deletion index check
- `actingweb/interface/trust_manager.py`: clears stale permissions on a new row
- `actingweb/deletion_finish.py`: comment
- `tests/test_client_connection_deletion.py`:
  - peer-created rows name no client
  - `test_a_peer_cannot_take_an_oauth2_peer_id`
  - ownership compares `actor_id`
  - the guard without an index row
  - actor deletion keeps a foreign index row
  - a fixture for the side stores
- `tests/test_trust_core.py`: the same side-store fixture
- `tests/test_cross_site_and_peer_inputs.py`: an OAuth2 id is no longer a valid peer id
- `CHANGELOG.rst`

**Rationale**: the D1 fix had to hold against the protocol's
unauthenticated trust request as well as against signed-in users.
