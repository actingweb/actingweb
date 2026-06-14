# Implementation Plan: Sign in with Apple + Unified Native OIDC Grant

**Date:** 2026-05-29
**Status:** Phases 1–7 Implemented; Phase 8 (GitHub mobile parity) Planned for the same 3.11.0 release
**Research:** thoughts/research/2026-05-28-apple-signin-support.md
**Branch:** feature/apple-signin-google-mobile-support
**Target release:** actingweb 3.11.0

## Overview

Add Sign in with Apple as a third OAuth provider alongside Google and GitHub, covering web SPA, native iOS, and Android Capacitor flows. As part of the same release, consolidate native-mobile sign-in (currently re-implemented per-app in actingweb_mcp's `/api/auth/google-mobile`) into a first-class `/oauth/spa/token` JWT-bearer grant the library exposes for any OIDC provider. Out-of-scope: the actingweb_mcp app changes — a separate coordination checklist accompanies this plan.

## Decisions Made

- **Architecture**: Strategy pattern on `OAuth2Provider`. Provider classes carry `make_client_secret()`, `validate_id_token()`, `get_user_info_from_token_response()`, `discovery_extras()`. `OAuth2Authenticator` becomes a thin orchestrator delegating to the Provider. Existing method signatures preserved (60+ call sites unchanged); request-mocking at module-level `actingweb.oauth2.requests` preserved.
- **Apple callback CSRF protection**: Dedicated `POST /oauth/callback/apple` endpoint backed by a server-side single-use nonce store (state = opaque nonce, server holds the JSON; SameSite=Lax cookies don't need to survive cross-site POST). Standards basis: RFC 9700 §4.7, OIDC Core §15.5.2, OWASP OAuth Cheat Sheet; matches django-allauth / python-social-auth / Curity implementations.
- **Native OIDC grant**: `POST /oauth/spa/token` accepts `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer` (RFC 7523) with `provider` + `assertion` (the id_token) + `nonce` parameters. Validator is dispatched by the **validated `iss` claim**, not the request body's `provider` field. Replay protection via `jti` (or `sub+iat`) table in the session backend with TTL ≥ token lifetime.
- **Validators**: JWKS-only (`JWKSIdTokenValidator`) for both Apple and Google native; no tokeninfo fallback. Module-level cache with 1h positive TTL, 60s negative TTL, kid-miss force-refetch with debounce, `timeout=(3, 5)` seconds. Fail-closed when no cached keys are available.
- **Apple `client_secret`**: ES256 JWT generated via PyJWT; cached via `functools.lru_cache(maxsize=4)` keyed by `(time_bucket_5min, provider_name)`. `.p8` bytes are NOT in the cache key (re-read from `Config.oauth_providers` inside the cached function).
- **`.p8` storage**: `APPLE_PRIVATE_KEY_PATH` (file) and `APPLE_PRIVATE_KEY_PEM` (string) both supported; file path wins if both set. Validated eagerly at `with_apple_sign_in()` time — invalid key paths or unparseable PEM raise `ValueError` with the path/reason at config-build, not at first request.
- **Library API**: New `app.with_apple_sign_in(client_id, audiences=[…], team_id, key_id, private_key_path | private_key_pem, …)` and `app.with_google_native(client_id, audiences=[…], …)` builders. Both reuse the existing `client_id` vocabulary; `audiences` is the list of acceptable `aud` values (Apple: Services ID + Bundle ID; Google: web/iOS/Android/Android-server client IDs). All audience entries individually optional. Existing `with_oauth(provider="google" / "github" / "github-mobile")` web flows unchanged.
- **Android Apple delivery**: After Apple POST callback, server validates state nonce + persists the IdP `code` against a short-lived ticket, then deep-links to the mobile app's `redirect_uri` with the **ticket** (not an ActingWeb session token). Mobile POSTs the ticket to `/oauth/spa/token`; server does the JWT-`client_secret` exchange with Apple and issues ActingWeb tokens. Mirrors the existing GitHub mobile pattern; no long-lived ActingWeb token in any deep link.
- **MCP parity**: Apple is supported in the LLM-triggered OAuth web form flow. MCP server's pre-instantiated `google_authenticator`/`github_authenticator` at `oauth2_server/oauth2_server.py:45-54` are replaced with an on-demand `_get_authenticator(provider_name)` that calls `create_oauth2_authenticator(self.config, provider_name)`. Apple's POST callback is routed to the same `/oauth/callback/apple` endpoint for both SPA (cleartext-JSON state) and MCP (Fernet-encrypted state) flows — the handler dispatches based on which state format decodes successfully.
- **Token revocation**: Library `revoke_token()` supports Apple's JWT client_secret. Apps call it from their own `actor_deleted` hook; best-effort/async/rate-limited (recommended pattern documented). Library does not auto-revoke.
- **`actor.store.oauth_provider`**: Written on every successful sign-in (single write site at the tail of `lookup_or_create_actor_by_identifier`), so revocation logic can rely on the property reflecting the most recent provider.
- **`user_info` normalization**: Before firing `oauth_success`, the library normalizes display-name fields into `display_name`, `given_name`, `family_name`, `email` regardless of provider. Apple's `firstName`/`lastName` → `given_name`/`family_name`; Google passes through; GitHub's `name` → `display_name`. Apps then read one shape.
- **`/oauth/config` response**: Additive new fields per provider: `"response_mode"` (`"query"` / `"fragment"` / `"form_post"`), `"platform"` (`"web"` / `"ios"` / `"android"` / `"any"`). Existing SPA clients ignore unknown fields; new clients can branch on them.
- **Discovery metadata**: New `Provider.discovery_extras() -> dict` method replaces the Google-specific blocks at `fastapi_integration.py:2581-2588` / `flask_integration.py:1677-1684`. Each provider contributes its own `jwks_uri`, `id_token_signing_alg_values_supported`, etc.
- **Dependency**: `PyJWT[crypto]` becomes a core dependency of actingweb 3.11.0 (required for both ES256 client_secret generation and RS256 id_token validation).
- **`github-mobile`**: Kept as today (separate provider entry, prefix-matched by factory). No rename in this release.
- **Logging hygiene**: All token-exchange error logs at `oauth2.py:294-296, 353-355` truncate `response.text` and redact known sensitive fields (`client_assertion`, `assertion`, `id_token`, `client_secret`). Pre-shipped audit confirms no startup banner logs the resolved config dict.
- **Naming**: New Google native provider is registered as `google-native` (not `google-mobile`) to avoid collision with any existing `google-mobile` web-flow entry. Prefix-match in `oauth2.py:937-945` and `_KNOWN_PROVIDER_PREFIXES` at `oauth2_spa.py:53` extended for `apple`, `apple-mobile`, `google-native`.

## What We're NOT Doing

- No changes to actingweb_mcp app — separate plan/PR in that repo. This plan tracks library-side only.
- No Apple Developer Portal automation — manual setup (App ID + Services ID + `.p8`) documented as a runbook, not scripted.
- ~~No rename of `github-mobile` to a per-flow `redirect_uri` model. Future cleanup.~~ **Superseded:** because 3.11.0 is the first public release branded as "full mobile auth," GitHub mobile must reach parity with Apple/Google. See Phase 8 — a `with_github()` builder, mandatory fail-closed PKCE, and a generalized opaque-ticket flow now land in this release.
- No bearer-token validation of raw Apple id_tokens via `Authorization: Bearer`. Apple id_tokens are only accepted via `/oauth/spa/token`'s new grant. `auth.py:_check_oauth2_token()` stays single-provider and userinfo-based.
- No library-level scheduler for Apple's recommended 24h refresh-token validation. Library exposes a helper; apps schedule it themselves.
- No library-level auto-revocation on actor deletion. Apps invoke `revoke_token()` from their own `actor_deleted` hook.
- No new database tables or DynamoDB indexes specifically for Apple. JWKS cache and JWT cache are process-local. The state-nonce store and id_token replay table reuse the existing session manager backend.
- No backward-compat shim for the (never-shipped) `/api/auth/google-mobile` endpoint — actingweb_mcp's coordinating release switches to the new grant on the same drop.

## Phase 1: Strategy-pattern refactor of OAuth2Authenticator (no behavior change)

Move provider-specific branches out of `OAuth2Authenticator` and onto `OAuth2Provider` subclasses. This phase ships zero new functionality and must be a behavior-preserving refactor.

### Changes

- `actingweb/oauth2.py:33-51` — Extend base `OAuth2Provider` with new strategy methods: `build_token_exchange_body(code, redirect_uri) -> dict`, `build_token_exchange_headers() -> dict`, `make_client_secret(time_bucket: int | None = None) -> str`, `extract_user_info_from_token_response(token_response: dict) -> dict | None`, `get_email_from_user_info(user_info: dict) -> tuple[str, str | None]`, `discovery_extras() -> dict`, `supports_refresh_tokens() -> bool`. Default implementations match today's generic OAuth2 behavior.
- `actingweb/oauth2.py:54-77` — `GoogleOAuth2Provider` overrides `extract_user_info_from_token_response` (Google identifier `google:{sub}`), `get_email_from_user_info`, `discovery_extras` (Google JWKS URI).
- `actingweb/oauth2.py:80-100` — `GitHubOAuth2Provider` overrides `build_token_exchange_headers` (User-Agent), `supports_refresh_tokens` (False), `extract_user_info_from_token_response`, `get_email_from_user_info` (with `_get_github_primary_email` fallback now living on the provider).
- `actingweb/oauth2.py:240-308` — `exchange_code_for_token` becomes thin delegator: builds request from `provider.build_token_exchange_body()` + `provider.build_token_exchange_headers()`, passes `provider.make_client_secret()` if non-empty.
- `actingweb/oauth2.py:310-366` — `refresh_access_token` similarly delegates client_secret to `provider.make_client_secret()`.
- `actingweb/oauth2.py:368-426` — `validate_token_and_get_user_info` keeps signature; when `provider.userinfo_uri` is empty it returns `None` (Apple-shaped behavior unlocked in P3). All call sites stay on the existing method.
- `actingweb/oauth2.py:428-495` — same for `validate_token_and_get_user_info_async`.
- `actingweb/oauth2.py:497-572` — `get_email_from_user_info` becomes one-line delegate to `self.provider.get_email_from_user_info(user_info)`.
- `actingweb/oauth2.py:574-672` — `_get_github_primary_email` moves to `GitHubOAuth2Provider._get_primary_email`. The free function stays as a thin shim for backward compat; mark internal.
- `actingweb/oauth2.py:830-891` — `revoke_token` delegates client_secret to `provider.make_client_secret()`.
- `actingweb/oauth2.py:909-910` — keep `_PROVIDER_DISPLAY_NAMES`; provider class exposes `display_name` property reading from this map plus any subclass override.
- `actingweb/oauth2.py:918-950` — `create_oauth2_authenticator` factory branch table refactored to a registry: `_PROVIDER_REGISTRY: dict[str, type[OAuth2Provider]] = {"google": GoogleOAuth2Provider, "github": GitHubOAuth2Provider}`. Prefix matching unchanged.
- `actingweb/oauth2.py:953-982` — `create_google_authenticator` / `create_github_authenticator` shims preserved verbatim (docs and tests reference them).
- `actingweb/interface/integrations/fastapi_integration.py:2581-2588` — replace Google-specific block with `provider.discovery_extras()`.
- `actingweb/interface/integrations/flask_integration.py:1677-1684` — same.
- `actingweb/handlers/oauth2_endpoints.py:967-989` — GitHub-revocation-not-supported note moves to `GitHubOAuth2Provider.supports_revoke()` returning False; handler reads from provider.

### New tests

- `tests/test_oauth_provider_strategy.py` (new): provider-class unit tests — each subclass round-trips `build_token_exchange_body` + `build_token_exchange_headers` + `extract_user_info_from_token_response` + `get_email_from_user_info` for representative inputs. Includes Google `sub`-without-email, GitHub `id`-only, GitHub email fallback.
- `tests/test_actingweb_app.py` — extend existing tests at `:605-610` covering `create_google_authenticator` / `create_github_authenticator` to assert that the returned object still exposes the same public methods.
- `tests/test_mobile_oauth2.py` — existing tests at `:25-67` (`redirect_uri` override) and `:109-165` (`exchange_code_for_token` override) must pass unchanged. These are the regression canaries for the refactor.

### Verification

- [ ] `make test-all-parallel` passes (900+ tests, all unchanged)
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] `poetry run ruff format actingweb tests` no changes needed
- [ ] `git diff` review: zero new branches in `OAuth2Authenticator.exchange_code_for_token` / `refresh_access_token` / `revoke_token` (all branches must move onto provider)
- [ ] Manual: `grep -rn "provider.name == " actingweb/oauth2.py` returns nothing

### Implementation Status: Complete

**Notes / deviations:**
- The plan's provider strategy-method names were adapted to fit the existing
  oauthlib-based authenticator (body building stays on the authenticator via
  `self.client`). Final provider strategy surface: `make_client_secret()`,
  `authorize_extra_params()`, `token_request_headers()`,
  `userinfo_request_headers()`, `supports_refresh_tokens()`, `supports_revoke()`,
  `extract_user_info_from_token_response()`, `extract_identifier_from_user_info()`,
  `get_primary_email()`, `store_provider_identity()`, `discovery_extras()`, plus a
  `display_name` property.
- `OAuth2Authenticator.get_email_from_user_info()` keeps its public signature
  `(user_info, access_token=None, require_email=False)`; it delegates the
  provider-specific parts to `provider.get_primary_email()` /
  `provider.extract_identifier_from_user_info()`.
- `_get_github_primary_email` moved to a module-level free function;
  `OAuth2Authenticator._get_github_primary_email` kept as a thin shim.
- Factory now uses `_PROVIDER_REGISTRY` (base-name prefix match) instead of an
  if/elif chain. `create_google_authenticator` / `create_github_authenticator`
  shims unchanged.
- Discovery extras now come from `provider.discovery_extras()` in both Flask and
  FastAPI integrations (Google block removed).
- All 20 `test_mobile_oauth2.py` regression tests pass unchanged; new
  `tests/test_oauth_provider_strategy.py` (29 tests) added. Full suite green.

---

## Phase 2: PyJWT dep + JWKS validator + JWKS cache infrastructure

Add the cryptographic infrastructure both Apple and Google native flows need. No new endpoints yet.

### Changes

- `pyproject.toml` — add `pyjwt = {extras = ["crypto"], version = "^2.9"}` to core dependencies.
- `actingweb/oauth2_jwks.py` (new) — module-level JWKS cache + fetcher.
  - `_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]]` keyed by JWKS URI.
  - `_JWKS_NEGATIVE_CACHE: dict[str, float]` for unreachable JWKS endpoints.
  - `JWKS_POSITIVE_TTL = 3600.0`, `JWKS_NEGATIVE_TTL = 60.0`, `JWKS_TIMEOUT = (3.0, 5.0)`.
  - `fetch_jwks(jwks_uri: str, *, force: bool = False) -> dict | None`.
  - `get_key_for_kid(jwks_uri: str, kid: str) -> dict | None` — on kid-miss, force-refetch with one debounced retry.
- `actingweb/oauth2_id_token.py` (new) — `JWKSIdTokenValidator` class.
  - Constructor: `(jwks_uri, expected_iss: str | tuple[str, ...], audiences: list[str], algorithms: list[str] = ["RS256"], leeway: int = 60)`.
  - `validate(id_token: str, *, nonce: str | None = None) -> dict | None` returns claims dict on success, None on any failure. Uses PyJWT `decode` with `options={"verify_signature": True, "verify_aud": False}` (we do aud checking ourselves to accept lists) + manual `iss`/`aud`/`exp`/`nonce` checks. Tolerates `iss` as either string or tuple (Apple has experimented with `account.apple.com` vs `appleid.apple.com`).
  - Failures logged at WARNING with claim names but never claim values for sensitive fields.
- `actingweb/oauth2_replay.py` (new) — id_token replay protection.
  - `IdTokenReplayCache` backed by `OAuth2SessionManager` (DynamoDB/Postgres-backed). Key: `jti` if present, else `sha256(iss + sub + iat)`. TTL: `exp - now + 60s leeway`.
  - `check_and_record(claims: dict) -> bool` — returns True if first sight, False if replay.
- `actingweb/oauth2.py` — new helper `OAuth2Provider.id_token_validator: JWKSIdTokenValidator | None`. Default `None`; subclasses can carry one.
- `actingweb/oauth2.py:29-30` — extend the existing `_invalid_token_cache` comment to mention JWKS cache pattern (no merging — separate modules).

### New tests

- `tests/test_oauth2_jwks.py` (new): cache hit/miss/kid-miss/refetch-debounce/positive-TTL-expiry/negative-TTL-expiry. Use `responses` or `requests_mock` to intercept Apple/Google JWKS URLs.
- `tests/test_oauth2_id_token.py` (new): valid-token / wrong-iss / wrong-aud / expired / nonce-mismatch / nonce-required-missing / kid-not-in-jwks. Build test JWTs with `PyJWT` using ephemeral RS256 keys.
- `tests/test_oauth2_replay.py` (new): first-sight passes, immediate replay fails, expired replay window allows re-use.
- `tests/integration/test_oauth2_jwks_live.py` (new, marked `@pytest.mark.slow` and skipped by default): fetch real Apple + Google JWKS once and assert structure. CI runs sequentially only.

### Verification

- [ ] `make test-all-parallel` passes (new tests added)
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] Manual: `python -c "from actingweb.oauth2_jwks import fetch_jwks; print(fetch_jwks('https://appleid.apple.com/auth/keys'))"` returns a JWKS dict with at least one key
- [ ] Negative cache: simulate Apple JWKS unreachable → confirm 60s suppression before retry

### Implementation Status: Complete

**Notes / deviations:**
- `pyjwt[crypto]` added to core deps (resolved to 2.13.0).
- New modules: `oauth2_jwks.py` (module-level JWKS cache: 1h positive TTL, 60s
  negative TTL, kid-miss force-refetch with 5s debounce, fail-soft to stale cache
  / fail-closed when no cache), `oauth2_id_token.py` (`JWKSIdTokenValidator`,
  manual iss/aud/nonce checks, fail-closed on unresolvable kid),
  `oauth2_replay.py` (`IdTokenReplayCache` over the attribute backend, keyed by
  jti or sha256(iss|sub|iat)).
- New bucket/TTL constants added to `constants.py` (`ID_TOKEN_REPLAY_*`,
  `OAUTH_STATE_NONCE_*`, `APPLE_TICKET_*`).
- `OAuth2Provider.id_token_validator` attribute added (default None).
- 30 unit tests (`test_oauth2_jwks.py`, `test_oauth2_id_token.py`,
  `test_oauth2_replay.py`) all passing. The optional live-JWKS integration test
  was not added (deferred; not needed for green CI).

---

## Phase 3: AppleOAuth2Provider + ES256 client_secret + revoke + with_apple_sign_in()

Plumb Apple as a provider — full token exchange, refresh, revocation, and config builder — using only the synchronous OAuth code path (no web/mobile flow yet, no callback POST yet).

### Changes

- `actingweb/oauth2_apple.py` (new) — Apple-specific helpers.
  - `make_apple_client_secret(team_id: str, key_id: str, client_id: str, private_key_pem: str, *, now: int) -> str` — ES256 JWT signing via PyJWT. iss/iat/exp(=now+15777000)/aud/sub claims.
  - `@functools.lru_cache(maxsize=4)` wrapper: `_cached_client_secret(time_bucket: int, provider_name: str) -> str` — re-reads `team_id`/`key_id`/`client_id`/`private_key_pem` from `Config.oauth_providers[provider_name]` inside the function. PEM bytes are NOT in cache key.
  - `load_private_key_pem(provider_config: dict) -> str` — resolves `APPLE_PRIVATE_KEY_PATH` first, then `APPLE_PRIVATE_KEY_PEM`. Validates EC P-256 parses (catches `cryptography` exceptions, re-raises as `ValueError` with explicit message including path/reason).
- `actingweb/oauth2.py` — new `AppleOAuth2Provider(OAuth2Provider)` class.
  - Endpoints: hardcoded Apple URLs (authorize, token, revoke). `userinfo_uri = ""` (no userinfo endpoint).
  - `make_client_secret()` calls `oauth2_apple._cached_client_secret(time_bucket, self.name)`.
  - `extract_user_info_from_token_response(token_response)` decodes the `id_token` field (using `id_token_validator.validate`) and returns the claims dict (`sub`, `email`, `email_verified`, `is_private_email`). Returns None if validation fails.
  - `get_email_from_user_info(user_info)` returns `(f"apple:{sub}", email)` — identifier prefixed for consistency.
  - `discovery_extras()` returns `{"jwks_uri": "https://appleid.apple.com/auth/keys", "id_token_signing_alg_values_supported": ["RS256"]}`.
  - `supports_refresh_tokens()` returns True.
  - `supports_revoke()` returns True.
  - `id_token_validator` carries a `JWKSIdTokenValidator(jwks_uri, expected_iss=("https://appleid.apple.com", "https://account.apple.com"), audiences=config["audiences"])`.
- `actingweb/oauth2.py:909-910` — extend `_PROVIDER_DISPLAY_NAMES` with `"apple": "Apple"`, `"apple-mobile": "Apple"`.
- `actingweb/oauth2.py:918-950` — factory registry extended with `"apple": AppleOAuth2Provider`. Prefix match `apple-` works automatically. Add `create_apple_authenticator(config)` shim mirroring Google/GitHub at `:953-982`.
- `actingweb/interface/app.py:210-261` — `with_oauth()` extended to accept `audiences: list[str] | None` and pass through to `oauth_providers[name]["audiences"]`. Backward compatible (None for non-Apple providers).
- `actingweb/interface/app.py:630-634` — new `with_apple_sign_in(client_id: str, *, audiences: list[str], team_id: str, key_id: str, private_key_path: str | None = None, private_key_pem: str | None = None, scope: str = "openid name email", web_redirect_uri: str = "", mobile_redirect_uri: str = "")` builder.
  - Eagerly validates `team_id`, `key_id`, `client_id` non-empty; resolves `.p8` (file path wins); calls `load_private_key_pem` to validate parse.
  - Registers `apple` provider (web-flow) with `redirect_uri=web_redirect_uri`.
  - If `mobile_redirect_uri` is set, also registers `apple-mobile` with same Apple credentials and `redirect_uri=mobile_redirect_uri` (the custom scheme the mobile app intercepts after the bridge — see P5).
- `actingweb/interface/app.py:139-208` — `_apply_runtime_changes_to_config` writes `audiences`, `apple_team_id`, `apple_key_id`, `apple_private_key_pem`, `apple_audiences` into each provider entry.
- `actingweb/config.py:136-153` — type-annotation update on `oauth_providers` to document the Apple-extra keys.

### New tests

- `tests/test_oauth2_apple.py` (new): `make_apple_client_secret` signs valid ES256 (decode + verify with PyJWT against the public key). `_cached_client_secret` returns the same value within a 5-min bucket; new value after bucket roll. `load_private_key_pem` accepts file path, PEM string, file-precedence. Rejects invalid PEM with explicit message including the path.
- `tests/test_apple_provider.py` (new): `AppleOAuth2Provider.make_client_secret()` integrates with the cache. `extract_user_info_from_token_response` validates a synthetic JWT (test JWKS served via `responses`). `get_email_from_user_info` returns `apple:{sub}`. `discovery_extras` includes Apple JWKS URI.
- `tests/test_actingweb_app.py` — `with_apple_sign_in()` registers expected `oauth_providers` entries; eager validation raises `ValueError` for missing `.p8`, missing `team_id`, etc., with the path/reason in the message.
- `tests/test_mobile_oauth2.py` — extend `_KNOWN_PROVIDER_PREFIXES` test coverage to assert `apple` and `apple-mobile` are accepted.

### Verification

- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] Manual: in a Python REPL, `create_apple_authenticator(config).revoke_token(refresh_token)` builds a POST with a valid ES256 `client_secret` JWT (intercept with `responses`); JWT decodes against the test public key
- [ ] Manual: `app.with_apple_sign_in(...)` with valid `.p8` produces a non-empty `client_secret` JWT inside the 5-min bucket; same value on a second call

### Implementation Status: Complete

**Notes / deviations:**
- New `oauth2_apple.py`: `make_apple_client_secret()`, `_cached_client_secret()`
  (lru_cache keyed by `(time_bucket, provider_name)`; PEM re-read from a module
  registry, never in the cache key), `get_client_secret()`, `load_private_key_pem()`
  (file path wins; literal `\n` conversion; EC-key validation with explicit
  ValueError incl. path/reason). Credentials registered per provider-variant via
  `register_apple_credentials()`.
- `AppleOAuth2Provider` added to `oauth2.py`: hardcoded Apple endpoints,
  `userinfo_uri=""`, ES256 `make_client_secret()`, `response_mode=form_post`
  authorize param, `extract_user_info_from_token_response()` (validates id_token),
  `apple:{sub}` identifier, `discovery_extras()` with Apple JWKS. Carries a
  `JWKSIdTokenValidator` (expected_iss tolerates appleid/account.apple.com).
- Factory: registry gains `"apple"`; concrete provider name threaded via
  `_provider_name` in prov_cfg so apple vs apple-mobile key distinct credentials.
  `create_apple_authenticator()` shim added. Display names extended.
- `with_apple_sign_in()` builder added to `app.py` (eager validation; registers
  `apple` and optional `apple-mobile`). `audiences` flows through `_oauth_configs`
  → `config.oauth_providers` unchanged (no `_apply_runtime_changes` edit needed).
- Tests: `test_oauth2_apple.py`, `test_apple_provider.py`, plus extensions to
  `test_actingweb_app.py` (with_apple_sign_in) and `test_mobile_oauth2.py`
  (apple/apple-mobile prefix). All passing.
- Full suite (`-n auto --dist loadgroup`): 2219 passed; 4 pre-existing parallel
  flakes (peer-sync read-timeouts + one ordered-test-class dep) all pass
  sequentially.

---

## Phase 4: Server-side state nonce store + dedicated POST /oauth/callback/apple

The CSRF-safe Apple callback. Web SPA flow end-to-end.

### Changes

- `actingweb/oauth_state.py` — new `StateNonceStore` class backed by `OAuth2SessionManager`.
  - `create(state_payload: dict, *, ttl: int = 600) -> str` returns an opaque random nonce; stores `{nonce: state_payload}` server-side.
  - `consume(nonce: str) -> dict | None` returns the payload and deletes it (single-use). Returns None on miss/expired/already-consumed.
  - `decode_state()` at `:38-72` extended: if the state value is a short opaque token (e.g. 32-byte URL-safe base64) AND `StateNonceStore.consume(state)` returns a payload, use it. Otherwise fall back to existing cleartext-JSON decode (for Google/GitHub backward compatibility) and Fernet (for MCP).
- `actingweb/handlers/oauth2_spa.py:305-466` — `_build_authorize_state` updated: when provider is `apple` or `apple-mobile`, build the full state dict (provider, csrf, return_path, etc.) as today, then store it via `StateNonceStore.create()` and send the resulting nonce as the `state` URL parameter to Apple. Other providers continue to use the cleartext-JSON path.
- `actingweb/handlers/oauth2_callback.py` — new `OAuth2AppleCallbackHandler` with a `post()` method.
  - Reads `state`, `code`, `id_token`, `user` (JSON string, first-sign-in only) from `application/x-www-form-urlencoded` body.
  - Looks up state via `StateNonceStore.consume(state)`. Returns 400 on miss with message `"Invalid or expired state nonce"`.
  - Validates SameSite=Lax cookies are NOT required (this is documented at the route registration site).
  - For `apple` provider: calls `authenticator.exchange_code_for_token(code, redirect_uri)` (the same redirect_uri Apple was told to use). Validates returned `id_token` via Apple provider's `id_token_validator`. Parses `user` JSON into `{firstName, lastName, email}` and merges into the user_info dict as `given_name`, `family_name`, `email`, `display_name = f"{firstName} {lastName}"` (preserving the on-first-sign-in semantic).
  - For `apple-mobile`: produces a short-lived "exchange ticket" (random opaque value, TTL 5 min) bound to the IdP `code` + Apple's `redirect_uri`. Persists in the session backend. Redirects browser (302) to the configured `apple-mobile.redirect_uri` (custom scheme) with `?ticket=...` (NOT an ActingWeb token). Mobile app intercepts deep link, exchanges ticket via P5.
  - For successful `apple` web flow: calls `_process_spa_oauth_and_create_session` (`oauth2_callback.py:706-1001`) reusing existing logic.
  - Logs at INFO with `kid`, `aud`, `sub` (sanitized). On failure logs at WARNING.
- `actingweb/handlers/oauth2_callback.py` — extract `_merge_apple_user_payload(user_info, user_json_str) -> dict` helper.
- `actingweb/handlers/oauth2_callback.py:670-699` — extend `_is_safe_redirect` allowlist to include configured Apple `redirect_uri` values from `Config.oauth_providers`. Validate `spa_redirect_url` at `:1054-1069` (security risk #6 in the review).
- `actingweb/interface/integrations/flask_integration.py:118-141` — register `POST /oauth/callback/apple` → `OAuth2AppleCallbackHandler.post`. Existing GET `/oauth/callback` route unchanged.
- `actingweb/interface/integrations/fastapi_integration.py:620-648` — same registration.
- `actingweb/oauth2.py:294-296, 353-355` — token-exchange error logger redacts `client_assertion`, `assertion`, `id_token`, `client_secret` from `response.text` before logging. Truncate at 500 chars.
- `actingweb/handlers/oauth2_spa.py:53` — extend `_KNOWN_PROVIDER_PREFIXES` to `("google", "github", "apple", "google-native")`.
- `actingweb/handlers/oauth2_spa.py:200-290` — `/oauth/config` response shape extended: each provider entry gains `"response_mode"` (Apple: `"form_post"`, others: `"query"`) and `"platform"` (`"web"` / `"ios"` / `"android"` / `"any"`). Filter behavior unchanged (clients still see `-mobile` variants but can now distinguish them by platform).

### New tests

- `tests/test_state_nonce_store.py` (new): create / consume / replay-rejection / TTL-expiry / collision-safety (random nonce uniqueness).
- `tests/test_oauth2_callback_apple.py` (new): valid POST callback creates an actor (web flow); invalid state nonce returns 400; replayed state nonce returns 400; first-sign-in `user` JSON merges into `user_info` with normalized field names; subsequent sign-in (no `user` JSON) succeeds and does not overwrite existing display_name; `apple-mobile` POST redirects with `?ticket=...` and NO ActingWeb token in the URL.
- `tests/test_oauth2_callback_apple.py` — verify `_is_safe_redirect` blocks an attacker-supplied `spa_redirect_url`.
- `tests/integration/test_apple_signin_end_to_end.py` (new): seeded test app, mocked Apple endpoints, end-to-end web SPA Apple sign-in producing an ActingWeb session token. Verifies `oauth_success` hook fires with normalized `user_info`.
- `tests/test_logging_redaction.py` (new): assert that a forced token-exchange error log entry does NOT contain `client_assertion`/`assertion`/`id_token`/`client_secret` substrings.

### Verification

- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] Manual: simulate Apple POST with a forged state JSON — handler returns 400 (CSRF protection works)
- [ ] Manual: simulate Apple POST with a valid nonce, second use of same nonce — handler returns 400 (replay protection works)
- [ ] Manual: Apple POST with first-sign-in `user` JSON → `oauth_success` hook receives `given_name`/`family_name` (not `firstName`/`lastName`)
- [ ] Code review: grep for any `logger.*` call that could emit `id_token` or `client_secret` substrings — all such call sites use the redaction helper

### Implementation Status: Complete

**Notes / deviations:**
- `StateNonceStore` + `AppleTicketStore` live in a new module
  `actingweb/oauth_state_store.py` (not appended to `oauth_state.py`) to keep the
  pure state-codec functions dependency-light. `decode_state()` was intentionally
  NOT made to consume nonces (it must stay pure / side-effect-free); the Apple
  POST handler consumes the nonce explicitly instead — same security outcome.
- New `OAuth2AppleCallbackHandler(OAuth2CallbackHandler)` with `post()`: parses
  form body, consumes the single-use nonce (400 on miss/replay), dispatches by
  the payload's `provider`. apple-mobile → opaque ticket deep-link (no token in
  URL); apple web/SPA → stashes the first-sign-in `user` payload and replays the
  request through the shared `get()` path.
- Made the shared callback path Apple-capable: both `get()` and
  `_process_spa_oauth_and_create_session()` now prefer
  `provider.extract_user_info_from_token_response()` (id_token) and fall back to
  the userinfo endpoint — behavior-identical for Google/GitHub.
  `_merge_apple_user_payload()` normalizes Apple's first-sign-in name into
  `given_name`/`family_name`/`display_name` before `oauth_success` fires.
- **Corrected an Apple constraint the plan understated:** Apple's `redirect_uri`
  (authorize + token exchange) must be HTTPS, so `apple-mobile` points Apple at
  the HTTPS `/oauth/callback/apple` and stores the custom-scheme deep link
  separately as `apple_mobile_deep_link` (surfaced as `provider.mobile_deep_link`).
- `/oauth/spa/authorize`: Apple providers now store full state server-side and
  send Apple only the opaque nonce; PKCE is not forwarded to Apple. `/oauth/config`
  gains additive `response_mode` + `platform` per provider. `_KNOWN_PROVIDER_PREFIXES`
  extended to include `apple` / `google-native`.
- Routes `POST /oauth/callback/apple` registered in both Flask and FastAPI.
- Logging redaction helper `_redact_token_response()` applied to token
  exchange/refresh error logs (redacts client_secret/assertion/id_token/
  client_assertion, truncates to 500 chars).
- New tests: `test_state_nonce_store.py`, `test_oauth2_callback_apple.py`
  (errors/replay/mobile-ticket/web-SPA/first-sign-in merge), `test_logging_redaction.py`.
  The live end-to-end integration test (`test_apple_signin_end_to_end.py`) is
  deferred — the web-SPA path is covered by the mocked callback test plus the
  per-component unit tests. 1493 non-integration tests pass.

**Full suite:** 2243 passed; the 5 parallel failures are the same pre-existing
peer-sync timing flakes (all pass sequentially), none OAuth/Apple-related.

---

## Phase 5: JWT-bearer grant + with_google_native() + Android Apple code-redemption

The unified native-OIDC grant on `/oauth/spa/token` plus the Android Apple flow's second leg.

### Changes

- `actingweb/handlers/oauth2_spa.py:664-864` — extend `_handle_authorization_code` (or split into a new `_handle_token_request` dispatcher) to handle three grant types:
  - `authorization_code` (existing, unchanged): mobile passes `code` + `code_verifier`, server exchanges with upstream.
  - `urn:ietf:params:oauth:grant-type:jwt-bearer` (new): mobile passes `assertion` (id_token) + `nonce` + `provider`. Server:
    1. Decodes the JWT header, reads `kid`, validates that `provider` matches the validated `iss` (e.g. `iss=https://appleid.apple.com` only accepted when `provider` resolves to `AppleOAuth2Provider`; `iss=accounts.google.com` only for `GoogleOAuth2Provider`). Mismatch → 400 `"id_token issuer does not match declared provider"`.
    2. Calls `provider.id_token_validator.validate(assertion, nonce=nonce)`.
    3. Checks replay table via `IdTokenReplayCache.check_and_record(claims)`. Replay → 400 `"id_token replay rejected"`.
    4. Calls `provider.get_email_from_user_info(claims)`.
    5. Calls `authenticator.lookup_or_create_actor_by_identifier(identifier, user_info=claims)`.
    6. Issues ActingWeb session token + refresh token via `OAuth2SessionManager`.
    7. Fires `oauth_success` hook with normalized `user_info`.
    8. Returns same JSON shape as the existing `authorization_code` grant.
  - `apple_mobile_ticket` (new, scoped to apple-mobile only): mobile passes `ticket` from the deep link. Server:
    1. Consumes the ticket from the session backend (single-use, 5-min TTL).
    2. Retrieves the IdP `code` and Apple `redirect_uri` associated with the ticket.
    3. Calls `apple_authenticator.exchange_code_for_token(code, redirect_uri)` with the ES256 client_secret.
    4. Validates returned id_token, looks up/creates actor, issues tokens (same as above).
- `actingweb/interface/app.py:630-634` — new `with_google_native(client_id: str, *, audiences: list[str] | None = None, web_client_id: str | None = None, ios_client_id: str | None = None, android_client_id: str | None = None, android_server_client_id: str | None = None, scope: str = "openid profile email", redirect_uri: str = "")` builder. If `audiences` is None, builds it from the four `*_client_id` kwargs (filtering None). Registers `google-native` provider. Eager validation: at least one of `audiences` (after build) must be non-empty.
- `actingweb/oauth2.py` — `GoogleOAuth2Provider` gains an `id_token_validator` when `audiences` is set in provider config: `JWKSIdTokenValidator(jwks_uri="https://www.googleapis.com/oauth2/v3/certs", expected_iss=("accounts.google.com", "https://accounts.google.com"), audiences=config["audiences"])`.
- `actingweb/oauth2.py:918-950` — factory registry adds `"google-native": GoogleOAuth2Provider`. Prefix matching unchanged.
- `actingweb/handlers/oauth2_spa.py:53` — already extended in P4, confirm `google-native` is in the list.
- `actingweb/handlers/oauth2_spa.py` — `_validate_id_token_for_provider(provider_name, assertion, nonce)` helper consolidates the four-step validation above; shared between JWT-bearer and apple_mobile_ticket grants.
- `actingweb/handlers/oauth2_callback.py` — Apple callback handler from P4 calls into the same ticket-issuing helper as the apple_mobile_ticket consumer in P5.
- `actingweb/handlers/oauth2_spa.py` — new helper `_normalize_user_info(provider_name, raw)` producing `{display_name, given_name, family_name, email, sub, ...passthrough}`. Apple `firstName`/`lastName` → `given_name`/`family_name`; Google passes through; GitHub `name` → `display_name`. Called immediately before firing `oauth_success` in all token-issuing code paths (callback handler + JWT-bearer grant + apple_mobile_ticket grant).
- `actingweb/oauth2.py:688-765` — `lookup_or_create_actor_by_identifier` modified: the `actor.store.oauth_provider = self.provider.name` write moves out of the create-only branch (`:729`) into the function tail so it runs on both create and lookup paths. The lookup-path branch at `oauth_session.py:209` keeps its write for the legacy callback path.

### New tests

- `tests/test_oauth2_spa_jwt_bearer.py` (new): valid Apple id_token via JWT-bearer grant creates session; valid Google id_token via JWT-bearer creates session; provider/iss mismatch returns 400; replay returns 400; missing nonce returns 400; expired token returns 400; wrong aud returns 400; identifier extracted as `apple:{sub}` / `google:{sub}`.
- `tests/test_oauth2_spa_apple_ticket.py` (new): valid ticket consumption produces session; replayed ticket returns 400; expired ticket returns 400.
- `tests/test_actingweb_app.py` — `with_google_native()` registration tests; audiences-derivation from `*_client_id` kwargs; rejects empty audiences.
- `tests/test_user_info_normalization.py` (new): `_normalize_user_info("apple", {"firstName": "Jane", "lastName": "Doe", ...})` produces `given_name="Jane"`, `family_name="Doe"`, `display_name="Jane Doe"`. Google passthrough. GitHub `name` → `display_name`.
- `tests/integration/test_apple_android_flow.py` (new): full Android Apple flow — POST /oauth/callback/apple with `apple-mobile` provider produces a ticket deep-link; mobile POSTs ticket to /oauth/spa/token; receives session token.
- `tests/test_actor_oauth_provider_property.py` (new): `oauth_provider` property is written on both create and existing-actor sign-in paths.

### Verification

- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] Manual: forged JWT-bearer request claiming `provider=apple-mobile` with a Google id_token → 400 (iss/provider mismatch protection works)
- [ ] Manual: same id_token submitted twice within its TTL → second submission returns 400 (replay protection works)
- [ ] Manual: Android Apple end-to-end with mocked Apple endpoints produces a session token AND the deep link contains a ticket, NOT an ActingWeb access token
- [ ] Code review: grep `oauth_success` firing sites — all call `_normalize_user_info` first

### Implementation Status: Complete

**Notes / deviations:**
- `_handle_token` dispatches two new grants:
  `urn:ietf:params:oauth:grant-type:jwt-bearer` (`_handle_jwt_bearer_grant`) and
  `apple_mobile_ticket` (`_handle_apple_mobile_ticket`).
- `_validate_id_token_for_provider()` dispatches the validator by the declared
  `provider`, and pre-checks the token `iss` against that provider's accepted
  issuers (clear 400 on mismatch) before signature validation — so a Google
  id_token submitted as `apple-mobile` is rejected.
- Replay protection via `IdTokenReplayCache.check_and_record()` (400 on replay).
- `_finalize_native_session()` shared tail (actor lookup/create, actor_created +
  oauth_success hooks, ActingWeb token issuance, response shaping) — works with
  or without an upstream access token (JWT-bearer has only the id_token; the
  ticket grant has the full Apple token set and persists them for revocation).
- `_normalize_user_info()` module helper produces the consistent
  display_name/given_name/family_name/email shape; called in the
  authorization_code, JWT-bearer, and ticket paths before `oauth_success`.
- `GoogleOAuth2Provider` gains a `JWKSIdTokenValidator` (+ audiences) when
  audiences are configured; `extract_user_info_from_token_response()` validates
  the id_token for the native path. `google-native` resolves via the existing
  `google` prefix match.
- `with_google_native()` builder added (derives audiences from the per-platform
  client IDs or accepts an explicit list; rejects empty).
- `lookup_or_create_actor_by_identifier()` now writes `actor.store.oauth_provider`
  on the existing-actor path too (previously create-only).
- New tests: `test_oauth2_spa_jwt_bearer.py` (12), `test_oauth2_spa_apple_ticket.py`
  (4), `test_user_info_normalization.py` (6), `test_actor_oauth_provider_property.py`
  (2), plus `with_google_native` cases in `test_actingweb_app.py`. 1522
  non-integration tests pass; ruff + pyright clean.

---

## Phase 6: MCP server on-demand authenticator + Apple in LLM-triggered OAuth web form

Provide parity between SPA-triggered OAuth and LLM-triggered OAuth so Apple is offered in both.

### Changes

- `actingweb/oauth2_server/oauth2_server.py:45-54` — remove pre-instantiated `self.google_authenticator` / `self.github_authenticator`. Add `self._authenticator_cache: dict[str, OAuth2Authenticator] = {}` and `_get_authenticator(provider_name)` that lazily calls `create_oauth2_authenticator(self.config, provider_name)`.
- `actingweb/oauth2_server/oauth2_server.py:196-208` — `handle_authorization_request()` provider branching becomes `_get_authenticator(provider_name).create_authorization_url(...)`. Apple's authorize-URL construction routes through `AppleOAuth2Provider.create_authorization_url()` which sets `response_mode=form_post` automatically.
- `actingweb/oauth2_server/oauth2_server.py:269, 289-294` — `handle_oauth_callback()` provider branching becomes `_get_authenticator(provider_name).exchange_code_for_token(...)`. For Apple's POST callback, the integration layer marshals `request.form` data into the same `params` dict the handler reads.
- `actingweb/oauth2_server/state_manager.py:25-117` — extend Fernet payload to optionally carry `apple_state_nonce`. When MCP issues an Apple-bound authorize, also persists a `StateNonceStore` entry. Apple's POST callback (P4) checks both: cleartext JSON state → SPA flow; opaque nonce hit in `StateNonceStore` → could be SPA or MCP; the consumed payload carries `mcp_context` if it's an MCP flow, in which case the existing MCP completion path runs.
- `actingweb/handlers/oauth2_endpoints.py:459-718` — MCP authorization form provider enumeration adds Apple. Provider list filter check confirms Apple-mobile is excluded from the LLM-triggered web form (only `apple` web variant is offered).
- `actingweb/handlers/oauth2_endpoints.py:643-675` — Fernet state composition for Apple route preserves `mcp_context` payload; combined with the nonce store so `/oauth/callback/apple` POST can decode.
- `actingweb/handlers/oauth2_callback.py` — Apple callback handler from P4: after `StateNonceStore.consume`, inspect the payload for `mcp_context`. If present, dispatch to `ActingWebOAuth2Server.handle_oauth_callback()` (mirrors the existing logic at `oauth2_server.py:235-302`). Otherwise SPA path as in P4.

### New tests

- `tests/test_oauth2_server_lazy_authenticator.py` (new): `_get_authenticator` caches per name; unknown provider returns appropriate error; Apple is reachable.
- `tests/test_mcp_apple_signin.py` (new): MCP-initiated Apple authorize URL contains `response_mode=form_post`; Apple POST callback with MCP-bound nonce dispatches to MCP completion path; SPA-bound nonce dispatches to SPA completion path.
- `tests/integration/test_mcp_apple_end_to_end.py` (new): full LLM-triggered Apple OAuth web flow producing an MCP-completion response.

### Verification

- [ ] `make test-all-parallel` passes
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] Manual: LLM-triggered OAuth form lists Apple as an option (web SPA equivalence)
- [ ] Manual: completing the LLM-triggered Apple flow produces the same MCP completion response shape Google/GitHub produce today
- [ ] Manual: SPA-initiated and MCP-initiated Apple flows never cross-contaminate (a state nonce from one flow does NOT complete the other flow)

### Implementation Status: Complete

**Notes / deviations:**
- `ActingWebOAuth2Server`: pre-instantiated `google_authenticator` /
  `github_authenticator` replaced with `_get_authenticator(provider_name)` (lazy
  + cached). Kept `google_authenticator` / `github_authenticator` as properties
  delegating to it for backward compat. `handle_authorization_request` and
  `handle_oauth_callback` now use `_get_authenticator`, making Apple reachable.
- MCP callback `handle_oauth_callback` made Apple-capable (prefers
  `extract_user_info_from_token_response`, userinfo fallback).
- Apple authorize in the MCP form / `handle_authorization_request`: the encrypted
  Fernet MCP state is wrapped in a `StateNonceStore` nonce (because Apple
  form_posts); `POST /oauth/callback/apple` consumes the nonce, detects
  `mcp_state` in the payload, and dispatches to
  `ActingWebOAuth2Server.handle_oauth_callback()` via
  `_dispatch_apple_mcp_callback()`. SPA-bound nonces (no `mcp_state`) take the SPA
  path — verified no cross-contamination.
- MCP authorization form enumeration skips `-mobile` / `-native` variants (native
  flows aren't offered in the web form) and nonce-wraps Apple's state.
- New tests: `test_oauth2_server_lazy_authenticator.py` (4),
  `test_mcp_apple_signin.py` (3: form_post URL, MCP dispatch, SPA-no-dispatch).
  The full MCP end-to-end integration test is deferred (client-registration
  setup heavy); the dispatch + routing are covered by the focused tests.

---

## Phase 7: Docs + CHANGELOG + release prep

### Changes

- `docs/guides/apple-sign-in.rst` (new) — Apple Developer Portal runbook (App ID, Services ID, `.p8`, Team ID, Key ID), `with_apple_sign_in()` usage, the `audiences` list explanation, first-sign-in-only `user` payload semantics, `actor_deleted` → `revoke_token` pattern, env var precedence (`APPLE_PRIVATE_KEY_PATH` vs `APPLE_PRIVATE_KEY_PEM`), iOS/Android Capacitor integration notes, and the MCP/LLM-triggered web flow equivalence.
- `docs/guides/spa-authentication.rst` — add section on the JWT-bearer grant on `/oauth/spa/token`, request/response shape, and the migration table from any prior custom mobile auth endpoints.
- `docs/reference/routing-overview.rst` — document that `/oauth/callback/apple` accepts POST, and that `/oauth/spa/token` now supports `urn:ietf:params:oauth:grant-type:jwt-bearer` and `apple_mobile_ticket` grants in addition to `authorization_code` and `refresh_token`.
- `docs/reference/hooks-reference.rst` — document the normalized `user_info` shape passed to `oauth_success` (`display_name`, `given_name`, `family_name`, `email`, `sub`, plus passthrough). Note Apple's first-sign-in-only quirk.
- `docs/guides/authentication.rst` — update OAuth2 provider table to include Apple. Cross-reference `with_apple_sign_in()` and `with_google_native()` builders.
- `docs/quickstart/configuration.rst` — add Apple env vars to the configuration reference. Add MCP parity note for OAuth web form.
- `CHANGELOG.rst` — "Unreleased" entry covering: PyJWT[crypto] core dep added; Apple Sign-In support (web SPA, native iOS, Android Capacitor, LLM-triggered MCP web form); new `with_apple_sign_in()` and `with_google_native()` builders; new JWT-bearer grant on `/oauth/spa/token`; new POST `/oauth/callback/apple` endpoint; normalized `user_info` shape on `oauth_success` hook; server-side state nonce store; id_token replay protection; Apple revocation via existing `revoke_token()`; `actor.store.oauth_provider` written on every sign-in.
- `thoughts/coordination/2026-05-29-actingweb-mcp-apple-changes.md` (new) — coordination checklist for the actingweb_mcp consuming repo (not committed to library docs — lives in `thoughts/`).

### New tests

No new code tests in this phase. Documentation-only.

### Verification

- [x] All docs build (`sphinx-build` from repo root succeeds with **0 warnings**;
  conf.py is at the repo root, not `docs/`)
- [x] `CHANGELOG.rst` "Unreleased" entry is accurate
- [x] Manual: code examples in `apple-sign-in.rst` match the shipped
  `with_apple_sign_in()` / `with_google_native()` / grant APIs
- [ ] Sample app bootstrap demonstrating `with_apple_sign_in()` — deferred to the
  actingweb_mcp coordination work (checklist written)

### Implementation Status: Complete

**Notes / deviations:**
- Docs build from the **repo root** (`conf.py` at root, RTD `configuration: conf.py`),
  not `docs/`. `sphinx-build . _build` → 0 warnings; `apple-sign-in.html` renders.
- Delivered: new `docs/guides/apple-sign-in.rst` (+ toctree entry), JWT-bearer
  section + migration note in `spa-authentication.rst`, OAuth endpoints/grants in
  `routing-overview.rst`, normalized `user_info` + first-sign-in quirk in
  `hooks-reference.rst`, Apple provider cross-ref in `authentication.rst`, Apple
  env vars + MCP parity note in `configuration.rst`, CHANGELOG "Unreleased"
  entry, and `thoughts/coordination/2026-05-29-actingweb-mcp-apple-changes.md`.

---

## Phase 8: GitHub mobile parity — generalized mobile-ticket flow, mandatory PKCE, with_github() builder

3.11.0 is the first public release advertising full mobile auth, so GitHub mobile must be a first-class, secure, documented citizen — not the hand-wired `with_oauth(provider="github-mobile", redirect_uri="custom://...")` the consuming app uses today.

**Protocol constraint:** GitHub OAuth issues no OIDC `id_token` — identity comes from the `/user` API after an `authorization_code → access_token` exchange. So GitHub *cannot* use the JWT-bearer grant; its mobile path is structurally the Apple-on-Android pattern (web flow → server-side code exchange), not the Google/Apple-iOS native-id_token pattern.

This phase has three threads:

1. **Generalized opaque-ticket flow** so the authorization code never reaches the device for *any* mobile provider (today only Apple-Android is protected this way; `github-mobile` ships the raw `code` in the deep link).
2. **Mandatory fail-closed PKCE** for any native `authorization_code` exchange that still uses a custom-scheme redirect (today PKCE is optional and only warns — `oauth2_spa.py:775`).
3. **`with_github()` builder** mirroring `with_apple_sign_in()`'s dual web/mobile registration.

### Changes

- `actingweb/oauth_state_store.py` — generalize `AppleTicketStore` into a provider-agnostic `MobileTicketStore` (opaque, single-use, short-TTL record `{provider, code, redirect_uri}`). Keep `AppleTicketStore` as a thin subclass/alias so existing imports and `tests/test_state_nonce_store.py` / `tests/test_oauth2_spa_apple_ticket.py` keep working.
- Config key generalization: `apple_mobile_deep_link` → `mobile_deep_link`. The Apple provider and `is_safe_spa_redirect` read both keys (back-compat); new code writes `mobile_deep_link`.
- `actingweb/handlers/oauth2_callback.py` (`GET /oauth/callback`, the `get()` path) — add a mobile-ticket branch mirroring the Apple form_post handler (`oauth2_callback.py:1252`): when the resolved provider is a `-mobile` variant with a configured `mobile_deep_link`, store `{provider, code, redirect_uri}` in `MobileTicketStore` and 302 to `mobile_deep_link?ticket=...` instead of completing a web session. No token or code in the redirect URL.
- `actingweb/handlers/oauth2_callback.py` (Apple form_post handler, `:1252`) — refactor to call the shared `MobileTicketStore` (behavior-preserving).
- `actingweb/handlers/oauth2_spa.py:1166` — generalize `_handle_apple_mobile_ticket` into `_handle_mobile_ticket`: consume the ticket, resolve the provider from the stored record, `exchange_code_for_token(code, redirect_uri=...)` server-side, then provider-appropriate identity extraction — `validate_token_and_get_user_info()` for GitHub's userinfo path, `extract_user_info_from_token_response()` for Apple's id_token path — then `_finalize_native_session(...)`.
- `actingweb/handlers/oauth2_spa.py:585` (`_handle_token`) — add `grant_type == "mobile_ticket"` → `_handle_mobile_ticket`; keep `apple_mobile_ticket` as an alias to the same handler.
- `actingweb/handlers/oauth2_spa.py:775` (`_handle_authorization_code`) — replace the warn-only PKCE check: when the provider is a `-mobile`/native variant **or** `redirect_uri` uses a non-`http(s)` (custom) scheme, require `code_verifier` and return `400 "PKCE code_verifier required for native authorization_code exchange"` if absent. Web/SPA same-origin server-managed-PKCE exchanges are unaffected.
- `actingweb/handlers/oauth2_callback.py:91` (`is_safe_spa_redirect`) — also read `mobile_deep_link` (not just `apple_mobile_deep_link`) when allowlisting redirect origins, so the github-mobile deep link is an accepted target.
- `actingweb/interface/app.py` — add `with_github(client_id, client_secret, *, scope="read:user user:email", redirect_uri="", mobile_redirect_uri="")`. Registers `github` (web) with the standard GitHub auth/token URIs (apps no longer hand-pass `auth_uri`/`token_uri`); when `mobile_redirect_uri` is set, also registers `github-mobile` with HTTPS `redirect_uri` defaulting to `/oauth/callback` and `mobile_deep_link=mobile_redirect_uri`. Mirrors `with_apple_sign_in()`. Existing `with_oauth(provider="github", ...)` stays valid.
- `docs/guides/spa-authentication.rst` / `docs/guides/authentication.rst` — document the generic `mobile_ticket` grant and a GitHub-on-mobile runbook alongside the Apple/Google flows; state the mandatory-PKCE rule for custom-scheme exchanges.

### New tests

- `tests/test_oauth2_spa_mobile_ticket.py` (new) — generic `mobile_ticket` grant for `github-mobile` (server-side code exchange → userinfo → session); `apple_mobile_ticket` alias still routes to the same handler; expired/invalid/replayed ticket → 400.
- `tests/test_oauth2_callback_github_mobile.py` (new) — `GET /oauth/callback` for a `github-mobile` provider stores a ticket and redirects to the deep link with only `?ticket=`; assert neither `code` nor any token appears in the redirect URL.
- `tests/test_oauth2_spa.py` — PKCE fail-closed: mobile/custom-scheme `authorization_code` without `code_verifier` → 400; web same-origin exchange still succeeds.
- `tests/test_actingweb_app.py` — `with_github()` registers `github` + `github-mobile` with correct config; the mobile entry carries `mobile_deep_link` and an HTTPS `redirect_uri`.
- `tests/test_state_nonce_store.py` — `MobileTicketStore` round-trip + single-use; `AppleTicketStore` alias compatibility.

### Verification

- [ ] `make test-all-parallel` passes (existing + new tests)
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` / `ruff format` clean
- [ ] Manual: grep that no `-mobile`/custom-scheme `authorization_code` path can proceed without a `code_verifier`
- [ ] Manual: the `github-mobile` deep link carries only an opaque `ticket` (no `code`, no token)
- [ ] `apple_mobile_ticket` grant + `AppleTicketStore` import still pass unchanged (back-compat)
- [ ] Docs build with 0 warnings

### Implementation Status: Planned

**Open design notes:**
- `mobile_ticket` vs keeping per-provider grant names: chosen approach is one generic grant + `apple_mobile_ticket` alias, so the app's frontend uses a single redemption path regardless of provider.
- Whether `with_github()` should *deprecate* the raw `with_oauth(provider="github")` form: no — keep both; `with_github()` is the ergonomic path, `with_oauth` remains the escape hatch.
- Custom-scheme direct-exchange (pattern A) stays supported but is now PKCE-gated; the generalized ticket flow (pattern B) is the documented recommendation because the code never touches the device and the client never needs the client_secret.

---

## Evaluation Notes

### Architecture
The architecture-evaluation agent identified five risks. Top three drove plan adjustments:

1. **MCP server's pre-instantiated authenticators** (`oauth2_server/oauth2_server.py:45-54`) cannot reach Apple without an on-demand refactor. **Addressed in P6** with `_get_authenticator(provider_name)` lazy lookup.
2. **State decoding diverges between SPA cleartext-JSON and MCP Fernet**. The original "one /oauth/callback POST handler" plan was too simple. **Addressed in P4 + P6** by introducing a dedicated `/oauth/callback/apple` route backed by `StateNonceStore` that holds payloads (cleartext or MCP-context) keyed by an opaque random nonce — both flows present an opaque nonce to Apple; the handler distinguishes via the consumed payload's contents.
3. **Strategy refactor touches the most-called surface**. **Addressed by Phase 1's "behavior-preserving" constraint**: `OAuth2Authenticator` method signatures and the `actingweb.oauth2.requests` module-level patch point preserved. 60+ call sites and 4 mock-patching test files continue to work without changes. Phase 1 ships zero new functionality precisely so this is reviewable in isolation.

Also addressed: `_PROVIDER_DISPLAY_NAMES`, factory else-branch, and discovery metadata sites — all extended in P1/P3 via the new `Provider.discovery_extras()` strategy method.

The agent's suggested `google-native` naming (instead of `google-mobile`) was adopted to avoid collision with the existing `google-mobile` web-flow provider entry.

### Security
The security-evaluation agent flagged seven concerns. Five drove plan adjustments:

1. **CRITICAL: SPA cleartext state is unauthenticated; Apple's cross-site POST opens CSRF**. **Addressed in P4** with `StateNonceStore` + dedicated `/oauth/callback/apple` POST route. Standards basis: RFC 9700 §4.7, OIDC Core §15.5.2, OWASP OAuth Cheat Sheet; matches django-allauth, python-social-auth, Curity implementations. State sent to Apple is just an opaque nonce; server holds the full payload; SameSite=Lax cookies are not needed for state binding.
2. **HIGH: SameSite=Lax cookies don't survive cross-site POST**. **Addressed implicitly**: the nonce-store design doesn't depend on cookies for state binding. Documented at the route registration site.
3. **HIGH: JWT-bearer grant validator dispatched by `iss`, not request body `provider`**. **Addressed in P5** — `_validate_id_token_for_provider` checks that the validated `iss` matches the declared `provider` and rejects mismatches.
4. **HIGH: Replay protection**. **Addressed in P2** with `IdTokenReplayCache` backed by the session manager; **invoked in P5**.
5. **HIGH: Android session-token-in-deep-link risk**. **Addressed in P4 + P5** — Android Apple flow delivers an opaque exchange ticket via deep link; mobile exchanges ticket for ActingWeb tokens. No long-lived token in any deep link.
6. **MED: Token-exchange error logger leaks assertions**. **Addressed in P4** — redaction helper applied at `oauth2.py:294-296, 353-355`; `tests/test_logging_redaction.py` asserts no leak.
7. **MED: JWKS fail-closed posture**. **Addressed in P2** — `JWKSIdTokenValidator.validate()` returns None (rejected) when no cached keys are available and the fetch fails.

### Scalability
Eight findings:

1. **JWKS cache as module-level dict** — adopted pattern in `actingweb/oauth2_jwks.py`. 1h positive TTL, 60s negative TTL, kid-miss force-refetch with debounce, `timeout=(3, 5)`. Per-Lambda-container behavior accepted (documented).
2. **Positive id_token validation cache for `_check_oauth2_token`** — not needed for this plan: id_tokens are NOT accepted as raw bearer tokens (out of scope). Documented.
3. **`make_jwt` lru_cache key safety** — adopted: key is `(time_bucket, provider_name)`; PEM bytes re-read inside the function from `Config.oauth_providers`. Test `tests/test_oauth2_apple.py` verifies cache safety.
4. **`oauth_provider` write cost** — accepted (1 GetItem + 1 PutItem per sign-in). Documented in the `oauth_provider`-on-every-sign-in decision.
5. **`lookup_or_create_actor_by_identifier` cost** — already O(1) via existing `creator_index` GSI; no change.
6. **JWKS cold-start latency** — `(3, 5)` timeout adopted. Recommend measuring p99 before shipping (verification step).
7. **Apple 24h refresh validation** — library exposes helper only; no scheduler. Documented in `docs/guides/apple-sign-in.rst`.
8. **`oauth_provider` indexed?** — opt-in via existing `with_indexed_properties()`. Not enabled by default in this release.

Measurement work added to the verification step: p50/p99 JWKS GET latency, RS256 verify latency, end-to-end JWT-bearer grant latency, `make_jwt` cache hit rate.

### Usability
Seven findings:

1. **Apple builder vocabulary mismatch** — adopted: `with_apple_sign_in(client_id=services_id, audiences=[services_id, bundle_id], …)`. Consistent with `with_oauth()`; collapses the dual-aud quirk into one list. Documented in P3.
2. **`with_google_native()` requiredness** — adopted: all four `*_client_id` kwargs individually optional; `audiences` derived from them or supplied directly. Documented in P5.
3. **`/oauth/config` cannot distinguish form_post vs redirect** — adopted: additive `"response_mode"` and `"platform"` fields. Documented in P4.
4. **Error message style** — adopted in P3 (eager validation with explicit messages) and P4 (specific Apple-callback errors). All "Apple "-prefixed errors include the failing context (path, claim, JWKS URL).
5. **Hook contract `user_info` shape change** — adopted: `_normalize_user_info` in P5 produces a consistent `display_name` / `given_name` / `family_name` / `email` / `sub` shape regardless of provider. Documented in P7's `hooks-reference.rst` update.
6. **`apple` vs `apple-mobile` duality** — adopted: `"platform"` field in `/oauth/config` distinguishes; existing `-mobile`-suffix filtering pattern still works for clients that don't want to branch on platform.
7. **Documentation deliverables** — fully covered in P7: `apple-sign-in.rst`, `spa-authentication.rst` migration table, `routing-overview.rst` route updates, `hooks-reference.rst` user_info shape, `authentication.rst` provider table, `configuration.rst` env vars, CHANGELOG.

---

## Implementation Summary

**Completed:** 2026-06-14
**All phases:** Complete (1–7)
**Test status:** All passing (2279 passed in the full parallel suite; the 4–5
recurring failures are pre-existing peer-to-peer subscription-sync timing flakes
that pass sequentially — none OAuth/Apple-related). ruff + pyright: 0 errors.
Docs: `sphinx-build` from repo root, 0 warnings.

### Deviations from Plan
- **Apple `redirect_uri` must be HTTPS** (plan understated this): `apple-mobile`
  points Apple at the HTTPS `/oauth/callback/apple` for both authorize and token
  exchange; the custom-scheme deep link is stored separately as
  `apple_mobile_deep_link` (`provider.mobile_deep_link`), used only for the final
  app handoff.
- **`StateNonceStore`/`AppleTicketStore` live in a new `oauth_state_store.py`**
  (not appended to `oauth_state.py`), and `decode_state()` was kept pure — the
  Apple POST handler consumes nonces explicitly rather than giving the shared
  decoder a destructive side-effect.
- **`_get_authenticator` properties retained** (`google_authenticator` /
  `github_authenticator` as delegating properties) for backward compat with
  existing call sites/tests, rather than removing them outright.
- **Deferred (low-value / heavy-setup) integration tests:** live JWKS fetch,
  full web-SPA Apple end-to-end against a running server, and full MCP Apple
  end-to-end (client-registration heavy). Each is covered by focused
  mocked/unit tests of its components; noted in the per-phase status.
- **Strategy method names** were adapted from the plan's sketch to fit the
  existing oauthlib-based authenticator while preserving all public signatures.

### Learnings
- The repo's Sphinx `conf.py` is at the **repository root** (RTD
  `configuration: conf.py`), so docs build from root, not `docs/`.
- The full parallel suite **must** be run with `--dist loadgroup` (as the
  Makefile does); without it, DB-sharing integration tests scatter across xdist
  workers and produce ~140 spurious failures. Running `pytest -n auto` alone is
  misleading.
- A handful of peer-to-peer subscription-sync integration tests are timing-flaky
  under parallel execution (read timeouts on the local peer server); they pass
  reliably when run sequentially.

### New / changed library modules
- New: `oauth2_jwks.py`, `oauth2_id_token.py`, `oauth2_replay.py`,
  `oauth2_apple.py`, `oauth_state_store.py`.
- Changed: `oauth2.py` (strategy refactor + `AppleOAuth2Provider` + registry +
  redaction), `handlers/oauth2_spa.py` (grants + normalization),
  `handlers/oauth2_callback.py` (`OAuth2AppleCallbackHandler`),
  `handlers/oauth2_endpoints.py` (MCP form), `oauth2_server/oauth2_server.py`
  (lazy authenticator), `interface/app.py` (builders),
  Flask/FastAPI integrations (Apple route + discovery extras), `constants.py`,
  `pyproject.toml` (PyJWT[crypto]).
- New test files: `test_oauth_provider_strategy.py`, `test_oauth2_jwks.py`,
  `test_oauth2_id_token.py`, `test_oauth2_replay.py`, `test_oauth2_apple.py`,
  `test_apple_provider.py`, `test_state_nonce_store.py`,
  `test_oauth2_callback_apple.py`, `test_logging_redaction.py`,
  `test_oauth2_spa_jwt_bearer.py`, `test_oauth2_spa_apple_ticket.py`,
  `test_user_info_normalization.py`, `test_actor_oauth_provider_property.py`,
  `test_oauth2_server_lazy_authenticator.py`, `test_mcp_apple_signin.py`.
