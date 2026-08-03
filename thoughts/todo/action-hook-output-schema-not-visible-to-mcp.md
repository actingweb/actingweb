# `output_schema` on `action_hook` never reaches MCP

Found during review of PR #119 (`chatgpt-codex-connector`, P2). Documented in
`v3.13.0rc4`; the underlying asymmetry is unfixed.

## What happens

A hook's schema can be supplied three ways, and only one of them reaches MCP:

| How the schema is supplied | `get_hook_metadata` | `get_mcp_metadata` → `tools/list` |
| --- | --- | --- |
| `@app.action_hook(..., output_schema=S)` | `S` | **`None`** |
| Return-type `TypedDict` annotation (auto) | derived | **`None`** |
| `@mcp_tool(output_schema=S)` | `S` | `S` |

Verified empirically at commit `695a870`. `mcp.py`'s `tools/list` loop and the
`tools/call` dispatch both read `get_mcp_metadata(hook)`
(`actingweb/mcp/decorators.py:199-205`), which returns `_mcp_metadata` — set
only by `@mcp_tool`. `action_hook` writes a separate `HookMetadata` to
`_hook_metadata` (`actingweb/interface/hooks.py:1489`), and the TypedDict
auto-derivation happens inside `get_hook_metadata`
(`actingweb/interface/hooks.py:195`). Nothing bridges the two.

Consequence: an author who declares `output_schema` on the action hook, or who
annotates a `TypedDict` return type, reasonably believes their MCP tool
advertises `outputSchema`. It does not, and the rc4 missing-`structuredContent`
warning stays silent for them too, because it is gated on the same metadata.

## Why rc4 documented it rather than fixed it

Merging the two would **newly advertise `outputSchema`** for every MCP tool with
a `TypedDict` return annotation. Every one of those that does not also return
`structuredContent` would immediately start failing on spec-conforming clients
with `Tool X has an output schema but did not return structured content` — the
exact failure mode rc4 exists to warn about. That is a breaking change to a
population that is currently working, and it does not belong in a release whose
point is to make one behaviour predictable.

## Options

1. **Leave as is, documented.** Current state. Cost: the ergonomic trap
   persists, and the two decorators keep diverging.
2. **Merge, opt-in.** e.g. `@mcp_tool(inherit_hook_schema=True)`. Safe, but adds
   API surface for something `@mcp_tool(output_schema=...)` already expresses.
3. **Merge by default, behind a major/minor boundary**, paired with real
   server-side validation so a schema mismatch is caught before it reaches a
   client. This is the same work as research option C in
   `thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
   (D1/option C) and should be decided together with it.
4. **Warn at `tools/list`** when `_hook_metadata` has an `output_schema` and
   `_mcp_metadata` does not — cheap, catches the confusion at registration
   rather than at call time. Note the rc4 decision to keep the *missing
   structured content* warning off `tools/list` does not apply here: this
   condition is knowable at listing time and cannot false-positive.

Option 4 is the cheapest real improvement and is independent of the rest.

## Related

- `thoughts/plans/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
- `thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
  (F7 — the two halves of the `outputSchema` ⇄ `structuredContent` contract were
  implemented a day apart and never wired together; this is a third disconnected
  half)
