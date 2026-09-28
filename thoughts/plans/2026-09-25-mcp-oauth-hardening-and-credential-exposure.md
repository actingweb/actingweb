---
status: active
---

# Implementation Plan: 3.15.0 — MCP OAuth hardening and two credential exposures

**Date:** 2026-09-25
**Research:** thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Branch:** to be created as `release/3.15.0-mcp-oauth-hardening` from `master` at `2d5eaa4`

## Overview

Three consumer reports, all verified against the tree, land in one minor.
Two are credential exposures: `AwProxy` logs every remote-method body at
DEBUG (four sites), and `GET /{actor_id}/trust` hands the owner's browser every
peer's bearer secret and verification token. Four are MCP OAuth server gaps
found by running claude.ai, Claude Code, Codex and ChatGPT against the
connector: dynamic registration ignores `token_endpoint_auth_method: none`
and the refresh grant then refuses public clients; PKCE is stored and
validated but never read from any library authorize path; refresh tokens are
never rotated and the "revoke old access token" step is a WARNING-logging
no-op; and the token endpoint reports every 400 as `invalid_request`.

This plan (1) summarises instead of logging the proxy bodies, (2) strips the
two credential fields from the trust **list** route only, (3) makes public
clients work end to end with PKCE as their proof, (4) ports the SPA
refresh-token rotation design into the MCP token manager, and makes
authorization codes single-use atomically on the way, (5) returns the right
OAuth error codes, and (6) ships it as 3.15.0 with a migration guide.

A fourth consumer report, triaged the same day
(`thoughts/research/2026-09-25-mcp-client-name-cache.md`), adds Phase 2: the
unauthenticated `clientInfo` cache writes one user's client name into
another user's trust row, client-supplied names reach trust rows and logs
unsanitised, a token-store fault reads as "no such token", and
`Attributes.get_bucket()` cannot say "could not read" — which also broke
Phase 1's chain-revocation fault path.

## Decisions Made

- **`AwProxy` logs a summary, never the body.** All four `with data(...)`
  sites log the sorted key names (capped at 20) and the serialised byte
  length. No opt-in: a consumer that wants bodies logs them at its own call
  site, where it knows what to redact. Key names of a `/properties` write are
  the property names, which is stated in the changelog. The same summary
  helper replaces the two other request-body DEBUG lines the review found
  (`handlers/oauth2_endpoints.py:250`, which would otherwise start logging
  PKCE challenges once D reads them, and the FastAPI trust-param lines).
  SECURITY entry.
- **Trust list strips `secret` and `verification_token`; the per-relationship
  GET is untouched.** Chosen over an opt-in query parameter (nothing known
  needs it) and over leaving it (the consumer redacts, every other consumer
  inherits the exposure). The strip lives in `TrustHandler.get`, not the db
  layer, because `auth.py`, `aw_proxy.py` and the peer verification flow read
  the same row dicts. The spec's list example loses the field; its
  per-relationship SHOULD stays satisfied. SECURITY entry with a **Behavior
  change** sentence, a **Breaking:** line under CHANGED (the repo's shape for
  a wire-field change, `CHANGELOG.rst:900-909`), and a migration-guide
  section.
- **Client authentication moves into the grants; `validate_client` keeps its
  current contract.** `MCPClientRegistry.validate_client(client_id,
  client_secret=None)` is a *lookup* that compares a secret only when one is
  passed (`client_registry.py:130`); the authorize endpoint, the callback's
  trust-type filter and the SDK all call it without a secret and depend on
  that. The draft's "normalise an empty secret to `None`" on its own would
  therefore have let a confidential client refresh or exchange with no
  secret at all. Instead the OAuth2 server gets one
  `_authenticate_client(client_id, client_secret)` that fails closed for a
  confidential client with no or a wrong secret and ignores any presented
  secret for a `none` client, used by all three grants. The auth-code grant's
  current two-call fallback (`oauth2_server.py:489-500`) is replaced by it.
- **DCR honours `none`, and a `none` client gets no secret.** Registration
  accepts `none`, `client_secret_post` and `client_secret_basic`; anything
  else is `invalid_client_metadata` (RFC 7591 §3.2.2). A `none` registration
  response omits `client_secret`; a confidential one gains
  `client_secret_expires_at: 0` (RFC 7591 §3.2.1, REQUIRED when a secret is
  issued). The SDK path (`interface/oauth_client_manager.py`) goes through the
  same validation and `regenerate_client_secret` refuses a `none` client.
  Public clients are refused the `client_credentials` grant with
  `unauthorized_client`. **Registrations made before 3.15 are stored as
  `client_secret_post` with a secret whatever the client asked for, and stay
  that way**: a Codex or ChatGPT connector added before the upgrade keeps
  failing on refresh until the user removes and re-adds it (a fresh
  registration). The migration guide says so in "Start here".
- **PKCE is read on both library authorize paths and required to be `S256`
  there.** GET and POST `/oauth/authorize` read `code_challenge` and
  `code_challenge_method`; both show-form responses (template values and the
  JSON `form_data`) echo them; the provider-button `mcp_context` carries them
  into the callback. On the library path a challenge with an absent method,
  `plain`, or any method other than `S256` is `invalid_request`, and the
  challenge is bounded to `[A-Za-z0-9._~-]{43,128}`. **Exchange keeps
  accepting an explicitly stored `plain` method**, so the consumer's own
  password authorize path, which stores `plain` challenges through
  `create_authorization_code` with the method spelled out
  (`actingweb_mcp/api/oauth_password.py:268`), keeps working. Exchange does
  not apply the RFC 7636 default: an absent stored method is stringified to
  `"None"` at `token_manager.py:158` and rejected by `_validate_pkce`, which
  is unchanged. There is no
  request-side downgrade: the method reaches exchange only through the
  encrypted state and the stored code. The stored code also records the
  `redirect_uri` it was issued for, and exchange compares it when present
  (RFC 6749 §4.1.3); codes created without one (the consumer's path) are not
  compared. SECURITY entry.
- **MCP refresh tokens rotate, in this release.** Owner's call over a todo.
  Port the `oauth_session` design: `chain_id` on both token records, a `used`
  pre-check **before** the compare-and-swap (the SPA order at
  `oauth_session.py:711-726`; without it an already-used record matches
  itself and re-rotates), atomic consume with `conditional_update_attr` on a
  copy of the loaded row, three explicit horizons after a failed pre-check or
  CAS — inside `MCP_REFRESH_TOKEN_GRACE_PERIOD` (60 s) a full rotation in the
  same chain; inside `MCP_REFRESH_TOKEN_REUSE_WINDOW` (2 days) theft, the
  chain is revoked and the grant answers `invalid_grant`; beyond the window
  expired, the row is removed, no revocation — and the consumed row **and its
  global index row** re-stamped to the reuse window. The horizons are
  explicit because neither backend's `get_attr` filters `ttl_timestamp` and
  DynamoDB TTL lags up to 48 h, so a replay days later must not read as
  theft. The refresh record stores the access-token **string**, so the old
  access token is deleted directly (actor id known, no re-load) and popped
  from this process's MCP token cache. A single 60 s grace tier replaces the
  SPA's 10 s/60 s pair; both tiers rotate fully there, so nothing
  client-visible is lost. Legacy refresh records (no `chain_id`, `used`,
  `access_token`) rotate into a fresh chain and skip the old-token delete,
  at DEBUG. The two no-op helpers that log a WARNING per call are deleted.
  **Behavior change**: a refresh response carries a new refresh token and
  the presented one is single-use.
  **[Updated 2026-09-25]** The re-stamp is no longer a second write: the
  compare-and-swap sets the consumed row's TTL itself
  (`conditional_update_attr(ttl_seconds=)`), so it can never re-create a
  row a revocation deleted. A failed swap is re-read strictly, and a row
  still unused (or a re-read that faults) is a store fault answered with
  `server_error`, never "already used". Iteration 16.
- **Chain revocation uses the existing `delete_by_chain` primitive plus a
  bucket snapshot.** `db/protocols.py:1210` `delete_by_chain(actor_id,
  buckets, chain_id)` exists on both backends (PostgreSQL has an expression
  index on `chain_id`). It does not clear the two global index buckets or
  the per-token cache, so `_revoke_chain` first snapshots the actor's two
  token buckets (`list(get_bucket().items())`, one Query each) to collect the
  matching token names, then calls `delete_by_chain`, then deletes each
  index row by name and pops each access token from the cache. Per-actor
  buckets keep this small; the per-row `_remove_*` helpers (5–9 round-trips
  each) are not used on this path.
  **[Updated 2026-09-25]** `_revoke_chain` takes the loaded row as an
  anchor:
  - `delete_by_chain(defer_name=)` deletes it last, so a partial DynamoDB
    delete leaves it to retry from;
  - a delete that removed nothing reads it strictly, to tell a concurrent
    revocation from a fault.

  Eviction runs in a `finally`. `/oauth/logout` with an MCP token now
  reaches `revoke_token`. Iterations 17 and 18.
  **[Updated 2026-09-26]** A faulted revocation keeps the presented token
  (Iteration 20), and `/oauth/logout` answers that fault with 503 and
  `Retry-After` so the client retries (Iteration 22, the owner's choice over
  a `revoked` mark).
- **Authorization codes become single-use atomically; nothing more.**
  `exchange_authorization_code` today reads `used`, validates PKCE, then
  writes `used = True`; two concurrent exchanges both mint tokens. It now
  consumes the code with the same pre-check-plus-CAS before PKCE validation,
  so a failed verifier burns the code, and the code row is deleted on
  success exactly as today. The draft's "a replayed code revokes the chain
  it minted" (RFC 6749 §4.1.2 SHOULD) is dropped: the success path deletes
  the row the replay would need, the chain id does not exist until after
  minting, and retaining the row would only move the horizon to the code
  index's TTL. Atomic consume closes the MUST; the SHOULD is not worth a
  retained row. In scope because F rewrites this function and ports the
  primitive anyway.
- **Consumed MCP records are reaped by a named mechanism per backend.**
  Shortening `ttl_timestamp` alone does nothing on PostgreSQL unless the
  operator's pg_cron job runs, and `cleanup_expired_tokens` keys on
  `expires_at`, which the consume does not change. So: `/oauth/token` calls
  a throttled `TokenManager.maybe_purge_expired_tokens()` (once per hour per
  process, the SPA shape at `oauth_session.py:1033`) that runs
  `delete_expired` over **all seven** MCP buckets — access tokens, refresh
  tokens, provider tokens (`mcp_google_tokens`), auth codes, and the three
  global indexes — and the scheduled `cleanup_expired_tokens` additionally
  treats a refresh record with `used` and `used_at + REUSE_WINDOW < now` as
  expired and sweeps the provider-token bucket it ignores today. On DynamoDB
  `delete_expired` is a no-op and native TTL (already an operator step in
  `docs/guides/database-maintenance.rst:83`) does the work; the guide says
  which reaper each backend relies on. A consumed row whose TTL re-stamp
  faulted keeps its 30-day TTL; that is harmless (a `used` row can never
  rotate) and the plan claims no automatic fallback for it.
- **Refresh lifetime is sliding.** Every rotation stamps a fresh 30-day
  expiry on the new refresh record, so an active chain never expires and
  "30 days" means 30 days of inactivity. Inherited from the SPA store
  (`oauth_session.py:587`) and the current MCP code (`token_manager.py:414`),
  now stated rather than implied; a fixed chain lifetime is not added.
- **`token_endpoint_auth_method` distinguishes public from confidential
  only.** `client_secret_post` and `client_secret_basic` are both accepted
  as the transport for any confidential client; the field is not enforced
  per request. The token handler refuses a request whose body `client_id`
  disagrees with the Basic header's (RFC 6749 §2.3.1 allows one method per
  request; disagreement is `invalid_request`). **[Updated 2026-09-25]** A
  disagreeing `client_secret` is refused the same way; identical duplicates
  are accepted (Iteration 12).
- **Rotation pops one token from the MCP cache; theft evicts the actor.**
  `evict_caches_for_token` today also evicts the actor's `ActorInterface`
  and every trust entry, which is right for revocation but makes every
  hourly refresh a cold path for every connector on the actor. A token-only
  pop is added for rotation (**[Updated 2026-09-25]** it records a per-token
  eviction instead of moving the global cache generation, Iteration 9); `_revoke_chain` and `revoke_token` keep the
  actor-wide eviction. **Both are per-process**: another worker or Lambda
  container keeps serving a deleted access token from its own cache for up
  to `_cache_ttl` (300 s). The SECURITY entry and the `_revoke_chain`
  docstring say so; closing it is the cross-process item in
  `thoughts/todo/mcp-cache-lifecycle-and-revocation.md`.
- **The token endpoint returns the server's error code.** `_handle_token_request`
  returns `{"error": <server code>, "error_description": ...}` with the
  existing status map; `error_response()` keeps its status-derived defaults
  for the other callers. The authorize endpoint's own error collapse
  (`oauth2_endpoints.py:280-283`) is left alone deliberately: RFC 6749
  §4.1.2.1 puts authorize errors on the redirect, and today's behaviour is
  the pre-redirect validation failure, not that path. FIXED entry.
- **Theft on the MCP path answers 400 `invalid_grant`; the SPA path answers
  401.** The MCP token endpoint follows RFC 6749 §5.2; the SPA endpoint has
  its own documented contract. The asymmetry is deliberate and recorded so
  it is not "harmonised" later.
- **Release: 3.15.0, a minor.** A documented response field changes (trust
  list), the token endpoint's refresh contract changes (single-use), and the
  registration response shape changes. Per the owner's standing rule that is
  a minor, with `docs/migration/v3.15.rst`.
- **Phasing: two code phases, one docs phase, one release phase.** Phase 2
  was added by the second triage; Phase 1's list follows.
- **Phase 1 phasing (as first written): one code phase, one docs-and-hardening phase, one release
  phase.** The six code areas are not independent files — C and E both edit
  `handlers/oauth2_endpoints.py`, C and D both edit `oauth2_server.py`, and
  C's grant-side authentication must land before its handler-side
  normalisation — but each has its own tests and none is worth a separate
  green checkpoint; the owner prefers fewer, larger phases.

- **The callback-time client-info write is deleted, not re-keyed.** The
  OAuth callback is a browser redirect with no MCP session, header or token,
  so nothing can link it to a pre-auth `initialize`. The authenticated
  `initialize` path already writes the request's own `clientInfo` to the
  trust row. Deduced, not confirmed: every connector re-initialises with its
  bearer token after OAuth; the Phase 4 rc pass checks it per connector.
  **[Updated 2026-09-25]** The live `clientInfo` cache's session entries
  carry the owning actor; see Iteration 19. A client that only initialised
  before signing in keeps its info: its first authenticated request claims
  the entry.
- **Client-supplied text is sanitised at write and at read.** Names and
  versions (`clientInfo`, DCR `client_name`) are stripped of control and
  format characters (U+200C/U+200D kept), whitespace-collapsed and capped at
  80; `desc` is stripped but never capped because users edit it. Read-time
  sanitising in the two trust GET routes covers rows stored before 3.15 and
  applies to every trust row, peers' included. **Behavior change** entry.
  The consumer's `helpers/client_name.py` rule, adopted.
- **A token-store fault answers 503 on `/mcp` and 500 on refresh, not 401
  and `invalid_grant`.** Owner to confirm: during a store outage every
  uncached MCP request is refused with 503 `Retry-After: 5` instead of 401,
  which a client would answer by re-authenticating against the same broken
  store. Chosen because a 401 on a fault fails a consumer's own guard open
  and makes clients discard good refresh tokens. The fix is strict reads in
  the two token lookups (`get_attr_strict`, both backends), because the
  backends' `get_attr` swallow faults one layer below the token manager.
  `TokenStoreUnavailable` is new public API.
  **[Updated 2026-09-25]** The token endpoint also reads the client
  registration strictly (`MCPClientRegistry.load_client_strict`): a fault
  there answered 401 `invalid_client` before the token lookup could raise.
  The FastAPI `AsyncMCPHandler` answers the 503 too. Iterations 2 and 1.
- **[Added 2026-09-26] Revocation removes the index row first; only a chain
  fault keeps a token alive.** Every token lookup resolves through the
  global index row, so deleting it is the revocation as far as any worker
  is concerned. `_remove_access_token(actor_id=...)` and
  `_remove_refresh_token_row` delete the index row unconditionally, then
  confirm the actor row; an unconfirmed actor row is cleanup (TTL or the
  purge) and is reported, never a reason to keep the token reachable. The
  one deliberate exception is a fault while revoking a token's *chain*:
  the presented token is kept whole as the handle to the chain, and
  `/oauth/logout` answers 503 with `Retry-After` so the client presents it
  again. This settles the question Iterations 17, 20 and 22 each answered
  differently, by stating the property instead of a mechanism; it is pinned
  per revocation path by
  `tests/test_mcp_refresh_rotation.py::TestAnUnconfirmedDeleteStillRevokes`.
  Behaviour that only one caller wants belongs in that caller, never in a
  shared helper (the cause of the Iteration 17 and 22 regressions).
  Iteration 24.
- **`Attributes.loaded` is public.** Consumers stop reading
  `_bucket_loaded`; `_revoke_chain` uses it.

## What We're NOT Doing

- **DCR registration expiry and the two-registrations-per-connect
  observation** — needs a retention policy decision and a scan design;
  `thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md`.
- **Loopback redirect-URI matching, RFC 8707 `resource`, CIMD,
  `openid-configuration`, `resources/templates/list`, `listChanged`
  notifications, the protected-resource `resources: false` field, the
  shared-registration name flip, a post-auth hook for app middleware** —
  conformance work with no live failure behind it;
  `thoughts/todo/mcp-oauth-connector-conformance-followups.md`. The
  unbound-code exposure of a confidential client that sends no challenge
  is noted there too: it is guarded by the client secret, as today.
- **Rejecting `plain` at exchange** — breaks the consumer's password path
  until it changes its default; owner chose lenient exchange.
- **Stripping credentials from the per-relationship GET, the POST-create
  response, or `TrustRelationship.to_dict()`** — the spec says the secret
  SHOULD be readable on the relationship URI, the creator must learn a new
  secret once, peer verification needs `verification_token` there, and
  `to_dict()` is in-process.
- **Cross-process cache invalidation** — the 300 s window is named, not
  closed; `mcp-cache-lifecycle-and-revocation.md` §1.
- **Closing the grace-window divergence** — inside the 60 s grace a thief
  and the victim can each obtain a live branch of the chain and neither is
  detected afterwards; the SPA design accepted this so a client that
  dropped a rotation recovers, and the MCP port takes the same trade. The
  security doc states what the 60 s buys and costs.
- **The `tools/list` fail-open on evaluator error** — a recorded deliberate
  decision (`CHANGELOG.rst:1102`).
- **Dual-era MCP support** — the Claude Code CLI sighting is one data point
  and the client did connect; appended to that todo's trigger list only.
- **The shared-registration name flip** (two clients on one registration
  rewrite `client_name` alternately) — stays in
  `mcp-oauth-connector-conformance-followups.md`; Phase 2 closes the
  cross-user write, not last-writer-wins within one user's row.
- **Strict reads outside the two MCP token lookups** (auth codes, the SPA
  store, trust lookups) — the consumer's guard needs these two; the rest
  keep today's fail-as-absent reads. **[Updated 2026-09-25]** The client
  lookup inside the token-endpoint grants became strict as well
  (Iteration 2); authorize, the callback filter and the SDK keep the
  fail-as-absent read.
- **SPA logout refresh-chain revocation** — different token store, its own
  todo (`logout-does-not-revoke-refresh-chain.md`); unaffected by this work.

## What Already Exists

- `actingweb/oauth_session.py:552-600, 682-773` and
  `handlers/oauth2_spa.py:660-727` — chain ids, `used` pre-check, atomic
  consume on a copy, grace / theft / past-window horizons, token-family
  revocation. **Reused as the design**; the code is not shared because the
  MCP store is per-actor and keyed differently.
- `actingweb/db/protocols.py:1210` `delete_by_chain`, implemented at
  `db/dynamodb/attribute.py:365-403` and `db/postgresql/attribute.py:647-675`
  (indexed). **Reused** by `_revoke_chain`.
- `actingweb/attribute.py:228` `conditional_update_attr` (bucket-agnostic,
  TTL preserved on both backends) and `set_attr(..., ttl_seconds=)`.
  **Reused** for the consume and the TTL re-stamp.
- `actingweb/oauth_session.py:1033` `maybe_purge_expired_tokens` and
  `DbAttribute.delete_expired(buckets=)`. **Copied** for the MCP buckets.
- `actingweb/oauth2_server/token_manager.py:1046-1117` `revoke_client_tokens`
  — the per-actor bucket snapshot shape. **Reused** by `_revoke_chain`.
- `actingweb/mcp/invalidation.py:31` `evict_caches_for_token` and
  `handlers/mcp.py` `clear_token_from_cache`. **Extended** with a token-only
  variant.
- `actingweb/oauth2_server/state_manager.py:120-158` `create_mcp_state`
  already accepts `code_challenge`/`code_challenge_method`, and
  `oauth2_server.py:203-212` already passes them. **Reused**; only the
  handler-side reads are missing.
- `templates/aw-oauth-authorization-form.html:15-16` hidden PKCE inputs.
  **Reused**; they render empty today.
- `token_manager.py:60-110, 165-176, 941-988` challenge storage and
  verification. **Reused unchanged.**
- `actingweb/oauth2.py` `_redact_token_response` and
  `tests/test_logging_redaction.py`. **Pattern copied** for the summary
  helper and its tests.
- `tests/test_oauth2_spa_refresh_rotation.py:32-118` `_make_config()` with an
  in-memory `MockDbAttribute`. **Copied and extended** (it must return copies
  from `get_attr`, honour `used` in `conditional_update_attr`, and expose
  `delete_by_chain`, `delete_expired` and `get_bucket`) as the MCP token
  manager test double.
- `tests/test_mcp_trust_cache_key.py:96-100` patches `actingweb.actor.Actor`.
  **Copied** so registry unit tests do not touch the actor store.
- `tests/test_trust_handler_permissions.py:17-90` mocked-handler setup for
  `handlers/trust.py`. **Copied** for the list-strip unit test.
- `tests/test_oauth2_server_lazy_authenticator.py:31-43` a `Config` with
  `oauth_providers` set. **Copied** for the PKCE provider-path tests.

## Phase 1: Code and tests — proxy log summary, trust-list strip, public clients with PKCE, single-use codes and refresh rotation, error codes

### Changes

**A. Request-body DEBUG lines** — new `actingweb/log_summary.py`,
`actingweb/aw_proxy.py`, `actingweb/handlers/oauth2_endpoints.py`,
`actingweb/interface/integrations/fastapi_integration.py`

- `log_summary.summarize_payload(obj: Any, *, encoded_len: int | None =
  None, max_keys: int = 20) -> str` returns `"keys=[a, b] bytes=N"` for a
  dict (sorted keys, `+K more` past the cap), `"bytes=N"` otherwise. It takes
  the object the caller already has, so there is no re-parse and no error
  branch; `encoded_len` is `len(data)` where the caller has it.
- `aw_proxy.py:247`, `:306`, `:542`, `:646`: `str(data)` →
  `summarize_payload(params, encoded_len=len(data))`. Line text otherwise
  unchanged so existing grep patterns keep matching.
- `oauth2_endpoints.py:250`: `dict(params)` → `summarize_payload(params)`
  (the line logs `email` today and would log `code_challenge` after D).
- `fastapi_integration.py:1349` (`Trust query params: {params}`) and `:2470`
  (`Trust handler args/kwargs`): same helper.

**B. `actingweb/handlers/trust.py`** (`TrustHandler.get`, `:46-77`)

- Add `_public_trust_row(row: Any) -> Any` (module level): a dict copy
  without `secret` and `verification_token`; non-dicts unchanged (the
  PostgreSQL `fetch` annotation admits `list[Any]`).
- Apply it to every row in the list response before `json.dumps`.
- `TrustPeerHandler.get` (`:376-470`) is **not** changed; add a comment
  there naming the spec SHOULD (`actingweb-spec.rst:1754-1758`) and the peer
  verification read (`actor.py:1263`) so the asymmetry is not "fixed" later.
- `handlers/www.py:462` keeps passing full rows to the template (server-side
  render, nothing printed); no change.

**C. Public clients** — `actingweb/oauth2_server/client_registry.py`,
`actingweb/oauth2_server/oauth2_server.py`,
`actingweb/handlers/oauth2_endpoints.py`,
`actingweb/interface/oauth_client_manager.py`

Order matters: C.1–C.3 land before C.4, because C.4 only becomes safe once
every grant fails closed on its own.

- **C.1 `client_registry.py:61-71` `register_client`**: read
  `token_endpoint_auth_method` (default `client_secret_post`); accept
  `none`, `client_secret_post`, `client_secret_basic`; raise
  `ValueError("token_endpoint_auth_method must be one of ...")` otherwise.
  For `none`, store `client_secret: None`. Response (`:86-101`): omit
  `client_secret` for `none`; add `"client_secret_expires_at": 0` when a
  secret is issued. `_create_client_trust_relationship` (`:447`) keeps
  passing `client_data["client_secret"]` into `oauth_tokens` — `None` for a
  `none` client; `trust_manager.py:616-628` reads only
  `access_token`/`refresh_token`/`expires_at`/`token_type`, so the trust row
  carries no secret and nothing breaks. `validate_client` (`:113-148`) is
  **unchanged**.
- **C.2 `oauth2_server.py`**: add `_authenticate_client(client_id,
  client_secret) -> dict | None`: `client = validate_client(client_id)`
  (lookup only; **[Updated 2026-09-25]** now `load_client_strict`, and the
  secret is compared on that record, Iteration 2); `None` → `None`; method `none` → return the client, any
  presented secret ignored (RFC 6749 §2.3: a public client does not become
  confidential by sending one); otherwise `client_secret` must be non-empty
  and `secret_equals` the stored one, else `None`. Use it in
  `_handle_authorization_code_grant` (replacing `:489-500`),
  `_handle_refresh_token_grant` (`:537-540`) and
  `_handle_client_credentials_grant`, where the lookup now precedes the
  `if not client_secret` presence check (`:568-569`) so a `none` client
  answers `unauthorized_client` rather than `invalid_request`. The
  auth-code grant's `code_verifier required for public clients` check
  (`:501-506`) stays and now follows the new call.
- **C.3 `oauth_client_manager.py:65`**: pass `token_endpoint_auth_method`
  explicitly (from kwargs, default `client_secret_post`) instead of relying
  on `**kwargs` overriding a hardcoded key; `regenerate_client_secret`
  (`:207-244`) raises `ValueError` for a `none` client.
- **C.4 `oauth2_endpoints.py:332-358`**: `"client_secret": form_data.get(
  "client_secret", [None])[0] or None`; parse the `Authorization: Basic`
  header **whenever present** (not only when the form lacks `client_id`,
  `:335`): fill `client_id` if absent, fill `client_secret` if absent, keep
  a body value that is present; a body `client_id` that disagrees with the
  header's is `invalid_request` (RFC 6749 §2.3.1). Fix the "headsers" typo
  at `:339` while there.

**D. PKCE on the library authorize paths** —
`actingweb/handlers/oauth2_endpoints.py`, `actingweb/oauth2_server/oauth2_server.py`,
`actingweb/oauth2_server/token_manager.py`

- `oauth2_endpoints.py:212-246`: add `code_challenge` and
  `code_challenge_method` to both the GET params and the POST form params,
  normalised so an absent or empty value is `None` (`AWWebObj.get` returns
  `""` for an absent param, `aw_web_request.py:14`).
- `oauth2_server.py:135-136`: drop the `"plain"` default (`None` when
  absent). `:161-175` authorize validation, when a challenge is present:
  method must be exactly `S256` (`invalid_request: code_challenge_method
  must be S256; plain is not accepted`), challenge must match
  `^[A-Za-z0-9._~-]{43,128}$`; keep the `none`-requires-PKCE check.
- `oauth2_server.py:178-185` show-form response and
  `oauth2_endpoints.py:711-714` (template values) **and** `:727-740` (the
  JSON `form_data` branch): both carry `code_challenge` and
  `code_challenge_method`.
- `oauth2_endpoints.py:652-661` provider-button `mcp_context`: add both
  fields from `form_data`.
- `token_manager.py:60-110` `create_authorization_code`: new keyword
  `redirect_uri: str | None = None`, stored on the record;
  `oauth2_server.py:412-419` passes the callback's `redirect_uri`;
  `exchange_authorization_code` takes `redirect_uri` and, when the record
  has one, refuses a mismatch (`None` when the stored value is absent, the
  consumer's path). `_validate_pkce` (`:941-988`) unchanged.

**E. Token-endpoint error codes** — `actingweb/handlers/oauth2_endpoints.py`

- `:363-388`: after computing `status`, `self.response.set_status(status)`
  and `return {"error": error, "error_description": description}`; keep the
  `WWW-Authenticate` header on 401. Add `unauthorized_client` and
  `invalid_scope` to the 400 list.
- `:146-192` registration: on `ValueError`, return
  `{"error": "invalid_client_metadata", "error_description": str(e)}` with
  400 (RFC 7591 §3.2.2).
- `error_response()` (`:1022-1035`) unchanged for its other callers.

**F. Single-use codes and refresh-token rotation** —
`actingweb/oauth2_server/token_manager.py`, `actingweb/constants.py`,
`actingweb/mcp/invalidation.py`, `actingweb/handlers/mcp.py`,
`actingweb/handlers/oauth2_endpoints.py`

- `constants.py`: `MCP_REFRESH_TOKEN_GRACE_PERIOD = 60`,
  `MCP_REFRESH_TOKEN_REUSE_WINDOW = 86400 * 2`,
  `MCP_TOKEN_PURGE_INTERVAL = 3600`; asserts `MCP_ACCESS_TOKEN_TTL <
  MCP_REFRESH_TOKEN_REUSE_WINDOW < MCP_REFRESH_TOKEN_TTL` and
  `MCP_REFRESH_TOKEN_GRACE_PERIOD < MCP_REFRESH_TOKEN_REUSE_WINDOW`.
- Records: `_create_access_token` / `_create_access_token_from_refresh`
  (`:355-401`) take `chain_id` and store it. `_create_refresh_token`
  (`:403-419`) takes `access_token: str`, `chain_id` and
  `google_token_key: str | None`; stores `access_token`, `chain_id` (fresh
  `secrets.token_urlsafe(16)` when `None`), `google_token_key` (the
  provider-token row the access token owns, `None` for refresh-minted
  tokens), `used: False`; keeps `access_token_id` for one release.
- `_consume(bucket, name, record, *, restamp_ttl: int | None) ->
  tuple[bool, dict | None]`: the SPA `try_mark_refresh_token_used` shape on
  a per-actor bucket — `used` pre-check first (return `(False, record)`),
  then `old = copy(record)`, `new = old | {used: True, used_at: now}`,
  `conditional_update_attr`; on success and when `restamp_ttl` is given,
  best-effort re-`set_attr(ttl_seconds=restamp_ttl)`; on CAS failure re-read
  through a fresh `Attributes` and return `(False, current)`. Refresh tokens
  pass `REUSE_WINDOW`; codes pass `None` (a code row is deleted on success
  and expires on its own 10-minute TTL otherwise).
- `exchange_authorization_code` (`:112-223`): after the expiry and client
  checks, `_consume` the code **before** PKCE validation. Pre-check or CAS
  failure: return `None` (the code is already consumed; nothing is
  revoked). PKCE failure after a successful consume returns `None` with the
  code burnt (remove the code and its provider-token row as the used-code
  branch does today, `:150-157`). Success: mint the access token with a
  fresh `chain_id`, the refresh token with the token string, the chain and
  the access token's `google_token_key`, then `_remove_auth_code` as today
  (`:203`). `redirect_uri` comparison from D sits with the client check.
- `refresh_access_token` (`:252-303`):
  1. load; expired → remove, `None`; `client_id` mismatch → `None`.
  2. `_consume` on the actor's refresh bucket. On success also re-stamp the
     global index row (`REUSE_WINDOW + INDEX_TTL_BUFFER`, one write).
  3. Not consumed and a record came back: `age = now - used_at`.
     `age <= GRACE_PERIOD` → full rotation in the same chain, nothing
     revoked, the consumed row not re-stamped (`oauth2_spa.py:660-673`).
     `GRACE_PERIOD < age <= REUSE_WINDOW` → `_revoke_chain` when the record
     has a chain, else `_remove_refresh_token` only; one WARNING naming the
     actor and the masked token; return `None`.
     `age > REUSE_WINDOW` → remove the row, DEBUG, return `None`
     (`oauth2_spa.py:674-687`: expired, not theft). No `used_at` → treat as
     `None` result with the row removed.
  4. Success: when the record carries `access_token`,
     `_remove_access_token(token, actor_id=record["actor_id"],
     google_token_key=record.get("google_token_key"))` (new keywords: skip
     the re-load and the index re-read; delete the provider-token row when
     the key is given — the first refresh of a chain deletes a code-minted
     access token that owns one, `token_manager.py:363`) and the token-only
     cache pop; legacy records skip all of it at DEBUG. Mint the new pair in
     the same chain (the new refresh record carries `google_token_key:
     None`) and return it with `"refresh_token": <new>`.
- `_revoke_chain(actor_id, chain_id) -> int`: snapshot
  `list(tokens.get_bucket().items())` and the same for the refresh bucket
  (a `None` bucket read is logged at WARNING and treated as empty); collect
  names whose `chain_id` matches; `delete_by_chain(actor_id, [tokens_bucket,
  refresh_tokens_bucket], chain_id)` on the db layer; delete each matching
  index row by name in the two global index buckets; pop each access token
  from the cache; `evict_caches_for_actor(actor_id)` once; return the count.
  Docstring states the per-process cache window.
- `revoke_token` (`:305-353`): a refresh token also removes its
  `access_token` string when present; an access token also removes the
  refresh tokens in its `chain_id` when present (a bucket snapshot, rare
  path). **[Updated 2026-09-25]** Both branches revoke the whole chain
  (Iteration 5). Delete `_revoke_access_token_by_id` and
  `_revoke_refresh_tokens_for_access_token` (`:894-939`; only callers are
  `:285`, `:332`, `:345`).
- `cleanup_expired_tokens` (`:1119+`): a refresh record with `used` and
  `used_at + REUSE_WINDOW < now` counts as expired (index row and actor row
  both removed); the provider-token bucket, which it ignores today, is
  swept by `ttl_timestamp`. Still scheduled-only.
- `maybe_purge_expired_tokens()`: process-local throttle
  (`MCP_TOKEN_PURGE_INTERVAL`; reset the way
  `test_oauth2_spa_refresh_rotation.py` resets the SPA one), calls
  `DbAttribute.delete_expired(buckets=[...])` over all seven MCP buckets
  (access tokens, refresh tokens, provider tokens, auth codes, and the
  access-token, refresh-token and auth-code indexes); called from
  `_handle_token_request` after the grant (same placement as the SPA
  endpoint). DynamoDB returns 0 by design. **[Updated 2026-09-25]** Now
  called **before** the grant (Iteration 6).
- `mcp/invalidation.py` and `handlers/mcp.py` `clear_token_from_cache`: add
  `actor_wide: bool = True`; rotation calls it with `False` (pop the token
  entry only). No other hot-path change: the cached record gains a
  `chain_id` key and nothing reads it.

### New Tests, both unit and integration tests

Test double (`tests/mcp_token_double.py`, copied from
`test_oauth2_spa_refresh_rotation.py:32-118` and extended): `get_attr`
returns a **deep copy**; `conditional_update_attr` compares against the
stored value and honours a monkeypatch to force failure; `get_bucket`,
`delete_by_chain`, `delete_expired` and `set_attr(ttl_seconds=)` (recorded,
not enforced) implemented. Registry tests patch `actingweb.actor.Actor` as
`test_mcp_trust_cache_key.py:96-100` does.

- `tests/test_log_summary.py` and `tests/test_aw_proxy.py` (new class,
  caplog at DEBUG, `requests.post`/`put` and `httpx.AsyncClient` patched):
  for each of the four proxy methods a body `{"password": "hunter2",
  "note": "x"}` yields a record containing `keys=[note, password]` and
  `bytes=` and **not** `hunter2`; a list body yields `bytes=` only; 25 keys
  yield 20 names and `+5 more`. `oauth2_endpoints.py:250`: an authorize
  request with `email` and `code_challenge` logs neither value.
- `tests/test_trust_list_strips_credentials.py` (mocked handler per
  `test_trust_handler_permissions.py:90`): `TrustHandler.get` with two rows
  carrying both fields → neither key on either row, all other keys kept; a
  non-dict row passes through; `TrustPeerHandler.get` as creator → both
  keys present (pins the asymmetry).
- `tests/integration/test_trust_lifecycle.py`: after `:98`, GET the list and
  assert no row has `secret` or `verification_token` while the
  per-relationship body still does. Both backends in CI.
- `tests/test_oauth2_public_clients.py` (unit, double + patched `Actor`):
  - `register_client` with `none` → no `client_secret`, stored method
    `none`; with `client_secret_basic` → secret and
    `client_secret_expires_at == 0`; unknown method → `ValueError`; absent
    → `client_secret_post` (unchanged).
  - `_authenticate_client`: `none` client with no secret and with a bogus
    secret → client; confidential with `None`, `""` and a wrong secret →
    `None`; confidential with the right secret → client.
  - auth-code grant, confidential client, no secret → `invalid_client`
    (the regression the review found); `none` client without
    `code_verifier` → `invalid_request`.
  - refresh grant, `none` client, no secret → new tokens; confidential, no
    secret → `invalid_client`.
  - client-credentials grant, `none` client → `unauthorized_client`;
    confidential without a secret → `invalid_request` (unchanged).
  - `OAuth2ClientManager.create_client(token_endpoint_auth_method="none")`
    → no secret; `regenerate_client_secret` on it → `ValueError`.
  - handler: Basic header **plus** the same body `client_id` → the header
    secret is used; body secret present and header present → body wins;
    body `client_id` differing from the header's → 400 `invalid_request`.
- `tests/test_oauth2_pkce_binding.py` (handler + server on the double,
  config with `oauth_providers` per `test_oauth2_server_lazy_authenticator.py:31-43`,
  provider `exchange_code_for_token`/userinfo patched):
  - GET authorize, `Accept: text/html`, with an S256 challenge → template
    values carry both fields **and** `extract_mcp_context` on the `state` in
    `template_values["oauth_providers"][0]["url"]` carries them (the
    provider-button path); GET as JSON → `form_data` carries them.
  - POST with `provider=google` → the redirect's state decodes with both
    fields; callback with that state → the stored code has the challenge
    and the `redirect_uri`; exchange with the wrong verifier → `None`, with
    the right verifier → tokens; exchange with a different `redirect_uri` →
    `None`.
  - authorize with `plain` → `invalid_request`; with a challenge and no
    method → `invalid_request`; challenge of 42 chars or with `+` →
    `invalid_request`; `none` client without a challenge → `invalid_request`
    (existing).
  - a challenge stored directly through `create_authorization_code` with
    `code_challenge_method="plain"` spelled out and no `redirect_uri` still
    exchanges (pins the lenient exchange and the consumer's path); the same
    with the method omitted does not (pins today's `"None"` behaviour so a
    later "fix" is deliberate).
- `tests/test_oauth2_token_endpoint_errors.py` (handler unit): dead refresh
  token → 400 body `error == "invalid_grant"`; bad code → `invalid_grant`;
  unknown grant → `unsupported_grant_type`; bad secret → 401
  `invalid_client` with `WWW-Authenticate`; registration with a bad
  `token_endpoint_auth_method` → 400 `invalid_client_metadata`.
- `tests/test_mcp_refresh_rotation.py` (`TokenManager` on the double):
  - rotation returns a **different** refresh token; the presented one is
    `used`; the old access token is gone from the actor bucket, the global
    index and `_token_cache`, and the actor's trust cache entry is **not**
    evicted; the new records share the chain; the consumed row and its
    index row were re-stamped (recorded `ttl_seconds`).
  - first refresh after a code exchange also deletes the provider-token row
    the code-minted access token owned (`mcp_google_tokens`); the second
    refresh has none to delete and logs nothing above DEBUG.
  - CAS succeeds and `_store_access_token` raises → the grant fails; a
    retry 30 s later rotates in the same chain (grace pre-check path); a
    retry 90 s later revokes the chain. Pins the recovery contract that
    makes the 60 s grace non-negotiable.
  - a second presentation after a completed rotation, `used_at` seeded
    10 s ago → full rotation, same chain, nothing revoked (pre-check path,
    not CAS).
  - `used_at` seeded 5 min ago → `None`; every access and refresh token in
    the chain gone from both buckets and both indexes; a token from a
    different chain on the same actor survives; actor cache evicted.
  - `used_at` seeded 3 days ago → `None`, row removed, nothing revoked.
  - legacy record (no `chain_id`, `used`, `access_token`) → fresh chain,
    no exception, no WARNING.
  - CAS loser: `conditional_update_attr` monkeypatched to flip `used` and
    return `False` → the loser gets a rotation in the same chain.
  - old-access-token delete faults → new tokens still issued, one WARNING.
  - `revoke_token(refresh)` removes its access token; `revoke_token(access)`
    removes its chain's refresh tokens.
  - `cleanup_expired_tokens` removes a used record past the reuse window and
    keeps one inside it; `maybe_purge_expired_tokens` runs once per interval.
- `tests/test_mcp_auth_code_single_use.py`: two exchanges of one code →
  exactly one token pair and the code row gone; a CAS loser (monkeypatched
  double) → `None`, the winner's tokens untouched; wrong verifier → `None`
  and the code is consumed (a correct retry also fails); the code row's
  recorded `ttl_seconds` is never re-stamped.
- `tests/integration/test_mcp_oauth2.py`: registration with `none` → 201
  without `client_secret` (register directly; `tests/integration/utils/oauth2_helper.py:76`
  switches to `.get`); a `none` client asking for `client_credentials` →
  400 `unauthorized_client`; `test_token_request_invalid_credentials`
  additionally asserts `error == "invalid_client"`.
- Existing tests: no existing assertion breaks (the review grepped
  `"refresh_token": refresh_token`, `invalid_request`, `client_secret`,
  `access_token_id`); the only edits are the ones named above.

### Failure Scenarios

- Proxy log summary — a non-dict payload — `bytes=` only; covered.
- Trust list strip — a non-dict row — passed through; covered.
- `none` registration — client later sends a secret anyway (ChatGPT does) —
  ignored by `_authenticate_client`; covered.
- Confidential client omits its secret on refresh — `invalid_client`, as
  today; covered (the regression test).
- Basic header with a body `client_id` — header secret read; covered.
- Refresh consume — CAS succeeds and the TTL re-stamp faults — the token is
  consumed and keeps its 30-day TTL; harmless, a `used` row can never
  rotate, and the scheduled cleanup reaps it by `used_at` if the operator
  runs it; DEBUG. No automatic fallback is claimed.
- Refresh consume — CAS succeeds and a mint write faults — the client holds
  a consumed token; a retry inside 60 s rotates in the same chain, a retry
  after 60 s reads as theft; covered by the 30 s / 90 s test and stated in
  the `refresh_access_token` docstring.
- Refresh consume — a replay after DynamoDB TTL lag or on PostgreSQL before
  the purge — the past-window branch answers `None` without revoking;
  covered by the 3-day case.
- Old access token delete faults after the consume — new tokens issued, old
  one lives out ≤ 1 h, WARNING; covered.
- Chain revoke — a bucket read faults — `get_bucket()` never returns `None`
  (it returns `{}` on a fault), so the original "`None` → WARNING" branch was
  dead. Corrected in Phase 2 (J): `Attributes.loaded` tells the two apart.
  **[Updated 2026-09-25]** That held for PostgreSQL only; DynamoDB raises
  from `get_bucket`. Both shapes are now caught (Iteration 3).
- Chain revoke — `delete_by_chain` faults — the exception propagates out of
  the grant as today's storage faults do (500 `server_error`); the
  presented token was already consumed so a retry cannot rotate it.
  **[Updated 2026-09-25]** PostgreSQL's `delete_by_chain` returned 0 rather
  than raising; a delete of nothing is now `TokenStoreUnavailable` too, and
  the retry re-runs the revocation (Iteration 3).
- Auth code — two concurrent exchanges — one wins the CAS, the other gets
  `None`; the winner's tokens stand; covered.
- Auth code — PKCE fails — code burnt, `None`; covered.
- PKCE — a custom authorize template without the hidden inputs — the POST
  read finds nothing; a `none` client is refused at authorize, a confidential
  client gets an unbound code as today; the migration guide names the two
  inputs.
- Rotation on a multi-process deployment — another worker serves the old
  access token from its cache for ≤ 300 s — named in the SECURITY entry and
  the docstring; not closable here.
- Error mapping — an unknown server error code — 500 `server_error`;
  covered by the unknown-grant case.

### Verification

- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests && poetry run ruff format --check actingweb tests`
- [x] `make test-all-parallel` on DynamoDB; re-run failures sequentially
- [x] `DATABASE_BACKEND=postgresql ... make test-integration` (per `CLAUDE.md`)
- [ ] Manual, dev server with a real provider: register a `none` client with
      `curl`; GET authorize with an S256 challenge → form POST → callback →
      exchange with the verifier; refresh, then present the first refresh
      token again after 60 s and confirm 400 `invalid_grant` and that the
      second refresh token is dead; on PostgreSQL confirm the consumed rows
      are gone after the purge interval

### Implementation Status: Complete

Notes (2026-09-25):

- Branch `release/3.15.0-mcp-oauth-hardening` was cut from
  `docs/workflow-contract-and-3.15.0-plan` (661ee03), not from `master` at
  `2d5eaa4`, so the plan and the workflow contract travel with the code. That
  docs branch is not merged yet; its two commits land with this PR unless it
  merges first.
- Minor-release triggers, for the changelog phase: new registration
  metadata value (`none`) and response fields (`client_secret` omitted,
  `client_secret_expires_at`), new error codes on `/oauth/token` and
  `/oauth/register`, a changed trust-list response shape, a new refresh
  contract, new constants (`MCP_REFRESH_TOKEN_GRACE_PERIOD`,
  `MCP_REFRESH_TOKEN_REUSE_WINDOW`, `MCP_TOKEN_PURGE_INTERVAL`), additive
  keyword parameters (`create_authorization_code(redirect_uri=)`,
  `exchange_authorization_code(redirect_uri=)`,
  `clear_token_from_cache(actor_wide=)`, `evict_caches_for_token(actor_wide=)`)
  and a new `provider_tokens` key in `cleanup_expired_tokens()`'s result.
- Additions beyond the plan's list:
  - `oauth2_endpoints.py` also logged the whole authorize **server response**
    at DEBUG, which after D carries the challenge; it now logs the action
    and a summary.
  - `OAuth2ClientManager.regenerate_client_secret` logged the new and the
    stored client secret at ERROR when its read-back check failed; those two
    values are no longer logged.
  - The Basic header is form-urldecoded before use (RFC 6749 §2.3.1); ids
    and secrets this library issues are unchanged by it.
  - `_revoke_chain` also deletes the provider-token rows of the chain's
    code-minted access tokens, so a theft revocation leaves no orphan in
    `mcp_google_tokens`.
  - The token handler's old "No Authorization headsers" branch is gone: a
    missing `client_id` reaches the grants, which answer `invalid_request`.
- On the grace path (a consumed token replayed within 60 s) the old access
  token is not deleted a second time: the CAS winner already deleted it.
- The plan's "logs nothing above DEBUG" on a second refresh is asserted as
  "no WARNING": the existing `Stored ... token` lines log at INFO on every
  mint and were left alone.
- Test helpers: `tests/mcp_token_double.py` (store double on a real
  `Config`) and `tests/mcp_oauth_server_helpers.py` (server built without
  its provider probe, handler factory). Added
  `tests/integration/test_mcp_refresh_rotation_backend.py`, which runs
  rotation, grace, theft and past-window on DynamoDB and PostgreSQL. It
  closes the "legacy `None` fields in the CAS" unverified note for new
  records; legacy records stay unit-only.
- Checks: ruff, format and pyright clean; fast tier 2601 passed; full tier
  on DynamoDB 3576 passed; on PostgreSQL everything passed except the two
  benchmark subscription tests already filed as
  `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`
  (this branch does not touch `tests/performance/`). Manual curl pass with a
  real provider: not run (no provider credentials in this session); the
  rc connector pass in Phase 4 covers it.

---

## Phase 2: Client-supplied text, the client-info cache, and store faults that read as absence

Added 2026-09-25 from the triage of `actingweb_mcp`'s client-name cache
report (`thoughts/research/2026-09-25-mcp-client-name-cache.md`). Item
numbers below are the report's.

### Changes

**G. Sanitising client-supplied text** — new `actingweb/client_text.py`,
`actingweb/handlers/mcp.py`, `actingweb/oauth2_server/client_registry.py`,
`actingweb/interface/trust_manager.py`, `actingweb/handlers/trust.py`

- `sanitize_client_name(value, *, max_len=80) -> str`: strip Unicode
  control (`Cc`) and format (`Cf`) characters except U+200C and U+200D,
  collapse whitespace runs to one space, strip, cap at `max_len`.
  `sanitize_label(value) -> str`: the same without the cap (for `desc`,
  which users edit). Non-strings become `""`.
- Write sites: `clientInfo.name` and `.version` before caching, logging or
  writing to a trust row (`_handle_initialize`,
  `_update_trust_with_client_info`); the DCR `client_name` in
  `register_client` (stored and returned sanitised; empty after sanitising
  is `invalid_client_metadata`); the `desc` seed in `trust_manager.py`.
- Read sites: `_public_trust_row` and `TrustPeerHandler.get` pass
  `client_name` and `client_version` through `sanitize_client_name` and
  `desc` through `sanitize_label`, for rows stored before 3.15. The
  www templates render server-side and are not changed.

**H. The client-info cache** — `actingweb/handlers/mcp.py`,
`actingweb/oauth2_server/oauth2_server.py`

- Delete the callback-time write (`oauth2_server.py:447` and
  `_store_mcp_client_info_in_trust`, `_update_trust_with_client_info_oauth`
  if nothing else calls it). The authenticated `initialize` path
  (`mcp.py:918-926`) names the trust row from the request's own
  `clientInfo`.
- `_get_session_key` loses the `remote_addr:hash(UA)` fallback: the key is
  `mcp-session:<Mcp-Session-Id>`, or, on an authenticated request,
  `token:<sha256(bearer)[:32]>`; with neither it is `None` and nothing is
  cached or read. `_resolve_live_client_info` and the client-type detection
  reads try the session key, then the token key.
- On an authenticated `initialize` the sanitised `clientInfo` is also cached
  under the token key, so a client without `Mcp-Session-Id` keeps its live
  context.
- The cache is bounded (`MCP_CLIENT_INFO_CACHE_MAX = 1000`, oldest evicted
  first) as well as pruned by age.

**I. Token-store faults are not "no such token"** —
`actingweb/oauth2_server/token_manager.py`,
`actingweb/oauth2_server/oauth2_server.py`, `actingweb/handlers/mcp.py`

- `class TokenStoreUnavailable(Exception)` in `token_manager.py`, exported
  from `actingweb.oauth2_server`.
- `_search_token_in_actors` and `_search_refresh_token_in_actors` read the
  index row and the actor row with `get_attribute(config).get_attr_strict`
  and raise `TokenStoreUnavailable` from a backend error. Absence, a
  malformed row and a stale index row keep returning `None`.
  `validate_access_token` and `validate_mcp_token` propagate it (docstrings
  say so).
- `authenticate_and_get_actor_cached` re-raises it; the two MCP entry
  points that turn a failed authentication into 401 (`GET /mcp` and the
  JSON-RPC POST) answer **503** with `Retry-After: 5` instead
  (`-32603`-shaped JSON-RPC error on POST). The `initialize`
  opportunistic authentication keeps swallowing it.
- The refresh grant lets it reach `handle_token_request`'s catch-all, which
  answers 500 `server_error`, so a throttle no longer tells the client its
  refresh token is dead.

**J. `Attributes.loaded`** — `actingweb/attribute.py`,
`actingweb/oauth2_server/token_manager.py`

- A read-only `loaded` property: `True` once `get_bucket()` got an answer
  from the backend (an empty bucket included), `False` before and after a
  faulted read. Documents that `get_bucket()` returns `{}` in both cases.
- `_snapshot_bucket` checks `loaded` after `get_bucket()`; on a fault it
  logs a WARNING and `_revoke_chain` still runs `delete_by_chain` (the
  actor rows go) but skips the index and provider-row cleanup it could not
  enumerate. Stale index rows are already cleaned by the lookups that find
  them, and expire on their TTL.

### New Tests, both unit and integration tests

- `tests/test_client_text.py`: control and format characters stripped;
  U+200C/U+200D kept; newlines and tabs collapse to a space; the cap; a
  non-string becomes `""`; `sanitize_label` does not cap.
- `tests/test_mcp_client_info_cache.py` (handler on stubs):
  an unauthenticated `initialize` without `Mcp-Session-Id` caches nothing;
  one with it caches under the session key, sanitised; a second user's
  authenticated request with a different or no session id does not see it;
  an authenticated `initialize` caches under the token key and the next
  request with the same bearer resolves it; the cache never exceeds its cap;
  the INFO line carries the sanitised name; `clientInfo` without `name`
  does not raise.
- `tests/test_oauth2_callback_does_not_write_client_info.py`: the callback
  with a populated cache writes no client name to the trust row
  (`_update_trust_with_client_info_oauth` not called; the attribute gone).
- `tests/test_oauth2_public_clients.py`: registration sanitises
  `client_name`; a name that sanitises to empty is refused.
- `tests/test_trust_list_strips_credentials.py`: list and per-relationship
  GET sanitise `client_name`, `client_version` and `desc` (a `desc` longer
  than 80 characters is not cut).
- `tests/test_mcp_token_store_faults.py`: with `get_attr_strict` raising,
  `validate_access_token` raises `TokenStoreUnavailable`; the refresh grant
  answers `server_error`, not `invalid_grant`; the MCP POST and GET answer
  503 with `Retry-After`; an absent token is still 401.
- `tests/test_mcp_refresh_rotation.py`: `get_bucket` faulting during theft
  revocation → WARNING, the chain's actor rows gone, no exception.
- `tests/test_attribute_loaded.py`: `loaded` false before a read, true
  after an empty and a non-empty read, false after a faulted read.
- Integration (both backends): register a client with a control character
  in `client_name` and read it back from the trust list without it.

### Failure Scenarios

- A connector continues its pre-auth MCP session after OAuth instead of
  re-initialising — its trust row keeps the DCR name until its first
  authenticated `initialize`. Deduced, not confirmed; the Phase 4 rc pass
  checks every connector.
- A store outage — every uncached MCP request answers 503 rather than 401
  for its length; cached tokens keep working for up to 300 s (unchanged).
  Stated in the changelog.
- A client name made only of control characters — stored as `""` at
  `initialize`; refused at registration.
- `get_bucket` faults during chain revocation — actor rows deleted, index
  and provider rows left to TTL, WARNING; covered.

### Verification

- [x] Phase 1's checks re-run green on both backends
- [x] `grep -n "_mcp_client_info_cache" actingweb/oauth2_server/` is empty

### Implementation Status: Complete

Notes (2026-09-25):

- A third cross-user reader of the client-info cache, not in the report:
  the web OAuth callback (`handlers/oauth2_callback.py`) looked the cache up
  by `remote_addr:hash(User-Agent)` to name the trust row. The lookup was
  also broken (it read a `client_info` key inside the returned dict, so only
  a crafted `clientInfo` carrying that key matched). Removed; the platform
  there is the sanitised User-Agent.
- `client_platform` (a User-Agent or `clientInfo.implementation`) is
  sanitised too, capped at 200, at the MCP trust write, the web callback,
  `TrustManager.create_or_update_oauth_trust` and both trust GET routes.
- `TrustManager.create_or_update_oauth_trust` sanitises all three client
  fields itself, so the `desc` seed is safe whatever the caller passes.
- The MCP 503 body is a JSON-RPC error `-32603` on both `GET /mcp` and the
  POST; `Retry-After: 5`.
- `_strict_read` expires rows past their `ttl_timestamp` (the strict reads'
  contract on both backends), so a consumed refresh token past its
  re-stamped TTL now reads as absent rather than reaching the past-window
  branch; the answer (`invalid_grant`, nothing revoked) is the same.
- `cleanup_expired_tokens()` now raises on a store fault instead of
  deleting the index row of a token it could not read (the old lookup's
  `None` took the "orphaned index entry" branch). FIXED entry.
- `tests/test_mcp_session_key.py` pinned the User-Agent fallback; it now
  pins its absence.
- The integration check reads the sanitised name from the `/oauth/register`
  response: the DCR trust row lives on the system actor, whose trust list
  the integration harness cannot read as creator.
- `tests/test_mcp_refresh_rotation.py`'s theft-with-unreadable-bucket test
  covers the corrected Phase 1 failure scenario.
- Checks: ruff, format, pyright clean; full tier on DynamoDB 3606 passed; on
  PostgreSQL all passed except the same two filed benchmark tests.

---

## Phase 3: Docs, spec, migration guide, and the todos that carry the deferred items

### Changes

- `CHANGELOG.rst` "Unreleased":
  - SECURITY: `AwProxy` and the two other DEBUG body lines (what is logged
    now; key names of a property write are property names); trust list
    credentials (**Behavior change** sentence; per-relationship GET
    unchanged; spec example moved); PKCE binding on the library authorize
    paths (`S256` required there, `plain` still accepted at exchange and
    why; `redirect_uri` compared at exchange); MCP refresh-token rotation
    (**Behavior change**: single-use refresh tokens, 60 s grace, theft beyond
    grace revokes the family and answers `invalid_grant`, the old access
    token is revoked on rotation, **the revocation is per-process and
    another worker may honour the old access token for up to 300 s**; the
    per-refresh WARNING is gone); authorization codes single-use atomically.
  - SECURITY (Phase 2): an unauthenticated `initialize` could name another
    user's MCP trust row (the callback-time write is gone); client-supplied
    names are sanitised at write and in both trust GET routes (**Behavior
    change**, `desc` included, never capped); the raw-name INFO log line.
  - CHANGED (Phase 2): a token-store fault answers 503 `Retry-After` on
    `/mcp` and 500 `server_error` on refresh (**Behavior change**; was 401 /
    `invalid_grant`); `TokenStoreUnavailable` raised by
    `validate_access_token` / `validate_mcp_token`; `Attributes.loaded`;
    the live `clientInfo` cache no longer falls back to a User-Agent key.
  - FIXED: DCR honours `token_endpoint_auth_method: none`, the refresh grant
    accepts public clients, the Codex symptom, **pre-3.15 registrations
    must be re-created**; token-endpoint error codes; Basic header parsed
    alongside a body `client_id`.
  - CHANGED: **Breaking:** `secret` and `verification_token` are gone from
    `GET /{actor_id}/trust` (the wire-shape line, `CHANGELOG.rst:900-909`
    shape); a `none` registration response omits `client_secret`;
    confidential registrations gain `client_secret_expires_at: 0`; public
    clients are refused `client_credentials`; registration rejects unknown
    auth methods with `invalid_client_metadata`; `/oauth/token` runs a
    throttled purge of expired MCP token rows.
- `docs/migration/v3.15.rst` (new) + `docs/migration/index.rst` toctree and
  summary paragraph. "Start here": (1) the trust-list fields, (2) MCP
  refresh tokens are single-use — a client that replays its original token
  works once and then gets `invalid_grant` and a dead chain every hour; what
  to persist, (3) **connectors added before 3.15 with public-client auth
  (Codex, ChatGPT) must be removed and re-added once**, (4) custom
  authorize templates must carry the two hidden PKCE inputs, (4b) callers
  of `validate_access_token` / `validate_mcp_token` handle
  `TokenStoreUnavailable` and consumers reading `_bucket_loaded` switch to
  `Attributes.loaded`, (5) consumers
  that quieted `actingweb.aw_proxy` can drop the override, (6) PostgreSQL
  operators: which reaper removes consumed token rows.
- `docs/protocol/actingweb-spec.rst:1486-1520`: one sentence after the MUST
  ("The list response MUST NOT include the shared secret or the verification
  token; those are read from the individual relationship URI, see Reading
  Trust Relationship Data"), and both example rows lose `"secret"`.
  `:1754-1758` unchanged.
- `docs/guides/trust-relationships.rst`: "What the list returns" note under
  the endpoint list.
- `docs/guides/oauth2-setup.rst`: "Client Types" (`:146`) gains public
  clients; `:63`, `:68`, `:347`, `:389` stop reading `client['client_secret']`
  unconditionally; "Security Considerations" (`:305`) gains PKCE `S256`,
  rotation, the 60 s grace and what it costs, the per-process cache window.
- `docs/guides/mcp-applications.rst:1147-1162`: the DCR example uses
  `.get("client_secret")` and shows a `none` registration.
- `docs/reference/routing-overview.rst`: entries for `/oauth/register`,
  `/oauth/authorize`, `/oauth/token` with their error contract (there are
  none today, only `/oauth/spa/token` at `:208-218`).
- `docs/guides/troubleshooting.rst`: "connector asks to log in again every
  hour" → refresh-token reuse, with the cause.
- `docs/reference/security.rst`: bullets on the three DEBUG lines, MCP
  rotation next to the SPA bullet (`:55`), and the cross-process window.
- `docs/guides/database-maintenance.rst`: which reaper each backend relies
  on for consumed MCP token rows.
- `docs/guides/logging-and-correlation.rst`: the DEBUG line's new shape.
- `token_manager.py`, `client_registry.py`, `oauth2_server.py` docstrings:
  rotation, single-use codes, `_authenticate_client` and public-client
  semantics stated where the code is.
- `thoughts/todo/mcp-oauth-connector-conformance-followups.md`: add the
  unbound-confidential-code note; re-check all todo line references against
  the branch.
- `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md` and its
  `INDEX.md` row are **deleted** when Phase 1 lands.

### New Tests, both unit and integration tests

- Docs build check as configured in `Makefile` (confirm which of
  `sphinx-build -W` / rst lint the project runs); no code tests. Phases 1-2's
  suite runs again after docstring edits.

### Failure Scenarios

- A consumer reads the spec example and expects `secret` in the list — the
  migration guide and the CHANGED line name it.
- A PostgreSQL operator has no pg_cron job — the token-endpoint purge covers
  it; the guide says so.

### Verification

- [x] `grep -n '"secret"' docs/protocol/actingweb-spec.rst` shows only the
      POST body and the per-relationship GET examples
- [x] `docs/migration/index.rst` lists v3.15 first
- [x] Phase 1 and Phase 2 checks re-run green

### Implementation Status: Complete

Notes (2026-09-25):

- Changelog entries under `Unreleased` cover Phases 1 and 2: six SECURITY,
  seven CHANGED (two **Breaking:**), three FIXED. The workflow-contract
  entry already under CHANGED stays.
- `docs/migration/v3.15.rst` has seven "Start here" items: the plan's six
  plus `TokenStoreUnavailable` / `Attributes.loaded` from Phase 2.
- Docs also touched beyond the list: `docs/guides/trust-relationships.rst`
  mentions the sanitised text fields; `docs/reference/security.rst` gained
  "Trust API and client-supplied text" and "Logging" subsections;
  troubleshooting gained the public-client `invalid_client` and the `/mcp`
  503 entries.
- `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md` and its
  `INDEX.md` row are deleted. The conformance todo's line references were
  re-checked against this branch, and it gained the unbound-confidential-code
  item and a note that 3.15 closed the cross-user name write.
- Checks: ruff, format, pyright clean; `sphinx-build -W` succeeds. The only
  code change after the Phase 2 full-tier runs is a docstring.

---

## Phase 4: Release 3.15.0

### Changes

- **Pre-release first.** `3.15.0rc1` in `pyproject.toml`,
  `actingweb/__init__.py` and a `v3.15.0rc1` changelog heading; PR, merge,
  tag, TestPyPI (the `CLAUDE.md` pre-release path). Install it in the
  consumer's dev deployment and run one pass with each of claude.ai, Claude
  Code, Codex and ChatGPT: a fresh registration, code exchange, a refresh
  after more than 60 s, a deliberate replay of the consumed refresh token,
  and a pre-3.15 registration confirming the reconnect note, and — for
  Phase 2's deduced decision — that each connector sends an authenticated
  `initialize` after OAuth (its trust row shows its `clientInfo` name, not
  only the DCR name). The curl pass
  in Phase 1 does not stand in for this; four named connectors motivated
  the release and the rotation contract is untested against any of them.
  A finding here is a Phase 1 or 2 fix and an `rc2`.
- **Deploy the rc to `demo.actingweb.io`.** Point `../actingwebdemo` at
  `actingweb==3.15.0rc1` (TestPyPI index, per the `CLAUDE.md` pre-release
  install line) and deploy it to `demo.actingweb.io`, so the library's own
  reference app (`examples/demo/`) runs the rc against a real provider
  alongside the consumer's dev deployment. Walk the same connector pass
  against it where a connector can reach it. The stable `3.15.0` waits for
  this deployment to be up and clean too.
- Then `3.15.0`: version files, rename the rc heading to `v3.15.0: <date>`
  folding the rc notes in, a new empty "Unreleased" above it, a `.. note::`
  at the top of the entry pointing at `docs/migration/v3.15.rst` (the
  3.14.0 entry's shape).
- Commit `Release v3.15.0`, push the PR, CI green on both backends, merge,
  tag the merge commit on master, push the tag (per `CLAUDE.md`).
- Delete `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md` and its
  index row; set this plan to `done` after `/verify_implementation`.
- Tell the consumer: switch `read_service_bucket` from `_bucket_loaded` to
  `Attributes.loaded`; its suspended-account middleware can fail closed on
  `TokenStoreUnavailable`; its own `client_name` sanitising can stay (the
  library now does the same at write and on the trust routes); drop the
  `actingweb.aw_proxy` logger override; confirm
  its MCP clients persist rotated refresh tokens; its own OAuth password
  path is unaffected (`plain` still exchanges, no `redirect_uri` stored);
  users with Codex/ChatGPT connectors added before the upgrade reconnect
  once. **[Updated 2026-09-25]** Also: `/oauth/logout` called with an MCP
  bearer token now revokes that token's whole chain (Iteration 18), and
  answers 503 with `Retry-After` when the store faults: the consumer's MCP
  clients should retry a 503 logout (Iteration 22); a custom
  attribute backend, if the consumer has one, must accept
  `conditional_update_attr(ttl_seconds=)` and `delete_by_chain(defer_name=)`.
  **[Updated 2026-09-27, from
  `thoughts/plans/2026-09-27-refresh-grace-setting.md`]** Also: bump the pin
  to the rc; the refresh grace period is now
  `with_refresh_token_grace(seconds)` (0 to 60, default 60, both ladders),
  and the consumer needs no change to it (their feedback: no value up to
  60 s covers a 336 s gap); the SPA store now reads a consumed token past
  its own `expires_at` as expired, not theft (`c280bcf`). For their #109,
  point at the SPA guide's "Refreshing reliably on native and mobile
  clients": no refresh started during a dark wake or once sleep is
  announced; a power assertion / `beginBackgroundTask` around an in-flight
  refresh; a timeout on the refresh request; a failed persist of the new
  refresh token is a failed refresh; keep single-flight, the final 401 and
  keep-on-ambiguous-failure, without counting on a retry after sleep.

### New Tests, both unit and integration tests

- None; CI on the tag validates the version files match.

### Failure Scenarios

- Tag pushed before both CI backends are green — the release workflow
  re-runs tests and refuses; `CLAUDE.md` step 5 is the guard.

### Verification

- [ ] `git tag -l v3.15.0` on master after merge; GitHub Release created;
      PyPI shows 3.15.0
- [ ] `pip install actingweb==3.15.0` in a scratch venv imports and reports
      `__version__`

### Implementation Status: In Progress

**[Updated 2026-09-28] rc1 progress.**
- `3.15.0rc1` was tagged on the PR #149 merge commit `8c0b8d8`, published
  to TestPyPI, and has a GitHub pre-release.
- actingweb_mcp's full test suite against rc1 from TestPyPI: 4803 passed.
  The 3 errors were Stripe webhook tests that need DynamoDB Local on :8000,
  which was not running there, so they are environment, not rc1.
- actingwebdemo #29 pinned rc1, refreshed its lock (pyjwt 2.13 → 2.15), and
  changed its deploy to follow the pin on push, pre-releases included.
  demo.actingweb.io runs rc1: the deploy log shows actingweb 3.15.0rc1,
  pyjwt 2.15.0 and cryptography 50.0.0.
- The owner tested the demo manually on 2026-09-28: all OK. The demo has no
  MCP, so this covers the OAuth2 sign-in, SPA and protocol paths only.
- actingweb_mcp signed off on rc1 (2026-09-28): full suite 4928 passed,
  12 skipped. Live through ngrok, Codex (public client, codex-cli 0.150.1)
  refreshes without a secret after its access token is revoked and keeps
  its tools (the #95/#96 defect). curl checks of registration, the token
  endpoint error codes, S256-only PKCE and the authorize forms all matched
  the docs. On both the MCP and SPA grants a reuse inside the grace rotates
  again and a reuse after about 70 s revokes the chain. Their migration
  took four small code changes. Not verified live: the SPA 503 on a store
  fault (covered by `tests/test_spa_token_retry_after.py`).
- From their production data (30 days): pre-3.15 registrations are all
  confidential, and only one external Codex client failed refresh (43
  "Invalid client secret"); five ChatGPT registrations never failed, and
  claude.ai / Claude Code send their secret. The reconnect guidance in the
  migration guide, troubleshooting guide, migration index and changelog was
  narrowed to clients that refresh without their issued secret.
- Live connector pass on rc1 (2026-09-28, consumer's dev deployment via
  ngrok; refreshes forced by deleting the access-token rows and waiting out
  the 5-min process cache, refresh #2 more than 60 s after #1):
  - Claude Code 2.1.283: public (`none`), S256, clientInfo "claude-code";
    refresh #1 and #2 OK with no secret and no reuse logged, so it stores
    the rotated token.
  - claude.ai: confidential (`client_secret_post`; its CIMD default fell
    back to DCR), S256, clientInfo "Anthropic/ClaudeAI"; refresh #1 and #2
    OK. A leftover Sep 24 (3.14) registration and 3.14-issued refresh
    token also refreshed under rc1: the upgrade path works.
  - ChatGPT: public (`none`), S256, clientInfo "openai-mcp". It does not
    refresh on a 401; it asks the user to reconnect (full sign-in, same
    registration). Refreshing on its own expiry clock works: with the dev
    access-token lifetime temporarily at 120 s (reverted), refresh #1
    (20:45:07) and #2 (20:48:39) were 200 with no secret, and the store
    showed one linear chain, every consumed token used once, no reuse or
    theft logged. So it stores the rotated token.
  - Codex desktop (codex-mcp-client 0.155.0-alpha): public, S256, refresh
    without a secret OK.
  - The deduced decision in Phase 2 holds: all four send an authenticated
    `initialize` (clientInfo seen on the trust rows).
- The connector pass is complete: all four clients pass. Nothing blocks
  `3.15.0`.

**[Updated 2026-09-26]** Sequencing changed. The hardening work (Phases 1–3,
Iterations 1–24) merges to `master` first through an ordinary PR with no
version bump, so the branch stops growing after five verifications. The
successor rule from
`thoughts/research/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md`
(a dropped rotation is not theft; both ladders) gets its own plan and PR
and lands before `3.15.0rc1`, because it changes the rotation contract the
rc connector pass validates. The rc release PR, with the bump, follows
that. The rest of this phase is unchanged.

---

## Iterations

Phases 1–3 are implemented and Phase 4 has not started, so the plan stays
`status: active` while these iterations are recorded (the project's rule: the
status changes when the last phase lands).

### 2026-09-25, after verification thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md

The six High and Medium fault-path and theft-detection issues from that
verification, plus `thoughts/todo/actor-trust-request-logs-peer-secret.md`.
Root causes and regression tests are in
`thoughts/research/2026-09-25-mcp-oauth-hardening-verification-fixes.md`.

#### 1. FastAPI `/mcp` answers 503 on a token-store fault

**Category**: Verification fix (bug)

**What changed**: `AsyncMCPHandler.post_async` catches `TokenStoreUnavailable`
around authentication and returns `_token_store_unavailable_response`, as
the sync handler does. Before, it answered HTTP 200 with a `-32603` error
whose text carried the actor id and bucket name.

**Files affected**:
- `actingweb/handlers/async_mcp.py` — the try/except and the import
- `tests/test_mcp_token_store_faults.py` — async POST (503), GET (503) and
  invalid token (401) cases

**Rationale**: Phase 2's 503 contract did not reach FastAPI deployments,
including the consumer's.

#### 2. The token endpoint reads the client registration strictly

**Category**: Decision changed

**What changed**: new `MCPClientRegistry.load_client_strict()`, which uses
`get_attr_strict` on the client index row and the client row, and raises
`TokenStoreUnavailable` on a fault. `_authenticate_client` and the
`client_credentials` public-client check use it, and `_authenticate_client`
compares the secret against the record it already loaded (one read instead
of two). A fault now answers 500 `server_error`.

**Files affected**:
- `actingweb/oauth2_server/client_registry.py` — `load_client_strict`
- `actingweb/oauth2_server/oauth2_server.py` — `_authenticate_client`, the
  client-credentials check, the `secret_equals` import
- `tests/test_mcp_token_store_faults.py` — fault in either read →
  `server_error`, and the refresh token still works afterwards; an unknown
  client is still `invalid_client`

**Rationale**: a store fault answered 401 `invalid_client` ("your
registration is bad") before `refresh_access_token`'s strict read could run.
That is worse than the `invalid_grant` Phase 2 set out to remove. The plan
had scoped strict reads to the two token lookups; this widens that scope by
one read.

#### 3. Chain revocation fails loudly instead of reporting success

**Category**: Verification fix (bug)

**What changed**: `_snapshot_bucket` catches a raising `get_bucket` (the
DynamoDB throttle shape) as well as the `loaded` fault (PostgreSQL).
`_revoke_chain` turns a raising `delete_by_chain`, or one that deleted
nothing, into `TokenStoreUnavailable`: the theft grant answers
`server_error` and leaves the chain for the next presentation to revoke.

**Files affected**:
- `actingweb/oauth2_server/token_manager.py` — `_snapshot_bucket`,
  `_revoke_chain` and its docstring
- `tests/mcp_token_double.py` — `raising_buckets`, `chain_delete_fault`
- `tests/test_mcp_refresh_rotation.py` — the raising-snapshot case and the
  zero/raise delete cases

**Rationale**: on DynamoDB the theft response aborted before anything was
revoked. On PostgreSQL it logged "revoked 0" and left the thief's branch
live. Corrects Phase 1's failure scenario "chain revoke — a bucket read
faults", which held only for PostgreSQL.

#### 4. Legacy refresh tokens join their new chain on first rotation

**Category**: Verification fix (bug)

**What changed**: `refresh_access_token` picks the chain id before
`_consume`. A record without one gets it stamped into the consumed row
(`_consume(stamp=)`, never into the compare-and-swap's expected value). The
grace path rotates in the chain the winner recorded.

**Files affected**:
- `actingweb/oauth2_server/token_manager.py` — `_consume` and
  `refresh_access_token`
- `tests/test_mcp_refresh_rotation.py` — a legacy replay after grace revokes
  the new chain

**Rationale**: a replayed pre-3.15 token removed only its own dead row, and
the chain it had rotated into survived. This affected every connector live
at upgrade time.

#### 5. `revoke_token` revokes the whole chain

**Category**: Verification fix (plan gap)

**What changed**: both branches call `_revoke_chain` when the record has a
chain. `_remove_refresh_tokens_in_chain` is deleted (it had one caller).

**Files affected**:
- `actingweb/oauth2_server/token_manager.py` — `revoke_token` and its
  docstring
- `tests/test_mcp_refresh_rotation.py` — the refresh-token and access-token
  branches, including a grace sibling

**Rationale**: after a logout, a consumed predecessor could still rotate
inside the 60 s grace window. RFC 7009 §2.1 says revoking a refresh token
SHOULD invalidate the same grant.

#### 6. The opportunistic purge runs before the grant

**Category**: Decision changed

**What changed**: `_handle_token_request` calls `maybe_purge_expired_tokens()`
before `handle_token_request` instead of after it.

**Files affected**:
- `actingweb/handlers/oauth2_endpoints.py` — call order and comment
- `tests/test_oauth2_token_endpoint_errors.py` — the order test and the
  fault-does-not-fail-the-grant test

**Rationale**: the first purge on each process (the first ever on an
existing PostgreSQL deployment) ran after the refresh token was consumed. A
slow purge could make the response time out, and the client's retry after
60 s then read as theft. Seeding the throttle at import was rejected, because
Lambda containers rarely live an hour and the purge would never run there.
Bounding the DELETE would change the backend protocol and was not needed.

#### 7. Credential logging outside the plan's three lines

**Category**: Verification fix (bug; from the todo)

**What changed**: `actor.py` summarises the async reciprocal-trust request
body (INFO; it carried `secret` and `verify`), the subscription create and
callback bodies, and the peer-info responses. `token_manager.py` masks
authorization codes in the lookup and removal helpers and in the five
provider-token log lines (their row names embed the code), and masks token
names in `revoke_client_tokens`. `fastapi_integration.py` summarises the
decrypted MCP state and the authorize template values. The todo file and its
`INDEX.md` row are deleted.

**Files affected**:
- `actingweb/actor.py`, `actingweb/oauth2_server/token_manager.py`,
  `actingweb/interface/integrations/fastapi_integration.py`
- `tests/test_actor_logging_redaction.py` (new),
  `tests/test_mcp_auth_code_single_use.py` — the code is never logged in full
- `thoughts/todo/actor-trust-request-logs-peer-secret.md` (deleted),
  `thoughts/todo/INDEX.md`

**Rationale**: the same class of exposure as the release's headline
SECURITY entry, at INFO. The new test found the provider-token key leak,
which the todo had missed.

**Docs for the batch**: `CHANGELOG.rst` has a new SECURITY entry (item 7) and
wider rotation (3–5), store-fault (1–2) and purge (6) entries.
`docs/migration/v3.15.rst` covers rotation and store faults.

**Checks**: the fast tier after all seven items (2646 passed, 23 skipped;
ruff, format and pyright clean). Full tier after the batch:
DynamoDB 3623 passed, 31 skipped, 1 error
(`test_hot_path_n_plus_one.py::…::test_items_and_values_are_bulk_reads`,
a DynamoDB Local lock timeout; 11 passed when re-run alone); PostgreSQL 3512
passed, 140 skipped, 2 failed (the two benchmark subscription tests filed in
`benchmark-subscription-tests-pass-url-to-boolean-callback.md`).
`test_mcp_oauth2.py` and `test_mcp_refresh_rotation_backend.py` pass on both
backends (strict client read, stamped CAS). `sphinx-build -W` clean. A
later docstring-only edit was re-checked with ruff and format.

Not in this batch: verification issue 7 is filed as
`thoughts/todo/mcp-cleanup-expired-tokens-strict-read.md`. Issue 8 is item 7
above. Issues 9–11 (Low) followed in the next batch.

### 2026-09-25, low-severity items of the same verification

The owner asked for issues 9, 10 and 11 of the verification to be fixed as
well. Numbering continues.

#### 8. Live `clientInfo`: token entry first, every string sanitised, the cache locked

**Category**: Verification fix (issues 9, 11 client-info items)

**What changed**:
- `_resolve_live_client_info` reads the bearer-token entry before the
  `Mcp-Session-Id` entry, because the session id is chosen by the client.
- `_sanitized_client_info` sanitises every string in `clientInfo`, nested
  ones included: `name`, `version` and `title` are capped at 80, others at
  200, and nesting past three levels is dropped.
- `_cache_client_info` and `get_stored_client_info` hold a lock.
- The `initialize` comment and the `_resolve_transport_session_id` docstring
  no longer describe the removed User-Agent key.
- A dead `global` is removed from `_handle_tools_list`.

**Files affected**:
- `actingweb/handlers/mcp.py`
- `tests/test_mcp_client_info_cache.py`: token-over-session, full
  sanitising, and a threaded test that reproduced
  `RuntimeError: dictionary changed size during iteration` before the lock
  (the switch interval is forced to 1 µs)

**Rationale**:
- An unauthenticated `initialize` naming a victim's session could override
  the victim's own entry.
- Unsanitised `title` and nested fields reached `MCPContext.client_info`.
- A threaded server could crash an `initialize` with the RuntimeError above.

#### 9. Rotation evicts one token without cancelling every in-flight cache fill

**Category**: Verification fix (issue 11)

**What changed**:
- `clear_token_from_cache(actor_wide=False)` records a per-token eviction
  (`_record_token_eviction`), kept for 120 s and pruned, instead of bumping
  the global cache generation.
- The token-cache fill checks `_token_fill_still_valid(token, seq)` as well
  as the global generation.

**Files affected**:
- `actingweb/handlers/mcp.py`
- `tests/test_mcp_revocation_evicts_caches.py`, `TestTokenOnlyEviction`

**Rationale**:
- Each hourly refresh of any client cancelled every concurrent cache fill
  in the process.
- The race the bump guarded against (an in-flight read re-caching the
  rotated access token) is still closed, now per token.
- Actor-wide revocation keeps the global bump.

#### 10. The callback test is behavioural

**Category**: Verification fix (issue 10)

**What changed**:
- `tests/test_oauth2_pkce_binding.py::TestCallbackDoesNotUseCachedClientInfo`
  fills the client-info cache with a spoofed entry under three keys, drives
  the real provider callback, and asserts that no trust write carries the
  spoofed name or version.
- The `hasattr` test is removed.

**Files affected**: `tests/test_oauth2_pkce_binding.py`,
`tests/test_mcp_client_info_cache.py`

**Rationale**:
- The structural test would pass if the write came back under another
  name.
- The new test cannot be shown failing against the old code: the old
  callback no longer exists on this branch independently of its
  dependencies.

#### 11. Revoking a deleted client's tokens reports a store fault

**Category**: Verification fix (issue 11); the fix direction deviates from
the verification's suggestion

**What changed**:
- `revoke_client_tokens` reads both buckets through `_snapshot_bucket`,
  revokes what it could read, and raises `TokenStoreUnavailable` naming
  the unreadable bucket.
- `delete_client` catches the exception, logs at ERROR, and **still
  deletes the client**.
- Token names in its DEBUG lines are masked (done in item 7).

**Files affected**:
- `actingweb/oauth2_server/token_manager.py`,
  `actingweb/oauth2_server/client_registry.py`
- `tests/test_mcp_token_store_faults.py`: the revoke raises; delete still
  deletes, and the client's refresh token then answers `invalid_client`

**Rationale**:
- The verification suggested failing the delete. That would keep a live
  registration able to refresh for 30 days.
- Deleting the client disables every refresh token at once. What remains
  are access tokens with up to one hour left, and the ERROR says so.

#### 12. Body and header secrets that disagree are refused

**Category**: Verification fix (issue 11); decision updated

**What changed**:
- The token handler answers `invalid_request` when the body
  `client_secret` and the Basic header's secret are both present and
  differ.
- Identical duplicates are accepted.

**Files affected**:
- `actingweb/handlers/oauth2_endpoints.py`
- `tests/test_oauth2_public_clients.py`: the old "body secret wins" test
  becomes "differing secrets are refused" and "identical secrets are
  accepted"

**Rationale**:
- The body silently won over the header (RFC 6749 §2.3.1).
- Refusing only a disagreement avoids breaking a client that sends the
  same secret in both places.

#### 13. Key names in log summaries are sanitised

**Category**: Verification fix (issue 11)

**What changed**: `summarize_payload` runs key names through
`sanitize_client_name(..., max_len=64)`.

**Files affected**: `actingweb/log_summary.py`, `tests/test_log_summary.py`

**Rationale**: a peer chooses the keys. A newline in a key forged a log
line, and a long key flooded the log.

#### 14. `client_credentials` reads the client once

**Category**: Verification fix (issue 11)

**What changed**:
- `_authenticate_client` is split into the strict load and
  `_check_client_credentials(record, ...)`.
- The `client_credentials` grant checks the record it already loaded for
  the public-client test.

**Files affected**:
- `actingweb/oauth2_server/oauth2_server.py`
- `tests/test_oauth2_public_clients.py`:
  `load_client_strict.call_count == 1`

**Rationale**: two index and actor reads became one on that grant. The
other grants were already down to one read after item 2.

#### 15. One compare-and-swap and one purge throttle for both token stores

**Category**: Verification fix (issue 11; refactor)

**What changed**:
- New internal `actingweb/single_use.py` with `consume_once()` and
  `PurgeThrottle`.
- `OAuth2SessionManager.try_mark_refresh_token_used` and the MCP
  `_consume` delegate to `consume_once`.
- Both `maybe_purge_expired_tokens` use a `PurgeThrottle` (`_purge_throttle`
  in `oauth_session.py`, `_mcp_purge_throttle` in `token_manager.py`)
  instead of the module float.
- The SPA side now deep-copies the record, where it used to shallow-copy
  it, and gains `stamp=` without using it.

**Files affected**:
- `actingweb/single_use.py` (new), `actingweb/oauth_session.py`,
  `actingweb/oauth2_server/token_manager.py`
- `tests/test_oauth_session.py`, `tests/test_mcp_refresh_rotation.py`: the
  throttle reset
- `tests/test_single_use.py` (new)

**Rationale**: the two stores had line-for-line copies of the CAS,
re-stamp, lost-race re-read and throttle, so a fix to one would not reach
the other. Both SPA and MCP rotation suites pass unchanged apart from the
throttle reset.

**Docs for the batch**: `CHANGELOG.rst`
- the client-info SECURITY entry gains the lookup order, thread safety and
  full sanitising;
- the logging entry gains the key-name rule;
- the Basic-header FIXED entry changes;
- a new FIXED entry covers client-deletion revocation.

**Checks**: ruff, format and pyright are clean. On the Full tier, DynamoDB
had 3637 passed and 31 skipped with no errors. PostgreSQL had 3526 passed,
140 skipped and 2 failed; the failures are the benchmark subscription tests
already filed in
`benchmark-subscription-tests-pass-url-to-boolean-callback.md`.
`sphinx-build -W` is clean.

### 2026-09-25, after verification thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure-2.md

The owner asked for all ten issues of the re-verification to be fixed, and
chose to route MCP tokens through `/oauth/logout` rather than correct the
docs (issue 2). Numbering continues. Root causes and regression tests:
`thoughts/research/2026-09-25-mcp-oauth-hardening-verification-fixes-2.md`.

#### 16. A faulted compare-and-swap is a store fault, and the consumed row's TTL is written by the swap

**Category**: Bug fix (re-verification issues 1 and 3)

**What changed**:
- `consume_once` tells a lost race from a fault. Both backends answer
  `False` from `conditional_update_attr` for either, so the loser now
  re-reads with `get_attr_strict`:
  - a used row means another caller won, as before;
  - a row still unused, or a re-read that faults, raises the new
    `single_use.StoreFault`.
- The MCP `_consume` turns `StoreFault` into `TokenStoreUnavailable`, so the
  refresh and code grants answer `server_error` and the token or code stays
  usable.
- The SPA `try_mark_refresh_token_used` catches `StoreFault` and returns
  `(False, None)`: the SPA endpoint keeps answering 401 on that path, as it
  always has. It never deleted there, so this is a deliberate non-change and
  its fault contract stays outside this plan.
- `refresh_access_token` no longer deletes a consumed row that lacks
  `used_at`; it refuses it.
- The best-effort `set_attr` re-stamp after the swap is gone. The swap
  writes the TTL itself: `conditional_update_attr` gains an additive
  `ttl_seconds=` on the `Attributes` wrapper, `db/protocols.py`, both
  backends and the three test doubles. It is never an upsert, so a
  revocation landing between the swap and the mint is no longer undone by
  re-creating the consumed row. The `consume_once` keyword is renamed
  `restamp_ttl` → `consumed_ttl`.
- Residual, accepted: a winner whose chain is revoked between its swap and
  its mint still gets its own new pair; that race needs a transaction to
  close.

**Files affected**:
- `actingweb/single_use.py`: `StoreFault`, strict re-read, TTL in the swap
- `actingweb/oauth2_server/token_manager.py`: `_consume` translates the
  fault; no delete on a missing `used_at`
- `actingweb/oauth_session.py`: catches `StoreFault`
- `actingweb/attribute.py`, `actingweb/db/protocols.py`,
  `actingweb/db/dynamodb/attribute.py`, `actingweb/db/postgresql/attribute.py`:
  `ttl_seconds=` on `conditional_update_attr`
- `tests/mcp_token_double.py`: `cas_fault`, TTL recorded by the swap;
  `tests/test_oauth_session.py`, `tests/test_oauth2_spa_refresh_rotation.py`:
  doubles gain `ttl_seconds=` and `get_attr_strict`
- `tests/test_mcp_refresh_rotation.py`, `tests/test_mcp_auth_code_single_use.py`:
  new tests

**Rationale**: one throttle at the swap deleted a legitimate refresh token
and answered `invalid_grant`, the failure Phase 2 exists to remove. The
upsert re-stamp could revive a revoked row. Four new tests fail on `253ee76`
and pass now: `test_cas_fault_is_a_store_fault_not_a_dead_token`,
`test_cas_fault_with_unreadable_store_is_a_store_fault`,
`test_revocation_between_swap_and_mint_is_not_undone`,
`test_cas_fault_leaves_the_code_exchangeable`.

#### 17. Revocation and deletes confirm what they did

**Category**: Bug fix (re-verification issues 4, 5, 6, 7, 8)

**What changed**:
- `_revoke_chain` takes `anchor=(bucket, name)`, the row its caller just
  loaded, and uses it in two ways:
  - It is deleted last: `delete_by_chain` gains an additive `defer_name=`
    (protocol, both backends, the double). DynamoDB deletes row by row and
    defers that row; PostgreSQL's single DELETE ignores it. A fault
    part-way therefore leaves the replayed token for the next presentation
    to retry from.
  - When the delete removed nothing, a strict read of the anchor tells a
    chain another revocation already removed (not a fault; logged at INFO,
    returns 0) from a failed delete (`TokenStoreUnavailable`).
- `_revoke_chain` evicts the actor's caches in a `finally`.
- `revoke_token` removes the presented token (and, for a refresh token, its
  access token) in a `finally` around the chain revocation, then lets the
  fault propagate.
- New `single_use.delete_confirmed()`: a conditional delete, then a strict
  read when that answers False. `delete_attr` cannot report a fault:
  DynamoDB swallows it and answers True. It is used by:
  - `_remove_access_token(actor_id=...)`, which now returns whether the row
    is gone and logs an unconfirmed delete at ERROR (the rotation path);
  - the new `_remove_refresh_token_row(actor_id, token)`;
  - `revoke_client_tokens`, which passes the actor it already knows, counts
    only confirmed deletes, and raises `TokenStoreUnavailable` naming the
    unconfirmed ones;
  - `delete_client`, which confirms the client row and its index row and
    answers False only when neither is gone. The token endpoint needs both,
    so either one gone disables the client.
- `load_client_strict` uses `self.clients_bucket`.
- `revoke_token` removes the presented token through its known owner
  (`_remove_access_token(actor_id=...)`, `_remove_refresh_token_row`). That
  path skips the index read a fault would fail, and confirms the delete.
- `Trust.delete` logs "Deleted OAuth2 client" only when `delete_client`
  answered True; `delete_client` logs its own ERROR otherwise.
- `revoke_token`'s docstring no longer claims a pre-chain token revokes the
  token it is linked to. The removed helpers never did: they were stubs that
  only logged "not implemented" (`2d5eaa4`). It also gains a `Raises:`
  section. The comment on `access_token_id` names its real reader, a
  pre-3.15 process in a rolling deploy.

**Files affected**:
- `actingweb/single_use.py`: `delete_confirmed`
- `actingweb/oauth2_server/token_manager.py`: `_revoke_chain`,
  `revoke_token`, `_remove_access_token`, `_remove_refresh_token_row`,
  `revoke_client_tokens`
- `actingweb/oauth2_server/client_registry.py`: `delete_client`,
  `load_client_strict`
- `actingweb/trust.py`: the INFO line after `delete_client`
- `actingweb/db/protocols.py`, `actingweb/db/dynamodb/attribute.py`,
  `actingweb/db/postgresql/attribute.py`: `defer_name=`
- `tests/mcp_token_double.py`: `delete_attr_conditional`, `delete_faults`,
  the `"partial"` chain-delete fault, `defer_name`
- `tests/test_mcp_refresh_rotation.py`, `tests/test_mcp_token_store_faults.py`:
  new tests

**Rationale**: the backends report faults as ordinary results, and the
revocation paths took those results at face value. The first six tests
below fail on `253ee76` and pass now:
- `test_revocation_fault_still_removes_the_presented_token_and_evicts`
- `test_a_chain_revoked_concurrently_is_not_a_fault`
- `test_partial_chain_delete_leaves_the_replayed_token_to_retry_from`
- `test_unconfirmed_delete_of_the_old_access_token_is_logged`
- `test_delete_client_fails_when_nothing_is_confirmed_deleted`
- `test_revoke_client_tokens_counts_only_confirmed_deletes`
- `test_delete_client_succeeds_when_its_index_row_is_gone` (coverage for
  the rule; it passes on both)

#### 18. `/oauth/logout` revokes an MCP token and its chain

**Category**: Decision changed / new functionality (re-verification issue 2;
owner chose to route rather than correct the docs)

**What changed**:
- `_handle_provider_token_logout` sends a token carrying the MCP token
  manager's prefix (`aw_`) to the new `_handle_mcp_token_logout`, which calls
  `ActingWebTokenManager.revoke_token` and so revokes the whole chain. SPA
  session tokens come from `config.new_token()`, which is hex and can never
  carry the prefix; they keep the session-store path.
- A `TokenStoreUnavailable` is logged at ERROR and answered with the
  endpoint's existing success shape and the message "Logged out (token
  revocation failed)". The presented token is still removed. The route's
  contract (always success, cookies cleared) is unchanged.
- `ActingWebOAuth2Server.handle_logout_request` (SDK-only; nothing routes to
  it) answers "Logged out (with errors)" when revocation raised, instead of
  "Successfully logged out".
- The SPA refresh-chain gap (`thoughts/todo/logout-does-not-revoke-refresh-chain.md`)
  is untouched and stays open.

**Files affected**:
- `actingweb/handlers/oauth2_endpoints.py`: prefix dispatch,
  `_handle_mcp_token_logout`
- `actingweb/oauth2_server/oauth2_server.py`: `handle_logout_request` message
- `tests/test_oauth2_logout_mcp_tokens.py` (new)

**Rationale**: the 3.15 changelog and migration guide promised that
`/oauth/logout` revokes an MCP token's chain, but no route reached the MCP
token manager. Three tests fail on `253ee76` and pass now:
`test_logout_revokes_the_mcp_token_and_its_chain`,
`test_logout_reports_a_revocation_fault_and_still_drops_the_token`,
`test_sdk_logout_does_not_claim_success_on_a_fault`.
`test_a_session_token_still_goes_to_the_session_store` pins the unchanged
SPA path.

#### 19. Session `clientInfo` entries have an owner; the smaller items

**Category**: Verification fix (re-verification issues 9 and 10)

**What changed**:
- Client-info cache entries carry an `owner`: the actor of the
  authenticated `initialize` that wrote them. That `initialize` now caches
  the session entry too, not only the token entry.
- An unowned write (an unauthenticated `initialize`) never replaces a fresh
  owned entry.
- `_resolve_live_client_info(actor_id)` still reads the token entry first.
  On an authenticated request it then:
  - uses a session entry owned by the same actor;
  - ignores one owned by another actor;
  - claims an unowned one for this actor (a client that initialised before
    signing in keeps its info).

  A hit resets the entry's age, so an active session keeps it past the
  ten-minute expiry and across token rotation. The four call sites pass the
  authenticated actor.
- Residual, documented in the docstring: after ten idle minutes an
  unauthenticated `initialize` that knows the session id can seed an entry
  before the owner's next request claims it.
- `initialize` no longer swallows a failure silently: `TokenStoreUnavailable`
  and any other exception are logged at WARNING.
- Token-only eviction records: `_token_eviction_pruned_through` holds the
  highest sequence pruned, and a fill whose snapshot predates it is refused.
  A read that stalls past the 120 s keep time can no longer cache a
  rotated-out token. This was chosen over raising the keep time, which only
  moves the bound.
- New tests drive the real fill in `authenticate_and_get_actor_cached`, not
  only the helper.
- `PurgeThrottle` uses `time.monotonic()`. `last_attempt` is `None` until the
  first claim, so a fresh process still purges on its first call on a host
  with short uptime.
- Docstrings:
  - `TokenStoreUnavailable` lists every raiser;
  - `refresh_access_token` gains `Raises:`;
  - `_snapshot_bucket` describes the PostgreSQL fault shape correctly.

**Files affected**:
- `actingweb/handlers/mcp.py`: owner, `_claim_client_info`, call sites,
  `initialize` logging, the pruned-through floor
- `actingweb/single_use.py`: monotonic `PurgeThrottle`
- `actingweb/oauth2_server/token_manager.py`: docstrings
- `tests/test_mcp_client_info_cache.py`: the spoof test now asserts that the
  owned entry survives, plus six new tests;
  `tests/test_mcp_trust_cache_key.py`: `TestRotationEvictionDuringFill`;
  `tests/test_single_use.py`, `tests/test_mcp_refresh_rotation.py`,
  `tests/test_oauth_session.py`: the throttle reset is `None`, and a
  clock-step test

**Rationale**: the token-first lookup protected only until the token entry
expired or rotated, and then fell back to a session entry anyone naming the
session could write. Nine tests fail on `253ee76` and pass now (listed in
the research note).

**Backend coverage for the batch**:
`tests/integration/test_mcp_refresh_rotation_backend.py::TestBackendKeywordsForSingleUse`
runs the two new protocol keywords on real DynamoDB and PostgreSQL:
- a swap with `ttl_seconds=` in the past makes the row read as absent, and a
  swap on a missing row creates nothing;
- `delete_by_chain(defer_name=)` still deletes the whole chain and nothing
  else.

It passes on both backends (4 passed each, run on their own after the Full
tier).

**Docs for the batch**:
- `CHANGELOG.rst`: the rotation SECURITY entry gains the consume-fault rule
  and the `/oauth/logout` **Behavior change**; the client-info entry gains
  ownership; the additive-keywords entry names the two protocol keywords;
  the client-deletion FIXED entry gains confirmed deletes and a **Behavior
  change**.
- `docs/migration/v3.15.rst`: the consume-fault bullet, logout with an MCP
  token, session-entry ownership, and a new "Custom database backends"
  section.
- The Phase 4 consumer message gains the logout and backend-keyword notes.

**Checks**:
- Fast tier: ruff, format and pyright clean; unit tests 2686 passed, 23
  skipped. Re-run after the last two changes in entry 17 (the owner path in
  `revoke_token`, the `Trust.delete` log line): same result.
- Full tier, DynamoDB: 3663 passed, 31 skipped, 0 errors.
- Full tier, PostgreSQL: 3554 passed, 140 skipped, 2 failed. The failures are
  the benchmark subscription tests already filed in
  `benchmark-subscription-tests-pass-url-to-boolean-callback.md`.
- `sphinx-build -W`: clean.

### 2026-09-26, after verification thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure-3.md

The owner asked for all eight issues of the third verification to be fixed.
Numbering continues. Root causes and regression tests:
`thoughts/research/2026-09-26-mcp-oauth-hardening-verification-fixes-3.md`.

#### 20. A revocation that faults keeps the presented token for the retry, and never reports an unconfirmed delete as done

**Category**: Bug fix (third verification issues 1 and 2; a regression from
Iteration 17)

**What changed**:
- When `_revoke_chain` raises, `revoke_token` evicts this process's cache
  (the token, and for a refresh token also its access token and the actor)
  and re-raises, leaving the presented token's row in place. Iteration 17
  deleted that row in a `finally`, which removed the anchor that
  `defer_name` had just kept for the retry. A logout that hit a store fault
  therefore left the chain's refresh token live with nothing able to revoke
  it.
- After a successful chain revocation, or for a chainless (pre-3.15) token,
  the presented token is deleted through its known owner and the delete is
  confirmed. A refresh token's linked access token is deleted first and the
  presented token last. An unconfirmed delete raises `TokenStoreUnavailable`
  rather than returning True, so `/oauth/logout` answers "Logged out (token
  revocation failed)", not "Successfully logged out".
- The docstrings of `revoke_token` and `_handle_mcp_token_logout` describe
  the retry contract.

**Files affected**:
- `actingweb/oauth2_server/token_manager.py`: `revoke_token`
- `actingweb/handlers/oauth2_endpoints.py`: `_handle_mcp_token_logout`
  docstring
- `tests/test_mcp_refresh_rotation.py`:
  `test_revocation_fault_still_removes_the_presented_token_and_evicts` is
  replaced by `test_revocation_fault_keeps_the_presented_token_to_retry_from`
  (parametrized over the zero, raise and partial chain-delete faults), and
  there are two new tests
- `tests/test_oauth2_logout_mcp_tokens.py`: the fault test becomes
  `test_logout_after_a_revocation_fault_can_be_retried`

**Rationale**: the two safeguards of Iteration 17 worked against each other
in `revoke_token`, which both reviewers of the third verification found
independently. Six tests fail on `6748937` and pass now.

#### 21. The Lows of the third verification

**Category**: Verification fix (third verification issues 3–8)

**What changed**:
- **Issue 3:** `revoke_client_tokens` loops over the two buckets with a
  per-token `try`. A token whose revocation raises is counted as unconfirmed
  and logged at ERROR. The rest are still revoked, and the final
  `TokenStoreUnavailable` names the count. The broad `except` around both
  loops, which swallowed a mid-loop failure and returned a partial count, is
  gone.
- **Issue 4:** a fresh owned client-info entry is replaced only by a write
  from the same owner. Another actor's authenticated `initialize` naming the
  session no longer blanks the owner's entry.
- **Issue 5:** `_claim_client_info` moves the entry to the newest end of the
  cache, so the size bound (which evicts in insertion order) evicts idle
  entries before one in use.
- **Issue 6:** the changelog's consume-fault sentence names MCP and says the
  SPA endpoint still answers 401. The changelog and the migration guide
  describe the logout retry after a failed revocation.
- **Issue 7:** every consume writes a random `consume_id`. When the swap
  answers False and the strict re-read finds this call's own `consume_id`,
  the write landed but its response was lost. That counts as a successful
  consume (logged at WARNING) instead of burning the code as "already
  used". A competing consume carries another id and is still refused.
- **Issue 8:**
  - The docstring of `test_revocation_between_swap_and_mint_is_not_undone`
    names the accepted residual.
  - The `StoreFault` ERROR line carries the actor and a masked record name.
  - The FastAPI cookie logout passes a failure message through
    (`_logout_message`) instead of always saying "Logged out successfully".

**Files affected**:
- `actingweb/oauth2_server/token_manager.py`: `revoke_client_tokens`
- `actingweb/handlers/mcp.py`: `_cache_client_info`, `_claim_client_info`,
  the `_resolve_live_client_info` docstring
- `actingweb/single_use.py`: `consume_id`, the lost-response branch, `_mask`
- `actingweb/interface/integrations/fastapi_integration.py`:
  `_logout_message`
- `CHANGELOG.rst`, `docs/migration/v3.15.rst`
- `tests/mcp_token_double.py`: `cas_lost_response`
- Tests:
  - `tests/test_mcp_token_store_faults.py`,
    `tests/test_mcp_client_info_cache.py`,
    `tests/test_mcp_auth_code_single_use.py`,
    `tests/test_oauth2_logout_mcp_tokens.py`: new tests
  - `tests/test_mcp_refresh_rotation.py`: the docstring

**Rationale**: every item is small and on a fault path or a documented
claim. Five tests fail on `6748937` and pass now:
- `test_revoke_client_tokens_counts_a_raising_delete_and_goes_on`
- `test_another_actors_authenticated_initialize_cannot_replace_an_owned_entry`
- `test_an_entry_in_use_survives_the_size_bound`
- `test_a_swap_whose_response_was_lost_still_exchanges_the_code`
- `test_fastapi_cookie_logout_passes_a_failure_message_through`

`test_a_competing_consume_is_still_refused` pins the unchanged race rule.

**Docs for the batch**:
- `CHANGELOG.rst`: the rotation SECURITY entry scopes the consume-fault rule
  to MCP (the SPA endpoint answers 401) and describes the logout retry after
  a failed revocation.
- `docs/migration/v3.15.rst`: the logout retry.

**Checks**:
- Fast tier: ruff, format and pyright clean; unit tests 2696 passed, 23
  skipped.
- Full tier, DynamoDB: 3675 passed, 31 skipped, 0 errors.
- Full tier, PostgreSQL: 3564 passed, 140 skipped, 2 failed. The failures are
  the benchmark subscription tests already filed in
  `benchmark-subscription-tests-pass-url-to-boolean-callback.md`.
- `sphinx-build -W`: clean.

### 2026-09-26, after verification thoughts/verifications/2026-09-26-mcp-oauth-hardening-and-credential-exposure.md

The owner's decisions on the fourth verification:
- issue 1: option (b), 503 with `Retry-After`;
- issue 2: fix;
- issue 3: fix the message;
- issue 4: add tests;
- issue 5: evict the client's access tokens on client deletion.

Root causes and regression tests:
`thoughts/research/2026-09-26-mcp-oauth-hardening-verification-fixes-4.md`.

#### 22. A faulted MCP logout answers 503 with Retry-After, and the kept token stays reachable

**Category**: Decision changed (fourth verification issue 1, the owner's
option b) and bug fix (issue 2)

**What changed**:
- `_handle_mcp_token_logout` returns the action `retry` on
  `TokenStoreUnavailable`. `_handle_logout_request` answers it with
  **503**, `Retry-After: 5` and `{"success": false, "error":
  "temporarily_unavailable", ...}`, and clears no cookies. Before, it
  answered 200 "Logged out (token revocation failed)", which no client
  retries. The token stays valid until the retry completes; options (a), a
  `revoked` mark, and (c), accept, were not taken. Both integrations already
  pass the handler's status and headers through (`fastapi_integration.py`
  merges `webobj.response.headers`; Flask copies status and headers).
- `_remove_access_token(actor_id=...)` and `_remove_refresh_token_row` keep
  the index row (and the provider row) when the actor row's delete is
  unconfirmed. Before, they deleted the index row anyway, so a retry could
  not resolve the token and logout then said "Successfully logged out"
  while the row lingered.

**Files affected**:
- `actingweb/handlers/oauth2_endpoints.py`: the `retry` action, 503 and
  `Retry-After`; the `_handle_mcp_token_logout` docstring
- `actingweb/oauth2_server/token_manager.py`: the two remove helpers
  return early on an unconfirmed delete
- `CHANGELOG.rst`, `docs/migration/v3.15.rst`: 503 and the retry
- Tests:
  - `tests/test_oauth2_logout_mcp_tokens.py`:
    `test_logout_after_a_revocation_fault_can_be_retried` asserts 503,
    `Retry-After` and the retry; new route tests for FastAPI and Flask
  - `tests/test_mcp_refresh_rotation.py`:
    `test_unconfirmed_delete_of_a_chainless_token_is_not_reported_revoked`
    now retries

#### 23. FastAPI cookie logout reports a handler failure; route tests; client deletion clears the cache

**Category**: Bug fix and tests (fourth verification issues 3, 4 and 5)

**What changed**:
- `_logout_message` becomes `_logout_outcome(handler_response) ->
  (success, message)`. A handler status of 400 or more, or an `error` body,
  is a failure: `success: false` with the handler's message or error
  description. The web UI branch uses both values.
- Route-level tests through `TestClient` (FastAPI) and the Flask test
  client:
  - 503 and `Retry-After` pass through on both frameworks;
  - success is still 200;
  - the cookie branch reports a failed revocation and a handler 500.

  The cookie branch still clears only `oauth_token`. That predates this plan
  and the owner asked for tests only.
- `revoke_client_tokens` evicts each access token from this process's MCP
  token cache (`evict_caches_for_token`), confirmed delete or not, so a
  deleted client's cached token stops authenticating on that worker.

**Files affected**:
- `actingweb/interface/integrations/fastapi_integration.py`:
  `_logout_outcome`
- `actingweb/oauth2_server/token_manager.py`: `revoke_client_tokens`
- `CHANGELOG.rst`: the client-deletion entry names the cache eviction
- `tests/test_oauth2_logout_mcp_tokens.py`, `tests/test_mcp_token_store_faults.py`

**Rationale**: seven tests fail on `9e70e47` and pass now (listed in the
research note).

**Checks for the batch**:
- Fast tier: ruff, format and pyright clean; unit tests 2702 passed, 23
  skipped.
- Full tier, DynamoDB: 3681 passed, 31 skipped, 3 errors. All three are
  DynamoDB Local "waiting for a lock" teardown errors in
  `test_hot_path_n_plus_one.py` and `test_bulk_list_update_handles.py`;
  run on their own, both files pass (31 passed).
- Full tier, PostgreSQL: 3570 passed, 140 skipped, 2 failed. The failures are
  the benchmark subscription tests already filed.
- `sphinx-build -W`: clean.

### 2026-09-26, after verification thoughts/verifications/2026-09-26-mcp-oauth-hardening-and-credential-exposure-2.md

The fifth verification found a High regression from Iteration 22, the
fourth time the revocation fault path had been re-answered. The owner
agreed to settle it by stating the invariant (see the `[Added 2026-09-26]`
decision), fix only the High and Medium items, file the Lows, and close the
loop on the next run that has no High or Medium and no regression. Root
causes: `thoughts/research/2026-09-26-mcp-oauth-hardening-verification-fixes-5.md`.

#### 24. Revocation deletes the index row first; the property is pinned per path

**Category**: Bug fix and decision (fifth verification issues 1–4)

**What changed**:
- `_remove_access_token(actor_id=...)` and `_remove_refresh_token_row`
  delete the index row (and, for access tokens, the provider row) first and
  unconditionally, then confirm the actor row. An unconfirmed actor row is
  reported (the helper returns False, logs at ERROR) but the token is
  already dead on every worker. This reverts Iteration 22's "keep the index
  row for a retry", which had regressed rotation and client deletion.
- `revoke_token`'s refresh branch removes both the linked access token and
  the presented refresh token whatever the other's outcome. Its docstring
  states the two fault outcomes: a chain fault keeps the presented token as
  the handle (the owner's 503 decision stands); an unconfirmed single delete
  leaves a dead token whose retry only confirms.
- `_handle_logout_request` clears this process's MCP token cache on the
  `retry` outcome too, so a fault before `revoke_token` could evict does not
  leave a cached token serving for 300 s after a 503.
- New `TestAnUnconfirmedDeleteStillRevokes` pins the property, not the
  mechanism, for rotation, `revoke_token` (access and refresh) and client
  deletion.
- The four Lows (5–8) are filed in
  `thoughts/todo/mcp-logout-fault-path-followups.md`.

**Files affected**:
- `actingweb/oauth2_server/token_manager.py`: the two remove helpers,
  `revoke_token`
- `actingweb/handlers/oauth2_endpoints.py`: cache clearing on `retry`, the
  `_handle_mcp_token_logout` docstring
- `CHANGELOG.rst`, `docs/migration/v3.15.rst`: the invariant replaces the
  "kept, stays valid until retry" wording
- `tests/test_mcp_refresh_rotation.py`: the property class; two existing
  tests now assert the token is dead
- `tests/test_oauth2_logout_mcp_tokens.py`: the cache-eviction test
- `thoughts/todo/mcp-logout-fault-path-followups.md` (new), `INDEX.md` row

**Rationale**: five tests fail on `fade3da` and pass now:
`TestAnUnconfirmedDeleteStillRevokes::test_rotation`,
`::test_client_deletion`,
`test_unconfirmed_delete_of_the_old_access_token_is_logged`,
`test_unconfirmed_delete_of_a_chainless_token_is_not_reported_revoked`, and
`test_a_lookup_fault_on_logout_still_evicts_the_cached_token`. The two
`revoke_token` property tests pass on both versions (a chain delete removes
the row before the faulted delete runs) and stand as coverage.

**Checks for the batch**:
- Fast tier: ruff, format and pyright clean; unit tests 2707 passed, 23
  skipped.
- Full tier, DynamoDB: 3686 passed, 31 skipped, 1 error: the DynamoDB Local
  "waiting for a lock" teardown flake in `test_bulk_list_update_handles.py`,
  which passes on its own (20 passed).
- Full tier, PostgreSQL: 3575 passed, 140 skipped, 2 failed: the benchmark
  subscription tests already filed.
- `sphinx-build -W`: clean.

## Evaluation Notes

Five evaluators (architecture, security, scalability, usability, tests and
code quality) reviewed the first draft against the tree at `2d5eaa4` on
2026-09-25. Every finding below quoted its line; the draft was rewritten
before the outside-voice pass.

### Architecture

- **Blocker, folded**: the draft's `validate_client` change was not
  "unchanged" — `client_registry.py:130` skips the compare on `None`, and
  `oauth2_server.py:154`, `:492`, `oauth2_endpoints.py:566` and
  `oauth_client_manager.py:198` all rely on that. Resolved by
  `_authenticate_client` in the grants (C.2) and leaving the registry alone.
- **Folded**: the consume step lacked the pre-CAS `used` check
  (`oauth_session.py:711-713`); an already-used row matches itself and
  re-rotates. Now the first step of `_consume`.
- **Folded**: `delete_by_chain` exists on both backends
  (`db/protocols.py:1210`); `_revoke_chain` uses it plus a snapshot for
  index rows and cache pops.
- **Folded**: "six independent files" was false; the phasing decision now
  says which files are shared and that C.1–C.3 precede C.4.
- **Folded**: the JSON `show_form` branch (`oauth2_endpoints.py:727-740`),
  the SDK registration path (`oauth_client_manager.py:65`,
  `regenerate_client_secret`), the integration helper's `KeyError`
  (`oauth2_helper.py:76`), and the authorize-path error collapse
  (deliberately left; recorded).

### Security

- **Blocker** (same as above), folded; plus the auth-code-grant regression
  test for a confidential client with no secret.
- **Folded**: authorization codes were not single-use atomically
  (`token_manager.py:149` read, `:181` write); now consumed by CAS before
  PKCE, with chain revocation on reuse.
- **Folded**: the per-process cache window (`mcp/invalidation.py:19`,
  `handlers/mcp.py:52`) is named in the SECURITY entry, the docstring and
  "What We're NOT Doing".
- **Folded**: the grace-window divergence is recorded as an accepted trade.
- **Folded**: `oauth2_endpoints.py:250` and `fastapi_integration.py:1349,
  :2470` get the same summary helper as the proxy.
- **Folded**: `redirect_uri` compared at exchange when stored.
- **Folded**: key-name cap and the property-name note.
- Checked clean by the evaluator: no request-side PKCE downgrade; `none`
  refresh binding is client-id plus rotation; handler-level trust strip is
  sufficient (`trust.py:74`, `:468`, `:125` are the only wire sites).

### Scalability

- **Folded**: `_revoke_chain` no longer goes through the per-row `_remove_*`
  helpers (5–9 round-trips each); `delete_by_chain` plus direct index
  deletes.
- **Folded**: nothing reaped the shortened TTL on PostgreSQL
  (`cleanup_expired_tokens` keys on `expires_at`, `token_manager.py:1198`);
  now `used_at`-aware cleanup plus a throttled token-endpoint purge, and the
  maintenance guide names the reaper per backend.
- **Folded**: the global refresh index row is re-stamped too, so it does not
  grow by one row per refresh for 30 days.
- **Folded**: `_remove_access_token(token, actor_id=)` skips the re-load and
  index re-read; a refresh is ~11 round-trips instead of ~16.
- **Folded**: replays after TTL lag must not read as theft — the explicit
  past-window branch (`oauth2_spa.py:674-687`).
- **Folded**: rotation pops one token instead of evicting the actor's
  caches (`handlers/mcp.py:2805-2814`).
- Trust-list copy: not a concern (`actor.py:786-799` already materialises
  every row).

### Usability

- **Folded**: pre-3.15 registrations stay confidential; reconnect note in
  "Start here" and the consumer message.
- **Folded**: the non-persisting-client trap documented for MCP
  (troubleshooting and migration), mirroring
  `spa-authentication.rst:1469-1483`.
- **Folded**: `client_secret_expires_at: 0`; Basic header parsed whenever
  present (`oauth2_endpoints.py:335`); the "headsers" typo.
- **Folded**: the doc pages that state the old behaviour
  (`oauth2-setup.rst:63,68,347,389`, `mcp-applications.rst:1147-1162`,
  `routing-overview.rst` with no `/oauth/*` entries).
- **Folded**: the absent-method message and the `"plain"` default at
  `oauth2_server.py:136`.
- **Folded**: the trust-list change appears under CHANGED as **Breaking:**
  as well as under SECURITY.
- Recorded: the single 60 s grace tier; the 400-vs-401 asymmetry with the
  SPA path.

### Tests and code quality

- **Folded**: the double must return copies (`test_oauth2_spa_refresh_rotation.py:48`
  returns by identity) and the CAS-loser test needs a monkeypatch; the
  "past window" case cannot rely on TTL (the double ignores `ttl_seconds`,
  `:51`) — seeded `used_at` instead.
- **Folded**: `unauthorized_client` for `none` + `client_credentials` was
  unreachable behind `oauth2_server.py:568`; the lookup now precedes the
  presence check.
- **Folded**: registry unit tests patch `actingweb.actor.Actor`
  (`client_registry.py:87` → `:426`).
- **Folded**: PKCE tests cover the HTML GET provider-button path, the JSON
  echo site and the `""`→`None` normalisation (`aw_web_request.py:14`).
- **Folded**: the draft's C had two mechanisms for one thing (registry
  ignore plus grant fallback); one place now.
- **Folded**: `summarize_payload` takes the object, not the encoded string.
- Confirmed: no existing test assertion breaks beyond the one edit named.

### Outside voice

Ran Codex (`codex exec -s read-only`, outside the sandbox) and a
fresh-context Claude reviewer against the rewritten draft. Eight findings:

- **Folded (high)**: the fast-path `_remove_access_token(token, actor_id=)`
  would have orphaned the provider-token row a code-minted access token
  owns (`token_manager.py:363`), and neither the purge nor
  `cleanup_expired_tokens` swept that bucket. The refresh record now
  carries `google_token_key`; the purge covers all seven MCP buckets.
- **Folded (high, simpler approach taken)**: chain revocation on a replayed
  authorization code was specified against a success path that deletes the
  code row (`:203`, `_remove_auth_code` `:518-547`), and the chain id does
  not exist until after minting. Dropped: atomic consume only, row deleted
  on success as today, no TTL re-stamp for codes.
- **Folded (medium)**: the draft claimed `cleanup_expired_tokens` as an
  automatic fallback for a failed TTL re-stamp; it is scheduled-only
  (`:1122-1131`). The scenario now says the row lives 30 days, harmlessly.
- **Folded (medium)**: rotation is several writes after the CAS; the
  mint-fault recovery contract (retry inside 60 s rotates, after 60 s reads
  as theft) is now a test and a docstring statement.
- **Folded (medium)**: Codex proposed splitting the release (C/D/E first,
  F later); the fresh-context reviewer and this plan keep them together
  because a `none` client's refresh token without rotation is an unbound
  30-day bearer. Both agreed a curl-only verification is not enough for a
  stable tag: Phase 4 now ships `3.15.0rc1` to TestPyPI and runs each of
  the four connectors against it first.
- **Folded (low)**: sliding refresh lifetime stated as a decision; the auth
  method is public-vs-confidential only and body/header `client_id`
  disagreement is refused; the exchange-side `plain` wording corrected
  (exchange stringifies an absent method to `"None"`, `:158`, and the
  consumer passes `plain` explicitly).
- Checked and dropped by the reviewer: `secret_equals(None, secret)` is
  `False`, not an exception (`secret_compare.py:24-25`), so a `none` client
  reaching `validate_client` with a secret through the callback filter or
  the SDK is safe.

### Unverified notes

- Whether claude.ai and Claude Code register with `none` or a confidential
  method is not recorded anywhere in the tree; the reconnect note is written
  for "connectors that registered as public clients" and names Codex and
  ChatGPT as the observed cases.
- Whether Codex puts `client_id` in the body alongside the Basic header on
  code exchange (which today would skip the header) is a live claim the
  review could not check; C.4 parses the header either way.
- Whether Codex or ChatGPT re-run dynamic registration on their own after a
  refresh answers `invalid_client`, which would make the "remove and
  re-add" migration step unnecessary for them. The rc pass in Phase 4
  answers it.
- DynamoDB `sanitize_json_data` on the CAS `old_data` for a legacy record
  with `None`-valued fields might not round-trip identically; the SPA store
  takes the same path. The legacy-record test is unit-only.
- No explicit Jinja autoescape configuration was found; `state` already
  renders through the same template path as the new `code_challenge`
  hidden input, and the integrations autoescape `.html` by default.
- The per-chain figures (24 refreshes a day) assume a client refreshes once
  per access-token lifetime; connector behaviour was not measured.

Verified and moved out of this list by the outside voice: PostgreSQL
`conditional_update_attr` does null the row `timestamp`
(`db/postgresql/attribute.py:547`), and the TTL re-stamp `set_attr` that
follows rewrites it; exchange does not apply an RFC 7636 default for an
absent method (`token_manager.py:158`).
