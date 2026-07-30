# MCP trust cache crosses client identities: report validated, immediate fix correct, request context still unsafe

**Date:** 2026-07-30
**Branch:** `master`
**Commit:** `cc29c03` (`v3.13.0rc2`, tagged 2026-07-26; working tree clean)
**Input:** `../actingweb_mcp/thoughts/todo/2026-07-29-mcp-trust-cache-crosses-clients.md`
(original report) and `../actingweb_mcp/thoughts/todo/2026-07-30-trust-cache-security-audit.md`
(blast-radius audit, `severity: HIGH`, one demonstrated authorization bypass)
**Report status at intake:** open ActingWeb library bug, found during live MCP
testing of consumer PR #242 (agent-run lifecycle)
**Consumer state inspected:** `../actingweb_mcp` on
`feat/agent-run-lifecycle-and-parallel-runs`; that working tree has uncommitted
changes, so its live-test measurements are treated as supplied evidence rather
than independently reproduced here.

> **Validation pass, same day.** Every claim below was re-derived from source at
> `cc29c03`, both central defects were reproduced in-process, and the reasoning
> was cross-checked against external primary sources. The result kept the
> original conclusions on C1, C2, C4 and C5, **corrected two claims** (C3 and the
> async-suspension framing), and added **five findings** the first pass did not
> cover: C6-C10 below. Sections marked *(validated)* were re-verified; sections
> marked *(new)* are additions.

## Research Question

Is the consumer bug report real; is `(actor_id, client_id)` the right repair;
and what else on the same code path is load-bearing for that fix?

## Executive conclusion *(validated)*

The reported cache defect is real, high severity, and caused by exactly the key
cardinality mismatch described in the report. `validate_mcp_token()` returns
`(actor_id, client_id, token_data)`, the trust resolver uses the client identity,
and trust persistence deliberately creates one relationship per client. The
cache then throws away `client_id` and stores the result under `actor_id` alone.

**Reproduced sequentially, in-process, with no concurrency required** (see C1).
That separation matters: C1 and C4 are independently actionable defects, and the
cache bug does not need overlapping requests to fire.

**Severity is authorization bypass, not misattribution.** The consumer's
blast-radius audit demonstrated a client registered with a read-only trust type
performing a write immediately after a read-write client authenticated on the
same actor. Validation traces the whole chain inside the library — per-client
trust types are a library feature (`client_registry.py:68`), the trust type is
stored as the trust row's `relationship`, and permission evaluation resolves
that `relationship` *from the peer id* (`permission_evaluator.py:471-478`). A
poisoned `peer_id` therefore selects a different permission rule set. No
application defect is in that path (C11). Two further consequences follow: the
exposure window is not the nominal five minutes but unbounded on a
continuously-accessed actor (C6), and the poisoned identity is written durably
into the *other* client's trust record on every request carrying `clientInfo`
(C12).

The proposed `(actor_id, client_id)` key is the correct immediate fix. It matches
the domain identity, follows this repository's documented composite-key cache
pattern, matches the MCP specification's own normative keying rule for
server-side state (see External References), and has a small blast radius. It
should ship with a focused regression test and should not wait for a larger
cache rewrite.

It does **not** make MCP identity request-safe under concurrency. The actor cache
returns one shared `ActorInterface` for an actor, and `RuntimeContext` stores
request identity by mutating that shared object. Deterministic reproductions in
**both** the asyncio and the threaded model make request A read request B's peer.
The report's 60-request test not observing that race is useful evidence about one
workload, but it does not establish an isolation invariant.

**Exposure window:** the defect was introduced in `613cc27` (PR #17,
2025-10-04), first tagged `release_3_3`, and has been present in every release
since — approximately ten months. The `_trust_cache` declaration has changed
exactly once in that time (`9ab3171`, a typing modernization); its key shape
never has.

Recommended disposition:

1. Land the tuple-key cache fix immediately as a security/correctness patch.
2. Treat request-scoped `RuntimeContext` storage as a separate high-priority
   correctness fix, preferably in the same release train but not coupled to the
   small cache patch.
3. Use `ContextVar`-backed storage for runtime identity. The repository already
   implements and propagates request `ContextVar`s for Flask and FastAPI — but
   see C4 for one concrete blocker (`hooks.py:562-564`) the first pass missed.
4. Replace the trust resolver's substring match with exact client identity.
   C3 below is **reframed**: the substring scan is not a fallback, it is the
   only live matcher, because the direct lookup ahead of it is dead code.
5. Decide C8 (`resources/read` has no permission check at all under Flask)
   separately — it is arguably more severe than the reported bug, and unrelated.

---

## Claim-by-claim assessment *(validated)*

| Report claim | Verdict | Finding |
| --- | --- | --- |
| `_trust_cache` is keyed by actor alone | **Confirmed** | Declared `dict[str, Any]`, documented `actor_id -> trust_relationship` (`actingweb/handlers/mcp.py:46`). |
| The cached value depends on actor and client | **Confirmed, with a correction** | Token validation returns actor and client (`mcp.py:1305-1310`) and `_lookup_mcp_trust_relationship(actor, client_id, token_data)` uses the client id (`mcp.py:1423-1509`). The first pass said it "uses both client id and token email" — **it does not**: the persisted `token_data` contains no `email` key at all (see C3), so the email branch never executes. |
| A second client overwrites the first client's trust | **Confirmed, with wording refinement** | A **full-auth/cache-miss** request writes `_trust_cache[actor_id]` (`mcp.py:1331`); a hot-path trust miss also writes it (`mcp.py:1263`). A token/actor cache hit reads that last value without checking its client (`mcp.py:1255-1257`). Cache hits do not themselves overwrite it. |
| Alternating A/B/A misattributes A as B | **Independently reproduced** | Full script and output in "Reproduction scripts" below. Request 3 returns `(token-A, client-A, peer-B)`. **Sequential — no threads, no overlap.** |
| `(actor_id, client_id)` fixes this defect | **Confirmed** | Preserves the resolver's relevant input identity and the trust model's per-client cardinality. Both values are in hand before the lookup on both paths (`mcp.py:1239`, `1310`). |
| `(actor_id, peer_id)` is equally usable | **Conceptually unique, not operationally interchangeable** | `peer_id` is the result being cached and is not known on a cache hit until after the lookup the cache is meant to avoid. `client_id` is available before lookup. |
| Both eviction sites only know `actor_id` | **Partly confirmed** | Expired-actor cleanup only has actor id — the `_actor_cache` records written at `mcp.py:1416-1419` contain only `"actor"` and `"last_accessed"`, despite the declaration comment at `:43-45` promising a `trust_context` field. `clear_token_from_cache()` *does* have the cached token record, which contains `client_id` (`mcp.py:1876`), although it currently extracts only actor id. Actor-wide trust eviction is still the safest minimal behavior-preserving change. |
| `RuntimeContext` is request-scoped only by convention | **Confirmed, and deterministically reproducible in two concurrency models** | It stores a mutable dict on the actor (`runtime_context.py:46`, `125-129`); the same actor wrapper is cached and returned across requests (`mcp.py:1363-1367`, `1411-1421`, and the identical `id()` in the C1 repro); **no production code clears it by any means** — not `clear_context()`, not a direct `delattr`. |
| The preview-server counts prove the patch | **Plausible supplied evidence, not independently repeated** | This review did not connect to or modify the preview deployment. The implementation path and local focused reproductions independently validate the root cause. |
| App-side ownership checks should not compensate for this | **Agreed** | The library supplies the wrong principal. A consumer cannot reconstruct the right trust relationship reliably after the library has substituted another client's `peer_id`. |

## Finding C1 — the cache collapses two different principals into one slot

**Severity: high. Immediate fix is release-worthy.**

The authentication path maintains the correct identity until the trust write:

1. `validate_mcp_token()` delegates to `validate_access_token()`, which returns
   `(actor_id, client_id, token_data)`
   (`actingweb/oauth2_server/oauth2_server.py:637-647` →
   `actingweb/oauth2_server/token_manager.py:224-249`).
2. The MCP token cache retains all three values (`mcp.py:1313-1318`).
3. Trust creation is explicitly per client. `TrustManager` says the purpose is
   to allow one user to authenticate multiple MCP clients independently, and
   constructs a peer id from the establishment source, normalized email and
   normalized client id (`actingweb/interface/trust_manager.py:390-392`,
   `440`, `451-463`).
   The report observed the resulting shapes as
   `oauth2_client:<client>:<client>` for client credentials and
   `oauth2:<email>:<client>` for email-backed OAuth. **Validation refines this:**
   the prefix is always `established_via`, and both live MCP creation paths pass
   `established_via="oauth2_client"` — dynamic registration
   (`oauth2_server/client_registry.py:441-453`, where `email=client_id`, giving
   `oauth2_client:<cid>:<cid>`) and the authorize-callback
   (`oauth2_server/oauth2_server.py:379`, `394-401`, giving
   `oauth2_client:<email>:<cid>`). No live path produces an `oauth2:` prefix.
4. `_lookup_mcp_trust_relationship()` receives the actor, client id, and token
   data and resolves that client's relationship (`mcp.py:1423-1509`).
5. The result is stored as `_trust_cache[actor_id]` (`mcp.py:1331`; and on a
   hot-path trust miss at `mcp.py:1263`).

On the fast path, the token cache correctly recovers client A's `client_id`, but
the trust cache returns whichever relationship was most recently written for
the actor. `RuntimeContext` then becomes internally inconsistent:

```text
client_id           = client A          (from _token_cache, correct)
trust_relationship  = client B's row    (from _trust_cache, wrong)
peer_id             = client B's peerid (mcp.py:1270-1272)
```

That is more than a display bug.

### What the wrong `peer_id` actually controls *(new detail)*

Nine decision sites read `peer_id` out of `MCPContext` and pass it straight to
`evaluator.evaluate_permission(actor.id, peer_id, ...)`:

| Method | Handler | Gate | Non-ALLOWED result |
| --- | --- | --- | --- |
| `tools/list` | `mcp.py:395` | `mcp.py:515` | tool omitted (`:528`) |
| `resources/list` | `mcp.py:634` | `mcp.py:674` | omitted (`:687`) |
| `prompts/list` | `mcp.py:706` | `mcp.py:743` | omitted (`:756`) |
| `tools/call` | `mcp.py:777` | `mcp.py:803` | JSON-RPC `-32003` (`:808`) |
| `prompts/get` | `mcp.py:854` | `mcp.py:880` | `-32003` (`:889`) |
| `resources/read` | `mcp.py:957` | `mcp.py:984` | `-32003` (`:993`) — but see C8 |
| `tools/call` (async) | `async_mcp.py:121` | `:148` | `-32003` (`:157`) |
| `prompts/get` (async) | `async_mcp.py:203` | `:230` | `-32003` (`:239`) |
| `resources/read` (async) | `async_mcp.py:307` | `:335` | `-32003` (`:344`) |

The three `*/list` methods route to the inherited sync handlers on both
integrations (`async_mcp.py:99-103`), so **list filtering is computed against the
wrong principal too** — a client can be shown another client's allowed tool set,
not merely be denied or over-granted on call. Consumer hooks also read the same
context to attribute ownership. The authenticated token still belongs to A, but
authorization and ownership logic execute as B.

`client_id` and `trust_relationship` are **not** used in any permission
decision — `client_id` is cache-key and logging only (`mcp.py:1239`, `1350`),
`trust_relationship` feeds client-metadata bookkeeping (`mcp.py:1723-1756`) and
`get_client_info_from_context` (`runtime_context.py:354-366`). So `peer_id` is
the entire authorization surface, and it is exactly the field the cache
corrupts.

### Fail-open amplification *(expanded)*

If the cached trust value is `None`, `peer_id` becomes `""` (`mcp.py:1270-1272`,
`1343`), which is falsy, so **every gate above is skipped and the hook is
dispatched unchecked**. There are three distinct fail-open mechanisms:

1. The falsy-`peer_id` gate — the nine gate lines in the table above.
2. `evaluator = get_permission_evaluator(self.config) if peer_id else None`
   with `except: evaluator = None` (`mcp.py:414-419`, `650-657`, `722-729`).
3. Per-item evaluation exceptions in the list loops log a warning and do *not*
   `continue` — `mcp.py:529-533` says so explicitly:
   `# Fail-open on evaluation errors to avoid hard lockouts`. Ten lines above,
   `visibility_predicate` exceptions are deliberately **fail-closed**
   (`mcp.py:508-512`), so the two policies sit side by side in one loop.

For contrast, if the evaluator *were* reached with `peer_id=""` it would return
`NOT_FOUND` (`permission_evaluator.py:92-96`), which every call site treats as a
denial. The fail-open lives entirely in the handler gates, not the evaluator.

The tuple key prevents one client's missing/failed trust lookup from poisoning
every other client on the actor. It does not decide whether "authenticated token
but no resolved trust" should continue to be fail-open; that is a separate
authorization-policy decision (Decision 4).

### Independent focused reproduction *(validated — sequential)*

The cache path was exercised with only the storage/OAuth boundaries mocked: two
tokens validated to the same actor and different client ids; the resolver
returned distinct relationships; the real `authenticate_and_get_actor_cached()`,
the real module-global caches, the real `_lookup_mcp_trust_relationship()` and
the real `RuntimeContext` ran unchanged. Full script in "Reproduction scripts".

Observed:

```text
token       ctx.client_id  ctx.peer_id                       actor obj id
token-A     client-A       oauth2_client:client-A:client-A   4489688272
token-B     client-B       oauth2_client:client-B:client-B   4489688272
token-A     client-A       oauth2_client:client-B:client-B   4489688272   <-- wrong principal
token-B     client-B       oauth2_client:client-B:client-B   4489688272

_trust_cache keys: ['actor-1']
cache stats: {'token_hits': 2, 'token_misses': 2, 'actor_hits': 2,
              'actor_misses': 0, 'trust_hits': 2, 'trust_misses': 0}
```

The third request is a token/actor/trust cache hit and reads client B's
`peer_id` while carrying client A's `client_id`. Request 4 happens to be correct
only because B was the last writer — the sequence, not a hit-rate, is the
finding. It proves the defect without depending on the consumer's agent-run code
or preview server, **and without any concurrency**. The identical `actor obj id`
on all four rows is the shared `ActorInterface` that C4 is about.

### Original live evidence preserved from the report

The consumer observed this exact sequence on the preview server with two
different OAuth client registrations for one actor:

```text
A (1st): you_are='OAuth2 client: AAA'   correct  (cache miss)
B (1st): you_are='OAuth2 client: BBB'   correct  (cache miss)
A (2nd): you_are='OAuth2 client: BBB'   wrong    (cache hit on B's entry)
A (3rd): you_are='OAuth2 client: BBB'   wrong
```

The defect is bounded by cache state, not by the MCP session: a full-auth miss
for a client writes that client's trust into the actor-wide slot, and subsequent
hot-path requests for any client on the actor consume that value until another
full-auth miss replaces it or the relevant caches are invalidated. The intended
TTL is five minutes (`_cache_ttl = 300`), although C6 below shows expiry is far
weaker in practice than the constant suggests.

The report's end-to-end consequence was not merely wrong `you_are` output:
client A called `agent_run_complete(last_open=true)` and closed client B's live
run. PR #242 had added per-client ownership scoping specifically to prevent that
operation. Its ownership rule received B's `peer_id` while handling A's token,
so it made the expected decision for the wrong principal.

For verification, the reporter patched the **installed library** on the preview
server, reran the same scenarios, and then reverted that patch so the upstream
repository remained the source of the eventual fix. Supplied results:

| Scenario | Actor-only key | `(actor_id, client_id)` key |
| --- | --- | --- |
| Sequential A/B/A/B/A | 3 of 5 requests misattributed | 0 |
| Six concurrent A+B pairs | 6 of 6 pairs misattributed | 0 |
| 60 requests, 3 clients, 24 threads | not recorded for the old key | 0 |

These numbers are not reproduced by this research run, but they are retained as
acceptance evidence and are consistent with both the implementation trace and
the independent focused reproduction above.

## Finding C2 — `(actor_id, client_id)` is the right minimal repair *(validated)*

The trust relationship's domain key is actor plus client. A tuple expresses that
without delimiter escaping or prefix parsing:

```python
_trust_cache: dict[tuple[str, str], Any] = {}

trust_key = (actor_id, client_id)
if trust_key in _trust_cache:
    trust_relationship = _trust_cache[trust_key]
else:
    trust_relationship = self._lookup_mcp_trust_relationship(
        actor_interface, client_id, token_data
    )
    _trust_cache[trust_key] = trust_relationship
```

Both the cache-hit write at current line 1263 and the full-auth write at current
line 1331 must use the same key helper/value. Centralizing construction in a
small helper or local `trust_key` avoids fixing only one path.

This fits the repository's published caching guidance. The guide prescribes
composite keys — including `trust_key = f"{actor_id}:peer_relationships"` — and
shows actor-wide removal of every matching trust key via prefix scan
(`docs/guides/caching.md:26-41`, `119-144`); `:389` lists "Key Collisions: Use
sufficiently unique cache keys with proper prefixing" as a known pitfall. **None
of that design was ever implemented in `mcp.py`.** The current implementation is
the outlier, not the proposed fix.

It also matches the MCP specification's own normative rule for server-side
state: bind stored state to a server-derived principal, keying it as
`<user_id>:<handle>` (see External References). The tuple is that rule.

### Invalidation

For expired actors, removing all `(actor_id, *)` entries is required because the
cleanup loop only has the actor id:

```python
for key in [key for key in _trust_cache if key[0] == actor_id]:
    del _trust_cache[key]
```

For `clear_token_from_cache()`, the report is slightly imprecise: the cached
token record still contains `client_id` (`mcp.py:1876`, written at `:1313-1318`),
so client-scoped eviction is possible. However, current behavior evicts the whole
actor wrapper and its one trust slot to force a fresh authentication path — note
that this means **one client's logout already drops the shared `ActorInterface`
for every other client on that actor** (`mcp.py:1884-1885`). Evicting every tuple
for that actor preserves those semantics exactly and is the safest patch.
Narrowing invalidation can be considered later with explicit tests for logout,
remaining valid tokens, and trust modification.

### Why not key by `peer_id`

`peer_id` is the better authorization principal, but not the better lookup key
here. A cache hit starts with token-derived actor/client identity. Discovering
the relationship's peer id requires resolving the relationship first, which
removes the value of the cache. `(actor_id, peer_id)` would work only with a
second client-to-peer index or a fully reliable derivation function. Neither is
needed for the immediate fix.

## Finding C3 — the substring scan is not a fallback, it is the only live matcher *(REFRAMED)*

The first pass described `mcp.py:1457-1478` as a fallback behind a direct
lookup, and treated substring matching as an unlikely-but-wrong comparison.
Validation shows something stronger: **the direct lookup cannot fire on the live
MCP path at all**, for two independent reasons.

1. **The guard is never true.** `user_email = token_data.get("email") or
   token_data.get("user_email")` (`mcp.py:1442`). The persisted access-token
   record contains `token_id, token, actor_id, client_id, created_at,
   expires_at, expires_in, scope, google_token_key`
   (`token_manager.py:349-359`) or `..., scope, trust_type, grant_type, ...` for
   the client-credentials path (`token_manager.py:997-1007`). **Neither contains
   an `email` or `user_email` key.** (The `"email"` at `token_manager.py:220`
   belongs to the token *endpoint response* sent to the client, not the stored
   record.) `validate_access_token` returns the stored dict verbatim
   (`:249`), and `mcp.py:1240`/`1310` propagate exactly that.
2. **The prefix would be wrong anyway.** The key is hardcoded
   `f"oauth2:{normalized_email}:{normalized_client}"` (`mcp.py:1451`), while
   `create_or_update_oauth_trust` uses `source = established_via or "oauth2"` as
   the prefix (`trust_manager.py:440`, `460`). Both live MCP creation paths pass
   `established_via="oauth2_client"` (see C1 step 3), so live peer ids always
   begin `oauth2_client:`.

So **every** MCP trust resolution falls through to the scan over
`actor.trust.relationships` and matches `elif via == "oauth2_client":` with
`client_id in peer_id_str` (`mcp.py:1473-1478`). Two consequences:

- **Correctness.** Substring containment is the sole comparison at an
  authorization boundary. With in-repo-generated ids this is functionally exact:
  `client_id = f"mcp_{secrets.token_hex(16)}"` (`client_registry.py:51`) is a
  uniform 36 characters with 128 bits of entropy, so no generated id can be a
  substring of another; and externally supplied `client_id` values are never
  honoured — `register_client` overwrites unconditionally and never reads a
  `client_id` key from `registration_data`. The residual exposure is data not
  produced by that generator: migrated rows
  (`scripts/migrate_dynamodb_to_postgresql.py:277-299` copies existing values
  verbatim) or hand-created trusts.
- **Cost.** An O(n) full-relationship scan on every trust-cache miss, on the hot
  authentication path — which the tuple key will make *more* frequent, since
  misses become per-client rather than per-actor.

### `oauth_client_id` is available for an exact comparison — with one caveat *(validated)*

The first pass asserted "the stored `oauth_client_id` field is already available
on `TrustRelationship`." That was verified end to end and holds, with a
qualification that changes the recommendation:

- The property exists on every `TrustRelationship` (`trust_manager.py:119-122`).
- It is accepted by `create` and `modify` on both backends
  (`db/dynamodb/trust.py:104-106`, `323`, `365-366`;
  `db/postgresql/trust.py:207`, `282`, `304`, `329`, `540-543`).
- Critically, it round-trips on the **list** read path the resolver actually
  iterates (`db/dynamodb/trust.py:491-492`; `db/postgresql/trust.py:756-757`,
  positional index 19, verified against the SELECT column order at `:698-702`),
  not merely on the single-`get` path.
- **Caveat:** it is only *written* when `source == "oauth2_client"`
  (`trust_manager.py:506-507`, `578-579`). It is `None` on every other row. That
  covers the current MCP path, but an exact `oauth_client_id` match cannot be the
  *sole* matcher without a peer-id fallback for legacy rows.

Exact comparison on this field is already the established pattern elsewhere in
the codebase: `oauth2_server/oauth2_server.py:886-892` and
`handlers/www.py:549-551` both use
`getattr(trust, "oauth_client_id", None) == client_id`.

### `established_via="oauth2_interactive"` matches no branch *(new)*

The resolver's three branches test `via == "oauth2"` (`:1465`),
`via == "oauth2_client"` (`:1473`), and `via is None` (`:1483`). A trust with
`established_via="oauth2_interactive"` — written by the regular web-login
callback (`handlers/oauth2_callback.py:630-638`) — matches none of them and
resolves to `None`, hence `peer_id=""`, hence the fail-open above. Whether an MCP
access token can ever be issued against such a trust was not settled here; the
`oauth2_interactive` branch inside the MCP authorize handler
(`oauth2_server.py:381`) is unreachable because `extract_mcp_context()` returns
`None` unless `flow_type == "mcp_oauth2"` (`state_manager.py:182-188`).

Also note the literal `"oauth2"` value that branch `:1465` tests for is written
by **no production path** — `source = established_via or "oauth2"` only
degrades to it when a caller passes `established_via=None`, which no in-repo
caller does (`oauth2.py:1424-1425` substitutes `"oauth2_interactive"` first).
The only in-repo producer is a unit test.

Two more substring comparisons on peer ids exist nearby, for the record:
`client_registry.py:461-464` (post-create lookup) and `:513-525` (deletion,
`pattern in peer_id or peer_id.endswith(client_id)`).

### Revised hardening options

1. Prefer exact `trust.oauth_client_id == client_id`, with an exact peer-id
   fallback for rows where it is `None`.
2. Or build exact peer-id candidates for each supported prefix and use
   `get_relationship` directly — this restores a real fast path *and* removes
   the O(n) scan, but is blocked on the email not being in `token_data`.
3. At minimum, delete the dead `if user_email:` block rather than leaving ~12
   lines of unreachable code in front of the live matcher.
4. Decide whether `oauth2_interactive` should be matchable.

This can be a narrowly tested companion commit. If it is deferred, the tuple
cache fix remains valid and should still ship.

## Finding C4 — `RuntimeContext` violates its own request-scope contract *(validated, with two corrections)*

**Severity: high under overlapping requests. Not fixed by the cache key.**

The module explains the real requirement accurately: multiple clients can
access one actor and every request needs its own client context
(`actingweb/runtime_context.py:4-18`). Its implementation then attaches one
mutable context dict to the actor object (`runtime_context.py:46`, `125-129`) and
overwrites the `"mcp"` entry on each authentication
(`runtime_context.py:155-163`). `ActorInterface` defines no `__slots__` and no
`__setattr__` override, so the attribute sticks.

The MCP actor cache deliberately returns the same `ActorInterface` object while
the actor is hot (`mcp.py:1252`, `1288`, `1363-1367`) — the C1 repro shows the
identical `id()` across four requests.

**No production code clears runtime context by any means.** Repo-wide, the only
`clear_context()` call is `tests/integration/test_runtime_context_advanced.py:247`,
and the underlying attribute name (`_actingweb_runtime_context` /
`_RUNTIME_CONTEXT_ATTR`) appears only inside `runtime_context.py` and one test
docstring. Context is only ever created and overwritten. The public hook guide
nevertheless states that runtime context is request-scoped and automatically
managed (`docs/guides/hooks.rst:304`). That documentation promises an invariant
the implementation does not provide.

Both the hot and full-auth paths do reset MCP context before dispatch
(`mcp.py:1266-1276`, `1339-1347`). That explains why short concurrent calls
often appear correct: the normal timing is set-then-read. It does not protect a
request after another request has set the same shared attribute.

### Correction 1 — Flask is exposed, not "potentially"

`ActingWebApp.run()` calls `flask_app.run(...)` (`interface/app.py:1476`), and
Flask's `run()` defaults `threaded=True` (Flask `app.py:655` in the pinned
venv). A fresh `MCPHandler` and `AWWebObj` are built per request
(`flask_integration.py:1388-1390`), but the actor comes from the shared
module-global cache. The threaded reproduction below is exactly that model. The
same applies to any threaded WSGI deployment — gunicorn's `gthread` worker
submits request handling to a reused `ThreadPoolExecutor` with no
`copy_context()` (see External References).

### Correction 2 — the async dispatch path itself does not suspend

The first pass implied FastAPI "can interleave tasks at an awaited async hook",
which is right, but the sharper statement is: between
`authenticate_and_get_actor_cached()` (`async_mcp.py:75`, a **sync** inherited
method) and the first `get_mcp_context()` read, the only `await`s are
`async_mcp.py:105/107/109`, each awaiting a freshly-created coroutine on the same
handler — which begins executing inline and does not yield to the loop. Inside
each callee the context read (`:145-147`, `:227-229`, `:332-334`) precedes the
synchronous `evaluate_permission` call.

The real suspension points are the hook awaits at `async_mcp.py:180`, `261`,
`383`. So on FastAPI the leak requires **an async hook that reads
`RuntimeContext` after an `await`**; the permission gate itself is currently safe
by accident of statement ordering. That is a fragile invariant — any future
`await` inserted before the read breaks it silently — but it should be stated
accurately rather than overclaimed.

### Deterministic reproduction *(both concurrency models)*

Full script in "Reproduction scripts". Both scenarios use a barrier/gate the test
controls: they demonstrate the **absence of an invariant**, not a measured
production leak rate. The consumer's 60-request test finding zero leaks is fully
compatible with this result.

```text
asyncio (single-threaded event loop, interleaved at an await):
  LEAK request A read peer-B
  OK   request B read peer-B

threads (Flask/WSGI model):
  LEAK request A read peer-B
  OK   request B read peer-B
```

A load test with short synchronous hooks can easily miss it, because
authentication and the first permission read do not await. An async hook that
reads `RuntimeContext` after an await, or two Flask threads preempted between set
and read, exposes it.

### Preferred durable design: `ContextVar` — and one concrete blocker *(new)*

The repository already has the correct pattern in
`actingweb/request_context.py`: request id, actor id, and peer id are
`ContextVar`s, documented as thread-safe and async-safe
(`request_context.py:3-8`, `16-18`). Flask sets in `before_request` and clears in
`after_request` (`flask_integration.py:73-115`); FastAPI sets in middleware and
clears in a `finally` (`fastapi_integration.py:461`, `474-476`) and propagates
into executor work via `copy_context()` + `ctx.run()`
(`fastapi_integration.py:538-573`, `479-497`).

`RuntimeContext(actor)` can retain its public API while moving storage off the
actor:

- Store MCP/OAuth2/web contexts in execution-context-local variables.
- Include the actor identity in the stored value, or maintain an
  execution-local actor-to-context mapping, so asking for another actor's
  context in the same request does not return the current actor's identity.
- Use immutable values or copy-on-write. Mutating a dict held inside a
  `ContextVar` would let copied contexts share the same mutable object.
- Integrate clearing/reset with the existing Flask and FastAPI request
  lifecycle. A `ContextVar` isolates concurrent asyncio tasks, but reused WSGI
  threads still need end-of-request cleanup.
- Preserve propagation into framework-managed executor work through the
  existing `copy_context()` helper.

**Three implementation constraints the first pass did not surface:**

1. **`interface/hooks.py:562-564` loses ContextVars.** An async hook invoked
   from a sync context while a loop is already running is executed as
   `executor.submit(asyncio.run, hook(*args, **kwargs))` — a bare
   `ThreadPoolExecutor` submit with **no `copy_context()`**. ContextVars set on
   the calling thread are invisible inside. Today's attribute-on-actor storage
   *does* survive that hop, because the actor travels in `*args`. A `ContextVar`
   rewrite regresses this path unless it is fixed at the same time. (The sibling
   `except RuntimeError` branch at `:567` calls `asyncio.run` on the same thread,
   where the new Task copies the current context — that one is fine.)
2. **`clear_request_context` uses `.set(None)`, not `.reset(token)`**
   (`request_context.py:242-244`); no `Token` is captured anywhere in the
   module. Adequate for flat request scoping, but it does not nest, and the
   existing precedent is "clear", not "restore". CPython, Flask and
   OpenTelemetry all specify the token/reset contract (External References).
3. **Flask's `after_request` does not run when an unhandled exception
   propagates**, and no `teardown_request` is registered
   (`flask_integration.py:102-115`). Any ContextVar scheme inherits that gap on a
   reused WSGI worker thread — which is precisely where a missing reset leaks
   into the next request.

An alternative containment is to cache the core actor but construct a fresh
`ActorInterface` wrapper per request, leaving the attribute-based context on
that wrapper. That is smaller and touches no hook plumbing, but it preserves the
flawed abstraction for core actors and any other reused wrappers. `ContextVar`
matches the declared contract and existing architecture better.

**Scope note:** `set_oauth2_context` and `set_web_context`
(`runtime_context.py:176-201`, `213-238`) have **zero production call sites**.
The MCP auth path is the only live producer of runtime context in the entire
library; non-MCP request identity already flows through the `request_context`
ContextVars (`auth.py:164, 258, 285, 337, 360, 418, 582, 609`). That materially
shrinks the blast radius of a rewrite.

## Finding C5 — existing tests cover values, not same-actor request isolation *(validated, and worse than stated)*

The current tests establish:

- new MCP context fields round-trip (`tests/test_runtime_context_unit.py:23-52`);
- live `client_info` wins over trust metadata (`:55-99`);
- `clear_context()` removes the attribute
  (`tests/integration/test_runtime_context_advanced.py:228-250`);
- two **different actor objects** do not share context (`:252-293`);
- permission handlers receive a mocked/current `peer_id`.

They do not exercise two clients on one cached actor. Validation sharpens two
points:

- **`grep -rn` over `tests/` returns zero references to `_trust_cache`,
  `_actor_cache`, `_token_cache`, `clear_token_from_cache`, or
  `_lookup_mcp_trust_relationship`.** `authenticate_and_get_actor_cached` appears
  **only as a patch target** — `tests/test_mcp_permissions.py:55,94,145`,
  `tests/test_mcp_tool_visibility.py:70,157,226`,
  `tests/test_async_mcp_handler.py:91,139,184,240,311,347,390`,
  `tests/test_mcp_tool_result_format.py:139,145`,
  `tests/test_mcp_tool_schema_fields.py:27`. So `mcp.py:1208-1356`, the entire
  cache body, is **never executed by any test in the suite**.
- The different-actor isolation test cannot catch this issue not only because the
  actor object differs, but because it also uses **two different context types**
  (MCP on one actor, OAuth2 on the other). It passes regardless of the bug.

The only MCP cache with any coverage at all is `_mcp_client_info_cache`, in
`tests/test_mcp_session_key.py` (13 tests, including
`test_second_initialize_does_not_overwrite_first_session` at `:87-107`) — a
different dict, added for a different, already-fixed cross-client leak.

Both defects in this document are reproducible as **pure unit tests with no
docker**; the two scripts below are the skeletons.

### Exact mechanical patch surface for the reported bug

Every current `_trust_cache` use is in `actingweb/handlers/mcp.py`. A later
implementation should use this inventory rather than relying on a broad
search-and-replace:

| Current location | Current behavior | Required immediate change |
| --- | --- | --- |
| `:46` | declares `dict[str, Any]`, actor id key | declare `dict[tuple[str, str], Any]` and document `(actor_id, client_id)` |
| `:152-155` | expired actor removes one actor-id entry | remove every tuple whose first component is the expired actor |
| `:1210-1219` | docstring says trust is cached per actor and keys use token/actor ids | say trust is cached per actor/client pair |
| `:1255-1257` + `:1263` | hot path reads, then writes on miss, keyed by `actor_id` | construct one `trust_key = (actor_id, client_id)` and use it for both read and miss write |
| `:1331` | full-auth path writes `actor_id` | write the same `(actor_id, client_id)` key |
| `:1884-1888` | token clear removes one actor-id trust entry (and the whole `_actor_cache` entry) | preserve current actor-wide invalidation by deleting every tuple for the actor |

(Line ranges re-derived at `cc29c03` during validation; they now match the Code
References section exactly.)

Two documentation lines change with the code:
`docs/guides/mcp-applications.rst:839` currently states the defect as intended
behavior ("Trust relationships — Permission context cached **per actor**"), and
`mcp.py:43-45`'s declaration comment promises an `_actor_cache` `trust_context`
field that is never written.

After editing, `rg -n "_trust_cache" actingweb tests` should show no remaining
string-key assumption. Tests should clear all three module caches before and
after each case; otherwise the module-global state makes results order-dependent.

Minimum cache regression coverage:

1. Same actor, clients A and B, tokens A and B: `A / B / A / B`, asserting both
   `MCPContext.client_id` and `peer_id` match on every request.
2. Assert the trust resolver is called once per `(actor, client)` while entries
   are hot.
3. Cover cached `None` independently per client.
4. Expire one actor and assert every tuple for it is removed while another
   actor's tuples remain.
5. Revoke a cached token and assert the selected actor-wide invalidation
   behavior.
6. Run the identity sequence through `AsyncMCPHandler` as well as the shared
   parent authentication method, so inheritance cannot conceal a divergent
   path later.

Minimum request-context regression coverage:

1. Deterministic asyncio event/barrier test: A sets context, B overwrites in its
   task, A resumes and must still read A.
2. Equivalent threaded barrier test for the Flask/WSGI model.
3. An async MCP hook that reads context after an `await`.
4. Same request with two actor objects, proving actor association is preserved.
5. End-of-request cleanup on success and exception paths.

### Definition of done for the immediate cache bug

The reported bug is closed when all of the following are true:

1. Every trust-cache lookup and write uses the raw token-derived
   `(actor_id, client_id)` pair.
2. Actor expiry and token clearing cannot leave another trust tuple for the
   invalidated actor under the chosen actor-wide semantics.
3. A deterministic A/B/A/B/A test reports the caller's own `client_id`,
   `trust_relationship.peerid`, and `peer_id` on all five requests.
4. Both clients exercise the hot path; a test that forces a full lookup on every
   request does not cover the defect.
5. At least one test verifies cached `None` for client A does not suppress client
   B's valid trust, and vice versa.
6. Cache hit/miss statistics retain their meaning per pair; expected resolver
   call counts are asserted.
7. Sync and inherited async dispatch paths remain green.
8. The focused tests fail against the actor-only implementation and pass with
   tuple keys.
9. `pyright`, Ruff, and the full test suite required by `AGENTS.md` pass.

The immediate patch must **not** claim to provide request isolation under
overlap. That requires Finding C4's `RuntimeContext` work and its deterministic
async/threaded tests. Conversely, the known context race must not delay landing
the tuple key: the two defects are independently actionable, and C1's
reproduction is entirely sequential.

## Finding C6 — a hot actor's cached trust never refreshes *(new)*

This is distinct from the "cleanup is inert" note the first pass filed under
adjacent observations. The consequence is stale **authorization**, not just
stale objects.

- `_trust_cache` has no TTL of its own. Its only TTL-driven eviction sits inside
  the expired-*actor* loop (`mcp.py:152-155`).
- `_actor_cache` uses a **sliding** window: `last_accessed` is refreshed on every
  hit (`mcp.py:1251`, `mcp.py:1366`). An actor under continuous traffic never
  ages out.
- The cleanup that drives it is called from exactly one place, gated on
  `if time.time() % 20 == 0:` (`mcp.py:1221-1223`). `time.time()` returns a
  float; landing on an exact representable integer boundary is effectively never.
- No other code path clears `_trust_cache` (verified repo-wide).

Combined: for an actor receiving MCP requests at least every five minutes, the
trust relationship resolved on the *first* request is served for the process
lifetime. A trust modification, permission change, `peer_approved` flip, or
trust deletion is invisible to the MCP path indefinitely.

Related: `_trust_cache[actor_id]` is written at `mcp.py:1331` **before**
`_mark_client_peer_approved` mutates `peer_approved` at `mcp.py:1334-1336`, so
the cached object is stale on that field from the moment it is cached.

## Finding C7 — token revocation does not clear the cache; only logout does *(new)*

`MCPHandler.clear_token_from_cache` (`mcp.py:1855-1890`) has exactly one caller
repo-wide: `handlers/oauth2_endpoints.py:857-866`, inside
`_handle_logout_request`, guarded on `response.get("action") == "success"`.

Not calling it: `/oauth/revoke` and `/oauth/spa/revoke`
(`handlers/oauth2_spa.py:1390`), `token_manager.revoke_token` (`:304`),
`revoke_client_tokens` (`:1029`), `oauth_session.revoke_access_token` (`:369`),
`revoke_refresh_token` (`:623`), `revoke_all_tokens` (`:653`),
`revoke_token_chain` (`:708`), `oauth2.revoke_token` (`:1094`), and every trust-
and actor-deletion path.

So a revoked token continues to authenticate MCP requests from any warm process
for up to `_cache_ttl = 300` seconds. RFC 7662 §4 names exactly this tradeoff and
its bound (External References). Because all six caches are module globals
(`mcp.py:21`, `42-47`, `50-57`) shared by `MCPHandler` and `AsyncMCPHandler`
alike (`async_mcp.py:18`), even the logout path only clears *the process that
served the logout* — in a multi-worker or multi-container deployment every other
warm process keeps accepting the token. This wants a different remedy from the
tuple key: shorter or no positive token caching, a shared invalidation channel,
or a revocation/version check.

## Finding C8 — sync `resources/read` performs no permission check at all *(new)*

`mcp.py:982-983`:

```python
trust_context = getattr(actor, "_mcp_trust_context", None)
peer_id = trust_context.get("peer_id") if trust_context else None
if peer_id and uri:
```

`_mcp_trust_context` is set by **no production code**. Repo-wide the only
writers are `tests/test_mcp_permissions.py:40`,
`tests/test_mcp_tool_visibility.py:19`, and
`tests/test_mcp_tool_schema_fields.py:21`; the live auth path writes
`_actingweb_runtime_context` instead (`runtime_context.py:46`, `127-129`).

History: `_mcp_trust_context` was the original mechanism, introduced in
`613cc27` — the same commit that introduced `_trust_cache` — and read from the
then-current MCP SDK server. That server file was removed in `c61e059` ("drop
mcp SDK dependency"); the read at `mcp.py:982` was left behind, now matching an
attribute nothing writes.

Consequence: in a live request `trust_context` is `None`, the guard at
`mcp.py:984` is never entered, and control falls straight through to hook
dispatch at `mcp.py:1006-1045`. Flask dispatches `MCPHandler.post`
(`flask_integration.py:1388-1407`), so **`resources/read` is unauthorized on the
Flask path**. FastAPI dispatches `AsyncMCPHandler.post_async`
(`fastapi_integration.py:2340-2357`), whose `_handle_resource_read_async` reads
`RuntimeContext` correctly (`async_mcp.py:332-334`), so that path does evaluate.

The three MCP permission tests that pass today do so by setting the dead
attribute themselves — they are exercising a code path that cannot occur in
production.

## Finding C9 — `operation=` diverges between the sync and async `tools/call` *(new)*

`mcp.py:806` passes `operation="use"` (matching `tools/list` at `mcp.py:522`);
`async_mcp.py:155` passes `operation="invoke"`. `_evaluate_rules` only consults
`operations` in the `{"patterns": [...], "operations": [...]}` rule form
(`permission_evaluator.py:537-552`, returning `DENIED` at `:551-552` when the
operation is absent). Every shipped default trust type expresses `tools` in the
`{"allowed": [...], "denied": [...]}` form (`trust_type_registry.py:303`, `328`,
`351`, `373`, `409-421`, `463`), resolved at `permission_evaluator.py:521-534`
before `operations` is read — so the string is currently unread. It becomes a
Flask-vs-FastAPI behavioural divergence the moment an application defines a
patterns/operations rule for tools.

## Finding C10 — documentation states the bug as intended behavior, and contradicts itself *(new)*

- `docs/guides/mcp-applications.rst:836-839` — "**What Gets Cached:** … 3. Trust
  relationships – Permission context cached **per actor**." The defect,
  documented as a feature, since v3.3.
- `docs/guides/caching.md:26-41`, `119-144` — composite keys and prefix-scan
  invalidation: the *correct* design, never implemented. `:389` warns explicitly
  about key collisions.
- `docs/guides/hooks.rst:304` — "The runtime context is request-scoped and
  automatically managed by the framework." Not true (C4).
- `docs/guides/hooks.rst:316-319` already acknowledges that "the trust record is
  per-OAuth2-credential and is overwritten whenever a new session registers" —
  but the fix documented there covers only `client_info`, not `peer_id`.
- `runtime_context.py:18`, `:113`, `:268-271` — three source docstrings
  promising cleanup that never happens.

## Finding C11 — the escalation is mechanical: wrong `peer_id` means wrong *trust type* *(new)*

**This re-rates C1 from wrong-attribution to authorization bypass.**

The consumer's blast-radius audit demonstrated a read-only MCP client performing
a write after a read-write client authenticated on the same actor. Validation
confirms the full chain is inside the library, with no app defect in it:

1. **Per-client trust types are a library feature.** `register_client` takes the
   trust type from the registration request:
   `"trust_type": registration_data.get("trust_type", "mcp_client")`
   (`oauth2_server/client_registry.py:68`). Two clients on one actor can
   therefore carry different trust types by design.
2. **The trust type is stored as the trust row's `relationship`.**
   `create_or_update_oauth_trust` passes it as `relationship=trust_type`
   (`interface/trust_manager.py:583-601`, via
   `client_registry.py:441-443`).
3. **Permission evaluation resolves the trust type *from the peer id*.**
   `_lookup_trust_type_from_database(actor_id, peer_id)` calls
   `db_trust.get(actor_id=actor_id, peerid=peer_id)` and returns
   `trust_record["relationship"]` (`permission_evaluator.py:471-478`). That name
   selects the entire permission rule set from the trust type registry.

So a poisoned `peer_id` does not merely mislabel the caller — it selects a
**different permission set**. The consumer's measured result:

```text
RO tools/list, isolated:        1 tool    (memory_save absent)
RW authenticates
RO tools/list, again:          32 tools   (memory_save present)

RO memory_save, isolated  -> -32003 "Access denied"
RW authenticates
RO memory_save, identical -> succeeds; canary present in actor storage
```

That matches the mechanism exactly: C1's finding that the `*/list` handlers
filter against the wrong principal explains the 1 → 32 tool jump, and the gate
at `mcp.py:803` explains the write landing. **The escalation runs both
directions** — a read-write client can equally be demoted to a read-only
client's rules, surfacing as unexplained mid-session denials.

Note that `mcp_client_readonly` / `mcp_client_readwrite` are *not* built-in
types — the library ships only `mcp_client` (`trust_type_registry.py:381`).
They are application-registered custom trust types. The registration mechanism,
the storage, and the evaluation path are all library-supplied, so any
application that registers differentiated MCP trust types inherits this bypass.

**Bounding the damage:** the downstream permission caches are keyed correctly —
`TrustPermissionStore._cache`, `PeerPermissionStore._cache`,
`CachedCapabilitiesStore._cache` and `PeerProfileStore._cache` all use
`f"{actor_id}:{peer_id}"` (`trust_permissions.py:144`, `peer_permissions.py:254`,
`peer_capabilities.py:524`, `peer_profile.py:151`). There is no second-order
pollution: the *wrong* principal's permissions are fetched *correctly*.
`_trust_cache` is the sole mis-keyed cache in the library, which is why a
one-key fix closes the whole class.

### Two corrections to the audit's framing

**The exposure window is not five minutes.** The audit reasons from
"two clients touching the account within the 5-minute TTL". C6 shows worse:
`_actor_cache` uses a sliding `last_accessed` (`mcp.py:1251`, `1366`) and the
only cleanup is gated on `time.time() % 20 == 0` (`mcp.py:1221-1223`), which
effectively never fires. On an actor receiving MCP traffic at least every five
minutes, the poisoned entry **never expires** for the process lifetime. The
audit's "any two of those touching the account within five minutes is enough"
understates it: one crossing is enough, and it persists.

**"Cannot self-defend" is very nearly right, but not exactly.** The audit says
the only identity a hook can see is the runtime context, and the handler
"discards" the correct client. In fact `MCPContext.client_id` **is** correct on
both paths — from `_token_cache` on the hot path (`mcp.py:1239` → `:1268`) and
from token validation on the full path (`mcp.py:1310` → `:1341`). Only
`trust_relationship` and `peer_id` are poisoned. So an application *can*
reliably **detect** the condition — `client_id` not appearing in `peer_id` is an
unambiguous poison signal — even though it cannot *repair* it without
re-implementing `_lookup_mcp_trust_relationship`. That is worth stating for two
reasons: it gives consumers a fail-closed assertion they can add today, and it
gives the library a cheap invariant check worth landing alongside the tuple key.
It is a detection aid, not a fix.

### Library-side sites the audit did not cover

The audit's §2 and §3 enumerate application code. Two library-side items belong
on the same list:

- **C12 below** — a durable write into the wrong trust record.
- **C8** — `resources/read` is unauthorized on the Flask path. `actingweb_mcp`
  runs FastAPI (`application.py:707`), so it is unaffected, and its
  `hooks/mcp/resources.py` app-side filtering is doing the work regardless. A
  **Flask** consumer relying on the library gate has no resource authorization
  at all.

## Finding C12 — the poisoned `peer_id` is written durably into trust storage *(new)*

The audit's §3 lists three durable effects, all in application code. The library
has one of its own, and it is on the hot path.

`_update_trust_with_client_info` reads `peer_id` straight out of the MCP runtime
context (`mcp.py:1696-1705`) and, when the client metadata differs from what is
stored, calls `core_actor.modify_trust_and_notify(peerid=peer_id, ...)` writing
`client_name`, `client_version`, `client_platform`, `last_accessed` and
`last_connected_via` (`mcp.py:1745-1760`).

It runs on **every authenticated request that carries `clientInfo`**, not only
`initialize` — `_update_actor_client_info` is called unconditionally at
`mcp.py:247` (sync) and `async_mcp.py:93` (async), and it forwards any
`clientInfo` found in `params` or at top level (`mcp.py:1665-1676`). There is a
second call from the `initialize` path at `mcp.py:349`.

Consequence: while the cache is poisoned, **client A's `clientInfo` is written
into client B's trust record**. This is self-reinforcing in two ways:

- It corrupts the same `client_name` that `get_client_info_from_context` falls
  back to when live per-session `client_info` is absent
  (`runtime_context.py:354-366`) — the exact field the `hooks.rst:316-319` note
  was written to protect, and the field the consumer's
  `hooks/mcp/protocol/client_detection.py` reads to choose response shape.
- It corrupts `last_accessed` and `last_connected_via`, which are audit-trail
  fields — so the record of *which client connected when* is wrong in storage,
  and stays wrong after the cache expires.

Unlike the cache, this survives the TTL. Fixing the key stops new corruption but
does not repair rows already written; a remediation note for operators is worth
considering (see Decision 8).

## Consumer impact and temporary mitigation to preserve

> **Updated by the blast-radius audit
> (`../actingweb_mcp/thoughts/todo/2026-07-30-trust-cache-security-audit.md`).**
> The run-ownership framing below was the original report's scope. The audit
> shows the same poisoned `peer_id` also crosses per-memory-type access control,
> MCP resource filtering, and the memory-service write gate, and stamps wrong
> identities into `created_by`, write-origin audit trails and run records. PR
> #242's guard and the two `SKILL.md` defenses remain correct but are **not** a
> general mitigation — they cover one destructive path and say nothing about
> tool gating or memory permissions. The only general mitigation is the library
> fix. C11 adds one thing the consumer can do today: assert that
> `mcp_context.client_id` appears in `mcp_context.peer_id` and fail closed when
> it does not.

The consumer's ownership model is not the source of the cache defect. Its
`started_by_client_id` is the MCP `peer_id` read from
`RuntimeContext`; the library supplied another client's value. The correct
layering is:

```text
ActingWeb authenticates token -> resolves exact client trust -> supplies peer_id
consumer records/compares peer_id -> ownership decision
```

Do not add a consumer-side identity reconstruction or maintain a second trust
cache in `actingweb_mcp`. It would duplicate framework logic and still be
vulnerable to the shared `RuntimeContext`.

At report time, the consumer retained two defensive changes while waiting for
the library fix:

- `skills/working-with-emm/SKILL.md` 2.2.1 was softened to say that a matching
  `started_by_client_id` is **not proof** a run belongs to the caller, because
  multiple sessions may also share one OAuth credential.
- Agents were told to prefer the explicit `run_id` returned by `agent_run()`
  over `agent_run_complete(last_open=true)`. Explicit run id is an exact
  capability and does not require caller-identity inference.

Those defenses should remain after the tuple fix. They also protect the
same-credential/multiple-session case, which `(actor_id, client_id)` cannot and
should not distinguish. What should not remain is any implication that matching
another registered client's id is expected behavior.

External context reinforces this: the MCP specification requires that
authorization be revalidated on **every** request and that a session or state
handle never be treated as authentication. The identity carrier is the token, per
request; anything cached from it must be keyed by the principal that token
resolves to.

## Adjacent cache observations, deliberately not part of the tuple patch

These do not invalidate the reported fix, but should not be accidentally
described as solved by it.

### Cleanup scheduling is effectively inert

The comment says cleanup runs about every twentieth request, but the condition is
`time.time() % 20 == 0` (`mcp.py:1221-1223`). With a fractional wall clock this
requires landing on an exact representable boundary and is effectively never
true in normal traffic. Inline TTL checks prevent expired token/actor entries
from being used, but expired objects accumulate — and, per C6, the sliding
`last_accessed` window means the sharper consequence is stale authorization, not
just memory growth. Use a request counter or a monotonic `next_cleanup_at`.

### Caches and revocation are process-local

All six caches are module globals. In a multi-worker or multi-container
deployment, `clear_token_from_cache()` only clears the process that handles the
logout. Another warm process can continue accepting its cached validation until
the five-minute token-cache TTL, even after persistent token removal. C7 adds
that most revocation paths do not call it at all. This is a separate
revocation-consistency problem and needs either shorter/no positive token
caching, a shared invalidation mechanism, or a revocation/version check.

### Module-global keys assume one application/configuration per interpreter

Actor ids and raw tokens are used without a config/application namespace. That
is normally harmless when one process hosts one ActingWeb application, but test
suites or embedded multi-app deployments can share caches across configurations.
A future cache abstraction should make process/application scope explicit.

### `Mcp-Session-Id` is being tracked against a superseded transport

`MCPContext.transport_session_id` and `_get_session_key()` key off the
`Mcp-Session-Id` header (`mcp.py:1164-1194`, `1808-1841`), per the Streamable
HTTP transport as specified in MCP revision 2025-06-18. **Revision 2026-07-28
removed protocol-level sessions entirely** and instructs servers to ignore an
inbound `Mcp-Session-Id` and not mint or echo session ids (External References).
This does not affect any finding above — the library's own reasoning already
treats the header as a transport hint and not as identity — but it is worth
knowing before any further work builds on it.

## Decisions to make

### Decision 1: Ship the tuple key alone, or hold for a broader cache rewrite?

**Options:**

1. **Ship `(actor_id, client_id)` now as an isolated patch.** Six line-level
   changes (the C5 table). No signature changes, no storage changes.
   Reproducible failure, reproducible fix, unit-testable without docker. Leaves
   C6 staleness, C7 revocation, and C4 request-scope untouched.
2. **Fold it into a cache redesign** (per-entry TTL, real cleanup scheduling,
   process-scope namespacing, shared invalidation). Fixes C6 and C7 at the same
   time. Much larger blast radius on a hot authentication path that has **zero
   existing test coverage** (C5), so the redesign must build its own safety net
   first.

**Recommendation:** Option 1, and the justification is now much stronger than a
correctness argument. This is a demonstrated authorization bypass (C11) with a
working end-to-end reproduction against a live deployment, an unbounded exposure
window on hot actors (C6), and durable corruption of trust records while it is
active (C12). It has been shipping for ten months. Nothing about a cache
redesign should delay a six-line key change.

### Decision 2: Eviction scope in the minimal patch

**Options:**

1. **Actor-wide at both sites** — `[k for k in _trust_cache if k[0] == actor_id]`.
   Preserves today's observable behaviour exactly, including that
   `clear_token_from_cache` already drops the shared `ActorInterface` for all
   clients (`mcp.py:1884-1885`).
2. **Client-scoped at `clear_token_from_cache`, actor-wide at TTL cleanup.**
   `cached_data` at `mcp.py:1876` carries `client_id`, so this is possible today.
   Narrower, but it changes logout semantics — other clients keep their cached
   trust across a peer's logout — and needs its own tests for logout, remaining
   valid tokens, and trust modification.

**Recommendation:** Option 1 in the minimal patch; revisit alongside Decision 5.

### Decision 3: How should the trust resolver match a client?

Reframed by C3: this is not "harden a fallback", it is "the only live matcher is
a substring compare, sitting behind ~12 lines of unreachable code."

**Options:**

1. **Exact `trust.oauth_client_id == client_id`, with an exact peer-id fallback.**
   Verified to round-trip on both backends on the list path (C3), and matches the
   existing exact-comparison pattern at `oauth2_server.py:886-892`. The fallback
   is required because `oauth_client_id` is only written when
   `source == "oauth2_client"`.
2. **Exact peer-id construction for the supported prefixes** — build
   `f"{via}:{normalized_email}:{normalized_client}"` per supported `via` and call
   `get_relationship` directly, restoring a real fast path and removing the O(n)
   scan. Blocked on the email not being present in `token_data` (C3), so it needs
   another source or a client-only key.
3. **Leave the substring match, delete only the dead code.** Lowest risk;
   preserves the O(n) scan and the substring compare.

**Also to decide here:** whether `established_via="oauth2_interactive"` should be
matchable at all, and whether the dead `if user_email:` block is removed or
repaired.

### Decision 4: Fail-open or fail-closed when no trust resolves?

Today: `trust_relationship is None` → `peer_id=""` → **every** permission gate
skipped and the hook dispatched (C1), while the resolver logs "permissions will
be empty" (`mcp.py:1503`). Three separate mechanisms produce this, one carrying
an explicit `# Fail-open on evaluation errors to avoid hard lockouts` comment
(`mcp.py:533`) ten lines below a deliberate fail-closed path (`mcp.py:508-512`).

**Options:**

1. **Fail closed** — a valid token with no resolvable trust gets an empty tool
   list and `-32003` on call. The correct posture at an authorization boundary;
   will break any deployment relying on the gap, including `oauth2_interactive`
   trusts (C3) if those turn out to be reachable.
2. **Fail closed on missing trust, keep fail-open on evaluator errors.** Splits
   "no principal" (a security condition) from "permission subsystem unavailable"
   (an availability condition).
3. **Status quo, documented.** No behaviour change; the fail-open remains an
   undocumented property of a security boundary.

**Note:** OWASP's Authorization Cheat Sheet and ASVS 5.0 V8 say nothing about
caching authorization decisions (External References) — this is a genuine
standards gap, so the decision has to be reasoned from first principles plus the
MCP keying rule.

### Decision 5: How to make `RuntimeContext` actually request-scoped

**Options:**

1. **`ContextVar`-backed storage behind the existing `RuntimeContext` API.**
   Matches `request_context.py` and both integration lifecycles. Must also fix
   `hooks.py:562-564` (no `copy_context()`), decide `.set(None)` vs
   `.reset(token)`, and close the Flask `after_request`-on-exception gap (C4).
2. **Fresh `ActorInterface` wrapper per MCP request, cache only the core actor.**
   Contains the leak for the only production producer of runtime context, with no
   hook-plumbing changes. Loses the wrapper's lazy sub-manager caching per
   request; leaves the abstraction flawed for any other reused wrapper.
3. **Keep attribute storage, add an explicit clear in both integrations.**
   Smallest change; fixes only sequential bleed, not overlap. Since every request
   re-sets the context before dispatch (C1), this buys very little.

This is genuinely independent of Decisions 1-4 and should not gate the cache
patch.

### Decision 6: What to do about `resources/read` under Flask (C8)

**Options:**

1. **Point `mcp.py:982` at `RuntimeContext`**, matching `async_mcp.py:332-334`,
   and update the three tests that set `_mcp_trust_context`. Turns on a
   permission check that has been off since the SDK removal — deployments
   relying on unchecked `resources/read` under Flask will start seeing denials.
2. **Fix it and treat it as a security advisory** in the release notes, since it
   is an authorization check that silently stopped running.
3. **Defer**, and document that `resources/read` is unauthorized under Flask.

Arguably higher severity than the reported cache bug — a missing check rather
than a wrong principal — but a different defect that could ship separately.

### Decision 7: Release target and security disclosure

`v3.13.0rc2` is tagged at the reviewed commit and cannot change; `Unreleased` in
`CHANGELOG.rst` is currently empty (line 5 is the heading, line 8 already begins
`v3.13.0rc2: July 26, 2026`). Both `pyproject.toml` and `actingweb/__init__.py`
read `3.13.0rc2`.

The blast-radius audit changes the character of this decision. It is no longer
only "which version number" — it is also "does this get disclosed, and how."

**Release options:**

1. **`v3.13.0rc3`** — keeps the candidate cycle open and lets the consumer
   re-validate against TestPyPI before a final tag. Given a demonstrated bypass,
   a candidate round with the consumer's escalation probe re-run is cheap
   assurance.
2. **Fold into final `v3.13.0`** — one fewer release, but the security fix ships
   without a candidate round on the consumer's preview deployment.

**Disclosure options:**

1. **Security advisory / CVE**, since the defect is an authorization bypass
   present in every release from `3.3` (2025-10-04) and the audit is a working
   escalation recipe against any deployment with two differently-typed MCP
   clients on one actor. Affected operators cannot detect past exploitation from
   the library alone.
2. **CHANGELOG security note only**, called out prominently, with backport
   guidance for anyone pinned below 3.13.
3. **Ordinary bugfix entry.** Not recommended given a demonstrated bypass, but
   it is the maintainer's call.

Relevant either way: the defect predates rc1 by roughly ten months, so it is
**not** an rc regression and does not by itself argue against finalizing.

### Decision 8: Remediating trust rows already corrupted (C12)

Fixing the cache key stops new corruption. It does not repair rows where client
A's `client_name` / `client_version` / `client_platform` / `last_accessed` /
`last_connected_via` were already written into client B's trust record.

**Options:**

1. **Do nothing; let it self-heal.** Once the key is fixed, the next request
   from each client rewrites its own record with correct metadata
   (`mcp.py:1745-1760` runs whenever the stored values differ). Audit-trail
   history stays wrong, but current values converge on their own.
2. **Ship a one-off reconciliation** that re-derives `client_name` from
   `oauth_client_id` for `established_via="oauth2_client"` rows, for operators
   who care about the audit fields.
3. **Document the corruption** in the release note so operators can decide, and
   flag that `last_connected_via` / `last_accessed` history in the affected
   window is unreliable.

Option 1 is likely sufficient for the metadata; the audit-trail question is a
judgment call. Note the consumer's own §3 durable effects — notably
`_auto_create_custom_type` stamping `created_by: "mcp_client:<peer_id>"` and
granting standing access — are **application** state and cannot be repaired by
the library; they need a consumer-side audit of their own.

### Decision summary

| Decision | Recommendation | Reason |
| --- | --- | --- |
| Is the report valid and high severity? | **Yes — authorization bypass.** | It substitutes one authenticated principal for another, and because the trust type is resolved from `peer_id`, that means a different permission rule set. Demonstrated end to end: a read-only client wrote after a read-write client authenticated (C11). |
| Ship tuple key alone or wait for redesign? | **Ship tuple key now.** | Small, correct, independently reproducible (sequentially), and it closes a demonstrated bypass that has shipped since `release_3_3`. |
| Disclosure | **Open question — see Decision 7.** | Advisory/CVE vs prominent CHANGELOG note. The audit is a working escalation recipe; affected operators cannot self-detect past exploitation. |
| Repair already-corrupted trust rows? | **Open question — see Decision 8.** | Library-side metadata self-heals after the fix; audit-trail fields and consumer-side `created_by` grants do not. |
| Cache key | **`(actor_id, client_id)` tuple.** | Both values are available before lookup, match persisted trust cardinality, and match the MCP spec's `<user_id>:<handle>` keying rule. |
| Eviction scope in the minimal patch | **Actor-wide trust eviction at both current sites.** | Preserves current behavior; optimize only after tests define narrower semantics. |
| Include exact resolver matching? | **Separate companion commit in the same security patch/release.** | C3 shows the substring compare is the *only* live matcher, not a fallback, which raises its priority relative to the first pass. |
| Treat the `RuntimeContext` race as closed by tuple key? | **No. Track separately as high priority.** | Deterministic same-actor concurrency still leaks identity, in both the threaded and async models. |
| Runtime context implementation | **`ContextVar`, API-compatible façade — plus a fix to `hooks.py:562-564`.** | Matches the repo's existing request-context architecture; the executor hop would otherwise silently lose context. |
| Missing trust behavior | **Make an explicit decision; security preference is fail-closed.** | Today empty/missing `peer_id` skips permission evaluation despite the resolver saying permissions are empty. |
| `resources/read` under Flask | **Fix, and decide whether it is advisory-worthy.** | The check has not run in production since the MCP SDK was dropped. |
| Release target | **A new version after `v3.13.0rc2`.** | `rc2` is tagged at the reviewed commit and immutable; `CHANGELOG.rst`'s `Unreleased` section is currently empty. `rc3` vs final `3.13.0` is a release-management choice. Note the defect predates rc1 by ten months, so it is not an rc regression. |

## Proposed sequencing

**Patch 1 — immediate**

- Change `_trust_cache` to tuple keys.
- Use the tuple in both read/write paths.
- Evict every tuple for an actor at both existing invalidation sites.
- Add focused A/B/A regression and eviction tests.
- Correct cache docstrings/comments that still say trust is cached per actor,
  including `docs/guides/mcp-applications.rst:839`.
- **Acceptance beyond unit tests:** re-run the consumer's escalation probe
  (two clients on one actor with differentiated trust types; confirm the
  read-only client's tool list stays at its own size and `memory_save` stays
  refused after the read-write client authenticates). The unit tests prove the
  key; the probe proves the bypass is closed.
- Consider landing the cheap invariant assertion from C11: log or fail when
  `mcp_context.client_id` does not appear in the resolved `peer_id`. It costs
  nothing and would have caught this in production.

**Patch 2 — `resources/read` authorization (C8)**

- Point the sync handler at `RuntimeContext`; update the three tests that set the
  dead attribute.
- Independent of Patch 1; arguably higher severity.

**Patch 3 — identity hardening**

- Replace substring trust resolution with exact `oauth_client_id`/peer-id
  matching; delete the unreachable direct-lookup block.
- Decide and test fail-closed behavior when no trust resolves.

**Patch 4 — request isolation**

- Move `RuntimeContext` storage to `ContextVar`s without changing hook
  signatures.
- Fix `hooks.py:562-564` to propagate context across the executor hop.
- Hook reset/clear into Flask and FastAPI lifecycles, including the
  exception path.
- Add deterministic async and threaded same-actor isolation tests.
- Update the hook guide only once "request-scoped and automatically managed" is
  true in implementation.

**Patch 5 — cache lifecycle (C6, C7)**

- Real cleanup scheduling; decide whether `_actor_cache` keeps a sliding window.
- Wire revocation paths to cache invalidation, or shorten/remove positive token
  caching. TTL should not exceed the token's own expiry.

The first patch fixes the reported cache bug. The fourth patch establishes the
stronger invariant the report ultimately needs: every hook and permission
decision sees the principal of its own request, regardless of cache warmth or
concurrent work on the same actor.

## Reproduction scripts

Both run against `cc29c03` with `poetry run python <file>`. Neither needs docker
or a database, which is why both defects are unit-testable.

### R1 — trust-cache client crossing (sequential)

```python
"""Independent reproduction of the MCP trust-cache client-crossing defect.

Only the storage and OAuth2 boundaries are mocked:
  * actingweb.actor.Actor  -> a stub core actor that "exists" in storage
  * validate_mcp_token     -> returns (actor_id, client_id, token_data)
  * actor.trust.relationships / get_relationship -> per-client trust rows

Everything else runs unchanged: the real _get_or_create_actor_cached,
the real _actor_cache / _token_cache / _trust_cache, the real
_lookup_mcp_trust_relationship, and the real RuntimeContext.
"""

import sys
from unittest import mock

sys.path.insert(0, "/Users/wedel/src/actingweb/actingweb")
sys.path.insert(0, "/Users/wedel/src/actingweb/actingweb/tests")

from actingweb.handlers import mcp as mcp_mod  # noqa: E402
from actingweb.runtime_context import RuntimeContext  # noqa: E402
from mcp_helpers import make_mcp_config, make_mcp_handler  # noqa: E402

ACTOR_ID = "actor-1"
CFG = make_mcp_config()


class FakeTrust:
    def __init__(self, client_id: str) -> None:
        self.peerid = f"oauth2_client:{client_id}:{client_id}"
        self.established_via = "oauth2_client"
        self.relationship = "mcp_client"
        self.oauth_client_id = client_id
        self.client_name = f"Client {client_id}"
        self.client_version = "1.0"
        self.client_platform = ""


TRUSTS = [FakeTrust("client-A"), FakeTrust("client-B")]


class FakeTrustManager:
    @property
    def relationships(self):
        return TRUSTS

    def get_relationship(self, peer_id):
        for t in TRUSTS:
            if t.peerid == peer_id:
                return t
        return None


class FakeCoreActor:
    def __init__(self, actor_id=None, config=None):
        self.id = actor_id
        self.config = config or CFG
        self.actor = {"id": actor_id, "creator": "user@example.com"}


TOKENS = {
    "token-A": (ACTOR_ID, "client-A", {"email": "user@example.com"}),
    "token-B": (ACTOR_ID, "client-B", {"email": "user@example.com"}),
}


class FakeOAuth2Server:
    def validate_mcp_token(self, token):
        return TOKENS.get(token)


def run_request(token: str):
    handler = make_mcp_handler({"Authorization": f"Bearer {token}"}, cfg=CFG)
    with (
        mock.patch("actingweb.actor.Actor", FakeCoreActor),
        mock.patch(
            "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
            return_value=FakeOAuth2Server(),
        ),
        mock.patch.object(
            mcp_mod.MCPHandler, "_mark_client_peer_approved", lambda *a, **k: None
        ),
        mock.patch.object(
            mcp_mod.ActorInterface,
            "trust",
            property(lambda self: FakeTrustManager()),
        ),
    ):
        actor_iface = handler.authenticate_and_get_actor_cached()
    assert actor_iface is not None, f"auth failed for {token}"
    ctx = RuntimeContext(actor_iface).get_mcp_context()
    return (token, ctx.client_id, ctx.peer_id, id(actor_iface))


if __name__ == "__main__":
    results = [run_request(t) for t in ("token-A", "token-B", "token-A", "token-B")]
    print("token       ctx.client_id  ctx.peer_id                       actor obj id")
    for tok, cid, pid, oid in results:
        print(f"{tok:11} {cid:14} {pid:33} {oid}")
    print()
    print("_trust_cache keys:", list(mcp_mod._trust_cache.keys()))
    print("cache stats:", mcp_mod._cache_stats)
```

Output is quoted in C1.

Note: this script supplies `{"email": ...}` in `token_data`, which the production
token record does **not** contain (C3). That makes the reproduction strictly
*more* favourable to the code than reality — it gives the direct lookup at
`mcp.py:1443` a chance to fire, which it still misses on the prefix mismatch.
The defect reproduces either way, and a regression test should use the realistic
(email-free) `token_data`.

### R2 — `RuntimeContext` cross-request leak (asyncio and threads)

```python
"""Deterministic reproduction of the RuntimeContext cross-request leak.

Uses the real RuntimeContext against one shared ActorInterface-like object,
exactly as the MCP actor cache hands it out. No cache involvement at all --
this is independent of the trust-cache key defect.
"""

import asyncio
import sys
import threading

sys.path.insert(0, "/Users/wedel/src/actingweb/actingweb")

from actingweb.runtime_context import RuntimeContext  # noqa: E402


class SharedActor:
    """Stands in for the cached ActorInterface handed to every request."""

    id = "actor-1"


class Trust:
    def __init__(self, peer):
        self.peerid = peer
        self.client_name = peer


shared = SharedActor()


def authenticate(client_id):
    """What authenticate_and_get_actor_cached does at mcp.py:1266-1276."""
    RuntimeContext(shared).set_mcp_context(
        client_id=client_id,
        trust_relationship=Trust(f"peer-{client_id}"),
        peer_id=f"peer-{client_id}",
    )


def read_peer():
    """What the permission checks / hooks do."""
    return RuntimeContext(shared).get_mcp_context().peer_id


async def async_scenario():
    gate = asyncio.Event()

    async def request(client_id, wait_before_read):
        authenticate(client_id)
        if wait_before_read:
            await gate.wait()  # any await in the dispatch path
        else:
            gate.set()
        await asyncio.sleep(0)
        return client_id, read_peer()

    a = asyncio.create_task(request("A", True))
    await asyncio.sleep(0)
    b = asyncio.create_task(request("B", False))
    return await asyncio.gather(a, b)


def thread_scenario():
    barrier = threading.Barrier(2)
    out = {}

    def request(client_id, first):
        authenticate(client_id)
        barrier.wait()  # both have authenticated; now both read
        out[client_id] = read_peer()

    t1 = threading.Thread(target=request, args=("A", True))
    t2 = threading.Thread(target=request, args=("B", False))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    return out


if __name__ == "__main__":
    print("asyncio (single-threaded event loop, interleaved at an await):")
    for client_id, peer in asyncio.run(async_scenario()):
        mark = "OK " if peer == f"peer-{client_id}" else "LEAK"
        print(f"  {mark} request {client_id} read {peer}")

    print("\nthreads (Flask/WSGI model):")
    for client_id, peer in sorted(thread_scenario().items()):
        mark = "OK " if peer == f"peer-{client_id}" else "LEAK"
        print(f"  {mark} request {client_id} read {peer}")
```

Output is quoted in C4.

## Code References

**The defect**

- `actingweb/handlers/mcp.py:46` — `_trust_cache: dict[str, Any] = {}  # actor_id -> trust_relationship`
- `actingweb/handlers/mcp.py:1255-1257` — trust-cache read, keyed by `actor_id` alone
- `actingweb/handlers/mcp.py:1263` — hot-path miss write
- `actingweb/handlers/mcp.py:1331` — full-auth write
- `actingweb/handlers/mcp.py:1266-1276`, `1339-1347` — the two `set_mcp_context` calls
- `actingweb/handlers/mcp.py:1270-1272`, `1343` — `peer_id = trust.peerid if trust else ""`
- `actingweb/handlers/mcp.py:1239`, `1310` — where the correct `client_id` is in hand
- `actingweb/handlers/mcp.py:152-155`, `1884-1888` — the two eviction sites
- `actingweb/handlers/mcp.py:1876-1877` — cached token record carries `client_id`
- `actingweb/handlers/mcp.py:43-45` — `_actor_cache` comment promises a `trust_context` field never written

**Consumers of `peer_id`**

- `actingweb/handlers/mcp.py:515`, `674`, `743`, `803`, `880`, `984` — permission gates
- `actingweb/handlers/async_mcp.py:148`, `230`, `335` — async gates
- `actingweb/handlers/async_mcp.py:99-103` — list methods route to the inherited sync handlers
- `actingweb/handlers/mcp.py:508-512` vs `529-533` — fail-closed and fail-open, ten lines apart
- `actingweb/permission_evaluator.py:92-96`, `116-120` — `NOT_FOUND` / `DENIED` returns

**Trust resolution**

- `actingweb/handlers/mcp.py:1423-1509` — `_lookup_mcp_trust_relationship`
- `actingweb/handlers/mcp.py:1441-1452` — dead direct lookup (`if user_email:` never true)
- `actingweb/handlers/mcp.py:1457-1478` — the only live matcher, `client_id in peer_id_str`
- `actingweb/oauth2_server/oauth2_server.py:637-647` — `validate_mcp_token` delegation
- `actingweb/oauth2_server/token_manager.py:224-249` — `validate_access_token` return tuple
- `actingweb/oauth2_server/token_manager.py:349-359`, `997-1007` — stored `token_data` keys (no email)
- `actingweb/interface/trust_manager.py:440`, `451-463` — peer-id prefix is `established_via`
- `actingweb/interface/trust_manager.py:506-507`, `578-579` — `oauth_client_id` written only for `oauth2_client`
- `actingweb/interface/trust_manager.py:119-122` — `TrustRelationship.oauth_client_id`
- `actingweb/db/dynamodb/trust.py:491-492`, `actingweb/db/postgresql/trust.py:756-757` — `oauth_client_id` on the list read path
- `actingweb/oauth2_server/client_registry.py:51` — `client_id = f"mcp_{secrets.token_hex(16)}"`
- `actingweb/oauth2_server/client_registry.py:441-453`, `actingweb/oauth2_server/oauth2_server.py:379`, `394-401` — the two live `oauth2_client` creation paths
- `actingweb/handlers/oauth2_callback.py:630-638` — the `oauth2_interactive` writer
- `actingweb/oauth2_server/state_manager.py:182-188` — `extract_mcp_context` gate
- `actingweb/oauth2_server/oauth2_server.py:886-892`, `actingweb/handlers/www.py:549-551` — existing exact-match precedent
- `actingweb/constants.py:156-162` — `ESTABLISHED_VIA_*` values

**Privilege escalation chain (C11) and durable write (C12)**

- `actingweb/oauth2_server/client_registry.py:68` — `trust_type` taken from the registration request
- `actingweb/oauth2_server/client_registry.py:441-443` — trust type passed as the relationship
- `actingweb/interface/trust_manager.py:583-601` — stored as the trust row's `relationship`
- `actingweb/permission_evaluator.py:471-478` — trust type resolved *from `peer_id`*, selecting the rule set
- `actingweb/trust_type_registry.py:381` — only `mcp_client` ships built in; RO/RW variants are app-registered
- `actingweb/trust_permissions.py:144`, `peer_permissions.py:254`, `peer_capabilities.py:524`, `peer_profile.py:151` — downstream caches correctly keyed `f"{actor_id}:{peer_id}"` (no second-order pollution)
- `actingweb/handlers/mcp.py:1696-1705` — `_update_trust_with_client_info` reads the poisoned `peer_id`
- `actingweb/handlers/mcp.py:1745-1760` — `modify_trust_and_notify` writes client metadata against it
- `actingweb/handlers/mcp.py:247`, `349`, `1665-1676`; `actingweb/handlers/async_mcp.py:93` — call sites: every request carrying `clientInfo`, not only `initialize`
- `actingweb/handlers/mcp.py:1239` → `:1268`, `:1310` → `:1341` — `MCPContext.client_id` is correct on both paths (the detection signal)

**Staleness and revocation**

- `actingweb/handlers/mcp.py:1221-1223` — `if time.time() % 20 == 0`
- `actingweb/handlers/mcp.py:1251`, `1366` — sliding `last_accessed`
- `actingweb/handlers/mcp.py:1334-1336` — `_mark_client_peer_approved` after the cache write
- `actingweb/handlers/mcp.py:1855-1890` — `clear_token_from_cache`
- `actingweb/handlers/oauth2_endpoints.py:857-866` — its only caller
- `actingweb/handlers/mcp.py:21`, `42-47`, `50-57` — all six caches are module globals

**Request scope**

- `actingweb/runtime_context.py:46`, `125-129` — attribute-on-actor storage
- `actingweb/runtime_context.py:266-275` — `clear_context`, no production caller
- `actingweb/runtime_context.py:176-201`, `213-238` — `set_oauth2_context` / `set_web_context`, no production callers
- `actingweb/handlers/mcp.py:1363-1367`, `1411-1421` — the shared `ActorInterface`
- `actingweb/request_context.py:3-8`, `16-18`, `227-244` — existing ContextVars, cleared via `.set(None)`
- `actingweb/interface/integrations/flask_integration.py:73-115`, `1388-1390` — Flask lifecycle and per-request handler
- `actingweb/interface/integrations/fastapi_integration.py:461`, `474-476`, `538-573`, `2340` — FastAPI lifecycle, `copy_context`, async handler
- `actingweb/interface/hooks.py:562-564` — `executor.submit(asyncio.run, ...)` with no `copy_context()`
- `actingweb/interface/app.py:1476` — `flask_app.run()` (threaded by default)
- `actingweb/handlers/async_mcp.py:75`, `105-109`, `180`, `261`, `383` — sync auth, inline awaits, hook awaits
- `actingweb/auth.py:164, 258, 285, 337, 360, 418, 582, 609` — `request_context.set_peer_id` callers

**Dead permission check**

- `actingweb/handlers/mcp.py:982-984` — reads `_mcp_trust_context`, set only in tests
- `tests/test_mcp_permissions.py:40`, `tests/test_mcp_tool_visibility.py:19`, `tests/test_mcp_tool_schema_fields.py:21` — the only writers

**Documentation**

- `docs/guides/mcp-applications.rst:836-839` — "cached per actor"
- `docs/guides/caching.md:26-41`, `119-144`, `389` — the unimplemented correct design
- `docs/guides/hooks.rst:304`, `316-319` — the request-scope claim

**Tests**

- `tests/test_runtime_context_unit.py:23-99` — 5 tests, fresh actor each
- `tests/integration/test_runtime_context_advanced.py:247` — the only `clear_context()` call in the repo
- `tests/integration/test_runtime_context_advanced.py:252-293` — isolation test that cannot catch this
- `tests/test_mcp_session_key.py` — the one MCP cache with coverage (`_mcp_client_info_cache`)
- `tests/mcp_helpers.py` — handler/config construction used by R1

**History**

- `613cc27` (PR #17, 2025-10-04, `release_3_3`) — introduced `_trust_cache` and `_mcp_trust_context`
- `c61e059` — dropped the MCP SDK, orphaning the `_mcp_trust_context` read
- `9ab3171` — typing modernization; key shape unchanged

## External References

### MCP specification — normative support for the tuple key

- **[MCP Security Best Practices, revision 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices)** —
  the strongest external citation for C2. On state-handle hijacking: MCP servers
  "**SHOULD** bind handles server-side to the authenticated user, for example by
  keying stored state as `<user_id>:<handle>` where the user ID is derived from
  the verified token rather than supplied by the client, and reject a handle
  presented by any other principal." The `(actor_id, client_id)` tuple *is* that
  rule. The 2025-06-18 wording is the same with `<user_id>:<session_id>`.
  Also: servers "**MUST NOT** treat possession of a state handle as
  authentication", and "**MUST NOT** accept any tokens that were not explicitly
  issued for the MCP server."
- **[MCP Authorization, 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)** —
  "authorization **MUST** be included in every HTTP request from client to
  server, **even if they are part of the same logical session**", plus audience
  binding per RFC 8707. Read together with the keying rule, the spec's position
  is that the token, revalidated per request, is the identity carrier; the
  session is not. Anything cached from it must be keyed by the principal that
  token resolves to. Carried forward verbatim into
  [2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
- **[MCP Streamable HTTP, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)** —
  "Removal of protocol-level sessions"; servers should "ignore" an inbound
  `Mcp-Session-Id` and "not mint or echo session IDs." Relevant to
  `MCPContext.transport_session_id` (see Adjacent observations), not to any
  finding above. Current revision per
  [MCP Versioning](https://modelcontextprotocol.io/specification/versioning).
- **No MCP guidance exists** on multiple concurrent clients sharing one OAuth
  credential. [SEP-1299](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1299)
  proposes per-client-instance cryptographic binding but is closed and
  unadopted; see also discussions
  [#234](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/234)
  and [#483](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/483).
  The server-side identity-keying problem is left to the implementer.

### Cache key correctness as a security concern

- **No CWE names this flaw exactly.** Closest fits, ranked:
  [CWE-668 Exposure of Resource to Wrong Sphere](https://cwe.mitre.org/data/definitions/668.html)
  (best abstraction; parent of the next two);
  [CWE-488 Exposure of Data Element to Wrong Session](https://cwe.mitre.org/data/definitions/488.html)
  (closest on impact — "data can 'bleed' from one session to another through
  member variables of singleton objects… and objects from a shared pool", which
  describes **both** C1 and C4);
  [CWE-639](https://cwe.mitre.org/data/definitions/639.html) is the wrong
  mechanism (attacker-modified key, not server-computed-but-incomplete);
  [CWE-524](https://cwe.mitre.org/data/definitions/524.html) is about
  unauthorized read access to a cache, not key design.
  With C11's demonstrated escalation,
  [CWE-863 Incorrect Authorization](https://cwe.mitre.org/data/definitions/863.html)
  and [CWE-269 Improper Privilege Management](https://cwe.mitre.org/data/definitions/269.html)
  become defensible *impact* labels alongside CWE-488, if an advisory is filed
  (Decision 7).
- **[PortSwigger, Web cache poisoning](https://portswigger.net/web-security/web-cache-poisoning)** —
  supplies the precise vocabulary: components of a request not included in the
  cache key are "**unkeyed**". Principal identity here is an unkeyed input, so
  the cache serves principal B the value computed for principal A.
- **[OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)**
  and **[OWASP ASVS 5.0 V8](https://github.com/OWASP/ASVS/blob/master/5.0/en/0x17-V8-Authorization.md)** —
  **neither mentions caching authorization decisions at all**. A genuine
  standards gap, relevant to Decision 4. The nearest guidance is "Permission
  should be validated correctly on every request."
- **[RFC 7662 §4](https://datatracker.ietf.org/doc/html/rfc7662#section-4)** — the
  authority for C7: "the token may be revoked while the protected resource is
  relying on the value of the cached response to make authorization decisions.
  This creates a window during which a revoked token could be used." And the
  hard constraint from §2.2: a response "**MUST NOT** be cached beyond the time
  indicated" by `exp`. Design rule: TTL ≤ token expiry, and the revocation window
  equals the TTL — per process. RFC 7662 does not address multi-process
  propagation.
- **[RFC 9700 / BCP 240](https://www.rfc-editor.org/rfc/rfc9700.html)** —
  sender-constrained (§2.2.1) and audience-restricted (§2.3) access tokens.
  Nothing on resource-server caching of validation results.

### ContextVars across WSGI and ASGI (Decision 5)

- **[CPython `contextvars`](https://docs.python.org/3/library/contextvars.html)** —
  "Each thread has its own effective stack of `Context` objects"; ContextVars
  "behave in a similar fashion to `threading.local()` when values are assigned in
  different threads." `Token`/`reset()` restores "the value it had before the
  `ContextVar.set()` that created the token"; the same token cannot be used
  twice. Python 3.14 adds `with var.set(value):`.
- **[gunicorn `gthread` worker](https://github.com/benoitc/gunicorn/blob/master/gunicorn/workers/gthread.py)** —
  dispatches `self.tpool.submit(self.handle, conn)` into a reused
  `ThreadPoolExecutor` with **no** `copy_context()`. This is why a `set()`
  without `reset()` leaks into the next request on a threaded WSGI worker — the
  concrete risk behind C4 constraint 2/3.
- **[Flask `ctx.py`](https://github.com/pallets/flask/blob/main/src/flask/ctx.py)** —
  the correct pattern: `self._cv_token = _cv_app.set(self)` on push,
  `_cv_app.reset(self._cv_token)` on pop.
- **[asyncio task/thread boundaries](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)** —
  `create_task` copies the current context (child sets invisible to parent);
  `asyncio.to_thread` **propagates** context; `loop.run_in_executor`
  **does not** (confirmed in CPython `base_events.py`). This asymmetry is
  directly relevant to `hooks.py:562-564` and
  `fastapi_integration.py:538-573`.
- **[Starlette middleware docs](https://www.starlette.io/middleware/)** —
  "Using `BaseHTTPMiddleware` will prevent changes to `contextvars.ContextVar`s
  from propagating upwards." ActingWeb's `RequestContextMiddleware`
  (`fastapi_integration.py:407-476`) is a `BaseHTTPMiddleware`, so downstream
  sets (e.g. `auth.py`'s `set_peer_id`) do not flow back up to it. Mechanism
  explained in [discussion #1729](https://github.com/Kludex/starlette/discussions/1729);
  see also [#2160 "Deprecating BaseHTTPMiddleware"](https://github.com/Kludex/starlette/discussions/2160).
- **Prior art:** [structlog contextvars](https://www.structlog.org/en/stable/contextvars.html)
  (clear-at-request-entry discipline);
  [OpenTelemetry Context spec](https://opentelemetry.io/docs/specs/otel/context/)
  (attach/detach = the same token/reset contract, with explicit wrong-call-order
  detection); [asgi-correlation-id](https://github.com/snok/asgi-correlation-id)
  (sets without reset — safe under pure ASGI task-per-request, would leak under
  threaded WSGI; same `X-Request-ID` convention ActingWeb uses).

### Caveats on the external material

- The MCP docs site appears to backport content into archived revision paths, so
  attribution of the `<user_id>:<session_id>` text specifically to the 2025-06-18
  revision is uncertain. The 2026-07-28 successor text is unambiguous and says
  the same thing.
- The threaded-WSGI leak conclusion is an inference from three separately
  confirmed facts (per-thread context stack; gunicorn's uncopied
  `ThreadPoolExecutor`; Flask's explicit token/reset), not a single documented
  statement. The threaded scenario in R2 demonstrates the equivalent shared-state
  leak directly for the attribute-based storage ActingWeb uses today.
