# TODO: Dual-era MCP support (2026-07-28 stateless revision)

**Status:** Open, deliberately unscheduled. Nothing is broken today and there
is no client we serve that is confirmed to need this.
**Severity:** None today; **high the day a client we serve ships modern-only**,
because a modern-only client cannot talk to a legacy-only server at all — the
spec's expected outcome is "Fails … the client then surfaces an actionable
error to the user."
**Origin:** `thoughts/research/2026-08-13-mcp-2026-07-28-stateless-revision.md`

## Why this is deferred rather than done

The MCP revision published 2026-07-28 removes `initialize`, protocol-level
sessions, `ping`, and server-initiated elicitation, and adds a mandatory
per-request `_meta` block, `server/discover`, caching hints and new required
headers. The library speaks up to `2025-11-25` and is therefore a **legacy-era
server**.

That sounds urgent and isn't, because the spec has **three** client eras:

| Client era | Against our legacy server |
| --- | --- |
| Legacy (`2025-11-25` and earlier) | Unaffected, indefinitely |
| Dual-era | **Works** — falls back to `initialize` after one rejected request |
| Modern-only | **Fails**, by design |

The fallback works because `_resolve_request_protocol_version`
(`actingweb/handlers/mcp.py:1390-1426`) answers an unknown version with HTTP
400 + JSON-RPC `-32600`, a *standard* code outside the MCP-reserved
`-32020`–`-32099` range. The spec: *"Anything else identifies a legacy
server."*

So the entire question is: **does any client we serve go modern-only, and
when?** That is unknown and unverifiable from public sources as of 2026-08-13.

## Pick this up when any one of these is true

1. **A client we serve announces or ships modern-only 2026-07-28 support.**
   The specific thing to watch for is *modern-only*, not "supports
   2026-07-28" — a dual-era client needs nothing from us. Anthropic's
   announcement (July 2026) said support was "rolling out across Claude
   products soon" with no per-surface dates.
2. **Unsupported-version rejections start appearing in production logs.** The
   signal is `POST /mcp` → HTTP 400 + `-32600` where the request carried
   `MCP-Protocol-Version: 2026-07-28` (or later). One per client origin is
   normal and healthy — that *is* the fallback handshake. A *sustained* stream
   from the same origin means a client is retrying rather than falling back,
   i.e. it is modern-only or mis-implements the fallback. **Logged at WARNING
   since 2026-08-15** — before that it was not logged at all, so this criterion
   could only have fired via a user report. See "Cheap hardening" below.
3. **A user reports an MCP client that can no longer connect** and the trace
   shows no `initialize` ever arriving.
4. **We want a feature that only exists in the modern revision** — most
   plausibly elicitation via MRTR, which the library does not implement in any
   form today (`elicit` appears nowhere in the codebase).
5. **The Python SDK question is being reopened for another reason.** The
   modern revision is the largest single argument for adopting the official SDK
   since the library chose to hand-roll; if that decision is revisited, decide
   both together rather than twice.

## Do NOT pick it up merely because

- The spec is published. It has been since 2026-07-28 and changed nothing for us.
- An MCP client advertises 2026-07-28 support. Dual-era clients fall back.
- A compliance checklist says we are on an old revision. `2025-11-25` remains a
  valid revision for legacy-era clients, which is every client confirmed to
  reach us today.

## Trap: do not "fix" the `-32600` error

The single most important thing to preserve. Returning a spec-shaped `-32022`
(`UnsupportedProtocolVersion`) with a `data.supported` array **looks** more
correct and would **break** dual-era clients: `-32022` identifies a *modern*
server, so the client would stop falling back and instead retry a
modern-shaped request declaring `2025-11-25` — incoherent, since that version
requires `initialize`. A working fallback becomes a retry loop.

`-32600` without `data.supported` is the correct legacy-only signal. It was
written as ordinary spec compliance, not as a deliberate era signal, and **no
test asserted it in that role** until 2026-08-15 —
`tests/test_mcp_version_negotiation.py` asserted the 400 and the code, but not
the absence of `data`, which is the half a `-32022` "fix" would change.
`tests/test_mcp_dual_era_signal.py` now guards it, and the rejection site
carries the reasoning inline so it is visible to whoever edits it.

## Cheap hardening — DONE 2026-08-15

Each is independent of the dual-era decision. **Decided 2026-08-14** (owner
walkthrough): **do all three.** Item 1 is the one that matters — it is what
stops a well-meaning `-32022` "fix" from breaking every dual-era client — and
item 3 is what makes criterion 2 above observable in telemetry rather than via
user reports. Item 2 stays in the `message` string; `data.supported` is the trap.

**All three landed 2026-08-15.** The rest of this file is unchanged and still
open: the hardening protects the current behaviour, it does not implement any
part of the modern revision. Criterion 2 above is now the *observable* trigger
it was written to be, which it was not before.

1. ~~**Regression test**~~ **Done** — `tests/test_mcp_dual_era_signal.py`. It
   asserts the *absence* of `data`, not just the presence of `-32600`, plus
   that the code falls outside the whole reserved `-32020`–`-32099` range
   rather than differing from one tempting constant. Verified non-vacuous by
   making the exact change the trap describes (`-32022` +
   `data.supported`): 4 assertions fail. The module docstring carries the
   reasoning, because a guard nobody understands gets deleted.
2. ~~**Name supported versions in the error `message` string**~~ **Done** —
   `unsupported_version_message()` in `actingweb/mcp/protocol.py`, next to
   `SUPPORTED_PROTOCOL_VERSIONS` so the two cannot drift. The docstring says
   why the versions must not migrate to `data`.
3. ~~**Raise the log level**~~ **Done**, though the premise was slightly off:
   the rejection did not log at debug, it **did not log at all**. It now logs
   at WARNING, naming the supported versions and stating in the message itself
   that one rejection is healthy and a sustained stream is the trigger — the
   operator reading the line is the person who needs criterion 2, and they
   should not have to find this file to apply it.

## Scope when it is picked up

Branch on **presence of modern `_meta`, never on method name** — `ping` is the
documented era-ambiguous trap (no parameters, so nothing distinguishes eras),
and `notifications/initialized` has the identical shape. Those are the
library's only two unauthenticated methods
(`actingweb/handlers/mcp.py:392-395`); both are removed in 2026-07-28.

| Item | Notes |
| --- | --- |
| Modern `_meta` parsing + era branch | `protocolVersion` and `clientCapabilities` are required; `clientInfo` is optional |
| `server/discover` | MUST implement |
| Capability enforcement → `-32021` | Capabilities are never parsed today (`actingweb/handlers/mcp.py:492-562`) |
| `MCP-Protocol-Version` header mirroring → `-32020` | Header MUST match the `_meta` field |
| `404` + `-32601` for unknown modern methods | Legacy path must **not** adopt this — it is a modern-server tell |
| `ttlMs` + `cacheScope` on list/read results | `tools/list` is permission-filtered per peer → **MUST be `"private"`** |
| MRTR + signed `requestState` | Only if elicitation is wanted; requires HMAC/AEAD, principal binding, TTL |
| `subscriptions/listen` | Needs SSE — unavailable on the primary consumer's API Gateway HTTP API v2 deployment |

Dead-code cleanup that becomes available at the same time: `Mcp-Session-Id`
handling (`:1428-1458`, `:2135-2168`) and `_mcp_client_info_cache` (`:21`,
`:2114-2133`) lose their write path entirely under modern traffic, and
`_handle_notifications_initialized` (`:1361-1370`) loses its caller. Durable
client identity survives on the trust row (`:2088-2096`).

## Downstream consumers to notify

`actingweb_mcp` has an app-side middleware, `require_mcp_auth_for_init`, that
forces Claude into the OAuth flow by intercepting unauthenticated `initialize`
requests and matching `clientInfo.name` against "claude"/"anthropic". Under the
modern revision **both** of its inputs disappear — there is no `initialize`
method, and `clientInfo` becomes optional per-request metadata — so it would
silently become a no-op. It is self-labelled TEMPORARY and exists because the
library's standard 401 challenge was apparently not sufficient on its own.
Any dual-era work must establish whether the library's
`WWW-Authenticate` path (`actingweb/handlers/mcp.py:400-412`) can carry OAuth
bootstrap alone, since consumers cannot keep sniffing for a method that no
longer exists.

## Related

- `thoughts/research/2026-08-13-mcp-2026-07-28-stateless-revision.md` — the
  full analysis, spec quotes, and the traced fallback path
- `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` — §2 cross-process
  invalidation, §4 `_mcp_client_info_cache` keyed by a client-supplied header;
  both overlap the cleanup above
- `thoughts/plans/2026-05-26-mcp-version-negotiation-structuredcontent.md` — the
  Phase 3 roadmap that `actingweb/mcp/protocol.py:8-13` defers transport
  compliance to
