# Threat model: actingweb

## What this project does

ActingWeb is a Python library that applications embed (through the Flask or
FastAPI integration in `actingweb/interface/integrations/`) to implement the
**ActingWeb protocol**, specified publicly in
`docs/protocol/actingweb-spec.rst` (version 1.4). Read the spec first: it is
the reference for intended behaviour. A deviation from a spec MUST/MUST NOT
that weakens authentication or authorization is a finding; behaviour the spec
itself requires (listed below) is not.

Each user or device is an **actor**: one instance of a mini-application with
its own root URI (`/<actor_id>`), holding "small pieces of sensitive data on
behalf of a user" (spec, Abstract). Actors share that data with each other
only through trust relationships. On top of the protocol, the library adds
OAuth2 login for the actor's owner, an OAuth2 authorization server and a
per-actor MCP server for AI clients, SPA/mobile session tokens, and a web UI.

## Principals, from most to least trusted

| Principal | How it authenticates | What the spec allows it |
|---|---|---|
| **creator** | HTTP basic auth with the username and passphrase given at actor creation (default username `creator`), or the owner's OAuth2 session | Everything on that one actor, same as `admin` |
| **admin** peer | Bearer token = the relationship's shared secret | Full access to the actor, including deleting it and reading other relationships' secrets |
| **trustee** | The creator passphrase as a bearer token, only when the creator username is `trustee` and the passphrase is > 80 bits | `/trust`, `/subscriptions` and the actor root only |
| **partner / friend / associate / custom** peers | Bearer token = the relationship's shared secret | What the trust type plus per-relationship permission overrides allow (`permission_evaluator.py`). Default deny |
| **MCP client** | OAuth2 access token from `actingweb/oauth2_server/`, bound to one actor and one trust row (`mcp_client`) | Same trust/permission rules as REST (spec, /mcp "Normative Requirements" 2 and 4) |
| **pending or denied peer** | Bearer token of a relationship that is not approved | Only polling the status of its own relationship |
| **anonymous** | none | See "Behaviour the spec requires" below |

Peers can be on other hosts and can be malicious. They choose their own
`id`, `baseuri`, `type`, `desc` and `secret` when they request trust.

## Behaviour the spec requires (not a vulnerability)

- **Anonymous actor creation**: `POST` to the factory URL creates an actor and
  sets its creator credentials (spec, "Instantiation of Actors").
  Mass-creation DoS is Low.
- **Anonymous `/meta`**: id, type, version, description and supported options
  are public.
- **Anonymous trust requests**: `POST /<actor_id>/trust/<type>` carries no
  authentication. The requester supplies `baseuri`, `id` and `secret`. The
  actor may call back to `baseuri` to verify the requester.
- **Anonymous `POST` to some `/callbacks` paths**: the spec allows callbacks
  from non-ActingWeb applications. The library still has to tie a callback
  attributed to peer X to X's shared secret before acting on it.
- **creator and admin can read shared secrets** on the per-relationship
  `GET /trust/<type>/<peerid>`. The list endpoints must not return them.
- **admin and creator have full access**, including deleting the actor.
  Anything an admin peer or the creator does to their own actor is not a
  finding.
- **Auto-approval** of the default relationship type when the application sets
  `auto_accept_default_relationship` (default off). Approval policy beyond
  that is the application's.
- **Property values are not semantically checked** ("actors MUST NOT apply
  any logic or process on semantics"). Values are untrusted, and an
  application that uses one unsafely has its own bug. A library code path
  that uses one unsafely (template, query, log, redirect) is in scope.
- **`/methods` may change state on `GET`** (spec, /methods).

## Invariants to attack

These follow from the spec. Breaking any of them is a finding.

1. **Actor isolation.** Credentials valid on actor A grant nothing on actor B.
   This applies to creator credentials, peer secrets, OAuth2/MCP/SPA tokens
   and cached auth or trust state.
2. **Peer binding.** A bearer secret authenticates as exactly one peer. A
   request naming peer Y in the path (`/subscriptions/<Y>`,
   `/trust/<type>/<Y>`, `/callbacks/permissions/<Y>`,
   `/callbacks/subscriptions/<Y>/...`) is refused unless the token is Y's
   (spec, Subscriptions: "MUST validate that the bearer token is valid for
   the peer specified in the POST URI").
3. **No trust hijack.** An actor holds at most one relationship per peer
   (spec, "Types of Relationships"). An anonymous trust request naming an
   existing peer's `id` must not replace that peer's secret, `baseuri`,
   relationship type or approval.
4. **Approval is authenticated and owned.** Only the actor's creator, admin or
   trustee (or the configured auto-approval) can approve a relationship. A
   peer cannot set its own `approved`, raise its relationship type, or edit
   its own permission overrides. The approval notification (`POST` to the
   reverse trust URI) must carry the relationship's secret.
5. **Pending and denied relationships grant nothing** beyond polling their own
   status.
6. **Verification is real.** `verified` becomes true only when the peer
   returns the `verificationToken` the actor sent, over the authenticated
   reverse `GET`.
7. **Trustee limits.** The passphrase works as a bearer token only when the
   creator username is `trustee` and the passphrase is > 80 bits. It then
   reaches only `/trust`, `/subscriptions` and the root.
8. **Permissions hold over time.** A subscriber needs read permission on the
   path when subscribing. Diffs, low-granularity URLs, resync callbacks and
   permission callbacks must not deliver data the peer is no longer allowed
   to read after a revocation, nor data from outside the subscribed path.
9. **Secrets stay secret.** Shared secrets, verification tokens, the
   passphrase, OAuth2 codes and tokens, and client secrets are never returned
   to the wrong principal, logged, or compared in non-constant time
   (`secret_compare.py`).
10. **MCP equals REST.** An MCP tool, resource or prompt never reaches data or
    actions that the same trust row could not reach over REST.

## Outbound requests (SSRF surface)

The actor makes HTTP requests to URLs that peers or anonymous callers choose:
the trust-verification `GET` to a requester's `baseuri`, approval
notifications, subscription callbacks and fan-out (`fanout.py`,
`callback_processor.py`), peer proxy calls (`aw_proxy.py`), and the
"initiate trust" `POST /<actor_id>/trust` with a `url`. Reaching
loopback, link-local or cloud-metadata addresses, or internal services,
through these is in scope. So is a response that is reflected back to the
caller or followed through redirects.

## Library features beyond the spec

These are implementation-defined and in scope:

- OAuth2 login for the actor's owner: `oauth2*.py`, `oauth_*`,
  `handlers/oauth2_*.py`, `handlers/callback_oauth.py`. Checks: `state`,
  redirect URIs, ID-token validation, and that only verified emails link
  accounts.
- The OAuth2 authorization server for MCP clients: `oauth2_server/`, dynamic
  client registration, single-use codes, PKCE `S256`, refresh-token rotation
  with reuse detection, revocation.
- SPA/mobile tokens: `handlers/oauth2_spa.py`, `oauth_session.py`,
  `single_use.py`.
- MCP: `handlers/mcp.py`, `handlers/async_mcp.py`, `mcp/`.
- The built-in web UI: `templates/`, `handlers/www.py`. Look for XSS, CSRF
  and open redirects.
- Storage: `db/` (both backends) and the property lookup tables.

`docs/reference/security.rst` lists the guarantees the library documents for
these (for example "a token-store fault fails closed").

## Out of scope

- `handlers/devtest.py` and anything reachable only with
  `with_devtest(enable=True)` (documented as never-in-production). A devtest
  route that answers while devtest is disabled **is** in scope.
- What `/actions`, `/methods` and `/resources` *do*. The library owns the
  routing, authentication, permission checks and dispatch for these paths
  (in scope). The application supplies the behaviour through
  `@app.action_hook`, `@app.method_hook` and callback hooks, and that code is
  the application's.
- Spec features the library has no route for: `/sessions` and agent/proxy
  request forwarding (`proxied` subscriptions). An application that adds its
  own route for one of these owns that route's authentication.
- `examples/`, `tests/`, `docs/`, `thoughts/`, `skills/`.
- Misconfiguration the docs warn against: plain `http://` outside a
  controlled network (the spec allows it there), `AWS_DB_HOST` pointing
  somewhere untrusted, a weak creator passphrase chosen by the caller, or an
  application hook that returns data it should not.
- The documented 300-second per-process MCP token cache after revocation.
- Dependency bugs (Flask, FastAPI, PynamoDB, psycopg, PyJWT, ...) unless
  ActingWeb uses the dependency unsafely.

## How to exercise it

- Start the test databases with `aw-test-services` (DynamoDB Local on :8001,
  PostgreSQL on :5433). The image's environment is already set up for both.
- Unit tests: `poetry run pytest tests/ --ignore=tests/integration --ignore=tests/performance -m "not benchmark" --no-cov`
- Integration tests start a real server on `:5555`:
  `poetry run pytest tests/integration --no-cov`, or with
  `DATABASE_BACKEND=postgresql` for PostgreSQL. Run one test run at a time.
- `tests/integration/` already drives two-actor flows (trust request,
  verification, approval, subscriptions, callbacks). Its `conftest.py` is the
  quickest base for a reproducer that plays a malicious peer.
- `examples/demo/application.py` is a full Flask application.

## How we rate severity

- **Critical**
  - Breaking invariants 1–4 without credentials, or with only a low-trust
    peer's credentials. Examples: cross-actor access, acting as another peer,
    hijacking a relationship, self-approval or escalation to `admin`.
  - Authentication bypass on any actor route, `/mcp` or the OAuth2 server.
  - Token or code forgery.
  - RCE.
- **High**
  - A peer or MCP client reading or writing beyond its trust permissions on
    the same actor, including after revocation (invariants 5, 8 and 10).
  - Escalation between regular trust types.
  - OAuth2 flaws that allow account linking or takeover, or code or token
    theft.
  - Secrets leaked in responses or logs (invariant 9).
  - SSRF to internal addresses with a readable response.
  - Injection into a database query.
- **Medium**
  - Blind SSRF.
  - Stored XSS or CSRF in the built-in web UI.
  - Open redirects.
  - Defeating refresh-token reuse detection or revocation.
  - Fail-open on a store fault.
  - Timing-unsafe secret comparison.
  - Setting `verified` without real verification (invariant 6).
  - Single-request resource exhaustion.
- **Low**
  - Disclosure of non-secret metadata (actor existence, trust-type names,
    peer ids).
  - Volumetric DoS, including mass actor creation or mass trust requests.
  - Hardening suggestions.

A bug that needs creator or admin credentials and only affects that same
actor is Low, unless it crosses into another actor or the host.

## How reports and patches should look

A reproducer as a pytest test in the style of `tests/integration/` (using the
fixtures there) is ideal. Name the invariant or the spec section the bug
breaks. Patches keep type hints on every function and pass
`poetry run pyright actingweb tests` and `poetry run ruff check actingweb tests`.
Say which backend(s) are affected; both DynamoDB and PostgreSQL must keep
working.
