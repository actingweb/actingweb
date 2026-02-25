# Research: Add GitHub as Authentication Provider Alongside Google

**Date:** 2026-02-24
**Status:** Complete
**Branch:** support-github-as-auth-provider-alongside-google-auth
**Commit:** 3bd4c55

## Research Question

How to add GitHub as an authentication provider so users can sign in with their GitHub account in addition to the existing Google authentication, with both providers supported simultaneously.

## Summary

The system already has **partial GitHub support**: the ActingWeb library (`../actingweb`) implements both `GoogleOAuth2Provider` and `GitHubOAuth2Provider` classes, the frontend `LoginPage` renders provider buttons dynamically (including a `GitHubIcon`), and the `oauth_success` lifecycle hook handles GitHub's user_info format. However, the current architecture is **single-provider-at-a-time** — configured via a single `OAUTH_PROVIDER` env var that selects either Google OR GitHub with one set of credentials.

To support both simultaneously, changes are needed in three layers: (1) the ActingWeb library must accept multiple provider configurations with separate credentials, (2) the application must configure both providers at startup, and (3) the `/oauth/config` endpoint must return both providers so the frontend displays both buttons. The frontend itself is already designed for multi-provider rendering and needs minimal changes.

The key architectural decision is whether to extend the ActingWeb library's `with_oauth()` to support multiple providers (clean but more work) or to configure multiple providers at the application level by passing provider-specific config to the library's existing per-request authenticator factory (pragmatic, less library change).

## Detailed Findings

### Current Architecture: Single-Provider Design

The system selects ONE OAuth provider at startup:

- `application.py:362` — `OAUTH_PROVIDER` env var (defaults to `"google"`)
- `application.py:365-380` — Single `app.with_oauth()` call with provider-conditional scope/URIs
- `application.py:384-386` — `config.oauth2_provider` set to a single string
- `config.py:149` — `self.oauth2_provider = "google"` (single string attribute)
- `config.py:136-148` — Single `self.oauth` dict storing one set of credentials

The `create_oauth2_authenticator()` factory at `oauth2.py:876-900` reads this single string to create one provider:

```python
def create_oauth2_authenticator(config, provider_name=""):
    if not provider_name:
        provider_name = getattr(config, "oauth2_provider", "google")
    if provider_name == "google":
        return OAuth2Authenticator(config, GoogleOAuth2Provider(config))
    elif provider_name == "github":
        return OAuth2Authenticator(config, GitHubOAuth2Provider(config))
```

### Existing Multi-Provider Infrastructure (Partial)

Several components already support multi-provider scenarios:

**Frontend (`LoginPage.tsx:122-137`)** — Renders provider buttons from an array:
```tsx
{providers.map((provider) => (
  <button key={provider.name} onClick={() => handleLogin(provider.name)}>
    {provider.name === 'google' && <GoogleIcon />}
    {provider.name === 'github' && <GitHubIcon />}
    <span>Continue with {provider.display_name}</span>
  </button>
))}
```

**AuthContext (`AuthContext.tsx:252-298`)** — `login()` accepts a `provider` parameter and passes it to `/oauth/spa/authorize`.

**SPA Authorize handler (`oauth2_spa.py:359-375`)** — Creates provider-specific authenticator based on `provider` param from the POST body, using `create_google_authenticator()` or `create_github_authenticator()`.

**SPA Config handler (`oauth2_spa.py:231-259`)** — Returns `oauth_providers` array, but currently only includes ONE provider based on `config.oauth2_provider`.

**MCP OAuth authorization form (`aw-oauth-authorization-form.html:546-573`)** — Iterates over `oauth_providers` array to render provider buttons.

**Lifecycle hook (`lifecycle_hooks.py:170-213`)** — Already handles both providers' user_info formats:
- Tries `name` (both providers)
- Falls back to `given_name` + `family_name` (Google)
- Falls back to `login` (GitHub username)

**Provider classes (`oauth2.py:54-86`)** — Both `GoogleOAuth2Provider` and `GitHubOAuth2Provider` exist with hardcoded endpoints. Both currently read `client_id`/`client_secret` from the same `config.oauth` dict.

### OAuth Callback Flow

The callback at `/oauth/callback` (`fastapi_integration.py:610-655`) handles both SPA and MCP flows:

1. Checks for encrypted MCP state → MCP OAuth2 endpoints handler
2. Otherwise → `OAuth2CallbackHandler` which reads `config.oauth2_provider` to create an authenticator

For the SPA flow, `OAuth2CallbackHandler._process_spa_oauth_and_create_session()` (`oauth2_callback.py:706-1001`):
1. Exchanges code for token at provider's token endpoint
2. Fetches user info from provider's userinfo endpoint
3. Extracts email (with GitHub `/user/emails` fallback)
4. Looks up or creates actor by email (since `with_email_as_creator(enable=True)`)
5. Executes `oauth_success` lifecycle hook
6. Creates SPA session tokens

### Provider-Specific Differences

| Aspect | Google | GitHub |
|--------|--------|--------|
| Auth URI | `accounts.google.com/o/oauth2/v2/auth` | `github.com/login/oauth/authorize` |
| Token URI | `oauth2.googleapis.com/token` | `github.com/login/oauth/access_token` |
| Userinfo URI | `googleapis.com/oauth2/v2/userinfo` | `api.github.com/user` |
| Scope for sign-in | `openid email profile` | `user:email` (or `read:user user:email`) |
| Token format | JWT id_token + opaque access_token | Opaque only (`gho_` prefix) |
| Token expiry | ~1 hour, refresh tokens available | Does not expire until revoked |
| Email availability | Always in id_token with `email` scope | Often `null` in `/user`; needs `/user/emails` fallback |
| Display name | `name` or `given_name`+`family_name` | `name` (often null) or `login` |
| Stable user ID | `sub` claim (string) | `id` field (integer) |
| Provider ID format | `google:{sub}` | `github:{user_id}` |

### Actor/Account Model

With `with_email_as_creator(enable=True)` and `with_unique_creator(enable=True)` (`application.py:331-332`), the system uses email as the unique actor identifier. This means:

- A user signing in with Google (email: `user@example.com`) creates an actor with `creator=user@example.com`
- If the same user later signs in with GitHub using the same verified email, `Actor.get_from_creator("user@example.com")` will find the **existing** actor
- This provides natural account linking by email — no separate linking table needed
- The `oauth_provider` property on the actor tracks which provider was used most recently

### Environment & Deployment Configuration

- `serverless.yml:65-66` — Passes `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` to Lambda; does NOT set `OAUTH_PROVIDER`
- `.devcontainer/start-app.sh:77-82` — Defaults `OAUTH_PROVIDER` to `"google"`
- `.github/workflows/deploy.yml` — Lists `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` as required secrets
- `docs/DEVELOPMENT.md:269-270` — Documents `OAUTH_PROVIDER` as `"google"` or `"github"`

### Frontend Test Mocks

`frontend/src/test/mocks/handlers.ts:160-192` — Mocks only Google provider in the OAuth config response. Will need updating to include GitHub.

## Decisions Needed

### Decision 1: Where to Store Multi-Provider Credentials

Currently `config.oauth` is a single dict with one `client_id`/`client_secret`. With two providers, each needs separate credentials.

**Options:**

1. **Add a `config.oauth_providers` dict-of-dicts** — Store per-provider config:
   ```python
   config.oauth_providers = {
       "google": {"client_id": "...", "client_secret": "...", "scope": "openid email profile"},
       "github": {"client_id": "...", "client_secret": "...", "scope": "user:email"},
   }
   ```
   - *Pros*: Clean separation, extensible to more providers, library-level support
   - *Cons*: Requires ActingWeb library changes to `Config`, `with_oauth()`, and all code reading `config.oauth`

2. **Add a second `with_oauth()` call or a `with_oauth_provider()` method** — Keep existing `with_oauth()` for primary provider, add method for additional providers:
   ```python
   app.with_oauth(client_id=google_id, client_secret=google_secret, ...)
   app.with_additional_oauth_provider("github", client_id=github_id, client_secret=github_secret, scope="user:email")
   ```
   - *Pros*: Backward compatible, primary provider still works unchanged
   - *Cons*: Asymmetric API design, still needs library changes

3. **Provider classes carry their own credentials** — Pass credentials directly to provider constructors instead of reading from `config.oauth`:
   ```python
   GoogleOAuth2Provider(client_id=google_id, client_secret=google_secret)
   GitHubOAuth2Provider(client_id=github_id, client_secret=github_secret)
   ```
   - *Pros*: Clean separation, provider classes are self-contained, minimal config.py change
   - *Cons*: Changes how provider classes are constructed; factory functions need credential params

**Recommendation:** Option 1 (dict-of-dicts) provides the cleanest long-term architecture. The provider classes already hardcode their endpoints; they just need per-provider credentials.

### Decision 2: How to Route Callbacks to the Correct Provider

When GitHub/Google redirects back to `/oauth/callback`, the handler needs to know which provider initiated the flow to create the correct authenticator.

**Options:**

1. **Encode provider in the `state` parameter** — The `state` JSON already contains multiple fields. Add `"provider": "github"` to it. The callback handler reads `state.provider` to select the authenticator.
   - *Pros*: Single callback URL, no route changes, already partially done in SPA flow (state contains provider context)
   - *Cons*: State is already complex; must ensure provider field survives encoding/decoding

2. **Use separate callback URLs** — `/oauth/callback/google` and `/oauth/callback/github`
   - *Pros*: Simple routing, no state parsing needed
   - *Cons*: More routes to register, changes redirect_uri config, may break existing MCP clients

**Recommendation:** Option 1 — encoding provider in state. The SPA authorize handler at `oauth2_spa.py:293-457` already passes the provider name when creating authenticators. The callback handler just needs to read it from state rather than from `config.oauth2_provider`.

### Decision 3: Account Linking Strategy

When a user signs in with GitHub using an email that matches an existing Google-authenticated actor.

**Options:**

1. **Automatic email-based linking (current behavior)** — Since `with_email_as_creator(enable=True)`, `Actor.get_from_creator(email)` will find the existing actor regardless of provider. The `oauth_provider` property updates to the most recent provider.
   - *Pros*: Already works, zero additional code, seamless UX
   - *Cons*: Relies on email match; requires both providers return a verified email; `oauth_provider` property doesn't track history

2. **Explicit linking with confirmation** — If email matches existing account, prompt user to confirm linking before proceeding.
   - *Pros*: User is aware of the link, prevents accidental linking
   - *Cons*: Additional UI and flow complexity, may confuse users

3. **No linking — separate accounts per provider** — Use provider-specific identifiers (`google:{sub}`, `github:{id}`) as creators instead of email.
   - *Pros*: Clean separation, no ambiguity
   - *Cons*: Breaks `with_email_as_creator`, users with same email get duplicate accounts, fundamentally changes actor model

**Recommendation:** Option 1 — automatic email-based linking. The existing actor model with `email_as_creator` provides natural linking. Both Google and GitHub return verified emails (GitHub via `/user/emails` fallback). The `oauth_provider` property could be extended to track all linked providers.

### Decision 4: Environment Variable Naming for Dual Credentials

**Options:**

1. **Provider-prefixed variables:**
   ```
   GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
   GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET
   ```
   - *Pros*: Clear, explicit, self-documenting
   - *Cons*: More env vars, breaking change from current `OAUTH_CLIENT_ID`

2. **Keep `OAUTH_CLIENT_ID` for Google (backward compat), add GitHub-specific:**
   ```
   OAUTH_CLIENT_ID (Google, backward compatible)
   OAUTH_CLIENT_SECRET (Google, backward compatible)
   GITHUB_OAUTH_CLIENT_ID
   GITHUB_OAUTH_CLIENT_SECRET
   ```
   - *Pros*: Backward compatible, existing deployments continue working
   - *Cons*: Asymmetric naming, confusing

3. **JSON config in single env var:**
   ```
   OAUTH_PROVIDERS='{"google": {"client_id": "...", "client_secret": "..."}, "github": {...}}'
   ```
   - *Pros*: Single env var, extensible
   - *Cons*: Hard to manage in CI/CD, breaks existing config

**Recommendation:** Option 1 with backward compatibility. Support the new `GOOGLE_OAUTH_CLIENT_ID` names, fall back to `OAUTH_CLIENT_ID` for backward compat, and add `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET`.

### Decision 5: Which GitHub OAuth Scopes to Use

**Options:**

1. **`user:email` only** — Minimal scope, gets email access. Public profile info (login, name, avatar) is available without any scope.
   - *Pros*: Least privilege, users see minimal permission request
   - *Cons*: May not get full profile if GitHub changes public access rules

2. **`read:user user:email`** — Explicit read access to user profile plus email.
   - *Pros*: Explicit about what's needed, slightly more future-proof
   - *Cons*: Users see two permissions in GitHub's consent screen

**Recommendation:** Option 1 (`user:email`) — the application currently uses this scope (`application.py:368`) and it's sufficient for sign-in. Public profile data (name, login) is available without extra scopes.

### Decision 6: Scope of ActingWeb Library Changes

**Options:**

1. **Minimal library changes** — Keep `config.oauth` as-is for the "default" provider. Add a `config.oauth_providers` dict for additional providers. Update `create_oauth2_authenticator()` to accept an explicit provider name and look up credentials from `config.oauth_providers`. Update `/oauth/config` handler to return all configured providers.
   - *Pros*: Backward compatible, minimal risk, focused changes
   - *Cons*: Two config mechanisms (legacy + new)

2. **Full library refactor** — Replace `config.oauth` entirely with `config.oauth_providers`. Update `with_oauth()` to be called per-provider. Update all consumers.
   - *Pros*: Clean design, single mechanism
   - *Cons*: More changes, higher risk, all consumers must update

**Recommendation:** Option 1 — minimal library changes. Add `config.oauth_providers` alongside existing `config.oauth` for backward compatibility. The factory functions already accept a `provider_name` parameter; they just need to look up per-provider credentials.

## Code References

### Application Layer (this repo)
- `application.py:355-394` — Current single-provider OAuth configuration
- `application.py:331-332` — `with_unique_creator` and `with_email_as_creator` settings
- `hooks/actingweb/lifecycle_hooks.py:170-213` — `oauth_success` hook (handles both providers)
- `routes/spa.py:54-63` — Login and callback SPA shell routes
- `frontend/src/pages/LoginPage.tsx:122-137` — Multi-provider button rendering
- `frontend/src/pages/LoginPage.tsx:16-45` — Google and GitHub icon SVGs
- `frontend/src/context/AuthContext.tsx:145-160` — OAuth config fetching
- `frontend/src/context/AuthContext.tsx:252-298` — `login()` with provider param
- `frontend/src/context/AuthContext.tsx:301-398` — `handleCallback()`
- `frontend/src/auth/TokenManager.ts:333-343` — Token storage
- `frontend/src/test/mocks/handlers.ts:160-192` — Test mock (Google-only, needs update)
- `serverless.yml:65-66` — Lambda env var config
- `templates/aw-oauth-authorization-form.html:546-573` — MCP auth form with provider iteration

### ActingWeb Library (`../actingweb`)
- `actingweb/config.py:136-149` — OAuth config storage + `oauth2_provider` attribute
- `actingweb/interface/app.py:193-218` — `with_oauth()` builder method
- `actingweb/oauth2.py:54-86` — `GoogleOAuth2Provider` and `GitHubOAuth2Provider` classes
- `actingweb/oauth2.py:876-900` — `create_oauth2_authenticator()` factory
- `actingweb/oauth2.py:479-554` — `get_email_from_user_info()` with GitHub email fallback
- `actingweb/oauth2.py:556-599` — `_get_github_primary_email()` via `/user/emails`
- `actingweb/oauth2.py:667-744` — `lookup_or_create_actor_by_identifier()`
- `actingweb/handlers/oauth2_spa.py:201-291` — `/oauth/config` endpoint (returns provider list)
- `actingweb/handlers/oauth2_spa.py:293-457` — `/oauth/spa/authorize` (creates provider-specific authenticator)
- `actingweb/handlers/oauth2_callback.py:87-660` — OAuth callback handler
- `actingweb/interface/integrations/fastapi_integration.py:610-655` — Callback route registration

## External References

- [GitHub Docs: Authorizing OAuth Apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) — Complete OAuth flow reference
- [GitHub Docs: Scopes for OAuth Apps](https://docs.github.com/en/developers/apps/building-oauth-apps/scopes-for-oauth-apps) — Scope reference
- [GitHub Docs: REST API for Users](https://docs.github.com/en/rest/users/users) — `/user` endpoint (note: `email` field is often `null`)
- [GitHub Docs: REST API for Emails](https://docs.github.com/en/rest/users/emails) — `/user/emails` endpoint for getting primary verified email
- [GitHub Docs: GitHub Apps vs OAuth Apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps) — OAuth App is sufficient for sign-in
- [GitHub Blog: Token Formats](https://github.blog/engineering/platform-security/behind-githubs-new-authentication-token-formats/) — `gho_` prefix for OAuth tokens
