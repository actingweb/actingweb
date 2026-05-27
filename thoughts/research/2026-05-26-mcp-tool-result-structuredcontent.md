# Research: MCP `tools/call` result formatting — `structuredContent` promotion in `mcp.py`

**Date:** 2026-05-26
**Status:** Complete
**Branch:** master
**Commit:** 11f957a

## Research Question

An uncommitted change in `actingweb/handlers/mcp.py` rewrites how `_handle_tool_call`
formats a hook's return value for the JSON-RPC `tools/call` response. Instead of
returning a hook's `{"content": [...], ...}` dict verbatim, it builds a normalized
`CallToolResult` shape (`content` + `isError`) and promotes any extra top-level keys
into a `structuredContent` object.

Is this the best approach? Is it consistent and not a hack? Are there better ways?

## Summary

The change is **spec-motivated and directionally correct**, but as written it is
**incomplete and introduces an inconsistency**, so in its current form it leans toward
"hack" — not because the idea is wrong, but because it only patches one of three
parallel code paths and rests on a protocol-version mismatch.

Key facts established by the research:

1. **There are three MCP tool-call code paths, and the change touches only one.**
   - `MCPHandler._handle_tool_call` (sync, **Flask**) — `handlers/mcp.py:749-780` — **CHANGED**.
   - `AsyncMCPHandler._handle_tool_call_async` (async, **FastAPI**) — `handlers/async_mcp.py:172-179` — **UNCHANGED** (still returns the raw dict).
   - `ActingWebMCPServer.handle_call_tool` (SDK server) — `mcp/sdk_server.py:307-318` — **UNCHANGED** and, per the routing investigation, **vestigial** (instantiated but never used to serve HTTP).
   So after this change, Flask and FastAPI deployments format the *same hook return*
   differently. That divergence is the strongest "this is a hack" signal.

2. **The hook shape the change targets is real**, used by external consumer apps (e.g. the
   Personal AI Memory / "emm" app): `{"content": [...], "isError": bool, "success": ..., "memory_type": ...}`.
   This is documented in the regression test at `tests/integration/test_mcp_tools.py:525-530`.
   In-repo examples never produce `content` + extra keys, so the change is invisible to
   the repo's own examples/tests.

3. **The MCP spec supports both the old and new behavior.** Extra top-level keys are
   structurally legal (the spec `Result` type has an open index signature; the official
   Python SDK uses Pydantic `extra="allow"` and preserves unknown keys). So the old code
   ("return the dict verbatim") was *not* broken for spec-compliant clients — extras were
   tolerated. `structuredContent` is the more *idiomatic* home for typed payloads, but it
   was introduced in protocol version **2025-06-18**.

4. **The live handler announces `protocolVersion: "2024-11-05"`** (`handlers/mcp.py:304`),
   which predates `structuredContent` (added 2025-06-18). So the change emits a
   2025-06-18 field under a 2024-11-05 handshake. Not harmful (extras are tolerated), but
   semantically inconsistent — the same inconsistency, in reverse, that the old code had.

5. **No existing test breaks.** No test registers a hook returning `content` + extras and
   asserts on top-level placement, and no test asserts `structuredContent`. There is also
   **no test that would catch the Flask/FastAPI divergence** the change introduces.

## Detailed Findings

### The proposed change (handlers/mcp.py:742-780)

Old behavior: if a hook returns a dict containing `"content"`, the whole dict is returned
verbatim as the JSON-RPC `result`.

New behavior:
- Build `mcp_result = {"content": result["content"], "isError": bool(result.get("isError", False))}`.
- If the hook supplied `structuredContent` (dict), pass it through.
- Otherwise collect all keys except `content`/`isError`/`meta`/`structuredContent` and, if
  any, place them under `mcp_result["structuredContent"]`.

Observations on the code itself:
- It excludes a key named `"meta"`, but the MCP wire field is `_meta` (the Python SDK maps
  `_meta` ↔ `.meta`). A hook returning `_meta` would have it swept into `structuredContent`;
  a hook returning `meta` would be dropped from output entirely. Minor, but it shows the
  reserved-key list is guessed rather than derived from the spec.
- It always emits `isError` (defaulting to `False`). That is spec-valid and is consistent
  with the intent of the Oct-2025 regression work (`tests/integration/test_mcp_tools.py:495-560`).
- It does **not** add the backward-compat serialized-JSON TextContent block that the spec
  recommends (SHOULD) when returning structured content — though here `content` already
  comes from the hook, so `content` is non-empty regardless.

### Three divergent tool-call paths

| Path | File:line | Handles `content`+extras how | Touched? |
|------|-----------|------------------------------|----------|
| Sync (Flask) | `handlers/mcp.py:749-780` | Normalizes; promotes extras to `structuredContent` | **Yes** |
| Async (FastAPI) | `handlers/async_mcp.py:172-179` | Returns raw dict verbatim (extras stay top-level) | No |
| SDK server | `mcp/sdk_server.py:307-318` | `json.dumps(result)` into one TextContent; drops `isError` | No |

Routing investigation conclusion: Flask wires `MCPHandler` (`flask_integration.py:220, 1310`),
FastAPI wires `AsyncMCPHandler` (`fastapi_integration.py:864-869, 2278`). The SDK server is
instantiated in `MCPHandler.__init__` (`handlers/mcp.py:71`) but `self.server_manager` is
never read anywhere in the handler — it is effectively dead for request handling.

Consequence: a hook returning `{"content":[...], "isError":False, "success":True, "memory_type":"x"}`
yields, after the change:
- Flask: `result = {"content":[...], "isError":False, "structuredContent":{"success":True,"memory_type":"x"}}`
- FastAPI: `result = {"content":[...], "isError":False, "success":True, "memory_type":"x"}` (unchanged)

### How hooks actually return results

- The dominant documented pattern is a **plain dict with no `content` key** (e.g.
  `{"status":"deleted"}`, `{"results":[...]}`) or a bare string — `decorators.py:62-77`,
  `docs/guides/mcp-quickstart.rst:65`, `docs/guides/hooks.rst:83-110`,
  `docs/reference/hooks-reference.rst:362-381`. These hit the **legacy/else branch**
  (`mcp.py:781-794`), which the change does **not** touch.
- The only documented `content`-key return is `docs/guides/mcp-quickstart.rst:94`:
  `{"content":[{"type":"text","text":...}]}` — with **no** extra keys, so the change is a
  no-op for it.
- The `content` + extras shape is **not** present in any in-repo example/doc; it originates
  in external consumer apps and is only referenced via the regression test comments
  (`tests/integration/test_mcp_tools.py:518-530`, referencing an external
  `hooks/mcp/protocol/mcp_response.py`).
- `structuredContent` appears in **zero** docs and nowhere in the codebase except the
  proposed code. No documentation tells hook authors how extra keys map to the wire result.

### MCP spec findings (authoritative)

- `CallToolResult`: `content` (REQUIRED array), `isError` (optional bool), `structuredContent`
  (optional object), `_meta` (optional). Base `Result` has `[key:string]: unknown` — extra
  top-level keys are **structurally legal**.
- `structuredContent` + `outputSchema` were introduced in **2025-06-18**; absent from
  2024-11-05 and 2025-03-26.
- If a tool declares `outputSchema`, the server **MUST** return conforming `structuredContent`.
  ActingWeb's `mcp_tool` decorator supports `output_schema` (`decorators.py:21,243-246`), and
  the SDK-server lister forwards it as `outputSchema` (`sdk_server.py:243-246`) — but **no
  tool-call path validates or guarantees** structuredContent against it. The proposed change
  doesn't wire outputSchema → structuredContent either; it promotes *whatever* extras exist.
- The official Python SDK (`extra="allow"`) **preserves** unknown top-level keys; it does not
  reject them. So the comment in the change ("most clients ignore those because they're not in
  the spec") is partly true (some clients ignore them) but the stronger claim that they're
  effectively lost is not generally accurate — they're preserved, just not surfaced to the LLM
  in a standard place.
- Backward-compat SHOULD: a tool returning structured content should also serialize the JSON
  into a TextContent block. Here `content` comes from the hook so this is generally satisfied.

Sources: modelcontextprotocol.io specification for 2024-11-05 and 2025-06-18; official
schema.ts/schema.json; python-sdk `types.py` (`Result`/`CallToolResult`, `ConfigDict(extra="allow")`).

### Test coverage

- No handler test registers a hook returning `content` + extras and asserts shape, so **no
  test breaks** (`tests/test_mcp_permissions.py:95-141`, `tests/test_async_mcp_handler.py`,
  `tests/integration/test_mcp_tools.py:48-84`).
- The regression tests (`tests/integration/test_mcp_tools.py:487-639`) **reimplement** SDK
  logic inline and construct `CallToolResult` themselves; they never call the live handler,
  so they neither protect nor constrain the changed code. They also reference
  `sdk_server.py:271-278` for an `isError`-preserving `CallToolResult`, but the current
  `sdk_server.py:307-318` does **not** preserve `isError` — the test has drifted from the code.
- There is **no test** asserting the Flask vs FastAPI result shapes match.

## Decisions Needed

### Decision 1: Should the change be applied to all live paths, or none?

**Options:**
1. **Apply identical normalization to both `mcp.py` and `async_mcp.py`** (and ideally factor
   the logic into one shared helper, e.g. `_format_call_tool_result(result) -> dict`). —
   Removes the Flask/FastAPI divergence; single source of truth. Cons: a little refactoring;
   need a test asserting both paths agree.
2. **Apply to `mcp.py` only (current change).** — Smallest diff. Cons: silent Flask/FastAPI
   divergence for the exact hook shape the change targets; this is the core "hack" risk.
3. **Don't change either; keep returning the dict verbatim.** — Extras are spec-tolerated and
   preserved by the SDK; nothing is actually broken for compliant clients. Cons: extras aren't
   in the idiomatic `structuredContent` slot, so LLM-facing clients may not surface them.

**Recommendation:** Option 1. The change's own premise (typed payload belongs in
`structuredContent`) only holds if it's applied consistently to the paths that actually serve
traffic. A shared helper plus one parity test resolves the hack concern.

### Decision 2: How should the reserved-key set and `_meta` be handled?

**Options:**
1. **Pass `_meta` through unchanged and exclude it from promotion** (fix the `meta` vs `_meta`
   mismatch), promote everything else. — Spec-correct; preserves caller `_meta`.
2. **Keep current `"meta"` exclusion.** — Drops a hook's `meta` key and sweeps `_meta` into
   structuredContent. Likely unintended.

**Recommendation:** Option 1 — match the spec wire field `_meta`.

### Decision 3: Promote *all* extras, or only when a tool declares `output_schema`?

**Options:**
1. **Promote all extras (current).** — Works without hook authors declaring schemas. Cons:
   blindly reshapes arbitrary app data into `structuredContent` without a declared contract;
   no validation; a hook that intentionally put app-private keys at top level loses that.
2. **Only populate `structuredContent` from extras when the tool declares `output_schema`;
   otherwise leave the dict verbatim (or drop extras).** — Aligns with the spec's
   outputSchema↔structuredContent contract and the decorator's existing `output_schema`
   support. Cons: requires hook authors to declare schemas to get the new behavior;
   larger change.
3. **Require hooks to set `structuredContent` explicitly; never auto-promote.** — Most
   predictable, no guessing. Cons: breaks the convenience for existing `content`+extras hooks
   that don't yet set it.

**Recommendation:** Evidence is split. Option 1 is the most backward-compatible for the
existing external hook shape; Option 2 is the most spec-idiomatic. If the goal is "make the
emm-style hooks render correctly in ChatGPT/Claude today," Option 1 is pragmatic; if the goal
is a clean long-term contract, Option 2. This is a genuine product decision, not a clear win.

### Decision 4: Protocol version vs `structuredContent`

**Options:**
1. **Negotiate/announce 2025-06-18** (echo the client's requested version when supported)
   before emitting `structuredContent`. — Makes the emitted field consistent with the
   handshake; also unlocks `outputSchema` semantics. Cons: broader change to
   `_handle_initialize` (`mcp.py:300-308`), needs client-compat testing.
2. **Leave `protocolVersion: "2024-11-05"` and emit `structuredContent` anyway (current).** —
   No handshake change; extras/structuredContent tolerated by clients. Cons: semantically
   emits a 2025-06-18 field under a 2024-11-05 contract.

**Recommendation:** Independent of Decisions 1-3. If `structuredContent` is going to be a
first-class part of the response contract, version negotiation should be revisited so the
handshake matches the payload.

## Code References

- `actingweb/handlers/mcp.py:742-780` — the proposed change (sync, Flask path)
- `actingweb/handlers/mcp.py:304` — `protocolVersion: "2024-11-05"` announced in initialize
- `actingweb/handlers/mcp.py:71` — `self.server_manager` set but never read (vestigial)
- `actingweb/handlers/async_mcp.py:172-179` — async path, unchanged verbatim return (FastAPI)
- `actingweb/mcp/sdk_server.py:307-318` — SDK server path, `json.dumps`→TextContent, drops `isError`
- `actingweb/mcp/decorators.py:21,243-246` — `output_schema` support exists but is unused at call time
- `actingweb/interface/integrations/flask_integration.py:220,1310` — Flask wires `MCPHandler`
- `actingweb/interface/integrations/fastapi_integration.py:864-869,2278` — FastAPI wires `AsyncMCPHandler`
- `tests/integration/test_mcp_tools.py:487-639` — regression tests (inline reimpl, not live path)
- `tests/integration/test_mcp_tools.py:525-530` — documents the `content`+extras hook shape
- `tests/test_async_mcp_handler.py`, `tests/test_mcp_permissions.py:95-141` — tool-call tests (no shape asserts)

## External References

- https://modelcontextprotocol.io/specification/2025-06-18/server/tools — `structuredContent`, `outputSchema`, backward-compat SHOULD
- https://modelcontextprotocol.io/specification/2024-11-05/server/tools — no structuredContent/outputSchema in this version
- https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2025-06-18/schema.ts — `Result` open index signature; `CallToolResult` fields
- https://github.com/modelcontextprotocol/python-sdk — `types.py`: `Result`/`CallToolResult`, `ConfigDict(extra="allow")` preserves unknown keys
- https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1624 — SEP-1624, structuredContent vs content (direction-of-travel)
