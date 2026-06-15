# Verification: Sign in with Apple + Unified Native OIDC Grant

**Date:** 2026-06-14
**Plan:** thoughts/plans/2026-05-29-apple-signin-and-native-oidc-grant.md
**Research:** thoughts/research/2026-05-28-apple-signin-support.md
**Branch:** feature/apple-signin-google-mobile-support
**Commit:** 4efe17d

## Automated Check Results

- **Ruff lint** (`ruff check actingweb tests`): **Pass** — "All checks passed!"
- **Ruff format** (`ruff format --check`): **Pass for feature code.** 6 files "would reformat":
  `db/postgresql/schema.py`, `runtime_context.py`, `tests/test_fastapi_template_response.py`,
  `tests/test_mcp_tool_schema_fields.py`, `tests/test_mcp_tool_visibility.py`,
  `tests/test_oauth_session.py`. **None are Apple-feature files** — pre-existing format drift,
  out of scope for this plan. (Low / informational.)
- **Pyright** (`pyright actingweb tests`): **Pass** — 0 errors, 0 warnings, 0 informations.
- **Pytest (feature suites)**: **Pass** — 145 passed across all 15 new test files.
- **Pytest (regression canaries)**: **Pass** — `test_mobile_oauth2.py` + `test_actingweb_app.py`
  + `test_oauth_session.py` = 89 passed. (Plan's designated refactor canaries are green.)
- Full parallel suite not re-run here; the plan reports 2279 passing with only the pre-existing
  peer-sync timing flakes. Feature + canary subsets independently confirmed green.

Warnings observed are pre-existing and unrelated to this work (`datetime.utcnow()` in
`db/dynamodb/subscription_diff.py`; oauthlib `client_id` deprecation).

## Phase Verification

### Phase 1: Strategy-pattern refactor of OAuth2Authenticator — VERIFIED

**Changes verified (read `oauth2.py` directly + agent sweep):**
- No `provider.name == "..."` conditional branches remain in `exchange_code_for_token`
  (558-621), `refresh_access_token` (623-679), `revoke_token` (1066-1129),
  `validate_token_and_get_user_info` (681-732/734-794). The only `self.provider.name` uses are
  log-string interpolation and identity persistence — no branching. Matches plan's hard
  constraint.
- Provider-specifics delegated via strategy methods: `make_client_secret()`,
  `token_request_headers()`, `supports_refresh_tokens()`, `supports_revoke()`,
  `extract_user_info_from_token_response()`, `extract_identifier_from_user_info()`,
  `get_primary_email()`, `discovery_extras()`.
- Base `OAuth2Provider.make_client_secret` returns the static `self.client_secret` (97-103);
  Google/GitHub do not override it (unchanged); only Apple overrides.
- Factory `_PROVIDER_REGISTRY` (1208-1212) + base-name prefix match (1242-1243);
  `create_google/github/apple_authenticator` shims present.

**Tests verified:** `test_oauth_provider_strategy.py` (29) + `test_mobile_oauth2.py` (20)
regression canaries pass unchanged.

**Deviations:** Strategy method names adapted from the plan sketch to fit the oauthlib-based
authenticator (documented in plan). Acceptable — public signatures preserved.

### Phase 2: PyJWT dep + JWKS validator + cache + replay — VERIFIED

**Changes verified (read all three modules directly):**
- `pyjwt = { version = "^2.9", extras = ["crypto"] }` in `pyproject.toml:35` (core dep).
- `oauth2_jwks.py`: 1h positive TTL, 60s negative TTL, 5s force-refetch debounce,
  `timeout=(3,5)`. Network fetch performed **outside** the lock. **Fail-soft** to stale cache on
  transient error, **fail-closed** (None) when no cache exists. kid-miss → one debounced
  force-refetch.
- `oauth2_id_token.py` `JWKSIdTokenValidator`: **alg allowlist check** (blocks `none`/alg-confusion),
  requires `kid`, fail-closed when key unresolvable, `verify_signature=True`,
  `require=["exp","iss","sub"]`, manual multi-issuer check, manual multi-audience check, nonce
  checked when supplied. Fail-closed posture confirmed (security risk #7).
- `oauth2_replay.py` `IdTokenReplayCache.check_and_record`: keyed by `jti` else
  `sha256(iss|sub|iat)`; TTL = remaining lifetime + 60s; rejects second sighting in-window.
- Constants added (`constants.py:130-188`): replay/state-nonce/ticket buckets + TTLs.

**Tests verified:** `test_oauth2_jwks.py`, `test_oauth2_id_token.py`, `test_oauth2_replay.py`
(30 total) pass.

**Deviations:** Live-JWKS integration test deferred (documented). Acceptable.

### Phase 3: AppleOAuth2Provider + ES256 client_secret + with_apple_sign_in() — VERIFIED

**Changes verified:**
- `oauth2_apple.py`: `make_apple_client_secret` (ES256, iss/iat/exp/aud/sub),
  `_cached_client_secret` via `lru_cache` keyed by **`(time_bucket, provider_name)` only — PEM
  never in cache key** (re-read from module registry). Confirms scalability risk #3.
  `load_private_key_pem` resolves file-path-over-inline, converts literal `\n`, validates EC key,
  raises `ValueError` with source/reason.
- `AppleOAuth2Provider` (oauth2.py:303): hardcoded endpoints, `userinfo_uri=""`, ES256
  `make_client_secret`, `extract_user_info_from_token_response` validates id_token,
  `apple:{sub}` identifier, Apple JWKS `discovery_extras`, `supports_refresh_tokens/revoke`=True.
  Validator `expected_iss` tolerates `appleid.apple.com` + `account.apple.com` (300).
- `with_apple_sign_in()` (app.py:640): eager `ValueError` on missing client_id/team_id/key_id and
  empty audiences; eager `.p8` parse via `load_private_key_pem` at build time. Registers `apple`
  and (if mobile_redirect_uri) `apple-mobile`; deep link stored separately as
  `apple_mobile_deep_link`. Credentials registered via `register_apple_credentials` in
  `AppleOAuth2Provider.__init__`, keyed by concrete `_provider_name` so apple/apple-mobile stay
  distinct.

**Tests verified:** `test_oauth2_apple.py`, `test_apple_provider.py`, plus
`test_actingweb_app.py` builder cases.

**Deviations:** `apple` identifier is **email-first** (falls back to `apple:{sub}`) rather than the
plan's literal `apple:{sub}`-first. This is intentional and correct — it matches Google/GitHub and
enables cross-provider account linking by email. Acceptable.

### Phase 4: State nonce store + POST /oauth/callback/apple — VERIFIED with one ISSUE

**Changes verified:**
- `oauth_state_store.py` `StateNonceStore`/`AppleTicketStore`: single-use (delete-before-return)
  so replays miss. CSRF risk #1 addressed — Apple gets only an opaque nonce; server holds payload.
- `OAuth2AppleCallbackHandler.post()` (oauth2_callback.py:1148): parses form body
  (state/code/id_token/user); consumes nonce → 400 on miss/replay; dispatches by payload:
  MCP (`mcp_state` present) → `_dispatch_apple_mcp_callback`; `apple-mobile` → opaque ticket
  deep-link with **only `?ticket=` and no ActingWeb token** (1210-1228, confirmed); `apple` web →
  replays through shared `get()`.
- id_token validated on web path via `extract_user_info_from_token_response` → full JWKS validation.
- `_merge_apple_user_payload` (714-746) merges first-sign-in name into
  given_name/family_name/display_name **before** `oauth_success`, with `not user_info.get(...)`
  no-clobber guards.
- Token-exchange/refresh error logs redacted via `_redact_token_response` (oauth2.py:38-60),
  called at 608 + 666 (security risk #6 partial — see Issues).
- `POST /oauth/callback/apple` registered in Flask + FastAPI.

**Tests verified:** `test_state_nonce_store.py`, `test_oauth2_callback_apple.py` (errors / replay /
mobile-ticket-no-token / web-SPA / first-sign-in merge), `test_logging_redaction.py`.

**ISSUE found:** `_is_safe_redirect` (683-712) is **dead code — never called**; the planned
`spa_redirect_url` allowlist validation was not wired, and the planned negative test was not
written. See Issues #1.

### Phase 5: JWT-bearer grant + with_google_native() + Android ticket — VERIFIED

**Changes verified:**
- `_handle_token` dispatches `urn:ietf:params:oauth:grant-type:jwt-bearer` and
  `apple_mobile_ticket`.
- `_handle_jwt_bearer_grant` (1109): **nonce required** (400 if missing);
  `_validate_id_token_for_provider` pre-checks token `iss` against the declared provider's
  `expected_iss` and rejects mismatch (security risk #3 — a Google id_token sent as `apple-mobile`
  is rejected) **before** signature validation; **replay protection invoked** via
  `IdTokenReplayCache.check_and_record` → 400 on replay (risk #4); `_normalize_user_info` before
  `oauth_success`.
- `_handle_apple_mobile_ticket` (1157): single-use ticket consume → Apple code exchange (ES256
  client_secret) → id_token validation → session. Correctly skips id_token replay (ticket + IdP
  code are themselves single-use). No token in any deep link (risk #5).
- `_finalize_native_session` shared tail; works with or without upstream access token.
- `with_google_native()` (app.py:738): derives audiences from non-None `*_client_id` kwargs,
  rejects empty → `ValueError`; registers `google-native`. Google provider gains a
  `JWKSIdTokenValidator` only when audiences configured.
- `lookup_or_create_actor_by_identifier` writes `oauth_provider` on both create and existing paths.

**Tests verified:** `test_oauth2_spa_jwt_bearer.py` (12), `test_oauth2_spa_apple_ticket.py` (4),
`test_user_info_normalization.py` (6), `test_actor_oauth_provider_property.py` (2).

**Deviations:** none material.

### Phase 6: MCP on-demand authenticator + Apple in LLM web form — VERIFIED

**Changes verified:**
- `oauth2_server.py`: pre-instantiated authenticators replaced by lazy cached
  `_get_authenticator(provider_name)` (47-64); `google/github_authenticator` retained as
  delegating properties; `handle_authorization_request`/`handle_oauth_callback` route through it,
  making Apple reachable.
- Apple MCP authorize wraps the Fernet MCP state in a `StateNonceStore` nonce (Apple sees only the
  nonce); `response_mode=form_post` applied in the Apple provider/authenticator.
- Cross-contamination prevented: MCP nonce payload carries `mcp_state`; the `/oauth/callback/apple`
  handler dispatches to MCP only when `mcp_state` present, SPA otherwise; `handle_oauth_callback`
  fails closed if `extract_mcp_context` returns nothing.
- `handle_oauth_callback` prefers id_token, userinfo fallback (Apple-capable).
- MCP web form (`oauth2_endpoints.py:644-679`) enumerates Apple web variant, skips
  `-mobile`/`-native`.

**Tests verified:** `test_oauth2_server_lazy_authenticator.py` (4), `test_mcp_apple_signin.py` (3).

**Deviations:** Full MCP end-to-end integration test deferred (documented). Acceptable.

### Phase 7: Docs + CHANGELOG + release prep — VERIFIED

- `docs/guides/apple-sign-in.rst` present; CHANGELOG "Unreleased" has Apple entries (14 mentions);
  constants/pyjwt/coordination doc all present.
- Plan reports `sphinx-build` from repo root with 0 warnings (not re-run here).

## Post-Verification Fixes (applied 2026-06-14)

- **Issue #1 — FIXED.** Added module-level `is_safe_spa_redirect(config, url)` in
  `oauth2_callback.py` (allowlist = relative + same-FQDN + configured provider redirect-URI
  origins + new `Config.spa_redirect_origins`). Enforced at `/oauth/spa/authorize` (400 on unsafe
  `redirect_uri`, primary choke point) and as a defense-in-depth fallback at the callback
  (`oauth2_callback.py:144`, falls back to backend root). `_is_safe_redirect` now delegates to it
  (no longer dead code). Added `Config.spa_redirect_origins` for split-domain SPAs. Tests:
  `tests/test_oauth2_spa.py::TestSpaRedirectSafety` (12 cases incl. protocol-relative,
  userinfo-host confusion, lookalike-host, mobile-scheme, allowlist). CHANGELOG SECURITY entry
  added.
- **Issue #4 — FIXED.** `_redact_token_response` now also applied to the token-revocation
  (`oauth2.py:1123`) and both userinfo (`:719`, `:778`) error logs.
- **Issue #3 — RETRACTED (not a bug).** `lookup_or_create_actor_by_identifier` looks up only via
  `get_from_creator(identifier)` — the identical check `_finalize_native_session` performs before
  setting `is_new_actor=True`. There is no property-index path that could make it find-not-create,
  so `is_new_actor` is correct. Only a harmless redundant lookup remains.
- **Issue #2 — ACCEPTED / documented.** A proper atomic fix needs an "insert-if-absent" backend
  primitive: `conditional_update_attr` only does compare-and-swap on an *existing* item (returns
  False when absent — the replay cache's first write), so it can't close the race. Adding a
  put-if-not-exists primitive across DynamoDB + PostgreSQL is disproportionate for a tight
  concurrent-double-submit window; the primary capture-and-replay-later vector is already blocked.
  Left as a documented low-severity limitation.

Post-fix checks: `ruff check` ✓, `ruff format --check` (changed files) ✓, `pyright` (changed
modules) 0 errors ✓, affected suites 119 passed (incl. 12 new redirect-safety tests).

## Remaining Tasks

- [ ] (Optional) Pre-ship JWKS/RS256/grant latency measurement noted in plan §Scalability — not a
      blocker but was listed as a verification step.
- [ ] (Optional) Deferred live/end-to-end integration tests (JWKS-live, Apple web E2E, Apple
      Android E2E, MCP Apple E2E) — covered by mocked/unit tests; acceptable to ship without.
- [ ] (Optional, unrelated) Reformat the 6 pre-existing files flagged by `ruff format`.
- [ ] (Optional, follow-up) Add an "insert-if-absent" attribute primitive to make id_token replay
      protection atomic (Issue #2).

## Issues Found

### Issue #1 — Planned open-redirect protection (`_is_safe_redirect`) is dead code
**Severity:** Medium
**Description:** `OAuth2CallbackHandler._is_safe_redirect` (oauth2_callback.py:683-712) is defined
but never invoked anywhere. At `/oauth/spa/authorize`, the client-supplied `redirect_uri`
(oauth2_spa.py:415) is stored verbatim as state `redirect_url` (oauth2_spa.py:471) with no
allowlist validation. On success the callback appends `?session=<pending_session_id>` to that
unvalidated URL and 302-redirects to it (oauth2_callback.py:1110-1126). An attacker who induces a
victim to start an authorize flow with `redirect_uri=https://evil.example` receives the victim's
one-time `pending_session_id`, which can be exchanged for ActingWeb tokens → session/account
takeover. The plan's P4 explicitly scoped this fix (security risk #6: "Validate `spa_redirect_url`")
and the plan's P4 "New Tests" claimed a test that "verifies `_is_safe_redirect` blocks an
attacker-supplied `spa_redirect_url`" — **neither the wiring nor that test exists** in
`test_oauth2_callback_apple.py`.
**Location:** `actingweb/handlers/oauth2_callback.py:683-712` (dead), `:1110-1126` (sink);
`actingweb/handlers/oauth2_spa.py:415,471` (unvalidated source).
**Note:** This is a **pre-existing** weakness affecting the Google/GitHub SPA flow too — the Apple
work surfaced it because the plan intended to close it. The Apple-mobile deep-link path itself is
safe (its target comes from server-side `apple_mobile_deep_link` config, not attacker input).
**Recommendation:** Call `_is_safe_redirect` on `redirect_uri` at `/oauth/spa/authorize` (reject
with 400) and/or on `spa_redirect_url` before each 302 in the callback; extend its allowlist to
include configured per-provider redirect URIs. Add the negative test the plan specified.

### Issue #2 — id_token replay check is not atomic (TOCTOU)
**Severity:** Low
**Description:** `IdTokenReplayCache.check_and_record` (oauth2_replay.py:70-84) does a
`get_attr` then `set_attr` with no conditional/atomic write. Two concurrent JWT-bearer submissions
of the same id_token could both read "unseen" and both succeed. The store does block the common
"capture and replay later" case; only a tight concurrent double-submit slips through.
**Location:** `actingweb/oauth2_replay.py:70-84`
**Recommendation:** Use a conditional put (attribute_not_exists) if the backend supports it, or
accept and document the limitation. Not a ship blocker.

### Issue #3 — `is_new_actor` heuristic may misfire `actor_created`
**Severity:** Low
**Description:** In `_finalize_native_session` (oauth2_spa.py:1005-1013), `is_new_actor` is set
True whenever `get_from_creator(identifier)` misses, then `lookup_or_create_actor_by_identifier`
runs. If that lookup *finds* a pre-existing actor via a configured property index (rather than
creating one), `actor_created` would fire for an already-existing actor.
**Location:** `actingweb/handlers/oauth2_spa.py:1005-1041`
**Recommendation:** Have `lookup_or_create_actor_by_identifier` report whether it created vs found,
and gate `actor_created` on that. Low impact unless property-index lookup is enabled.

### Issue #4 — `revoke_token` / userinfo error logs not redacted
**Severity:** Low
**Description:** The redaction helper covers token-exchange/refresh error logs (the plan's scope),
but `revoke_token`'s non-200 log (oauth2.py:1122-1124) and the userinfo non-200 logs
(718-719, 778-779) emit raw `response.text`. These are lower-risk (revoke response bodies and
userinfo errors are less likely to echo secrets, and userinfo logs are `debug`), but for
consistency they could use the same redactor.
**Location:** `actingweb/oauth2.py:1122-1124, 718-719, 778-779`
**Recommendation:** Apply `_redact_token_response` to these sites too. Optional.

## Overall Assessment

The implementation is **substantially complete and high quality**, and matches the plan closely
across all seven phases. The hard architectural constraint (behavior-preserving strategy refactor
with zero provider-name branches in hot paths) is met; the regression canaries pass unchanged. The
core Apple/native-OIDC security properties the plan set out to deliver are genuinely implemented and
test-covered: single-use CSRF nonce for the form_post callback, fail-closed JWKS/id_token
validation with an alg allowlist, `iss`-vs-declared-provider binding on the JWT-bearer grant,
id_token replay rejection, no ActingWeb token in any deep link, ES256 client_secret with the PEM
kept out of the cache key, and token-exchange log redaction. Ruff, pyright, and the 145 feature
tests + 89 regression tests are green.

**One Medium issue should be addressed before merge:** the planned `spa_redirect_url` open-redirect
validation (`_is_safe_redirect`) was written but never wired in, and its negative test was never
added — leaving an open-redirect that leaks a one-time session ID. It is pre-existing (affects
Google/GitHub SPA too) but was explicitly in scope for this plan (security risk #6), so it should
be closed here rather than silently carried forward. The remaining three issues are Low severity
and can be follow-ups. The deferred integration tests are acceptable given the per-component
mocked/unit coverage.
