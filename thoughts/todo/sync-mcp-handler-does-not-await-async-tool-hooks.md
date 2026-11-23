# The sync MCP handler answers an `async def` tool with its coroutine

**Filed:** 2026-11-23, found while implementing
`thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md` (its
tests for an async tool had to skip the sync handler). Unverified beyond
the handler; behaviour of 4.0.0rc2.

`MCPHandler._handle_tool_call` calls `hook(actor, action_name, arguments)`
and formats what it returns. For an `async def` hook that is a coroutine
object: the tool never runs, the result's text is the coroutine's `repr`,
and Python warns "coroutine ... was never awaited". The async handler
checks `inspect.iscoroutinefunction` and awaits.

First: whether the Flask integration can reach this (an application that
registers an async tool and serves `/mcp` through Flask). If it can, either
run the coroutine to completion there or refuse the tool at registration or
at the call with a clear error. The same check for prompt and resource
hooks.
