# Implementation Plan: Multi-Provider OAuth Support (ActingWeb Library)

**Date:** 2026-02-24
**Status:** Ready for Implementation (Updated 2026-02-25)
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

### Implementation Status: Not Started

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

### Implementation Status: Not Started

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

### Implementation Status: Not Started

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

### Implementation Status: Not Started

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
