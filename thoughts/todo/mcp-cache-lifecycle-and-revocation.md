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

**Cache eviction must be actor-wide, not keyed on `_trust_cache` alone.**
`_actor_cache` holds a live `ActorInterface` carrying the trust list itself, so
dropping the trust tuple leaves the shared wrapper serving stale trust
(`thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`). Anyone
adding a seventh cache or a new revocation path inherits this.

## 1. No cross-process invalidation

All six MCP caches (`_token_cache`, `_actor_cache`, `_trust_cache`,
`_mcp_client_info_cache`, and two more — see `mcp.py`'s module-level
declarations) are plain module globals. Single-process eviction on every
revocation path exists (`actingweb/mcp/invalidation.py`), and none of it crosses
a process boundary: `clear_token_from_cache()` clears the process that served
the revocation request, and in any multi-process deployment (multiple Lambda
containers, gunicorn or uvicorn workers) every *other* process keeps serving the
stale entry until its own TTL expires.

**Proposed fix:** out of scope for a quick patch — needs either a shared
invalidation channel (pub/sub, a version stamp read on each cache hit) or a
documented acceptance of "revocation takes up to N minutes to propagate across a
fleet", made explicit in `docs/reference/security.rst` rather than left implicit.

This is also the design that would replace the four unbounded per-process dicts
in `thoughts/todo/permission-path-unbounded-caches.md`.

## 2. No explicit trust-freshness policy

There is no documented answer to "how stale can a cached trust relationship be,
and is that acceptable for this deployment's threat model?" Today it is an
accident of `_cache_ttl = 300` shared across three caches, plus `_TRUST_CACHE_TTL`
(unset/infinite). It should be a deliberate, documented and probably
independently-configurable value: trust freshness and token freshness are
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

## 4. Substring/`endswith` peer-id matching survives on the deletion path

The exact-match resolver fix touched only the *authentication* trust lookup
(`_lookup_mcp_trust_relationship` in `mcp.py`). A structurally identical
substring match still exists on the **client deletion** path,
`actingweb/oauth2_server/client_registry.py:521`:

```python
for pattern in expected_peer_patterns:
    if pattern in peer_id or peer_id.endswith(client_id):
```

**Why this is lower severity than the authentication-path bug was — worth
recording rather than re-deriving.** `_delete_client_trust_relationship` has one
caller, `ClientRegistry.delete_client()`, which has two: `OAuth2ClientManager.delete_client()`
(actor-owner-initiated) and `Trust.delete()`, which triggers it only when the
trust row being deleted already carries a server-issued `oauth_client_id`. That
field is written exclusively by the two OAuth2 client-creation paths; a trust row
created through the ordinary `/trust` peer protocol never has one, so it can
never be the *trigger*. And `client_id` values are server-generated
(`f"mcp_{secrets.token_hex(16)}"`), high enough entropy that no client can choose
or predict another's, so the substring check can only ever match a *coincidental*
collision between legitimate ids, not an attacker-steered one.

That makes it a data-integrity/availability problem — deleting client A can
collaterally delete an unrelated trust row whose peer id happens to contain A's
client id — rather than a reachable privilege escalation. Still worth the same
exact-match treatment for defense in depth: `oauth_client_id == client_id`
first, falling back to the gated full-string peer-id reconstruction the resolver
now uses.

## 5. Registration doesn't hard-fail when trust creation fails

`client_registry.py` swallows trust-creation failure during client registration
("client registration can continue without trust relationship"), and the
authorize callback continues past a `trust_error`. Under the current fail-closed
authorization such a client gets a **permanent** `-32003` — it can never
authorize, because no trust row will ever exist for it to resolve. Issuing
credentials that can never authorize and issuing credentials that bypass
authorization are the same root cause: registration should hard-fail when trust
creation fails, surfacing the error to the registering client.

## 6. Module-global cache keys assume one ActingWeb application per interpreter

All six MCP caches are bare module globals with no namespacing by
application/config. A process hosting more than one `ActingWebApp` (distinct
`aw_type`/config) would have their MCP caches collide on identical
`(actor_id, client_id)` tuples if actor ids can coincide across apps. Not a
deployment shape we support today (one app per process is the documented
pattern), but worth a `docs/quickstart/configuration.rst` note if someone asks,
and worth namespacing by config identity if multi-app-per-process ever becomes
supported.

## 7. Sync/async `resources/read` result-formatting divergence

Not a permission-decision bug. For a **successful** `resources/read` on a
dict-shaped result, the sync handler (`mcp.py`) serializes with
`json.dumps(result, indent=2)` while the async handler (`async_mcp.py`) uses
`str(result)` — so an MCP client gets differently-formatted (and for `str()`,
malformed-for-JSON-consumers: single quotes, `None`/`True`/`False`) resource
content depending on whether Flask or FastAPI served it. Both paths return
`-32003` identically on authorization decisions; this is purely content
formatting on the success path.

**Proposed fix:** make the async path use the same `json.dumps(result, indent=2)`
for dict results, and add a sync/async parity test asserting byte-identical
`resources/read` response bodies for a successful read — not just identical
authorization decisions, which `tests/test_mcp_resource_read_permissions.py`
already covers.

## Related

- `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md` — the parent
  plan; "What We're NOT Doing" is the long form of why these were cut.
- `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md` — C6, C7 and
  the `_mcp_client_info_cache` analysis.
