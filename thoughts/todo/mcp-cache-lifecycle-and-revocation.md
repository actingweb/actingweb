# TODO: MCP cache lifecycle — revocation doesn't evict, cross-process invalidation, and related residuals

**Status:** Open. Deferred out of the `bug/trust_mcp_cache` plan
(`thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md`) on purpose —
that plan's "What We're NOT Doing" section calls out most of these items by
name as scope decisions, not oversights.
**Severity:** Medium. None of these are the authorization bypass that plan
fixed (client-A-sees-client-B's-permissions) — that's closed. These are
staleness/consistency gaps: a revoked credential or changed permission can
still be honored for up to the in-process cache TTL, and a few narrower
correctness/robustness issues found along the way.
**Origin:** `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md`
(research Patch 5, "cache lifecycle"), plus items discovered while
implementing Phases 1–4 of the plan above.

## 1. Revocation does not evict the MCP caches (research C7)

`MCPHandler.clear_token_from_cache()` (`actingweb/handlers/mcp.py`) has
exactly **one** caller: the logout handler
(`actingweb/handlers/oauth2_endpoints.py:861`). None of the other paths that
should invalidate a client's cached identity call it:

- `TokenManager.revoke_token()` (`actingweb/oauth2_server/token_manager.py:304`)
- `revoke_all_tokens()` (same file)
- `/oauth/revoke` endpoint
- Trust deletion (any path — peer-initiated, admin-initiated, or
  actor-initiated)
- Trust modification (e.g. permission downgrade via
  `TrustPermissionStore`)

A token revoked, or a trust relationship deleted/downgraded, through any of
these paths still authenticates/authorizes from a warm process for up to the
5-minute token-cache TTL (`_cache_ttl` in `mcp.py`). This is a **staleness**
window, not the cross-client bypass the parent plan fixed — a revoked
client still only ever gets *its own* prior permissions, not someone else's.

**Proposed fix:** wire eviction into each of the paths above, calling
`MCPHandler.clear_token_from_cache()` (or, for trust changes where the token
is unknown, `_evict_trust_entries_for_actor(actor_id)` directly). Needs a
decision on scope: token revocation can evict by token; trust
deletion/modification only has `actor_id` + `peer_id`/`client_id` in hand,
which the tuple-keyed `_trust_cache` (see the parent plan, Phase 1) now
supports evicting directly without touching `_token_cache`/`_actor_cache`.

## 2. No cross-process invalidation

All six MCP caches (`_token_cache`, `_actor_cache`, `_trust_cache`,
`_mcp_client_info_cache`, and two more — see `mcp.py`'s module-level
declarations) are plain module globals. Even with (1) fixed, calling
`clear_token_from_cache()` only clears the process that served the
revocation request. In any multi-process deployment (multiple Lambda
containers, multiple Flask/gunicorn workers, multiple FastAPI/uvicorn
workers) every *other* process keeps serving the stale entry until its own
TTL expires.

**Proposed fix:** out of scope for a quick patch — needs either a shared
invalidation channel (pub/sub, a version stamp read on each cache hit, etc.)
or a documented acceptance of "revocation takes up to N minutes to
propagate across a fleet," made explicit in `docs/reference/security.rst`
rather than left implicit.

## 3. No explicit trust-freshness policy (research C6)

There's no documented answer to "how stale can a cached trust relationship
be, and is that acceptable for this deployment's threat model?" Right now
it's an accident of `_cache_ttl = 300` (shared across all three caches) plus
whatever TTL scaffold Phase 1 of the parent plan added
(`_TRUST_CACHE_TTL`, currently unset/infinite). Should be a deliberate,
documented, and probably independently-configurable value — trust
freshness and token freshness are different security properties with
different acceptable staleness windows.

## 4. `_mcp_client_info_cache` is a residual cross-client channel (clientInfo only)

`_mcp_client_info_cache` (`actingweb/handlers/mcp.py`, keyed by
`Mcp-Session-Id`) is keyed by a **client-supplied header**, not by anything
server-verified. It does not affect `peer_id` or any permission decision —
confirmed during the parent plan's Phase 1 investigation — so it cannot
reproduce the authorization bypass. But it is a distinct cache with its own
key shape that was deliberately *not* touched or "harmonized" into the
`(actor_id, client_id)` tuple scheme, and a client that reuses another
client's session id (if that's even attacker-reachable — not verified
either way) could see its own request's `clientInfo` respond with a stale
or mismatched cached value. Needs someone to actually characterize whether
`Mcp-Session-Id` is attacker-controllable in a way that matters, and if so,
whether it should be scoped by something server-verified (e.g. bound to the
resolved `peer_id`).

## 5. Substring/`endswith` peer-id matching survives on the deletion path

The exact-match resolver fix in the parent plan (Phase 3) only touched the
*authentication* trust lookup (`_lookup_mcp_trust_relationship` in
`mcp.py`). A structurally identical substring-matching pattern still exists
on the **client deletion** path,
`actingweb/oauth2_server/client_registry.py:521`:

```python
for pattern in expected_peer_patterns:
    if pattern in peer_id or peer_id.endswith(client_id):
```

This is lower severity than the authentication-path bug was — deleting the
wrong trust relationship is a data-integrity/availability problem (an
operator deletes client A's registration and it collaterally deletes a
trust row that merely contains A's client id as a substring of client B's
peer id), not a permission-widening bypass — but it's the same shape of bug
and should get the same exact-match treatment: `oauth_client_id ==
client_id` first, falling back to the same gated full-string peer-id
reconstruction the resolver now uses.

## 6. Registration doesn't hard-fail when trust creation fails

`client_registry.py` currently swallows trust-creation failure during
client registration — the comment says "client registration can continue
without trust relationship" — and the authorize callback
(`oauth2_server.py:406-409`) continues past a `trust_error`. Before the
parent plan's Phase 3, such a client got full **fail-open** access (no
trust to check against, and the old fail-open default let it through
anyway). After Phase 3's fail-closed change, such a client instead gets a
**permanent** `-32003` — it can never authorize, because no trust row will
ever exist for it to resolve. Neither behavior is intended; issuing
credentials that can never authorize (or that silently bypass authorization
entirely) both point at the same root cause: registration should hard-fail
when trust creation fails, surfacing the error to the registering client
rather than silently completing.

## 7. Module-global cache keys assume one ActingWeb application per interpreter

All six MCP caches are bare module globals with no namespacing by
application/config. A process hosting more than one `ActingWebApp` instance
(distinct `aw_type`/config) would have their MCP caches collide on identical
`(actor_id, client_id)` tuples if actor ids can coincide across apps. Not
believed to be a real deployment shape today (one app per process is the
documented pattern), but worth a `docs/quickstart/configuration.rst` note if
someone asks, and worth namespacing by `config` object identity or app id if
multi-app-per-process ever becomes supported.

## 8. Sync/async `resources/read` result-formatting divergence (found in Phase 3, not fixed)

Not a permission-decision bug — found via the parent plan's Phase 3 manual
sync/async parity check, explicitly scoped out of that (security-focused)
plan and recorded here instead. For a **successful** `resources/read` on a
dict-shaped result, the sync handler (`mcp.py`) serializes with
`json.dumps(result, indent=2)`, while the async handler
(`async_mcp.py`) uses `str(result)` for the same shape. This means an
MCP client can get differently-formatted (and for `str()`, arguably
malformed-for-JSON-consumers, since Python dict `repr` uses single quotes
and `None`/`True`/`False` rather than JSON's `null`/`true`/`false`) resource
content depending on whether it's served by the Flask or FastAPI transport.
Both paths return `-32003` identically on authorization decisions — this is
purely a content-formatting bug on the success path.

**Proposed fix:** make the async path use the same `json.dumps(result,
indent=2)` formatting as sync for dict results, and add a
sync/async parity test asserting byte-identical `resources/read` response
bodies for a successful read (not just identical authorization decisions,
which `tests/test_mcp_resource_read_permissions.py` already covers).

## Related

- `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md` — the
  parent plan; see "What We're NOT Doing" for items 1, 2, 4, 5, 6, 7 above
  as originally-scoped-out decisions, and Phase 3's Verification notes for
  item 8's discovery.
- `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md` — C6,
  C7, and the `_mcp_client_info_cache` analysis.
