# MCP tasks on the actor task store

**Filed:** 2026-11-25, by the A2A research (tasks note
`thoughts/research/2026-11-24-a2a-actor-interface.tasks.md`, "MCP tasks";
main note, owner decisions 11–16).

The A2A work builds a general actor task store, a worker handle, a task
token and a `task_dispatch` hook. MCP's long-running tasks can use the same
store, with `/mcp` as one more way to create a task.

## What to build

- **Which MCP version: only the 2026-07-28 extension**
  `io.modelcontextprotocol/tasks`.
  - The server decides per `tools/call` whether to return a task; for
    example, the tool's hook is one that hands off to a worker.
  - The methods are `tasks/get`, `tasks/update` and `tasks/cancel`. There
    is no blocking `tasks/result` and no `tasks/list`.
- **Who owns a task:** the MCP client's trust peer id is the task's origin,
  so each client sees only its own tasks. Deleting the client deletes its
  tasks.
- **Status mapping:** the store's internal status set maps to MCP's
  `working`, `input_required`, `completed`, `failed` and `cancelled`.
  `ttlMs` reports the store's expiry.
- **Headers:** `Mcp-Name` carries `taskId` on the task methods (Streamable
  HTTP).

## Not this

- **The experimental 2025-11-25 tasks design.**
  - Its `tasks/result` must block until the task ends, which fails on
    serverless for minute-long work.
  - It needs a listing.
  - Upstream replaced it with a design that is not wire-compatible.

## Waiting on

- **Dual-era support:** `mcp-2026-07-28-dual-era-support.md`. The extension
  exists only under the 2026-07-28 revision.
- **The A2A long-running-tasks plan:** it provides the store and the handle.
- **`input_required`:** needs the store's input-request support, which the
  first A2A round may leave out.
