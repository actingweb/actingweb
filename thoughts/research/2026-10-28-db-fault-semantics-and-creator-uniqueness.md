# Research: DB-layer fault semantics and creator uniqueness (the root causes behind the 3.16 adoption findings)

**Date:** 2026-10-28
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the 3.16 adoption work is uncommitted in the tree this describes)

Requested by the owner on 2026-10-28, as its own plan and PR in the same major
release as `thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md`.

Inputs:
- `thoughts/todo/db-layer-get-bucket-or-empty.md`;
- `thoughts/todo/dynamodb-known-next.md` §2 (the `consistent_read` audit);
- `thoughts/todo/creator-uniqueness-not-enforced.md`;
- verifications `…-3.md` (BR, BS, BU), `2026-10-28-….md` (AX, AY, AZ) and
  `…-2.md` (BJ, BO);
- `thoughts/todo/adoption-fault-and-hygiene-followups.md`.

## Research Questions

1. **Which DynamoDB backend methods answer a fault like a real answer?** 20
   methods, plus five deletes that report True without confirming a row
   (§1.1).
2. **Which PostgreSQL methods do, and where do the backends and
   `protocols.py` disagree?** 30 PostgreSQL methods; 16 divergence points,
   including four where the protocol's own text matches neither backend
   (§1.2, §1.3).
3. **Which workarounds exist, and which callers act on a folded answer?** The
   primitives sit in the token, adoption and deletion paths only. 11
   destructive or creating callers sit outside them, B1-B11 (§2).
4. **How is `creator` stored, cased and indexed?** A plain string with a
   non-unique index on both backends. It is lowercased only when it contains
   `@`. `trustee` and `creator` are legitimately shared by many actors (§3).
5. **Every creation and creator-change path, and how `unique_creator`
   behaves:** 14 creation paths and 6 change paths. `unique_creator` defaults
   off. With it on, a matching passphrase answers with the existing actor
   (§3.3-§3.5).
6. **Duplicate detection and consumer reliance:** no tool finds duplicates.
   Both consumers turn `unique_creator` on, and one consumer script bypasses
   it (§4).
7. **External patterns:** a marker item in `TransactWriteItems` on DynamoDB,
   and a unique expression index on PostgreSQL. Both need existing duplicates
   resolved first (§5).
8. **Which 3.16 adoption workarounds depend on which root cause:** §6.

## Summary

**Faults.** Neither backend has one fault contract. PostgreSQL catches
nearly everything and answers `None`, `[]`, `{}` or `False`. DynamoDB
catches single-row reads (`get`, `get_attr`, trust, peer-trustee and
subscription `get`), lets list reads raise, and answers `True` for deletes
it never confirms.

PynamoDB's `query()`/`scan()` are lazy, so `try` blocks around the call
catch nothing, and `if handle:` on a result iterator is always true
(`.venv/…/pynamodb/models.py:685-692`, `pagination.py:101-119`).

The protocol docstrings promise `False on error` in places neither backend
honours. The workarounds the 3.16 adoption work added (`strict=`, `.loaded`,
`set_confirmed`, `delete_confirmed`, `get_attr_strict`, `classify_marker`)
cover the adoption, token and deletion paths. Outside them, the sweep found
11 callers that create, overwrite or delete on a folded answer. Examples:
- an OAuth trust's secret is regenerated when its row read faults;
- a trust's permission override is replaced by a partial one;
- a second actor is created for an address that already has one;
- callback queues are overwritten.

**Uniqueness.** Neither backend enforces one actor per creator.
- DynamoDB keys the actor table on `id` alone, with an eventually
  consistent `creator-index` GSI.
- PostgreSQL has `ix_actors_creator` (`unique=False`) and compares
  case-sensitively.
- Lowercasing happens in application code, and only for values with `@`.
- Two fixed creators are shared by design:
  - `trustee`, set on every actor a remote trustee creates and on the
    protocol's handoff;
  - `creator` (`DEFAULT_CREATOR`), on every factory call without a creator.
- The system actors use `system` and `oauth2-system`, one each per
  deployment.

`unique_creator` is off by default and is a check-then-insert. With it on,
a create whose passphrase matches an existing actor's returns that actor
(`actor.py:446-452`), and the factory then answers 201 with the existing
id.

Both consumer apps (`../actingweb_mcp`, `examples/demo`) enable it. No tool
reports duplicates. `actingweb_mcp/scripts/restore_actor.py:1749-1753`
creates through `DbActor` directly, bypassing the check.

**What this means for 3.16's workarounds.** Most of the adoption scaffolding
exists because of these two causes:
- the candidate ranking, the factory-sibling sweep and `SWEEP_LIMIT`, the
  successor step's guesswork and `_creator_rows` exist because duplicates
  can exist;
- the strict kwargs, the `loaded` checks and `classify_marker`'s
  `None` exist because faults fold.

§6 maps each workaround to its cause. Enforced uniqueness lets the
duplicate-handling code go. Strict reads at the DB layer reduce, but do not
remove, the per-call fault checks: they move from callers into the backend
contract.

## Detailed Findings

### 1. Fault folding in the DB layer

#### 1.1 DynamoDB (`actingweb/db/dynamodb/`)

Methods where a fault returns the same value as a real answer:

| # | Method | Fault answer | Real answer it matches |
|---|---|---|---|
| 1 | `DbActor.get` `actor.py:56` | `None` (caught `:64-80`, logged ERROR) | absent |
| 2 | `DbActor.get_by_creator`, non-strict `:121` | `None` element | row deleted since the GSI listed it |
| 3 | `DbActor.create` `:163` | pre-check reads as absent | absent. The conditional put `:170` still blocks an overwrite |
| 4 | `DbAttribute.get_attr` `attribute.py:116` | `None` | absent |
| 5-6 | `set_attr(data=falsy)` / `delete_attr` `:189-191, :217` | `True` without deleting | deleted |
| 7 | `delete_attr_conditional` `:241, :249` | `False` | absent or lost race |
| 8 | `conditional_update_attr` `:337` | `False` | mismatch or absent |
| 9 | `DbProperty.get_actor_id_from_property`, lookup mode `property.py:255-303` | `None` | no actor |
| 10-12 | `DbProperty.set` `:413`, `delete` `:489`, `DbPropertyList.delete` `:837` | `True` with the lookup-row sync failed | success |
| 13-16 | `DbPropertyLookup.get` `property_lookup.py:137`, `get_v1` `:155`, `create` `:213/219`, `delete` `:240/249/259` | `None` / `False` | absent / collision / absent |
| 17 | `DbPeerTrustee.get` `peertrustee.py:67-68` | `None` | absent |
| 18 | `DbSubscription.get` `subscription.py:72-74` | `None` | absent |
| 19 | `DbSubscription.create` `:127, :145` | pre-check fault, then an unconditional `save()`, then `True` | created |
| 20 | `DbTrust.get` `trust.py:141-142` (both paths) | `None` | absent |

Two related findings:
- **Deletes that never confirm a row:** `DbActor.delete`, `DbPeerTrustee`,
  `DbSubscription`, `DbSubscriptionDiff` and `DbTrust` `delete` answer
  `True` after an unconditional DeleteItem.
- **`except` blocks that catch nothing:** `get_bucket` `attribute.py:97`,
  `delete_bucket` `:361` and the `DbAttributeBucketList` methods
  `:477/496/511` wrap only the lazy `query()`, so iteration faults raise.

Reads without `consistent_read`:
- `DbAttributeBucketList.*`;
- `DbPropertyList` reads (`:773`, `:785`, `:805`);
- `DbActorList.fetch` `actor.py:204`;
- all of `subscription_suspension.py`;
- GSI reads, which cannot be consistent.

`DbPeerTrusteeList` became consistent in this release (entry 49).

#### 1.2 PostgreSQL (`actingweb/db/postgresql/`)

Every method opens `get_connection()` inside its `try`, so pool timeouts and
SQL errors reach `except Exception`. The only exceptions are
`get_attr_strict` (`attribute.py:288`, no `try`), `delete_by_chain` (raises
`:709-713`), and the `DbProperty` range and conditional methods, which raise
`DbError`.

**30 methods answer a fault like a real answer:**
- `DbActor.get` `:57`, `get_by_creator` non-strict `:112`, `create`
  `:147/170`, `modify` `:230/234`;
- `DbActorList.fetch` `:316/319`;
- `get_attr` `:285`, `delete_attr_conditional` `:508`,
  `conditional_update_attr` `:588`, `delete_expired` `:662`;
- `DbAttributeBucketList.fetch` `:779`, `fetch_timestamps` `:825`;
- `get_actor_id_from_property` (four sites);
- the empty-value branch of `DbProperty.set` `:302-303`;
- `fetch_all_including_lists` `:908`;
- `DbPropertyLookup.get` `:59`, `create` `:137`;
- `DbPeerTrustee.get` `:113`, and `DbPeerTrusteeList.fetch` non-strict;
- `DbSubscription.get` `:88`, `create` `:174`, and `DbSubscriptionList.fetch`
  non-strict;
- `DbSubscriptionDiff.get` `:127`, `DbSubscriptionDiffList.fetch` `:311`;
- `DbTrust.get` `:182`, `is_token_in_db` `:657`, and `DbTrustList.fetch`
  non-strict;
- suspension `is_suspended` `:44`, `suspend` `:97`, `resume` `:123` and
  `get_all_suspended` `:145`.

Writes without a row-count check answer `True` for zero rows, while a fault
answers `False`. That covers `DbActor.delete` and the attribute, property,
peer-trustee, subscription, trust and diff `delete`/`modify` methods.
`DbActor.modify` checks `rowcount != 1` (`:225`), and the conditional
attribute ops check too.

`DbProperty.set` (`:372-373`, `:393-399`) and `DbPropertyList.delete`
(`:963-966`) catch an error inside a transaction and then commit. Per the
comment at `attribute.py:65-69`, that commit silently rolls back while the
method returns True. This was not verified at runtime.

#### 1.3 Contract divergence (`actingweb/db/protocols.py`)

The backends disagree on:
- non-strict `get_by_creator` (PG `None`/`None`, DDB `[]`/raise);
- `DbActorList.fetch` (PG `False`/`False`, DDB `[]`/raise);
- every trust, peer-trustee, subscription and diff `create`/`modify`/`delete`
  (PG `False`, DDB raises);
- the `delete_attr` delete branch (PG `False`, DDB `True`);
- `DbPropertyList.fetch` and `fetch_all_including_lists`;
- `DbSubscriptionDiff.get` (DDB raises `DoesNotExist` for an absent row when
  `seqnr` is given);
- suspension, and `delete_expired`.

Where the protocol's text matches neither backend:
- `DbPeerTrustee.get` "False on error" (P:746);
- `fetch_timestamps` "False on error" (P:1295);
- `DbTrust.create`, which lacks three kwargs both backends accept;
- `DbPropertyLookup.delete`, whose signature differs between the backends.

`get_bucket` (P:1050-1056) is the one method whose docstring already states
the DynamoDB/PostgreSQL difference.

### 2. Workarounds, and callers that act on a folded answer

#### 2.1 The primitives that exist

| Primitive | Definition | Semantics |
|---|---|---|
| `strict=` | `protocols.py:37-53, 693-708, 798-811, 910-925`; PG raises in `except`; DDB is a no-op except `get_by_creator` | raise instead of an empty answer |
| `Attributes.loaded` / `InternalStore.loaded` | `attribute.py:184-193, 43-52` | the bucket read was answered |
| `InternalStore.set_confirmed` | `attribute.py:62-96` | write or delete, then a strict read-back |
| `get_attr_strict` | `protocols.py:1077-1096`; DDB `attribute.py:128-153`; PG `:288` | `None` only for absent or expired; raises on a fault |
| `single_use.consume_once`, `delete_confirmed`, `revoke_chain_confirmed`, `StoreFault` | `single_use.py:85, 117-284` | CAS and confirmed deletes |
| `TokenStoreUnavailable` | `oauth2_server/token_manager.py:30-44` | token-store fault |
| `ActorListUnavailable` | `maintenance/mark_actors_vouched.py:72` | actor-list fault |
| `DeletionStatus.UNKNOWN` | `deletion.py:81-94, 177-206` | tombstone read fault |
| `classify_marker` → `None` | `oauth2.py:1625-1638` | marker unreadable |

Call sites are confined to `actor.py` (create, creator change, purge),
`oauth2.py` (adoption), `oauth_session.py`, `oauth2_server/token_manager.py`,
`client_registry.py`, `oauth2_server.py`, the OAuth handlers, `mcp.py`'s
`_race_winner`, `oauth_email.py`, `deletion.py` and `mark_actors_vouched.py`.

#### 2.2 Callers outside the workarounds that create, overwrite or delete on a folded answer

| # | Site | Folded read | What it does next | Backends |
|---|---|---|---|---|
| B1 | `interface/trust_manager.py:476` `create_or_update_oauth_trust` | `Trust.get()` → `None` | new secret, `remote_approved=False`, upsert over the row (PG `ON CONFLICT … DO UPDATE` `trust.py:287-307`; DDB unconditional `save()` `:402-403`) | both |
| B2 | `handlers/trust.py:756-775, 1113-1131` | `get_permissions` → `None` (`trust_permissions.py:493`) | builds a partial override and overwrites the stored one, plus a peer notification | both |
| B3 | `trust_permissions.py:495-499` | same | caches "no override" process-wide; `permission_evaluator.py:442-447` falls back to the base permissions | both |
| B4 | `actor.py:419-427` (`unique_creator`) | `get_by_creator` → `None` | inserts a duplicate | PG |
| B5 | `actor.py:338-340` `get_from_creator` → `oauth2.py:1024→1046`, `oauth_email.py:469`, `factory.py:260` | `get_by_creator` → `None` | creates a new actor for an address that has one | PG (DDB per-row fault) |
| B6 | `actor.py:854-956` `get_peer_trustee` | `PeerTrustee.get()` → `None` | POSTs to the peer factory, creates a peer-trustee row and a reciprocal trust | both |
| B7 | `callback_processor.py:216-250, 132-204, 112-113` | `get_attr` → `None` | overwrites the pending queue and the state; treats every sequence as a gap | both |
| B8 | `actor.py:700-716` `Actor.delete` | `trusts.fetch()` → `[]` | deletes the actor without notifying peers; per-peer side stores and diffs orphaned | PG |
| B9 | `actor.py:2063-2113` `delete_subscription` | `get_subscriptions` → `[]` | deletes the whole `RemotePeerStore` bucket | PG |
| B10 | `handlers/callbacks.py:242-266` | `get_permissions` → `None` | treats it as initial: skips revocation cleanup, syncs everything | both |
| B11 | `fanout.py:256, 285` | `get_bucket`/`get_attr` | resets an open circuit breaker and persists it | both |

Non-destructive effects of the same fold (orphans, skipped work, empty
summaries):
- `callback_processor.py:547`;
- `handlers/callbacks.py:1015`;
- `actor.py:1610-1629`, `3048-3052`, `2559-2561`;
- `client_registry.py:617`;
- the `actor_adopted` summaries `oauth2.py:2076-2077, 2165-2168`;
- `migrate_property_lists.py:192`;
- expiry cleanup in `oauth_session.py:409-412`.

Callers that fail closed:
- `auth.py:259-279` and `auth.py:229-231`;
- `mcp.py:2505`, `mcp.py:2426-2462`;
- `oauth_email.py:203-208`;
- `handlers/trust.py:484-490`.

Not traced:
- how `get_actor_id_from_property` feeds `Actor.get_from_property`
  (`actor.py:298-306`);
- the subscription read behind `_get_last_seq`.

### 3. Creator: storage, casing, paths

#### 3.1 Storage and index

- **DynamoDB:** `actors` is hash-keyed on `id` only (`db/dynamodb/actor.py:39-47`).
  - `CreatorIndex` (`creator-index`, `AllProjection`, hash `creator`, `:21-30`)
    is eventually consistent.
  - `create` conditions on `Actor.id.does_not_exist()` (`:170`), not on the
    creator.
  - Tables are created from the model by `ensure_table` (`_ensure.py:73-107`).
- **PostgreSQL:** `actors(id PK, creator varchar(255) NOT NULL, passphrase,
  created_at)`, with `ix_actors_creator` `unique=False`
  (`migrations/versions/3307e3616c5e_initial_postgresql_schema.py:25-33`,
  `schema.py:39-42`). No later migration touches it. Queries use
  `WHERE creator = %s`, which is case-sensitive (`postgresql/actor.py:86-90`).

#### 3.2 Casing

Every backend `create`/`modify`/`get_by_creator` lowercases only when `"@"`
is in the value:
- DDB `:132-136, 156-160, 106-107`;
- PG `:77-79, 134-139, 197-200`.

`Actor.create` keeps the raw value in memory (`actor.py:415-418`).

Sources that already lowercase:
- provider emails (`oauth2.py:886-896`);
- the email form (`oauth_email.py:411`);
- the factory (`factory.py:253-256`);
- `github:{login}` (`oauth2.py:339`).

Sources that do not:
- `google:{sub}` (`oauth2.py:267`);
- `github:{id}` (`:332`);
- `apple:{sub}` (`:464`).

Auth compares in different ways:
- basic auth is exact (`auth.py:145`);
- the trustee check is `creator.lower() == "trustee"` (`auth.py:239, 563`),
  so `Trustee` and `trustee` are different stored keys but the same to
  auth.

#### 3.3 Creation paths

Everything ends in `Actor.create` (`actor.py:387-550`). Creator per path, and
whether the id is generated:
- **Factory:** the body's creator, or `"creator"` when empty; generated id;
  marker `factory`.
- **`ActorInterface.create`:** the caller's creator, raw; the id may be
  caller-supplied; marker `app` by default.
- **`_create_actor_for_identifier`:** used by every OAuth, SPA, native,
  email-form, MCP-server and bearer path; generated id.
- **Adoption successor:** the stored creator; generated id.
- **MCP bridge:** the token's email, or `oauth2-user-{id}@unknown.domain`;
  caller-supplied id (`mcp.py:2438-2450`).
- **System actors:** `oauth2-system` (`_actingweb_oauth2`) and `system`
  (`_actingweb_system`), with fixed ids (`system_actor.py:60-66`,
  `trust_type_registry.py:126-132`).
- **Remote trustee:** POSTs `creator: "trustee"` to the peer's factory
  (`actor.py:878-891`).

#### 3.4 Creator-change paths

- `Actor.modify(creator=)` `actor.py:645-672`.
- The `force_email_prop_as_creator` rewrite on every `Actor.get` (`:277-280`).
- The `unique_creator` branch's `DEFAULT_CREATOR` rewrite (`:436-445`).
- `modify_creator_unvouched` (`:571-643`).
- `PUT /<id>/trust/trustee` (`handlers/trust.py:221-293`).
- `ActorInterface.modify_creator` (`interface/actor_interface.py:394-415`).

Adoption never changes a creator.

#### 3.5 `unique_creator`

Defaults:
- `Config.unique_creator = False` (`config.py:83`), and `ActingWebApp`
  `False` (`app.py:70`), set through `with_unique_creator()`.
- `force_email_prop_as_creator` is `True` on a bare `Config` (`config.py:89`)
  but `False` on `ActingWebApp` (`app.py:71`).

What `Actor.create` does with it on (`:419-453`):
- it lists by creator and drops None rows;
- with `delete=True` (only `ActorInterface.create(delete_existing=True)`, no
  in-tree caller) it deletes every match;
- otherwise it rewrites `DEFAULT_CREATOR` actors from their stored email,
  then returns **True bound to an existing actor whose passphrase matches**
  (`:446-452`), skipping the marker write, the tombstone clear and
  `actor_created`;
- otherwise it returns False, and the factory answers 403 "Creator already
  exists" (`factory.py:281-299`), or 201 with the existing actor on a
  passphrase match.

The check is read-then-insert, and nothing in the database backs it.

#### 3.6 Creators that are shared on purpose

- **`trustee`:** every actor a remote trustee creates (`actor.py:878-891`)
  and the handoff through `PUT /trust/trustee`. Auth treats it per actor
  together with `trustee_root` (`auth.py:229-252, 560-570`). Under
  `unique_creator` the second one gets a 403, because its empty passphrase
  never matches (`actor.py:454-457`).
- **`creator` (`DEFAULT_CREATOR`):** every factory call without a creator.
  The code at `actor.py:428-445` exists because many actors carry it.
- **`system` / `oauth2-system`:** one each per deployment, shared only if
  several apps share a table.
- **The MCP fallback** `oauth2-user-{id}@unknown.domain` is unique per actor.

### 4. Tooling and consumers

- **No tool finds duplicate creators.**
  - `mark_actors_vouched --creator` only filters.
  - `verify_orphans` reads ids only.
  - `get_actor_list().fetch()` is unpaginated: a DynamoDB full scan without
    `consistent_read` (`db/dynamodb/actor.py:198`), PostgreSQL
    `SELECT id, creator` (`db/postgresql/actor.py:286`).
  - The only signal is the WARNING in `get_from_creator` (`actor.py:355-359`).
- **`../actingweb_mcp`** pins `actingweb==3.15.1` (`pyproject.toml:11`) and
  enables `with_unique_creator(True)` and `with_email_as_creator(True)`
  (`application.py:561-562`). Its lookups (`api/auth_demo.py:174`,
  `api/oauth_password.py:283`) only test truthiness.
  `scripts/restore_actor.py:1749-1753` creates through `DbActor` with a
  snapshot's id and creator, bypassing the check.
  `scripts/manage_actors.py` and `verify_integrity.py` scan actors with
  boto3, without a duplicate check.
- **`examples/demo`** (deployed by `../actingwebdemo`, which vendors
  actingweb at 3.15.1) enables both flags (`examples/demo/application.py:78-83`)
  and has a boto3 "nuke" scan (`:206-249`).

### 5. External patterns

#### 5.1 DynamoDB: a unique constraint on a non-key attribute

Sources:
- [AWS, "Simulating Amazon DynamoDB unique constraints using transactions"](https://aws.amazon.com/blogs/database/simulating-amazon-dynamodb-unique-constraints-using-transactions/);
- [advancedweb.hu](https://advancedweb.hu/how-to-properly-implement-unique-constraints-in-dynamodb/);
- [TransactWriteItems](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html),
  [how transactions work](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html).

The pattern is a marker item (`CREATOR#<normalised>`) put with
`attribute_not_exists` in the same `TransactWriteItems` as the actor.
- **Change:** update the actor (conditioned on the old value), delete the old
  marker and put the new one, all in one transaction.
- **Delete:** both items in one transaction.
- **Costs and limits:**
  - each item costs 2× WCU, and a cancelled transaction is billed too;
  - at most 100 items, same Region;
  - no transactions on a GSI;
  - one action per item.
- **Errors:** `CancellationReasons` is indexed per item.
  `ConditionalCheckFailed` on the marker is the duplicate.
  `TransactionConflict` and the throttle codes are retryable.
- **The SDK does not retry `TransactionCanceledException`.**
- **Idempotency:** `ClientRequestToken` lasts 10 minutes.
- **The marker can live in the actor table or a separate one.** A separate
  table keeps markers out of actor scans.
- **Every write path must maintain the marker.**
- **DynamoDB Local** never raises `TransactionConflict`, so the conflict
  branch needs a mock.
- **PynamoDB:** `pynamodb.transactions.TransactWrite` (since 4.0) raises
  `TransactWriteError` with `cancellation_reasons` (since 5.4). Its
  `Connection` is separate from the models' `Meta`; it must be given the same
  host and region (6.0 removed the default region).

#### 5.2 PostgreSQL

Sources: [CREATE INDEX](https://www.postgresql.org/docs/current/sql-createindex.html),
[INSERT](https://www.postgresql.org/docs/current/sql-insert.html),
[ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html),
[Alembic autocommit_block](https://alembic.sqlalchemy.org/en/latest/api/runtime.html).

- `CREATE UNIQUE INDEX … ((lower(creator)))` fails over existing
  duplicates.
- An expression or partial index cannot become a `UNIQUE` constraint, and
  `NOT VALID` does not exist for uniqueness, so duplicates must be resolved
  first.
- A `WHERE` clause can exempt values (`trustee`, `creator`).
- `CONCURRENTLY` must run outside a transaction, which in Alembic means an
  `autocommit_block()`, and is best kept in its own migration. A failed
  concurrent build leaves an INVALID index that still enforces uniqueness.
- `ON CONFLICT ((lower(creator))) [WHERE …]` must repeat the index's
  expression and predicate.
- `citext` and nondeterministic collations are alternatives, but they change
  the column type or the query semantics.

#### 5.3 Rollout practice

[GitLab, deduplicating records](https://docs.gitlab.com/development/database/deduplicate_database_records)
uses three steps:
1. stop new duplicates;
2. resolve the existing ones;
3. enforce.

Each step runs on its own, because a duplicate created between cleanup and
enforcement fails the index build.

### 6. What each 3.16 adoption workaround depends on

| Workaround (current tree) | Exists because of | What changes under each fix |
|---|---|---|
| `Actor._candidate_rank`, the ranking in `get_from_creator` (`actor.py:305-385`) | duplicates | goes away with uniqueness (one candidate); faults also make it fail open (BR) |
| `Actor.factory_sibling_ids`, the vouched-branch sweep (`oauth2.py` vouched branch) | duplicates | goes away with uniqueness |
| `_factory_siblings`, `_sweep_factory_actors`, `SWEEP_LIMIT` | duplicates | go away with uniqueness |
| `_creator_rows`, the strict `get_by_creator`, the successor step's "remaining" logic and recursive hand-off, `carried` | duplicates, plus faults | with uniqueness a replacement deletes one actor and creates its successor under the same marker (a transactional swap or delete-then-create); the hand-off cases cannot arise |
| The factory's existing-creator redirect and 403 (`factory.py:258-299`) | duplicates | become the creation path's own uniqueness answer |
| `unique_creator`'s check-then-insert and passphrase match (`actor.py:419-453`) | duplicates | replaced by the database constraint; the passphrase-match "return existing" needs a decision (Decision 4) |
| `strict=` on list fetches, `get_by_creator(strict)`, peer-trustee `strict` | faults | become the default contract if the DB layer raises |
| `InternalStore.loaded` checks in adoption, `classify_marker`'s `None`, `_actor_client_ids`'s `loaded` raise | faults | stay as fail-closed points, or become exceptions from the store |
| `set_confirmed` / `delete_confirmed` / `get_attr_strict` | writes report success unconfirmed (DDB `delete_attr` `True`, PG zero-row `True`) | stay unless writes confirm themselves (row counts on PG, `ReturnValues`/conditions on DDB) |
| The tombstone checks in the replace path | faults (UNKNOWN), and stalled wipes | unchanged |

The 3.16 known limitation "two concurrent first sign-ins may both run the
rule" (CHANGELOG) and `thoughts/todo/creator-uniqueness-not-enforced.md`
also close with uniqueness.

## Decisions Needed

### Decision 1: What contract should the DB layer give for a fault?

**Options:**
1. **Raise on every fault, everywhere.** One `DbFault` exception, absence as
   `None`/`[]`/`False`, both backends, and the protocol rewritten to match.
   - Pros: one meaning, and the per-call strict kwargs go away.
   - Cons: touches about 50 methods on two backends, and every caller that
     relied on folding (§2.2 shows many) now raises into handlers. That is a
     large behaviour change for consumers and custom backends.
2. **Strict by default only on the reads that drive decisions:**
   single-row `get` for actor, trust, peer-trustee, subscription and
   attribute, plus the list fetches, plus `get_by_creator`. Writes report
   confirmed results. `strict=False` stays for display callers.
   - Pros: fixes B1-B11 at the source, a smaller blast radius, and the
     existing `strict` pattern is reused.
   - Cons: two modes stay in the contract.
3. **Leave the backends, fix the 11 callers** with the existing primitives.
   - Pros: the smallest diff.
   - Cons: the same per-call pattern that produced six verification rounds,
     and new callers repeat the mistake.

**Recommendation:** none; the evidence favours 2 over 3, while 1 versus 2
is a release-scope call.

### Decision 2: Which of B1-B11 must this release fix?

Destructive on both backends: B1 (trust secret regenerated), B2 (override
replaced), B6 (duplicate peer trustee and a network create), B7 (callback
queue) and B11 (circuit breaker). B4, B5, B8 and B9 fold on PostgreSQL. B3
and B10 are authorization and cleanup effects without a write. The owner
chooses all of them or a subset; the rest go to a todo.

### Decision 3: Unconditional or opt-in uniqueness, and which creators are exempt?

**Options:**
1. **Unconditional**, in the major release.
   - Pros: the 3.16 duplicate handling goes away for everyone.
   - Cons: every deployment with duplicates must resolve them before
     upgrading. The `trustee` and `creator` sharing (§3.6) needs exemptions
     or a different creator value.
2. **Opt-in** (`with_unique_creator()` becomes enforcing).
   - Pros: no forced migration. Both known consumers already enable it.
   - Cons: the duplicate-handling code stays for the default (off), so most
     of §6 cannot be deleted.
3. **Default on, with an opt-out**.
   - Same pros as 1 for new deployments; an operator escape hatch.
   - The code paths for off stay.

Exemptions to decide:
- `trustee` (shared by design);
- `creator` (an empty factory creator; alternatively give each such actor a
  unique placeholder);
- `system` / `oauth2-system` (one each, so no exemption needed);
- provider-id case (`google:{sub}` is case-sensitive today: normalise or
  not).

### Decision 4: What does a create for an existing creator do?

Today, with `unique_creator` on, a matching passphrase answers 201 with the
existing actor, and a non-matching one answers 403. Under enforcement:
- keep that (the factory as a "get or create by passphrase");
- always refuse (403/409);
- or, for OAuth paths, return the existing actor, which is what the lookup
  already does.

This interacts with the 3.16 rule that a `factory` actor is replaced at a
sign-in. With uniqueness on, a squatter's factory actor would **block** the
owner's actor from being created, unless the replacement deletes and
recreates under the same marker.

### Decision 5: The DynamoDB mechanism

**Options:**
1. **A marker item in the actor table plus `TransactWriteItems`**
   (`CREATOR#…` as `id`). No new table, but markers appear in every actor
   scan (`DbActorList.fetch`, `verify_orphans`, consumer boto3 scans such as
   `actingweb_mcp/scripts/manage_actors.py` and the demo's nuke), and each
   would need filtering.
2. **A separate `creators` table plus `TransactWriteItems`.** Clean scans; a
   new table for `ensure_table` and for operators to provision.
3. **A conditional put on a separate table without transactions**, with a
   reconciler for orphaned markers. Cheaper writes; partial states.

Costs: a create goes from 1 to about 4 WCU, a creator change to about 6.

### Decision 6: The PostgreSQL mechanism

A unique expression index on `lower(creator)` (partial, if exemptions are
chosen), in its own Alembic migration using `CONCURRENTLY` in an
`autocommit_block`. The migration must stop with a clear error when
duplicates exist. Alternatively, `citext`.

Also decide whether to normalise the stored values, for example lowercasing
provider ids, with a data migration, or only to compare case-insensitively.

### Decision 7: Migrating existing duplicates

No tool finds them today. Options:
1. A report-only tool (`actingweb-find-duplicate-creators`) for both
   backends, with the operator resolving duplicates before enforcement.
2. The same tool plus an automatic rule (keep the vouched actor, then the
   lowest id). The other actors hold user data, so external practice
   (GitLab) leaves this choice to a person.

The DynamoDB marker backfill must put markers with `attribute_not_exists`,
so that duplicates surface instead of overwriting each other. Consumer
scripts that write through `DbActor` directly (`restore_actor.py`) would
need to write markers too.

### Decision 8: Release shape and sequencing

Both parts change protocols (a custom backend must implement new strict
semantics and maintain markers), behaviour and configuration, so this is a
major release under the `### Release` rule, alongside 3.16's own work.

**Sequencing options:**
- faults first, since they are independent;
- uniqueness enforcement after the tool and a migration window.

**Whether to remove the 3.16 workarounds (§6) in the same PR or after:**
- removing them in the same PR depends on Decision 3 being unconditional;
- with opt-in uniqueness they stay.

## Code References

- `actingweb/db/dynamodb/actor.py:21-47, 56-80, 91-122, 147-176, 198-216`:
  model, GSI, get, get_by_creator, create, list fetch.
- `actingweb/db/dynamodb/attribute.py:97, 116, 128-153, 189-191, 241-250, 337`:
  folded reads, swallowed deletes, conditionals.
- `actingweb/db/postgresql/actor.py:20-57, 59-112, 114-170, 172-240, 286-319`.
- `actingweb/db/postgresql/attribute.py:65-69, 234-285, 288, 357-387, 504-588`.
- `actingweb/db/postgresql/migrations/versions/3307e3616c5e_initial_postgresql_schema.py:25-33`:
  `ix_actors_creator`, not unique.
- `actingweb/db/protocols.py:37-53, 693-708, 746, 798-811, 910-925, 1050-1056, 1077-1096, 1295`.
- `actingweb/actor.py:277-280, 305-385, 387-550, 645-672, 700-716, 854-956, 2063-2113`.
- `actingweb/oauth2.py:1625-1638, 1801-1936, 1958-2235`: classifier, sweep,
  adoption.
- `actingweb/interface/trust_manager.py:476-609` (B1);
  `actingweb/handlers/trust.py:756-775, 1113-1131` (B2);
  `actingweb/trust_permissions.py:493-499` (B2, B3);
  `actingweb/callback_processor.py:112-250, 547` (B7);
  `actingweb/fanout.py:237-308` (B11);
  `actingweb/handlers/callbacks.py:242-284, 1015` (B10).
- `actingweb/handlers/factory.py:234-299`; `actingweb/config.py:83, 89`;
  `actingweb/interface/app.py:70-71, 517-527, 1355-1356`.
- `actingweb/constants.py:74, 76, 95, 98`: `DEFAULT_CREATOR`,
  `TRUSTEE_CREATOR`, the system actor ids.
- `../actingweb_mcp/application.py:561-562`;
  `../actingweb_mcp/scripts/restore_actor.py:1749-1753`;
  `examples/demo/application.py:78-83`.

## External References

- https://aws.amazon.com/blogs/database/simulating-amazon-dynamodb-unique-constraints-using-transactions/:
  the marker-item pattern.
- https://advancedweb.hu/how-to-properly-implement-unique-constraints-in-dynamodb/:
  the update and delete conditions, and a separate table.
- https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html:
  limits, `CancellationReasons`, `ClientRequestToken`.
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html:
  cost (2×) and isolation.
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.UsageNotes.html:
  no `TransactionConflict` locally.
- https://pynamodb.readthedocs.io/en/stable/transaction.html: `TransactWrite`
  and `TransactWriteError`.
- https://www.postgresql.org/docs/current/sql-createindex.html: unique,
  expression, partial and `CONCURRENTLY`; an invalid index still enforces.
- https://www.postgresql.org/docs/current/sql-insert.html: the
  `ON CONFLICT` expression target.
- https://alembic.sqlalchemy.org/en/latest/api/runtime.html: `autocommit_block`.
- https://docs.gitlab.com/development/database/deduplicate_database_records:
  the staged dedup-then-enforce rollout.
