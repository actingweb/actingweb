# Implementation Plan: MCP Version Negotiation + structuredContent (with 2025-11-25 roadmap)

**Date:** 2026-05-26
**Status:** Phases 1 & 2 implemented (PR #100); Decision Gate decided (keep hand-rolled); roadmap pending
**Branch:** master (uncommitted)

## Update Log

- **2026-05-27 — Dropped the `mcp` SDK dependency entirely (option A), folded into PR #100.**
  Review of SDK usage showed the live path had no functional dependency on `mcp` (only two
  version constants with a fallback, plus the vestigial server). Actions taken: made
  `protocol.py` version constants first-class literals; deleted `sdk_server.py`
  (`ActingWebMCPServer`/`MCPServerManager`/`get_server_manager`) and moved `_match_uri_template`
  → `mcp/uri.py` as `match_uri_template`; wired `serverInfo.name`/`instructions` into the live
  `_handle_initialize` (the #98/#99 bug fix); removed the `mcp` dep + extra + mypy override from
  `pyproject.toml` and re-locked (12 transitive packages removed); repointed test imports to
  `actingweb.mcp.protocol` and rewrote the SDK-coupled regression / server-name tests against
  the live handler. 139 MCP+OAuth2 tests pass with no SDK installed; pyright/ruff clean.
- **2026-05-27 — Decision Gate decided: keep the hand-rolled handler, do not migrate to
  the SDK server.** Driven by the SDK transport being ASGI/async-only (incompatible with
  ActingWeb's Flask + serverless support) and the high blast radius of re-porting the
  auth/cache/trust/permission surface. Full evaluation + a found latent bug (configurable
  `server_name`/`instructions` never reach clients via the live path) recorded in the
  "Decision Gate" section below. Spawned a small follow-up: wire server_name/instructions
  into `_handle_initialize`, drop the unused `self.server_manager`, and resolve the
  vestigial `sdk_server.py`.

- **2026-05-27 — Phase 2 implemented.** Extracted a shared module-level
  `format_call_tool_result(result, negotiated_version)` in `handlers/mcp.py`; both
  `MCPHandler._handle_tool_call` and `AsyncMCPHandler._handle_tool_call_async` now call it,
  removing the Flask/FastAPI divergence. `structuredContent` is gated on
  `supports_structured_content` (>= 2025-06-18) and omitted for older negotiated versions;
  the reserved-key bug is fixed (`_meta`, not `meta`), and a hook-supplied `_meta` is
  preserved. MVP behavior = promote all extras (open question O3 deferred to roadmap item
  3). New `tests/test_mcp_tool_result_format.py` (incl. sync/async parity test). Full
  quality gate green; MCP unit + integration suites pass (53 incl. the regression tests).
  Also fixed a stale venv shebang issue (project had moved paths) so `poetry run
  pytest`/`pyright` work directly again.

- **2026-05-26 — Phase 1 implemented.** Added `actingweb/mcp/protocol.py` (version
  constants + `negotiate_protocol_version` / `is_supported_protocol_version` /
  `supports_structured_content`). `_handle_initialize` now negotiates `protocolVersion`;
  GET discovery and `_resolve_request_protocol_version` (MCP-Protocol-Version header,
  default + 400-on-unsupported) added to `MCPHandler`; `post()` and `post_async()` both
  resolve the version per request. `oauth2_endpoints.py` repointed to the shared module.
  New tests in `tests/test_mcp_version_negotiation.py` (19 pass); existing MCP unit +
  integration tests still pass. **Open question O1 resolved:** reuse the SDK's full
  `SUPPORTED_PROTOCOL_VERSIONS` (through `2025-11-25`) rather than the hand-capped
  `2025-06-18` list — the OAuth discovery endpoint already advertised the full SDK list,
  so capping would have *introduced* a discovery/initialize mismatch. `structuredContent`
  remains independently gated via `supports_structured_content` (>= 2025-06-18) for
  Phase 2.

## Context

ActingWeb serves MCP over a **hand-rolled JSON-RPC handler** (`handlers/mcp.py` for
Flask, `handlers/async_mcp.py` for FastAPI). It does **not** use the official MCP Python
SDK for protocol handling — the SDK-based `ActingWebMCPServer` (`mcp/sdk_server.py`) is
instantiated at `handlers/mcp.py:71` but never read, i.e. vestigial.

Two findings drive this plan (see `thoughts/research/2026-05-26-mcp-tool-result-structuredcontent.md`):

1. **The handler hardcodes `protocolVersion: "2024-11-05"`** in three places and never
   negotiates. Per the MCP lifecycle spec, a server "MUST respond with the same version"
   the client requested when supported — so the current behavior actually violates the
   spec for any client requesting a newer revision.
2. **An uncommitted change** reshapes `tools/call` results to promote extra hook keys into
   `structuredContent`. But `structuredContent` is a **2025-06-18** feature, so the change
   emits a 2025-06-18 field under a 2024-11-05 handshake, and it only patches the sync
   (Flask) path — the async (FastAPI) path diverges.

The mcp Python SDK is **not** the blocker: `mcp = "^1.23"` already resolves to 1.26.0,
whose `LATEST_PROTOCOL_VERSION = "2025-11-25"` and
`SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05","2025-03-26","2025-06-18","2025-11-25"]`.
Because the handler is hand-rolled, that SDK support does not flow through automatically.

## Decisions taken (2026-05-26)

- **Handler strategy:** keep the hand-rolled handler for near-term work; carry an explicit
  **SDK-migration decision gate** before the transport/OAuth phase (user choice
  "Keep hand-rolled, decide SDK later").
- **structuredContent extras strategy:** **MVP = promote all extras** (the current
  uncommitted change's behavior): build `{content, isError}`, pass through an explicit
  `structuredContent` if the hook set one, else sweep all non-reserved top-level keys into
  `structuredContent`. Backward-compatible with existing `content`+extras hooks (the
  "emm" Personal AI Memory app) without requiring `output_schema` declarations.
  `output_schema`-gated validation is an optional later refinement, not MVP.

## Problem Summary

1. No version negotiation — `protocolVersion` hardcoded to `2024-11-05`
   (`handlers/mcp.py:116,126,304`; `handlers/oauth2_endpoints.py:34-35`).
2. `tools/call` result formatting is duplicated and divergent across the sync and async
   handlers (`handlers/mcp.py:742-780` vs `handlers/async_mcp.py:172-179`), and the
   `structuredContent` reshaping exists only in the sync path.
3. The reserved-key list in the uncommitted change excludes `"meta"`, but the spec wire
   field is `_meta` (the SDK maps `_meta` ↔ `.meta`).
4. The handler does not read the `MCP-Protocol-Version` HTTP header that clients send on
   post-initialize requests, so it cannot make per-request version-aware decisions.

---

## Phase 1 — Version negotiation (the enabler)

Goal: echo the client's requested `protocolVersion` when we support it; otherwise return
our highest supported version. Establish a single source of truth for supported versions.

### 1.1 Define supported-version constants

**File:** new small module or top of `handlers/mcp.py` (and reuse in
`handlers/oauth2_endpoints.py`).

```python
# Versions whose tools/resources/prompts semantics this hand-rolled handler implements.
# Capped at 2025-06-18 in Phase 1: that revision delivers structuredContent/outputSchema,
# which is the near-term target. 2025-11-25 is added only after the transport + OAuth
# follow-ups (Phase 3+), since claiming it implies those features.
MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18"]
MCP_LATEST_SUPPORTED = "2025-06-18"
MCP_DEFAULT_NEGOTIATED = "2025-03-26"  # per spec, assumed when no header present
```

Rationale for the 2025-06-18 cap: negotiating a version implies the server honors that
revision's mandatory behavior (notably the Streamable HTTP transport for 2025-03-26+).
We surface that tension as an explicit risk below rather than over-claiming. **Open
question O1** covers whether to cap at 2025-06-18 or be more conservative.

### 1.2 Negotiate in `_handle_initialize`

**File:** `handlers/mcp.py:254-308` (and mirror in `async_mcp.py` if it overrides; it does
not currently — it calls the sync `_handle_initialize`, so one change covers both).

- Read `requested = params.get("protocolVersion")`.
- If `requested in MCP_SUPPORTED_PROTOCOL_VERSIONS`: echo `requested`.
- Else: return `MCP_LATEST_SUPPORTED`.
- Replace the hardcoded `"2024-11-05"` at line 304 with the negotiated value.

### 1.3 Update discovery + OAuth metadata

- `handlers/mcp.py:116,126` (GET discovery) — report `MCP_SUPPORTED_PROTOCOL_VERSIONS`.
- `handlers/oauth2_endpoints.py:34-35,776` — align `LATEST_PROTOCOL_VERSION` /
  `SUPPORTED_PROTOCOL_VERSIONS` with the new constants.

### 1.4 Accept the `MCP-Protocol-Version` header

- In `post()`/`post_async()`, read `MCP-Protocol-Version` (case-insensitive). If absent,
  assume `MCP_DEFAULT_NEGOTIATED`. If present and unsupported, return HTTP 400 per spec.
- Stash the resolved version where the tool-call formatter can read it (e.g. an instance
  attribute set at the start of request handling). This feeds Phase 2's gating.

### 1.5 Tests

- Initialize with `protocolVersion` of each supported value → response echoes it.
- Initialize with an unsupported/newer value (e.g. `2025-11-25`) → response returns
  `MCP_LATEST_SUPPORTED`; assert old `2024-11-05`-only clients still get `2024-11-05`.
- `MCP-Protocol-Version` header: absent → default; unsupported → 400.

---

## Phase 2 — structuredContent consistency (depends on Phase 1)

Goal: one shared, spec-aligned `tools/call` result formatter used by **both** handlers,
version-aware so it only emits `structuredContent` when the negotiated version supports it.

### 2.1 Shared formatter

**New:** module-level helper (e.g. in `handlers/mcp.py`, imported by `async_mcp.py`):

```python
def format_call_tool_result(result, negotiated_version: str) -> dict:
    """Normalize a hook return into a CallToolResult-shaped dict."""
```

Behavior:
- If `result` is a dict with `"content"`:
  - `out = {"content": result["content"], "isError": bool(result.get("isError", False))}`.
  - If negotiated version >= `2025-06-18`:
    - If `result.get("structuredContent")` is a dict → pass it through.
    - Else promote all keys except the reserved set `{"content","isError","_meta","structuredContent"}`
      into `structuredContent` (MVP = promote all extras). **Fix:** reserve `_meta`, not
      `meta`; pass a hook-supplied `_meta` through to the result's `_meta`.
  - If negotiated version < `2025-06-18`: omit `structuredContent`; extras stay where the
    spec tolerates them (top-level) OR are dropped — **Open question O2**. Content is
    already populated, satisfying the required field for old clients.
- Else (no `content`): legacy wrap — `{"content": [{"type":"text","text": str(result)}]}`
  (unchanged from today's else-branch at `mcp.py:781-794` / `async_mcp.py:180-193`).

### 2.2 Wire both handlers to the helper

- `handlers/mcp.py:742-780` → call `format_call_tool_result(result, self._negotiated_version)`.
- `handlers/async_mcp.py:172-193` → same, removing the divergent inline copy.
- Replace the uncommitted change's inline block so there is a single implementation.

### 2.3 Tests

- **Parity test:** same hook return through sync and async handlers produces identical
  `result`. (None exists today — this is the guard against re-divergence.)
- `content`+extras hook, negotiated 2025-06-18 → extras under `structuredContent`,
  `isError` present, `content` preserved.
- Same hook, negotiated 2024-11-05 → no `structuredContent` (per O2 resolution).
- Hook supplying explicit `structuredContent` → passed through unchanged.
- Hook supplying `_meta` → preserved as `_meta`, not swept into `structuredContent`.
- Plain-dict / bare-string hook (no `content`) → unchanged legacy text wrap.

---

## Decision Gate — SDK migration vs. continue hand-rolling

**Evaluated 2026-05-27. Decision: KEEP the hand-rolled handler; do NOT migrate the live
`/mcp` path to the SDK's `ActingWebMCPServer`. Adopt SDK *types/helpers* only (already
done). Resolve the vestigial SDK server and a latent bug it masked.**

### Decisive factor — the SDK transport is ASGI/async-only; ActingWeb is not

The official SDK's Streamable HTTP transport (`StreamableHTTPSessionManager`,
`FastMCP.streamable_http_app()`) is **ASGI/async-only**, requires a persistent task-group
entered in the host app's lifespan, and in stateful mode keeps an **in-memory session
dict** keyed by `Mcp-Session-Id`. There is no official synchronous/WSGI path.

ActingWeb, by contrast:
- Supports **both Flask (WSGI/sync) and FastAPI** — the hand-rolled handler is a single
  "parsed-JSON-RPC dict in → dict out" cycle that works identically on both.
- Explicitly targets **Lambda/serverless** (`with_sync_callbacks()`,
  `docs/quickstart/deployment.rst`); the SDK's in-memory sessions don't survive a freeze,
  and stateless mode still needs the `run()` task group at cold start (plus open
  reliability issues, SDK #1658) and has documented mounting friction (SDK #1367, #673,
  #1220).

A wholesale migration would therefore either **drop Flask support** (ASGI-only) or require
a fragile, unsupported WSGI↔ASGI bridge — a regression in ActingWeb's framework-agnostic
value proposition. This alone is disqualifying for now.

### Effort / blast radius — high, on the production-critical auth path

Migration means relocating the entire token→actor→trust→runtime-context chain
(`mcp.py:1153-1450`, plus the three caches, actor-bridging-on-auth, `_mark_client_peer_
approved`, and logout cache invalidation at `oauth2_endpoints.py:839`) into ASGI auth
middleware (the SDK's `TokenVerifier` + `get_access_token()` + per-request `ContextVar`
model), then injecting per-actor context into a shared `Server`. The SDK's auth/ContextVar
design is genuinely clean and *would* map onto ActingWeb's per-actor OAuth2 model — but the
payoff only materializes if we also go ASGI-only, and the change touches auth, caching, and
permissions simultaneously on the most security-sensitive path.

### Feature parity — the SDK server today implements almost none of it

`ActingWebMCPServer` (`mcp/sdk_server.py`) is missing, vs. the hand-rolled handler: auth
caching, token validation, actor-bridging-on-auth, trust lookup / peer_id derivation,
client-type detection, `client_descriptions`, `allowed_clients`, ChatGPT-specific
formatting, client-info capture into trust, and `structuredContent`/`isError` preservation
(it `json.dumps`es the whole result and drops `isError`). It also reads
`actor._mcp_trust_context`, which the **live auth path never sets** (it sets
`_actingweb_runtime_context["mcp"]` via `RuntimeContext`), so even if invoked it would see
`peer_id=None` and mis-filter permissions. Porting all of this is a large project for
little gain.

### Incremental benefit — low

The headline SDK wins are native `structuredContent`/`outputSchema` (we already implemented
`structuredContent` in Phase 2) and Streamable HTTP streaming (no current client requires
it — plain POST/JSON is the valid minimal Streamable HTTP mode and is what every target
client uses). Spec-tracking-via-SDK-upgrade is a real maintenance convenience but does not
outweigh the transport/risk costs.

### Concrete finding — the vestigial server masked a latent bug

`self.server_manager` is constructed in `MCPHandler.__init__` (`mcp.py:129-132`) with the
configured `mcp_server_name` / `mcp_instructions` but **never read**. The live
`_handle_initialize` hardcodes `serverInfo={"name": "ActingWeb MCP Server",
"version": "1.0.0"}` (`mcp.py:386`) and never emits `instructions`. So the configurable
server name (#98) and instructions (#99) **never reach MCP clients** through the live path —
they flow only into the unused SDK server. The vestigial code created a false impression
that these features were wired.

### Actions (small, separate follow-up PR — not Phase 3)

1. **Wire the config through the live path**: in `_handle_initialize`, set
   `serverInfo.name` from `config.mcp_server_name` and add `instructions` (from
   `config.mcp_instructions`) to the `InitializeResult`. Add a test asserting both appear.
   *(This is a real bug fix for #98/#99.)*
2. **Remove the dead `self.server_manager`** field from `MCPHandler.__init__`.
3. **Resolve `mcp/sdk_server.py`**: keep `_match_uri_template` (reused by both handlers) by
   moving it somewhere neutral (e.g. `mcp/protocol.py` or a small `mcp/uri.py`), then either
   delete `ActingWebMCPServer`/`MCPServerManager` or clearly mark them experimental/unused
   in a docstring. Update `get_server_manager` callers accordingly.

### Re-evaluation triggers (revisit migration if any become true)

- ActingWeb drops Flask/WSGI and commits to ASGI-only.
- A use case needs real streaming/SSE or server→client messages (sampling, elicitation).
- Hand-maintaining protocol revisions becomes a measurable burden.

### Phase 3 implication

Streamable HTTP (JSON mode) + modern OAuth (RFC 9728 / OIDC) can be added **incrementally on
the hand-rolled handler** — the handler already implements the simple Streamable-HTTP
single-POST-returns-JSON shape. Only full SSE streaming is genuinely hard to hand-roll;
defer it until a concrete need appears. Phase 3 proceeds without an SDK migration.

---

## Phase 3+ — 2025-11-25 roadmap (folded in, not scheduled)

Each is its own project; sequencing depends on the Decision Gate. Raising the negotiated
ceiling to `2025-11-25` should happen only after the mandatory pieces below are in place.

1. **Streamable HTTP transport** — the modern transport for 2025-03-26+. Today we serve
   plain JSON-RPC POST (effectively the deprecated 2024-11-05 transport). Required to
   honestly claim 2025-03-26+. Largest single item. Strong driver for the SDK option.
2. **Modern OAuth / authorization** — RFC 9728 protected-resource metadata, OIDC Discovery
   1.0, OAuth Client ID Metadata Documents, incremental scope consent via
   `WWW-Authenticate`, and `403` on invalid `Origin`. Intersects existing
   `handlers/oauth2_endpoints.py` and the OAuth2 server.
3. **outputSchema → structuredContent validation** — promote Phase 2's MVP to validate
   extras against a declared `output_schema` (decorator already accepts it at
   `decorators.py:21`; no call path uses it today). Resolves Open question O2/O3.
4. **Elicitation** (incl. 2025-11-25 URL-mode) — new client interaction capability.
5. **Tasks** (experimental in 2025-11-25) — durable/async requests with polling; relates
   to the existing async hook work. Defer until the spec finalizes it.
6. **Smaller 2025-11-25 niceties** — icons metadata for tools/resources/prompts; optional
   `description` on `Implementation` (serverInfo); JSON Schema 2020-12 default dialect;
   input-validation errors as `isError: true` rather than protocol errors.

When ready: add `"2025-11-25"` (and `"2025-03-26"` transport) to
`MCP_SUPPORTED_PROTOCOL_VERSIONS` and raise `MCP_LATEST_SUPPORTED`.

---

## Dependency note

No change strictly required (`^1.23` already permits the 2025-11-25-capable 1.26.0).
Recommend refreshing the lock to the latest 1.x (**1.27.1**, still within `^1.23`) for
fixes. A v2 SDK is in development with no firm date; if/when adopted, pin `>=1.25,<2`
until v2 is evaluated.

## Open Questions

- **O1 — Negotiation ceiling in Phase 1:** cap at `2025-06-18` (enables structuredContent,
  accepts that our POST transport is technically pre-2025-03-26) or be conservative and
  cap at `2024-11-05` until Streamable HTTP lands (then structuredContent is emitted only
  to clients that opt past negotiation)? Plan assumes the `2025-06-18` cap.
- **O2 — Old-version extras:** when negotiated < 2025-06-18, drop extra hook keys, or leave
  them top-level (spec-tolerated)? Plan leans "omit structuredContent, content carries the
  payload"; dropping vs. keeping top-level extras needs a call.
- **O3 — When to gate on output_schema:** keep MVP "promote all extras" indefinitely, or
  switch to schema-gated validation in Phase 3 (Roadmap item 3)?

## Code References

- `actingweb/handlers/mcp.py:116,126,304` — hardcoded `2024-11-05`
- `actingweb/handlers/mcp.py:254-308` — `_handle_initialize` (negotiation target)
- `actingweb/handlers/mcp.py:742-780` — sync tool-call formatting (uncommitted change)
- `actingweb/handlers/async_mcp.py:172-193` — async tool-call formatting (divergent)
- `actingweb/handlers/oauth2_endpoints.py:34-35,776` — protocol version constants
- `actingweb/mcp/decorators.py:21,243-246` — `output_schema` support (unused at call time)
- `actingweb/mcp/sdk_server.py:71(in mcp.py),639-735` — vestigial SDK server / manager
- `pyproject.toml:40` — `mcp = "^1.23"`; lockfile resolved 1.26.0

## External References

- https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle — version negotiation rules
- https://modelcontextprotocol.io/specification/2025-11-25/changelog — 2025-11-25 changes
- https://modelcontextprotocol.io/specification/2025-06-18/server/tools — structuredContent/outputSchema
- https://github.com/modelcontextprotocol/python-sdk — `LATEST_PROTOCOL_VERSION`, `SUPPORTED_PROTOCOL_VERSIONS`
- Companion research: `thoughts/research/2026-05-26-mcp-tool-result-structuredcontent.md`
