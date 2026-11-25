# Research: A2A credentials, an API key and OAuth2 for third-party clients

**Date:** 2026-11-25
**Feature:** thoughts/features/2026-11-24-a2a-actor-interface.md
**Companion to:** `2026-11-24-a2a-actor-interface.md` (main note), `.tasks.md` and `.reuse.md`
**Branch:** master
**Commit:** a74ae35

## Why this note exists

The owner set the direction on 2026-11-25. A user should be able to create an
A2A client in a consumer app and generate credentials for it, the way MCP
clients get a client id, a secret and a token today. If A2A supports OAuth2,
that path should be supported too. It uses **new trust types, not the
`mcp_client` ones**, because an A2A client is a third party granted access to
communicate with the actor. It never acts as the actor.

This refines the main note's table of who each surface's caller is. The
`/a2a` row said "never OAuth2-authorised to act for the actor". A2A callers
may now hold OAuth2 credentials, but always as a third party, on trust types
of their own.

The note answers two questions:
1. How does A2A 1.0 handle authentication?
2. What in the library's OAuth2 server can issue such clients?

## What A2A 1.0 says

### Security schemes

The Agent Card declares `securitySchemes`, modelled on the OpenAPI 3.2
Security Scheme Object (§4.5.1). There are five kinds:
- an API key, in a header, query or cookie
- HTTP auth, for example `Bearer`
- OAuth2
- OpenID Connect
- mutual TLS

**An OAuth2 scheme carries exactly one flow** (§4.5.7):

| Flow | Notes |
| --- | --- |
| `authorization_code` | Carries `pkce_required`; PKCE "is recommended for all clients" |
| `client_credentials` | |
| `device_code` | |
| `implicit` and `password` | Deprecated, though they are still in the proto on main |

An OAuth2 scheme may also carry `oauth2_metadata_url` (RFC 8414).

**`securityRequirements`:**
- It is a list of maps from a scheme to its scopes. Third-party code reads the
  list as "any one of" and each map as "all of" **[inference; the spec text
  read does not say so]**.
- The proto calls the field `securityRequirements`. Some prose and topic pages
  still say `security`.

### Getting credentials is outside the protocol

- §7.3 says the client "obtains the necessary credentials through an
  out-of-band process specific to the required authentication scheme".
- The only links to discovery are the scheme fields themselves
  (`oauth2MetadataUrl`, `openIdConnectUrl`).
- No dynamic client registration appears in the spec text read. Some vendors
  add it themselves:
  - Atlassian's A2A gateway requires it.
  - Gemini Enterprise registers itself through the Marketplace.

### Authentication happens at the transport

- Credentials travel in headers on every request (§7.3), for example
  `Authorization: Bearer` (§9.2).
- The server "MUST authenticate every incoming request" (§7.4) and "SHOULD
  provide relevant authentication challenge information".
- 401 and 403 appear only as examples (§3.3.2). The non-normative
  enterprise-ready page gives the guidance:
  - 401 when credentials are missing or invalid, with `WWW-Authenticate`
  - 403 when the credentials are valid but don't permit the request
- The a2a-js client retries on 401 and 403.

### The extended card

- It uses the same schemes as every other call (§3.1.11), and it "MUST
  require authentication" (§13.3).

### `TASK_STATE_AUTH_REQUIRED`

- This state is for a downstream credential the agent needs, for example a
  token to call another API (§7.6).
- It is not a way to sign in to the agent. The spec says it is not, "by
  itself, as authorization".

### Who the principal is

- The spec doesn't define one. A topic page says the authenticated identity
  "could represent an end user, a client application, or both".
- Only vendors tell an agent acting as itself apart from one acting for a
  user, for example Foundry's "app-only" call versus its on-behalf-of-user
  call.

### What real callers can send

| Caller | Credentials it can use |
| --- | --- |
| Copilot Studio | None, an API key, or OAuth 2.0 (client id and secret, authorise, token and refresh URLs); 0.3-era names |
| Azure AI Foundry | A key header, an Entra agent or managed identity, user delegation, OAuth passthrough with per-user consent; `a2a_version: "1.0"` |
| Gemini Enterprise | Per-user OAuth (authorization code), or a Cloud Run identity token. No API key. It ignores the card's security fields. |
| a2a-python, a2a-js | Attach a credential the application already holds (a bearer, OAuth2 or OIDC as a bearer, or an API key in a header). They implement no OAuth flow. |

None of these callers offers a generic OAuth `client_credentials` option as a
first-class choice **[inference from three vendors]**. The common ground is
two things:
- a static key or bearer
- per-user authorization code with consent

## What the library has (verified by reading, 2026-11-25)

### The OAuth2 server

- **Grants the token endpoint accepts**
  (`oauth2_server/oauth2_server.py:622-851`):
  - `authorization_code`, with PKCE
  - `refresh_token`, with rotation and theft detection
  - `client_credentials`: only for clients an owner created, never for
    clients on the system actor (`824-828`). It mints a 1-hour `aw_` token
    with no refresh token (`token_manager.py:1713-1781`).
- **Metadata:** the server metadata leaves `client_credentials` out on purpose
  (`oauth2_server.py:874-880`).
- **Scope and audience:**
  - The scope is hard-coded `"mcp"` (`token_manager.py:399, 659, 1008, 1033`).
    Over HTTP, `client_credentials` never takes a scope from the request
    (`oauth2_endpoints.py:426-434`).
  - No `resource` or audience is bound to a token.
  - **Nothing checks scope.**

### Owner-created clients

`OAuth2ClientManager.create_client` → `MCPClientRegistry.register_client`
(`interface/oauth_client_manager.py:40-105`, `client_registry.py:66-204`).

- **Id and secret:** the id is `mcp_<32 hex>` and the secret is
  `token_urlsafe(32)`.
- **Storage:**
  - The record goes in the actor's `mcp_clients` bucket.
  - An index row `client_id → actor_id` goes on the system actor.
- **Trust type:** the default is `mcp_client`. The owner path doesn't check
  that the type is acceptable for clients.
- **A token for the owner to hand over:** `generate_access_token`
  (`oauth_client_manager.py:377-435`) mints a 1-hour token directly.
- **Prefix checks:** `generate_access_token` and `regenerate_client_secret`
  refuse ids without the `mcp_` prefix (`401`, `281`).

### How a client's trust row is written

`create_or_update_oauth_trust` (`interface/trust_manager.py:555-889`).

- **Peer id:** `oauth2_client:<client_id>:<client_id>` for a registered
  client.
- **Fields:**
  - `established_via="oauth2_client"`
  - `peer_type="mcp"`
  - an empty `baseuri`
  - `approved=True`
  - the tag `oauth_client_id`
  - a fresh row secret, which is never returned to anyone

### Classification has two meanings mixed in one list

`OAUTH2_SOURCES` (`oauth2_server/trust_lookup.py:15`) is used for two
different things:

**Mechanical: a row the library made, with no endpoint.**
- `is_valid_peer_id` refuses these prefixes from peers (`trust.py:17-37`).
- `_has_peer_endpoint` (`actor.py:71-85`).
- `delete_reciprocal_trust` skips the remote DELETE for them
  (`actor.py:3292-3346`).
- `is_oauth2_peer` skips the permission callback
  (`trust_permissions.py:169-177`).
- The client sweeps in `Trust.delete` (`trust.py:200-266, 311-365`), which
  need the `mcp_` prefix.
- `client_trusts_for_deletion`.

**Client semantics: a caller acting on the actor's behalf.**
- **`is_client_peer` → `override_applies`**
  (`trust_permissions.py:163-189`): a client's override applies only when it
  names the row's type.
- **`_is_client_row` → `GrantSnapshot.is_client` → `decide`**
  (`permission_evaluator.py:414-416, 906`; `access_decision.py:183, 220-221`):
  a client **never reaches `acl_rules`**. Owner decision 6 admits A2A callers
  through `acl_rules`, so an A2A row must stay out of this set.
- **`find_client_trust`** (`trust_lookup.py:94-120`): arm 1 resolves a row by
  the `oauth_client_id` tag alone, with no source check. `/mcp` would
  therefore resolve any row carrying the tag.

### Token validation

- **`validate_access_token`** (`token_manager.py:405-441`) checks the prefix,
  the index and the expiry, and returns `(actor_id, client_id, token_data)`.
  It checks neither scope nor class.
- **Today `/mcp` accepts any `aw_` token** whose client resolves to a trust
  row (`handlers/mcp.py:2386-2565`). The authenticator around it is tied to
  MCP: its caches, the bridge that creates the actor, and its runtime context.
- **On REST, an `aw_` token fails every authenticator** (SPA, provider,
  passphrase, trust row, basic) without an explicit refusal (`auth.py:264-524`).

### Revocation

- **Deleting a client** revokes its tokens and deletes the index row, the
  client row and its trust rows (`client_registry.py:343-520`).
- **Outside strict mode,** a token-store fault lets an access token run out
  its hour.
- **An `/a2a` route that calls `validate_access_token`** reads the store on
  every request, so it doesn't have `/mcp`'s cache staleness.

## What this means for the design

### Three kinds of credential fit an owner-created A2A client

1. **An API key: the trust row's own secret.**
   - **Card:** `httpAuthSecurityScheme` `Bearer`, or `apiKey` in a header.
   - **Callers:** Copilot Studio, Foundry and both SDKs can use it.
   - **Revocation:** immediate, because the row is read per request.
   - **Already decided:** this is the main note's Decision 1, option 1.
   - **What it needs:**
     - an owner call that creates the row with no `baseuri`
     - a call that reveals or rotates the secret
     - the deletion branch for an empty `baseuri`
2. **OAuth2 `client_credentials`.**
   - **What the owner gets:** a client id and secret, and the caller
     exchanges them at `/oauth/token` for 1-hour `aw_` tokens.
   - **Card:** `oauth2SecurityScheme` with `clientCredentials.tokenUrl`.
   - **Reuse:** the grant is reusable as is.
   - **What it needs:**
     - a client class
     - a class stamped on the token
     - separating the two classes on the route
   - **Callers:** few real ones offer it directly, though any OAuth library
     can **[inference]**.
3. **OAuth2 authorization code with consent.**
   - **What it serves:** this is what Gemini Enterprise and Copilot Studio
     call "OAuth".
   - **The fit problem:**
     - The flow is built for on-behalf access. The client is registered
       anonymously on the system actor, and the actor is found from the email
       of whoever signs in (`oauth2_server.py:552`).
     - With a platform such as Gemini Enterprise, the person signing in is the
       platform's user, so the token would stand for that user's own actor:
       on-behalf access.
     - Reading it as "the owner grants a third party" needs a separate
       completion path that knows the client's class. Otherwise the flow
       blurs the line the owner's rule draws.

### What separating the two classes takes

- **A new source and prefix,** for example `established_via="a2a_client"`,
  a peer id `a2a_client:…`, and a `peer_type` of its own.
- **Split `OAUTH2_SOURCES` into two sets:**
  - **"Library-made, no endpoint"** gains the new source. That fixes the
    empty-`baseuri` deletion and the callback skip.
  - **"Client on behalf"** stays without it. The A2A row is then a peer:
    overrides always apply and `acl_rules` can be reached.
- **`find_client_trust`'s first arm** must also check the source, so `/mcp`
  can't resolve an A2A row.
- **A class on the client record,** with a prefix such as `a2a_` and its own
  trust types. The four `mcp_` prefix checks are updated or the prefix is
  made a parameter.
- **A class stamped on the token** at minting, taken from the client record,
  never from the request.
- **`/mcp` refuses A2A-class tokens and `/a2a` refuses MCP-class tokens.**
  Both checks are new. The `/mcp` one is a change on a security path while
  4.0 is being checked.
- **A2A trust types must not be offered in the MCP authorise flow.** With no
  client list configured, every registered type except `admin` is
  acceptable (`permission_integration.py:562`), so they need a filter by
  class.

### Status codes

- **Decision 7 (403 for a bearer that matches no trust)** fits a static key.
- **An OAuth2 caller expects 401 with `WWW-Authenticate` for an expired or
  invalid token** (RFC 6750, and A2A's enterprise-ready page).
- The token path gives a reason to revisit decision 7 for `/a2a`.

## Decisions for the owner

1. **Which credentials the first round offers:**
   - (a) the API key only
   - (b) the API key and `client_credentials`
   - (c) also authorization code with the owner's consent

   **Recommended: (b).**
   - (c) carries the highest risk of blurring third party and on-behalf
     access.
   - The callers that need (c) use the user who signs in, which is on-behalf
     access by construction.
2. **The client class:** a new `a2a_` prefix and an `a2a_client` source in the
   same client registry, with a class field. The alternative is to keep
   `mcp_` and tell the classes apart by type only.

   **Recommended: the new prefix and source.**
   - Every classifier above keys on the source or the prefix.
   - Telling them apart by type alone would leave A2A rows inside the
     on-behalf set.
3. **401 or 403 on `/a2a`:**
   - **Recommended:** 401 with `WWW-Authenticate` for a missing, invalid or
     expired credential, and 403 for a valid one that doesn't permit the
     request.
   - REST keeps its 403.
   - This reopens decision 7 for `/a2a` only.
4. **Refusing the other class on `/mcp` and `/a2a`:**
   - **Recommended:** both, in the core plan, with recorded wire transcripts
     for `/mcp` first.

## Owner decisions recorded 2026-11-25

A1. **API key and `client_credentials`.** The owner creates an A2A client in
    the consumer app. The library returns two credentials:
    - the trust row's secret, to use as an API key or Bearer
    - a client id and secret for `client_credentials`

    The card declares both schemes, and the caller may use either.
    Authorization code goes to `thoughts/todo/a2a-followups.md`.

A2. **A client class of its own:**
    - client ids `a2a_<hex>`
    - trust rows with `established_via="a2a_client"` and peer ids
      `a2a_client:…`
    - a class field on the client record, in the same registry

    `OAUTH2_SOURCES` is split: the new source joins "library-made, no
    endpoint" and stays out of "client on behalf". The `mcp_` prefix
    checks become class-aware.

A3. **401 with a `Bearer` `WWW-Authenticate` challenge on `/a2a`** when a
    credential is missing, invalid or expired. 403 when the credential is
    valid but its trust doesn't permit the request. This replaces decision 7
    for `/a2a`; REST keeps its 403.

A4. **Both routes refuse the other class, in the core plan.** The token's
    class is stamped at minting from the client record. `/mcp` refuses
    A2A-class tokens and `/a2a` refuses MCP-class tokens. `find_client_trust`
    also checks the source. `/mcp`'s wire behaviour is recorded first.

    A2A trust types are filtered out of the MCP authorise flow by class.

## Size effect

The core A2A plan grows by about 500–900 library lines:
- the source split
- the client class and token stamp
- the two route checks
- the reveal and rotate call for the secret
- the type filter

Most of this is on authentication and classification paths, so it needs a
second-opinion review. Authorization code, if chosen, would add a further
400–700 lines.

## External References

- <https://a2a-protocol.org/latest/specification/>: §3.1.11, §3.3.2, §4.5, §7.3–7.6, §9.2, §13.3
- <https://raw.githubusercontent.com/a2aproject/A2A/main/specification/a2a.proto>: `SecurityScheme`, `OAuthFlows`, `securityRequirements`
- <https://a2a-protocol.org/latest/topics/enterprise-ready/>: 401/403, `WWW-Authenticate`, scopes per skill
- <https://raw.githubusercontent.com/a2aproject/a2a-python/main/src/a2a/client/auth/interceptor.py>: SDK credential handling
- <https://raw.githubusercontent.com/a2aproject/a2a-js/HEAD/src/client/auth-handler.ts>: retry on 401/403
- <https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent>: Copilot Studio authentication options
- <https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-to-agent-authentication>: Foundry, app-only versus delegated
- <https://docs.cloud.google.com/gemini/enterprise/docs/register-and-manage-an-a2a-agent>: Gemini Enterprise, per-user OAuth, no API key
- <https://developer.atlassian.com/cloud/rovo-a2a/authentication/>: a vendor requiring DCR
