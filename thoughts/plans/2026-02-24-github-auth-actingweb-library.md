# Implementation Plan: Multi-Provider OAuth Support (ActingWeb Library)

**Date:** 2026-02-24
**Status:** Implemented
**Research:** thoughts/research/2026-02-24-github-auth-provider.md
**Branch:** support-github-as-auth-provider-alongside-google-auth
**Repo:** ../actingweb

## Update Log

- **2026-02-25**: Added Phase 4 (Documentation Updates) after reviewing all docs/ files for multi-provider OAuth impact. 10 documentation files identified for updates across configuration, authentication, SPA, security, and migration guides.
- **2026-02-25**: Deep codebase audit found 17 single-provider locations. 4 gaps not covered by original plan: (1) SPA state missing provider field, (2) token revocation hardcoded to Google, (3) legacy bearer token validation, (4) 401 redirect target. Added fixes to Phase 2, new decisions recorded. Usage model: each user logs in via one provider at a time, typically sticks with one, but email-based linking allows same user to use both.

## Overview

Extend the ActingWeb library to support multiple OAuth providers simultaneously (Google + GitHub). Currently the library is single-provider-at-a-time: one `config.oauth` dict, one `config.oauth2_provider` string. This plan adds `config.oauth_providers` as a dict-of-dicts, extends `with_oauth()` to accept a `provider` parameter for multiple calls, and updates all handler/factory code to use per-provider credentials and return all configured providers.

## Decisions Made

- **Credential storage**: Dict-of-dicts in `config.oauth_providers`, fluent `.with_oauth(provider="google", ...).with_oauth(provider="github", ...)` builder API
- **Callback routing**: Encode `provider` in state parameter (both plain JSON, SPA JSON state, and encrypted MCP state)
- **Scopes**: `read:user user:email` for GitHub
- **Library change scope**: Minimal additive — `config.oauth_providers` alongside existing `config.oauth` for backward compat
- **Usage model**: Each user logs in via one provider at a time. Same user can use both providers if GitHub provides a verified email matching the actor's creator. Typically users stick with one provider. [Added 2026-02-25]
- **Legacy bearer token validation**: Default provider only — ActingWeb-generated session tokens are the primary validation path and don't need provider info. Raw OAuth bearer tokens (legacy fallback) validate against the default provider. [Added 2026-02-25]
- **401 redirect target**: Redirect to `/login` (factory page) where all configured providers are shown, letting the user choose. Don't redirect directly to a single provider's OAuth page. [Added 2026-02-25]
- **Token revocation**: Look up provider from session/actor data. GitHub doesn't support token revocation anyway. Primary logout action is invalidating the ActingWeb session. [Added 2026-02-25]

## What We're NOT Doing

- Removing `config.oauth` or `config.oauth2_provider` — kept for backward compat
- Adding account linking UI or explicit user confirmation — email-based linking via `email_as_creator` works as-is
- Adding new OAuth providers beyond Google and GitHub
- Refactoring the Flask integration beyond the minimum needed (discovery endpoints)

## Phase 1: Config & Provider Infrastructure

### Changes

- `../actingweb/actingweb/config.py:136-149` — Add `self.oauth_providers: dict[str, dict[str, str]] = {}` attribute alongside existing `self.oauth`. When `oauth_providers` is populated, `self.oauth` should point to the first provider's config for backward compat. Keep `self.oauth2_provider` but it becomes the "default" provider name.

- `../actingweb/actingweb/interface/app.py:58` — Change `self._oauth_config: dict[str, Any] | None = None` to `self._oauth_configs: dict[str, dict[str, Any]] = {}`.

- `../actingweb/actingweb/interface/app.py:193-218` — Extend `with_oauth()` to accept optional `provider: str = ""` parameter. When `provider` is specified, store in `self._oauth_configs[provider]`. When not specified (backward compat), store as the single default. Multiple calls accumulate in the dict.

- `../actingweb/actingweb/interface/app.py:151-153` — Update `_apply_runtime_changes_to_config()`: populate `self._config.oauth_providers` from `self._oauth_configs`. Set `self._config.oauth` to the first provider's config for backward compat. Set `self._config.oauth2_provider` to the first provider name.

- `../actingweb/actingweb/interface/app.py:821` — Update `get_config()` to pass `oauth_providers` to Config constructor.

- `../actingweb/actingweb/oauth2.py:54-86` — Update `GoogleOAuth2Provider` and `GitHubOAuth2Provider` constructors to accept optional `provider_config: dict | None` parameter. When provided, use it instead of `config.oauth` for `client_id`/`client_secret`. This allows factory functions to pass per-provider credentials.

- `../actingweb/actingweb/oauth2.py:876-943` — Update `create_oauth2_authenticator()`, `create_google_authenticator()`, `create_github_authenticator()` factory functions. Add logic: if `config.oauth_providers` has an entry for the requested provider, extract that provider's config and pass it to the provider class constructor.

### New Tests

- Test `with_oauth()` called twice with different providers accumulates both in config
- Test `with_oauth()` without `provider` param maintains backward compat (single provider)
- Test `config.oauth` backward compat points to first provider
- Test `create_oauth2_authenticator("google")` uses Google credentials from `oauth_providers`
- Test `create_oauth2_authenticator("github")` uses GitHub credentials from `oauth_providers`
- Test provider classes constructed with explicit `provider_config` use those credentials

### Verification

- [ ] `cd ../actingweb && poetry run pytest` passes
- [ ] `cd ../actingweb && poetry run ruff check . --fix` passes
- [ ] `cd ../actingweb && poetry run pyright` passes

### Implementation Status: Complete

**Notes:** All changes implemented as specified. Existing test `test_with_oauth_sets_config` updated
for new `_oauth_configs` dict structure. 7 new tests added and passing. Pyright 0 errors.

---

## Phase 2: State Parameter & Handler Updates

### Changes

- `../actingweb/actingweb/oauth_state.py:14-35` — Add `provider` field to `encode_state()`. Add it as a new field in the state JSON dict (in the `extra` dict or as a top-level field).

- `../actingweb/actingweb/oauth_state.py:38-72` — Update `decode_state()` to extract and return the `provider` field. Return it as part of the tuple (or extract from `extra` dict if stored there).

- `../actingweb/actingweb/handlers/oauth2_spa.py:201-291` — Update `_handle_config()`: instead of `if/elif` on `config.oauth2_provider`, iterate over `config.oauth_providers` and build a provider entry for each configured provider. Fall back to single-provider behavior when `oauth_providers` is empty.

- `../actingweb/actingweb/handlers/oauth2_spa.py:293-457` — Update `_handle_authorize()`: when creating the state for the authorization URL, include the `provider` name in the state data. The provider name already comes from the POST body — just pass it through to the state. **Important**: The SPA flow builds its own JSON state dict at lines 402-411 (does NOT use `encode_state()`), so `provider` must be added directly to this dict.

- `../actingweb/actingweb/handlers/oauth2_callback.py:85` — Update constructor: instead of `self.authenticator = create_oauth2_authenticator(config)`, defer authenticator creation until the state is parsed (in `get()`). After parsing state at line 119-124, extract `provider` from state and create the authenticator with that specific provider name.

- `../actingweb/actingweb/handlers/oauth2_callback.py:706-1001` — Update `_process_spa_oauth_and_create_session()`: extract `provider` from parsed state data. Use it when creating the authenticator for token exchange. Store the actual provider name (from state) in session data at line 968 instead of reading `config.oauth2_provider`.

- `../actingweb/actingweb/handlers/oauth2_endpoints.py:626-724` — Update `_render_authorization_form()`: instead of `if/elif` on `config.oauth2_provider`, iterate over `config.oauth_providers` to populate `oauth_providers` template variable with all configured providers.

- `../actingweb/actingweb/handlers/factory.py:47-93,150-205` — Update both `_get_json_config()` and `get()` HTML mode: replace single-provider `if/elif` with iteration over `config.oauth_providers`. Generate authorization URLs for each configured provider.

- `../actingweb/actingweb/oauth2_server/state_manager.py` — Update `create_mcp_state()`: include `provider` field in the encrypted MCP state payload. Update `extract_mcp_context()` to return the provider from decrypted state.

- `../actingweb/actingweb/oauth2_server/oauth2_server.py:44-46` — Keep both authenticator instances but create them with per-provider credentials from `config.oauth_providers`.

- `../actingweb/actingweb/oauth2_server/oauth2_server.py:289-301` — Fix hardcoded `self.google_authenticator`: read `provider` from the decrypted MCP state and dispatch to the correct authenticator (`self.google_authenticator` or `self.github_authenticator`).

- `../actingweb/actingweb/oauth2_server/oauth2_server.py:195-201` — Update `handle_authorization_request()`: when creating the encrypted state for MCP flow, include the selected `provider` from the form POST data.

- `../actingweb/actingweb/interface/integrations/fastapi_integration.py:2525-2596` — Update `_create_oauth_discovery_response()` and `_create_mcp_info_response()`: these describe ActingWeb's own OAuth2 server endpoints (not the upstream provider), so they may need minimal changes. If they reference provider-specific info, update to handle multiple providers.

- `../actingweb/actingweb/interface/integrations/flask_integration.py:1628-1699` — Mirror same changes as FastAPI integration for discovery endpoints.

**Token revocation fixes (identified in codebase audit 2026-02-25):**

- `../actingweb/actingweb/handlers/oauth2_endpoints.py:842,922-942` — Rename `_handle_google_token_logout()` to `_handle_provider_token_logout()`. Instead of creating a bare `OAuth2Authenticator(self.config)` (which defaults to Google), look up the provider from the session data and create the correct authenticator. Note: GitHub doesn't support token revocation, so this is best-effort.

- `../actingweb/actingweb/handlers/oauth2_spa.py:852,902` — Update `_handle_revoke()` and `_handle_logout()`: instead of creating `OAuth2Authenticator(self.config)` (defaults to Google), extract the provider from the session/token being revoked and create the correct authenticator.

**401 redirect fix (identified in codebase audit 2026-02-25):**

- `../actingweb/actingweb/auth.py:617-619` — Update `_should_redirect_to_oauth2()`: instead of creating a single provider's authorization URL, redirect to `/login` (the factory page) where all configured providers are shown. This lets the user choose their provider.

- `../actingweb/actingweb/interface/integrations/fastapi_integration.py:253,337` — Update `create_oauth_redirect_response()` and `check_authentication_and_redirect()`: redirect to `/login` instead of generating a single provider's OAuth URL.

- `../actingweb/actingweb/interface/integrations/flask_integration.py:779,1391,1424` — Update `_handle_factory_post_with_oauth_redirect()`, `_check_authentication_and_redirect()`, and `_create_oauth_redirect_response()`: redirect to `/login` instead of a single provider.

**Legacy bearer token validation — no changes needed:**

- `../actingweb/actingweb/auth.py:302-304,487-489` — `_check_oauth2_token()` and `_check_oauth2_token_async()` create `create_oauth2_authenticator(config)` which uses the default provider. This is intentional: ActingWeb-generated session tokens (the primary path) don't need provider info, and the legacy raw OAuth bearer token fallback uses the default provider. No changes needed.

### New Tests

- Test `/oauth/config` returns both Google and GitHub when both are configured
- Test `/oauth/config` returns only Google when only Google is configured (backward compat)
- Test `/oauth/spa/authorize` with `provider: "github"` includes provider in state
- Test OAuth callback with GitHub provider in state creates GitHub authenticator
- Test OAuth callback with Google provider in state creates Google authenticator
- Test MCP authorization form renders both provider buttons
- Test MCP callback dispatches to correct authenticator based on encrypted state
- Test factory JSON response includes both providers' authorization URLs
- Test SPA state JSON dict includes `provider` field when `_handle_authorize()` is called with `provider: "github"`
- Test token revocation dispatches to correct provider (or skips gracefully for GitHub)
- Test 401 redirect goes to `/login` when multiple providers are configured

### Verification

- [ ] `cd ../actingweb && poetry run pytest` passes
- [ ] `cd ../actingweb && poetry run ruff check . --fix` passes
- [ ] `cd ../actingweb && poetry run pyright` passes

### Implementation Status: Complete

**Notes:** All code changes implemented as specified. SPA state includes provider field, OAuth callbacks
dispatch to correct authenticator based on provider in state, MCP state includes provider, factory and
discovery endpoints iterate providers, token revocation uses correct authenticator, 401 redirects to
factory login page when multiple providers configured. Pyright 0 errors, ruff clean, all tests passing.

---

## Phase 3: Security Fix — GitHub Email Verification

### Changes

- `../actingweb/actingweb/oauth2.py:584-587` — Update `_get_github_primary_email()`: when selecting the primary email, also check `email_info.get("verified", False)`. If primary email is not verified, skip it and fall through to the verified-email fallback loop at lines 590-593. This prevents an attacker from using an unverified primary email to link to an existing actor.

### New Tests

- Test `_get_github_primary_email()` with primary email that is NOT verified — should skip it and return the first verified email instead
- Test `_get_github_primary_email()` with primary email that IS verified — should return it (existing behavior)
- Test `_get_github_primary_email()` with no primary and no verified emails — should return None
- Test `_get_github_primary_email()` with only unverified emails — should return None

### Verification

- [ ] `cd ../actingweb && poetry run pytest` passes
- [ ] `cd ../actingweb && poetry run ruff check . --fix` passes
- [ ] `cd ../actingweb && poetry run pyright` passes

### Implementation Status: Complete

**Notes:** Updated `_get_github_primary_email()` to require both `primary` and `verified` flags.
Added 4 unit tests covering: verified primary (normal case), unverified primary (falls back to
first verified), all unverified (returns None), and no primary but verified (returns first verified).
Pyright 0 errors, ruff clean, all tests passing.

---

## Phase 4: Documentation Updates

Update all documentation to reflect multi-provider OAuth support and the GitHub email verification fix. This phase should be done after Phases 1-3 are implemented and passing tests.

### Changes

**Critical updates (directly impacted by new APIs):**

- `docs/guides/oauth-login-flow.md:173-198` — Replace the single-provider configuration example (`config.oauth2_provider = "google"`) with the new fluent multi-provider API:
  ```python
  app = ActingWebApp(...)
      .with_oauth(provider="google", client_id="...", client_secret="...", ...)
      .with_oauth(provider="github", client_id="...", client_secret="...", ...)
  ```

- `docs/guides/oauth-login-flow.md:359-369` — Replace the "Multiple OAuth Providers" section that currently says "only one provider can be configured at a time" and "Future enhancement" with actual multi-provider documentation showing the `with_oauth(provider=...)` API.

- `docs/guides/authentication.rst:100-132` — Update the Provider Configuration section. Currently shows separate `config.oauth = {...}` + `config.oauth2_provider = "google"` blocks for each provider. Replace with the new `with_oauth(provider="google", ...).with_oauth(provider="github", ...)` fluent API pattern.

- `docs/guides/authentication.rst:183-186` — Update factory function documentation. The `create_oauth2_authenticator(config)` section should mention that when `config.oauth_providers` is populated, the factory extracts per-provider credentials automatically.

- `docs/guides/authentication.rst:893-896` — Remove or update the `config.oauth2_provider = "google"  # or "github"` example to show the new fluent API.

- `docs/quickstart/configuration.rst:82-90` — Update the OAuth2 section. Currently shows `with_oauth(client_id="...", client_secret="...")` without a `provider` parameter. Add documentation for the `provider` parameter and show multi-provider example. Document `config.oauth_providers` as a new config attribute.

- `docs/quickstart/configuration.rst:14-21` — Update the Quick Start code example to optionally show multi-provider configuration.

**Endpoint response updates (Phase 2 changes):**

- `docs/guides/spa-authentication.rst:218-240` — Update the `/oauth/config` response example to show both Google and GitHub providers in the `oauth_providers` array when both are configured.

- `docs/guides/spa-authentication.rst:826-852` — Update the API Reference for `GET /oauth/config` to show a multi-provider response example.

**Security documentation (Phase 3 changes):**

- `docs/reference/security.rst:26-30` — Add a note about GitHub email verification: "GitHub: only verified primary emails are accepted for actor linking. Unverified primary emails are skipped to prevent account linking attacks."

- `docs/guides/authentication.rst` — In the GitHub provider section, add a note that only verified emails from the GitHub `/user/emails` API are accepted for actor creation/linking.

**Getting started / tutorial updates:**

- `docs/quickstart/getting-started.rst:55-60` — Update `with_oauth()` example to mention the optional `provider` parameter.

- `docs/quickstart/getting-started.rst:173` — Update configuration methods list: `.with_oauth(client_id, client_secret, scope, ..., provider=...)` to include the new parameter.

**Minor cross-references (backward compatible, low priority):**

- `docs/guides/web-ui.rst:319-332` — Template variables section already supports multi-provider iteration. Verify examples are accurate with the new output format.

- `docs/guides/mcp-applications.rst:87-91,777-781` — Single `with_oauth()` calls are backward compatible, no changes needed unless we want to show multi-provider examples.

### Verification

- [ ] All code examples in docs compile/are syntactically correct
- [ ] No remaining references to "only one provider can be configured at a time"
- [ ] No remaining `config.oauth2_provider = "google"  # or "github"` patterns (replaced with fluent API)
- [ ] Security docs mention GitHub email verification fix
- [ ] Backward-compatible single-provider examples still shown alongside multi-provider

### Implementation Status: Complete

**Notes:** Updated 8 documentation files: oauth-login-flow.md (configuration + multi-provider section),
authentication.rst (provider config, factory functions, migration guide, GitHub verified email note),
configuration.rst (quick start + OAuth2 section), spa-authentication.rst (config response examples + API reference),
security.rst (GitHub email verification + multi-provider redirect), getting-started.rst (with_oauth example + config methods list).
No remaining references to "only one provider can be configured at a time" or `config.oauth2_provider = "google"  # or "github"`.

---

## Implementation Summary

**Completed:** 2026-02-25
**All phases:** Complete
**Test status:** All passing (47 failures in parallel mode are known isolation issues, all pass sequentially)

### Deviations from Plan
- Phase 2 `oauth_state.py` changes were not needed — the SPA flow uses its own JSON state dict (not `encode_state()`), and MCP flow uses encrypted state via `state_manager.py`. Both were updated as specified.

### Learnings
- The `replace_all` Edit tool can have unintended side effects when renaming variables that share names with function parameters
- Parallel test failures (port conflicts, timing) should always be verified sequentially before investigating

## Post-Verification Changes (2026-02-25)

After the initial implementation was completed, the following changes were made during iteration.

### 1. SPA flow email form fallback when GitHub returns no verified emails

**Category**: Bug fix

**What changed**: When `require_email=True` and GitHub returns no verified emails, the SPA OAuth callback flow now redirects to the `/oauth/email` form instead of returning a hard `identifier_failed` error. This matches the Web UI flow behavior. The email form flow creates the actor with `email_verified = "false"` and fires the `email_verification_required` lifecycle hook so the app can send a verification email.

**Files affected**:
- `actingweb/handlers/oauth2_callback.py` — `_process_spa_oauth_and_create_session()`: added email form redirect path when `identifier` is None and `require_email` is True, including fetching verified emails for the dropdown
- `actingweb/oauth2_server/oauth2_server.py` — Improved MCP error message to explain that a verified email is required and suggest adding one to the provider account

**Rationale**: The Web UI flow already had this fallback (redirect to email form → email verification), but the SPA flow returned a hard error. Users logging in via GitHub with private/unverified emails had no recovery path in the SPA flow.

### 2. Migration notes and backward compatibility documentation

**Category**: New functionality

**What changed**: Added migration notes to `docs/migration/v3.10.rst` documenting the multi-provider OAuth support as a non-breaking, additive change. All 12 public API surface areas verified as fully backward compatible. Also added CHANGELOG entries under "Unreleased" for: multi-provider OAuth support, SPA email form fallback for GitHub, GitHub email verification security fix, and MCP verified email requirement.

**Files affected**:
- `docs/migration/v3.10.rst` — Added "Multi-Provider OAuth Support" section with: what changed, backward compatibility evidence (12 items), no-action-required note, opt-in multi-provider example, GitHub email verification security fix details, SPA email form fallback, MCP verified email requirement
- `CHANGELOG.rst` — Added 4 entries under "Unreleased": 2 ADDED (multi-provider OAuth, SPA email form fallback) and 2 FIXED (GitHub email verification, MCP verified email)

**Rationale**: User requested verification that changes are non-breaking and documentation in migration notes for the feature release.

### 3. PR review fixes — 7 issues from code review

**Category**: Bug fix / UX refinement

**What changed**: Addressed all actionable items from the PR #84 code review:

1. **Token revocation uses correct provider** (Bug fix): All three revocation paths (`_handle_provider_token_logout`, `_handle_revoke`, `_handle_logout`) now look up the provider from the `session_id` cookie via `session_manager.get_session()` before creating the authenticator. Falls back to default provider when no session is available.

2. **Rename `google_token_data` parameter** (Cleanup): Renamed `google_token_data` parameter to `provider_token_data` in `TokenManager.create_authorization_code()` and `_create_access_token()`. Updated the kwarg in `oauth2_server.py` caller. Storage keys (`google_token_key`, bucket names) left unchanged to avoid data migration.

3. **Extract `display_name` helper** (Cleanup): Added `get_provider_display_name()` function and `_PROVIDER_DISPLAY_NAMES` dict in `oauth2.py`. Replaced all 5 duplicated `prov_name.capitalize() if prov_name != "github" else "GitHub"` expressions across `factory.py`, `oauth2_endpoints.py`, and `oauth2_spa.py`.

4. **Document mixed API limitation** (Documentation): Added `.. note::` to `with_oauth()` docstring warning that mixing nameless calls with named provider calls silently drops the nameless provider.

5. **Make `get_github_verified_emails()` public** (Cleanup): Renamed from `_get_github_verified_emails()` on `OAuth2Authenticator`. Updated both call sites in `oauth2_callback.py`.

6. **Non-idiomatic mock pattern** (No action): The `type("Response", ...)` pattern was not found anywhere in the test suite. False positive in the review.

7. **RFC 8414 discovery limitation** (Documentation): Added `.. note::` to `_create_oauth_discovery_response()` in both Flask and FastAPI integrations documenting that discovery only reflects the default provider and that non-default providers should use `/oauth/authorize` directly.

**Files affected**:
- `actingweb/oauth2.py` — Added `get_provider_display_name()`, renamed `_get_github_verified_emails` → `get_github_verified_emails`
- `actingweb/handlers/oauth2_endpoints.py` — Provider lookup in revocation, display_name helper
- `actingweb/handlers/oauth2_spa.py` — Provider lookup in revocation/logout (2 locations), display_name helper
- `actingweb/handlers/oauth2_callback.py` — Updated 2 call sites for renamed method
- `actingweb/handlers/factory.py` — display_name helper (2 locations)
- `actingweb/oauth2_server/token_manager.py` — Renamed `google_token_data` → `provider_token_data` parameter
- `actingweb/oauth2_server/oauth2_server.py` — Updated kwarg name
- `actingweb/interface/app.py` — `with_oauth()` docstring note
- `actingweb/interface/integrations/flask_integration.py` — Discovery docstring note
- `actingweb/interface/integrations/fastapi_integration.py` — Discovery docstring note

**Rationale**: Code review on PR #84 identified correctness gaps (token revocation), naming inconsistencies from the provider-agnostic refactor, code duplication, and missing documentation.

### 4. Loosen dependency constraints and update dev dependencies

**Category**: Changed

**What changed**: Loosened runtime dependency version ranges to reduce conflicts for downstream consumers. Updated dev dependencies and removed redundant `black` formatter.

**Runtime deps loosened**: `boto3 >=1.26`, `requests >=2.20`, `cryptography >=43.0`, `oauthlib >=3.2`, `typing-extensions >=4.0`, `flask >=3.0`, `werkzeug >=3.0`, `fastapi >=0.100`, `uvicorn >=0.20`, `jinja2 >=3.0`.

**Dev deps updated**: `ruff` 0.14→0.15, `responses` 0.25→0.26, `pytest-rerunfailures` 13→16. Removed `black` (redundant with `ruff format`).

**Files affected**:
- `pyproject.toml` — Updated version constraints
- `poetry.lock` — Re-resolved

**Rationale**: Library dependencies should be as permissive as possible to avoid version conflicts for downstream consumers. Dev dependencies don't affect consumers so can be updated freely.

### 5. Native SPA email verification flow

**Category**: UX refinement / New functionality

**What changed**: The SPA email verification flow no longer redirects to a server-rendered HTML form, which was a jarring UX break for SPA users. Instead, the flow now redirects back to the SPA with query parameters, and the SPA handles email collection and verification natively through the JSON API.

**Changes:**

1. **SPA callback redirects back to SPA**: When GitHub returns no verified email, the SPA OAuth callback now redirects to `{spa_redirect_url}?email_required=true&session={session_id}` instead of to `/oauth/email?session={id}`. This matches the existing SPA redirect patterns (success: `?session=...`, error: `?error=...`).

2. **POST `/oauth/email` does NOT return verification token**: The verification token is never exposed in API responses. Instead, both SPA and HTML template flows rely on the `email_verification_required` lifecycle hook — the app backend hook handler sends the verification email in both cases. The JSON response includes `email_requires_verification: true` so the SPA knows to inform the user.

3. **GET `/oauth/email?verify=<token>` verification endpoint**: Added email verification handling directly on the `/oauth/email` endpoint. A reverse token→actor_id index (stored in `_email_verify_tokens` attribute bucket with TTL) enables clean verification URLs without the actor_id in the path.

4. **Verification URL format updated**: Changed from `/{actor_id}/www/verify_email?token=...` to `/oauth/email?verify=...` in both the `oauth_email.py` POST handler and the `email_verification.py` resend handler. The existing `/{actor_id}/www/verify_email` endpoint continues to work for backward compatibility.

5. **New constant**: Added `EMAIL_VERIFY_TOKEN_INDEX_BUCKET` to `constants.py` for the reverse token index bucket.

**Expected SPA flow:**
1. SPA starts GitHub OAuth → callback finds no verified email
2. Callback redirects: `{spa_redirect_url}?email_required=true&session={session_id}`
3. SPA shows email input form → POSTs to `POST /oauth/email` with `Accept: application/json`
4. Response includes `email_requires_verification: true`; `email_verification_required` lifecycle hook fires
5. App backend hook handler sends verification email with link: `https://<root>/oauth/email?verify=<token>`
6. User clicks link → `GET /oauth/email?verify=<token>` validates and marks email verified

**Expected HTML template flow:**
1. Browser starts GitHub OAuth → callback finds no verified email
2. Callback redirects: `/oauth/email?session={session_id}` (server-rendered form)
3. User submits email → POST `/oauth/email` (form POST)
4. `email_verification_required` lifecycle hook fires — app backend sends verification email
5. Browser redirect to `/{actor_id}/www`
6. User clicks email link → `GET /oauth/email?verify=<token>` validates and marks email verified

Both flows rely on the same `email_verification_required` hook for sending the verification email — the token is never exposed in API or HTML responses.

**Files affected**:
- `actingweb/constants.py` — Added `EMAIL_VERIFY_TOKEN_INDEX_BUCKET`
- `actingweb/handlers/oauth2_callback.py` — SPA email redirect now goes back to SPA with `email_required=true&session=...` params
- `actingweb/handlers/oauth_email.py` — GET handles `?verify=<token>`, POST returns verification token in JSON, stores token index
- `actingweb/handlers/email_verification.py` — Updated resend handler to use new verification URL format and token index

**Rationale**: SPA users were redirected to a server-rendered HTML form when GitHub returned no verified email, breaking the SPA experience. The library should support the SPA handling email collection and verification natively through the JSON API, with the app composing and sending the verification email itself.

### 6. Fix spurious token revocation warnings and add proper provider token revocation on logout

**Category**: Bug fix + Security improvement

**What changed**: Logout was producing confusing `Token revocation failed with status 400: invalid_token` warnings and calling the logout handler twice (FastAPI only). Fixed both issues, then added proper provider token revocation as a security measure.

**Root cause (two issues)**:

1. **Wrong token sent to provider**: All three revocation paths were sending the ActingWeb-generated session token to the OAuth provider's (e.g. Google) revocation endpoint. The provider doesn't recognize ActingWeb tokens — it only knows about its own tokens. This always fails with `invalid_token`.

2. **Double logout call**: The FastAPI integration called `_handle_oauth2_endpoint(request, "logout")` twice — once for "MCP token revocation" and again at the end of the handler.

**Fix (two parts)**:

1. **Proper token lookup chain**: Instead of sending the ActingWeb session token to the provider, the handlers now:
   - Validate the session token via `session_manager.validate_access_token(token)` → get `actor_id`
   - Load the `Actor` and read `actor.store.oauth_token` (the actual provider-issued token)
   - Send that token to the provider's revocation endpoint (if the provider supports it)
   - Clear `actor.store.oauth_token` and `oauth_token_expiry` on success
   - Skip silently for GitHub (no revocation URI)

2. **Restructured FastAPI logout handler**: Made the cookie path and Bearer token path mutually exclusive, eliminating the double call.

**Files affected**:
- `actingweb/handlers/oauth2_endpoints.py` — `_handle_provider_token_logout()`: rewrote to look up actor and revoke provider token; new `_revoke_provider_token_for_actor()` helper
- `actingweb/handlers/oauth2_spa.py` — `_handle_revoke()` and `_handle_logout()`: updated to call `_revoke_provider_token_for_actor()`; new `_revoke_provider_token_for_actor()` helper (same logic)
- `actingweb/interface/integrations/fastapi_integration.py` — Restructured `/oauth/logout` handler to avoid double call

**Rationale**: The warnings were confusing because the wrong token was being sent. The user also requested that provider tokens be revoked on logout as a security measure to prevent the backend from making API calls on behalf of the user after logout. GitHub does not support revocation (no `revocation_uri`) so only Google tokens are revoked. Flask integration was not affected by the double-call bug and does not require changes.

---

## Evaluation Notes

### Architecture
- The `with_oauth()` fluent builder pattern is preserved by adding a `provider` param; calling without it maintains backward compat.
- 6 handler locations with `if/elif` branching on `config.oauth2_provider` all need updating to iterate `config.oauth_providers`. These are in: `factory.py` (x2), `oauth2_spa.py`, `oauth2_endpoints.py`, `fastapi_integration.py`, `flask_integration.py`.
- Frontend templates (`aw-oauth-authorization-form.html`) already loop over `oauth_providers` — no template changes needed.
- The Flask integration (`flask_integration.py`) needs parallel changes to FastAPI for discovery endpoints.
- **[2026-02-25 Audit]**: 17 single-provider locations identified across 12 files (~30 call sites following `create_oauth2_authenticator(config)` or `if/elif` on `config.oauth2_provider`). All are now accounted for in the plan. The SPA flow has its own state format (not using `encode_state()`) — provider must be added to the SPA JSON state dict directly.

### Security
- **GitHub email verification gap**: `_get_github_primary_email()` selects primary email without checking `verified` field. Phase 3 addresses this. An attacker could register a GitHub account with a victim's email (unverified) and potentially link to the victim's actor.
- **CSRF in non-MCP flows**: Existing issue (CSRF token generated but discarded at `oauth2_callback.py:122`). Not introduced by this change, not addressed in this plan.
- **State not signed in non-MCP flows**: Existing design. Provider field in state could be tampered, but this would cause a cross-provider code exchange to fail (Google code at GitHub endpoint), so tampering is self-defeating.
- **Credential isolation**: Per-provider `oauth_providers` dict ensures each provider class gets its own credentials. Factory functions look up by provider name.
- **[2026-02-25 Audit]**: Legacy bearer token validation (raw OAuth tokens, not ActingWeb session tokens) uses the default provider. This is acceptable because: (1) ActingWeb-generated session tokens are the primary validation path and are provider-agnostic, (2) each user typically uses one provider, (3) adding multi-provider token probing adds complexity and latency for a legacy fallback path.

### Scalability
- No new database queries. Provider config is loaded once at startup and held in memory.
- The `/oauth/config` endpoint iterates a small dict (2 entries) — negligible overhead.
- GitHub API calls during sign-in (userinfo + emails) remain the same as single-provider mode.

### Usability
- `with_oauth(provider="google", ...)` is intuitive and consistent with existing builder pattern.
- Backward compat: calling `with_oauth()` without `provider` param works identically to today.
- Error messages should clearly indicate which provider failed if token exchange fails.
