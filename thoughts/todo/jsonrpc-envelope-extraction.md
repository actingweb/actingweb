# One JSON-RPC envelope for `/mcp`, `/methods` and `/a2a`

**Filed:** 2026-11-25, by the A2A research
(`thoughts/research/2026-11-24-a2a-actor-interface.reuse.md`, "Exists but
embedded").

Parsing a request and building the error object are written out by hand in
each JSON-RPC handler:
- `handlers/mcp.py:1006-1140, 2180-2188`
- `handlers/methods.py:21, 182-386`

The A2A plan adds a third copy of its own on purpose (decision 9). Moving MCP
or `/methods` onto shared code would touch authentication and dispatch paths
while 4.0 is being checked by consumers.

**Doing it later gives:** one parser with one set of refusals (`-32700`,
`-32600`, batch handling). Each protocol keeps its own error codes, because
A2A's `-32001` to `-32009` differ from MCP's.

**When to do it:** after the A2A core plan lands and 4.0 is final. It needs
each handler's wire behaviour recorded first, by the rule of proving today's
behaviour before changing it.
