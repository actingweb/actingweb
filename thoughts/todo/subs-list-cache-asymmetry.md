# TODO: `Actor.subs_list` cache is falsy-guarded — costs a Query per write for quiet actors, goes stale for busy ones

**Date:** 2026-07-26
**Status:** Partly fixed in v3.13.0rc2 (invalidation). The cost half is open
and its obvious fix is **blocked** — see "Status after v3.13.0rc2".
**Severity:** Medium-high. One correctness bug (silent dropped notifications;
the window is a container lifetime on the MCP path, not one request — see
below), one cost bug (broad, cheap-ish per call). Neither is a regression;
both predate 3.13.
**Origin:** Follow-up from the v3.13.0 work — found while removing the
per-write suspension `GetItem` from `register_diffs()`
(see `thoughts/research/2026-07-25-rc2-triage.md`).
**Owner:** unassigned — candidate for 3.14 alongside I0

## Summary

`Actor.get_subscriptions()` memoises the actor's subscription list on
`self.subs_list`, guarded by **truthiness** rather than `is None`:

```python
# actingweb/actor.py:1582
if not self.subs_list:
    self.subs_list = subscription.Subscriptions(
        actor_id=self.id, config=self.config
    ).fetch()
```

An empty list is falsy, so the cache only ever sticks for actors that *have*
subscriptions. That single line produces two opposite defects:

| Actor state | `subs_list` | Effect |
| --- | --- | --- |
| **0 subscriptions** | `[]` — falsy, never sticks | Re-queries DynamoDB on **every** call. `register_diffs()` runs per property write, so this is one Query per write, forever, to keep learning there is nobody to notify. |
| **≥1 subscription** | truthy, sticks | Cache is never invalidated by `Actor.create_subscription()`, so a subscription created during the instance's lifetime is **invisible** to `get_subscriptions()` and `register_diffs()` for the rest of that instance. |

The two cases mask each other, which is probably why this has survived: the
quiet-actor path is accidentally always-fresh, and on the REST paths the
busy-actor instance is short-lived enough (one request) that the staleness
window closes before it matters. That second mitigation does **not** hold on
the MCP path or under a warm serverless container — see Bug 1.

## Bug 1 — correctness: stale cache after subscription creation

`Actor.create_subscription()` (`actor.py:1453`) does **not** reset
`self.subs_list`. Only the *delete* paths do (`actor.py:1676`, `actor.py:1710`).

Someone has already hit this and patched it at one call site — the protocol
handler resets the cache by hand, with a comment naming the exact symptom:

```python
# actingweb/handlers/subscription.py:262
# Invalidate subscription cache so register_diffs() sees the new subscription
myself.subs_list = None
```

That is the tell: the invariant is enforced **by convention at call sites**
rather than inside `create_subscription()`. Two other creation paths do not do
it and are therefore exposed:

- `actingweb/interface/subscription_manager.py:707` — the SDK path application
  code uses. An app that subscribes a peer and then writes a property in the
  same request silently skips the diff for the subscription it just created.
- `actingweb/interface/authenticated_views.py:325` — accepting a subscription
  request from the authenticated peer.

**Window: much wider than "one request".** The staleness window is one
`Actor` *instance* lifetime, and instances are not always per-request:

- **REST handlers:** per request. Needs create-then-write in a single
  request to bite. Narrow — but it is exactly what a "subscribe and
  immediately sync current state" flow does, and the failure is silent.
- **MCP handlers:** `handlers/mcp.py` keeps a module-global `_actor_cache`
  (`_cache_ttl = 300`) holding the `ActorInterface` — and therefore the core
  `Actor` and its `subs_list` — across requests. The TTL is **sliding**
  (`cached_data["last_accessed"] = current_time` on every hit,
  `mcp.py:1366`), so an actor touched more often than every 5 minutes
  **never expires**. On a warm container its `subs_list` can live for the
  container's entire lifetime.

Under autoscaling this becomes non-deterministic rather than merely stale:
different containers hold different `Actor` instances with different cache
ages, so whether a newly created subscription receives a diff depends on
which container serves the write. Reproducing it means hitting the wrong
container.

Reference deployment (`../actingweb_mcp`): Lambda container images behind
HTTP API v2, no provisioned concurrency, **plus a 5-minute warmup ping**
(`serverless.yml`) that deliberately keeps one execution environment alive
indefinitely. That warm instance is precisely the long-lived process where an
actively used actor's `subs_list` never expires.

## Bug 2 — cost: a strongly-consistent Query per property write

For an actor with no subscriptions, every `register_diffs()` call issues:

```python
# actingweb/db/dynamodb/subscription.py:174
Subscription.query(self.actor_id, consistent_read=True)
```

A **strongly-consistent** Query — 2× the RCU of an eventually-consistent one —
on the `<prefix>_subscriptions` partition, per property write, to return `[]`.

This is the same shape as the defects 3.13 fixed (per-construction
`DescribeTable`, per-read full-table `Scan`): an unconditional control-flow
read on a hot path whose answer almost never changes. It was not in scope for
3.13 because it is not a `Scan` and not superlinear — it is bounded and
per-actor — but for a write-heavy deployment it is a real per-write cost.

Note the correct pattern already exists one layer down —
`Subscriptions.fetch()` (`subscription.py:252`) guards on
`if self.subscriptions is not None`, so it caches an empty list properly. The
bug is that `Actor.get_subscriptions()` constructs a **new** `Subscriptions`
object each time the outer falsy check fails, so the inner cache never spans
calls.

## Status after v3.13.0rc2

**Bug 1 is fixed for the same-instance case.** `Actor.create_subscription()`
now invalidates `self.subs_list` itself (`actor.py`), so the invariant no
longer depends on each caller remembering. Verified against DynamoDB Local:
subscribe then write on one instance, and the new subscription receives the
diff.

**Bug 2 is still open, and the obvious fix is *unsafe* — this is the finding
that matters.** The original plan here was "invalidation first, then the
cache guard." Invalidation alone is **not** enough to make
`if self.subs_list is None:` safe, because it only refreshes the instance the
create happened on:

- `handlers/mcp.py` shares one `Actor` across requests on a sliding TTL. A
  subscription created in **another process or another container** never
  touches that cached instance.
- Today the falsy guard accidentally protects against exactly this: a
  zero-subscription actor refetches on every call, so a cross-container
  create is picked up immediately.
- Make the cache stick and that protection disappears. A long-lived cached
  MCP actor with zero subscriptions would become **permanently blind** to
  subscriptions created elsewhere — for the container's whole lifetime.

So the guard cannot land until the cross-request `Actor` sharing is addressed
(item 4 below). Ordering is: **actor-cache lifetime → then the guard**, not
"invalidation → guard". Bug 2's cost (one strongly-consistent `Query` per
property write for actors with no subscribers — confirmed live in the rc2
operation profile: `{GetItem: 1, PutItem: 1, Query: 1}`) stays until then.

## Proposed fix

**Decided 2026-08-14** (owner walkthrough): **take item 4 first — the
cache-lifetime question — not the guard.** Deciding whether `_actor_cache` holds
only identity/auth context with the `Actor` rebuilt per request, or whether
instance caches need an explicit request-boundary reset, is what unblocks item 2
*and* de-risks every future instance-level memo. The guard alone was rejected as
trading a bounded cost bug for an unbounded correctness one.

The half of item 4 that §1 of
`thoughts/todo/mcp-cache-lifecycle-and-revocation.md` needed was answered on
2026-08-15 and that work landed, so this no longer pairs with anything — the
*should* is now this file's alone to answer.

1. ~~**Centralise invalidation.**~~ **DONE in rc2** — `create_subscription()`
   resets `self.subs_list`. The hand-rolled reset at
   `handlers/subscription.py:262` is now redundant; harmless, but it
   advertises the wrong pattern and can be dropped.
2. **Fix the guard** in `get_subscriptions()`: `if self.subs_list is None:`.
   **Blocked on item 4** — see "Status after v3.13.0rc2". Landing this before
   the actor-cache lifetime is sorted trades a bounded cost bug for an
   unbounded correctness one.
3. **Check the sibling call site** at `actor.py:1322` (trust deletion) — same
   `if not self.subs_list` idiom, same latent behaviour. It reads the list to
   delete a peer's subscriptions, so a stale cache there means missing a
   subscription during trust teardown.
4. **Decide whether a cross-request `Actor` cache should hold instance state
   at all.** **Partly answered 2026-08-15** —
   `thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`
   establishes that it *does*: `_actor_cache` stores a live `ActorInterface`,
   keyed by actor id, on a **sliding** TTL, shared across requests and across
   users of the container. That was the half the MCP revocation work needed, and it is enough to
   make the revocation-eviction work (#130) correct regardless of how the rest
   is decided. What remains open is the *should* — identity-only with the
   `Actor` rebuilt per request, versus an explicit request-boundary reset. That
   question is now this file's alone, and item 2 below stays blocked on it. Fixing invalidation inside `create_subscription()` closes the
   window for one process, but `handlers/mcp.py`'s `_actor_cache` shares an
   `Actor` across requests *and across users of that container*, so any
   future instance-level memo inherits the same hazard. Either the MCP cache
   should hold only the identity/auth context and rebuild the `Actor` per
   request, or instance caches need an explicit "request boundary" reset the
   integrations call. This is the general fix; items 1-3 are the specific one.
5. Consider whether `consistent_read=True` is required on the subscription
   list fetch. If eventual consistency is acceptable for diff fan-out, that
   halves the RCU independently of the caching question. Needs thought — a
   subscription created moments earlier is exactly the read this would relax,
   which interacts with (1).

## Tests to add

- Create a subscription via **each** of the three creation paths, then call
  `register_diffs()` on the same `Actor` instance; assert the new subscription
  receives the diff. This fails today for the two interface paths.
- Assert `get_subscriptions()` issues exactly one backend fetch across N calls
  for an actor with **zero** subscriptions (currently N). The operation-counter
  recipe in `docs/migration/v3.13.rst` ("Proving the fixes actually landed") is
  the tool — patch `BaseClient._make_api_call` and count `Query`.
- Trust deletion with a subscription created earlier in the same instance
  (item 3 above).

## Consumer evidence, 2026-09-01 — Bug 2 also lands on a *read* path, per page load

Reported from `../actingweb_mcp`. Everything above frames Bug 2 as a per-**write**
cost ("one Query per property write" via `register_diffs()`). It is also a
per-**read** cost, and there the multiplier is the number of peers rather than
one, which makes it user-visible latency rather than background spend.

`api/trust_unified.py`'s `get_all_relationships` (the `GET /api/trust/relationships`
endpoint behind the SPA's connections page, and part of both shell families)
loops over trust relationships and calls four per-peer helpers. Three of them
reach for subscriptions:

- `_determine_direction` → `get_subscriptions_from_peer` **and** `get_subscriptions_to_peer`
- `_get_inbound_summary` → `get_subscriptions_from_peer`
- `_get_outbound_summary` → `get_subscriptions_to_peer`

An **MCP-client-only account has trust relationships and zero subscriptions** —
exactly the falsy-guard case — so the memo never sticks and every one of those
calls refetches.

**Measured** on a persona actor with 5 trust relationships and 0 subscriptions,
by patching `subscription.Subscriptions.fetch` and counting through the loop's
exact helper sequence:

| | subscription fetches |
| --- | --- |
| per-peer lookups | **40** |
| single read, indexed by peer | **2** |

(Two rather than one because each logical `get_subscriptions()` triggers two
`Subscriptions.fetch` calls; the ratio is 20 logical reads → 1.)

Why this is worth adding to an already-thorough file:

1. **It changes the severity shape.** The write-path cost is bounded at one
   Query per write. The read-path cost is `4 × peers` per page load, on the
   critical path of a page the user is waiting for. In production this endpoint
   sat at **p50 689 ms** and was the only shell endpoint that did not improve
   while every other fell 55–60%.
2. **It confirms the "quiet actor" case is not rare.** The file notes the two
   cases mask each other and that the zero-subscription path is "accidentally
   always-fresh". Accounts that connect AI clients but never subscribe to a peer
   are a normal, probably majority, shape for this consumer — so the accidental
   freshness is being paid for constantly, not occasionally.
3. **It does not change the blocked-ness of item 2.** The reasoning in "Status
   after v3.13.0rc2" holds: making the cache stick would make a long-lived
   MCP-cached zero-subscription actor blind to subscriptions created in another
   container. This evidence raises the *value* of fixing item 4, it does not
   offer a shortcut past it.

**Consumer-side workaround, for other callers hitting the same shape.** The fix
that does not need the library: read `all_subscriptions` **once** and index it by
`(peer_id, is_outbound)`, then hand each peer its slice, instead of calling the
per-peer accessors in a loop. `SubscriptionInfo.is_outbound` is `is_callback` is
the `callback` flag, which is the same discriminator
`get_subscriptions_to_peer(peer_id)` queries with, so the in-memory split is
equivalent. Landed downstream as `actingweb_mcp@f9bef42f`; downstream note in
`../actingweb_mcp/thoughts/todo/2026-09-01-trust-relationships-is-now-the-slowest-shell-endpoint.md`.

This workaround is per-call-site and does not generalise — which is the argument
for item 4, not against it.

## Related

- `thoughts/research/2026-07-25-rc2-triage.md` — the 3.13.0 triage this came
  out of; I0 (whole-partition property reads) is the other deferred item —
  now filed as `thoughts/todo/property-fetch-reads-whole-partition.md`.
- `thoughts/research/2026-07-25-v3.13.0rc1-consumer-feedback.md` — the consumer
  report; D7 documents the operation-counting technique and its `get_session()`
  trap.
- `thoughts/todo/dynamodb-known-next.md`
