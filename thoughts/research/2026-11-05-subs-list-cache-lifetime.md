# Research: `subs_list` and the lifetime of the MCP actor cache

**Date:** 2026-11-05
**Branch:** docs/3-16-rollup-records
**Commit:** fea9e42

Source: `thoughts/todo/subs-list-cache-asymmetry.md` (High leverage in
`thoughts/todo/INDEX.md`). The todo's own line numbers are stale; every
reference below is from the tree at fea9e42.

## Research Questions

1. **What instance-level state does a cached `Actor`/`ActorInterface` carry?**
   The actor row, the `_internal` attribute bucket, a per-key property cache
   and `subs_list`. Not the trust list: three places in the tree say it does
   and are wrong. See "What the cached object holds".
2. **Who holds an `Actor` across requests?** Only `_actor_cache` in
   `handlers/mcp.py`. See "Who holds an actor across requests".
3. **What does a rebuild cost?** One strongly consistent actor-row read per
   request if the hit path is reshaped; the full authentication path (four or
   five reads) if `_actor_cache` is only deleted, because the token and trust
   caches are read solely inside the actor-hit branch. See "Cost of a rebuild".
4. **What does the existing eviction machinery do, and what would a lifetime
   decision close in the cache-lifecycle register?** It evicts whole entries on
   revocation and guards cache fills with a generation counter; nothing resets
   an instance memo. See "Invalidation machinery" and the table under
   Decision 1.
5. **Where is `subs_list` read and written, who calls `get_subscriptions()`,
   and what does a write cost?** Seven library sites; one backend list read
   per `register_diffs()` call for a zero-subscription actor, never memoised.
   See "`subs_list` sites" and "Callers and cost".
6. **What does the fetch return on each backend, and with what consistency?**
   Always a list or a raise, on both; DynamoDB reads with
   `consistent_read=True`, PostgreSQL with one `SELECT` at the pool's default
   isolation. See "The backend fetch".
7. **Which creation and deletion paths invalidate `subs_list`?** Every creation
   path does (all go through `Actor.create_subscription`). The trust-deletion
   cascade, `Actor.delete` and `purge_relationships` populate it and never
   reset it. See "Creation and deletion paths".
8. **What has been decided before?** The guard was left alone deliberately in
   3.13 and the lifetime question was deferred three times, each time to "its
   own plan". See "Recorded decisions".
9. **What does the consumer do today?** `actingweb_mcp` reads all
   subscriptions once and buckets them by peer; it holds no actor across
   requests itself and asks nothing of the library. See "Consumer".
10. **Which docs state the behaviour?** `docs/guides/caching.rst` describes
    `_actor_cache` with example code that does not match the implementation;
    no page states the sliding TTL or that instance memos ride on it. See
    "Documentation Impact".

## Summary

`Actor.get_subscriptions()` (`actingweb/actor.py:2440-2484`) memoises on
`self.subs_list` behind `if not self.subs_list:` (`:2468`). An empty list never
sticks, so an actor with no subscriptions pays one backend list read per call,
and `register_diffs()` (`:3879`) makes that one strongly consistent DynamoDB
Query per property write. A non-empty list sticks for the life of the instance.
On REST handlers an instance lives for one request. On the MCP path it lives in
the module-global `_actor_cache` (`actingweb/handlers/mcp.py:110`) on a sliding
300-second TTL (`:117`, refreshed at `:2297` and `:2474`), so on a warm
container it can live as long as the process.

Two findings change the premise the todo and the 2026-08-15 research note were
written on. First, the cached object does **not** carry a trust list: trust is
read fresh on every call (`actor.py:1476-1484`), and the statement that it
"comes along" is repeated in `handlers/mcp.py:376-382`, `trust.py:250-252` and
`tests/test_mcp_revocation_evicts_caches.py:79-82`. What the cached object does
carry, and no earlier note names, is the whole `_internal` attribute bucket
(`attribute.py:35-48`, never re-read once loaded) and a per-key property cache
that also caches `None` (`property.py:357-365`). `subs_list` is one of four
stale-able memos, not the only one. Second, `_actor_cache` is structurally the
gate for the other two caches: a token-cache hit is only used when the actor
cache also hits (`mcp.py:2280-2342`), and the trust cache is only read inside
that branch. Deleting `_actor_cache` without reshaping the hit path sends every
MCP request down the full path (`:2352-2419`).

The guard change itself is small but not one line: with `is None`, a folded
`[]` from the `strict=False` trust-deletion fetch (`actor.py:2087-2089`) would
stick for the instance, and the trust-deletion cascade deletes rows through
`sub_obj.delete()` without resetting the memo. Both are harmless today only
because the falsy guard refetches.

## Detailed Findings

### What the cached object holds

`Actor.__init__` (`actingweb/actor.py:113-142`) and `Actor.get()` (`:380-400`):

| Attribute | Set at | Refreshed by | Stale against another process? |
| --- | --- | --- | --- |
| `actor` (row: id, creator, passphrase), and `id`/`creator`/`passphrase` copied from it | `get()` `:389-395` | `get()` returns early while `self.actor` is truthy (`:386-387`); `modify()` patches in place (`:1046-1053`) | Yes, never re-read on a live instance |
| `store` (`InternalStore`, bucket `_internal`) | `:133`, `:396` | First access loads the whole bucket into `__dict__` (`attribute.py:35-48`); `__getattr__` then serves from `__dict__` (`:201-207`). Only `set_confirmed`/`read_strict`/`replace_if_equal`/`set_if_absent` re-read single keys (`:71-177`) | Yes: `auth_method`, the vouched creator, `email`, `trustee_root` freeze once loaded |
| `property` (core `PropertyStore`) | `:134`, `:397` | `__getattr__` caches each key read, including `None` (`property.py:357-365`); `get_all()` reads fresh (`:367-375`) | Yes, per key. `ActorInterface.properties[k]`/`.get()` read through it (`interface/property_store.py:108-110`, `:146-167`) |
| `subs_list` | `:2087`, `:2469` | Falsy guards at `:2084`, `:2468`; reset at `:2353`, `:2562`, `:2598`, `handlers/subscription.py:270` | Yes when non-empty |
| `property_lists` (core `PropertyListStore`) | `:135`, `:398` | Returns a new `ListProperty` per access (`property.py:291`) | No |
| `property_list` | `:1128`, `:1188`, `:1195` | Rebuilt by `get_properties()` | Snapshot within one call chain |
| `last_response_code`, `last_response_message` | peer HTTP calls | overwritten per call | Mutable state shared across concurrent requests |

Trust is not on the instance: `get_trust_relationship()` and
`get_trust_relationships()` construct a new `trust.Trust`/`trust.Trusts` per
call (`actor.py:1476-1484`); `TrustManager` keeps only `_core_actor` and
`_hooks` (`interface/trust_manager.py:160-162`). Trust state that outlives a
request is in `_trust_cache` (`handlers/mcp.py:116`) and
`TrustPermissionStore._cache` (`trust_permissions.py:101`).

`ActorInterface` (`interface/actor_interface.py:65-94`) holds no data of its
own: its managers wrap the core actor. `_services` caches one `ServiceClient`
per service (`interface/services/service_registry.py:146`, `:158-167`).

### Who holds an actor across requests

`_actor_cache` is the only holder in the library. `handlers/async_mcp.py:109`
calls the same `authenticate_and_get_actor_cached()`. The Flask and FastAPI
integrations build a handler per request (`flask_integration.py:1617`,
`fastapi_integration.py:2560`). No other module global or `lru_cache` holds an
`Actor`. The consumers hold none either (see "Consumer").

Two reads of the cache, with different checks:

- `mcp.py:2289-2298` (token hit, then actor hit): TTL check only. **No
  `config is self.config` check.**
- `mcp.py:2468-2475` (`_get_or_create_actor_cached`): TTL and
  `cached_data.get("config") is self.config`.

What MCP handling takes from the cached `ActorInterface`:

- Library: `actor.id` (permission evaluation, `mcp.py:1683`, `:1782`, `:1908`;
  the evaluator reads the trust row fresh, `permission_evaluator.py:606-610`),
  `actor.trust.relationships` in the resolver (`:2593`), `RuntimeContext(actor)`
  keyed by `actor.id` (`runtime_context.py:115-118`).
- Application: the whole object goes to `visibility_predicate(actor)`
  (`:1333`), `description_predicate(actor)` (`:1381`) and every tool, prompt and
  resource hook (`mcp.py:1723`, `:1826`, `:1944`; `async_mcp.py:237-239`,
  `:340-342`, `:468-470`). A property write in a hook reaches `register_diffs`
  on the cached core actor (`interface/property_store.py:95`).
- `_update_trust_with_client_info` (`mcp.py:2791`) and
  `_mark_client_peer_approved` (`:3091`) already build a fresh `Actor` for
  their writes.

### Cost of a rebuild

`Actor(actor_id, config)` does one eager read, `handle.get()`
(`actor.py:142` → `:389`): DynamoDB `Actor.get(actor_id, consistent_read=True)`
(`db/dynamodb/actor.py:121`); PostgreSQL one `SELECT id, creator, passphrase
FROM actors WHERE id = %s` (`db/postgresql/actor.py:138-146`). The stores read
nothing on construction (`attribute.py:22-25`). With
`force_email_prop_as_creator` on, `get()` also loads the `_internal` bucket
(`actor.py:401-406`); raw `Config` defaults it to True (`config.py:125`),
`ActingWebApp` to False (`interface/app.py:103`, `:205`).
`ActorInterface.__init__` reads nothing.

| Path | Storage reads per MCP request |
| --- | --- |
| Today, all three caches hit (`mcp.py:2280-2342`) | 0 |
| Today, trust miss on the hit path | 1 trust Query (`db/dynamodb/trust.py:492`, consistent) |
| Today, full path (`:2352-2419`) | 2 token point reads (`oauth2_server/token_manager.py:1254-1261`) + 1 actor read + 1 trust Query; the resolver runs unconditionally (`:2391`) and never reads `_trust_cache` |
| `_actor_cache` deleted, hit path unchanged | The full path on every request: a token hit with no actor entry falls through (`:2343-2350`) |
| Hit path reshaped: token hit → `Actor()` → trust-cache lookup | +1 actor read per request (+1 bucket Query under `force_email_prop_as_creator`) |

Hook-side: repeated `actor.properties[k]` and `actor.store.x` reads are free
across requests today; on a per-request instance each costs one point read per
key, or one bucket Query, once per request.

`AsyncMCPHandler` runs on the event loop without an executor
(`fastapi_integration.py:2557-2577`), so a synchronous `Actor()` read there
runs on the loop. The full path already does this on every miss today.

### Invalidation machinery

| Mechanism | Trigger | Clears |
| --- | --- | --- |
| `evict_mcp_caches_for_actor` (`mcp.py:367-413`) | `mcp/invalidation.evict_caches_for_actor`, from `Trust.delete` (`trust.py:254-256`), `TrustPermissionStore` (`trust_permissions.py:158-160`, `:581-583`), `oauth_session.py:921`, `:1015`, `:1097`, `:1177`, `token_manager.py:652`, `:674`, `:874`, `:1789` | The actor's `_token_cache` entries, its `_actor_cache` entry, all its `_trust_cache` tuples; always bumps the generation (`:409`) |
| `clear_token_from_cache` (`mcp.py:2988-3039`) | logout (`handlers/oauth2_endpoints.py:982`), token eviction (`token_manager.py:439-446`) | `actor_wide=False`: one token. Otherwise resolves the actor and calls the above |
| Generation counter (`:298-310`, `_cache_fill_still_valid` `:360-364`) | snapshot at `:2361-2362` | Refuses the token, actor and trust fills when an eviction landed during the read. Touches no existing entry |
| Cleanup loop (`mcp.py:782-815`) | at most every 20 s, at the start of authentication (`:2265-2269`) | Expired tokens, expired actor entries, **and every trust tuple of each expired actor** (`:808-810`) |

None of these resets an instance memo; a memo goes away only when the wrapper
is evicted. Eviction fires on revocation, and a subscription created in another
process revokes nothing.

Positive `_trust_cache` entries have no TTL of their own
(`_TRUST_CACHE_TTL = None`, `mcp.py:122`); negative ones expire after 10 s
(`:129`). The only time bound on a positive trust entry today is the
actor-expiry sweep at `:808-810`, which is keyed on `_actor_cache`.

Request-boundary hooks exist in both integrations
(`flask_integration.py:128-186`, `fastapi_integration.py:559-568`) but neither
has the actor in hand: the MCP actor id comes from the token, and the FastAPI
comment at `:561-566` notes that ContextVars set inside the handler are gone
when the middleware runs. The one place holding the cached object at a request
boundary is the hit-path return (`mcp.py:2297-2342`, `:2474-2475`).
`runtime_context.py:15-18` and `:29-34` record why request state cannot live on
the cached actor: it leaks "between requests and, under concurrency, between
callers". A reset on the shared wrapper would run while other threads or tasks
use it, for example between the guard at `actor.py:2468` and the loop at
`:2473-2474`.

### `subs_list` sites

- `actor.py:116` — initialised to `None`.
- `actor.py:2084-2092` (`delete_reciprocal_trust`, inside `for rel in rels`
  from `:2026`) — `if not self.subs_list:` then `.fetch(strict=False)`; deletes
  each matching row with `sub_obj.delete()`. Never resets the memo.
- `actor.py:2353` (`create_subscription`) — reset to `None`.
- `actor.py:2468-2474` (`get_subscriptions`) — the falsy guard and the filter.
- `actor.py:2562`, `:2598` (`delete_subscription`) — reset before the re-read
  and after the delete.
- `handlers/subscription.py:270` — hand reset after
  `create_local_subscription()`, which has already reset through
  `create_subscription`.
- `handlers/mcp.py:378` — docstring only.

Tests: `tests/test_actor.py:138` (`hasattr`),
`tests/test_subscription_suspension.py:485-519` (reset after create),
`tests/test_db_fault_sixth_pass.py:46` (clears it to force the faulted read).

### Callers and cost

Filters never reach the backend: every `get_subscriptions()` call does the same
unfiltered fetch (`actor.py:2469-2471`) and filters in Python (`:2473-2484`).
`strict` defaults to True (`:2448`).

Direct callers: `delete_subscription` (`:2565`), `resume_subscriptions`
(`:3062`), `_send_resync_callbacks` (`:3144`, only when `subs is None`),
`register_diffs` (`:3879`).

Interface accessors (`interface/subscription_manager.py`), one
`get_subscriptions` call each, none passing `strict=`: `all_subscriptions`
(`:205`), `outbound_subscriptions` (`:213`) and `inbound_subscriptions`
(`:221`) through it, `get_subscriptions_to_peer` (`:228`,
`peerid=…, callback=True`), `get_subscriptions_from_peer` (`:240`, through
`inbound_subscriptions`, filtered by peer in Python),
`get_subscriptions_for_target` (`:251`). The library has two per-peer
accessors and no peer-indexed bulk accessor; `SubscriptionInfo.is_outbound` is
at `:64-71`. No library handler calls an accessor in a loop over peers
(`handlers/subscription.py:39-49`, `:168-179`: one or two calls per request).

`register_diffs()` (`actor.py:3856-4076`) fetches first and returns on an empty
list (`:3879-3883`), before the suspension check (`:3886`). Call sites: twelve
in `handlers/properties.py` (one per request, except DELETE-all at
`:1769-1770`, which costs one per key plus two), `handlers/www.py:479`, `:496`,
`interface/property_store.py:95` (`__setitem__`, `__delitem__`; `update()` one
per key at `:202-205`; `clear()` one per key plus one at `:215`), `:332`
(`NotifyingListProperty`, one per list mutation),
`interface/subscription_manager.py:480`.

| Actor state | Subscription list reads per `register_diffs()` |
| --- | --- |
| 0 subscriptions | 1 every time (`[]` is falsy) |
| ≥1 subscription | 1 on the first call per `Actor` instance, then 0 |

On a fault the read happens twice per call: `Subscriptions.__init__` swallows
the first `DbError` (`subscription.py:315-318`) and the caller's `.fetch()`
reads again (`:268-269`).

`CHANGELOG.rst:4333-4347` records the measured profile of a write for an actor
with no subscribers as `{GetItem: 1, PutItem: 1, Query: 1}`, and
`thoughts/research/2026-07-25-rc2-triage.md:300-301` records the `Query: 1` as
"still there by design". The consumer measured 40 subscription fetches on a
5-peer, 0-subscription actor before its workaround and 2 after
(`../actingweb_mcp/thoughts/plans/2026-08-25-spa-fanout-cost-and-latency.md:693-701`).

### The backend fetch

`subscription.Subscriptions.fetch(strict=True)` (`subscription.py:260-278`)
caches on `self.subscriptions is not None`, so it caches an empty list
correctly, on a wrapper that `get_subscriptions` discards. The wrapper's
`strict` never reaches the backend (`:269`); the fold to `[]` happens at
`:270-277` and caches nothing.

- **DynamoDB** (`db/dynamodb/subscription.py:257-297`):
  `Subscription.query(actor_id, consistent_read=True)` (`:278`), hash key `id`,
  range key `peer_sub_id` (`:31-32`). Returns a list, `[]` for none. Raises
  `DbError` when strict; otherwise logs and returns `[]` (`:270-275`).
- **PostgreSQL** (`db/postgresql/subscription.py:401-472`): one `SELECT …
  FROM subscriptions WHERE id = %s ORDER BY peer_sub_id` on a pooled connection
  (`:437-448`). Returns a list, `[]` for none; raises when strict, `[]`
  otherwise (`:468-472`). `connection.py:172-181` sets neither `autocommit` nor
  an isolation level, so the read runs at the server default; there is no
  consistency knob to relax.
- **Contract** (`db/protocols.py:1108-1141`): `fetch(actor_id, *, strict=True)
  -> list`. The `strict` note at `:1124-1126` ("PostgreSQL catches faults;
  DynamoDB raises either way") no longer matches either backend, and
  `purge_relationships`'s docstring (`actor.py:2240-2242`) makes the same
  outdated statement about PostgreSQL.

Neither backend returns `None` or `False`. The only non-list values reachable
are `None` from `Subscriptions.fetch()` with no config (`:265-278`) and `None`
from `get_subscriptions` itself when the actor has no id (`actor.py:2466-2467`).

Under an `is None` guard, therefore: a successful empty read sticks (the point
of the change); a `strict=False` fold to `[]` at `actor.py:2087-2089` would
also stick, for the rest of the trust-deletion loop and the instance.

### Creation and deletion paths

Creation — all go through `Actor.create_subscription` (`actor.py:2322-2354`),
the only library caller of `Subscription.create`, which resets at `:2353`:
`create_remote_subscription` (`:2356-2438`, via `:2424`),
`SubscriptionManager.subscribe_to_peer` and its async twin
(`subscription_manager.py:262-439`), `create_local_subscription` (`:678-722`,
reached from `handlers/subscription.py:199-291`), and
`AuthenticatedSubscriptionManager.create_local_subscription`
(`interface/authenticated_views.py:672-689`).

Deletion:

- `Actor.delete_subscription` (`actor.py:2550-2621`) resets. Its callers:
  `SubscriptionManager.unsubscribe`, `unsubscribe_from_peer`,
  `revoke_peer_subscription`, `delete_callback_subscription`,
  `cleanup_peer_subscriptions`, `handlers/subscription.py:486`,
  `handlers/callbacks.py:122`.
- `delete_reciprocal_trust` (`actor.py:2007-2226`) fills the memo at `:2087`,
  deletes rows with `sub_obj.delete()` (`subscription.py:86-123`) and leaves
  the deleted rows in `subs_list`. Entry points:
  `TrustManager.delete_relationship` (`interface/trust_manager.py:317`),
  `delete_all_relationships` (`:328`), `:797`, `subscription_manager.py:1643`,
  `actor.py:1277`, `Actor.delete` (`:1137`), `purge_relationships` (`:2280`).
- `Actor.delete` (`actor.py:1096-1155`) wipes through a separate
  `Subscriptions` object (`:1132`) before the per-relationship loop (`:1137`).
- `purge_relationships` (`actor.py:2228-2320`) calls `delete_reciprocal_trust`
  per relationship (`:2280`) before `subs.delete()` (`:2287`).

### Recorded decisions

- **The guard was left alone deliberately.**
  `thoughts/research/2026-07-25-rc2-triage.md:173-179`: the accidental refetch
  is "probably load-bearing for subscriptions created mid-instance"; `:279-281`:
  "The obvious fix is *unsafe*."
- **`create_subscription()` invalidates, for this instance only.**
  `CHANGELOG.rst:4389-4401` (v3.13.0) and the comment at `actor.py:2345-2352`.
- **The fetch precedes the suspension check.** `actor.py:3867-3878`,
  `CHANGELOG.rst:4333-4347`.
- **`register_diffs` reads strictly and a fault answers 503.**
  `thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md:327`, `:358`;
  `CHANGELOG.rst:1213` (Unreleased).
- **The trust-deletion fetch folds.** Commit 4275401;
  `thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md:499-507`
  and entry 31 (`:1739-1760`); `actor.py:2085-2086`: "a fault leaves this
  peer's subscriptions as orphans rather than failing the trust deletion";
  `thoughts/reference/trust-row-deletion-invariants.md:39`.
- **Eviction is actor-wide.**
  `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md:38-41`,
  `:121`, `:128` ("No change to `_token_cache` or `_actor_cache` key shapes");
  `thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md:53-71`.
  The stated reason (the wrapper carries the trust list) does not hold; the
  rule does, because the wrapper carries other memos.
- **Request identity came off the cached object.** Same plan, Phase 4
  (`:552-560`): moved to ContextVars because the cache "deliberately hands the
  **same** `ActorInterface` object to every request for a hot actor".
- **Whether the cache should hold an `ActorInterface` was never decided.**
  2026-08-15 research `:14-16`, `:75-78`;
  `thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md:566-568`
  ("its own plan"); `thoughts/plans/2026-08-20-v2-positional-access-cost.md:245-249`
  rejected caching `ListProperty` instances because the actor cache renews on
  every access, and `:266-268` deferred this item to "the MCP cache-lifetime
  work".
- **The cached wrapper's staleness is documented once.**
  `CHANGELOG.rst:3190-3202` (v3.14.3) names the sliding five-minute cache for
  an `Attributes` bucket held in it.
- **Relaxing `consistent_read` on list fetches was deferred.**
  `thoughts/todo/dynamodb-known-next.md:33-51`: subscriptions are a candidate;
  "recount before relaxing", per call site, as was done for `get_range`.

Stale cross-references found on the way: the cross-process section of
`thoughts/todo/mcp-cache-lifecycle-and-revocation.md` is §1, but
`handlers/mcp.py:385-386`, `mcp/invalidation.py:23` and the 2026-08-15 note
cite it as §2.

### Consumer

`../actingweb_mcp/api/trust_unified.py:446-466` is the endpoint the todo
measured. `_subscriptions_by_peer` (`:837-878`) reads `all_subscriptions` once
and buckets by `is_outbound` and peer; the three helpers (`_determine_direction`
`:881`, `_get_inbound_summary` `:950`, `_get_outbound_summary` `:1001`) fall
back to the per-peer accessors when passed `None`.
`tests/test_trust_relationships_subscription_reads.py` pins that the read count
does not grow with peers. Its plan
(`thoughts/plans/2026-08-25-spa-fanout-cost-and-latency.md:665-725`) records
"no library change needed" and that the p50 against 689 ms was never
re-measured.

Neither `actingweb_mcp` nor `actingwebdemo` has a module-global holding an
`Actor` or `ActorInterface`. `actingweb_mcp/repositories/property_list_accessor.py:491-493`
carries a constraint that depends on the cache: never store row snapshots
"anywhere reachable from the 5-minute `ActorInterface` cache".

### Tests that depend on the cache

No test asserts that the same `ActorInterface` object comes back across
requests. Direct references: `tests/test_mcp_revocation_evicts_caches.py:32-135`
(seeds `_actor_cache` with `object()`, asserts eviction counts of 4, one being
the actor entry) and `tests/test_mcp_trust_cache_key.py:126-133`, `:284-321`
(ages `last_accessed`, asserts the actor entry and its trust tuples go).
Indirect: `test_alternating_clients_never_cross` asserts
`_cache_stats["trust_hits"] >= 3` (`:188`) and
`test_resolver_called_once_per_actor_client_pair` asserts two resolver calls
(`:246`); both pass only because the actor-hit branch runs.

No test counts backend reads for `get_subscriptions` or `register_diffs`, checks
trust deletion against a subscription created earlier on the instance, or
creates a subscription through each path and then checks diff delivery. The
operation counter exists once, inline, at
`tests/test_actor_deletion_tombstone.py:495-539` (DynamoDB only); a
backend-agnostic counter is at `tests/test_adoption_bounded_reads.py:183-208`.

## Documentation Impact

### The MCP actor cache

- `docs/guides/caching.rst:1-435` — contributor guide. Shows `_actor_cache` as
  `actor_id -> {actor, last_accessed}` and `_cache_ttl = 300` (`:24-28`), "one
  shared actor instance per actor" (`:51-52`), an `invalidate_actor_cache`
  example (`:154-157`). Its example code already differs from the
  implementation (hashed token keys, a `ttl` field, a
  `"{actor_id}:trust_relationships"` key) and it does not say the TTL slides.
  False in whichever way Decision 1 changes the cache.
- `docs/guides/hooks.rst:304-319` — "isolated per request even when the same
  cached actor object is reused across many requests (as ActingWeb's MCP
  handler does)". False if the object stops being shared.
- `docs/reference/security.rst:103`, `docs/guides/oauth2-setup.rst:351-354`,
  `docs/migration/v3.15.rst:121-127`, `docs/migration/v3.13.rst:104-110` —
  "revocation is per process", 300 s, tokens only. Stay unless token-cache
  behaviour changes; none mentions actor-state staleness.
- `docs/quickstart/deployment.rst` — no MCP-cache note (`:118-122` covers the
  per-worker circuit breaker only). Needs nothing unless a per-process
  staleness statement is wanted.
- `docs/guides/mcp-applications.rst`, `docs/guides/mcp-quickstart.rst` — none.

### The subscription list memo

- `docs/migration/v3.13.rst:62-65` — `create_subscription()` invalidates the
  cached list. Historical; stays.
- `docs/guides/subscriptions.rst:41-46`, `docs/sdk/developer-api.rst:46-48`,
  `:290-310` — list the accessors, no caching statement. Stay; a new sentence
  only if the memo's lifetime becomes a stated contract.
- `docs/reference/actingweb.rst:19-21` autodocs `actingweb.actor` with
  `:undoc-members:`, exposing the `get_subscriptions` and `register_diffs`
  docstrings and the `subs_list` attribute; `:83-85` exposes
  `Subscriptions.fetch`'s "(and caches nothing)".
- `docs/migration/v3.13.rst:982-1037` ("Proving the fixes actually landed") —
  the operation-count table has no subscription row. Historical; stays.
- `subs_list`, the sliding TTL and `register_diffs` guarantees appear nowhere
  else in `docs/`: none.

### Where a 3.16 entry goes

- `docs/migration/v3.16.rst` — sections under "What changed and why" (`:126`)
  run to "Idempotent appends" (`:1135`), then "Cross-site requests" (`:1191`)
  and "What stays the same" (`:1248`). No section covers MCP caching.
- `CHANGELOG.rst:5` `Unreleased`: SECURITY `:8`, REMOVED `:474`, CHANGED
  `:503`, ADDED `:1236`, FIXED `:1563`. The nearest existing entries are
  CHANGED `:1213` (a diff that cannot be registered answers 503) and FIXED
  `:1757` (the four per-process permission caches).

## Decisions Needed

### Decision 1: what the MCP path keeps across requests

**Options:**

1. **Cache nothing of the actor; build `Actor` per request.** Reshape the hit
   path to token hit → `Actor()` → trust-cache lookup. Every instance memo
   becomes per-request, as on REST. Costs one strongly consistent actor read
   per MCP request (plus one bucket Query under `force_email_prop_as_creator`),
   and hooks that read properties or `store` pay per request. The trust-cache
   expiry sweep (`mcp.py:808-810`) is keyed on `_actor_cache` and has to be
   re-keyed, or positive trust entries lose their only time bound. A deleted
   actor is noticed on the next request rather than at eviction or expiry.
2. **Cache the identity, not the object.** Keep an entry per actor holding what
   `Actor()` reads eagerly (the row: id, creator, passphrase) and construct a
   new `Actor`/`ActorInterface` per request from it, with no storage read.
   Lazy memos (`subs_list`, `store`, `property`) become per-request; the actor
   row stays as stale as today. `Actor.__init__` has no path that accepts a
   preloaded row (`actor.py:113-142` always calls `self.get()`), so this adds
   one. The read profile of a fully warm request stays at 0.
3. **Keep the shared object; reset its memos on a hit.** Smallest diff. Runs
   into the concurrency constraint `runtime_context.py:15-34` records: the
   reset mutates an object other threads and tasks are using. The memo list is
   not a stable surface (the same argument `mcp.py:383-384` makes for
   eviction).
4. **Leave the cache; take `subs_list` off the instance** (request-scoped, or
   stamped with a short TTL). Closes the todo's item only; the `store`,
   `property` and actor-row memos keep the sliding lifetime.

Effect on `thoughts/todo/mcp-cache-lifecycle-and-revocation.md`:

| § | Option 1 | Option 2 | Option 3 | Option 4 |
| --- | --- | --- | --- | --- |
| 1 Cross-process invalidation | Narrows: instance memos no longer cross requests; token and trust caches unchanged | Same, except the actor row | Same as 1 as far as the reset reaches | Narrows for `subs_list` only |
| 2 Trust-freshness policy | Touched: the sweep that bounds positive trust entries must be re-keyed | Untouched if the identity entry keeps driving the sweep | Untouched | Untouched |
| 3, 5, 8 | Untouched | Untouched | Untouched | Untouched |
| 6 One app per interpreter | Narrows: removes the global whose hit path lacks the config check | Entry remains; the check at `:2289-2294` is still absent | Untouched | Untouched |

Tests that change under options 1 and 2:
`tests/test_mcp_revocation_evicts_caches.py` (eviction counts, the seeded
`object()`), `tests/test_mcp_trust_cache_key.py:284-321` (ageing
`last_accessed`, expiry removing trust tuples), and the two indirect ones at
`:188` and `:246`.

**Recommendation:** none. Options 1 and 2 both remove the hazard class rather
than one member of it; they differ by one read per request against one more
piece of cached state.

### Decision 2: sliding or absolute TTL for what remains cached

Applies to options 2 to 4. Today the entry never expires for an actor touched
more often than every 300 s (`mcp.py:2297`, `:2474`); `_token_cache` uses an
absolute `cached_at` (`:2282`).

1. **Keep sliding.** No change in read profile; whatever is cached can be as
   old as the process.
2. **Absolute, from fill time.** Bounds the staleness of whatever is cached to
   300 s per process, at one reload per actor per window.

### Decision 3: the guard and its sibling

The guard at `actor.py:2468` becomes `is None` once Decision 1 bounds the
instance's lifetime. The sibling at `:2084-2092` has three behaviours that the
falsy guard masks:

- a `strict=False` fold stores `[]` (`:2087-2089`), which would then stick;
- rows deleted through `sub_obj.delete()` stay in the memo;
- `Actor.delete` and `purge_relationships` run it in a loop over
  relationships, in opposite orders relative to their bulk wipe.

**Options:**

1. **The sibling stops using the memo.** It reads into a local, once per
   `delete_reciprocal_trust` call, and resets `subs_list` to `None` when it has
   deleted anything. A fold is never cached.
2. **The sibling goes through `get_subscriptions(strict=False)`** and the memo
   is only assigned on a successful read, with a reset after the deletes.
   One fetch can then serve a whole `purge_relationships` loop.

Also in scope whichever is chosen: `handlers/subscription.py:270` duplicates
the reset `create_subscription` already does.

### Decision 4: `consistent_read=True` on the subscription list fetch

DynamoDB only; PostgreSQL has nothing to relax.

1. **Keep.** With the guard fixed, a zero-subscription actor pays one
   consistent Query per `Actor` instance rather than per write.
2. **Relax for the list fetch.** Halves that Query's RCU. A subscription
   created moments earlier in another process is the read this relaxes;
   `thoughts/todo/dynamodb-known-next.md:33-51` asks for a per-call-site
   recount first, and `register_diffs` is the caller where a missed
   subscriber is a silently undelivered diff.

### Decision 5: a peer-indexed accessor on `SubscriptionManager`

The consumer's workaround exists because per-peer accessors refetched. With the
guard fixed, every accessor on one instance is served by one fetch, so the cost
argument for a bulk accessor goes away.

1. **Add nothing.** The consumer can keep or drop `_subscriptions_by_peer`.
2. **Add a grouped accessor** (subscriptions by peer and direction). Additive
   API; saves the consumer its helper, not a read.

### Decision 6: corrections that ride along

Facts found wrong while answering the questions; each is a comment, docstring
or doc edit:

- the "trust list" claim at `handlers/mcp.py:376-382`, `trust.py:250-252`,
  `tests/test_mcp_revocation_evicts_caches.py:79-82`;
- §2 for §1 at `handlers/mcp.py:385-386`, `mcp/invalidation.py:23`;
- the `strict` note at `db/protocols.py:1124-1126` and the PostgreSQL sentence
  at `actor.py:2240-2242`;
- `docs/guides/caching.rst`'s example code.

Include them in this plan, or leave them.

## Release shape

3.16, the unreleased minor (`docs/migration/v3.16.rst` exists; the tag is
held). No route, hook name, kwarg or response field changes under any option.
Options 1 and 2 of Decision 1 change what an MCP hook observes on the actor it
is handed (fresh property and `_internal` values per request instead of values
up to a process lifetime old) and what it costs to read them, which is a
`**Behavior change:**` entry under `CHANGED` and a short migration-guide
section; the guard fix is a `FIXED` entry with the measured read counts.

Owner decisions: 1 (what is cached), 2 (TTL shape), 3 (sibling), 4
(consistency), 5 (accessor), 6 (ride-along corrections).

## Code References

- `actingweb/actor.py:113-142` — `Actor.__init__`, the one eager read
- `actingweb/actor.py:380-400` — `Actor.get()`, early return on a loaded row
- `actingweb/actor.py:2084-2092` — trust-deletion sibling, `strict=False`
- `actingweb/actor.py:2322-2354` — `create_subscription`, the reset at `:2353`
- `actingweb/actor.py:2440-2484` — `get_subscriptions`, the guard at `:2468`
- `actingweb/actor.py:2550-2621` — `delete_subscription`, resets at `:2562`, `:2598`
- `actingweb/actor.py:3856-3890` — `register_diffs`, fetch before suspension
- `actingweb/subscription.py:260-318` — `Subscriptions.fetch` and `__init__`
- `actingweb/db/dynamodb/subscription.py:257-297` — the consistent Query
- `actingweb/db/postgresql/subscription.py:401-472` — the `SELECT`
- `actingweb/db/protocols.py:1108-1141` — the list-fetch contract
- `actingweb/handlers/mcp.py:110-129` — the caches and their TTLs
- `actingweb/handlers/mcp.py:367-413` — `evict_mcp_caches_for_actor`
- `actingweb/handlers/mcp.py:782-815` — cleanup loop, trust tuples tied to actor expiry
- `actingweb/handlers/mcp.py:2247-2419` — `authenticate_and_get_actor_cached`
- `actingweb/handlers/mcp.py:2453-2560` — `_get_or_create_actor_cached`
- `actingweb/attribute.py:22-48`, `:201-207` — `InternalStore` lazy whole-bucket load
- `actingweb/property.py:357-365` — per-key property cache, caches `None`
- `actingweb/interface/subscription_manager.py:205-260` — the accessors
- `actingweb/handlers/subscription.py:269-270` — redundant reset
- `actingweb/runtime_context.py:15-34` — why request state is not on the cached actor
- `tests/test_actor_deletion_tombstone.py:495-539` — the DynamoDB operation counter
- `tests/test_adoption_bounded_reads.py:183-208` — backend-agnostic read counter

## External References

None. Both questions are internal to this codebase.
