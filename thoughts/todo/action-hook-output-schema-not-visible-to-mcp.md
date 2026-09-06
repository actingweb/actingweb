# `output_schema` on `action_hook` never reaches MCP

## What happens

A hook's schema can be supplied three ways, and only one of them reaches MCP:

| How the schema is supplied | `get_hook_metadata` | `get_mcp_metadata` → `tools/list` |
| --- | --- | --- |
| `@app.action_hook(..., output_schema=S)` | `S` | **`None`** |
| Return-type `TypedDict` annotation (auto) | derived | **`None`** |
| `@mcp_tool(output_schema=S)` | `S` | `S` |

`mcp.py`'s `tools/list` loop and the `tools/call` dispatch both read
`get_mcp_metadata(hook)` (`actingweb/mcp/decorators.py`), which returns
`_mcp_metadata` — set only by `@mcp_tool`. `action_hook` writes a separate
`HookMetadata` to `_hook_metadata` (`actingweb/interface/hooks.py`), and the
TypedDict auto-derivation happens inside `get_hook_metadata`. Nothing bridges
the two.

Consequence: an author who declares `output_schema` on the action hook, or who
annotates a `TypedDict` return type, reasonably believes their MCP tool
advertises `outputSchema`. It does not, and the missing-`structuredContent`
warning stays silent for them too, because it is gated on the same metadata.

**A `tools/list` warning already covers the confusion**
(`_warn_hook_output_schema_not_advertised_once()` in
`actingweb/handlers/mcp.py`, once per tool per process, both the explicit
`output_schema=` and the TypedDict cases). It tells an author their schema is
not advertised; it does not advertise it. Don't add a second warning — the
asymmetry is what is left.

## Why merging them by default is not a free fix

Merging would **newly advertise `outputSchema`** for every MCP tool with a
`TypedDict` return annotation. Every one of those that does not also return
`structuredContent` would immediately start failing on spec-conforming clients
with `Tool X has an output schema but did not return structured content`. That
is a breaking change to a population that is currently working.

## The two remaining options

1. **Merge, opt-in** — e.g. `@mcp_tool(inherit_hook_schema=True)`. Safe, but
   adds API surface for something `@mcp_tool(output_schema=...)` already
   expresses.
2. **Merge by default, behind a major/minor boundary**, paired with real
   server-side validation so a schema mismatch is caught before it reaches a
   client. This is the same work as option C in
   `thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
   and **should be decided together with it**, not taken as a side effect of
   something else.

## Related

- `thoughts/plans/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
- `thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
  (F7 — the two halves of the `outputSchema` ⇄ `structuredContent` contract were
  implemented a day apart and never wired together; this is a third disconnected
  half)
