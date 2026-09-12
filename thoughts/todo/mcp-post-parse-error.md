# `POST /mcp` treats a body that is not JSON as `{}` instead of a parse error

Raised by the automated Claude review on PR #145 as pre-existing and out of
that PR's scope. Verified against the tree on 2026-09-12.

## What is wrong

Both integrations' `_handle_mcp_request`
(`actingweb/interface/integrations/fastapi_integration.py`,
`actingweb/interface/integrations/flask_integration.py`) parse the body with
`json.loads` and, on `json.JSONDecodeError` / `ValueError`, pass `data = {}`
to the handler. An empty body also becomes `{}`.

`{}` has no `method` and no `id`, so it runs through version resolution and
authentication: an unauthenticated caller gets the `401` challenge, an
authenticated one gets `-32601 Method not found: None`. JSON-RPC 2.0 says
invalid JSON is `-32700 Parse error` with `id: null`.

## What doing it buys

A malformed request is reported as malformed, which is what a client author
debugging their transport needs. No known client sends invalid JSON.

## What has to be decided first

- **Before or after authentication.** Answering `400`/`-32700` ahead of the
  auth check means an unauthenticated POST with a broken or empty body stops
  receiving the `401` + `WWW-Authenticate` challenge that MCP clients use for
  authorization discovery. Whether any client probes discovery with an empty
  POST decides whether that is safe.
- **Empty body.** Whether an empty body is a parse error (`-32700`) or an
  invalid request (`-32600`), or keeps its current route to the challenge.
- **Where.** The parse lives in both integrations, so the fix is either a
  sentinel passed to the handler — which already rejects non-object bodies
  in `MCPHandler._reject_non_object_body` — or the same branch in both
  integrations.
