# Verification: 3.15.0 — MCP OAuth hardening and two credential exposures

**Date:** 2026-09-25
**Plan:** thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md
**Research:** thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md,
thoughts/research/2026-09-25-mcp-client-name-cache.md
**Branch:** release/3.15.0-mcp-oauth-hardening
**Commit:** 661ee03 plus an uncommitted working tree (all of Phases 1–3 is
uncommitted; 35 modified files, 18 untracked)

**Scope:** Phases 1, 2 and 3. Phase 4 (release: `3.15.0rc1`, the
four-connector pass, the demo deployment, the stable tag) is *Not Started*,
so this verification covers a subset of the plan. The plan stays
`status: active` and gets no `verified:` link; this document's `**Plan:**`
line carries the thread. No feature document exists for this work.

## Automated Check Results

- **Browser QA:** not run. The only UI surface touched is the OAuth authorize
  form (two hidden PKCE inputs, `templates/aw-oauth-authorization-form.html`),
  reachable only through a real OAuth provider; no provider credentials exist
  in this session (`CLAUDE.md` "Test account: none"). Template values are
  covered by `tests/test_oauth2_pkce_binding.py::…::test_html_get_carries_challenge_to_template_and_provider_state`.
  The Phase 4 rc connector pass is where the form is exercised for real.
- **Second opinion — outside-voice:** providers Codex (`codex exec -s
  read-only`, unsandboxed) and a fresh-context Claude reviewer. 15 findings
  plus 5 unverified notes; the ones checked against the tree are folded into
  Issues Found.
- **Second opinion — built-in code review (high, no `--fix`):** 10 findings,
  returned unverified; 6 confirmed against the tree and folded in, 2 are
  duplicates of outside-voice items, 2 are quality notes (duplicated CAS/purge
  logic with `oauth_session.py`; double registry read in
  `_authenticate_client`).
- **Second opinion — built-in security review:** no finding at or above the
  confidence threshold (≥ 8). Three near-misses excluded: grace-window
  replays (documented trade), client-chosen `Mcp-Session-Id` cache key
  (cosmetic impact), anonymous public-client DCR (no new capability).
- `poetry run ruff check actingweb tests`: pass, 0 findings.
- `poetry run ruff format --check actingweb tests`: pass, 393 files formatted.
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel` (**DynamoDB**): 3605 passed, 31 skipped, **1
  error** — `tests/test_hot_path_n_plus_one.py::TestPropertyStoreBulkReads::test_items_and_values_are_bulk_reads`,
  DynamoDB Local `InternalServerError: … too long waiting for a lock` on a
  `PutItem`. Re-run sequentially (`pytest tests/test_hot_path_n_plus_one.py
  -p no:rerunfailures`): 11 passed. Parallel isolation flake, not a
  regression.
- `make test-all-parallel` (**PostgreSQL**): 3495 passed, 140 skipped, 2
  failed — `tests/performance/test_backend_performance.py::TestSubscriptionPerformance::test_subscription_create_performance`
  and `::test_subscription_read_performance` (`invalid input syntax for type
  boolean: "https://callback.example.com"`). Pre-existing, already filed as
  `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`;
  this branch does not touch `tests/performance/`.
- Benchmarks alone (`pytest tests/ -m benchmark`, DynamoDB, run because
  `attribute.py` changed): 17 passed. Means (µs): attribute write 3772,
  property write 3844, actor update 5147, trust create 4684, subscription
  create 5072, actor delete 9148, actor create 16191, bulk property read
  71204, bulk property write 354681. The `attribute.py` change is a
  read-only property; no hot path changed.
- `sphinx-build -W --keep-going …`: build succeeded, 0 warnings.

## Phase Verification

### Phase 1: Code and tests — ISSUES FOUND

**Changes verified:**

- A. `actingweb/log_summary.py:19-45` `summarize_payload` logs key names and
  sizes only. Used at `aw_proxy.py:251`, `:314`, `:552`, `:656`;
  `handlers/oauth2_endpoints.py:263-266` (authorize params) and `:273-276`
  (authorize server response, an addition the plan's notes record);
  `fastapi_integration.py:1350`, `:2472`. Matches plan.
- B. `handlers/trust.py:47` `_TRUST_LIST_CREDENTIAL_FIELDS`, `:70-81`
  `_public_trust_row`, applied at `:117`; `TrustPeerHandler.get` keeps the
  credentials with the spec comment at `:511-517`. Matches plan. No other
  route serialises a trust list (POST responses echo one row to its
  creator/peer by design; `www.py:586` renders server-side).
- C. `client_registry.py:25-29`, `:73-145` (method validation, `none` → no
  secret, `client_secret_expires_at: 0`); `oauth2_server.py:484-513`
  `_authenticate_client`, used by the code grant (`:535`), refresh grant
  (`:579`) and client-credentials grant (`:611-623`, lookup before the
  presence check); `oauth_client_manager.py:58-71`, `:236-240`; token
  handler Basic parsing `oauth2_endpoints.py:358-387`. Matches plan.
- D. PKCE read on GET (`oauth2_endpoints.py:222-225`) and POST (`:255-259`),
  `""`→`None`; `oauth2_server.py:25`, `:168-183` S256-only and the length
  regex; show-form echo `oauth2_endpoints.py:762-764`, `:784-785`;
  provider-button `mcp_context` `:698-710`; `redirect_uri` stored
  (`token_manager.py:119-120`) and compared (`:182-185`). Matches plan.
- E. `oauth2_endpoints.py:404-434` status map and `_token_error`; `:183-185`
  `invalid_client_metadata`. Matches plan.
- F. `constants.py:208-215`; `_consume` `token_manager.py:518-579` (used
  pre-check → deep copy → CAS → best-effort re-stamp); exchange consumes
  before PKCE (`:190-212`); refresh branches `:338-459`; `_revoke_chain`
  `:599-663`; `revoke_token` `:461-511`; `cleanup_expired_tokens`
  `:1420-1554`; `purge_expired_tokens` over all seven buckets `:1556-1583`;
  throttle `:1585-1607`, called at `oauth2_endpoints.py:399-402`;
  `clear_token_from_cache(actor_wide=)` `mcp.py:2836-2888`,
  `evict_caches_for_token(actor_wide=)` `mcp/invalidation.py:31-49`.
  Matches plan, with the deviations below.

**Security properties the plan claims, and the test that pins each:**

| Property | Test | Assertion |
| --- | --- | --- |
| Trust list carries no credentials | `tests/test_trust_list_strips_credentials.py::test_list_drops_credentials_and_keeps_the_rest` | `assert "secret" not in row`, `assert "verification_token" not in row` for both rows; integration `tests/integration/test_trust_lifecycle.py:110` `assert "secret" not in row` on both backends, while `:98-99` asserts the per-relationship GET keeps both |
| Proxy body values never logged | `tests/test_aw_proxy.py::TestRequestBodyNotLogged::test_sync_methods` / `test_list_body_logs_size_only` | `assert "hunter2" not in caplog.text` |
| Authorize DEBUG line holds no values | `tests/test_oauth2_pkce_binding.py::test_authorize_debug_log_holds_no_values` | email and challenge absent from the record |
| Confidential client cannot use a grant without its secret | `tests/test_oauth2_public_clients.py::…::test_code_grant_confidential_without_secret_is_invalid_client`, `test_refresh_grant_confidential_without_secret` | `assert resp["error"] == "invalid_client"` |
| Public client refused `client_credentials` | `…::test_client_credentials_public_is_unauthorized_client` | `error == "unauthorized_client"` |
| Code bound to challenge and `redirect_uri` | `tests/test_oauth2_pkce_binding.py::…::test_stored_code_is_bound_and_verified` | `stored["code_challenge"] == CHALLENGE`, `stored["redirect_uri"] == REDIRECT`; wrong verifier and different `redirect_uri` → `None` |
| `plain` refused at authorize, still accepted at exchange when explicit | `…::test_refused`, `…::test_explicit_plain_still_exchanges`, `…::test_absent_method_does_not_exchange` | `invalid_request`; tokens; `None` |
| Code single-use, atomically | `tests/test_mcp_auth_code_single_use.py::test_second_exchange_of_a_code_fails`, `test_cas_loser_gets_none_and_winner_tokens_stand` | `assert first is not None`, `assert second is None`, code row and index gone |
| Wrong verifier burns the code | `…::test_wrong_verifier_burns_the_code` | `exchange(..., code_verifier=VERIFIER) is None` after a wrong one; `code not in store.names(...)` |
| Refresh token single-use; theft revokes the chain only | `tests/test_mcp_refresh_rotation.py::test_reuse_inside_window_revokes_the_whole_chain_only` | replay → `None`; the chain's tokens gone from both buckets and both indexes; `other["refresh_token"] in store.names(...)` (other chain survives); `(ACTOR, CLIENT) not in mcp_mod._trust_cache` |
| Mint-fault recovery contract (30 s rotates, 90 s is theft) | `…::test_mint_fault_after_consume_recovers_in_grace_and_is_theft_after` | `retry is not None`, same chain; later `refresh_access_token(...) is None` and the retry's tokens gone |
| Past-window replay is not theft | `…::test_reuse_past_window_is_expired_not_theft`; both backends in `tests/integration/test_mcp_refresh_rotation_backend.py::…::test_replay_past_window_is_expired` | `None`, nothing else revoked |

The unit tests run on `tests/mcp_token_double.py`; the rotation, grace,
theft and past-window paths are also run against real DynamoDB and
PostgreSQL in `tests/integration/test_mcp_refresh_rotation_backend.py`.

**Deviations from plan:**

- Branch cut from the docs branch rather than `master` at `2d5eaa4`, and
  five additions (authorize server-response log, secrets removed from the
  `regenerate_client_secret` ERROR log, Basic header urldecode,
  provider-token rows in `_revoke_chain`, the "headsers" branch removed).
  All recorded in the plan's Phase 1 notes and acceptable.
- The Failure Scenario "chain revoke — a bucket read faults … corrected in
  Phase 2 (J)" holds on PostgreSQL only. See Issues Found, "Chain revocation
  aborts or reports success on a store fault".
- Manual curl pass with a real provider: not run (no credentials). Deferred
  to the Phase 4 rc pass by the plan's own note.

### Phase 2: Client-supplied text, the client-info cache, store faults — ISSUES FOUND

**Changes verified:**

- G. `actingweb/client_text.py:25-53`; write sites `mcp.py:28-38`,
  `:938-946`, `:2667-2680`; `trust_manager.py:415-419`;
  `client_registry.py:73-75`; `oauth2_callback.py:588`; read sites
  `trust.py:50-67` via `:117` and `:518-519`. Matches plan.
- H. Callback-time write gone (no `_mcp_client_info_cache` reference under
  `actingweb/oauth2_server/` or in `handlers/oauth2_callback.py`; the plan's
  grep check is empty); `_get_session_key` `mcp.py:2797-2814` has no
  User-Agent fallback; token key `:2816-2822`; bound
  `MCP_CLIENT_INFO_CACHE_MAX = 1000` `:25`, enforced `:2794-2795`. Matches
  plan.
- I. `TokenStoreUnavailable` `token_manager.py:28`, exported; strict reads
  `_strict_read` `:1005-1025`, `_search_indexed_token` `:1027-1069`;
  `get_attr_strict` on both backends (`db/dynamodb/attribute.py:107-137`,
  `db/postgresql/attribute.py:276-315`); 503 on the **sync** handler's GET
  (`mcp.py:737-740`) and POST (`:868-871`) via
  `_token_store_unavailable_response` `:2747-2761`. **Not** on the async
  handler (see Issues Found).
- J. `Attributes.loaded` `attribute.py:126-135`; `_snapshot_bucket`
  `token_manager.py:581-597`. Matches plan for the PostgreSQL fault shape.

**Tests verified:** `tests/test_client_text.py`,
`tests/test_mcp_client_info_cache.py`, `tests/test_mcp_token_store_faults.py`
(`test_mcp_post_answers_503_on_store_fault`: `status_code == 503`,
`headers["Retry-After"] == "5"`; drives `MCPHandler` only),
`tests/test_attribute_loaded.py`,
`tests/test_mcp_refresh_rotation.py::test_theft_revocation_with_unreadable_bucket`
(fault injected as the PostgreSQL shape: `get_bucket` returns `None`).

**Deviations from plan:**

- The planned `tests/test_oauth2_callback_does_not_write_client_info.py`
  became `tests/test_mcp_client_info_cache.py:114`, which asserts only that
  two methods no longer exist (`hasattr`). The plan asked for a behavioural
  test (callback with a populated cache writes no client name). Low; see
  Issues Found.
- The plan's notes add `client_platform` sanitising, the web-callback cache
  reader removal, `_strict_read` expiring TTL-past rows, and
  `cleanup_expired_tokens` raising on a fault. Recorded and acceptable,
  except the last interacts with the TTL expiry (see Issues Found,
  "`cleanup_expired_tokens` orphans…").

### Phase 3: Docs, spec, migration guide, todos — VERIFIED (with one doc claim made false by an Issue)

**Changes verified:**

- `CHANGELOG.rst` `Unreleased`: SECURITY, CHANGED (two **Breaking:**), FIXED
  entries present; `:110-115` states the `/mcp` 503.
- `docs/migration/v3.15.rst` present, listed first in
  `docs/migration/index.rst`; "Start here" items present; `:153` states
  `GET /mcp` and `POST /mcp` answer 503.
- `docs/protocol/actingweb-spec.rst`: plan's grep check holds — `"secret"`
  appears only at `:1621` (POST body example) and `:1773` (per-relationship
  GET example).
- `docs/guides/{oauth2-setup,mcp-applications,troubleshooting,trust-relationships,database-maintenance,logging-and-correlation}.rst`,
  `docs/reference/{routing-overview,security}.rst` updated.
- Docs build clean with `-W`.

**Todos against the plan:**

- `thoughts/todo/trust-list-endpoint-returns-peer-secrets.md` deleted, its
  `INDEX.md` row gone. ✔
- Deferrals named in "What We're NOT Doing" each have a file and an index
  row: `dcr-registrations-and-client-trust-rows-never-expire.md`,
  `mcp-oauth-connector-conformance-followups.md` (gained the
  unbound-confidential-code item), `mcp-cache-lifecycle-and-revocation.md`,
  `logout-does-not-revoke-refresh-chain.md`. ✔
- Added by this verification: `actor-trust-request-logs-peer-secret.md`
  with its index row (pre-existing, out of scope; see Remaining Tasks).

**Deviation:** the 503 guarantee stated at `CHANGELOG.rst:110-115`,
`docs/migration/v3.15.rst:153` and `docs/guides/troubleshooting.rst:133` is
true only for the sync handler (see Issues Found).

### Phase 4: Release — NOT STARTED

Not verified. The consumer message (Phase 4, plan lines 1065-1073):

> Tell the consumer: switch `read_service_bucket` from `_bucket_loaded` to
> `Attributes.loaded`; its suspended-account middleware can fail closed on
> `TokenStoreUnavailable`; its own `client_name` sanitising can stay (the
> library now does the same at write and on the trust routes); drop the
> `actingweb.aw_proxy` logger override; confirm its MCP clients persist
> rotated refresh tokens; its own OAuth password path is unaffected (`plain`
> still exchanges, no `redirect_uri` stored); users with Codex/ChatGPT
> connectors added before the upgrade reconnect once.

Every clause is accurate against the tree. `validate_access_token` raises,
so middleware that calls it can fail closed; the `plain` path is pinned by
`test_explicit_plain_still_exchanges`. **But** the consumer
(`../actingweb_mcp/application.py:135`, `FastAPI(`) serves `/mcp` through
`AsyncMCPHandler`, so the 503 behaviour the migration guide promises does
not reach it until the async-handler issue below is fixed. The message
should say which library version fixes that once one does.

## Remaining Tasks

- [ ] Fix the issues below through `/iterate_plan` (the High and Medium ones
      before `3.15.0rc1`), then re-run this verification.
- [ ] Phase 4 in full: rc1, the four-connector pass (including the deduced
      "every connector re-initialises with its bearer token" decision), the
      demo deployment, the stable tag.
- [ ] `master` has moved: the docs branch this release was cut from merged
      as PR #147 (`d6a9130`, parents `2d5eaa4` and `661ee03`). The plan's
      Phase 1 note that its commits "land with this PR" is moot; merge
      `master` into the release branch before opening the rc PR.
- [ ] Manual curl pass with a real provider (Phase 1 Verification's
      unchecked box), or record it as superseded by the rc pass.
- [ ] `thoughts/todo/actor-trust-request-logs-peer-secret.md` (filed by this
      verification): `actor.py:1159-1161` logs the new trust secret and
      verification token at INFO. Pre-existing, outside the plan; cheap
      enough to fold into 3.15 if the owner wants.

## Issues Found

### 1. The FastAPI MCP handler never answers 503 on a token-store fault

**Severity:** High
**Description:** Phase 2 (I) added the 503 mapping to `MCPHandler` only.
`AsyncMCPHandler` calls `authenticate_and_get_actor_cached()`
(`actingweb/handlers/async_mcp.py:103`), which now re-raises
`TokenStoreUnavailable`, and the exception lands in the generic
`except Exception as e:` at `:141`, which returns
`self._create_jsonrpc_error(data.get("id"), -32603, f"Internal error: {str(e)}")`:
HTTP 200, no `Retry-After`, and an error text that carries the actor id and
bucket name (`_strict_read`'s message). The changelog, migration guide and
troubleshooting page promise 503 on `/mcp`. The consumer that motivated
Phase 2 runs FastAPI. `tests/test_mcp_token_store_faults.py` drives only
`MCPHandler`.
**Location:** `actingweb/handlers/async_mcp.py:103`, `:141-145`
**Recommendation:** catch `TokenStoreUnavailable` around the async
authentication and return `_token_store_unavailable_response`; add the
async case to `tests/test_mcp_token_store_faults.py`.

### 2. A store fault in client lookup answers 401 `invalid_client` at the token endpoint

**Severity:** High
**Description:** `_authenticate_client` runs before the grant
(`oauth2_server.py:579`) and reads the client through
`MCPClientRegistry._load_client`, which ends
`except Exception as e: logger.error(f"Error loading client {client_id}: {e}"); return None`
(`client_registry.py:377-379`). During a store outage every refresh answers
401 `invalid_client` — "your registration is bad" — before
`refresh_access_token`'s strict read can raise. Phase 2's goal ("a
throttle no longer tells the client its refresh token is dead") is missed
one call earlier, and `invalid_client` is a stronger signal than
`invalid_grant` (the plan's own unverified notes expect some connectors to
drop or re-register on it).
This is a plan-scoping gap, not an implementation miss: "What We're NOT
Doing" keeps strict reads to the two MCP token lookups and says "the rest
keep today's fail-as-absent reads"; the client lookup is in "the rest".
`/iterate_plan` should reopen that decision.
**Location:** `actingweb/oauth2_server/client_registry.py:377-379`,
`actingweb/oauth2_server/oauth2_server.py:579`
**Recommendation:** a strict client read that raises
`TokenStoreUnavailable`; map it in `handle_token_request` to 503 with
`Retry-After` (today the catch-all makes it 500 `server_error`).

### 3. Chain revocation aborts, or reports success, on a store fault

**Severity:** Medium
**Description:** Two backend shapes, neither handled as the plan claims.
On **DynamoDB** `get_bucket` raises on a mid-page throttle (the new
docstring at `attribute.py:102-106` says so), so `_snapshot_bucket`
(`token_manager.py:593`, no try) raises before `delete_by_chain` runs: the
theft response becomes 500 and nothing in the chain is revoked. The comment
at `:619-621` ("the chain's actor rows are still deleted below") is false
there, and `test_theft_revocation_with_unreadable_bucket` injects only the
PostgreSQL `None` shape. On **PostgreSQL** `delete_by_chain` catches every
exception and returns 0 (`db/postgresql/attribute.py:674-676`), so `:638`
gets 0, the WARNING at `:420` says "revoked 0 token(s)", and the thief's
branch stays live with nothing louder than that line.
**Location:** `actingweb/oauth2_server/token_manager.py:593`, `:619-642`
**Recommendation:** run `delete_by_chain` first and make the name
enumeration best-effort; treat a 0 count on a chain that the snapshot saw
as a failure (ERROR, and `server_error` rather than `invalid_grant`); add a
raising-`get_bucket` case to the test.

### 4. A legacy (pre-3.15) refresh token's first rotation has no theft detection

**Severity:** Medium
**Description:** A legacy record rotates into a fresh chain
(`chain_id = refresh_data.get("chain_id") or self._new_chain_id()`,
`token_manager.py:438`), but `_consume` stores a copy of the old record, so
the consumed legacy row never gets that chain id. A replay of it after 60 s
takes the theft branch with `chain_id = current.get("chain_id")` → `None`
and only `self._remove_refresh_token(refresh_token)` (`:418-423`); the new
chain survives. Every connector live at upgrade time is in this state for
one rotation.
**Location:** `actingweb/oauth2_server/token_manager.py:418-423`, `:438`
**Recommendation:** assign the chain id before `_consume` and write it into
the consumed row's new data.

### 5. `revoke_token` on a refresh token leaves the rest of its chain live

**Severity:** Medium
**Description:** The refresh branch (`token_manager.py:492-509`) removes the
token and its one access token. The access-token branch removes the
chain's refresh tokens (`:488-489`), but the refresh branch does not. After
a rotation the client may revoke RT2 while RT1 (consumed, `used_at` < 60 s)
still exists; presenting RT1 takes the grace branch (`:411-416`) and mints
a fresh pair after the revocation. RFC 7009 §2.1 says revoking a refresh
token SHOULD invalidate the same grant. The asymmetry is the plan's own
spec, so this is a plan gap, not an implementation deviation.
**Location:** `actingweb/oauth2_server/token_manager.py:492-509`
**Recommendation:** when the record has a `chain_id`, `_revoke_chain` in
both branches.

### 6. The first purge after an upgrade runs inside a token request, after the rotation

**Severity:** Medium
**Description:** `maybe_purge_expired_tokens()` runs synchronously after
`handle_token_request` (`oauth2_endpoints.py:399-402`) with the throttle
starting at `_last_mcp_purge_attempt: float = 0.0`
(`token_manager.py:1607`). On PostgreSQL nothing purged the MCP buckets
before 3.15, so an existing deployment's first token request per process
runs a potentially large `DELETE` after the refresh token was already
consumed. A gateway timeout there means the client never receives the new
pair; its retry after 60 s reads as theft and revokes the chain. Every cold
start repeats it.
**Location:** `actingweb/handlers/oauth2_endpoints.py:399-402`,
`actingweb/oauth2_server/token_manager.py:1585-1607`
**Recommendation:** purge before the grant or off the request path, bound
the batch, and seed the throttle with process start time.

### 7. `cleanup_expired_tokens` orphans TTL-expired actor rows and aborts on one fault

**Severity:** Medium
**Description:** `_load_access_token` / `_load_refresh_token` now use
`_strict_read`, which answers `None` for a row past its `ttl_timestamp`
(`db/postgresql/attribute.py:310-311`; DynamoDB `:132-133`). At
`token_manager.py:1477-1481` that reads as "token doesn't exist, clean
index" — the index row goes, the actor row stays, and the `used_at` branch
at `:1506-1511` is mostly unreachable for the same reason. Nothing in the
loop catches `TokenStoreUnavailable`, so one transient fault ends the
scheduled sweep. Mitigated on PostgreSQL by the throttled purge (which
deletes TTL-past actor rows) and on DynamoDB by native TTL, so the orphans
are reaped, but the scheduled job no longer does what its docstring and
`docs/guides/database-maintenance.rst` say.
**Location:** `actingweb/oauth2_server/token_manager.py:1477-1481`,
`:1502-1511`
**Recommendation:** delete the actor row by name using the index row's
actor id instead of re-reading it; catch the fault per row.

### 8. Raw authorization codes still logged in the auth-code helpers

**Severity:** Medium
**Description:** `exchange_authorization_code` masks codes, but
`_search_auth_code_in_actors` and `_remove_auth_code` log the full code at
DEBUG (`token_manager.py:829`, `:834`, `:855`, `:887`, `:891`), WARNING
(`:847`) and ERROR (`:858`, `:862`, `:894`) — e.g. `:862`
`logger.error(f"Error searching for auth code {code}: {e}")`. A live,
not-yet-consumed code in a log is redeemable by whoever reads it (with the
client's PKCE verifier or secret). Same file the plan rewrote, in a release
whose theme is credential logging. The same helper also still swallows
faults as "no such code" (`:861-863`), outside Phase 2's strict-read scope
by the plan's decision.
**Location:** `actingweb/oauth2_server/token_manager.py:829-894`
**Recommendation:** `_mask_token(code)` at every site.

### 9. Session key is consulted before the token key for live `clientInfo`

**Severity:** Low
**Description:** `_resolve_live_client_info` tries
`self._get_session_key()` before `self._token_client_info_key()`
(`mcp.py:2078`). `Mcp-Session-Id` is client-chosen and never issued by the
library, so an unauthenticated `initialize` carrying a victim's session id
overrides what the victim's authenticated `initialize` cached under its
token. Impact is `client_type` detection and `MCPContext.client_info` only;
trust rows are written from the request's own `clientInfo`. The comment at
`mcp.py:943` ("never under a key another client could share") overstates
it.
**Location:** `actingweb/handlers/mcp.py:2078`, `:943`
**Recommendation:** token key first on authenticated requests; correct the
comment.

### 10. Behavioural callback test replaced by a structural one

**Severity:** Low
**Description:** `tests/test_mcp_client_info_cache.py:114-118`
`test_oauth_callback_does_not_write_client_info` asserts only
`not hasattr(ActingWebOAuth2Server, "_store_mcp_client_info_in_trust")`.
The plan asked for the callback with a populated cache to write no client
name to the trust row; a future re-introduction under a different name
would pass.
**Location:** `tests/test_mcp_client_info_cache.py:114`
**Recommendation:** drive `handle_oauth_callback` with a populated cache and
assert the trust write carries no cached name.

### 11. Smaller items (Low)

- Rotation bumps the global cache generation (`mcp.py:2860-2864`
  `_bump_cache_generation()`), so every refresh cancels in-flight cache
  fills for every actor, partly undoing the "pop one token" decision.
- `_cache_client_info` iterates and trims the module-global dict without a
  lock (`mcp.py:2787-2795`); the iteration pattern is pre-existing, the size
  loop is new. Under threaded Flask a concurrent `initialize` can raise
  `RuntimeError: dictionary changed size during iteration`.
- Stale docstring: `_resolve_transport_session_id` (`mcp.py:2048-2052`)
  still describes the removed `<client_ip>:<hash(UA)>` fallback.
- `_sanitized_client_info` (`mcp.py:28-38`) sanitises `name` and `version`
  only; other `clientInfo` fields (`title`, `implementation`) reach
  `MCPContext.client_info` raw.
- Body secret and header secret both present: body wins silently
  (`oauth2_endpoints.py:386-387`); RFC 6749 §2.3.1 allows one method.
- `revoke_client_tokens` ignores `Attributes.loaded`
  (`token_manager.py:1370`), so a faulted read revokes 0 tokens silently
  before the client is deleted.
- `summarize_payload` key names are unsanitised (`log_summary.py:38`).
- `_authenticate_client` loads the client twice, three times on
  `client_credentials` (`oauth2_server.py:484-513`, `:611-623`).
- `_consume` and the purge throttle duplicate `oauth_session.py`'s
  `try_mark_refresh_token_used` / `maybe_purge_expired_tokens`.

## Overall Assessment

Phases 1–3 are implemented as planned. The static checks and the docs
build are clean, and both backends pass apart from one parallel flake that
passed sequentially and the two benchmark failures already filed. Each
security property the plan claims is pinned by a named test: the
trust-list strip, proxy log summaries, confidential-client authentication
in every grant, S256-only authorize with a stored and compared
`redirect_uri`, single-use codes and refresh tokens with chain revocation.
Rotation, grace, theft and past-window also run against real DynamoDB and
PostgreSQL. The adversarial and built-in reviews found no way around those
properties on the happy path.

The gaps are on the fault paths, which were Phase 2's reason for existing.
The 503 contract does not reach FastAPI deployments, the consumer's
included (#1). A store fault during client lookup still tells a connector
its registration is bad (#2). Chain revocation can abort on DynamoDB or
report success on PostgreSQL without revoking anything (#3). Two Medium
theft-detection holes remain in rotation (#4, #5), and the first purge per
process can turn a routine refresh into a chain revocation (#6). #1–#6
should go through `/iterate_plan` before `3.15.0rc1`; #1 also changes a
documented promise. The UI (the authorize form's PKCE inputs) was not
exercised in a browser: no provider credentials exist in this session, and
the Phase 4 connector pass is where it gets exercised. The plan stays
`active` with no `verified:` link, because Phase 4 has not started and this
verification covers Phases 1–3 only.
