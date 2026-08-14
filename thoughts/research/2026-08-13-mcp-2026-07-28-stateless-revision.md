# Research: MCP 2026-07-28 stateless revision — what it means for the library's hand-rolled MCP handler

**Date:** 2026-08-13
**Branch:** master
**Commit:** 3c497a3 (v3.13.0rc6)

## Research Question

The MCP specification revision published 2026-07-28 (SEP-2567, SEP-2575)
removes the `initialize` handshake and protocol-level sessions, making MCP a
stateless request/response protocol. ActingWeb implements MCP by hand and
advertises support up to `2025-11-25`.

What does the revision change, what breaks, and what would the library have to
do to serve modern clients?

## Summary

**This is a breaking protocol change with no automatic fall-forward, and the
library owns all of it.** `actingweb/mcp/protocol.py:4-6` states the position
plainly: the library implements MCP by hand and does not depend on the official
`mcp` SDK. Nothing arrives for free on an SDK bump — but equally, no SDK bump
can break us. The whole 2026-07-28 surface is ours to implement or decline.

**Nothing is broken today, and the reason is a happy accident worth
protecting.** The spec's compatibility model has three client eras, not two.
*Modern → legacy* fails, but ***dual-era* → legacy explicitly "Works"**, via a
client-side fallback triggered by a `4xx` whose body is **not** a recognised
modern error. Traced through our code: a 2026-07-28 request carries
`MCP-Protocol-Version: 2026-07-28`, hits `_resolve_request_protocol_version`
(`actingweb/handlers/mcp.py:1390-1426`), and returns HTTP 400 + JSON-RPC
`-32600` — a *standard* code, outside the MCP-reserved `-32020`–`-32099` range.
The spec: *"Anything else identifies a legacy server."* The client then falls
back to `initialize`, which we serve and which we deliberately exempt from
version validation (`actingweb/handlers/mcp.py:377-382`).

**The most important finding is a negative one: do not "improve" that error.**
Returning a spec-shaped `-32022` with a `data.supported` array would *break*
dual-era clients — `-32022` identifies a **modern** server, so the client would
stop falling back and instead retry a modern-shaped request declaring
`2025-11-25`, which is incoherent because that version requires `initialize`.
The current `-32600`-without-`data.supported` is the correct legacy-only
signal. It was written as ordinary spec compliance, not as a deliberate era
signal, and **no test asserts it in that role**.

**Two mechanisms in the library become permanently dead rather than broken.**
`Mcp-Session-Id` is read but never issued or validated
(`actingweb/handlers/mcp.py:1428-1458`, `:2135-2168`); the downstream consumer
records it as null on 100 % of production rows. And `_mcp_client_info_cache`
(`:21`, `:2114-2133`) is a module-global keyed on that header with an
`ip+hash(UA)` fallback — already unreliable in any multi-process deployment,
which the existing `todo/mcp-cache-lifecycle-and-revocation.md` item 4 already
tracks from a different angle.

**Urgency is set entirely by a fact we could not verify:** when, or whether,
any client ships *modern-only*. Anthropic's announcement says "rolling out
across Claude products soon" with no per-surface dates; the Claude Code
changelog has zero matches for the revision. Legacy clients are unaffected
indefinitely; dual-era clients degrade to us successfully; modern-only clients
fail by design.

## Detailed Findings

### 1. What the revision removes and adds

Prior revision was `2025-11-25`. From the
[changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog),
verbatim:

> Remove protocol-level sessions and the `Mcp-Session-Id` header from the
> Streamable HTTP transport. … Servers that need cross-call state use explicit,
> server-minted handles passed as ordinary tool arguments (SEP-2567).

> Make MCP stateless: remove the `initialize`/`notifications/initialized`
> handshake. Every request now carries its protocol version and client
> capabilities in `_meta` … (SEP-2575).

**Removed outright, not deprecated** — none appear in the
[deprecated registry](https://modelcontextprotocol.io/specification/2026-07-28/deprecated):
`initialize`, `notifications/initialized`, `Mcp-Session-Id` + DELETE teardown,
`ping`, `logging/setLevel`, the standalone GET SSE stream,
`resources/subscribe`/`unsubscribe`, SSE resumability (`Last-Event-ID`).

Every one of those except the SSE machinery is something this library
implements today.

**Added, mandatory for a modern server:**

| Surface | Requirement |
| --- | --- |
| `_meta` `io.modelcontextprotocol/protocolVersion` | **Required** on every request |
| `_meta` `io.modelcontextprotocol/clientCapabilities` | **Required**; missing capability → `-32021` |
| `_meta` `io.modelcontextprotocol/clientInfo` | **Optional** (SHOULD) — identity is no longer guaranteed |
| `server/discover` | Servers **MUST** implement |
| `MCP-Protocol-Version` header | **MUST** mirror the `_meta` field; mismatch → `-32020` |
| `Mcp-Method`, `Mcp-Name`, `Mcp-Param-{Name}` | **REQUIRED** request headers |
| `ttlMs` + `cacheScope` on list/read results | **MUST** include (SEP-2549) |
| Unknown modern method | **MUST** return HTTP `404` + `-32601` |

Elicitation moves to Multi Round-Trip Requests (MRTR, SEP-2322): a server
returns `resultType: "input_required"` with an opaque `requestState` blob the
client echoes back on a *new* request id. The spec requires servers to treat it
as attacker-controlled — integrity protection (HMAC/AEAD), principal binding,
TTL — and to enforce single-use server-side where that matters. **Roots,
Sampling and Logging are newly deprecated** (SEP-2577) under a new twelve-month
window; Dynamic Client Registration is deprecated too (still functional this
revision). Elicitation is the surviving client feature.

### 2. Where the library sits today

- **Versions:** `["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]`,
  `LATEST` = `2025-11-25`, default-when-header-absent `2025-03-26`
  (`actingweb/mcp/protocol.py:28-39`).
- **Transport:** JSON-RPC over plain HTTP POST. `GET /mcp` returns a static
  discovery dict (`actingweb/handlers/mcp.py:331-363`); no SSE, no
  `StreamingResponse`, no DELETE route — non-GET/POST is 405
  (`actingweb/interface/integrations/fastapi_integration.py:2365-2366`).
- **Handler size:** `actingweb/handlers/mcp.py` 2313 lines,
  `actingweb/handlers/async_mcp.py` 457, dispatching by hand. The value in
  those lines is the ActingWeb-specific wiring — `_require_mcp_peer_id`
  (`:564-594`), the permission evaluator (`:1056-1059`), trust-row writes
  (`:2088-2096`) — not the JSON-RPC plumbing.
- **Methods implemented:** `initialize`, `notifications/initialized`, `ping`,
  `tools/list`, `tools/call`, `resources/list`, `resources/read`,
  `prompts/list`, `prompts/get`. Anything else → `-32601` (`:434-436`).
- **Not implemented:** `resources/templates/list`, `resources/subscribe`,
  `completion/complete`, `logging/setLevel`, sampling, roots. `elicit` appears
  nowhere in the codebase.
- **Client capabilities are never parsed.** `_handle_initialize`
  (`:492-562`) reads only `protocolVersion` and `clientInfo`. A modern server
  MUST enforce declared capabilities and return `-32021` when one is missing —
  we have no machinery for that at all.

### 3. The fallback path, traced

First contact from a 2026-07-28 client against the library as it stands:

1. Any method other than `initialize` carries `MCP-Protocol-Version: 2026-07-28`.
2. `_resolve_request_protocol_version` (`actingweb/handlers/mcp.py:1409-1423`)
   reads the header (both casings), finds it unsupported, sets HTTP 400 and
   returns JSON-RPC `-32600` with message
   `"Unsupported MCP-Protocol-Version: 2026-07-28"`.
3. `-32600` is a standard JSON-RPC code. The MCP-reserved range is
   `-32020`–`-32099`, holding exactly `HeaderMismatch` (`-32020`),
   `MissingRequiredClientCapability` (`-32021`) and
   `UnsupportedProtocolVersion` (`-32022`).
4. Per the spec's HTTP detection procedure, a body that is *not* a recognised
   modern error means "legacy server" → the client falls back to `initialize`.
5. We serve `initialize` and deliberately skip header validation on it
   (`:377-382`), so the fallback lands on a working path.
6. Era determination is cached per origin, so the cost is **one** rejected
   request per client, not per call.

The relevant matrix rows, verbatim from
[Versioning and Compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning):

> | Modern | Legacy | **Fails.** The server may reject the request with an
> implementation-defined error, stay silent, or even process an era-ambiguous
> method under legacy semantics. …

> | Dual-era | Legacy | **Works.** … HTTP: the modern request returns a `4xx`
> without a recognized modern error body, and the client falls back to
> `initialize` …

**Residual risk.** The probe is `MAY`, body inspection is `SHOULD`, and the
fallback instruction itself carries **no RFC-2119 keyword**. "Recognized modern
JSON-RPC error" is never defined as a closed set — only via "such as". The
spec's summary sentence (*"Anything else identifies a legacy server"*) is the
strongest protection available. Low risk, non-zero, per-client
implementation-dependent.

**This makes the `-32600` shape load-bearing and untested-as-such.**
`tests/test_mcp_wire_shape.py` covers version gating for `structuredContent`,
not this. A future cleanup that "upgrades" the error to a spec-shaped `-32022`
would read as an improvement in review and would silently break dual-era
fallback.

### 4. What becomes dead rather than broken

**`Mcp-Session-Id`.** Read at `_resolve_transport_session_id`
(`actingweb/handlers/mcp.py:1428-1458`) and `_get_session_key` (`:2135-2168`),
surfaced to hooks as `MCPContext.transport_session_id`
(`actingweb/runtime_context.py:134-139`). Never generated, never validated, no
response header anywhere. The fallback key is
`f"{client_ip}:{hash(user_agent[:50])}"`, degenerating to the placeholder
`"unknown:0"` when IP and UA are both absent (`:1439-1441`).

Downstream evidence from the consumer repo (`actingweb_mcp`): the field is
persisted as `RunRecord.started_by_transport_session_id` and used for
run-ownership fencing, and that repo's own code records it as **null on 100 %
of production run records** — the header never arrives in practice. Removing it
from the spec makes an already-inert guard permanently inert. The ownership
check that actually runs keys on `peer_id` and is untouched.

**`_mcp_client_info_cache`.** Module-global dict (`:21`), 600 s TTL
(`:2125-2133`), keyed by the same session key. It stores `clientInfo` at
`initialize` and reads it on later requests. With `initialize` gone and
`clientInfo` optional-per-request, its write path disappears. Note the library
already reads `clientInfo` opportunistically on non-`initialize` requests
(`:414-416`, *"MCP clients send clientInfo with many requests, not just
initialize"*) — which is directionally what the new revision formalises.

Durable client identity survives regardless: `_update_trust_with_client_info`
(`:2088-2096`) writes `client_name`/`client_version`/`client_platform` onto the
trust row, and `get_client_info_from_context`
(`actingweb/runtime_context.py:430-479`) falls back to it.

**`_handle_notifications_initialized`** (`actingweb/handlers/mcp.py:392-393`,
`:1361-1370`) loses its caller entirely — the notification it answers no longer
exists in the modern revision. It currently responds even to a true
notification (returning `"id": null`) because, per its own comment, some
clients send it as a request.

Existing related item: `todo/mcp-cache-lifecycle-and-revocation.md` §4 already
flags `_mcp_client_info_cache` as keyed by a client-supplied header, and §2 the
absence of cross-process invalidation.

### 5. What a dual-era server would have to do

The spec permits one endpoint to serve both eras:

> A dual-era **server** selects its behavior from how the client opens:
> * A request carrying modern per-request `_meta` is served statelessly …
> * An `initialize` request selects legacy semantics …

**The discipline is: branch on the presence of modern `_meta`, never on method
name.** `ping` is the documented trap — it takes no parameters, so nothing in
its shape distinguishes eras. A `ping` carrying modern `_meta` is a modern
request for a method that no longer exists, and must get `404` + `-32601`; a
`ping` without it is legacy and answered normally. Answering every `ping`
unconditionally lets a half-modern client conclude we support a removed method.

`notifications/initialized` has the identical shape and needs the identical
treatment: no meaningful params, unauthenticated, and removed in 2026-07-28
alongside `initialize`. Together with `ping` these are the library's only two
unauthenticated methods (`actingweb/handlers/mcp.py:392-395`), and both are
era-ambiguous by construction.

Gap list against the current handler:

| Needed | Status today |
| --- | --- |
| Modern `_meta` parsing + era branch | absent |
| `server/discover` | absent |
| Capability enforcement → `-32021` | capabilities never parsed (`:492-562`) |
| Header mirroring validation → `-32020` | absent |
| `404` + `-32601` for unknown modern methods | currently `-32601` with 200 |
| `ttlMs` + `cacheScope` on list/read results | absent |
| MRTR + signed `requestState` | no elicitation at all |
| `subscriptions/listen` | needs SSE; see §6 |

**A caching trap specific to this library.** `tools/list` output is
permission-filtered per peer (`:753-759`), so it varies by caller. That forces
`cacheScope: "private"` — `"public"` would authorise shared gateways to serve
one actor's tool list to another. The spec permits per-credential variation but
**forbids** per-connection variation:

> The set **MAY** vary by the authorization presented on the request … since
> credentials are per-request input, not connection state.

Our filtering keys on the resolved `peer_id` from the bearer token, which is
per-request input — compatible, but it must be `private`.

### 6. Deployment shapes that constrain the answer

The library is transport-agnostic, but its primary consumer runs FastAPI under
Mangum on AWS Lambda behind API Gateway **HTTP API v2**, which buffers the full
response. SSE is architecturally unavailable there, so `subscriptions/listen`
(a long-lived pinned POST stream) cannot be served on that deployment
regardless of what the library implements. It is opt-in, so this is a
limitation rather than a compliance failure.

Also relevant for any implementation that adds required request headers: the
new `Mcp-Param-{Name}` headers are **dynamically named**, so a CORS
`allowedHeaders` allow-list cannot enumerate them — and `'*'` is not usable
where `Authorization` is in play. Only affects browser-based MCP clients;
server-side clients never preflight.

The module-global caches are per-process and per-warm-container; the
statelessness the revision assumes is something this deployment already
violates quietly rather than loudly.

### 7. Documentation mismatches found while reading

Recorded, not fixed:

1. `actingweb/handlers/mcp.py:281` says the handler "Delegates the request to
   the FastMCP server"; it dispatches JSON-RPC by hand and
   `actingweb/mcp/protocol.py:4-6` says there is no SDK dependency.
2. `actingweb/handlers/oauth2_endpoints.py:795` advertises
   `capabilities.resources: False` in the published
   `/.well-known/oauth-protected-resource/mcp` document, while consumers
   register resources and `_handle_initialize` computes the capability
   dynamically (`actingweb/handlers/mcp.py:531-536`).
3. `actingweb/handlers/oauth2_endpoints.py:744` cites **RFC 8705** for the
   document served at the RFC 9728 path.
4. `actingweb/pyproject.toml:56-60` declares extras `postgresql`, `flask`,
   `fastapi`, `all` — but consumers request `mcp` and `dynamodb`, neither of
   which exists.
5. Sync/async `resources/read` formatting divergence — already recorded as
   `todo/mcp-cache-lifecycle-and-revocation.md` §8.

## Decisions Needed

### Decision 1: Does the library go dual-era, and when?

Deferred by design — see `todo/mcp-2026-07-28-dual-era-support.md` for the
trigger criteria this research produced.

**Options:**

1. **Wait for a trigger.** Zero cost. Legacy clients are unaffected and
   dual-era clients fall back successfully. Risk: we learn a client went
   modern-only from user reports, since the rejection currently logs at debug
   level only.
2. **Implement dual-era pre-emptively.** Removes timeline risk for a revision
   no client we serve is confirmed to speak, at the cost of the §5 gap list
   across a 2313-line handler.
3. **Minimum modern read path only** — `server/discover`, `_meta` parsing,
   `tools/list` + `tools/call`, caching hints — deferring MRTR and
   `subscriptions/listen` (the latter unusable on the primary deployment).

### Decision 2: Adopt the official Python SDK, or keep hand-rolling?

The revision is the first change large enough to make this worth re-asking.
`mcp` Python SDK v2.0.0 shipped 2026-07-28 with dual-era support,
`server/discover`, `subscriptions/listen` and MRTR; v1.x is maintenance-only.

**Options:**

1. **Adopt the SDK.** Gets the whole modern surface for free and permanently.
   Cost: the library's MCP layer is not JSON-RPC plumbing but ActingWeb trust
   and permission wiring threaded through every method — `_require_mcp_peer_id`,
   the permission evaluator, trust-row writes, the actor cache. Those would
   have to be re-expressed against `MCPServer` and the new resolver
   dependency-injection model. Also introduces a hard dependency the library
   has deliberately avoided (`actingweb/mcp/protocol.py:4-6`), affecting every
   consumer's dependency tree.
2. **Keep hand-rolling.** Consistent with the current design and keeps the
   trust wiring untouched; every item in §5 is then ours to write and test.
3. **Hybrid** — SDK for wire-format/era handling, ActingWeb hooks for
   authorization. Needs a spike to establish whether the SDK's extension points
   can carry per-peer permission filtering on `tools/list`.

### Decision 3: Protect the `-32600` era signal now?

Independent of Decisions 1 and 2, and cheap.

**Options:**

1. **Add a regression test** asserting HTTP 400 + `-32600` **without**
   `data.supported` for an unsupported future version, with a comment naming it
   as the dual-era fallback trigger. Prevents a well-intentioned future
   "upgrade" to `-32022`.
2. **Enrich the error message string** to name supported versions. The spec
   applies exactly this reasoning to the mirror-image case: a server SHOULD
   name its versions because for a client with no fall-forward *"this message
   may be the only diagnostic they can surface to users."* Must go in the
   free-text `message`, **not** `data.supported`.
3. **Raise the log level** on unsupported-version rejections so a client-era
   shift is visible in telemetry rather than in user reports.

These compose; they are not mutually exclusive.

## Code References

- `actingweb/mcp/protocol.py:4-6` — no MCP SDK dependency, by design
- `actingweb/mcp/protocol.py:8-13` — "supported" means negotiable, not fully implemented
- `actingweb/mcp/protocol.py:28-39` — supported versions, default `2025-03-26`
- `actingweb/handlers/mcp.py:377-382` — `initialize` exempted from version validation
- `actingweb/handlers/mcp.py:1390-1426` — 400 + `-32600` (the dual-era fallback trigger)
- `actingweb/handlers/mcp.py:414-416` — `clientInfo` already read per-request
- `actingweb/handlers/mcp.py:492-562` — `initialize`; client capabilities never parsed
- `actingweb/handlers/mcp.py:1428-1458`, `:2135-2168` — `Mcp-Session-Id` read, never issued
- `actingweb/handlers/mcp.py:21`, `:2114-2133` — `_mcp_client_info_cache`
- `actingweb/handlers/mcp.py:564-594`, `:753-759`, `:1056-1059` — trust/permission wiring
- `actingweb/handlers/mcp.py:2088-2096` — durable client identity on the trust row
- `actingweb/handlers/mcp.py:331-363` — `GET /mcp` static discovery dict
- `actingweb/runtime_context.py:121-146`, `:430-479` — `MCPContext`, client-info fallback
- `actingweb/interface/integrations/fastapi_integration.py:2365-2366`, `:2380` — 405 on other methods; `JSONResponse` only
- `actingweb/handlers/oauth2_endpoints.py:742-798` — RFC 9728 protected-resource document

## External References

- [MCP 2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [Key Changes / changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [Versioning and Compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning) — three-era model, compatibility matrix
- [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) — fallback procedure, required headers
- [Base Protocol / `_meta` and error codes](https://modelcontextprotocol.io/specification/2026-07-28/basic/index) — reserved `-32020`–`-32099`
- [Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr) — `requestState`
- [Server Utilities § Caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching) — `ttlMs`, `cacheScope`
- [Deprecated Features registry](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)
- [Anthropic: bringing MCP 2026-07-28 to Claude](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude) — "soon", no per-surface dates
- [Python SDK v2.0.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0) · [v1→v2 migration](https://py.sdk.modelcontextprotocol.io/migration/)

## Unverified

- **Per-surface Claude rollout dates.** No published statement that 2026-07-28
  is live in Claude.ai, Claude Desktop or Claude Code; the Claude Code
  changelog has zero protocol-version entries. This single fact sets urgency.
- **ChatGPT connectors' current revision** — OpenAI's docs declare none.
- Whether any client we serve will ship **modern-only** rather than dual-era.
- Whether the SDK's extension points could carry ActingWeb's per-peer
  permission filtering (Decision 2 option 3) — not spiked.

## Related

- `todo/mcp-2026-07-28-dual-era-support.md` — trigger criteria for picking this up
- `todo/mcp-cache-lifecycle-and-revocation.md` — §2 cross-process invalidation,
  §4 `_mcp_client_info_cache` keyed by client-supplied header
- `thoughts/plans/2026-05-26-mcp-version-negotiation-structuredcontent.md` — the
  Phase 3 roadmap that `actingweb/mcp/protocol.py:8-13` defers transport
  compliance to
