# TODO: MCP cache lifecycle — cross-process invalidation and related residuals

**Status:** Open. Scoped out of `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md`
by name — see its "What We're NOT Doing", which is where the reasoning for each
cut lives.
**Severity:** Medium. None of these is the authorization bypass that plan fixed
(client-A-sees-client-B's-permissions). These are staleness/consistency gaps — a
revoked credential or changed permission can still be honored for up to the
in-process cache TTL — plus a few narrower correctness and robustness issues
found alongside them.
**Origin:** `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md`
(research Patch 5, "cache lifecycle"), plus items found while implementing that
plan.

## The constraint everything here inherits

**Cache eviction must be actor-wide, not keyed on one client's entries.** One
revocation (a revoked-all, a deleted trust, a downgraded permission) or one
re-typing of a client's trust covers every client of the actor, so every token
and trust entry of the actor goes. (Until 4.0 the reason was `_actor_cache`'s
shared `ActorInterface`; that cache is gone, the MCP path builds its actor per
request, `thoughts/plans/2026-11-06-subs-list-cache-lifetime.md`.) Fills check
the revocation counter and write under the lock the eviction holds. Anyone
adding a cache or a new revocation path inherits this.

## 1. No cross-process invalidation

The MCP caches (`_token_cache`, `_trust_cache`, `_mcp_client_info_cache` and
the others in `mcp.py`'s module-level declarations) are plain module globals;
none holds instance state since 4.0 (no actor object is cached). Single-process eviction on every
revocation path exists (`actingweb/mcp/invalidation.py`), and none of it crosses
a process boundary: `clear_token_from_cache()` clears the process that served
the revocation request, and in any multi-process deployment (multiple Lambda
containers, gunicorn or uvicorn workers) every *other* process keeps serving the
stale entry until its own TTL expires.

**Proposed fix:** out of scope for a quick patch — needs either a shared
invalidation channel (pub/sub, a version stamp read on each cache hit) or a
documented acceptance of "revocation takes up to N minutes to propagate across a
fleet", made explicit in `docs/reference/security.rst` rather than left implicit.

This is also the design that would replace the four per-process permission-path
caches (`trust_permissions`, `peer_profile`, `peer_permissions`,
`peer_capabilities`). Each is now a bounded LRU (`actingweb/_bounded_cache.py`),
but it is still per process and never invalidated from another one. Since
`thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.md` the `trust_permissions`
cache (a peer's override, or its absence) expires an entry after 300 seconds,
so the staleness of a grant on another worker is bounded; the trust-row
deletion rules (`thoughts/reference/trust-row-deletion-invariants.md`, "Scope
of the rules") still hold only within one process for up to that window. The
other three caches and the trust type registry's cache have no expiry.

## 2. No explicit trust-freshness policy

There is no documented answer to "how stale can a cached trust relationship be,
and is that acceptable for this deployment's threat model?" Since 4.0 a
resolved trust entry expires after `_TRUST_CACHE_TTL = _cache_ttl` (300 s; a
cached "no trust" after 10 s), stated in `docs/reference/security.rst`; before
that its only expiry was the actor cache's sweep. Still open: whether it should
be configurable on its own, since trust freshness and token freshness are
different security properties with different acceptable staleness windows.

## 3. `_mcp_client_info_cache` is a residual cross-client channel (clientInfo only)

`_mcp_client_info_cache` (`actingweb/handlers/mcp.py`, keyed by
`Mcp-Session-Id`) is keyed by a **client-supplied header**, not by anything
server-verified. It does not affect `peer_id` or any permission decision, so it
cannot reproduce the authorization bypass — but it is a distinct cache with its
own key shape that was deliberately not harmonized into the
`(actor_id, client_id)` tuple scheme, and a client that reuses another client's
session id could see its own request's `clientInfo` answered from a stale or
mismatched entry. Needs someone to characterize whether `Mcp-Session-Id` is
attacker-controllable in a way that matters, and if so whether the cache should
be scoped by something server-verified (e.g. bound to the resolved `peer_id`).

## 6. Module-global cache keys assume one ActingWeb application per interpreter

The two MCP globals that authenticate, `_token_cache` and `_trust_cache`,
record the `Config` that filled each entry since 4.0, and an entry another
application filled is a miss (`thoughts/plans/2026-11-06-subs-list-cache-lifetime.md`,
Phase 1). The keys are still shared, so two applications holding the same
actor id evict and replace each other's entries (a re-validation, never an
accepted foreign entry). The other MCP globals (`_mcp_client_info_cache` and
the rest) carry no application, which matters only if multi-app-per-process
becomes a supported shape.

The same shape, noted 2026-09-27 from the PR #148 review: the opportunistic
token-purge throttles are module globals too (`oauth_session.py`
`_purge_throttle`, `oauth2_server/token_manager.py` `_mcp_purge_throttle`,
both `single_use.PurgeThrottle`). Two apps in one process share one
`last_attempt`, so one app's token-endpoint traffic can starve the other's
purge. Harmless on DynamoDB (native TTL reaps anyway); on PostgreSQL the
purge is the only reaper. Same trigger, same fix: scope by config.

## Related

- `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md` — the parent
  plan; "What We're NOT Doing" is the long form of why these were cut.
- `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md` — C6, C7 and
  the `_mcp_client_info_cache` analysis.

## Added 2026-11-19 (a consumer's A12)

One actor load per MCP session instead of one point read per request.
Caching the actor across requests touches deletion and revocation freshness
(above); waits for the consumer's measured cold-start and per-call numbers
(`thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md`).

