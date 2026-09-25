---
status: proposed
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
  request; disagreement is `invalid_request`).
- **Rotation pops one token from the MCP cache; theft evicts the actor.**
  `evict_caches_for_token` today also evicts the actor's `ActorInterface`
  and every trust entry, which is right for revocation but makes every
  hourly refresh a cold path for every connector on the actor. A token-only
  pop is added for rotation; `_revoke_chain` and `revoke_token` keep the
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
- **Phasing: one code phase, one docs-and-hardening phase, one release
  phase.** The six code areas are not independent files — C and E both edit
  `handlers/oauth2_endpoints.py`, C and D both edit `oauth2_server.py`, and
  C's grant-side authentication must land before its handler-side
  normalisation — but each has its own tests and none is worth a separate
  green checkpoint; the owner prefers fewer, larger phases.

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
  (lookup only); `None` → `None`; method `none` → return the client, any
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
  path). Delete `_revoke_access_token_by_id` and
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
  endpoint). DynamoDB returns 0 by design.
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
- Chain revoke — `get_bucket()` returns `None` — WARNING, treated as empty,
  the presented token still removed; covered.
- Chain revoke — `delete_by_chain` faults — the exception propagates out of
  the grant as today's storage faults do (500 `server_error`); the
  presented token was already consumed so a retry cannot rotate it.
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

- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests && poetry run ruff format --check actingweb tests`
- [ ] `make test-all-parallel` on DynamoDB; re-run failures sequentially
- [ ] `DATABASE_BACKEND=postgresql ... make test-integration` (per `CLAUDE.md`)
- [ ] Manual, dev server with a real provider: register a `none` client with
      `curl`; GET authorize with an S256 challenge → form POST → callback →
      exchange with the verifier; refresh, then present the first refresh
      token again after 60 s and confirm 400 `invalid_grant` and that the
      second refresh token is dead; on PostgreSQL confirm the consumed rows
      are gone after the purge interval

### Implementation Status: Not Started

---

## Phase 2: Docs, spec, migration guide, and the todos that carry the deferred items

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
  authorize templates must carry the two hidden PKCE inputs, (5) consumers
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
  `sphinx-build -W` / rst lint the project runs); no code tests. Phase 1's
  suite runs again after docstring edits.

### Failure Scenarios

- A consumer reads the spec example and expects `secret` in the list — the
  migration guide and the CHANGED line name it.
- A PostgreSQL operator has no pg_cron job — the token-endpoint purge covers
  it; the guide says so.

### Verification

- [ ] `grep -n '"secret"' docs/protocol/actingweb-spec.rst` shows only the
      POST body and the per-relationship GET examples
- [ ] `docs/migration/index.rst` lists v3.15 first
- [ ] Phase 1 checks re-run green

### Implementation Status: Not Started

---

## Phase 3: Release 3.15.0

### Changes

- **Pre-release first.** `3.15.0rc1` in `pyproject.toml`,
  `actingweb/__init__.py` and a `v3.15.0rc1` changelog heading; PR, merge,
  tag, TestPyPI (the `CLAUDE.md` pre-release path). Install it in the
  consumer's dev deployment and run one pass with each of claude.ai, Claude
  Code, Codex and ChatGPT: a fresh registration, code exchange, a refresh
  after more than 60 s, a deliberate replay of the consumed refresh token,
  and a pre-3.15 registration confirming the reconnect note. The curl pass
  in Phase 1 does not stand in for this; four named connectors motivated
  the release and the rotation contract is untested against any of them.
  A finding here is a Phase 1 fix and an `rc2`.
- Then `3.15.0`: version files, rename the rc heading to `v3.15.0: <date>`
  folding the rc notes in, a new empty "Unreleased" above it, a `.. note::`
  at the top of the entry pointing at `docs/migration/v3.15.rst` (the
  3.14.0 entry's shape).
- Commit `Release v3.15.0`, push the PR, CI green on both backends, merge,
  tag the merge commit on master, push the tag (per `CLAUDE.md`).
- Delete `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md` and its
  index row; set this plan to `done` after `/verify_implementation`.
- Tell the consumer: drop the `actingweb.aw_proxy` logger override; confirm
  its MCP clients persist rotated refresh tokens; its own OAuth password
  path is unaffected (`plain` still exchanges, no `redirect_uri` stored);
  users with Codex/ChatGPT connectors added before the upgrade reconnect
  once.

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

### Implementation Status: Not Started

---

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
  stable tag: Phase 3 now ships `3.15.0rc1` to TestPyPI and runs each of
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
  re-add" migration step unnecessary for them. The rc pass in Phase 3
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
