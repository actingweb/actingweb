# TODO: `Actor.subs_list` is falsy-guarded — a Query per write for quiet actors, staleness for busy ones

**Severity:** Medium-high. A broad cost defect with a live consumer measurement,
plus a correctness residue that survives across processes. Neither is a
regression; both predate 3.13.
**Origin:** found while removing the per-write suspension `GetItem` from
`register_diffs()` (`thoughts/research/2026-07-25-rc2-triage.md`).

## Summary

`Actor.get_subscriptions()` memoises the actor's subscription list on
`self.subs_list`, guarded by **truthiness** rather than `is None`:

```python
# actingweb/actor.py:1620
if not self.subs_list:
    self.subs_list = subscription.Subscriptions(
        actor_id=self.id, config=self.config
    ).fetch()
```

An empty list is falsy, so the cache only ever sticks for actors that *have*
subscriptions. That single line produces two opposite defects:

| Actor state | `subs_list` | Effect |
| --- | --- | --- |
| **0 subscriptions** | `[]` — falsy, never sticks | Re-queries DynamoDB on **every** call. `register_diffs()` runs per property write, so that is one strongly-consistent Query per write, forever, to learn there is nobody to notify |
| **≥1 subscription** | truthy, sticks | A cached instance in another process keeps serving a stale list |

The two cases mask each other, which is probably why this survived: the quiet
path is accidentally always-fresh, and on REST paths the busy instance is
short-lived enough that staleness closes before it matters. Neither mitigation
holds on the MCP path.

## Cost: a strongly-consistent Query per property write

For an actor with no subscriptions, every `register_diffs()` issues
`Subscription.query(self.actor_id, consistent_read=True)`
(`db/dynamodb/subscription.py`) — 2× the RCU of an eventually-consistent read,
on the `<prefix>_subscriptions` partition, per property write, to return `[]`.

The correct pattern already exists one layer down: `Subscriptions.fetch()`
guards on `if self.subscriptions is not None`, so it caches an empty list
properly. The bug is that `get_subscriptions()` constructs a **new**
`Subscriptions` object each time the outer falsy check fails, so the inner cache
never spans calls.

**It is also a read-path cost, and there the multiplier is peers, not one.**
Measured in `actingweb_mcp` on a persona actor with 5 trust relationships and 0
subscriptions: its trust-relationships endpoint loops over peers calling three
helpers that each reach for subscriptions, costing **40 subscription fetches**
where a single read indexed by peer costs 2. That endpoint sat at **p50 689 ms**
and was the only shell endpoint that did not improve when every other fell
55–60%. Accounts that connect AI clients but never subscribe to a peer are a
normal — probably majority — shape for that consumer, so the accidental
freshness is paid for constantly.

There is a **per-call-site workaround**: read all subscriptions once and index
them by `(peer_id, is_outbound)` instead of calling the per-peer accessors in a
loop (`SubscriptionInfo.is_outbound` is the same `callback` discriminator
`get_subscriptions_to_peer()` queries with). It does not generalise, which is
the argument for fixing the cache-lifetime question rather than against it.

## Correctness: staleness survives across processes

`create_subscription()` and the delete paths invalidate `self.subs_list`
themselves (`actor.py:1513`, `:1714`, `:1748`), so the single-instance window is
closed. What remains is cross-process: a **different** process can hold a truthy
stale `subs_list`, because nothing invalidates it there.

The exposed site is the trust-deletion sibling at `actor.py:1351`, same
`if not self.subs_list` idiom. It reads the list to delete a peer's
subscriptions, so a stale cache means a subscription created elsewhere is left
undeleted during trust teardown.

The MCP path is what makes the window wide: `handlers/mcp.py` keeps a
module-global `_actor_cache` holding the `ActorInterface` — and therefore the
core `Actor` and its `subs_list` — on a **sliding** 5-minute TTL, so an actor
touched more often than every five minutes never expires. On a warm container
its `subs_list` can live for the container's whole lifetime, and under
autoscaling whether a newly created subscription receives a diff depends on
which container serves the write.

## The obvious fix is unsafe — this is the part that matters

`if self.subs_list is None:` cannot land on its own. Today the falsy guard
accidentally protects against cross-process staleness: a zero-subscription actor
refetches on every call, so a subscription created in another container is
picked up immediately. Make the cache stick and that protection disappears — a
long-lived MCP-cached actor with zero subscriptions becomes **permanently blind**
to subscriptions created elsewhere, for the container's lifetime. That trades a
bounded cost bug for an unbounded correctness one.

**So the ordering is: decide the actor-cache lifetime first, then the guard.**

## What to do

1. **Decide whether a cross-request `Actor` cache should hold instance state at
   all.** `_actor_cache` demonstrably *does* — it stores a live `ActorInterface`,
   keyed by actor id, on a sliding TTL, shared across requests and across users
   of the container
   (`thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`). The
   open question is the *should*: identity/auth context only with the `Actor`
   rebuilt per request, versus an explicit request-boundary reset the
   integrations call. This unblocks item 2 and de-risks every future
   instance-level memo.
2. **Fix the guard** in `get_subscriptions()`: `if self.subs_list is None:`.
   **Blocked on item 1.**
3. **Fix the sibling call site** at `actor.py:1351` (trust deletion) — same
   idiom, and it is the one where staleness loses data rather than costing RCU.
4. **Drop the hand-rolled reset** at `handlers/subscription.py:262`. It is
   redundant now that `create_subscription()` invalidates, and it advertises the
   wrong pattern (invariant enforced by convention at call sites).
5. **Consider whether `consistent_read=True` is required** on the subscription
   list fetch. If eventual consistency is acceptable for diff fan-out, that
   halves the RCU independently of the caching question — but a subscription
   created moments earlier is exactly the read this would relax, which
   interacts with item 1.

## Tests to add

- Create a subscription via **each** of the three creation paths, then call
  `register_diffs()` on the same `Actor`; assert the new subscription receives
  the diff.
- Assert `get_subscriptions()` issues exactly one backend fetch across N calls
  for an actor with **zero** subscriptions (currently N). The operation-counter
  recipe in `docs/migration/v3.13.rst` ("Proving the fixes actually landed") is
  the tool — patch `BaseClient._make_api_call` and count `Query`.
- Trust deletion with a subscription created earlier in the same instance
  (item 3).

## Related

- `thoughts/research/2026-07-25-rc2-triage.md` — the triage this came out of.
- `thoughts/research/2026-07-25-v3.13.0rc1-consumer-feedback.md` — D7 documents
  the operation-counting technique and its `get_session()` trap.
- `thoughts/todo/dynamodb-known-next.md` — the subscription fetch is one of the
  `consistent_read` audit's relaxation candidates.
