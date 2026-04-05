# Implementation Plan: Mobile App OAuth2 Support

**Date:** 2026-04-05
**Status:** Planned
**Branch:** TBD (library changes in actingweb, app changes in actingweb_mcp/mobile_apps)

## Context

ActingWeb's OAuth2 module supports web apps (server-side and SPA) but assumes browser redirects throughout. Native mobile apps break this assumption: the mobile app receives the authorization code directly via deep link (custom URL scheme like `io.actingweb.memory://callback`), then needs to exchange it at the backend.

Per RFC 8252 (OAuth 2.0 for Native Apps), the standard flow is:
1. App opens system browser → user authenticates → provider redirects to custom URL scheme
2. App catches the code and exchanges it at a token endpoint

ActingWeb already has `POST /oauth/spa/token` as a token endpoint, and it already dispatches on `grant_type`. The `authorization_code` grant type is stubbed out — implementing it completes the mobile flow without inventing new endpoints.

Google Sign-In on mobile uses the native SDK (ID token flow) which is app-specific and doesn't require library changes. This plan covers the **authorization code flow** used by GitHub (and any future OAuth providers on mobile).

## Problem Summary

Three issues prevent mobile OAuth from working:

1. **`_handle_authorization_code` is a stub** — `oauth2_spa.py:652` returns an error instead of exchanging the code
2. **Providers hardcode `redirect_uri`** — `GoogleOAuth2Provider` (line 71) and `GitHubOAuth2Provider` (line 92) in `oauth2.py` ignore any `redirect_uri` from provider config, always using `{proto}{fqdn}/oauth/callback`
3. **`exchange_code_for_token` doesn't accept `redirect_uri` override** — no way to pass the mobile app's redirect_uri for the token exchange

## Changes

### 1. Respect `redirect_uri` from provider config (`actingweb/oauth2.py`)

**Files:** `actingweb/oauth2.py` lines 71 and 92

Both `GoogleOAuth2Provider.__init__` and `GitHubOAuth2Provider.__init__` hardcode:
```python
"redirect_uri": f"{config.proto}{config.fqdn}/oauth/callback",
```

Change to:
```python
"redirect_uri": oauth_config.get("redirect_uri") or f"{config.proto}{config.fqdn}/oauth/callback",
```

This makes `with_oauth(provider="github-mobile", redirect_uri="io.actingweb.memory://callback")` actually work. Falls back to the server default when no override is provided, so existing behavior is unchanged.

### 2. Add `redirect_uri` parameter to `exchange_code_for_token` (`actingweb/oauth2.py`)

**Files:** `actingweb/oauth2.py` line 234

Change signature from:
```python
def exchange_code_for_token(self, code: str, state: str = "", code_verifier: str | None = None)
```
To:
```python
def exchange_code_for_token(self, code: str, state: str = "", code_verifier: str | None = None, redirect_uri: str | None = None)
```

On line 255, change:
```python
"redirect_uri": self.provider.redirect_uri,
```
To:
```python
"redirect_uri": redirect_uri or self.provider.redirect_uri,
```

This provides defense-in-depth: even if the provider's stored redirect_uri is wrong, the caller can override it explicitly. Existing callers pass no `redirect_uri` and get the current behavior.

### 3. Support `github-*` provider variants in factory (`actingweb/oauth2.py`)

**Files:** `actingweb/oauth2.py` lines 928-940

The `create_oauth2_authenticator` factory needs to handle provider names like `github-mobile` using `GitHubOAuth2Provider`. Change the `elif` from exact match to prefix match:

```python
elif provider_name == "github" or provider_name.startswith("github-"):
    return OAuth2Authenticator(config, GitHubOAuth2Provider(config, provider_config=prov_cfg))
```

Same pattern for the SPA handler's provider dispatch (`oauth2_spa.py` line 366-371).

### 4. Implement `_handle_authorization_code` (`actingweb/handlers/oauth2_spa.py`)

**Files:** `actingweb/handlers/oauth2_spa.py` lines 652-687

This is the core change. Replace the stub with a full implementation that mirrors the callback handler's logic (from `oauth2_callback.py` lines 177-549) but returns JSON directly instead of redirecting.

**Request parameters:**
```json
{
  "grant_type": "authorization_code",
  "code": "<auth_code>",
  "provider": "github-mobile",
  "redirect_uri": "io.actingweb.memory://callback",
  "code_verifier": "<optional PKCE verifier>",
  "token_delivery": "json"
}
```

**Implementation steps:**
1. Extract `code`, `provider`, `redirect_uri`, `code_verifier` from params
2. Create authenticator via `create_oauth2_authenticator(config, provider)`
3. Validate authenticator is enabled
4. Exchange code: `authenticator.exchange_code_for_token(code, code_verifier=code_verifier, redirect_uri=redirect_uri)`
5. Validate token: `authenticator.validate_token_and_get_user_info(access_token)`
6. Extract identifier: `authenticator.get_email_from_user_info(user_info, access_token, require_email)`
7. Lookup/create actor: `authenticator.lookup_or_create_actor_by_identifier(identifier, user_info)`
8. Store OAuth tokens in actor properties
9. Execute lifecycle hooks (`actor_created`, `oauth_success`)
10. Generate ActingWeb SPA tokens (access + refresh)
11. Return JSON response based on `token_delivery` mode

**Response:**
```json
{
  "success": true,
  "actor_id": "<actor_id>",
  "email": "<identifier>",
  "access_token": "<spa_access_token>",
  "refresh_token": "<spa_refresh_token>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "expires_at": 1712345678
}
```

**Error handling:**
- Missing code → 400
- Unknown provider → 400
- Provider not enabled → 400
- Code exchange failed → 401
- Token validation failed → 401
- Actor creation failed → 500

### 5. App changes (actingweb_mcp — separate commits)

**`application.py`** — Register `github-mobile` provider (already done):
```python
app.with_oauth(
    provider="github-mobile",
    client_id=gh_mobile_client_id,
    client_secret=gh_mobile_client_secret,
    redirect_uri="io.actingweb.memory://callback",
    ...
)
```

**`frontend/src/auth/MobileAuthProvider.ts`** — Add `redirect_uri` to token exchange request:
```typescript
body: JSON.stringify({
  grant_type: 'authorization_code',
  code,
  provider: 'github-mobile',
  redirect_uri: 'io.actingweb.memory://callback',
  token_delivery: 'json',
})
```

## What Does NOT Change

- Google native sign-in flow (`POST /api/auth/google-mobile`) — app-specific, not a library concern
- Existing SPA web OAuth flow — the callback handler path is untouched
- Token refresh flow (`grant_type=refresh_token`) — already works
- Existing `with_oauth()` API — only behavior change is that `redirect_uri` kwarg now takes effect

## Security Considerations

- Backend holds the `client_secret` — mobile is not a public client. This is the BFF pattern, which is more secure than having mobile exchange codes directly with the provider.
- PKCE support is included via `code_verifier` parameter but optional since we have a client_secret.
- `redirect_uri` validation happens at the OAuth provider level during code exchange.
- Tokens returned via JSON body (`token_delivery: "json"`) — mobile stores them in iOS Keychain / Android Keystore.

## Tests

### Library tests
- Unit test: `exchange_code_for_token` with explicit `redirect_uri` override
- Unit test: `GoogleOAuth2Provider` and `GitHubOAuth2Provider` respect `redirect_uri` from provider_config
- Unit test: `create_oauth2_authenticator` handles `github-mobile` provider name
- Integration test: `POST /oauth/spa/token` with `grant_type=authorization_code` — mock the provider's token endpoint and userinfo endpoint, verify actor creation and token response

### App tests
- Frontend unit test: `githubMobileLogin` sends correct provider and redirect_uri
- Backend integration test: `github-mobile` provider registered and enabled

## Verification

- [ ] Existing `poetry run pytest` passes in actingweb library (no regressions)
- [ ] Existing `poetry run pytest` passes in actingweb_mcp
- [ ] `npm --prefix frontend run test:run` passes
- [ ] `poetry run ruff check . --fix` clean in both repos
- [ ] `poetry run pyright` clean in both repos
- [ ] Manual: GitHub OAuth works on iOS simulator via mobile flow
- [ ] Manual: Web OAuth flows unchanged (Google + GitHub)
