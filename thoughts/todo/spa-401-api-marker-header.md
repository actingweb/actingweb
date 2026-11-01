# The SPA token endpoint's 401 carries nothing that tells it from a gateway's

**Filed:** 2026-11-01, from the consumer's todo
`../actingweb_mcp/thoughts/todo/client-401-api-marker.md` (their #150, left
by the Codex review of their 2026-10-29 fillers branch) and the ask in
`actingweb-3-16-pin.md` there to carry the library half in 3.16, since 3.16
already touches the SPA token path. Verified against `99b2885`.

## What happens

The SPA guide tells a client to treat a `401` on the refresh grant as final
and sign the user out (`docs/guides/spa-authentication.rst`, "Refreshing
reliably on native and mobile clients", rule 7). The consumer learned the
hard way that not every 401 that reaches the client is ours: a captive
portal's page, a tunnel's error page, or a gateway in front of the API
answering its own `{"error": "unauthorized"}`. Its client now reads a 401
as the API's only when the body is JSON with an `error` or `detail` key
(`frontend/src/auth/apiEnvelope.ts`, `isApi401`), which a JSON-answering
gateway still passes, so such a gateway can end a session.

The library's SPA 401s are all `_json_error(401, ...)` in
`actingweb/handlers/oauth2_spa.py` (the refresh grant, the reuse response,
the token exchanges, the passphrase grant, the native grants) and carry no
header a client could key on: no `WWW-Authenticate`, nothing of ours. The
MCP endpoint's 401s do carry `WWW-Authenticate` (RFC 9728), but a proxy
can send that too.

## What a fix is

A response header only the library sets on its own 401s from the SPA token
endpoints, documented in the SPA guide as the thing a client checks instead
of the body. Shape, undecided:

- Name. `X-ActingWeb-Error: <code>` (a stable machine code next to the
  message, which is prose and has changed) would double as the error code
  the JSON body lacks; a bare `X-ActingWeb-Auth: 1`-style marker is the
  minimum. Decide whether every `_json_error` on the SPA endpoints carries
  it or only the 401s.
- Exposure. The header must be in `Access-Control-Expose-Headers`, which
  `spa_cors_headers()` (`oauth2_spa.py`) and the fault handler's
  `_cors_for()` (`interface/integrations/_errors.py`) set to `Retry-After`
  today, or a cross-origin native client cannot read it. The consumer also
  adds it to API Gateway's exposed headers (`serverless.yml`); that half is
  theirs.
- Whether `auth.py`'s own 401 (`response["code"] = 401`, the basic-auth
  and Bearer rejections on actor routes) carries it too. The consumer's
  own routes and its redirect-required handler are its own.

Additive and small (hours), but it changes a response shape the SPA guide
documents, so a minor. The consumer's `isApi401` then checks the header.

## Why not urgent

Fails toward a sign-out, not toward a security hole; needs a network with a
JSON-answering gateway. No report of one in production.
