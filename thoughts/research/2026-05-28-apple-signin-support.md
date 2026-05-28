# Research: Adding Sign in with Apple as a Third OAuth Provider

**Date:** 2026-05-28
**Status:** Complete
**Branch:** master
**Commit:** af9eed9

## Research Question

We are planning to release a web app built on ActingWeb together with Capacitor-based iOS and Android mobile apps. Apple's App Store rules require Sign in with Apple to be offered when Google login is offered. The 3.10.2 work has already added Google + GitHub login support, including the mobile/Capacitor flow. What does ActingWeb need to fully support Sign in with Apple as a third provider alongside Google and GitHub?

## Summary

ActingWeb's multi-provider OAuth2 architecture (added during the 3.10.2 work) is **a good foundation** for Apple Sign-In: per-provider credentials live in `config.oauth_providers`, `create_oauth2_authenticator(config, provider_name)` branches by provider name with prefix matching (e.g. `google-mobile`), `redirect_uri` can be overridden per provider for Capacitor deep links, and the cleartext-JSON `state` already carries the provider name through to the callback. The SPA token endpoint at `/oauth/spa/token` already supports an `authorization_code` grant for mobile apps with PKCE.

However, Apple Sign-In is **fundamentally different from Google/GitHub in five ways** that the existing architecture cannot accommodate without targeted changes:

1. **No userinfo endpoint.** All identity data lives in the OIDC `id_token` (a JWT). The existing `OAuth2Authenticator.validate_token_and_get_user_info()` always does an HTTP `GET` to `provider.userinfo_uri` — there is nothing for Apple to expose there. Apple's `access_token` has no documented purpose.
2. **JWT `client_secret`.** Apple requires a freshly generated ES256-signed JWT (Team ID / Key ID / `.p8` private key) as the client_secret with a maximum lifetime of 6 months. The existing `Provider.client_secret` is a static string passed verbatim in form bodies.
3. **No PKCE end-to-end to Apple.** Apple does not accept `code_verifier`. The mobile app cannot do PKCE directly against Apple. ActingWeb's mobile flow today exchanges the code **directly with Google/GitHub** (`oauth2_spa.py:_handle_authorization_code()` → `authenticator.exchange_code_for_token`). For Apple, the mobile app must do PKCE against ActingWeb, and ActingWeb (holding the `.p8`) must do the JWT-client-secret token exchange with Apple.
4. **`response_mode=form_post` required when scope includes `name`/`email`.** Apple will `POST` the authorization response to `redirect_uri`. The current `/oauth/callback` is `GET`-only.
5. **Dual `aud` claim.** Native iOS Capacitor uses the iOS Bundle ID as `client_id` (so `id_token.aud` = Bundle ID); web SPA and Android Capacitor use the Services ID (so `id_token.aud` = Services ID). The same user gets the same `sub` claim across both — but only if the Services ID is "associated" with the App ID in the Apple Developer Portal. Validation must accept both audiences.

A sixth practical concern: **name/email are returned only on the very first sign-in.** Subsequent sign-ins yield only `sub`. ActingWeb must persist these on first contact.

App Store Guideline 4.8 was relaxed in January 2024 (no longer literally requires "Sign in with Apple" — it now requires "an equivalent privacy-preserving login service"), but the three privacy criteria Apple wrote (name+email only, hide-email option, no advertising tracking without consent) are crafted such that Sign in with Apple remains the only widely-available service that qualifies. Practically, shipping our Capacitor app on the App Store with Google login requires Sign in with Apple.

## Detailed Findings

### Current Multi-Provider Architecture (ActingWeb 3.10.2)

**Configuration layer.** `app.with_oauth(provider="google", client_id=..., client_secret=...)` can be called multiple times with different `provider` names. Each call stores into `ActingWebApp._oauth_configs[provider]` (`interface/app.py:60`, `interface/app.py:210-261`). When `Config` is materialized, `_apply_runtime_changes_to_config()` (`interface/app.py:139-208`) writes all named providers into `Config.oauth_providers: dict[str, dict[str, str]]` (`config.py:153`) and copies the first one into `Config.oauth` for backward compatibility (`interface/app.py:154-170`). `Config.oauth2_provider` (`config.py:150`) holds the default/first provider name.

**Provider class registry.** `actingweb/oauth2.py` defines a base `OAuth2Provider` (`oauth2.py:33-51`) and two subclasses, each hardcoding endpoints for one provider:
- `GoogleOAuth2Provider` (`oauth2.py:54-77`)
- `GitHubOAuth2Provider` (`oauth2.py:80-100`)

Both pull `client_id`/`client_secret` from a `provider_config` dict (which comes from `config.oauth_providers[name]`) and respect a per-provider `redirect_uri` override for mobile apps.

**Factory function.** `create_oauth2_authenticator(config, provider_name)` at `oauth2.py:918-950` looks up per-provider credentials via `_get_provider_config()` (`oauth2.py:897-906`) and branches by name. The branching tolerates suffix variants:

```python
if provider_name == "google" or provider_name.startswith("google-"):
    return OAuth2Authenticator(config, GoogleOAuth2Provider(config, provider_config=prov_cfg))
elif provider_name == "github" or provider_name.startswith("github-"):
    return OAuth2Authenticator(config, GitHubOAuth2Provider(config, provider_config=prov_cfg))
else:
    return OAuth2Authenticator(config, GoogleOAuth2Provider(config, provider_config=prov_cfg))
```

This is the prefix-match used by `google-mobile` and `github-mobile` to share the same provider class with a different `redirect_uri`.

**Provider selection at runtime.** The provider name is encoded in two distinct state formats:

- **SPA flow:** cleartext JSON `state` constructed at `oauth2_spa.py:410-437` includes `"provider": provider`. The callback (`oauth2_callback.py:128-136`) decodes the JSON via `_decode_state_with_extras()` and re-instantiates the authenticator with `create_oauth2_authenticator(self.config, state_provider)`.
- **MCP flow:** Fernet-encrypted `state` containing an `mcp_context` dict that includes `"provider"` (`oauth2_endpoints.py:643-675`, `oauth2_server/state_manager.py:118-158`). Decrypted in `ActingWebOAuth2Server.handle_oauth_callback()` (`oauth2_server/oauth2_server.py:269, 289-294`).

**Mobile / Capacitor flow.** Mobile apps register a `-mobile`-suffixed provider entry whose `redirect_uri` is a custom URL scheme (e.g. `io.actingweb.memory://callback`). After Apple/Google/GitHub redirects to that URL scheme via the device's deep-link handler, the Capacitor app POSTs the code to `/oauth/spa/token` with `grant_type=authorization_code` (`oauth2_spa.py:664-864`). The handler:

1. Validates the provider name via `_is_known_provider()` (`oauth2_spa.py:56-61`, `oauth2_spa.py:53` — `_KNOWN_PROVIDER_PREFIXES = ("google", "github")`).
2. Creates the authenticator and exchanges the code **directly with the upstream provider's token endpoint** (`oauth2_spa.py:712-714`, ultimately `oauth2.py:240-308`).
3. Fetches user info via the provider's userinfo endpoint, extracts an identifier, looks up/creates the actor, fires `oauth_success`, and issues an ActingWeb session token.

Crucially, the upstream token exchange happens on the backend, so the upstream `client_secret` never leaves the server. The backend uses the same `redirect_uri` the mobile app used (the custom URL scheme) when redeeming the code.

**PKCE.** The server supports both **server-managed** PKCE (where ActingWeb generates the verifier/challenge and stores the verifier in an OAuth session keyed by `state.pkce_session_id`, `oauth2_spa.py:423-434` + `oauth_session.py:48-109`) and **client-managed** PKCE (where the SPA/mobile passes `code_challenge` + `code_verifier`, `oauth2_spa.py:393-406`).

**Bearer token validation.** `auth.py:290-370` (`_check_oauth2_token`) is **single-provider** today: it calls `create_oauth2_authenticator(self.config)` with **no provider name** (`auth.py:302-304`), so it falls back to `config.oauth2_provider` (the default). It does not iterate providers. It does not validate JWT id_tokens. It only sends the token as `Authorization: Bearer …` to that one provider's userinfo endpoint. For applications that mint their own ActingWeb access tokens after sign-in (as the 3.10.2 SPA flow does), this is fine — the ActingWeb token is validated separately via `_check_spa_token()` (`auth.py:372-424`) — but it is a real gap for any flow that wants to validate upstream-issued tokens server-side.

**Touchpoints currently containing provider-specific branches** (verified comprehensive):

| File | Lines | Branch |
|------|-------|--------|
| `oauth2.py` | 54-77 | `GoogleOAuth2Provider` class |
| `oauth2.py` | 80-100 | `GitHubOAuth2Provider` class |
| `oauth2.py` | 193 | `login_hint` only for Google |
| `oauth2.py` | 281, 400, 463 | User-Agent header for GitHub |
| `oauth2.py` | 336 | GitHub does not support refresh tokens |
| `oauth2.py` | 528, 574-672 | GitHub `/user/emails` fallback |
| `oauth2.py` | 543-547 | Google `sub` claim → `google:{sub}` identifier |
| `oauth2.py` | 549-561 | GitHub `id`/`login` → `github:{id}` identifier |
| `oauth2.py` | 741-748 | Store `oauth_sub` / `oauth_github_id` per provider |
| `oauth2.py` | 909-910 | `_PROVIDER_DISPLAY_NAMES` map |
| `oauth2.py` | 918-950 | `create_oauth2_authenticator` branching |
| `oauth2.py` | 953-982 | `create_google_authenticator` / `create_github_authenticator` |
| `oauth2_callback.py` | 220, 855 | GitHub-specific email collection |
| `oauth2_spa.py` | 53 | `_KNOWN_PROVIDER_PREFIXES = ("google", "github")` |
| `oauth2_spa.py` | 56-61 | `_is_known_provider()` |
| `oauth2_endpoints.py` | 967-968, 989 | GitHub revocation not supported note |
| `oauth2_server/oauth2_server.py` | 45-54 | Pre-instantiates `google_authenticator` + `github_authenticator` |
| `oauth2_server/oauth2_server.py` | 196-208 | Provider branching in `handle_authorization_request()` |
| `oauth2_server/oauth2_server.py` | 289-294 | Provider branching in `handle_oauth_callback()` |
| `fastapi_integration.py` | 2581-2588 | Google-specific JWKS URI in OAuth2 discovery metadata |
| `flask_integration.py` | 1677-1684 | Same Google-specific discovery extras |

**Account linking.** `with_email_as_creator(enable=True)` plus `with_unique_creator(enable=True)` means actors are keyed by email. The system already supports the "same email used with two different providers" case: the existing actor is found regardless of which provider authenticated this time. The `oauth_provider` property on the actor stores only the most recent provider name (`oauth2.py:729`, `oauth_session.py:209`).

### Sign in with Apple: Authoritative Protocol Facts

(Sources cited at end of section.)

**OIDC endpoints** (from Apple's discovery document at `https://appleid.apple.com/.well-known/openid-configuration`):

| Purpose | URL |
|---|---|
| Issuer | `https://appleid.apple.com` |
| Authorization | `https://appleid.apple.com/auth/authorize` |
| Token | `https://appleid.apple.com/auth/token` |
| JWKS | `https://appleid.apple.com/auth/keys` |
| Revocation | `https://appleid.apple.com/auth/revoke` |
| Userinfo | **does not exist** |

Token endpoint auth method: `client_secret_post` only. `id_token` signing alg: `RS256`. Subject type: `pairwise` (different `sub` per `client_id` unless App ID + Services ID are grouped).

**Authorization parameters:**

- `client_id` — Services ID (web/Android) or App ID/Bundle ID (native iOS, but native flow doesn't actually use the authorize endpoint)
- `redirect_uri` — must be HTTPS, pre-registered, no localhost/IP
- `response_type` — `code` (most common) or `code id_token`
- `response_mode` — `query`, `fragment`, or `form_post`. **`form_post` is required** when `scope` contains `name` or `email`; Apple will not put PII in URL parameters
- `scope` — any of `openid`, `email`, `name` (space-separated)
- `state`, `nonce` — supported as usual
- **PKCE (`code_challenge` / `code_challenge_method`) is not supported by Apple's token endpoint**; you must use the JWT `client_secret` instead

**`client_secret` JWT** (Apple's REST API requires this in every token exchange):

| Component | Value |
|---|---|
| Algorithm | `ES256` |
| Header `kid` | Apple-issued Key ID for the `.p8` |
| Claim `iss` | Apple Team ID |
| Claim `iat` | now (Unix seconds) |
| Claim `exp` | now + ≤ 15777000 (≈ 6 months) |
| Claim `aud` | `https://appleid.apple.com` |
| Claim `sub` | your `client_id` (Services ID or Bundle ID) |
| Private key | downloaded `.p8` file (one-time download) |

Standard practice: regenerate on a schedule (e.g. monthly) and cache; the JWT is sent as the `client_secret` form parameter in the token request body.

Recommended Python tools: **PyJWT** (with `cryptography`) for both signing the client_secret and validating the id_token. Reference implementations: `social_core/backends/apple.py` (python-social-auth) and `django-allauth`'s Apple provider.

**`id_token` validation**:

1. Fetch JWKS at `https://appleid.apple.com/auth/keys`, cache by `kid` (rotate every ~24h, re-fetch on `kid` miss).
2. Read unverified JWT header `kid`, match it to a key in the JWKS.
3. Decode + verify with `algorithms=["RS256"]`.
4. Validate claims:
   - `iss == "https://appleid.apple.com"` (be tolerant — Apple has experimented with `https://account.apple.com`)
   - `aud` ∈ allowed audiences (your Bundle ID and/or Services ID)
   - `exp` not in the past
   - `nonce` matches the nonce you sent (Apple hashes it on iOS native — match the SHA-256 of your nonce)
5. Trust `sub` as the stable user identifier.

**User info delivery quirks**:

- `id_token` claims include `sub` (always), `email` (usually), `email_verified` (always `true` per Apple's docs but sometimes serialized as the string `"true"`), `is_private_email` (sometimes missing — also fall back to checking whether the email host is `privaterelay.appleid.com`).
- **Name is NEVER in the id_token.** In the web flow with `response_mode=form_post`, Apple includes a `user` form parameter (JSON: `{"name":{"firstName":"…","lastName":"…"},"email":"…"}`) only on the FIRST sign-in. On native iOS, the plugin returns `givenName`/`familyName` directly only on first sign-in.
- **Persist name+email on first contact.** Apple does not let you "refresh" the name later. If account creation fails, the user must revoke the app in Settings to re-trigger first-login behavior.

**Native iOS vs web/Android audiences**:

- Native iOS (Capacitor plugin → `ASAuthorizationAppleIDProvider`): `client_id` = iOS Bundle ID (e.g. `com.example.app`). `id_token.aud` = Bundle ID.
- Web SPA / Android (Capacitor `WebView`/Custom Tab): `client_id` = Services ID (e.g. `com.example.web`). `id_token.aud` = Services ID.
- The Services ID **must be associated with the Primary App ID** in the Apple Developer Portal. When associated, the same Apple ID yields the **same `sub`** across both audiences. When not associated, `sub` differs.

**Refresh tokens**:

- Apple issues `refresh_token` from `/auth/token`. No rotation: the refresh token does not change on use.
- `access_token` has no documented use (no userinfo endpoint, no other Apple resource to call) — it's "reserved for future use."
- Apple recommends validating the refresh token roughly once every 24 hours (call `/auth/token` with `grant_type=refresh_token`) to detect user-side revocation.
- App Store compliance: when a user deletes their account, your app must call `/auth/revoke` with their refresh token (Apple Technote TN3194).

**Redirect URI requirements**:

- HTTPS, no `localhost`, no IPs, no `.localhost`, pre-registered exactly in the Services ID config.
- For dev/test: use a real subdomain with a cert (Let's Encrypt or self-signed CA), or an ngrok/cloudflared tunnel with a stable HTTPS subdomain.

### Capacitor Plugin Landscape (May 2026)

| Plugin | iOS | Android | Web | Maintenance |
|---|---|---|---|---|
| `@capacitor-community/apple-sign-in` | yes | **no** | yes | Maintained; v7.x (late 2024) |
| `@capgo/capacitor-social-login` | yes | **yes** (via web OAuth) | yes | Actively maintained, v8.x |
| `capacitor-apple-login` (rlfrahm) | yes | no | no | Minimal/low-activity |
| `@capacitor-community/generic-oauth2` | yes | yes | yes | Maintained; you implement the Apple flow yourself |

**`@capacitor-community/apple-sign-in` does not support Android.** Android users get no native Sign in with Apple; the only way to offer it on Android is the web OAuth flow (Custom Tab) — either via `@capgo/capacitor-social-login`, `@capacitor-community/generic-oauth2`, or a regular browser handoff.

### App Store Review Guideline 4.8 (current text, 2026)

> Apps that use a third-party or social login service (such as Facebook Login, Google Sign-In, Sign in with Twitter, Sign In with LinkedIn, Login with Amazon, or WeChat Login) to set up or authenticate the user's primary account with the app must also offer **as an equivalent option another login service** with the following features:
> - the login service limits data collection to the user's name and email address;
> - the login service allows users to keep their email address private as part of setting up their account; and
> - the login service does not collect interactions with your app for advertising purposes without consent.

Exceptions: own-account-only apps, alternative app marketplaces, enterprise/education/business apps using existing org accounts, government/industry citizen-ID systems, clients that sign you into a specific third-party service (e.g., a Dropbox client).

Applies to iOS, iPadOS, and macOS submissions. Applies to Capacitor/webview wrapper apps just like native apps — the rule has been interpreted by reviewers based on what the user sees, not how the app is built.

### How Apple Differs From the Current Architecture: Concrete Mapping

For each Apple quirk, what in the existing code path needs adjustment:

1. **No userinfo endpoint** → `OAuth2Authenticator.validate_token_and_get_user_info()` (`oauth2.py:368-426`) cannot work as written for Apple. We must either (a) extract user info from `id_token` returned in the token response, never from a separate HTTP call, or (b) override the method in an `AppleOAuth2Provider`-aware authenticator.
2. **JWT `client_secret`** → `OAuth2Authenticator.exchange_code_for_token()` (`oauth2.py:240-308`) passes `self.provider.client_secret` as a static string (`oauth2.py:268`). For Apple, this value must be regenerated as an ES256 JWT each time (or cached + rotated). Similarly `refresh_access_token()` (`oauth2.py:310-366`) and `revoke_token()` (`oauth2.py:830-891`).
3. **No PKCE to Apple** → Mobile flow's direct token exchange in `_handle_authorization_code()` (`oauth2_spa.py:664-864`) currently sends `code_verifier` to the upstream provider. For Apple, the mobile app must **only** PKCE with ActingWeb; ActingWeb must use the JWT client_secret to redeem the code with Apple (no `code_verifier` forwarded). The mobile app can still send `code_verifier` (validated by ActingWeb against its own server-stored challenge) — it just must not be passed onward.
4. **`response_mode=form_post`** → `/oauth/callback` (`OAuth2CallbackHandler.get()`, `oauth2_callback.py:88-668`) is GET-only. Apple will POST. We need a POST handler on the same route (or a dedicated Apple callback) that reads `code`, `state`, `id_token`, and `user` from `form-urlencoded` body.
5. **Dual `aud`** → New code path. `validate_token_and_get_user_info()` for Apple must accept multiple audiences from configuration (Services ID + Bundle ID).
6. **First-sign-in name/email** → The `oauth_success` lifecycle hook receives `user_info`. For Apple's web flow, the `user` form parameter content must be merged into `user_info` before firing the hook. For Apple's native flow (identityToken from the iOS plugin), the app would POST `firstName`/`lastName` alongside the token.
7. **Bearer token validation** → `auth.py:_check_oauth2_token()` cannot validate Apple access_tokens (no userinfo endpoint). This is only a problem if applications want to validate Apple-issued tokens directly. For the SPA flow that already mints its own ActingWeb tokens after sign-in, this is moot.
8. **Native iOS bypass-the-OAuth-flow entry point** → Capacitor iOS's native flow returns an `identityToken` directly without going through `/oauth/authorize`. We need a new endpoint, e.g. `POST /oauth/spa/apple/native`, that takes `identityToken` (and optionally `authorizationCode`, `firstName`, `lastName`), validates the JWT against Apple's JWKS, identifies/creates the actor, fires the lifecycle hook, and issues an ActingWeb session token. The existing `_handle_authorization_code` handler does not match this shape.

### Required Apple Developer Portal Setup

For a single product spanning web + iOS + Android Capacitor:

- **One App ID** (e.g. `com.example.app`) with the "Sign In with Apple" capability, set as **Primary**. Used as `client_id` by the Capacitor iOS plugin.
- **One Services ID** (e.g. `com.example.web`) **associated with** the primary App ID, with all web/Android callback URLs registered under "Return URLs". Used as `client_id` by the web SPA and by the Capacitor Android web flow.
- **One Sign-in-with-Apple private key** (`.p8`) — same key signs `client_secret` JWTs for both audiences.
- **Same Team ID and Key ID** for both.

Both audiences produce the same `sub` claim for the same Apple user, since they are grouped.

## Decisions Needed

### Decision 1: Library-level architecture for the Apple-specific OAuth differences

Apple's three big departures from "generic OAuth2" (no userinfo, JWT client_secret, JWKS-based id_token validation) need a home in the library.

**Options:**

1. **Add `AppleOAuth2Provider` + extend `OAuth2Authenticator`** to optionally use OIDC-style id_token validation when the provider declares one. Add a `provider.id_token_validation = True` flag, override `validate_token_and_get_user_info()` behavior when set, and add a hook for "client_secret resolver" (callable producing the secret per request).
   - *Pros:* Keeps a single `OAuth2Authenticator` class, additive changes, no parallel inheritance tree.
   - *Cons:* The class is already large (~1100 lines) and contains GitHub-specific branches; adding Apple-specific branches piles on more conditionals.

2. **Subclass: `AppleOAuth2Authenticator(OAuth2Authenticator)`** that overrides `exchange_code_for_token`, `refresh_access_token`, `validate_token_and_get_user_info`, and adds `validate_id_token`. Factory selects the right authenticator based on provider name.
   - *Pros:* Apple's logic stays cleanly separated; existing Google/GitHub code untouched.
   - *Cons:* Two authenticator classes diverge over time; callers must know which they're getting. Some existing handler code calls methods that would behave differently across the two.

3. **Replace `OAuth2Authenticator` with a strategy-pattern composition** where the Provider object carries methods: `make_client_secret(now)`, `validate_token(token, ...)`, `get_user_info_from_token_response(token_response)`. Authenticator becomes a thin orchestrator.
   - *Pros:* Cleanest separation; future providers (Microsoft, Facebook, …) become a few methods on a new Provider class.
   - *Cons:* Larger refactor of the existing Google/GitHub flows; higher regression risk just before a release.

### Decision 2: How Apple's JWT `client_secret` is generated and cached

**Options:**

1. **Generate per request.** On every token exchange / refresh / revocation, build a fresh ES256 JWT.
   - *Pros:* Simplest correctness; no cache invalidation; trivial across processes/instances.
   - *Cons:* PyJWT signing is fast but not free (~ms). Doable but wasteful at high QPS.

2. **Generate once at startup, regenerate on a schedule** (e.g. monthly), stored in process memory.
   - *Pros:* No per-request cost.
   - *Cons:* Multi-process / Lambda cold-start behavior: each Lambda container generates its own; that's fine, but requires care.

3. **Generate per request, cached via `functools.lru_cache` keyed by 5-minute time bucket.**
   - *Pros:* Self-clearing; safe across processes (each generates independently); avoids per-request cost without explicit cache plumbing.
   - *Cons:* Tiny code complexity overhead.

4. **Persist the JWT in DynamoDB/Postgres** and refresh from one process.
   - *Pros:* Truly shared.
   - *Cons:* Overkill — the JWT is cheap to regenerate; storing it adds risk (token-in-DB) for negligible benefit.

### Decision 3: How Apple's `.p8` key is stored

**Options:**

1. **File path env var** (`APPLE_PRIVATE_KEY_PATH=/etc/secrets/AuthKey_XXX.p8`).
   - *Pros:* Standard pattern; works well with Kubernetes secrets, AWS Secrets Manager mounts, etc.
   - *Cons:* Lambda needs the file in the bundle or mounted from EFS/extension; less convenient.

2. **PEM string env var** (`APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n…"`).
   - *Pros:* Easy with secret managers that inject strings; symmetric with `OAUTH_CLIENT_SECRET`-style env conventions.
   - *Cons:* Multi-line newlines in env vars require `\n` → newline conversion, which is fragile.

3. **Both, with file-path taking precedence.**
   - *Pros:* Maximum flexibility per deployment style.
   - *Cons:* Two code paths to test.

### Decision 4: Library API for declaring Apple as a provider

Today the API is `app.with_oauth(client_id=..., client_secret=..., scope=..., auth_uri=..., token_uri=..., userinfo_uri=..., provider="github")`. Apple needs Team ID, Key ID, and private key.

**Options:**

1. **Extend `with_oauth()`** with optional Apple-specific kwargs (`apple_team_id`, `apple_key_id`, `apple_private_key`, `apple_audiences`).
   - *Pros:* One method, additive.
   - *Cons:* Cluttered signature; awkward when those kwargs are required but only for Apple.

2. **Dedicated builder method `with_apple_oauth()`** that takes Apple-specific params and internally calls `with_oauth(provider="apple", ...)` with the right defaults.
   - *Pros:* Cleanest API ergonomics; mirrors a pattern like `app.add_github()` which already exists at `interface/app.py:630-634`.
   - *Cons:* One more public method.

3. **Both: keep generic `with_oauth()` for power users; add `with_apple_oauth()` as the recommended convenience.**

### Decision 5: How the native iOS Capacitor flow reaches the backend

The Capacitor iOS plugin returns `identityToken` (a signed JWT) plus optional `authorizationCode` and (first-sign-in-only) `firstName`/`lastName`. The app must hand these to ActingWeb.

**Options:**

1. **New endpoint `POST /oauth/spa/apple/native`** that accepts `identityToken`, `firstName`, `lastName`, validates the JWT against Apple JWKS with `aud=Bundle ID`, identifies/creates the actor, and issues an ActingWeb session token.
   - *Pros:* Explicit, well-scoped; no impact on existing flows.
   - *Cons:* Apple-specific endpoint in the SPA OAuth handler (slight asymmetry).

2. **Reuse `POST /oauth/spa/token`** with a new `grant_type=apple_native_id_token` or `provider=apple-native`.
   - *Pros:* Symmetric with the existing mobile authorization-code flow; one endpoint to document.
   - *Cons:* Stretching `grant_type` beyond standard OAuth2 values; "authorization_code" vs "id_token" are semantically different.

3. **Reuse `POST /oauth/spa/token`** with `grant_type=urn:openid:params:grant-type:id_token` (custom URN) or similar.
   - *Pros:* Standards-flavored, extensible to other "native" identity providers.
   - *Cons:* No real standardization for this case; cosmetic.

### Decision 6: Android Capacitor flow — what mechanism redeems the Apple code?

Capacitor Android has no native Apple SDK. The app opens Apple's web `auth/authorize` in a Custom Tab. Apple POSTs `code`+`id_token`+`user` to a registered HTTPS `redirect_uri`. From there, the code must end up in the Capacitor app — and the JWT-`client_secret` exchange must happen server-side.

**Options:**

1. **Apple `redirect_uri` = ActingWeb's `/oauth/callback`. ActingWeb does the token exchange server-side, then deep-links back into the Capacitor app with an ActingWeb session token.**
   - *Pros:* Same server-side exchange story; `.p8` never leaves the server; works identically for web SPA and Android.
   - *Cons:* Requires the Capacitor Android app to expose a Universal Link / App Link or Custom URL scheme that ActingWeb can redirect to. Same machinery as the existing Google/GitHub Android flow.

2. **Apple `redirect_uri` = a small bridge page that JS-redirects to a custom scheme** (e.g. `https://app.example.com/apple-bridge?code=…` → `<meta http-equiv="refresh" content="0;url=io.example.app://callback?code=…">`). The Capacitor app then POSTs the code to ActingWeb just like Google/GitHub mobile.
   - *Pros:* Symmetric with existing Google/GitHub mobile flow (same `_handle_authorization_code()` handler).
   - *Cons:* The mobile-app-side exchange currently goes to `oauth2.exchange_code_for_token()` which expects a static client_secret. Apple still needs a JWT client_secret on the server — so this option still ends in ActingWeb doing the JWT-based exchange; the only thing this option adds is a one-time bridge that custom-redirects the code. Slightly more code; no real benefit.

3. **Same as option 1 but with Universal Links** — Apple posts to ActingWeb's HTTPS URL, ActingWeb processes the form_post body and redirects to an HTTPS Universal Link the Capacitor app intercepts.
   - *Pros:* Cleaner UX (no "open in app" prompt on Android), works without registering custom URL schemes.
   - *Cons:* Universal Links / App Links require domain verification (apple-app-site-association on iOS, assetlinks.json on Android) — usually already needed regardless.

### Decision 7: How to handle the form_post POST callback

Apple's `response_mode=form_post` means the callback handler must accept POST with `application/x-www-form-urlencoded` body containing `code`, `state`, `id_token`, and `user` (JSON-encoded). Current `/oauth/callback` is GET only.

**Options:**

1. **Add POST support to existing `/oauth/callback`** route, decoding form body and routing to the same `OAuth2CallbackHandler.get()` logic. Adapt to extract `user` form parameter when present.
   - *Pros:* One route URL; works for any future provider that uses form_post.
   - *Cons:* Some code duplication between GET and POST entry points; SameSite=Lax cookie issue (cross-site POSTs may drop cookies — Apple's POST is cross-site).

2. **Dedicated `/oauth/callback/apple` (POST-only)** route for Apple's form_post.
   - *Pros:* Clean separation; explicit; SameSite cookie issues can be addressed in one place.
   - *Cons:* Apple's redirect_uri configuration in the Developer Portal must point to this dedicated URL — fine for a new integration, but means we can't share Apple's redirect_uri with existing GET-based callbacks.

3. **Use `response_mode=fragment` or `query` and skip name/email scope** so Apple uses the URL like Google/GitHub.
   - *Pros:* No POST handling needed; existing GET callback works.
   - *Cons:* Loses the first-sign-in name/email entirely (since those scopes trigger the form_post requirement). User would have to type their name into the SPA after sign-in. UX cost.

### Decision 8: Where to validate Apple's id_token JWT

A new dependency on PyJWT (and its `cryptography` backend) is required for: (a) generating the ES256 `client_secret` JWT, (b) validating Apple's RS256-signed `id_token`, (c) fetching and caching Apple's JWKS.

**Options:**

1. **Make PyJWT a hard dependency** of ActingWeb when Apple is configured (or always). Add it to `pyproject.toml` core deps.
   - *Pros:* Simple; consistent; PyJWT is widely used.
   - *Cons:* Adds a dependency to consumers who don't use Apple. (Mitigated: PyJWT is already pulled transitively by many ActingWeb deployments.)

2. **Make PyJWT an extra**: `poetry install --extras apple` installs `pyjwt[crypto]`.
   - *Pros:* Optional; consistent with the existing `postgresql` extra pattern.
   - *Cons:* Users must remember the extras flag; misconfiguration produces import errors.

3. **Vendor a small JWT/JWKS module inside `actingweb`** using only `cryptography` directly.
   - *Pros:* Minimizes deps.
   - *Cons:* Re-implementing JWT verification is risk-prone; not worth it.

### Decision 9: Capacitor plugin choice (application concern, but affects backend design)

The choice of mobile plugin determines what the iOS native flow delivers to the backend.

**Options:**

1. **`@capacitor-community/apple-sign-in`** (iOS-only) + `@capacitor-community/generic-oauth2` for Android web flow.
   - *Pros:* Independent plugins; smaller surface per platform.
   - *Cons:* Two plugins to maintain; iOS plugin is community-maintained, modest activity.

2. **`@capgo/capacitor-social-login`** (covers iOS native + Android web flow + web).
   - *Pros:* One plugin for all platforms; actively maintained.
   - *Cons:* Larger plugin; commercial vendor (Capgo).

3. **Plain WebView + ActingWeb's existing SPA flow on Android, native plugin on iOS.**
   - *Pros:* Minimal mobile dependencies; reuses web code on Android.
   - *Cons:* Worse UX on Android (browser handoff vs. in-app Custom Tab); custom tab still preferred.

### Decision 10: App Store rule 4.8 — minimum compliance vs. full Apple Sign-In support

**Options:**

1. **Ship Sign in with Apple as a peer of Google + GitHub.** Same UX, same architecture.
   - *Pros:* Unambiguous compliance; familiar to users who already use Apple ID; future-proof.
   - *Cons:* Most engineering work.

2. **Remove Google/GitHub login from the iOS build only** (offer only own-account or email-magic-link on iOS) and keep them on web/Android.
   - *Pros:* Avoids 4.8 entirely on iOS.
   - *Cons:* Drastically degrades iOS UX vs. competitors; alters product behavior per platform; arguably worse than implementing Sign in with Apple.

3. **Implement only a passwordless email magic-link as the "equivalent privacy-preserving login service".** Argue that it meets the three 4.8 criteria.
   - *Pros:* No Apple integration needed.
   - *Cons:* Open to App Review interpretation; in practice Apple reviewers still expect Sign in with Apple. High submission-risk; not recommended.

## Code References

### ActingWeb Library — multi-provider plumbing
- `actingweb/interface/app.py:60` — `self._oauth_configs: dict[str, dict[str, Any]] = {}`
- `actingweb/interface/app.py:139-208` — `_apply_runtime_changes_to_config()` writes `config.oauth_providers`
- `actingweb/interface/app.py:210-261` — `with_oauth(..., provider="")` API
- `actingweb/interface/app.py:630-634` — `add_github()` convenience
- `actingweb/interface/app.py:865-927` — `get_config()` populating providers
- `actingweb/config.py:136-153` — Config OAuth attributes (`oauth`, `oauth2_provider`, `oauth_providers`)
- `actingweb/oauth2.py:33-100` — Provider classes
- `actingweb/oauth2.py:240-308` — `exchange_code_for_token()` (where static client_secret is passed)
- `actingweb/oauth2.py:310-366` — `refresh_access_token()`
- `actingweb/oauth2.py:368-426` — `validate_token_and_get_user_info()` (sync userinfo call)
- `actingweb/oauth2.py:428-495` — `validate_token_and_get_user_info_async()`
- `actingweb/oauth2.py:497-572` — `get_email_from_user_info()` (provider-specific extraction)
- `actingweb/oauth2.py:830-891` — `revoke_token()`
- `actingweb/oauth2.py:897-915` — `_get_provider_config()`, `_PROVIDER_DISPLAY_NAMES`
- `actingweb/oauth2.py:918-982` — Authenticator factories with provider branching

### ActingWeb Library — handlers
- `actingweb/handlers/oauth2_spa.py:40-80` — PKCE generation
- `actingweb/handlers/oauth2_spa.py:53` — `_KNOWN_PROVIDER_PREFIXES = ("google", "github")`
- `actingweb/handlers/oauth2_spa.py:56-61` — `_is_known_provider()`
- `actingweb/handlers/oauth2_spa.py:200-290` — `/oauth/config` provider listing
- `actingweb/handlers/oauth2_spa.py:305-466` — `/oauth/spa/authorize` PKCE + state composition
- `actingweb/handlers/oauth2_spa.py:664-864` — `/oauth/spa/token` mobile authorization_code grant
- `actingweb/handlers/oauth2_spa.py:1278, 1299` — GitHub revocation note
- `actingweb/handlers/oauth2_callback.py:88-668` — `OAuth2CallbackHandler.get()`
- `actingweb/handlers/oauth2_callback.py:128-136` — Provider extraction from state
- `actingweb/handlers/oauth2_callback.py:220, 855` — GitHub-specific email collection
- `actingweb/handlers/oauth2_callback.py:481-510, 960-1004` — `oauth_success` lifecycle hook firing
- `actingweb/handlers/oauth2_callback.py:706-1001` — `_process_spa_oauth_and_create_session()`
- `actingweb/handlers/oauth2_endpoints.py:459-718` — MCP authorization form provider enumeration
- `actingweb/handlers/oauth2_endpoints.py:967-989` — GitHub revocation comment
- `actingweb/handlers/factory.py:34-180` — Web UI provider listings
- `actingweb/oauth_session.py:48-109` — PKCE verifier storage; `oauth_provider` persisted at `oauth_session.py:209`
- `actingweb/oauth_state.py:38-72` — `decode_state()` cleartext-JSON helper
- `actingweb/oauth2_server/oauth2_server.py:45-54, 196-208, 269, 289-294` — MCP server provider branching

### ActingWeb Library — integrations & auth
- `actingweb/interface/integrations/fastapi_integration.py:207-235` — `authenticate_google_oauth()`
- `actingweb/interface/integrations/fastapi_integration.py:257` — `oauth_providers` multi-provider redirect
- `actingweb/interface/integrations/fastapi_integration.py:610-665` — Callback route registration
- `actingweb/interface/integrations/fastapi_integration.py:1749-1792` — `_handle_google_oauth_callback()`
- `actingweb/interface/integrations/fastapi_integration.py:2581-2588` — Google-specific JWKS URI in OAuth2 discovery
- `actingweb/interface/integrations/flask_integration.py:1429, 1677-1684` — Equivalent Flask paths
- `actingweb/auth.py:219-288` — `check_token_auth()`
- `actingweb/auth.py:290-370` — `_check_oauth2_token()` single-provider userinfo call
- `actingweb/auth.py:372-424` — `_check_spa_token()` (ActingWeb-issued tokens)
- `actingweb/auth.py:426-473` — `_looks_like_oauth2_token()` heuristic
- `actingweb/auth.py:614-657` — `_should_redirect_to_oauth2()` multi-provider redirect

### Tests
- `tests/test_mobile_oauth2.py:25-67` — Provider redirect_uri override
- `tests/test_mobile_oauth2.py:70-106` — Prefix-suffixed provider name variants
- `tests/test_mobile_oauth2.py:109-165` — `exchange_code_for_token` redirect_uri override
- `tests/test_mobile_oauth2.py:167-522` — Mobile authorization_code grant end-to-end

## External References

### Apple authoritative
- [Sign in with Apple OIDC discovery](https://appleid.apple.com/.well-known/openid-configuration)
- [Apple — Authenticating users with Sign in with Apple](https://developer.apple.com/documentation/signinwithapple/authenticating-users-with-sign-in-with-apple)
- [Apple — Sign in with Apple REST API](https://developer.apple.com/documentation/signinwithapplerestapi)
- [Apple — Generate and validate tokens](https://developer.apple.com/documentation/signinwithapplerestapi/generate-and-validate-tokens)
- [Apple — Creating a client secret (ES256 JWT)](https://developer.apple.com/documentation/accountorganizationaldatasharing/creating-a-client-secret)
- [Apple — Fetch Apple's public key for verifying token signature](https://developer.apple.com/documentation/signinwithapplerestapi/fetch_apple_s_public_key_for_verifying_token_signature)
- [Apple — Revoke tokens](https://developer.apple.com/documentation/signinwithapplerestapi/revoke-tokens)
- [Apple TN3194 — Handling account deletions and revoking tokens](https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple)
- [Apple — Configure Sign in with Apple for the web](https://developer.apple.com/help/account/capabilities/configure-sign-in-with-apple-for-the-web/)
- [Apple — Register an App ID](https://developer.apple.com/help/account/identifiers/register-an-app-id/)
- [Apple — About Sign in with Apple (App ID + Services ID grouping)](https://developer.apple.com/help/account/capabilities/about-sign-in-with-apple/)
- [Apple — Communicating using the private email relay service](https://developer.apple.com/documentation/signinwithapple/communicating-using-the-private-email-relay-service)
- [Apple Developer Forums #118209 — name/email returned only first time](https://developer.apple.com/forums/thread/118209)
- [Apple Developer Forums #121760 — response_mode=form_post requirement](https://developer.apple.com/forums/thread/121760)
- [Apple Developer Forums #121627 — access_token has no use](https://developer.apple.com/forums/thread/121627)
- [Apple Developer Forums #651237 — refresh token lifetime](https://developer.apple.com/forums/thread/651237)
- [Apple Developer Forums #808653 — is_private_email sometimes missing](https://developer.apple.com/forums/thread/808653)
- [Apple Developer Forums #696055 — localhost not allowed](https://developer.apple.com/forums/thread/696055)
- [Apple Developer Forums #126319 — aud mismatch native vs web](https://developer.apple.com/forums/thread/126319)
- [Apple — App Review Guidelines (current 4.8 text)](https://developer.apple.com/app-store/review/guidelines/)

### App Store 4.8 history and analysis
- [App Store Review Guidelines History](https://www.appstorereviewguidelineshistory.com/)
- [Michael Tsai — Sign in With Apple No Longer Required (Jan 2024)](https://mjtsai.com/blog/2024/01/26/sign-in-with-apple-no-longer-required/)
- [9to5Mac — Apple (sort of) removes its requirement (Jan 2024)](https://9to5mac.com/2024/01/27/sign-in-with-apple-rules-app-store/)
- [WorkOS — Auth requirements for the Apple Store in 2025](https://workos.com/blog/apple-app-store-authentication-sign-in-with-apple-2025)

### Implementation guides
- [Okta — What the Heck is Sign In with Apple?](https://developer.okta.com/blog/2019/06/04/what-the-heck-is-sign-in-with-apple)
- [Scott Brady — Implementing Sign in with Apple (ASP.NET Core, but language-agnostic)](https://www.scottbrady.io/openid-connect/implementing-sign-in-with-apple-in-aspnet-core)
- [Sarunw — Sign in with Apple Tutorial Part 3: Backend Token verification](https://sarunw.com/posts/sign-in-with-apple-3/)
- [Sarunw — Part 4: Web and Other Platforms](https://sarunw.com/posts/sign-in-with-apple-4/)
- [Ory — How Apple broke "Sign in with Apple" with a silent redirect](https://www.ory.com/blog/apple-sign-in-incident-issuer)
- [Logto — Apple OAuth & OIDC endpoints overview](https://logto.io/oauth-providers-explorer/apple)
- [Better Auth — Apple integration (dual aud handling)](https://better-auth.com/docs/authentication/apple)
- [Curity — Sign in with Apple authenticator docs](https://curity.io/docs/idsvr/latest/authentication-service-admin-guide/authenticators/sign-in-with-apple.html)

### Python implementation references
- [python-social-auth — social_core/backends/apple.py](https://github.com/python-social-auth/social-core/blob/master/social_core/backends/apple.py)
- [python-social-auth — AppleID backend docs](https://python-social-auth.readthedocs.io/en/latest/backends/apple.html)
- [django-allauth — Apple provider docs](https://docs.allauth.org/en/dev/socialaccount/providers/apple.html)
- [Authlib — RFC 7523 JWT client auth](https://docs.authlib.org/en/stable/oauth2/specs/rfc7523.html)
- [PyJWT usage](https://pyjwt.readthedocs.io/en/latest/usage.html)
- [PyJWT issue #234 — .p8 / ES256](https://github.com/jpadilla/pyjwt/issues/234)
- [aamishbaloch gist — Sign In with Apple using Django](https://gist.github.com/aamishbaloch/2f0e5d94055e1c29c0585d2f79a8634e)
- [davidhariri gist — Python Apple JWT verification](https://gist.github.com/davidhariri/b053787aabc9a8a9cc0893244e1549fe)
- [truffls/sign-in-with-apple-using-django](https://github.com/truffls/sign-in-with-apple-using-django)
- [DEV — Validating Sign-In with Apple Tokens in Python](https://dev.to/amzar/guide-to-validating-sign-in-with-apple-tokens-in-python-13fm) (do NOT copy its disabled-verification example)
- [Medium — Why Apple SSO Doesn't Return First and Last Name After First Login](https://medium.com/@jating4you/why-apple-sso-doesnt-return-first-and-last-name-after-first-login-and-how-to-handle-it-f157e35d7a4d)

### Capacitor plugins
- [capacitor-community/apple-sign-in (iOS+Web only, no Android)](https://github.com/capacitor-community/apple-sign-in)
- [Cap-go/capacitor-social-login (Apple+Google+Facebook unified)](https://github.com/Cap-go/capacitor-social-login)
- [Capawesome — Apple Sign-In Plugin](https://capawesome.io/plugins/apple-sign-in/)
- [rlfrahm/capacitor-apple-login (iOS-only, minimal)](https://github.com/rlfrahm/capacitor-apple-login)
- [@capacitor-community/generic-oauth2](https://www.npmjs.com/package/@capacitor-community/generic-oauth2)

---

## Addendum: Findings from the actingweb_mcp Capacitor App

Date added: 2026-05-28. Source repo: `../actingweb_mcp` (checked alongside this document).

This addendum walks through the **consumer app's current Capacitor implementation** and surfaces facts that change the design surface for the actingweb library.

### Core finding: native mobile sign-in does not have to live in the actingweb library

The actingweb_mcp project has already shipped Capacitor-based iOS/Android apps with two distinct working patterns for native sign-in, and **the Google native flow bypasses the actingweb library's OAuth flow entirely**:

| Provider | Web | iOS native | Android |
|---|---|---|---|
| Google | actingweb `/oauth/spa/authorize` | **Custom app endpoint** `/api/auth/google-mobile` accepting an `id_token` | Same custom endpoint, different `aud` |
| GitHub | actingweb `/oauth/spa/authorize` | actingweb `/oauth/spa/token` (auth code + PKCE) with `provider="github-mobile"` | Same |

The Google native flow is implemented as a custom FastAPI route registered in `application.py` (`actingweb_mcp/api/auth_mobile.py`, `actingweb_mcp/helpers/oauth_mobile.py`). It:

1. Verifies the Google `id_token` by calling Google's `https://oauth2.googleapis.com/tokeninfo` endpoint (no local JWKS validation — simpler, no extra deps).
2. Accepts multiple acceptable `aud` values (iOS client ID, Android client ID, Android server client ID, web client ID — `auth_mobile.py:119-136`).
3. Calls `create_google_authenticator(config).lookup_or_create_actor_by_identifier(email, user_info=…)` from the actingweb library.
4. Generates an ActingWeb session token via `config.new_token()` and stores it in `OAuth2SessionManager` (`actingweb_mcp/api/auth_mobile.py:181-188`).
5. Creates a refresh token via `session_manager.create_refresh_token()`.
6. Manually fires the `oauth_success` lifecycle hook with `email`, `access_token`, `token_data={}`, `user_info` (`auth_mobile.py:194-212`).
7. Returns `{access_token, refresh_token, actor_id, email, expires_in, expires_at}` as JSON.

This means the **iOS native Apple Sign-In flow can follow the exact same pattern** without any actingweb library change at all: a new `/api/auth/apple-mobile` endpoint with a `verify_apple_id_token()` helper.

### What the actingweb library has to absorb anyway

Even though native iOS can live in the app, three flows **cannot** be implemented purely at the app level:

1. **Web SPA** — Apple is one of the providers shown on `LoginPage.tsx`. The user clicks "Continue with Apple" → `AuthContext.login('apple')` → `POST /oauth/spa/authorize` (the actingweb library handler). The library must produce a valid Apple auth URL — including the `client_id` (Services ID), `response_mode=form_post`, and correctly formatted `state`/`nonce`.
2. **`/oauth/callback`** — Apple POSTs the response (form_post). The library's callback handler must accept POST with form body containing `code`, `state`, `id_token`, and `user` (JSON-encoded, first sign-in only).
3. **Token exchange against Apple** — The backend must hit `https://appleid.apple.com/auth/token` with the JWT-based `client_secret`. The mobile app cannot do this (the `.p8` private key must stay on the server). This is true whether the code arrived via web SPA, iOS native (if you also want the refresh_token), or Android Custom Tab.

So the actingweb library **must** support Apple at least for: provider registration, authorize URL construction, form_post callback, and Apple's JWT-`client_secret` token exchange + id_token validation.

The iOS-native path **can optionally** live outside the library; whether to also add a library helper for it (analogous to a hypothetical `verify_apple_id_token()` in actingweb) is a design choice — see "Updated Decision 5" below.

### Concrete environment / identity facts already known

These were not visible from reading the actingweb library and are required to scope the work:

- **iOS Bundle ID / Android package**: `io.actingweb.emm` (both `frontend/capacitor.config.ts` and `frontend/ios/App/App/Info.plist`).
- **App display name**: "Emm AI" (Info.plist `CFBundleDisplayName`).
- **Apple Team ID**: `J468T7SG32` (documented in `docs/MOBILE.md:245` for fastlane).
- **Apple API key path pattern**: `~/keys/AuthKey_<KEYID>.p8` (already used for App Store Connect uploads in fastlane). A **second**, separate `.p8` is needed for Sign in with Apple (Keys → "Sign In with Apple" capability in developer.apple.com). They are not interchangeable.
- **Xcode 26 / iOS 26 SDK** is required for App Store Connect uploads (`docs/MOBILE.md:8`).
- **OAuth callback URL scheme** for non-Apple mobile providers: `io.actingweb.emm://callback`. Apple cannot use a custom URL scheme — Apple's `redirect_uri` must be HTTPS. The Android flow must route Apple's HTTPS redirect through the backend, then deep-link back into the app.

### Concrete patterns the actingweb library should mirror

These exist in actingweb_mcp today and should not be re-litigated:

1. **Provider naming convention `*-mobile`** — `application.py:447-456` registers `github-mobile` as a second provider entry with a different `redirect_uri` (`io.actingweb.emm://callback`). The actingweb library's prefix-match (`oauth2.py:938-945` — `provider.startswith("google-")` / `github-`) already supports this. **Apple needs the same**: `apple` for web, `apple-mobile` for the Android Capacitor case (Apple's `redirect_uri` would still be HTTPS, but the mobile entry could carry different `response_mode` or `aud` expectations).
2. **`/oauth/config` filtering** — `frontend/src/context/AuthContext.tsx:195-199` filters out any provider whose `display_name` ends with `-mobile`. This means mobile-only providers must use display names with the `-mobile` suffix to remain invisible in the UI. For Apple, the same naming rule applies — but more interestingly, **the web Apple provider does NOT need a `-mobile` variant on iOS** because iOS uses the custom endpoint, not the SPA provider list.
3. **Lifecycle hook user_info shape** — `hooks/actingweb/lifecycle_hooks.py:191-234` is the `oauth_success` hook. It pulls `displayname` by trying in order: `user_info["name"]` → `given_name`+`family_name` → `login`. For Apple, the source keys are `firstName` and `lastName` (in the web flow they arrive in the form_post `user` parameter, not in `id_token`; on native iOS the Capacitor plugin returns them as `givenName`/`familyName`). The actingweb library that fires the hook must **normalize** Apple's keys into a shape the hook can consume, OR the actingweb_mcp hook must be extended to also try Apple keys.
4. **Acceptable `aud` is a list, not a single value** — `helpers/oauth_mobile.py:60-66` already accepts multiple Google client IDs. Apple's library code should do the same out of the box (Bundle ID + Services ID).
5. **Rate limiting on unauthenticated token endpoints** — `auth_mobile.py:28-102` rate-limits per client IP. Any new public Apple endpoint in either the library or the app should do the same.
6. **Refresh-token storage** — `frontend/src/auth/SecureStorage.ts` (Keychain on iOS, Keystore on Android via `capacitor-secure-storage-plugin`). Token-delivery `json` mode (`token_delivery: 'json'` in the POST body) is used so the refresh token comes back in JSON rather than an HttpOnly cookie. Apple's flow should use the same delivery mode for mobile.
7. **`actor_created` + `oauth_success` hook order** — the custom `/api/auth/google-mobile` endpoint does NOT fire `actor_created` (only `oauth_success`). The actingweb library's standard flows do fire both. This inconsistency exists in the app today; Apple should match whichever is chosen.

### Apple Developer Portal config required (not yet present)

None of this exists yet in the actingweb_mcp repo:

- **App ID**: enable the **Sign In with Apple** capability on `io.actingweb.emm` as "Primary App ID."
- **Services ID**: create one (e.g. `io.actingweb.emm.web`), associate with the Primary App ID, register Return URLs (the backend's `/oauth/callback` over HTTPS).
- **Key**: create a new "Sign In with Apple" key in Keys → All. Download the `.p8` once. This is **separate** from the existing App Store Connect API key.
- **iOS entitlements**: add `com.apple.developer.applesignin = ['Default']` to the iOS `App.entitlements` file (Xcode → Signing & Capabilities → +Capability → "Sign in with Apple"). Currently no `App.entitlements` exists at `frontend/ios/App/App/`.
- **Email relay verification**: if you want to email private-relay users (`@privaterelay.appleid.com`), register sending domains in developer.apple.com under Configure → Email Sources.

### Capacitor plugin choice — what fits this codebase

The codebase currently uses `@capawesome/capacitor-google-sign-in` (Capawesome, native iOS+Android) and `@capacitor-community/generic-oauth2` (community, for GitHub's browser-tab flow). Two realistic plugin choices for Apple:

1. **`@capacitor-community/apple-sign-in`** (iOS+Web, **no Android**). Aligns with `@capacitor-community/generic-oauth2` which is already a dep. Android Apple sign-in must be handled separately (e.g., open the web flow via `@capacitor/browser` and listen for the deep-link, mirroring the existing `githubMobileLogin()` implementation in `MobileAuthProvider.ts:127-241`).
2. **`@capgo/capacitor-social-login`** (iOS+Android+Web). Would replace the existing `@capawesome/capacitor-google-sign-in` and absorb GitHub too. Larger refactor of `MobileAuthProvider.ts`.

Option 1 is the smaller change and keeps the existing Google/GitHub paths intact. Android Apple sign-in becomes a `Browser.open()` + deep-link flow analogous to `githubMobileLogin()` — landing on the **same** `/oauth/callback` (or a new dedicated route) that the web flow uses.

### Frontend changes implied (out of actingweb library scope but informs API design)

- `LoginPage.tsx:142-143` hardcodes provider icons by name (`provider.name === 'google' && <GoogleIcon />`). Adding Apple requires an `AppleIcon` SVG and a third conditional — trivial.
- `AuthContext.tsx:336-345` hardcodes mobile provider dispatch (`if (provider === 'google') ... else if (provider === 'github') ...`). Apple needs a third branch invoking a new `appleMobileLogin()`.
- The OAuth config response shape (`{ name, display_name }`) per provider is already used by the frontend — no change needed.

### Account-deletion compliance

Apple's longstanding rule: any app that supports Sign in with Apple must offer in-app account deletion. The actingweb_mcp app already supports actor deletion via `actor_deleted` lifecycle hook (`lifecycle_hooks.py:183-189`). For Apple compliance, that hook must also **call Apple's `/auth/revoke`** endpoint with the user's Apple refresh token (per Apple Technote TN3194). This requires:

- Persisting the Apple refresh token at sign-in time (the actingweb library already persists `oauth_refresh_token` via `actor.store.oauth_refresh_token` at `oauth2.py` / mobile token handler).
- Knowing which provider issued the token (the actingweb library already stores `actor.store.oauth_provider` — check for `"apple"` in `actor_deleted`).
- The library's `revoke_token()` (`oauth2.py:830-891`) needs to support Apple's JWT `client_secret` for the revoke call.

### Updated take on the original decisions

The new findings shift the weight on these decisions from the original document:

**Original Decision 5 (native iOS endpoint)** — The actingweb_mcp Google precedent (`/api/auth/google-mobile`) makes **Option 1 (dedicated endpoint)** look much more natural than originally weighted. The simplest path is: do not add a new endpoint to the actingweb library at all; document the helper functions needed (`lookup_or_create_actor_by_identifier`, `OAuth2SessionManager.create_refresh_token`, `hooks.execute_lifecycle_hooks("oauth_success", …)`) and let actingweb_mcp register its own `/api/auth/apple-mobile`. **OR** add a thin `verify_apple_id_token(id_token, audiences) -> user_info | None` helper to the actingweb library so apps don't have to copy the JWKS-validation logic.

**Original Decision 6 (Android code-redemption)** — Confirmed: Apple's redirect_uri must be HTTPS, so the only realistic path is for Apple to POST to ActingWeb's backend (a new or extended `/oauth/callback`), which then deep-links back into the Capacitor app at `io.actingweb.emm://callback`. The actingweb_mcp deep-link handler (`AndroidManifest.xml:24-30`, `Info.plist:53-62`) is already set up to receive that deep-link.

**Original Decision 7 (form_post POST callback)** — Confirmed: `/oauth/callback` currently is GET-only and is shared by Google + GitHub. Apple POSTs. Adding POST to the same route would handle Apple without changing redirect_uri config in Apple's Developer Portal later. The `user` form-post parameter (first sign-in name/email) must be parsed and merged into `user_info` before firing `oauth_success` so the existing `lifecycle_hooks.py` hook can use it.

**Original Decision 9 (Capacitor plugin choice)** — The codebase already prefers `@capacitor-community/*` and `@capawesome/*` over `@capgo/*`. Practical recommendation: `@capacitor-community/apple-sign-in` for iOS, hand-rolled `Browser.open()` for Android (mirroring `githubMobileLogin()` exactly).

### Additional decisions surfaced

**Addendum Decision A: Where does the iOS-native Apple id_token validation live?**

1. **In actingweb_mcp** (mirroring `helpers/oauth_mobile.py:verify_google_id_token`). New file `helpers/oauth_apple.py` with `verify_apple_id_token(id_token, audiences) -> user_info | None`, called from new `api/auth_apple.py:/api/auth/apple-mobile`.
   - *Pros:* Zero library change for native iOS; symmetric with how Google native is implemented; ships independently of an actingweb release.
   - *Cons:* JWKS caching, key rotation, and RS256 validation logic duplicates what the library will also need for the web flow.

2. **In the actingweb library** as a helper exposed alongside `create_apple_authenticator()`. Both `api/auth_apple.py` and the library's web-flow handler use the same helper.
   - *Pros:* One implementation of JWKS fetching + caching + validation; consistent error handling; reusable for other actingweb apps adding Apple later.
   - *Cons:* Requires an actingweb release; couples the timeline.

**Addendum Decision B: `with_oauth()` API shape for Apple's three extra params (Team ID, Key ID, private key)**

The current signature `app.with_oauth(provider="github", client_id=…, client_secret=…, scope=…, auth_uri=…, token_uri=…, redirect_uri=…)` cannot express Apple's needs:
- `client_secret` is the static string. Apple's needs to be regenerated as an ES256 JWT.
- No place for Team ID, Key ID, or private key (file path or PEM).

1. **Extend `with_oauth()`** with optional `apple_team_id`, `apple_key_id`, `apple_private_key_path`, `apple_private_key_pem`, `apple_audiences` kwargs. They are no-ops for non-Apple providers.
   - *Pros:* One method, additive.
   - *Cons:* Cluttered, awkward when those kwargs are required only for Apple.

2. **`with_apple_oauth()` builder** that takes Apple-specific params and internally constructs the right provider config (skipping `client_secret` since it's derived). Mirrors `add_github()` at `interface/app.py:630-634`.
   - *Pros:* Cleanest ergonomics; explicit about what Apple needs.
   - *Cons:* Two public methods to document.

3. **Pass an `oauth_extras` dict** to `with_oauth()` for provider-specific extras: `app.with_oauth(provider="apple", client_id=services_id, scope="name email", ..., oauth_extras={"apple_team_id": ..., "apple_key_id": ..., "apple_private_key_path": ...})`.
   - *Pros:* Future-proof for other oddball providers; no signature explosion.
   - *Cons:* Less self-documenting than typed kwargs.

**Addendum Decision C: How is `actor.store.oauth_provider` written for Apple users who sign in via iOS native?**

The custom `/api/auth/google-mobile` endpoint today does NOT set `actor.store.oauth_provider = "google"` after creating the actor (it relies on `lookup_or_create_actor_by_identifier` which only sets it on creation, `oauth2.py:729`). Existing actors keep their old `oauth_provider` value. For Apple, decide whether the custom endpoint should update this property each sign-in to reflect the latest provider — relevant if revocation logic (Addendum below) reads it to decide whether to call Apple's `/auth/revoke` on `actor_deleted`.

**Addendum Decision D: Account-deletion → Apple revocation**

For App Store compliance, when an Apple-signed-in user deletes their actor, the backend must call Apple's `/auth/revoke`. Two implementation paths:

1. **Lifecycle hook in actingweb_mcp** — `hooks/actingweb/lifecycle_hooks.py:on_actor_deleted` reads `actor.store.oauth_provider`, and if `"apple"`, fetches `actor.store.oauth_refresh_token` and calls `create_apple_authenticator(config).revoke_token(refresh_token)`.
   - *Pros:* Stays in the app; no library change.
   - *Cons:* Requires `revoke_token()` in the library to support Apple's JWT client_secret (still a library change).

2. **Library-level**: actingweb's actor deletion path itself calls `revoke_token` for whichever provider issued the most recent token.
   - *Pros:* Compliance is automatic for any actingweb app.
   - *Cons:* Larger change; surface for bugs in trust-relationship token revocation that exists today.

### Code references (actingweb_mcp)

- `frontend/capacitor.config.ts:1-26` — Bundle ID, app name
- `frontend/ios/App/App/Info.plist:53-62` — Custom URL scheme for OAuth deep links
- `frontend/android/app/src/main/AndroidManifest.xml:24-30` — Android intent filter for `io.actingweb.emm://callback`
- `frontend/package.json:24-26, 31` — Capacitor plugin versions; `@capawesome/capacitor-google-sign-in` for Google; no Apple plugin
- `frontend/src/auth/MobileAuthProvider.ts:59-121` — Google native flow (id_token → custom endpoint)
- `frontend/src/auth/MobileAuthProvider.ts:127-241` — GitHub browser-tab flow (auth code + PKCE → `/oauth/spa/token`)
- `frontend/src/auth/SecureStorage.ts` — Keychain/Keystore wrapper for refresh tokens
- `frontend/src/context/AuthContext.tsx:195-199` — `/oauth/config` filters providers whose display_name ends with `-mobile`
- `frontend/src/context/AuthContext.tsx:330-368` — Mobile login dispatch, hardcoded per provider
- `frontend/src/pages/LoginPage.tsx:21-50` — Provider icon SVGs; `provider.name === 'google' / 'github'` checks
- `application.py:411-457` — Provider config calling `app.with_oauth(provider=…)` per provider, including `github-mobile`
- `application.py:380` — `with_indexed_properties(["oauthId", "email"])`
- `api/auth_mobile.py:50-227` — Custom `/api/auth/google-mobile` endpoint (the precedent)
- `helpers/oauth_mobile.py:21-93` — Google id_token verification via tokeninfo endpoint
- `hooks/actingweb/lifecycle_hooks.py:191-234` — `oauth_success` hook (name extraction logic)
- `hooks/actingweb/lifecycle_hooks.py:183-189` — `actor_deleted` hook (where Apple revoke would go)
- `docs/MOBILE.md:148-189` — Existing mobile auth flow documentation
- `docs/MOBILE.md:222-264` — Mobile release pipeline including Apple Team ID J468T7SG32

### Summary: minimum required actingweb library work

Stripping back to the strict minimum needed so actingweb_mcp can submit to the App Store with Apple Sign-In:

1. **New `AppleOAuth2Provider`** (or equivalent strategy) supporting:
   - Apple's authorize URL construction with `response_mode=form_post`
   - ES256 JWT `client_secret` generation (Team ID, Key ID, private key) — used in token exchange and revoke
   - id_token-only userinfo extraction (no userinfo endpoint HTTP call)
   - JWKS fetching + caching for RS256 id_token validation
   - Acceptance of a list of audiences (Services ID + Bundle ID)

2. **`/oauth/callback` POST handler** that parses `application/x-www-form-urlencoded` body, merges the optional `user` JSON field into the user_info dict before firing `oauth_success`.

3. **`with_oauth()` API extension** accepting Apple-specific parameters (whichever shape Decision B picks).

4. **`/oauth/spa/authorize` provider-name allowlist** (`oauth2_spa.py:53`) extended with `"apple"` (and optionally `"apple-mobile"` for an Android variant).

5. **`oauth2_server/oauth2_server.py:45-54, 196-208, 289-294`** extended with Apple as a third pre-instantiated authenticator for the MCP flow (only needed if MCP clients should also be able to sign in with Apple — likely yes for parity).

6. **`revoke_token()`** uses the same JWT-generation path so Apple revocation works.

Everything else (iOS native `id_token` POST endpoint, frontend icons, AuthContext branch, Capacitor plugin install, Apple Developer Portal config, `App.entitlements`) lives in the actingweb_mcp app — no library change needed.

### External references added by this addendum

- [Apple — Sign in with Apple capability for App IDs](https://developer.apple.com/help/account/capabilities/configure-sign-in-with-apple-for-the-web/)
- [Apple Technote TN3194 — Handling account deletions and revoking tokens](https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple)
- [Apple Developer — Configure email sources for private email relay](https://developer.apple.com/help/account/capabilities/configure-private-email-relay-service/)
- [capacitor-community/apple-sign-in (used pattern reference)](https://github.com/capacitor-community/apple-sign-in)
- [@capacitor/browser docs (used for GitHub mobile + would be used for Android Apple)](https://capacitorjs.com/docs/apis/browser)

---

## Addendum 2: Consolidation — Move Native Mobile OAuth Functionality Into actingweb

The previous addendum noted that actingweb_mcp's `/api/auth/google-mobile` endpoint reimplements logic that is already in the actingweb library. This section maps the consolidation: what should move from the app to the library, what the resulting library API surface looks like, and what remains in actingweb_mcp.

### What the library already provides (verified)

The building blocks needed by the existing custom endpoint are all already public actingweb APIs:

| Need | Already in actingweb library |
|---|---|
| Find or create actor by identifier | `OAuth2Authenticator.lookup_or_create_actor_by_identifier()` — `oauth2.py:688-765` |
| Generate access token | `Config.new_token()` — `config.py:362` |
| Store access token in session backend | `OAuth2SessionManager.store_access_token()` — `oauth_session.py:277` |
| Create refresh token | `OAuth2SessionManager.create_refresh_token()` — `oauth_session.py:378` |
| Get session manager | `get_oauth2_session_manager(config)` — `oauth_session.py:695` |
| Fire `oauth_success` hook | `HookRegistry.execute_lifecycle_hooks()` — `interface/hooks.py:719-740` |

The 100+-line `/api/auth/google-mobile` handler in actingweb_mcp is essentially **orchestration boilerplate** plus **id_token validation logic** plus **rate limiting**. Of these, only the id_token validator is genuinely provider-specific; everything else is repeatable across providers.

### The unifying observation

Both Google native and Apple native sign-in produce the **same shape of operation** at the application boundary:

> Given a JWT id_token issued by a known OIDC provider, validate it, identify or create the actor for that identity, issue ActingWeb session tokens, fire the `oauth_success` lifecycle hook, and return tokens.

The same shape also describes any future Microsoft / Facebook / generic OIDC native flow. This is RFC 7523 territory ("JWT Bearer Token Grant"). The actingweb library should expose it as a first-class primitive.

### Proposed library surface: `/oauth/spa/token` with id_token grant

Extend the existing mobile token endpoint (`actingweb/handlers/oauth2_spa.py:664-864 _handle_authorization_code()`) to also accept an id_token grant. Symmetric with the existing authorization_code grant; same response shape; same `token_delivery` semantics.

**Request** (new grant alongside the existing `authorization_code`):

```json
POST /oauth/spa/token
{
  "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
  "provider": "google-mobile",   // or "apple-mobile"
  "assertion": "eyJhbGciOi…",    // the id_token from the native SDK
  "token_delivery": "json"
}
```

(The `urn:ietf:params:oauth:grant-type:jwt-bearer` value is RFC 7523's grant type for using a JWT as the assertion. Using a custom `id_token` grant type is also fine — Apple, AWS Cognito, and many libraries do — but the RFC URN avoids inventing new vocabulary.)

**Response** — identical to the existing authorization_code grant response.

**Handler behavior**:

1. Rate-limit per client IP (lifted from `actingweb_mcp/api/auth_mobile.py:28-102`).
2. Look up provider config by name (existing multi-provider machinery).
3. Validate the id_token via the provider's configured id_token validator.
4. Extract identifier (email or `provider:sub`).
5. `lookup_or_create_actor_by_identifier()`.
6. Create ActingWeb session token + refresh token.
7. Fire `oauth_success` lifecycle hook.
8. Return JSON with tokens.

The existing `authorization_code` grant path stays untouched; only a new branch on `grant_type` is added.

### Per-provider id_token validator

The library needs a pluggable id_token validator that the provider classes carry. Two implementations cover the current needs:

**1. JWKS-based RS256 validator** (Apple, Microsoft, most OIDC providers):

```python
class JWKSIdTokenValidator:
    def __init__(self, jwks_uri: str, expected_iss: str | tuple[str, ...],
                 audiences: list[str], algorithms: list[str] = ["RS256"]):
        ...
    def validate(self, id_token: str, *, nonce: str | None = None) -> dict | None:
        # fetch JWKS (with TTL cache + kid-miss refetch)
        # verify signature + iss + aud (∈ audiences) + exp + (optional) nonce
        # return claims dict or None
```

**2. Tokeninfo-endpoint validator** (Google's `/tokeninfo`, used today by actingweb_mcp):

```python
class TokeninfoIdTokenValidator:
    def __init__(self, tokeninfo_url: str, expected_iss: tuple[str, ...],
                 audiences: list[str]):
        ...
    def validate(self, id_token: str) -> dict | None:
        # GET tokeninfo_url?id_token=...
        # verify iss, aud, exp from response
        # return user_info dict or None
```

Either validator could back Google. JWKS is the "proper" OIDC path; tokeninfo is what actingweb_mcp uses today and is dependency-free. Library should offer both; provider config picks one.

Apple **requires** JWKS — no tokeninfo endpoint exists.

### Per-provider config schema

Extend `Config.oauth_providers[name]` with native-flow keys. Today each provider entry holds `client_id`, `client_secret`, `redirect_uri` (and optionally scope/uri overrides). Add:

```python
config.oauth_providers["google-mobile"] = {
    "client_id": "<web client ID>",            # used as default aud
    "client_secret": "",                       # not used for id_token grant
    "id_token_validator": {
        "type": "tokeninfo",                   # or "jwks"
        "tokeninfo_url": "https://oauth2.googleapis.com/tokeninfo",
        "expected_iss": ("accounts.google.com", "https://accounts.google.com"),
        "audiences": ["<web>", "<ios>", "<android>", "<android-server>"],
    },
}

config.oauth_providers["apple"] = {
    "client_id": "<services ID>",
    "client_secret": "",                       # generated at runtime as ES256 JWT
    "id_token_validator": {
        "type": "jwks",
        "jwks_uri": "https://appleid.apple.com/auth/keys",
        "expected_iss": "https://appleid.apple.com",
        "audiences": ["<services ID>", "<bundle ID>"],
    },
    "apple_team_id": "...",
    "apple_key_id": "...",
    "apple_private_key_path": "...",           # or apple_private_key_pem
}
```

The `with_oauth()` builder accepts these via either typed kwargs or an `oauth_extras` dict (Addendum Decision B from the previous section). My take: a typed builder method per provider type makes the most sense, since Google native and Apple have genuinely different parameter sets:

```python
# Existing — unchanged
app.with_oauth(provider="google", client_id=..., client_secret=..., ...)
app.with_oauth(provider="github", client_id=..., client_secret=..., ...)

# New — native id_token sign-in for Google
app.with_google_native(
    web_client_id=...,
    ios_client_id=...,
    android_client_id=...,
    android_server_client_id=...,
    validator="tokeninfo",  # or "jwks"
)

# New — Apple, covering web + native iOS + Android paths
app.with_apple_sign_in(
    services_id="io.actingweb.emm.web",        # web/Android aud
    bundle_id="io.actingweb.emm",              # iOS native aud
    team_id="J468T7SG32",
    key_id="<key id>",
    private_key_path="/path/to/AuthKey_*.p8",  # or private_key_pem=...
    accept_form_post=True,
)
```

Each of these builders internally calls `with_oauth(provider="google-mobile", …)` and/or `with_oauth(provider="apple", …)` / `with_oauth(provider="apple-mobile", …)`, populating the right `Config.oauth_providers` entries plus the id_token validator config.

### Apple-specific additions, layered on top of the unified primitive

Once the id_token grant is in place, Apple needs three additional library pieces (the only Apple-specific work):

1. **`AppleOAuth2Provider` class** in `oauth2.py` — endpoints, scope, no userinfo_uri, id_token-based identity extraction.
2. **ES256 JWT `client_secret` generator** — used by `exchange_code_for_token()`, `refresh_access_token()`, and `revoke_token()` whenever `provider.name == "apple"`. Cached (e.g. 5-month TTL with refresh on bucket roll-over).
3. **POST handler on `/oauth/callback`** to accept Apple's `response_mode=form_post` body. Parse `code`, `state`, `id_token`, and the `user` JSON field; merge `user` into `user_info` before firing `oauth_success`. Add `_KNOWN_PROVIDER_PREFIXES += ("apple",)` so the existing state machinery routes correctly.

The web SPA Apple flow then reuses the same `/oauth/spa/authorize` → Apple → `/oauth/callback` (POST) → `_process_spa_oauth_and_create_session` path the other providers use, with the new POST entry point and JWT-`client_secret` token exchange wired through `exchange_code_for_token()`.

### What's left in actingweb_mcp after the refactor

**Removed entirely**:
- `actingweb_mcp/api/auth_mobile.py` — 227 lines, gone. Endpoint moves into actingweb's `/oauth/spa/token`.
- `actingweb_mcp/helpers/oauth_mobile.py` — 93 lines, gone. Google tokeninfo validation moves into the library's `TokeninfoIdTokenValidator`.
- The hardcoded route registration `auth_mobile.register_routes(...)` in `application.py`.

**Changed**:
- `actingweb_mcp/application.py:411-457` — replace direct `with_oauth(provider="github-mobile", ...)` calls with the new typed builders (`app.with_google_native(...)`, `app.with_apple_sign_in(...)`). Existing `with_oauth(provider="google" / "github")` web calls unchanged.
- `actingweb_mcp/frontend/src/auth/MobileAuthProvider.ts:83` — change `fetch('/api/auth/google-mobile', { id_token })` to `fetch('/oauth/spa/token', { grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', provider: 'google-mobile', assertion: id_token, token_delivery: 'json' })`. Symmetric with the existing GitHub mobile call at `MobileAuthProvider.ts:195-207`.
- `actingweb_mcp/frontend/src/auth/MobileAuthProvider.ts` — add a new `appleMobileLogin()` function using `@capacitor-community/apple-sign-in`, posting the resulting `identityToken` to `/oauth/spa/token` with `provider: 'apple-mobile'`.
- `actingweb_mcp/frontend/src/context/AuthContext.tsx:330-368` — add a third `else if (provider === 'apple')` branch.
- `actingweb_mcp/frontend/src/pages/LoginPage.tsx:21-50, 142-143` — add `AppleIcon` SVG and conditional.
- `actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:191-234` — extend displayname extraction to try Apple's `firstName`/`lastName` keys.

**New (app-only, no library involvement)**:
- `frontend/ios/App/App/App.entitlements` — add `com.apple.developer.applesignin` (Xcode capability).
- Apple Developer Portal: App ID with Sign in with Apple capability, Services ID associated with the Primary App ID, "Sign In with Apple" private key (`.p8`) downloaded.
- Env vars: `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY_PATH` (or `_PEM`), `APPLE_SERVICES_ID`, `APPLE_BUNDLE_ID`.
- New Capacitor dep: `@capacitor-community/apple-sign-in`.

### Net effect on the codebase

| Layer | Lines added/removed |
|---|---|
| actingweb library | **+~600** (`AppleOAuth2Provider`, `JWKSIdTokenValidator`, `TokeninfoIdTokenValidator`, `with_apple_sign_in()`, `with_google_native()`, id_token grant in `/oauth/spa/token`, POST on `/oauth/callback`, ES256 JWT client_secret, JWKS cache) |
| actingweb library | **+1 dependency**: `PyJWT[crypto]` |
| actingweb_mcp app | **-320** (`api/auth_mobile.py` + `helpers/oauth_mobile.py` deleted) |
| actingweb_mcp app | **+~80** for Apple branches in `MobileAuthProvider.ts`, `AuthContext.tsx`, `LoginPage.tsx`, `lifecycle_hooks.py` |

The library carries the protocol logic; the app carries product UX. The Google-native pattern that actingweb_mcp pioneered becomes a first-class actingweb feature available to every consumer.

### No mobile-auth migration concerns

**Important framing**: neither actingweb nor actingweb_mcp has ever released mobile auth to production. The Capacitor builds in actingweb_mcp have been deployed as test apps only (TestFlight internal / Play internal, per `docs/MOBILE.md:222-228`), and the App Store submission is blocked precisely on this Apple Sign-In work. That means:

- **No live users on the legacy `/api/auth/google-mobile` path.** The endpoint can be deleted outright when the library absorbs its responsibilities — no deprecation window, no backward-compat shim, no token-format bridging.
- **No "mobile auth migration" code to write.** Refresh tokens issued by the old endpoint don't need to be re-issued or translated. (Internal-track testers will simply sign in again on the new build, which is normal app-update behavior.)
- **No production rollback risk** specific to the mobile flow — only the web SPA flow has live users, and the web Google + GitHub paths are not touched by this refactor.

This is unusually clean: the consolidation can be designed as the **only** mobile auth shape that actingweb ever ships, without carrying any legacy baggage.

### Migration path (ordering)

The actingweb library release and the actingweb_mcp refactor land together in a coordinated drop:

1. **actingweb 3.11.0 (additive, backward compatible)** — ship the new `with_google_native()` + `with_apple_sign_in()` builders, the unified id_token grant on `/oauth/spa/token`, the POST handler on `/oauth/callback`, `AppleOAuth2Provider`, validators. Existing `with_oauth(provider="google" / "github" / "github-mobile")` web flows unchanged. New PyJWT dep.
2. **actingweb_mcp** updates `pyproject.toml` to require `actingweb >= 3.11`. Switches `application.py` to call `app.with_google_native(...)` and `app.with_apple_sign_in(...)`. Front-end gains Apple. The custom `/api/auth/google-mobile` route is removed; the front-end re-points Google native to `/oauth/spa/token` with the JWT-bearer grant. Tests updated. The combined change is exercised on a test build (TestFlight internal / Play internal) before App Store submission.
3. Once the test build verifies Apple Sign-In end-to-end (web SPA, iOS native, Android Custom Tab), actingweb_mcp submits to the App Store and Play production.

This sequencing means **the only actingweb release blocking the Apple rollout is 3.11** with the consolidated work, and the actingweb_mcp release that consumes it. The two repos are released in lock-step but neither needs to support a transitional state — there's no period where, e.g., the library has the new grant but the app still calls the old endpoint, because the old endpoint is being removed at the same time.

### Updated decisions

The original document's Decisions 5 (native iOS endpoint) and 8 (PyJWT dependency) are resolved by the consolidation approach:

- **Decision 5** → **In the library**: the new id_token grant on `/oauth/spa/token` replaces both the actingweb_mcp custom endpoint and any need for a new library route. One endpoint serves Google native, Apple native, future OIDC native providers.
- **Decision 8** → **PyJWT becomes a core dep** of actingweb 3.11 (or `pyjwt[crypto]` as an `apple`/`native-auth` extra). Required for both ES256 client_secret generation and RS256 id_token validation. The library cannot ship Apple support without it; adding it as a hard dep simplifies installation. PyJWT is a small, well-maintained package and is already a transitive dep of many actingweb deployments.

Addendum Decision A (where Apple id_token validation lives) is also resolved: **in the library**, via the same `JWKSIdTokenValidator` used by any other JWKS-based OIDC provider.

Addendum Decision B (`with_oauth()` API shape) is resolved by introducing typed `with_google_native()` / `with_apple_sign_in()` builders. The base `with_oauth()` stays unchanged.

### Remaining decisions

**Consolidation Decision 1: grant_type value for the new id_token endpoint**

1. `urn:ietf:params:oauth:grant-type:jwt-bearer` (RFC 7523).
   - *Pros:* Standards-compliant; future-proof; recognizable to OAuth-savvy callers.
   - *Cons:* Verbose; some HTTP clients dislike colons in form values.
2. `id_token` (informal).
   - *Pros:* Short, obvious.
   - *Cons:* Not a registered grant type.
3. `native_oidc` or similar custom string.
   - *Pros:* Self-describing.
   - *Cons:* Invented.

**Consolidation Decision 2: validator implementation strategy for Google native**

1. **Tokeninfo** (matches actingweb_mcp today) — one HTTP call to Google per sign-in, no dependencies.
   - *Pros:* Simple; no JWKS cache to manage; existing code can be lifted in.
   - *Cons:* Network round-trip per sign-in; relies on a Google-operated endpoint.
2. **JWKS** (proper OIDC) — local validation with cached keys.
   - *Pros:* No network call after warm cache; symmetric with Apple validator; future-proof for other OIDC providers.
   - *Cons:* JWKS cache + kid-miss handling to test.
3. **Both, selectable per provider** — let `with_google_native(validator="tokeninfo" | "jwks")` choose.
   - *Pros:* Smooth migration from the current behavior; flexible.
   - *Cons:* Two code paths to maintain.

**Consolidation Decision 3: keep `github-mobile` as a separate provider config or fold into the new pattern**

GitHub mobile is **not** an id_token provider (GitHub does not issue id_tokens). It will keep using `/oauth/spa/token` with `grant_type=authorization_code` and PKCE — that is, its current path. Question: rename `github-mobile` to drop the `-mobile` suffix and just key off the `redirect_uri`?

1. **Keep `github-mobile` as today** — a second provider entry with a different `redirect_uri`.
   - *Pros:* No frontend or backend change; the prefix-match in `oauth2.py:938-945` already handles it.
   - *Cons:* Two GitHub provider records for one logical thing.
2. **Move to per-flow `redirect_uri`** — one GitHub entry, but the SPA passes the desired `redirect_uri` per request, validated against an allowlist.
   - *Pros:* Single source of truth for GitHub credentials; cleaner config.
   - *Cons:* Out of scope for the Apple rollout; can be done later.

Recommend: keep `github-mobile` as today; revisit in a future cleanup.


