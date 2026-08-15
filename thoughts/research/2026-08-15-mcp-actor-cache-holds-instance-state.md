---
date: 2026-08-15
status: done
question: "Does `handlers/mcp.py`'s `_actor_cache` hold instance state, and what does that make row 6's eviction surface?"
---

# `_actor_cache` holds instance state — so eviction is actor-wide

`thoughts/todo/INDEX.md` §0 requires this answered **on paper before writing row
6's eviction wiring**, because what the cache holds decides what eviction has to
touch. It is item 4 of `thoughts/todo/subs-list-cache-asymmetry.md`, and row 7's
`is None` guard is blocked on the same question.

**Scope.** This answers what the cache holds *today* and what row 6 must
therefore evict. It does **not** decide whether the cache *should* hold that —
INDEX §0 assigns any restructuring, and the guard itself, to 3.14.

## The answer

**Yes, and more than one layer of it.** `_get_or_create_actor_cached()`
(`actingweb/handlers/mcp.py`) stores a live `ActorInterface`:

```python
_actor_cache[actor_id] = {
    "actor": actor_interface,   # wraps a core actingweb.actor.Actor
    "last_accessed": current_time,
    "config": self.config,
}
```

Three properties compound:

1. **It is the object, not a snapshot.** The `ActorInterface` wraps a core
   `Actor`, so every memo on that instance is cached with it — `subs_list`
   being the one already filed as a defect, but the trust list and property
   handles come along too.
2. **The TTL is sliding.** Each hit sets `last_accessed = current_time`, so an
   actor touched more often than every five minutes **never expires**. On a warm
   container the entry can live for the container's lifetime. The reference
   deployment (`../actingweb_mcp`) runs a 5-minute warmup ping, which is
   precisely that shape.
3. **It is keyed by actor id alone** and shared across requests *and across
   users of that container*. The only qualifier is the `config is self.config`
   check, added so a multi-app process cannot serve one app's wrapper to
   another.

So the cache is not an identity/auth cache with the actor rebuilt per request.
It is an object cache, and any instance-level memo added anywhere in the `Actor`
hierarchy silently inherits its lifetime.

## What that makes row 6's eviction surface

**Actor-wide, and narrower eviction is not a valid option.**

The tempting reading of row 6 is that a permission downgrade for one client
should evict one `_trust_cache[(actor_id, client_id)]` tuple. That is wrong
here: the cached `ActorInterface` carries the trust list itself, so dropping the
tuple leaves the shared wrapper answering from stale state. The existing
`clear_token_from_cache()` already reached this conclusion — its comment says
actor-wide is "by design", because evicting the shared wrapper affects every
client on the actor anyway, so every `(actor, client)` entry goes with it.

Concretely, every revocation path must clear all three caches for the actor:
`_token_cache` entries whose `actor_id` matches, the `_actor_cache` wrapper, and
every `_trust_cache` tuple with that actor in position 0. That is what
`evict_mcp_caches_for_actor()` does.

**A narrower surface cannot be specified without freezing what the wrapper
caches**, and nothing constrains that — which is exactly the hazard item 4 was
raised about. Actor-wide eviction is correct *regardless* of how the 3.14
lifetime question is answered, which is why row 6 can land before it.

## What this does not settle

- **Whether the cache should hold an `ActorInterface` at all.** Item 4's actual
  question. The alternatives are holding only identity/auth context and
  rebuilding the `Actor` per request, or an explicit request-boundary reset the
  integrations call. Both are 3.14 per INDEX §0.
- **Row 7's `is None` guard stays blocked.** Making `subs_list` cache properly
  is unsafe while a long-lived cached actor can go permanently blind to
  subscriptions created in another container. Row 6's eviction does not unblock
  it: eviction fires on *revocation*, and a subscription created elsewhere
  revokes nothing.
- **Cross-process invalidation.** Every cache here is a module global. Eviction
  clears the process that served the revocation; other workers keep their
  entries until TTL. §2 of the cache-lifecycle todo, deliberately unscoped.

## Related

- `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` — §1 is row 6; §2 is the
  cross-process gap this leaves open
- `thoughts/todo/subs-list-cache-asymmetry.md` — item 4 is the question above;
  items 2 and 3 remain blocked on the 3.14 half
- `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md` — added the
  tuple-keyed `_trust_cache` that makes this eviction cheap
