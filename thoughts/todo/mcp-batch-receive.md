# MCP batches are declined, but protocol 2025-03-26 requires receiving them

Found while fixing the `POST /mcp` array-body crash. Verified against the spec
text and the tree on 2026-09-12.

## What is wrong

`MCPHandler.post` and `AsyncMCPHandler.post_async` answer any body that is not
a single JSON object — a JSON-RPC batch array above all — with HTTP `400` and
`-32600 Invalid Request`, via `MCPHandler._reject_non_object_body` in
`actingweb/handlers/mcp.py`.

That is correct for 2025-06-18 and later, which removed batching (spec
changelog item 1, PR #416). It is not correct for 2025-03-26, whose base
protocol page says: *"MCP implementations **MAY** support sending JSON-RPC
batches, but **MUST** support receiving JSON-RPC batches."*
`SUPPORTED_PROTOCOL_VERSIONS` in `actingweb/mcp/protocol.py` still lists
2025-03-26, and a request with no `MCP-Protocol-Version` header is treated as
2025-03-26 — so a header-less client is exactly the one the requirement covers.

No client we serve is known to send batches. Before this was declined it
crashed with a `500`, and nobody reported that.

## What doing it buys

Full conformance with a revision the server advertises. Nothing else: a client
that does not batch is unaffected either way.

## What has to be decided first

Either implement receiving, or stop claiming the revision:

- **Implement.** Dispatch each element through the existing per-message path
  and return the array of non-empty replies. Open questions: the HTTP status
  when elements disagree — one needs the `401` + `WWW-Authenticate` challenge,
  another succeeded; `202` with no body when every element is a notification or
  a client response; a single `-32600` for an empty array; whether a batch is
  still rejected when the header names 2025-06-18 or later. `post` and
  `post_async` duplicate their dispatch, so both need it.
- **Stop claiming it.** Drop 2025-03-26 from `SUPPORTED_PROTOCOL_VERSIONS`.
  This changes what `initialize` negotiates and what a header-less request is
  assumed to speak, so it is a compatibility decision, not a patch.
