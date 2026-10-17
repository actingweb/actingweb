# Threat model: actingweb

## What this project does and where untrusted input enters

ActingWeb is a Python library that applications embed (through the Flask or
FastAPI integration in `actingweb/interface/integrations/`) to serve the
ActingWeb REST protocol. Every user is an **actor** with its own URL
(`/<actor_id>`), its own key/value properties, trust relationships with peers,
subscriptions, and optionally a per-actor MCP server and OAuth2 authorization
server for AI clients.

Treat every HTTP request as untrusted, from any of these principals:

- **Anonymous internet clients**: actor creation (`POST /`), `/<actor_id>/meta`,
  OAuth2 login, callback and SPA token endpoints (`/oauth/*`), MCP dynamic
  client registration, `.well-known` discovery.
- **Peers**: other ActingWeb actors (possibly on other hosts, possibly
  malicious) holding a trust secret as a Bearer token. They call
  `/<actor_id>/properties`, `/trust`, `/subscriptions`, `/callbacks`,
  `/resources`, `/methods`, `/actions`, and send callback/notification payloads.
- **MCP clients**: AI clients holding an OAuth2 access token issued by
  `actingweb/oauth2_server/`, calling `/mcp` (and `/<actor_id>/mcp`).
- **OAuth2 providers' responses** (Google, GitHub, Apple, ...): ID tokens,
  userinfo, email lists. A provider is trusted, but anything relayed through
  the browser (`state`, `code`, `redirect_uri`) is not.
- **The creator**: the actor's owner, authenticated by basic auth (passphrase)
  or an OAuth2 session. The creator is trusted over their own actor only.

Outbound: the library makes HTTP requests to peer URLs that peers supply
(`actingweb/aw_proxy.py`, trust establishment, subscription callbacks,
`fanout.py`) and to OAuth2 provider endpoints. Peer-supplied URLs are an SSRF
surface.

Client-supplied text (MCP `clientInfo`, registration `client_name`,
User-Agent, trust `desc`) is stored, logged and returned, and may end up in
an LLM's context.

## Security properties we care about

1. **Actor isolation.** No principal may read or change another actor's data.
   An authenticated principal on actor A must never be treated as authorized
   on actor B.
2. **Authorization on trust permissions.** A peer or MCP client sees only what
   its trust type and per-relationship permissions allow
   (`permission_evaluator.py`, `trust_permissions.py`). Explicit deny > explicit
   allow > trust-type allow > default deny. Missing or unresolvable trust
   fails closed.
3. **Credential secrecy.** Trust secrets, verification tokens, OAuth2 access and
   refresh tokens, authorization codes, client secrets and the creator
   passphrase are never returned to the wrong principal, logged, or
   compared in non-constant time.
4. **OAuth2 correctness.** `state` validated, authorization codes single-use,
   PKCE `S256` enforced on the built-in authorize pages, refresh tokens
   single-use with rotation-family reuse detection, redirect URIs validated
   against registration, ID tokens verified (signature, `iss`, `aud`, `exp`,
   nonce), only verified emails used for account linking.
5. **Token-store faults fail closed** (503), never as "valid" or as a false
   "logged out".
6. **No injection** into DynamoDB/PostgreSQL queries, Jinja2 templates, logs,
   or HTTP headers/redirects (open redirect via `Location`).

## Components that matter most / least

Most important:

- `actingweb/auth.py`, `actingweb/secret_compare.py`, `actingweb/permission_*`,
  `actingweb/trust*.py`, `actingweb/peer_permissions.py`
- `actingweb/oauth2*.py`, `actingweb/oauth_*`, `actingweb/single_use.py`,
  `actingweb/oauth2_server/`, `actingweb/handlers/oauth2_*.py`,
  `actingweb/handlers/callback_oauth.py`
- `actingweb/handlers/` (all request handlers, sync and async) and
  `actingweb/interface/integrations/` (route wiring, request/response mapping)
- `actingweb/handlers/mcp.py`, `actingweb/handlers/async_mcp.py`, `actingweb/mcp/`
- `actingweb/aw_proxy.py`, `actingweb/fanout.py`, `actingweb/callback_processor.py`,
  `actingweb/subscription*.py` (outbound requests, peer-supplied payloads)
- `actingweb/db/` (both backends; query construction and the lookup tables)

Less important but in scope: `actingweb/templates/` (XSS in the built-in web
UI), `actingweb/maintenance/` (admin CLIs run by operators).

Out of scope:

- `actingweb/handlers/devtest.py` and anything reachable only with
  `with_devtest(enable=True)`. Devtest is documented as never-in-production
  and skips authorization checks by design. (A devtest route answering when
  devtest is *disabled* is in scope.)
- `examples/` (a reference/demo app), `tests/`, `docs/`, `thoughts/`, `skills/`.
  The demo's `/nuke` route is disarmed unless `NUKE_SECRET` is set.
- Misconfiguration the docs explicitly warn against (plain `http://` in
  production, `AWS_DB_HOST` pointing somewhere untrusted, disabling OAuth2
  while exposing the web UI, a custom hook that returns data it should not).
- Issues in dependencies (Flask, FastAPI, PynamoDB, psycopg, PyJWT, ...)
  unless ActingWeb uses them unsafely.
- The documented 300-second per-process MCP token cache after revocation
  (`docs/reference/security.rst`, "Revocation is per process").

## How to exercise it

- Start the test databases with `aw-test-services` (DynamoDB Local on :8001,
  PostgreSQL on :5433; the image's environment is already set up for both).
- Unit tests: `poetry run pytest tests/ --ignore=tests/integration --ignore=tests/performance -m "not benchmark" --no-cov`
- Integration tests start a real server on `:5555` and drive it over HTTP:
  `poetry run pytest tests/integration --no-cov` (DynamoDB) and
  `DATABASE_BACKEND=postgresql poetry run pytest tests/integration --no-cov`.
  Run one test run at a time (they share the port and database prefix).
  `tests/integration/conftest.py` shows how to build an app and actors; it is
  the quickest base for a reproducer.
- `examples/demo/application.py` is a full Flask application using the library.

## How we rate severity

- **Critical**: unauthenticated or cross-actor read/write of another actor's
  properties, trust or tokens; authentication bypass on any actor route,
  `/mcp` or the OAuth2 server; token forgery; RCE.
- **High**: a peer or MCP client escaping its trust permissions on the same
  actor (reading or writing what its trust type denies); OAuth2 flaws that
  allow account linking/takeover or code/token theft (state, PKCE, redirect
  URI, ID-token validation); secrets or tokens leaked in responses or logs;
  SSRF that reaches internal networks from a peer-supplied URL; injection
  into a database query.
- **Medium**: stored XSS in the built-in web UI; open redirects; refresh-token
  reuse detection or revocation that can be defeated; fail-open behaviour on
  a store fault; timing-unsafe secret comparison; unauthenticated
  resource-exhaustion that needs only one or a few requests.
- **Low**: information disclosure of non-secret metadata (actor existence,
  trust-type names), volumetric DoS, hardening suggestions.

Bugs that need the creator's own credentials to affect only the creator's own
actor are low unless they cross into another actor or the host.

## How reports and patches should look

A reproducer as a pytest test in the style of `tests/integration/` (using the
fixtures there) is ideal. Patches should keep type hints on every function and
pass `poetry run pyright actingweb tests` and
`poetry run ruff check actingweb tests`. Say which backend(s) are affected;
both DynamoDB and PostgreSQL must keep working.
