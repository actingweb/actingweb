---
status: active
---

# Implementation Plan: MCP trust cache client crossing (authorization bypass)

**Date:** 2026-07-30
**Research:** `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md`
**Branch:** `bug/trust_mcp_cache`
**Base commit:** `ac17fb8` (research write-up) on top of `cc29c03` (`v3.13.0rc2`)

## Overview

The MCP authentication path caches per-client trust relationships under an
actor-only key, so one MCP client's resolved trust silently replaces another's on
the same actor. Because the permission evaluator resolves the trust *type* — and
therefore the entire permission rule set — from `peer_id`, this is a demonstrated
authorization bypass, not a display bug: a read-only client performed a write
immediately after a read-write client authenticated on the same actor. The defect
has shipped in every release since `release_3_3` (2025-10-04).

This plan re-keys the cache to `(actor_id, client_id)`, turns on a permission
check that has been silently dead on the Flask path since the MCP SDK was
dropped, replaces substring trust matching with exact matching and closes the
fail-open at the authorization boundary, and moves `RuntimeContext` storage off
the shared cached actor object into execution-local storage so identity is truly
request-scoped under concurrency.

## Decisions Made

- **Cache key: `(actor_id, client_id)` tuple** — both values are in hand before
  the lookup on both code paths (`mcp.py:1239`, `:1310`), it matches the
  persisted trust cardinality (one trust row per client), it follows this
  repository's own documented composite-key guidance (`docs/guides/caching.md:26-41`),
  and it matches the MCP specification's normative `<user_id>:<handle>` keying
  rule for server-side state.
- **Eviction scope: actor-wide at both existing sites** — preserves today's
  observable behavior exactly (including that `clear_token_from_cache` already
  drops the shared `ActorInterface` for every client on the actor). Narrowing
  invalidation is deferred until tests define the narrower semantics.
- **Plan scope: research Patches 1–4; Patch 5 deferred** — cache lifecycle
  (revocation-to-cache wiring, cross-process invalidation, explicit trust
  freshness policy) becomes a `thoughts/todo/` entry. Two of its items are pulled
  forward into Phase 1 because later phases depend on them: the inert cleanup
  scheduler and a `cached_at` stamp on trust entries.
- **Cleanup scheduler and `cached_at` land in Phase 1** — `time.time() % 20 == 0`
  (`mcp.py:1222`) is a float modulo that is effectively never true, so the
  expired-actor eviction site is production-dead code and entries accumulate.
  `cached_at` on trust tuples is what lets Phase 3 give cached `None` a short
  negative TTL, which is required to avoid eventual-consistency lockouts once
  missing trust becomes fail-closed.
- **Trust resolver: exact `oauth_client_id == client_id`, with a gated exact
  peer-id fallback** — verified to round-trip on both backends on the list read
  path the resolver actually iterates, and it matches the existing exact-match
  precedent at `oauth2_server.py:886-892` and `www.py:549-551`. The fallback is
  required because `oauth_client_id` is only written when
  `source == "oauth2_client"` (`trust_manager.py:506-507`, `:578-579`).
  The security review's constraint is adopted: the fallback must require
  `established_via` to be an OAuth2-family value *and* full-string equality on a
  constructed candidate — never containment, never a bare segment compare.
  Client ids are public identifiers (RFC 6749), so a crafted peer id created
  through the ordinary `/trust` peer protocol must not be able to occupy the slot.
- **`oauth2_interactive` trusts cannot back an MCP access token — settled, no
  resolver branch needed.** The research left this open and it was a genuine
  lockout risk, so it was traced before finalizing this plan.
  `handle_google_callback` reaches the `established_via` selection at
  `oauth2_server.py:375-381` only after `extract_mcp_context(state)` succeeded at
  `:309-316`, and that returns `None` unless `flow_type == "mcp_oauth2"`
  (`state_manager.py:182-188`). So `flow_type` is necessarily `"mcp_oauth2"` at
  `:378`, the `else: established_via = "oauth2_interactive"` at `:381` is
  **unreachable dead code**, and every trust on the MCP authorize path is created
  `oauth2_client`. The only other producer is the default at `oauth2.py:1424-1425`,
  which applies when a caller passes `established_via=None` — the MCP path always
  passes it explicitly (`oauth2_server.py:394-401`). Fail-closed therefore cannot
  lock out interactively-established clients. Phase 3 asserts this with a test and
  removes the dead `else`.
- **Missing trust becomes fail-closed; evaluator errors stay fail-open** — a
  valid token that resolves to no trust relationship gets empty
  tools/resources/prompts lists and `-32003` on calls. This separates "no
  principal" (a security condition) from "permission subsystem unavailable" (an
  availability condition, `mcp.py:529-533`). Ships directly in rc3 rather than
  staged, because the release-candidate round exists precisely to validate it.
- **Invariant check: log at ERROR, do not deny** — after trust resolution, log
  when the authenticated `client_id` cannot be reconciled with the resolved
  `peer_id`. Zero behavioral risk, and it would have caught this bug in
  production. Denying on mismatch was rejected: a false positive on a legacy
  peer-id shape would cause denials.
- **`RuntimeContext`: ContextVar storage behind the unchanged public API** —
  matches the repository's existing `request_context.py` architecture and makes
  the `docs/guides/hooks.rst:304` claim ("request-scoped and automatically
  managed") true for the first time. Rejected alternatives: a fresh
  `ActorInterface` wrapper per request (preserves the flawed abstraction), and
  attribute storage plus explicit clears (fixes only sequential bleed, and every
  request already re-sets context before dispatch, so it buys almost nothing).
- **Release: `v3.13.0rc3` with a prominent CHANGELOG security note** — a
  candidate round lets the consumer re-run the escalation probe against TestPyPI
  before a final tag. Disclosure is a clearly-flagged CHANGELOG security section
  plus a migration checklist, not a CVE/advisory. Split across two phases because
  `CLAUDE.md` requires that PRs merge without version bumps and that tags be cut
  only from master: Phase 5 does the docs and the `Unreleased` entry on the
  branch, Phase 6 does the rename, bump and tag on master.
- **Corrupted trust-row metadata (C12): self-heal plus documentation** — no
  reconciliation script. After the key fix, each client's next request rewrites
  its own metadata. The CHANGELOG and migration guide state that
  `client_name` / `client_version` / `client_platform` / `last_accessed` /
  `last_connected_via` history is unreliable for the affected window.

## What We're NOT Doing

- **No cache redesign.** Per-entry TTL policy beyond the `cached_at` stamp,
  process/application namespacing of module-global cache keys, and a shared
  invalidation channel are out of scope.
- **No revocation-to-cache wiring (C7).** `clear_token_from_cache` still has
  exactly one caller (logout, `oauth2_endpoints.py:857-866`); `/oauth/revoke`,
  `revoke_token`, `revoke_all_tokens`, and every trust/actor deletion path still
  do not evict. A revoked token still authenticates from a warm process for up to
  the 5-minute token TTL. Recorded in `thoughts/todo/`.
- **No cross-process invalidation.** All six caches remain module globals, so
  logout still only clears the process that served it.
- **No narrowing of eviction to a single client.** Actor-wide stays.
- **No repair of the `Mcp-Session-Id`-keyed client-info cache.**
  `_mcp_client_info_cache` (`mcp.py:1808-1841`) is keyed by a client-supplied
  header and is a separate cross-client channel for `clientInfo` only — it does
  not affect `peer_id` or any permission decision. It must not be "harmonized"
  into the tuple change; it is recorded in `thoughts/todo/` as a known residual.
- **No reconciliation script for already-corrupted trust rows.**
- **No change to `_token_cache` or `_actor_cache` key shapes.**
- **No change to how registration handles trust-creation failure.**
  `client_registry.py` swallows the error ("client registration can continue
  without trust relationship") and the authorize callback continues on
  `trust_error` (`oauth2_server.py:406-409`). Those clients get *full fail-open
  access* today and a permanent `-32003` after Phase 3, so issuing credentials
  that can never authorize deserves a fix — but it is a registration-behavior
  change, not a cache or authorization-boundary fix, and it would widen this
  plan's blast radius. Recorded in `thoughts/todo/` and named in the migration
  guide so operators can spot it.
- **No CVE filing.** CHANGELOG security note and migration guidance only.

## Phase 1: Tuple trust-cache key, safe eviction, and cache hygiene

The security fix. Everything here is unit-testable with no docker and no
database.

### Changes

- `actingweb/handlers/mcp.py:46` — redeclare
  `_trust_cache: dict[tuple[str, str], dict[str, Any]] = {}`, documented as
  `(actor_id, client_id) -> {"trust": relationship, "cached_at": float}`. The
  value becomes a small record so the entry carries its own timestamp; keep the
  wrapper minimal and treat `trust` as possibly `None`.
- `actingweb/handlers/mcp.py:1255-1263` — hot path: build one local
  `trust_key = (actor_id, client_id)` and use it for both the read and the
  miss-write. This is the site that currently serves another client's trust.
  **Land the TTL scaffold here too**, as a no-op (effectively infinite TTL), so
  Phase 3 only tunes a constant instead of re-editing these same lines: unwrap
  the record, compare `cached_at`, and treat an expired entry as a miss.
  **Truthiness trap:** with a wrapper record, `trust_key in _trust_cache` is now
  true even when the cached trust is `None`, so the unwrap must be explicit
  before `peer_id = trust.peerid if trust else ""` at `:1270-1272` — a cached
  `None` must still yield an empty `peer_id`, not an `AttributeError` on the
  wrapper.
- `actingweb/handlers/mcp.py:1331` — full-auth path: write the same
  `trust_key`. Both sites must go through one construction helper so a future
  edit cannot fix only one path.
- `actingweb/handlers/mcp.py:152-155` — expired-actor cleanup: delete every
  tuple whose first component is the expired actor. **Iterate a snapshot**
  (`for key in [k for k in list(_trust_cache) if k[0] == actor_id]`). These
  module dicts are mutated from concurrent Flask worker threads with no lock;
  direct-key deletes were safe by CPython atomicity, but a live key scan can
  raise `RuntimeError: dictionary changed size during iteration`.
- `actingweb/handlers/mcp.py:1884-1888` — `clear_token_from_cache`: same
  actor-wide snapshot-scan deletion, preserving current semantics.
- `actingweb/handlers/mcp.py:1222` — replace `if time.time() % 20 == 0:` with a
  module-level request counter (or a monotonic `next_cleanup_at` deadline) so
  cleanup actually runs. Without this the `:152-155` eviction site is dead code
  and Phase 1's eviction test would only ever pass by calling the private method
  directly.
- `actingweb/handlers/mcp.py` (after each trust resolution, both paths) — add
  the C11 invariant check. It must be **format-aware** and must **not log the
  peer id verbatim**: live peer ids are
  `oauth2_client:<normalized_email>:<client_id>`, so the raw string embeds a
  user email that would land in production log aggregators at ERROR level.
  Reconcile as
  `trust.oauth_client_id == client_id or client_id in peer_id or normalized(client_id) in peer_id`
  (the dead direct-lookup branch at `:1444-1451` shows the normalization:
  `@`→`_at_`, `.`→`_dot_`, `:`→`_colon_`), and log only `actor_id`, `client_id`,
  and the peer id's *prefix segment*. Never log `token_data`.
- `actingweb/handlers/mcp.py:1210-1219` — docstring says trust is "cached per
  actor" and "cache keys are based on tokens and actor IDs". Correct both.
- `actingweb/handlers/mcp.py:43-45` — the `_actor_cache` declaration comment
  promises a `trust_context` field that is never written. Remove the false
  promise.
- `docs/guides/mcp-applications.rst:826-841` — the whole "What Gets Cached"
  block, not just the "per actor" line at `:839`: trust is now cached per
  actor/client pair, trust hit/miss statistics are now per pair, and the
  ":832 automatically cleaned up" claim becomes true only with the scheduler fix
  in this phase.
- `docs/guides/caching.md` — reconcile the composite-key and prefix-scan
  invalidation guidance (`:26-41`, `:119-144`) with what is now actually
  implemented in `mcp.py`, so the two documents agree.

### New Tests

New file `tests/test_mcp_trust_cache_key.py` (unit, no docker). The three MCP
module caches are globals, so every test clears `_token_cache`, `_actor_cache`
and `_trust_cache` in setup and teardown or results become order-dependent.
Use realistic **email-free** `token_data`, matching what
`token_manager.py:349-359` actually persists.

- **A/B/A/B/A identity sequence on one actor**: assert `MCPContext.client_id`,
  `MCPContext.peer_id` **and `MCPContext.trust_relationship.peerid`** are the
  caller's own on all five requests (research definition-of-done item 3 names all
  three fields), and that the later requests are genuine cache hits (assert
  `_cache_stats`). This is the test that must fail against the actor-keyed
  implementation.
- **Resolver call counts**: `_lookup_mcp_trust_relationship` is called exactly
  once per `(actor, client)` while entries are hot.
- **Cached `None` is per client**: a client whose trust does not resolve must not
  suppress another client's valid trust, in both orders.
- **Actor expiry evicts every tuple for that actor** and leaves another actor's
  tuples intact. Call `_cleanup_expired_cache_entries()` directly *and* add a
  separate test that the new scheduler trigger actually fires it.
- **`clear_token_from_cache` evicts every tuple for the actor** and returns the
  correct found/not-found result.
- **Eviction under concurrent mutation**: insert from a second thread while an
  eviction scan runs; assert no `RuntimeError`.
- **Async parity**: run the same identity sequence through `AsyncMCPHandler`, so
  the inherited authentication path cannot diverge later without a test failing.
- **Invariant check**: it fires on a deliberately mismatched resolution, stays
  silent for normalized-client-id peer ids and for `oauth_client_id`-matched
  rows, and the emitted record contains no email and no token data.

### Verification

- [x] `poetry run pytest tests/test_mcp_trust_cache_key.py -v` passes (12/12)
- [x] The new A/B/A/B test **fails** when `_trust_cache` is temporarily reverted
      to actor-only keys (research definition-of-done item 8 — prove the test
      has teeth, then restore) — confirmed manually: reverting
      `_trust_cache_key()` to ignore `client_id` makes
      `test_alternating_clients_never_cross` fail on request 3 with client A
      served client B's `peer_id`, and the C11 invariant check fires ERROR;
      restored and reconfirmed green
- [x] `rg -n "_trust_cache" actingweb tests` shows no remaining string-key
      assumption — the only direct-index write left in `mcp.py` is inside
      `_trust_cache_put()`, keyed by the tuple; test-file matches are
      explicit tuple keys
- [x] `poetry run pyright actingweb tests` — 0 errors, 0 warnings
- [x] `poetry run ruff check actingweb tests` passes
- [x] `make test-all-parallel` passes — 2531 passed, 26 skipped, 0 failed
- [x] Manual: run the research document's R1 reproduction script; request 3 must
      now report `peer_id` for client A — confirmed: all four requests report
      their own `client_id`/`peer_id`, `_trust_cache` holds one entry per
      `(actor_id, client_id)` tuple

### Implementation Status: Complete

**Notes:**

- Added a per-entry TTL scaffold (`_TRUST_CACHE_TTL` / `_TRUST_CACHE_NEGATIVE_TTL`,
  both `None` = no bound) as planned, so Phase 3's negative-TTL work only needs
  to set the negative constant rather than re-touch the read/write sites.
- The cleanup scheduler was changed from the dead `time.time() % 20 == 0` to a
  monotonic deadline (`_next_cleanup_at`, `_CLEANUP_INTERVAL_SECONDS = 20.0`).
  A request counter was tried first but rejected: `+=` on a module global
  under concurrent worker threads is a non-atomic read-modify-write, and would
  need a lock to stay correct. A racing double-check of `now >= _next_cleanup_at`
  across threads is harmless (cleanup is idempotent), so the deadline needs no
  lock.
- Switched the two cache-scanning sites (`_evict_trust_entries_for_actor`,
  `_cleanup_expired_cache_entries`) from `list(d)` / `list(d.items())` to
  `d.copy()` / `d.copy().items()`. Empirically, `list(d)` did not raise under
  a heavy concurrent-mutation stress test on this GIL-enabled CPython 3.14
  build (its C-level iteration loop does not yield the GIL), but `.copy()`
  gives a genuine independent-object guarantee that doesn't depend on GIL
  scheduling internals, at the same cost, so it's the safer default regardless.
- The C11 invariant check (`_check_trust_client_invariant`) is wired into both
  the hot-path and full-auth trust resolution sites, logs only `actor_id`,
  `client_id`, and the peer id's prefix segment, and never denies.
- Test-writing snag: `mock.patch.object(cls, "method", wraps=Cls.method)`
  replaces the class attribute with a `MagicMock`, which breaks descriptor
  binding — `self` is no longer auto-passed, so `wraps` silently receives one
  fewer positional argument than expected. Fixed by adding `autospec=True`,
  which restores the binding.
- A first draft of the concurrent-mutation test used an unbounded inserter
  thread racing an unbounded eviction scan; without a cap the dict grew
  without limit and the test never finished in reasonable time (observed
  multi-minute runaway before being killed). Bounded the inserter to 5000
  entries.

---

## Phase 2: Sync `resources/read` authorization (C8)

`mcp.py:982` reads `getattr(actor, "_mcp_trust_context", None)` — an attribute
**no production code writes**. It was the original mechanism, introduced in the
same commit as `_trust_cache`, and was orphaned when the MCP SDK was dropped
(`c61e059`). In a live request it is always `None`, the guard is never entered,
and control falls straight through to hook dispatch. Flask dispatches the sync
handler, so `resources/read` has had **no authorization check at all** on the
Flask path. FastAPI dispatches `AsyncMCPHandler`, which reads `RuntimeContext`
correctly (`async_mcp.py:332-334`), so it is unaffected.

This phase must not be reordered before Phase 1: turning the gate on is only
*correct* under multiple clients once the cache key is fixed.

### Changes

- `actingweb/handlers/mcp.py:982-984` — read `RuntimeContext(actor).get_mcp_context()`
  and take `peer_id` from it, mirroring `async_mcp.py:332-334` exactly.
- Keep `operation="read"` (`mcp.py:991`) so the sync and async resource paths do
  not diverge the way C9 documents for tools.
- `tests/test_mcp_permissions.py:37-40`, `tests/test_mcp_tool_visibility.py:17-19`,
  `tests/test_mcp_tool_schema_fields.py:19-21` — these three fakes set the dead
  `_mcp_trust_context` attribute themselves, so they currently exercise a code
  path that cannot occur in production. Convert them to set real runtime context.

### New Tests

- Sync `resources/read` denies with `-32003` when the peer lacks resource
  permission, and allows when it has it — the assertion that could not have been
  written before, because the check never ran.
- Sync and async `resources/read` produce the same decision for the same
  `(peer, uri)`, guarding the Flask/FastAPI divergence.
- Regression: `resources/read` with no runtime context at all does not crash.

### Verification

- [x] `poetry run pytest tests/test_mcp_permissions.py tests/test_mcp_tool_visibility.py tests/test_mcp_tool_schema_fields.py -v` passes (18/18)
- [x] `rg -n "_mcp_trust_context" actingweb tests` returns nothing — also fixed
      the fourth site not enumerated in this phase's Changes list:
      `tests/integration/test_mcp_permission_filtering.py:394` mentioned the
      attribute name in a historical-bugfix docstring; reworded without
      naming it
- [x] `poetry run pyright actingweb tests` — 0 errors, 0 warnings
- [x] `poetry run ruff check actingweb tests` passes
- [x] `make test-all-parallel` passes — 2536 passed, 26 skipped, 0 failed

### Implementation Status: Complete

**Notes:**

- Added `tests/test_mcp_resource_read_permissions.py` (5 tests): sync
  `resources/read` denies with `-32003` when the peer lacks permission and
  allows when it has it; sync/async parity on both an allowed and a denied
  peer; a no-runtime-context regression that must not crash. Verified the
  test has teeth the same way as Phase 1 — reverted `_handle_resource_read`
  to the dead `getattr(actor, "_mcp_trust_context", None)` lookup, confirmed
  `test_denies_when_peer_lacks_permission` and
  `test_denied_peer_matches_across_handlers` fail (the resource is served
  unauthorized, exactly as C8 described), then restored the fix.
- `async_mcp.py` imports `RuntimeContext` locally inside each handler method
  rather than at module scope, so the async-side test patches
  `actingweb.runtime_context.RuntimeContext` (the source module) rather than
  `actingweb.handlers.async_mcp.RuntimeContext` (which doesn't exist as a
  module-level name and would fail the patch).
- The three converted test fakes (`test_mcp_permissions.py`,
  `test_mcp_tool_visibility.py`, `test_mcp_tool_schema_fields.py`) had never
  actually depended on `_mcp_trust_context` for their assertions — all three
  already mocked `RuntimeContext` for the paths they exercise (`tools/list`,
  `tools/call`, `prompts/list`/`get`), so the attribute was already dead
  weight on the fakes. Removed rather than converted to setting real context.

---

## Phase 3: Exact trust matching and fail-closed authorization

Two coupled changes: make the resolver match exactly, then stop treating
"no resolvable trust" as "no permission checks". They are coupled because
tightening the matcher without fixing the fail-open would silently *widen*
access for rows that stop matching.

### Changes

- `actingweb/handlers/mcp.py:1441-1455` — delete the dead `if user_email:`
  block. The persisted token record contains no `email` or `user_email` key
  (`token_manager.py:349-359`, `:997-1007`), so this branch has never executed on
  the live path, and its constructed `oauth2:` prefix would have been wrong
  anyway since both live creation paths pass `established_via="oauth2_client"`.
- `actingweb/handlers/mcp.py:1457-1500` — replace the three substring branches
  with, in order:
  1. exact `getattr(trust, "oauth_client_id", None) == client_id`;
  2. an exact peer-id fallback for rows where `oauth_client_id` is `None`,
     which **must** require `established_via` to be an OAuth2-family value (or
     `None` with an `oauth2`/`oauth2_client` peer-id prefix, preserving today's
     legacy branch) **and** full-string equality against a constructed
     candidate, applying the same normalization trust creation applies
     (`trust_manager.py:455-460`). No containment, no bare segment compare.
  A trust row created through the ordinary `/trust` peer protocol with a crafted
  peer id must not be able to satisfy either arm.
- `actingweb/handlers/mcp.py:1502-1504` — the "permissions will be empty"
  warning describes the old fail-open world and becomes actively misleading.
  Replace with an actionable WARNING naming `actor_id` and `client_id` and the
  likely cause (`established_via` / `oauth_client_id` on the trust row) — again
  without logging the raw peer id or token data.
- `actingweb/oauth2_server/oauth2_server.py:378-381` — remove the unreachable
  `else: established_via = "oauth2_interactive"` branch (see Decisions Made:
  `flow_type` is necessarily `"mcp_oauth2"` at that point). Removing it makes the
  invariant legible rather than leaving a branch that implies interactive trusts
  can reach the MCP path. **No `oauth2_interactive` resolver branch is added** —
  it would be unreachable code at an authorization boundary.
- **Fail-closed, in both handlers in the same commit.** Sync gates:
  `mcp.py:515`, `:674`, `:743`, `:803`, `:880`, `:984`. Async gates:
  `async_mcp.py:148`, `:230`, `:335`. Shipping one without the other recreates
  exactly the Flask/FastAPI divergence C9 warns about.
  - **Pin the predicate explicitly**: deny when no trust relationship resolved,
    i.e. treat a falsy `peer_id` as denial rather than as "skip the check".
    Several existing tests set `mock_mcp_context.peer_id = None` and depend on
    gates being skipped — `tests/test_mcp_tool_visibility.py:75`, `:162`, `:234`
    and `tests/test_mcp_tool_schema_fields.py:32`. Enumerate and update them; do
    not let a truthy `Mock` attribute accidentally satisfy the new predicate.
  - **Position the denial so the availability fail-open cannot intercept it.**
    Every gate being changed sits inside a `try:` whose `except` says "Don't
    block execution if permission system not initialized; log and continue"
    (`mcp.py:815-816`, `:895-896`, `:999-1000`, and the async equivalents). If
    the no-trust denial is raised from inside that block — or is reached via
    anything that raises — the change silently reverts to fail-open. The denial
    must be an explicit early `return` of the JSON-RPC error evaluated
    **before** the evaluator is imported or constructed, outside the guarded
    region.
  - Keep the existing fail-open on **evaluator exceptions**
    (`mcp.py:529-533`, and the `except` blocks at `mcp.py:816`, `:896`, `:1000`,
    `async_mcp.py`) so a permission-subsystem outage does not hard-lock
    deployments. The two policies now sit side by side deliberately; comment
    them as such.
  - Give the no-trust denial **distinguishable** `-32003` text ("no trust
    relationship resolved for this client") versus the policy denial ("you don't
    have permission to use tool X"). Today they are byte-identical, so an
    operator cannot tell a broken trust row from a permissions-config problem.
- **Give cached `None` a short negative TTL** using the `cached_at` stamp added
  in Phase 1. Under fail-closed, a transient miss — notably DynamoDB eventual
  consistency on the very first request after registration — would otherwise pin
  a denial for the full 5-minute window. A short negative TTL (or not caching
  `None` at all) bounds that to seconds.
- `actingweb/handlers/mcp.py:806` vs `actingweb/handlers/async_mcp.py:155` —
  align the `operation=` string for `tools/call` (`"use"` vs `"invoke"`, C9).
  Currently unread because every shipped trust type expresses `tools` in the
  `{"allowed": [...], "denied": [...]}` form, but it becomes a live
  Flask-vs-FastAPI divergence the moment an application defines a
  patterns/operations rule. Pick `"use"` (matches `tools/list` at `mcp.py:522`).

### New Tests

- Exact `oauth_client_id` match resolves; a *different* client's row on the same
  actor does not.
- The peer-id fallback resolves a legacy row with `oauth_client_id=None`, and
  **rejects** a crafted peer id that merely contains or ends with the client id,
  and rejects a row whose `established_via` is outside the OAuth2 family.
- Client-id normalization round-trips: a client id containing `@`, `.` or `:`
  matches its normalized peer id.
- Fail-closed: valid token, no resolvable trust →
  `tools/list` / `resources/list` / `prompts/list` are empty and
  `tools/call` / `prompts/get` / `resources/read` return `-32003` with the
  no-trust message — asserted on **both** `MCPHandler` and `AsyncMCPHandler`.
- Fail-open preserved: an evaluator that raises does not deny.
- **The no-trust denial survives a broken permission subsystem**: with evaluator
  import/construction forced to raise, a no-trust request is still denied. This
  is the test that catches the denial being placed inside the availability
  `except` and silently reverting to fail-open.
- Negative-TTL: a cached `None` is re-resolved after the negative TTL rather
  than after the full token TTL.
- `oauth2_interactive` reachability assertion, per whichever way that question
  resolves.
- The dead `user_email` branch is gone: `rg` assertion or a test that
  `token_data` containing an `email` key does not change resolution.

### Verification

- [x] `poetry run pytest tests/ -k "mcp" -v` passes (232/232)
- [x] `poetry run pyright actingweb tests` — 0 errors, 0 warnings
- [x] `poetry run ruff check actingweb tests` passes
- [x] `make test-all-parallel` passes — 2559 passed, 26 skipped, 0 failed
- [x] Manual: confirm sync and async handlers return the same decision for the
      same `(peer, tool)` and the same `(peer, uri)` — confirmed with a
      standalone script exercising `tools/call` and `resources/read` under
      both an allowed and a denied peer: `-32003`/success and error codes
      matched on every case. Along the way found (and fixed, since it's a
      one-line change on lines I was already touching) a pre-existing
      wording mismatch — async said "read resource", sync said "access
      resource" — now aligned. Also found a pre-existing, unrelated
      formatting divergence in the *content* of a successful
      `resources/read` (sync uses `json.dumps(result, indent=2)`, async uses
      `str(result)` for dict results), which is a serialization bug, not a
      permission-decision divergence; out of this plan's scope, recorded in
      `thoughts/todo/mcp-cache-lifecycle-and-revocation.md`.

### Implementation Status: Complete

**Notes:**

- Added `_require_mcp_peer_id(actor, request_id)` to `MCPHandler`, shared by
  both sync and async single-item gates (`tools/call`, `prompts/get`,
  `resources/read`) so the two transports cannot diverge on the no-trust
  decision. Since it's defined in `mcp.py`, it resolves `RuntimeContext` via
  that module's own import regardless of which subclass calls it — the three
  async handler methods no longer need their own local `RuntimeContext`
  import.
- The three `*/list` handlers (`tools/list`, `resources/list`,
  `prompts/list`) fail closed to an empty result *before* the fail-open
  evaluator try/except, mirroring the single-item gates' placement
  discipline.
- Resolver rewrite: arm 1 is exact `oauth_client_id == client_id` (covers
  every trust row created by either live MCP creation path, both of which
  set this field). Arm 2 is a legacy-row fallback for rows predating that
  field — gated on an OAuth2-family `established_via` (or `None` with a
  legacy `oauth2`/`oauth2_client` peer-id prefix) *and* full-string equality
  against a peer id reconstructed the way trust creation would build it when
  email equals client_id (the only case reconstructable without knowing the
  real email, which MCP token records never carry). Legacy rows created via
  the interactive-authorize flow with a real email and no `oauth_client_id`
  remain an accepted, documented lockout risk (see migration guide, Phase 5).
- Deleted the unreachable `else: established_via = "oauth2_interactive"` in
  `oauth2_server.py`'s `handle_oauth_callback`, after independently
  re-verifying the reachability chain at current line numbers (not just
  trusting the plan's citation): `extract_mcp_context()` returns `None`
  (and the caller already returned) unless `flow_type == "mcp_oauth2"`
  (`state_manager.py:184`), so the `if` branch always fires. Added
  `TestOAuth2InteractiveReachability` to assert this invariant directly
  against the real `OAuth2StateManager` rather than only removing the branch.
- Set `_TRUST_CACHE_NEGATIVE_TTL = 10.0` (was the Phase 1 `None` scaffold).
- **Placement-discriminator tests were verified with the same teeth-proving
  discipline as Phases 1–2**: for `TestNoTrustDenialSurvivesBrokenEvaluator`,
  a first mutation (moving the whole check inside the try, computed *before*
  the raising call) still passed — a `return` inside `try` is not intercepted
  by `except`, so that mutation didn't reproduce the risk. A second mutation
  (constructing the evaluator, which raises, *before* the no-trust check,
  both inside the same try) correctly made the test fail exactly as C9's
  concern describes; restored afterward. This is worth remembering for any
  future placement test: the exception must be reachable *before* the
  denial's `return`, not just structurally nested near it.
- A large batch of existing tests depended on `peer_id = None` meaning "skip
  the permission gate" for reasons unrelated to permissions (testing
  `visibility_predicate`/`description_predicate` filtering, or async
  execution mechanics like same-event-loop dispatch and concurrency). Fixed
  by giving them a resolved peer id plus an allow-everything evaluator mock,
  rather than changing what they assert:
  `tests/test_mcp_tool_visibility.py`, `tests/test_mcp_tool_schema_fields.py`,
  `tests/test_async_mcp_handler.py` (6 tests), `tests/test_mcp_tool_result_format.py`
  (1 test). `tests/test_mcp_resource_read_permissions.py`'s
  `test_no_runtime_context_does_not_crash` was inverted per the plan's own
  design — it now asserts the fail-closed `-32003` denial (renamed
  `test_no_trust_denies_without_crashing`) rather than asserting success,
  since "no runtime context" and "no trust" are the same case now.
- New test file `tests/test_mcp_fail_closed_authorization.py` (23 tests):
  exact-resolver-matching (8), fail-closed across all six gates on both
  handlers (10), fail-open-preserved-on-evaluator-error (1),
  denial-survives-broken-evaluator (1), negative TTL (2),
  oauth2_interactive reachability (1).

---

## Phase 4: Request-scoped `RuntimeContext` via ContextVars

`RuntimeContext` stores a mutable dict as an attribute on the actor
(`runtime_context.py:46`, `:125-129`) while the MCP actor cache deliberately
hands the **same** `ActorInterface` object to every request for a hot actor. No
production code clears it. The research reproduced cross-request identity leaks
deterministically in both the asyncio and the threaded model. This phase is
independent of Phases 1–3 and does not gate them, but Phase 2's `resources/read`
gate inherits the race until this lands — so 2 and 4 should ship in the same
release.

### Changes

- `actingweb/runtime_context.py` — move storage from the actor attribute to a
  module-level `ContextVar`, keeping the public API (`RuntimeContext(actor)`,
  `set_mcp_context`, `get_mcp_context`, `get_oauth2_context`, `get_web_context`,
  `get_request_type`, `get_custom_context`, `clear_context`, and the module-level
  `get_client_info_from_context`) byte-identical.
  - **Key the stored value by actor id**, not a single flat slot. A flat
    ContextVar would make `RuntimeContext(other_actor).get_mcp_context()` return
    the *current* request's context instead of `None`. Keying by `actor.id` also
    fixes the existing set-on-`ActorInterface` / read-on-`CoreActor` asymmetry,
    which is a silent improvement worth its own test.
  - **Store immutable values**; replace rather than mutate. A copied context
    shares the same object, so in-place mutation would leak across copies.
  - **No attribute-storage fallback.** Any read path that falls back to the
    shared actor attribute reopens the leak; the migration must be total, and the
    cached `ActorInterface` must carry no per-request state afterwards.
- `actingweb/interface/hooks.py:562-564` — `executor.submit(asyncio.run, hook(*args, **kwargs))`
  runs on a bare `ThreadPoolExecutor` with no `copy_context()`, so ContextVars
  set on the calling thread are invisible inside. Today's attribute storage
  survives that hop because the actor travels in `*args`; the rewrite regresses
  it unless fixed here. The fix shape matters: capture
  `ctx = contextvars.copy_context()` and submit `ctx.run` — wrapping only the
  coroutine creation does nothing, because a Task binds its context at creation
  *inside* the worker thread. The sibling `except RuntimeError` branch at `:567`
  is already fine.
- `actingweb/interface/integrations/flask_integration.py:102-115` — `after_request`
  does not run when an unhandled exception propagates, and no `teardown_request`
  is registered. On a reused WSGI worker thread that is exactly where a missing
  reset leaks into the next request. Register a `teardown_request` (or equivalent
  `finally`) that clears runtime context on success *and* exception paths.
- `actingweb/interface/integrations/fastapi_integration.py:474-476` — the
  middleware `finally` clears only `request_context` vars; add the new runtime
  context vars. Preserve the existing `copy_context()` propagation into executor
  work (`:538-573`).
- `actingweb/runtime_context.py:1-37`, `:113`, `:268-275` — the module docstring
  describes attribute-on-actor storage and promises cleanup that never happens.
  Rewrite to describe what the code now does.
- `docs/guides/hooks.rst:304` — "The runtime context is request-scoped and
  automatically managed by the framework" becomes true **in this phase and not
  before**. Update `hooks.rst:255-320` as a unit, including the `:316-319`
  per-credential caveat block, and document the one real semantic change for app
  developers: `set_custom_context` data currently persists on the hot cached
  actor across requests and will now be per-request.

### New Tests

- **Deterministic asyncio isolation**: request A sets context, yields at an
  `await`, request B overwrites in its own task, A resumes and must still read
  A's peer. (Research script R2 is the skeleton.)
- **Deterministic threaded isolation**: the same via a `threading.Barrier`,
  modelling Flask/WSGI.
- **Async MCP hook that reads context after an `await`** returns its own
  request's identity — the real suspension point on FastAPI
  (`async_mcp.py:180`, `:261`, `:383`).
- **Executor hop**: an async hook dispatched through `interface/hooks.py:562`
  sees the caller's context.
- **Two actor objects in one request**: asking for actor X's context does not
  return actor Y's.
- **End-of-request cleanup on both success and exception paths**, per
  integration — a reused worker thread must not observe the previous request's
  context.
- **Per-test reset fixture** for `tests/integration/test_runtime_context_advanced.py`:
  execution-local state now persists across tests within a pytest worker thread
  unless reset.

### Verification

- [x] `poetry run pytest tests/test_runtime_context_unit.py tests/integration/test_runtime_context_advanced.py -v` passes (5/5, 13/13)
- [x] `poetry run pytest tests/ -k "mcp" -v` passes (232/232)
- [x] `poetry run pyright actingweb tests` — 0 errors, 0 warnings
- [x] `poetry run ruff check actingweb tests` passes
- [x] `make test-all-parallel` passes — 2572 passed, 26 skipped, 0 failed
      (up from 2559 in Phase 3 — the 13 new isolation/teardown tests), and
      again sequentially (`make test-integration`) since this phase changes
      concurrency semantics — 756 passed, 8 skipped, 0 failed
- [x] Manual: ran the research document's R2 reproduction script against the
      ContextVar implementation; both the asyncio and threaded scenarios
      report OK — `RESULT: ALL OK`

### Implementation Status: Complete

**Notes:**

- `RuntimeContext` storage is now a module-level
  `ContextVar[dict[str, dict[str, Any]] | None]` (`_runtime_context_var`),
  keyed by `_actor_key(actor)` — `str(actor.id)` when the actor has an id,
  else `f"_no_id_{id(actor)}"` for the unsaved-actor edge case (matches the
  old attribute-storage behavior for that one case, since there's no stable
  identity to key on yet). The value is treated as immutable: every write
  path (`_set_context_data`, `clear_context`) builds a *new* outer dict and
  a *new* per-actor dict via `dict(...)` rather than mutating in place,
  because a context snapshot captured by `copy_context()` shares the same
  dict objects as its parent — in-place mutation would cross that boundary.
  Ruff's `B039` flagged a first draft that used a mutable `{}` `ContextVar`
  default (the single shared sentinel object every un-set context would
  return); fixed by defaulting to `None` and normalizing via a
  `_all_contexts()` helper.
- Added `runtime_context.clear_all_context()` — a module-level "reset this
  thread's/task's own view to empty" used by Flask's new
  `teardown_request`, FastAPI's middleware `finally`, and test fixtures.
  Framework code doesn't generally know which actor id(s) a request
  touched, so a blanket per-thread/task reset is the natural granularity
  (and it's cheap: `.set({})`, not a scan).
- `hooks.py:562`'s executor hop (`_execute_hook_in_sync_context`'s
  thread-pool branch) now does
  `ctx = contextvars.copy_context()` on the calling thread, then
  `executor.submit(ctx.run, asyncio.run, hook(*args, **kwargs))`. Confirmed
  by mutation: reverting to the bare `executor.submit(asyncio.run,
  hook(*args, **kwargs))` makes
  `TestExecutorHopIsolation::test_async_lifecycle_hook_sees_callers_context`
  fail (`seen == [None]` instead of the caller's peer id); restored and
  reconfirmed green.
- Flask: added `teardown_request` (not `after_request`, which does not run
  when a view raises) that calls `runtime_context.clear_all_context()`.
  Confirmed by mutation: removing the `teardown_request` registration
  makes all three `TestFlaskRuntimeContextTeardown` tests fail (context
  survives a successful request, survives an exception, and leaks into a
  second request on the same thread); restored and reconfirmed green.
- FastAPI: added the same `runtime_context.clear_all_context()` call to
  `RequestContextMiddleware`'s existing `finally`. This one needed a more
  careful teeth-proof: Starlette's `BaseHTTPMiddleware` runs `call_next()`
  in its own child `asyncio` task, so `RuntimeContext` set deep inside a
  real handler already lives in a context that's discarded when that child
  task completes — the end-to-end `TestClient`-based tests
  (`test_runtime_context_cleared_after_successful_request`,
  `test_runtime_context_cleared_after_exception`) pass identically whether
  or not the middleware's own clearing line is present, because Starlette's
  task boundary already isolates them. Wrote one additional test
  (`test_dispatch_finally_clears_context_set_in_same_task`) that calls
  `RequestContextMiddleware.dispatch()` directly with a `call_next` that
  runs inline in the *same* task (bypassing `BaseHTTPMiddleware`'s
  task-spawning `__call__`), which does fail when the clearing line is
  removed and passes when it's present — confirmed both ways. Documented
  in-line why the middleware's own clearing is defense-in-depth rather than
  the primary isolation mechanism on the FastAPI side, unlike Flask where
  `teardown_request` is load-bearing (worker-thread reuse has no equivalent
  automatic boundary).
- Two-actor-objects test added the case the plan called out by name: a
  `Wrapper` object and the `SharedActor` (`CoreActor` stand-in) it wraps,
  both with the same `.id`, now observe the *same* context — the asymmetry
  fix. And two objects with different ids never share context.
- Per-test reset fixture added to
  `tests/integration/test_runtime_context_advanced.py` (`autouse`,
  `clear_all_context()` before and after each test) and to the new
  `tests/test_runtime_context_isolation.py`. In practice the integration
  tests didn't collide even without it (each test creates a fresh actor
  with a unique DB-assigned id), but the fixture matches production
  discipline and guards against future tests that reuse a fixed id.
- New test file `tests/test_runtime_context_isolation.py` (7 tests):
  asyncio interleaving (2, including the R2 skeleton and an
  async-hook-reads-after-await variant), threaded isolation (2, including
  a reused-worker-thread scenario), two-actor-objects (2), executor-hop (1,
  via the real `HookRegistry.execute_lifecycle_hooks` public API rather
  than a hand-rolled copy of the fix). Plus 6 new tests split across
  `tests/test_flask_context_integration.py` (3) and
  `tests/test_fastapi_context_integration.py` (3) for end-of-request
  cleanup.
- `docs/guides/hooks.rst`: updated the "request-scoped and automatically
  managed" line to describe the ContextVar mechanism, and added a `.. note::`
  documenting the one real semantic change for app developers:
  `set_custom_context()` data no longer persists across requests on a hot
  cached actor — it's genuinely per-request now.

---

## Phase 5: Documentation, changelog, and merge to master

Per `CLAUDE.md`, releases are decoupled from PRs: contributors add an
`Unreleased` entry and **no version bump**; maintainers bump, rename and tag as a
separate step, and tags may only be cut from master. This phase is everything
that happens on `bug/trust_mcp_cache` before the PR merges.

### Changes

- `CHANGELOG.rst` — fill the empty `Unreleased` section (do **not** rename it or
  bump any version here). Follow the rc2 entry's precedent
  (`CHANGELOG.rst:16-26`) of a prominent `.. note::` for re-validation. The
  security note must state:
  - the authorization bypass, affected versions (3.3 → 3.13.0rc2, ~10 months),
    and that operators cannot detect past exploitation from the library alone;
  - that `resources/read` was **unauthorized on the Flask path** and is now
    checked — FastAPI deployments were never exposed;
  - that missing trust is now fail-closed;
  - that trust-row metadata (`client_name`, `client_version`, `client_platform`,
    `last_accessed`, `last_connected_via`) written during the affected window is
    unreliable, and that current values self-heal on each client's next request
    while audit history does not;
  - the still-open 5-minute stale-positive window on token revocation and trust
    modification (deferred, C6/C7).
- `docs/migration/v3.13.rst` — a concrete pre-upgrade checklist, because a
  CHANGELOG note alone is not enough for the resolver change:
  - a query to find at-risk trust rows (`oauth_client_id` is `None`, or
    `established_via` outside the OAuth2 family, or a peer id not in the
    three-segment `source:email:client` shape);
  - Flask + resource hooks → audit resource URIs against the trust type's
    `resources.patterns`. The default `mcp_client` type only allows
    `public/*`, `shared/*`, `notes://*`, `usage://*`,
    `actingweb://properties/all` (`trust_type_registry.py:422-437`), so an app
    serving custom URIs has been working *because* the check was dead;
  - **the orphaning consequence**: a client whose legacy row stops resolving
    re-authenticates into a *new* trust row with a newly constructed peer id, and
    per-peer permission overrides are keyed `{actor_id}:{peer_id}`
    (`trust_permissions.py:68`, `:86`) — so customized permissions attached to
    the old peer id are silently abandoned and the client reverts to trust-type
    defaults. Name this explicitly; it is the change most likely to surprise;
  - note that `oauth_client_id` backfill happens on OAuth re-authorization
    (`trust_manager.py:505-507`), not on token validation, so between upgrade and
    re-auth resolution rests entirely on the peer-id fallback.
- `docs/guides/troubleshooting.rst` — new entry: "MCP client sees an empty tool
  list or `-32003` after upgrading", pointing at the no-trust WARNING and the
  migration checklist.
- `docs/guides/mcp-quickstart.rst:107-119` — one line noting that an empty
  `tools/list` now means no trust resolved, since that page is where a locked-out
  operator lands first.
- `docs/reference/security.rst` — reference the affected-version window and the
  unreliable audit-trail fields.
- `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` — record the deferred
  work: revocation paths that never evict (C7), cross-process invalidation,
  explicit trust-freshness policy (C6), the `Mcp-Session-Id`-keyed client-info
  cache as a known residual cross-client channel for `clientInfo`, the
  substring/`endswith` peer-id matching still present in
  `client_registry.py:513-525` (deletion path), registration not hard-failing
  when trust creation fails, and module-global cache keys assuming one
  application per interpreter.

### New Tests

No new tests — this phase is documentation. The gate is that every prior phase's
suite passes together.

### Verification

- [x] `make test-all-parallel` passes — 2572 passed, 26 skipped, 0 failed
- [x] `make test-integration` passes sequentially — 756 passed, 8 skipped,
      0 failed
- [x] `poetry run pyright actingweb tests` — 0 errors, 0 warnings
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry build` succeeds — built `actingweb-3.13.0rc2.tar.gz` and
      `actingweb-3.13.0rc2-py3-none-any.whl`
- [x] `pyproject.toml` and `actingweb/__init__.py` still read `3.13.0rc2` — no
      version bump on the branch
- [x] **Acceptance probe (manual, required — before merge):** re-ran the
      consumer's escalation scenario end-to-end against real actor storage
      (DynamoDB Local via `docker_services`), not the unit-test fakes: one
      real actor, two real MCP clients registered via
      `OAuth2ClientManager.create_client()` with genuinely different trust
      types (`viewer` vs `mcp_client`), driven through the real
      `MCPHandler.post()` JSON-RPC dispatch (only the token-validation
      boundary mocked). Confirmed: the read-only (`viewer`) client's
      `tools/list` size is unchanged after the read-write (`mcp_client`)
      client authenticates on the same actor immediately after it; the
      read-only client's `tools/call` on a write-shaped tool
      (`create_note`, in `mcp_client`'s allowed tool patterns but denied by
      `viewer`'s `tools: {"denied": ["*"]}`) is refused with `-32003`; the
      read-write client's identical call succeeds. Written as a throwaway
      pytest file (`tests/integration/_tmp_acceptance_probe_test.py`), run
      once, then deleted — per this section's own "No new tests" note, this
      phase does not add to the permanent suite.
- [ ] PR opened and merged to master

### Implementation Status: In Progress (all steps complete except the PR)

**Notes:**

- Verified on 2026-07-31 —
  `thoughts/verifications/2026-07-31-mcp-trust-cache-crosses-clients.md`.
  That verification covers Phases 1–4 in full plus this phase's code and
  documentation; the plan stays `status: active` (and carries no `verified:`
  back-link) because the PR and Phase 6 are still open.
- Three defects found during verification and fixed in place, all within this
  phase's remit: (1) `ruff format` drift in two Phase 4 test files — root
  cause is that every phase's checklist above lists `ruff check` but never
  `ruff format --check`; (2) a Sphinx docstring regression introduced by
  Phase 4's `runtime_context.py` rewrite (multi-line bullets under
  `Architecture Problem:` / `Solution:` / `Concurrency notes:` with no blank
  line, which docutils mis-parses — proven a regression by parsing the base
  commit's docstring, which is clean; docs build went 10 messages → 0);
  (3) `CHANGELOG.rst` had **no** entry for Phase 4 at all, so the
  `set_custom_context()` behavior change — which can break application code
  silently on upgrade — was documented only in `hooks.rst`. A `CHANGED`
  section now covers it plus the async `tools/call` `operation` alignment.

---

## Phase 6: Cut `v3.13.0rc3` from master

Maintainer step, on master after the PR merges. Listed as its own phase because
it must not happen on the feature branch.

### Changes

- `CHANGELOG.rst` — rename `Unreleased` to `v3.13.0rc3: <date>` and open a fresh
  empty `Unreleased` above it.
- `pyproject.toml:3` and `actingweb/__init__.py:1` — `3.13.0rc2` → `3.13.0rc3`.
- Commit `Pre-release v3.13.0rc3`, tag `v3.13.0rc3`, push commit and tag.
  GitHub Actions validates the version, runs tests, publishes to **TestPyPI**
  (pre-release versions do not go to production PyPI), and creates a GitHub
  Release marked pre-release.

### New Tests

None — release mechanics.

### Verification

- [ ] On master, working tree clean, all prior phases merged
- [ ] Version strings in `pyproject.toml`, `actingweb/__init__.py`, and the tag
      all read `3.13.0rc3`
- [ ] `make test-all-parallel` passes on master before tagging
- [ ] GitHub Actions run is green and the TestPyPI upload succeeded
- [ ] Manual: consumer installs from TestPyPI and re-runs the escalation probe
      against the published artifact before any final `v3.13.0` is cut

### Implementation Status: Not Started

---

## Evaluation Notes

Four evaluators reviewed the proposed changes against the codebase in parallel.
Their findings are folded into the phases above; this section records what was
raised and where it landed.

### Architecture

- **No aliasing risk on the tuple key.** `_trust_cache` is referenced only in
  `actingweb/handlers/mcp.py`; `async_mcp.py` never imports the cache names and
  inherits the sync `authenticate_and_get_actor_cached()` (`async_mcp.py:75`), so
  one change site covers both transports. Zero test references to any of the
  three caches today, so nothing else can break on the key type.
- **Eviction becomes an unlocked key scan** — folded into Phase 1 as a snapshot
  iteration.
- **The `:152-155` eviction site is production-dead code** because of the float
  modulo at `:1222` — the scheduler fix moved into Phase 1 rather than being
  deferred with the rest of C6/C7.
- **The invariant check needs format awareness** (normalized client ids exist in
  peer ids) or it emits spurious ERRORs — folded into Phase 1.
- **Fail-closed must land in the async gates too**, and the predicate must be
  pinned because several existing tests set `peer_id = None` and rely on gates
  being skipped — folded into Phase 3 with the affected test files enumerated.
- **The `hooks.py` fix shape**: `executor.submit(ctx.run, asyncio.run, coro)`,
  not merely wrapping the coroutine — folded into Phase 4.
- **Docs list was incomplete** — `mcp.py:43-45`, the `:1210-1219` docstring,
  `runtime_context.py:1-37`, `mcp-applications.rst:826-833`, and
  `docs/migration/v3.13.rst` were added.
- Flagged that dropping research Patch 5 should be an explicit decision, not
  silence — hence the explicit "What We're NOT Doing" section and the
  `thoughts/todo/` entry created in Phase 5.

### Security

- **The tuple key closes the demonstrated bypass**; downstream permission caches
  are already correctly keyed `f"{actor_id}:{peer_id}"`, so there is no
  second-order pollution.
- **The peer-id fallback is the weak point** — client ids are public
  identifiers, so a crafted peer id from the ordinary `/trust` protocol could
  occupy the slot if the fallback matched on containment or a bare segment. The
  fallback is now specified as `established_via`-gated plus full-string equality.
- **Fail-closed does not break the OAuth flow itself**: trust is created *before*
  code/token issuance on both live paths (`client_registry.py:441-453`,
  `oauth2_server.py:379-401`), and the DCR/authorize/token endpoints never
  traverse the MCP trust resolver. But **swallowed trust-creation failures become
  permanent lockouts** (those clients get full fail-open access today), and
  DynamoDB eventual consistency can produce a transient `None` — hence the
  negative TTL and the registration hard-fail item in Phase 3.
- **`peer_approved` is not checked by the resolver**, so fail-closed still does
  not gate on approval state. Noted, not changed.
- **The ERROR log would leak user emails** (live peer ids embed them) — Phase 1
  logs only the peer-id prefix segment.
- **No attribute-storage fallback** in the ContextVar migration, and reset must
  be `finally`-grade across exception exits — folded into Phase 4.
- **Eviction consistency is safe**: leaving other clients' token-cache entries
  valid while evicting their trust tuples is harmless, because the hot path
  requires an `_actor_cache` hit and the actor is evicted too.
- **`_mcp_client_info_cache` is a residual cross-client channel** keyed by a
  client-supplied header — explicitly out of scope, recorded in
  `thoughts/todo/`.

### Scalability

- **Tuple keys multiply trust-cache misses by clients-per-actor.** Each miss is
  one strongly-consistent DynamoDB Query (or full PostgreSQL SELECT) returning
  *every* trust row for the actor. Bounded acceptably by the 5-minute token TTL
  — roughly one full-list query per client per 5 minutes per process. Severity
  low-medium; accepted.
- **Accumulation is the real memory issue**, since cleanup is inert and trust
  entries carry no timestamp — resolved by pulling both the scheduler fix and
  the `cached_at` stamp into Phase 1.
- **Eviction scan cost is fine** (a 100k-entry dict scans in milliseconds at a
  logout-frequency event); a secondary actor-id index was rejected as adding
  invalidation bugs for negligible gain.
- **ContextVar overhead is negligible** (~100ns, comparable to the current
  `getattr`/`hasattr` dance) and is a **memory improvement**: the context dict —
  including `token_data` and trust references — is currently pinned on the
  cached `ActorInterface` indefinitely.
- **Thundering herd on actor-wide eviction is small and self-limiting**;
  accepted rather than adding single-flight machinery.
- Suggested making a direct-key `get_relationship` the primary matcher to
  collapse the O(n) scan — **not adopted**, because it is blocked on the email
  not being present in `token_data` (C3). Recorded as future work.

### Usability

- **Three populations were flagged as lockout risks under fail-closed.** One is
  now resolved: `oauth2_interactive` trusts were traced and provably cannot back
  an MCP access token (see Decisions Made), so no lockout exists and no resolver
  branch is added. The other two stand and are handled by the migration
  checklist: rows predating `oauth_client_id` (pre-3.3, copied verbatim by the
  PostgreSQL migration script), and deployments relying on the "permission system
  not initialized" fail-open (explicitly preserved).
- **Flask `resources/read` breakage is likely real, not theoretical** — the
  default `mcp_client` type allows a narrow resource pattern set, and apps
  serving custom URIs have worked only because the check was dead. Hence the
  audit step in the migration checklist.
- **The deny path was not debuggable**: identical `-32003` text for "no trust"
  and "policy denied", and for `tools/list` the no-trust case is not an error at
  all — the client just sees zero tools. The only diagnostic log is throttled by
  the cache TTL and its "permissions will be empty" wording describes the old
  fail-open world. Fixed in Phase 3 with distinguishable messages and an
  actionable WARNING.
- **"Self-heals" was oversold**: `oauth_client_id` backfill requires
  re-authorization, not merely the next request, and non-standard peer ids heal
  by *orphaning* the old row — which drops per-peer permission overrides keyed by
  the old peer id. Both are now called out in the migration guide.
- **The public `RuntimeContext` API is safe to keep**: the reference consumer
  uses only read paths inside request-scoped hooks. Two footnotes added — the
  `actor` argument's new meaning, and the consumer-side version of the
  background-thread context-loss pattern.
- Docs list extended with `troubleshooting.rst`, `mcp-quickstart.rst`,
  `security.rst`, and `docs/migration/v3.13.rst`.
