# Research: MCP `structuredContent` auto-promotion and the loss of tool text at the client

**Date:** 2026-08-03
**Branch:** `master`
**Commit:** `11563a3` (working tree clean apart from this document)
**Library version in tree:** `3.13.0rc3`

**Intake:** this document replaces an earlier draft written from a consumer bug
report in `actingweb_mcp`
(`../actingweb_mcp/thoughts/research/2026-08-03-agent-run-returns-only-run-id.md`,
`../actingweb_mcp/thoughts/plans/2026-08-03-agent-run-returns-only-run-id.md`).
Every load-bearing claim below has been re-verified against primary sources in
this repository, the published MCP specification, the reference Python SDK, and
the shipped Claude Code binary. Where a claim could **not** be verified from
here, it is marked as attributed rather than confirmed. Two claims from the
intake report were found to be wrong or incomplete and are corrected in
Findings F6 and F7.

## Research Question

`format_call_tool_result` promotes every unrecognised top-level key of a tool
hook's return value into MCP `structuredContent`. A consumer outage was
root-caused to that promotion. What exactly does the library do, what do the
specification and the reference implementations do, what is the measured client
behaviour, and what are the options for changing it — including what each option
breaks?

## Summary

The library's behaviour is confirmed exactly as described: when the negotiated
protocol version is `2025-06-18` or newer and a tool hook returns a dict
containing `content`, any top-level key other than `content`, `isError`,
`_meta` and `structuredContent` is swept into `structuredContent`
(`actingweb/handlers/mcp.py:162-171`). This is the only place in the library
that emits `structuredContent`, and both the Flask and FastAPI transports share
it.

The specification permits `structuredContent` without a declared `outputSchema`,
so the promotion is **not** a protocol violation — but it does break an
invariant that both the spec's guidance and the reference server maintain. The
spec says (verbatim, identical in `2025-06-18` and `2025-11-25`): *"For
backwards compatibility, a tool that returns structured content SHOULD also
return the serialized JSON in a TextContent block."* The reference Python server
honours this literally — when a tool returns a dict, it sets
`structuredContent` to that dict **and** sets `content` to
`json.dumps(results)` of the same dict
(`mcp/server/lowlevel/server.py:554-557`). It never produces a result where the
text and the structured payload say different things. ActingWeb's promotion
produces exactly that: prose in `content`, unrelated metadata in
`structuredContent`. A client that assumes the spec's invariant — that the text
is a serialization of the structure — will treat the text as redundant. Claude
Code 2.1.220 does precisely that: its MCP result normaliser, read directly from
the shipped binary, discards **every** `type: "text"` content block when
`structuredContent` is present, and passes only the serialized JSON to the
model. The library cannot observe this; the response is well-formed and nothing
in the protocol reports the discard back.

Three facts materially change the shape of the decision relative to the intake
report. First, the affected code shipped in **stable** releases `v3.11.0` and
`v3.12.0`, not only in the current `3.13.0` pre-release train, so this is a
change to behaviour that has been generally available since 2026-05-27
(F6). Second, gating on the declared `output_schema` — the spec-aligned
alternative — is *less* blocked than the intake report claims: the blocking
`isError` gap is real library behaviour but is presently **latent**, because no
tool in the one known consumer declares an `output_schema` at all (F7). Third,
the promotion is gated per request on the `MCP-Protocol-Version` header, and a
request without that header negotiates `2025-03-26`, where no
`structuredContent` is emitted at all — so the behaviour is header-conditional,
not merely deploy-conditional (F2).

## Detailed Findings

### F1 — What the library does today (verified)

`actingweb/handlers/mcp.py:133-177`, quoted in full from source:

```python
_CALL_TOOL_RESERVED_KEYS = frozenset(
    {"content", "isError", "_meta", "structuredContent"}
)                                                                    # :133-135

def format_call_tool_result(result: Any, negotiated_version: str) -> dict[str, Any]:
    if isinstance(result, dict) and "content" in result:             # :153
        out: dict[str, Any] = {
            "content": result["content"],
            "isError": bool(result.get("isError", False)),           # :156
        }
        meta = result.get("_meta")
        if isinstance(meta, dict):                                   # :159
            out["_meta"] = meta

        if supports_structured_content(negotiated_version):          # :162
            explicit_struct = result.get("structuredContent")
            if isinstance(explicit_struct, dict):                    # :164
                out["structuredContent"] = explicit_struct
            else:
                extras = {
                    k: v for k, v in result.items()
                    if k not in _CALL_TOOL_RESERVED_KEYS
                }                                                    # :167-169
                if extras:
                    out["structuredContent"] = extras                # :171
        return out

    if not isinstance(result, dict):                                 # :175
        result = {"result": result}
    return {"content": [{"type": "text", "text": str(result)}]}      # :177
```

Behaviours that follow directly from this code:

- The explicit-`structuredContent` passthrough at `:164-165` already exists and
  already suppresses the sweep. A hook that sets `structuredContent` explicitly
  gets exactly that dict and nothing else — `tests/test_mcp_tool_result_format.py:56-64`
  pins this, including that an extra sibling key is *not* merged in.
- On the `content` branch, `isError` is always present, explicitly `false` when
  the hook omits it (`:156`).
- A **non-dict** `structuredContent` supplied by a hook fails the `isinstance`
  check at `:164`, falls into the `else`, and is then excluded from `extras` by
  the reserved-key set — so it is silently dropped, and any *other* extra keys
  are emitted as `structuredContent` in its place. This is an undocumented
  edge case, not covered by any test.
- The legacy branch (`:174-177`) emits `content` only. It never emits
  `isError` and never emits `structuredContent`.

This is the **only** code in the library that writes `structuredContent`. A grep
over `actingweb/` finds `structuredContent` in just two modules:
`handlers/mcp.py` (the writer) and `mcp/protocol.py` (comments plus the version
constant). Resources and prompts do not emit it.

Both transports share the function: `actingweb/handlers/mcp.py:997-999` (sync,
Flask) and `actingweb/handlers/async_mcp.py:194-196` (async, FastAPI). The two
dispatch loops are otherwise identical apart from `await` handling
(`async_mcp.py:186-189`). A single change covers both.

### F2 — When the promotion gate is open (per-request, header-driven)

A new handler instance is constructed for every HTTP request
(`actingweb/interface/integrations/flask_integration.py:1404`,
`fastapi_integration.py:2347`), so the version recorded during `initialize`
does not survive to later requests. Every post-`initialize` request re-derives
the version from the `MCP-Protocol-Version` header
(`actingweb/handlers/mcp.py:1294-1330`):

- Header absent → `DEFAULT_NEGOTIATED_VERSION = "2025-03-26"`
  (`actingweb/mcp/protocol.py:36-39`), which is `< "2025-06-18"`, so
  `supports_structured_content` returns `False` and **no `structuredContent` is
  emitted at all** — not even an explicit one.
- Header present but unsupported → HTTP 400 with JSON-RPC `-32600`
  (`mcp.py:1321-1327`).
- Header present and supported → that version is used (`mcp.py:1329`).

Claude Code sends the header. Read from the shipped bundle
(`~/.local/share/claude/versions/2.1.220`):

```js
if(this._protocolVersion) e["mcp-protocol-version"] = this._protocolVersion;
```

and its latest supported revision is `"2025-11-25"`, which ActingWeb also
supports (`actingweb/mcp/protocol.py:28-33`), so negotiation settles on
`2025-11-25` and the gate is open by default for this client.

Practical consequence: the promotion is invisible to any test or client that
omits the header, and invisible on `2024-11-05`/`2025-03-26` clients. It becomes
active only against a client that negotiates `2025-06-18`+ — which is what makes
it appear to work in some environments and not others.

### F3 — What the specification says (primary source, verbatim)

Fetched from <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
and <https://modelcontextprotocol.io/specification/2025-11-25/server/tools>. The
two revisions are **identical** on these points.

Structured Content section:

> **Structured** content is returned as a JSON object in the `structuredContent`
> field of a result.
>
> For backwards compatibility, a tool that returns structured content SHOULD
> also return the serialized JSON in a TextContent block.

Output Schema section:

> Tools may also provide an output schema for validation of structured results.
> If an output schema is provided:
>
> * Servers **MUST** provide structured results that conform to this schema.
> * Clients **SHOULD** validate structured results against this schema.

What the spec does **not** say, checked explicitly:

- It does not forbid `structuredContent` on a tool with no declared
  `outputSchema`. The `outputSchema` rules are conditional ("If an output schema
  is provided"). So today's promotion is **legal**, not a violation. The next
  revision, `2026-07-28`, makes the permission explicit rather than merely
  implicit: *"This can be any JSON value … that conforms to the tool's
  `outputSchema` **if one is defined**."* (That revision also relaxes
  `structuredContent` from object-only to any JSON value; ActingWeb's supported
  set currently tops out at `2025-11-25`,
  `actingweb/mcp/protocol.py:28-33`.)
- It does not sanction, describe, or forbid a client discarding `content` when
  `structuredContent` is present. The client behaviour in F5 is an
  interpretation, not a mandated one.
- It does not require `structuredContent` to be a superset, subset, or
  derivative of the text — but the backwards-compatibility SHOULD assumes the
  text *is* the serialized structure. (Formatting note: that `SHOULD` is
  unbolded in the source `.mdx`, unlike the `MUST`/`SHOULD`/`MAY` around it.)

The example result in both revisions shows exactly that relationship: `content`
is `"{\"temperature\": 22.5, \"conditions\": \"Partly cloudy\", \"humidity\": 65}"`
and `structuredContent` is the same object.

**Client handling of the two fields is an acknowledged, unresolved gap in the
spec.** `modelcontextprotocol/modelcontextprotocol#1411`, "Clarify client
handling of structuredContent vs content fields" (filed 2025-09-01, assigned,
still open with no PR), states that the spec fails to define how clients must
handle `structuredContent` when present, whether `content` should always be a
stringified variant, and whether structured-capable clients should prioritise
it. `modelcontextprotocol/typescript-sdk#911` is the SDK-side tracker, blocked
on it, and lists "establish a proper fallback to `content`" as pending work.

Notably, the complaint driving #1411 is the **opposite** failure mode: clients
(it names Claude and Windsurf) *ignoring* `structuredContent` entirely, with
only Cursor supporting it. No spec-level issue was found asserting that clients
drop text blocks when `structuredContent` is present. That is a meaningful
negative result for this decision: relying on any particular client treatment of
a `content`/`structuredContent` divergence is unspecified territory in **both**
directions.

### F4 — What the reference implementations do

**Reference Python server** (`mcp` SDK, read from
`../actingweb_mcp/.venv/lib/python3.14/site-packages/mcp/server/lowlevel/server.py:540-583`).
Its normalisation has exactly three shapes:

```python
elif isinstance(results, tuple) and len(results) == 2:
    # tool returned both structured and unstructured content
    unstructured_content, maybe_structured_content = cast(CombinationContent, results)
elif isinstance(results, dict):
    # tool returned structured content only
    maybe_structured_content = cast(StructuredContent, results)
    unstructured_content = [types.TextContent(type="text", text=json.dumps(results, indent=2))]
elif hasattr(results, "__iter__"):
    # tool returned unstructured content only
    unstructured_content = cast(UnstructuredContent, results)
    maybe_structured_content = None
```

The reference server therefore **never** emits `structuredContent` alongside
text that is not its serialization, except when the tool author explicitly
returns a `(content, structured)` tuple. There is no auto-promotion of
individual keys anywhere in it. It also validates server-side when a schema is
declared (`:565-575`), returning an error result if `structuredContent` is
missing or non-conforming.

Two points follow that bear directly on D1. First, the reference server *does*
emit `structuredContent` for a schema-less tool (the `isinstance(results, dict)`
branch is unconditional; the schema check is a separate later block) —
confirming F3's reading that schema-less structured output is legitimate.
Second, the tuple form is precisely the shape ActingWeb's promotion produces —
prose in `content`, unrelated data in `structuredContent` — but there it is an
**explicit act by the tool author**, never inferred. The reference server's
tuple is the structural analogue of ActingWeb's explicit `structuredContent`
key; it has no analogue of the sweep.

**FastMCP** (the high-level server in the same SDK) is stricter still —
`mcp/server/fastmcp/utilities/func_metadata.py`, `convert_result`:

```python
    if self.output_schema is None:
        return unstructured_content
    else:
        ...
        validated = self.output_model.model_validate(result)
        structured_content = validated.model_dump(mode="json", by_alias=True)
        return (unstructured_content, structured_content)
```

No `structuredContent` at all unless a return-type-derived schema exists, and
what is emitted is the serialization of the declared return model — never keys
scraped from elsewhere.

**Reference Python client**
(`.../mcp/client/session.py:411-441`, read from source):

```python
if not result.isError:
    await self._validate_tool_result(name, result)
...
if output_schema is not None:
    if result.structuredContent is None:
        raise RuntimeError(
            f"Tool {name} has an output schema but did not return structured content"
        )
    validate(result.structuredContent, output_schema)
```

Note the guard: validation happens **only** when the tool declares an output
schema. `structuredContent` present with no declared schema raises nothing —
`_tool_output_schemas` stores `None` for schema-less tools and every validation
path is gated behind `if output_schema is not None`. (This validation was added
in SDK v1.10.0; v1.9.4 had none.)

**The bundled TypeScript MCP client** in Claude Code behaves the same way (read
from the 2.1.220 binary; the error string is byte-identical to the Python
SDK's):

```js
let o = this.getToolOutputValidator(e.name);
if (o) {
  if (!n.structuredContent && !n.isError)
    throw new _s(Rs.InvalidRequest, `Tool ${e.name} has an output schema but did not return structured content`);
  ...
}
```

So across both reference clients: declaring an `outputSchema` creates a hard
obligation to return `structuredContent` on every non-error result; not
declaring one imposes no obligation in either direction.

Equally important for F5: **neither SDK client touches `content`.** The upstream
TypeScript SDK's `callTool` (checked at tag `1.17.0`) returns the result
unmodified — it never reads, filters, or mutates `content`. Whatever discards
text blocks therefore lives in the *host application* layered on top of the SDK,
not in the protocol library.

### F5 — The observed client behaviour that makes promotion destructive

This is **host-application** behaviour, not MCP SDK behaviour (F4: the SDK
client passes `content` through untouched), and it is sanctioned by no spec
revision (F3). Verified independently for this document by reading the MCP
result normaliser out of the shipped Claude Code 2.1.220 binary
(`~/.local/share/claude/versions/2.1.220`), reformatted from the minified
source:

```js
if ("toolResult" in e) return { content: String(e.toolResult), type: "toolResult" };
if ("structuredContent" in e && e.structuredContent !== undefined) {
  let i = Ie(e.structuredContent);                       // JSON serialization
  let s = pcr(e.structuredContent);
  if ("content" in e && Array.isArray(e.content)) {
    let a = e.content.filter((l) => l && typeof l === "object"
                                  && ("type" in l) && l.type !== "text");
    if (a.length > 0) {
      let l = (await Promise.all(a.map((c) => Vbo(c, r, n, !0)))).flat();
      if (l.length > 0) {
        let c = [...l, { type: "text", text: i }];
        return { content: c, type: "contentArray", schema: pcr(LFe(c)) };
      }
    }
  }
  return { content: i, type: "structuredContent", schema: s };
}
if ("content" in e && Array.isArray(e.content)) { /* normal path */ }
```

When `structuredContent` is present and defined, every `type: "text"` block is
filtered out. Non-text blocks (images, audio) survive, with the serialized JSON
appended as a single text block. If the result contains only text blocks — the
common case — the model receives nothing but the serialized JSON.

Also verified from the same binary, and relevant to any workaround that routes
data through `_meta`:

```js
return {
  data: Ae.content,
  ...(Ae._meta || Ae.structuredContent) && {
    mcpMeta: { ...Ae._meta && { _meta: Ae._meta },
               ...Ae.structuredContent && { structuredContent: Ae.structuredContent } }
  }
}
```

`_meta` is routed to a side channel (`mcpMeta`) separate from the model-facing
`data`. The intake material listed "move the extra key to `_meta`" as an
unverified workaround; it is now verified that `_meta` does not reach the model
as content in this client, so that route hides the value rather than delivering
it.

The library has no way to detect any of this. The response is well-formed, there
is no `isError`, and nothing in the protocol reports the discard back to the
server.

### F6 — Affected releases (corrects the intake report)

The intake report frames the fix as cheap because "3.13.0 is still in
pre-release". That framing is incomplete.

`git log -S'_CALL_TOOL_RESERVED_KEYS'` and `-S'def format_call_tool_result'`
each return exactly one commit:

- **`c61e059`**, 2026-05-27, *"Pre-release v3.10.2b5: MCP version negotiation,
  structuredContent, drop mcp SDK dependency (#100)"*. The code has not been
  touched since.

`git tag --contains c61e059` returns 17 tags. Of those, the **stable** releases
are:

- **`v3.11.0`** (July 4, 2026)
- **`v3.12.0`**

plus the pre-release lines `v3.10.2b5`–`b9`, `v3.11.0b1`–`b7`, and
`v3.13.0rc1`–`rc3`.

Checked against production PyPI (`https://pypi.org/pypi/actingweb/json`):
`3.11.0` and `3.12.0` are both published there, and `3.12.0` is the current
`latest`. `3.10.2b5` and `3.13.0rc3` are absent, consistent with `CLAUDE.md`'s
rule that pre-releases publish to TestPyPI. So the promotion is not merely
tagged — it is generally available to anyone who has ever run
`pip install actingweb`, and has been for roughly two months across two stable
minor releases. It is documented as the contract in the `v3.11.0` changelog
entry (`CHANGELOG.rst:742-748`):

> A hook returning a dict with ``content`` plus extra top-level keys has those
> extras promoted into ``structuredContent``; an explicit ``structuredContent``
> from the hook is passed through, and a hook-supplied ``_meta`` is preserved.

and in the user-facing guide (`docs/guides/mcp-applications.rst:356-363`), which
additionally carries a worked example (`:365-382`) whose inline comment reads
`# Promoted into structuredContent on >= 2025-06-18:` — and which, confusingly,
also declares an `output_schema` on the same tool, implying a causal link that
does not exist in the code.

Any change is therefore a behaviour change to a documented, released contract,
not to unreleased code. It can still ride the current train (`3.12.0` →
`3.13.0` is a minor bump), but the decision should be made on that basis.

### F7 — The `output_schema` gate: what actually blocks it (corrects the intake report)

The intake report argues that gating promotion on a declared `output_schema` is
blocked, because the library never sets `isError` on the legacy-wrap path, so
any error result lacking a `content` key would reach the wire as
`isError: false` and then fail client-side schema validation. Both halves were
checked separately.

**The library half is confirmed.** A grep for `isError` across the whole
`actingweb/` package returns exactly three hits, all inside
`format_call_tool_result`: the reserved-key set (`mcp.py:134`), the docstring
(`:145`), and the single assignment (`:156`). The legacy branch
(`mcp.py:174-177`) emits no `isError` key, so `CallToolResult.isError` defaults
to `false` on the wire. Additionally, **every** library-internal failure on the
`tools/call` route returns a JSON-RPC *error object* via `_create_jsonrpc_error`
(`mcp.py:1284-1292`) rather than a `CallToolResult` — missing tool name
(`-32602`), no hooks registry (`-32603`), no resolved trust (`-32003`),
permission denied (`-32003`), hook raised (`-32603`), tool not found
(`-32601`), and the async mirrors at `async_mcp.py:129-208`. So `isError: true`
can *only* originate from a hook that returns `{"content": [...], "isError": True}`.

**The consequence half is presently latent, not active.** The trap requires a
tool that declares an `output_schema`. Checked in the one known consumer: a grep
for `output_schema` across `actingweb_mcp` (excluding its venv) returns 9 hits,
**all** of which belong to that app's own unrelated `describe_method` /
peer-capability surface — none is an `@mcp_tool(output_schema=...)` declaration.
Across 38 `@mcp_tool` decorations there, zero declare an MCP output schema.
Inside this library, `output_schema` is accepted by the decorator
(`actingweb/mcp/decorators.py:21,89`) and emitted in `tools/list`
(`actingweb/handlers/mcp.py:719-721`), but **no call path ever reads it**.

There is a second, independent consequence of that same gap that the intake
report does not mention, and which exists **today**, regardless of any change:
because the library never consults `output_schema` at call time, a tool that
declares one and returns a plain `{"content": [...]}` with no extras produces a
result with no `structuredContent`. Both reference clients raise on that
(`Tool X has an output schema but did not return structured content`). So
declaring `output_schema` on an ActingWeb tool is already a latent way to break
that tool for spec-conforming clients. No test covers this
(`tests/test_mcp_tool_schema_fields.py` covers only `tools/list` serialization),
and no known consumer has hit it because none declares a schema.

The two halves of the MCP `outputSchema` ↔ `structuredContent` contract were
implemented a day apart (`c61e059` for `structuredContent`, `506eb6d` for the
`tools/list` `outputSchema` emission) and were never wired together.

### F8 — Why the promotion exists (recorded design intent)

`thoughts/plans/2026-05-26-mcp-version-negotiation-structuredcontent.md:81-91`,
"Decisions taken (2026-05-26)":

> **structuredContent extras strategy:** **MVP = promote all extras** … build
> `{content, isError}`, pass through an explicit `structuredContent` if the hook
> set one, else sweep all non-reserved top-level keys into `structuredContent`.
> Backward-compatible with existing `content`+extras hooks (the "emm" Personal
> AI Memory app) without requiring `output_schema` declarations.
> `output_schema`-gated validation is an optional later refinement, not MVP.

The schema-gated alternative was explicitly deferred, recorded as open question
O3 (`:348-349`) and Phase 3 roadmap item 3 (`:317-319`). The companion research
`thoughts/research/2026-05-26-mcp-tool-result-structuredcontent.md:179-197` had
already listed the same three options and concluded *"Evidence is split… This is
a genuine product decision, not a clear win."*

Worth recording: the compatibility target that motivated promote-all-extras was
the *same consumer* that the promotion later broke. The measured harm is a
direct consequence of the compatibility choice made on its behalf.

### F9 — Reported consumer impact (attributed; mechanism verified, measurements not reproducible here)

From `../actingweb_mcp/thoughts/research/2026-08-03-agent-run-returns-only-run-id.md`.
These are consumer-side measurements against production data and **cannot be
reproduced from this repository**; they are recorded as attributed evidence. The
*mechanism* they describe is independently verified in F1 and F5.

- Server-side replay: the `agent_run` handler returned
  `keys: ['content', 'isError', 'run_id']` with **135,151 characters** of text,
  all sections present.
- Client-side, same call through Claude Code: the model received
  `{"run_id": null}`.
- Trigger: `agent_run` began returning a top-level `run_id` in the consumer's
  `v2026.08.02` deploy; the next scheduled hourly cycle degraded.
- The report lists the affected tool family as also including
  `agent_run_complete`, the `instruction_*` tools and the `output_*` tools, and
  states the failure went unnoticed on those because their extras *duplicate*
  the text payload, so the JSON still carried what the model needed. **This is
  the consumer's own classification of its own tools, not a measurement** — do
  not treat it as a verified scope list.
- Likewise the consumer's report that two tools were carrying a full document
  body in **both** `content` and the promoted extras (up to ~42 KB doubled per
  call) is its own estimate, unverified from here.

The asymmetry is the notable part and it follows from F5 without needing the
measurements: tools whose extras duplicate their prose keep working; tools whose
prose is the unique payload lose everything. The failure mode selects for the
cases where the loss matters most.

### F10 — What in this repository depends on the current behaviour

**Tests — six assertions across six tests fail if the sweep at
`mcp.py:166-171` is deleted:**

| File:line | Assertion |
| --- | --- |
| `tests/test_mcp_tool_result_format.py:38` | `assert out["structuredContent"] == {"success": True, "memory_type": "note"}` |
| `tests/test_mcp_tool_result_format.py:43` | `assert out["structuredContent"] == {"count": 3}` (the test's only assertion) |
| `tests/test_mcp_tool_result_format.py:75` | `assert out["structuredContent"] == {"extra": 1}` (in `test_meta_is_preserved_not_swept` — uses the promoted payload as the witness that `_meta` was not swept) |
| `tests/test_mcp_tool_result_format.py:166-169` | `assert sync_result["result"]["structuredContent"] == {...}` (the only test reaching the formatter through a real `tools/call` on both handlers) |
| `tests/integration/test_mcp_tools.py:517-520` | `assert out["structuredContent"] == {"success": True, "memory_type": "memory_test"}` |
| `tests/integration/test_mcp_tools.py:539-542` | `assert out["structuredContent"] == {"success": False, "error": "Validation failed"}` |

Everything else in the suite is unaffected. Specifically these keep passing
unchanged: `test_old_version_omits_structured_content:45` (already gated off by
version), `test_explicit_structured_content_passthrough:56` (the only existing
test of the explicit-only contract — it already asserts extras are *not* merged
in), `test_isError_true_preserved:77`, `test_content_only_no_structured_content:83`,
both legacy-wrap tests at `:91`/`:97`, `test_tool_response_without_is_error_field`
(`tests/integration/test_mcp_tools.py:544-556`), and the sync/async equality
assertion at `test_mcp_tool_result_format.py:165` (parity holds whatever the
formatter does).

Note the three "integration" tests in
`tests/integration/test_mcp_tools.py:487-556` call the formatter directly — no
HTTP, no fixtures — so they are unit tests by placement only. There is **no**
end-to-end test that asserts the wire shape of a `tools/call` response for a
hook returning extras; the sole in-dispatch coverage is
`test_mcp_tool_result_format.py:106-169`.

Only one test fixture returns `content` plus extras and can reach the sweep:
`store_hook` at `tests/test_mcp_tool_result_format.py:114-122`. Other fixture
hooks (`tests/test_async_mcp_handler.py:109,160,257,265,419`,
`tests/test_mcp_permissions.py:14,18`) return dicts with no `content` key and go
down the legacy wrap.

**Documentation and changelog:**

- `docs/guides/mcp-applications.rst:348-385` — the "Structured Tool Output"
  section documents promotion as the contract, with a worked example that relies
  on it (`:365-382`).
- `CHANGELOG.rst:742-748` — the `v3.11.0` `ADDED` entry documenting promotion.
- `CHANGELOG.rst:5-6` — an empty "Unreleased" section is present and ready.
- `docs/migration/v3.11.rst:164-166` mentions `structuredContent` only in
  passing, with no detail on promotion.
- `docs/_build/` contains generated copies; not source.

## Decisions Needed

### D1 — What replaces the current promotion behaviour?

**Option A — keep it as is.** No work, no migration. Cost: the measured client
harm in F5/F9 persists, and the trap keeps firing on addition of any top-level
key. Nothing in this research supports A except inertia; it is listed for
completeness.

**Option B — promote only an explicit `structuredContent` key.** Delete the
`else:` branch at `mcp.py:166-171`; keep the explicit passthrough at `:164-165`,
the `_meta` handling at `:158-160`, and the legacy wrap at `:174-177`.

- Aligns the library with the reference server's invariant (F4): implicit
  `structuredContent` disappears, and any `structuredContent` on the wire is a
  deliberate act by the hook author, who is then also responsible for the
  spec's backwards-compatibility SHOULD.
- **No-op for correctly-written hooks.** `mcp.py:164-165` already passes an
  explicit key through unchanged, so a downstream can migrate to explicit
  `structuredContent` *first*, verify byte-identical output against
  `3.13.0rc3`, and upgrade afterwards — no coordinated deploy window.
- Cost: any downstream relying on promotion silently loses its structured
  payload on upgrade (F6: shipped in two stable releases). Extras that are not
  explicitly promoted are simply not serialized anywhere.
- Test cost: six assertions (F10). Docs cost: `mcp-applications.rst:348-385`
  including its example.
- Migration-note considerations, two of them, both facts the migration guidance
  has to carry because the library cannot enforce either:
  1. Per spec issue #1411 (F3), several major clients **ignore**
     `structuredContent` entirely. A hook author moving extras under an explicit
     key should also honour the spec's backwards-compatibility SHOULD — keep the
     same data serialized in a text block — or those clients see nothing.
  2. Per F2, a request with no `MCP-Protocol-Version` header negotiates
     `2025-03-26`, where the version gate at `mcp.py:162` suppresses
     `structuredContent` **including an explicit one**. Under Option B the
     explicit key becomes the only path, so a migrated hook still emits no
     structured payload to such a client. The text block is the only thing that
     always arrives.

**Option C — gate promotion on a declared `output_schema`.** Pass the tool's
`metadata` (already in local scope at both call sites —
`mcp.py:983` and `async_mcp.py:180`, both 14 lines before the formatter call)
and promote only when `metadata.get("output_schema")` is set.

- Closest to the spec's model, and it *would* fix the reported incident, since
  the affected tool declares no schema.
- But: promoting arbitrary extras under a declared schema does not make them
  *conform* to it, and the spec is a **MUST** there (F3). Option C without
  validation trades a silent text loss for a silent conformance violation that
  both reference clients will surface as a hard error.
- And it inherits the `isError` gap (F7): a hook whose error path returns a dict
  with no `content` key reaches the wire as `isError: false` with no
  `structuredContent`, and a schema-declaring tool then fails client validation.
  This is **latent today** (no known tool declares a schema) but becomes active
  the moment anyone adopts C's incentive to declare one.
- C is not exclusive with B. B can ship now; C is a later, larger piece of work
  that also needs the `isError` gap closed and server-side validation added.

**Option D — opt-in promotion flag on the decorator**, e.g.
`@mcp_tool(promote_extras=True)`. Preserves the capability without the silent
default. Cost: a new public API surface for a behaviour that Option B already
provides via an explicit `structuredContent` key, with no additional
expressiveness — the correct payload can differ per response within one tool,
which a per-tool flag cannot express.

**Recommendation:** Option B. It is the only option that removes the measured
harm (F5) while matching what both reference server implementations do (F4), and
it is a no-op for hooks that already set `structuredContent` explicitly (F1), so
downstreams can migrate before upgrading. B and C are not mutually exclusive —
whether C is additionally in scope, now or later, is a separate call and is left
open here.

### D2 — How is this released, and is it breaking?

The promotion is documented behaviour shipped in stable `v3.11.0` and `v3.12.0`
(F6), so removing it is a breaking change to a released contract, whatever the
current pre-release state of `3.13.0`.

**Options:**

1. **Ride the current train** — ship as `3.13.0rc4`, TestPyPI, with the
   behaviour change called out prominently in `CHANGELOG.rst` and a migration
   note. `3.12.0` → `3.13.0` is already a minor bump, so the version number
   carries the change legitimately. The one known consumer is coordinating in
   the same train.
2. **Hold for a dedicated minor** after `3.13.0` goes stable, keeping the
   `3.13.0` release scoped to what it already contains.

Either way, `CLAUDE.md`'s release process applies: the version bump and the
"Unreleased" → `vX.Y.ZrcN` rename ride in the release PR, master is protected,
and the tag is pushed to the merge commit afterwards. `CHANGELOG.rst:5-6`
already has an empty "Unreleased" section.

Secondary question: does this warrant an entry in `docs/migration/` (a
`v3.13.rst` already exists and is referenced from the `v3.13.0rc3` changelog
note), or is a changelog entry plus the guide rewrite sufficient?

### D3 — Should there be an escape hatch that restores promotion?

**Options:**

1. **No flag.** The migration is one line per response (nest the extras under
   `structuredContent`), and a flag preserves a footgun that fails silently.
2. **App-level config flag** (e.g. on `with_mcp(...)`) for deployments that
   cannot migrate hooks in step with the upgrade.
3. **Per-tool decorator flag** (Option D above).

Evidence bearing on this: the correct answer differs *per response* within a
single tool (F9 — the same consumer wants `structuredContent` on its data-shaped
tools and none on its prose tools), which neither an app-level nor a per-tool
flag can express, while an explicit `structuredContent` key can.

### D4 — Should the library say anything when it drops extras it would previously have promoted?

Silent behaviour change vs. migration aid.

**Options:**

1. **Silent.** The upgrade is opt-in via the version pin and the changelog
   carries the migration.
2. **`logger.debug`** naming the tool and the dropped keys.
3. **`logger.warning`**, once per tool per process. Loudest migration aid;
   noisiest for hooks that return incidental keys deliberately and never wanted
   them serialized.

Note that under Option B the "dropped" keys were never *reaching the model as
content* anyway on affected clients — they were replacing it. Under
`2025-03-26` and older they are already dropped today with no log (F2), so
option 1 is at least self-consistent with existing behaviour.

### D5 — Are the two adjacent defects in scope for the same change?

Both are real, independent of D1, and were found while verifying F7.

1. **Legacy-wrap emits no `isError`** (`mcp.py:174-177`). Every error result
   from a hook that returns a dict without a `content` key reaches the wire
   claiming success. Not a prerequisite for Option B; a hard prerequisite for
   Option C.
2. **`output_schema` is advertised but never enforced.** A tool declaring
   `output_schema` today and returning content-only produces no
   `structuredContent`, which both reference clients reject with
   `Tool X has an output schema but did not return structured content` (F4, F7).
   This is broken *now*, for anyone who declares a schema.

**Options:** fix both in the same release (widens the blast radius of a release
whose point is to make one behaviour predictable); fix neither and file them as
`thoughts/todo/` items; or fix (1) only, since it is a two-line change and is
the gate on ever adopting Option C.

A third, smaller item for the same call: the non-dict-`structuredContent`
edge case in F1, where a hook supplying a non-dict `structuredContent` has it
silently dropped *and* gets other extras promoted in its place. Under Option B
the second half disappears; the silent drop remains.

### D6 — What test coverage should the change carry?

Not a decision so much as a scope question for the plan, but the intake material
under-specifies it. Beyond inverting the six assertions in F10:

- Extras present **and** an explicit `structuredContent` present → only the
  explicit one is emitted (guards the deleted branch from returning).
- Extras present, no explicit key → `structuredContent` absent **and** the text
  content survives byte-for-byte.
- `test_meta_is_preserved_not_swept` rebuilt on an explicit `structuredContent`
  rather than on promotion, so it still proves `_meta` is not swept.
- The sync/async parity fixture (`store_hook`,
  `tests/test_mcp_tool_result_format.py:114-122`) needs its assertion re-based;
  the parity assertion at `:165` itself is unaffected.
- Open: should a genuine end-to-end wire-shape test be added? Today no test
  asserts the JSON that leaves the handler for a hook returning extras; the
  closest is `test_mcp_tool_result_format.py:106-169`, and the integration
  "regression" class calls the formatter directly.

## Code References

- `actingweb/handlers/mcp.py:133-135` — `_CALL_TOOL_RESERVED_KEYS`
- `actingweb/handlers/mcp.py:138-177` — `format_call_tool_result`; docstring at
  `:138-152` documents promotion as the contract
- `actingweb/handlers/mcp.py:153` — the `"content" in result` gate that splits
  MCP-shaped from legacy results
- `actingweb/handlers/mcp.py:156` — the only `isError` assignment in the library
- `actingweb/handlers/mcp.py:162-171` — version gate, explicit passthrough
  (`:164-165`), extras sweep (`:166-171`)
- `actingweb/handlers/mcp.py:174-177` — legacy wrap; no `isError`, no
  `structuredContent`
- `actingweb/handlers/mcp.py:983`, `:997-999` — sync dispatch: `metadata` bound
  14 lines before the formatter call
- `actingweb/handlers/async_mcp.py:180`, `:194-196` — async dispatch, same shape
- `actingweb/handlers/mcp.py:1284-1292` — `_create_jsonrpc_error`; every
  library-internal `tools/call` failure goes here, not through the formatter
- `actingweb/handlers/mcp.py:1294-1330` — per-request protocol version
  resolution from the `MCP-Protocol-Version` header
- `actingweb/handlers/mcp.py:719-721` — `outputSchema` emitted in `tools/list`
  (never read at call time)
- `actingweb/mcp/decorators.py:21,89` — `output_schema` accepted and stored
- `actingweb/mcp/protocol.py:28-45` — supported versions,
  `DEFAULT_NEGOTIATED_VERSION = "2025-03-26"`,
  `STRUCTURED_CONTENT_MIN_VERSION = "2025-06-18"`
- `actingweb/mcp/protocol.py:65-69` — `supports_structured_content`
- `actingweb/interface/integrations/flask_integration.py:1404`,
  `fastapi_integration.py:2347` — a new handler instance per request
- `tests/test_mcp_tool_result_format.py:28-100` — pure-formatter tests
- `tests/test_mcp_tool_result_format.py:106-169` — the only in-dispatch
  sync/async parity test
- `tests/integration/test_mcp_tools.py:487-556` — response-format regression
  class (calls the formatter directly)
- `tests/test_mcp_version_negotiation.py:50-57` — the version gate in isolation
- `tests/test_mcp_tool_schema_fields.py:64-131` — `tools/list` `outputSchema`
  serialization only
- `docs/guides/mcp-applications.rst:348-385` — user-facing documentation of
  promotion, including the worked example at `:365-382`
- `CHANGELOG.rst:742-748` — the `v3.11.0` entry documenting promotion
- `thoughts/plans/2026-05-26-mcp-version-negotiation-structuredcontent.md:81-91,317-319,348-349`
  — the recorded MVP decision and its deferred alternative
- `thoughts/research/2026-05-26-mcp-tool-result-structuredcontent.md:179-197` —
  the original three-way option analysis

## External References

**Verified directly from primary sources on 2026-08-03:**

- <https://modelcontextprotocol.io/specification/2025-06-18/server/tools> and
  <https://modelcontextprotocol.io/specification/2025-11-25/server/tools> —
  "Structured Content" and "Output Schema" sections, quoted verbatim in F3.
  Identical text in both revisions. `structuredContent` without a declared
  `outputSchema` is permitted; the backwards-compatibility SHOULD expects the
  text block to carry the serialized JSON; nothing addresses clients discarding
  `content`.
- <https://modelcontextprotocol.io/specification/2026-07-28/server/tools> —
  the next revision, which makes schema-less `structuredContent` explicit
  ("*if one is defined*") and relaxes it to any JSON value. Not yet in
  ActingWeb's supported set.
- <https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1411> —
  "Clarify client handling of structuredContent vs content fields", open, no PR.
  The spec-level acknowledgement that client handling of the two fields is
  undefined. Its reported failure mode is clients *ignoring*
  `structuredContent`, not clients dropping `content`.
- <https://github.com/modelcontextprotocol/typescript-sdk/issues/911> — the
  SDK-side tracker for #1411; pending work includes "establish a proper fallback
  to `content`".
- <https://github.com/modelcontextprotocol/typescript-sdk/issues/654> (closed by
  PR #655) — why both SDKs now guard schema validation behind `isError`: a tool
  with an `outputSchema` previously could not return a plain-text error.
  Directly relevant to D5's `isError` gap.
- <https://github.com/anthropics/claude-code/issues/14465> — a live instance of
  the F7 trap in the wild: a server advertising `outputSchema` while returning
  `structuredContent: null` made every `call_tool` raise
  `Tool Bash has an output schema but did not return structured content`.
- Reference Python server, `mcp/server/lowlevel/server.py:540-583` (read from
  `../actingweb_mcp/.venv/lib/python3.14/site-packages/`, cross-checked against
  the published v1.18.0 source) — three-shape normalisation, `json.dumps` of the
  structured dict into `content`, server-side schema validation. No key
  promotion anywhere.
- Reference Python client, `mcp/client/session.py:411-441` (same install) —
  `if not result.isError: await self._validate_tool_result(...)`, and validation
  only when `output_schema is not None`. Added in SDK v1.10.0; absent in v1.9.4;
  error string unchanged through current `main`.
- FastMCP, `mcp/server/fastmcp/utilities/func_metadata.py` `convert_result` —
  no `structuredContent` unless a return-type-derived schema exists.
- Upstream TypeScript SDK `callTool` at tag `1.17.0`
  (`src/client/index.ts`) — validates `structuredContent` only when a validator
  exists, and returns `content` untouched. (Current `main` has been restructured
  into a monorepo with a pluggable validator; `callTool` there was not read.)
- Claude Code 2.1.220 (`~/.local/share/claude/versions/2.1.220`), bundled
  TypeScript MCP client — the result normaliser quoted in F5 (text blocks
  discarded when `structuredContent` is present), the `mcpMeta` side channel for
  `_meta`, the `mcp-protocol-version` request header, and the output-schema
  validator quoted in F4. Its latest supported revision is `2025-11-25`.
- This repository, at commit `11563a3` — everything in F1, F2, F6, F7, F10.

**Attributed, not reproducible from this repository:**

- `../actingweb_mcp/thoughts/research/2026-08-03-agent-run-returns-only-run-id.md`
  — the production measurements in F9 (135,151 characters server-side vs.
  `{"run_id": null}` client-side; the affected tool family; the ~42 KB doubled
  bodies). The mechanism they describe is independently verified in F1 and F5;
  the numbers are the consumer's.
- `../actingweb_mcp/thoughts/plans/2026-08-03-agent-run-returns-only-run-id.md`
  — the consumer's migration plan, whose Phase 3 is the library work described
  here. Note that plan defers to *this* document on library detail, so it should
  not be cited back as evidence for library claims.
