# OAuth Login Flow with Postponed Actor Creation

This document describes how to implement "Login with Google" / "Login with GitHub" buttons in your ActingWeb application, where actor creation is postponed until after the OAuth2 flow completes and email is obtained.

## Important: Two Different OAuth2 Flows

ActingWeb supports **TWO distinct OAuth2 flows**. This document covers the **Google/GitHub OAuth flow for web UI login**. For MCP OAuth2 where ActingWeb acts as an authorization server, see the MCP documentation.

### Flow 1: MCP OAuth2 (ActingWeb as Authorization Server)
- MCP clients dynamically register via `/oauth/register`
- User authorizes via `/oauth/authorize` with trust type selection
- ActingWeb proxies to Google/GitHub for user authentication
- ActingWeb issues its own tokens for `/mcp` endpoint access
- Uses **encrypted state** - routed to `OAuth2EndpointsHandler`

### Flow 2: Google/GitHub OAuth (This Document)
- Direct OAuth2 with Google/GitHub providers
- Used for web UI login at `/www` endpoints
- Can also establish MCP trust relationships (with `trust_type` parameter)
- Uses **JSON state** - routed to `OAuth2CallbackHandler`
- **This is what this document covers**

## Overview

> **Important: Token Architecture**
>
> ActingWeb generates its own session tokens after validating OAuth provider tokens.
> The Google/GitHub token is validated once during callback, then ActingWeb creates
> its own token stored in the session manager. This provides:
> - Fast validation (no network calls to Google/GitHub on each request)
> - Security (OAuth tokens never exposed to frontend)
> - Reliability (no dependency on OAuth provider availability)
>
> See the SPA Authentication Guide for details on token architecture.

The ActingWeb library now supports Google/GitHub OAuth2 login flows where:

1. **User clicks "Login with Google/GitHub"** on the factory page
2. **OAuth2 flow completes** and email is extracted from the provider
3. **Actor is created** with the obtained email
4. **User is redirected** to their actor's page

Additionally, if the OAuth provider cannot provide an email (e.g., GitHub with private email), the library will:

1. Store OAuth tokens temporarily in a session
2. Redirect user to an email input form
3. Complete actor creation once email is provided

## Library Components

The ActingWeb library provides all the backend functionality. Your application only needs to provide templates and configure OAuth2.

### 1. Factory Handler Updates

The factory handler (`actingweb.handlers.factory`) now exposes OAuth URLs in `template_values`:

```python
# In GET / request, template_values will contain:
{
    'oauth_urls': {
        'google': 'https://accounts.google.com/o/oauth2/v2/auth?...',
        'github': 'https://github.com/login/oauth/authorize?...'
    },
    'oauth_providers': [
        {
            'name': 'google',
            'display_name': 'Google',
            'url': 'https://accounts.google.com/o/oauth2/v2/auth?...'
        }
    ],
    'oauth_enabled': True
}
```

### 2. OAuth2 Callback Handler Updates

The OAuth2 callback handler (`actingweb.handlers.oauth2_callback`) now handles missing email gracefully:

- If email is successfully extracted: Creates actor and redirects to `/{actor_id}/www` (existing behavior)
- If email cannot be extracted (HTML template flow): Redirects to `/oauth/email` with a session token
- If email cannot be extracted (SPA flow): Redirects back to SPA with `?email_required=true&session=<id>`

### 3. OAuth Session Management

New module `actingweb.oauth_session` provides:

- `OAuth2SessionManager`: Manages temporary OAuth2 sessions
  - `store_session()`: Store OAuth tokens when email is missing
  - `get_session()`: Retrieve session data
  - `complete_session()`: Complete actor creation with provided email

Sessions are stored in the database using ActingWeb's attribute bucket system with a 10-minute TTL. This provides persistence across multiple containers in distributed deployments.

### 4. OAuth Email Input Handler

New handler `actingweb.handlers.oauth_email.OAuth2EmailHandler`:

- **GET /oauth/email?session=...**: Shows email input form (sets `template_values` for app to render, or returns JSON for SPAs)
- **GET /oauth/email?verify=...**: Validates email verification token and marks email as verified
- **POST /oauth/email**: Processes email input and completes actor creation

Both Flask and FastAPI integrations automatically route `/oauth/email` to this handler.

## Application Implementation

Your application needs to provide templates to create the UI.

### Step 1: Create Factory Template with OAuth Buttons

Create `templates/aw-root-factory.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Login - My ActingWeb App</title>
</head>
<body>
    <h1>Welcome to My ActingWeb App</h1>

    {% if oauth_enabled %}
        <h2>Login with OAuth</h2>
        {% for provider in oauth_providers %}
            <a href="{{ provider.url }}" class="oauth-button">
                Login with {{ provider.display_name }}
            </a>
        {% endfor %}
    {% endif %}

    <h2>Or create account with email</h2>
    <form action="/" method="post">
        <input type="email" name="creator" placeholder="your@email.com" required />
        <button type="submit">Create Account</button>
    </form>
</body>
</html>
```

### Step 2: Create Email Input Template (Optional)

Create `templates/aw-oauth-email.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Enter Email - My ActingWeb App</title>
</head>
<body>
    <h1>Email Required</h1>

    <p>{{ message }}</p>

    {% if error %}
        <p class="error">{{ error }}</p>
    {% endif %}

    <form action="/oauth/email" method="POST">
        <input type="hidden" name="session" value="{{ session_id }}" />
        <label>
            Email Address:
            <input type="email" name="email" required placeholder="your@email.com" />
        </label>
        <button type="submit">Continue</button>
    </form>
</body>
</html>
```

**Note:** If you don't provide this template, the Flask/FastAPI integration will use a basic fallback HTML form.

### Step 3: Configure OAuth2 Provider

In your application initialization:

```python
from actingweb.interface import ActingWebApp

# Single provider (backward compatible)
app = (
    ActingWebApp(
        aw_type="urn:actingweb:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(
        provider="google",
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        scope="openid email profile",
    )
    .with_web_ui(enable=True)  # Required for template rendering
)

# Multiple providers (Google + GitHub simultaneously)
app = (
    ActingWebApp(
        aw_type="urn:actingweb:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(
        provider="google",
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        scope="openid email profile",
    )
    .with_oauth(
        provider="github",
        client_id="your-github-client-id",
        client_secret="your-github-client-secret",
        scope="read:user user:email",
    )
    .with_web_ui(enable=True)
)
```

## Complete Flow Examples

### Flow 2.1: Web UI Login with Email Successfully Retrieved

```
1. User visits GET /
   ↓
   Factory handler returns template_values with oauth_urls (no trust_type)
   ↓
   App renders aw-root-factory.html with "Login with Google" button

2. User clicks "Login with Google"
   ↓
   Browser redirects to Google OAuth2

3. Google redirects to /oauth/callback with code (JSON state, no trust_type)
   ↓
   Flask/FastAPI routes to OAuth2CallbackHandler
   ↓
   Exchange code for access token
   ↓
   Extract email from user info: user@gmail.com
   ↓
   Create actor with email (or lookup existing)
   ↓
   Generate ActingWeb session token (not Google token)
   ↓
   Store in session manager for fast validation
   ↓
   Set HttpOnly cookie with ActingWeb token
   ↓
   Redirect to /{actor_id}/www
```

### Flow 2.2: Web UI Login without Email (GitHub Private Email)

```
1. User visits GET /
   ↓
   Factory handler returns template_values with oauth_urls (no trust_type)
   ↓
   App renders aw-root-factory.html with "Login with GitHub" button

2. User clicks "Login with GitHub" (email is private)
   ↓
   Browser redirects to GitHub OAuth2

3. GitHub redirects to /oauth/callback with code (JSON state, no trust_type)
   ↓
   Flask/FastAPI routes to OAuth2CallbackHandler
   ↓
   Exchange code for access token
   ↓
   Email extraction fails (private email)
   ↓
   Check: trust_type is NOT set → This is web UI login
   ↓
   Store OAuth tokens in temporary session
   ↓
   HTML template flow: Redirect to /oauth/email?session=<session_id>
   SPA flow: Redirect to {spa_redirect_url}?email_required=true&session=<session_id>

4a. HTML template flow:
   OAuth email handler returns template_values
   ↓
   App renders aw-oauth-email.html with email input form
   ↓
   User enters their email address and submits

4b. SPA flow:
   SPA detects email_required=true parameter
   ↓
   SPA shows its own email input form
   ↓
   SPA POSTs to /oauth/email with Accept: application/json

5. POST /oauth/email
   ↓
   Retrieve OAuth tokens from session
   ↓
   Create actor with provided email
   ↓
   If email needs verification:
     - Store verification token and reverse index
     - Fire email_verification_required lifecycle hook
     - App backend sends verification email
   ↓
   Generate ActingWeb session token
   ↓
   HTML template flow: Set HttpOnly cookie, redirect to /{actor_id}/www
   SPA flow: Return JSON with actor_id, access_token, email_requires_verification

6. Email verification (if required):
   ↓
   User clicks link in email: GET /oauth/email?verify=<token>
   ↓
   Token validated, email marked as verified
   ↓
   email_verified lifecycle hook fired
```

### Flow 2.3: MCP Authorization with trust_type (No Email Available)

```
1. OAuth flow initiated with trust_type='mcp_client' in state
   ↓
   Redirect to Google/GitHub OAuth2

2. Google redirects to /oauth/callback with code (JSON state with trust_type)
   ↓
   Flask/FastAPI routes to OAuth2CallbackHandler
   ↓
   Exchange code for access token
   ↓
   Email extraction fails
   ↓
   Check: trust_type IS set → This is MCP authorization
   ↓
   Return error (cannot redirect to web form for MCP clients)
   ↓
   HTTP 502: "Email extraction failed. OAuth provider did not provide
              email address required for mcp_client authorization."
```

**Note:** Flow 2.3 demonstrates that MCP authorization flows with `trust_type` cannot fall back to email input forms because MCP clients are programmatic and cannot interact with web UIs. Users should ensure their OAuth provider (Google/GitHub) is configured to provide email addresses publicly.

## Template Variables Reference

### Factory Template (aw-root-factory.html)

Variables available in `template_values`:

| Variable | Type | Description |
|----------|------|-------------|
| `oauth_urls` | Dict | Dictionary mapping provider names to OAuth URLs |
| `oauth_providers` | List | List of dicts with `name`, `display_name`, `url` |
| `oauth_enabled` | Boolean | True if OAuth is configured |

Example usage:
```html
{% if oauth_enabled %}
    {% for provider in oauth_providers %}
        <a href="{{ provider.url }}">
            Login with {{ provider.display_name }}
        </a>
    {% endfor %}
{% endif %}
```

### Email Input Template (aw-oauth-email.html)

Variables available in `template_values`:

| Variable | Type | Description |
|----------|------|-------------|
| `session_id` | String | Session ID for completing OAuth flow |
| `action` | String | Form action URL (always "/oauth/email") |
| `method` | String | Form method (always "POST") |
| `provider` | String | Provider name ("google", "github", etc.) |
| `provider_display` | String | Provider display name ("Google", "GitHub") |
| `message` | String | User-friendly message explaining why email is needed |
| `error` | String or None | Error message if email validation failed |

Example usage:
```html
<form action="{{ action }}" method="{{ method }}">
    <input type="hidden" name="session" value="{{ session_id }}" />
    <p>{{ message }}</p>
    {% if error %}
        <p class="error">{{ error }}</p>
    {% endif %}
    <input type="email" name="email" required />
    <button type="submit">Continue</button>
</form>
```

## Advanced Configuration

### Multiple OAuth Providers

Multiple OAuth providers can be configured simultaneously using the ``provider`` parameter:

```python
app = (
    ActingWebApp(
        aw_type="urn:actingweb:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(
        provider="google",
        client_id="your-google-client-id",
        client_secret="your-google-client-secret",
        scope="openid email profile",
    )
    .with_oauth(
        provider="github",
        client_id="your-github-client-id",
        client_secret="your-github-client-secret",
        scope="read:user user:email",
    )
    .with_web_ui(enable=True)
)
```

When multiple providers are configured:

- The factory page (``/``) shows login buttons for all configured providers
- The ``/oauth/config`` endpoint returns all providers in its ``oauth_providers`` array
- Each OAuth callback identifies the correct provider via the ``provider`` field in the state parameter
- ``config.oauth`` still points to the first provider for backward compatibility
- Users typically log in via one provider; email-based linking allows the same user to use both providers

### Session Storage Architecture

OAuth sessions are automatically stored in the database using ActingWeb's attribute bucket system:

- **Storage Location**: `OAUTH2_SYSTEM_ACTOR` actor with bucket `oauth_sessions`
- **Persistence**: Database-backed for multi-container deployments
- **TTL**: 10 minutes (configurable via `_SESSION_TTL` constant)
- **Automatic Cleanup**: Expired sessions are automatically removed on access

No custom session storage implementation is needed - the default implementation handles distributed deployments automatically.

### Custom Session TTL

The default session TTL is 10 minutes. To change it:

```python
# In actingweb/oauth_session.py
_SESSION_TTL = 600  # Default: 10 minutes

# Override by modifying the module constant before use:
import actingweb.oauth_session
actingweb.oauth_session._SESSION_TTL = 1800  # 30 minutes
```

## Security Considerations

1. **Session Storage**: Sessions are automatically stored in the database using ActingWeb's attribute bucket system, providing persistence across multiple containers.

2. **Session TTL**: Sessions expire after 10 minutes to prevent token leakage. Adjust TTL based on your security requirements.

3. **HTTPS Required**: OAuth2 flows must use HTTPS in production (`proto="https://"`).

4. **State Parameter**: The library automatically includes CSRF protection via the OAuth2 state parameter.

5. **Email Validation**: The library validates that authenticated email matches the expected email from forms (when applicable).

## Testing

To test the OAuth login flow:

1. Configure test OAuth2 credentials (Google/GitHub OAuth app)
2. Set redirect_uri to your local development URL
3. Visit `http://localhost:5000/` (or your dev server)
4. Click "Login with Google/GitHub"
5. Complete OAuth flow
6. Verify actor creation and redirection

For testing email input flow with GitHub (HTML template):

1. Configure GitHub OAuth app
2. Set your GitHub email to private in settings
3. Complete OAuth flow
4. Verify redirect to `/oauth/email`
5. Enter email and verify actor creation
6. Check that `email_verification_required` hook fires
7. Click verification link (`/oauth/email?verify=<token>`) to complete

For testing email input flow with GitHub (SPA):

1. Configure GitHub OAuth app
2. Set your GitHub email to private in settings
3. Complete SPA OAuth flow
4. Verify redirect back to SPA with `?email_required=true&session=...`
5. POST email to `/oauth/email` with `Accept: application/json`
6. Check that `email_verification_required` hook fires
7. Verify `email_requires_verification: true` in JSON response

## Troubleshooting

### OAuth URLs Not Showing

- Check that `config.oauth` is properly configured
- Verify `config.ui = True` for template rendering
- Check that `client_id` and `client_secret` are set
- Inspect `template_values` in factory handler logs

### Email Form Not Appearing

- Check that `/oauth/email` route is registered (Flask/FastAPI integration does this automatically)
- Verify session has not expired (10-minute TTL)
- Check browser console for JavaScript errors
- Inspect template rendering errors in logs

### Actor Not Created After Email Input

- Check session storage logs for session retrieval
- Verify email format validation
- Check actor creation logs for errors
- Verify database connectivity

### Session Expired Error

- User took longer than 10 minutes to enter email
- Increase `_SESSION_TTL` or implement database-backed sessions
- Add user-friendly error message in template

## Migration from Traditional Flow

If your app currently uses traditional actor creation (email input only), you can add OAuth login alongside:

1. Keep existing `aw-root-factory.html` template
2. Add OAuth button section with conditional rendering:
   ```html
   {% if oauth_enabled %}
       <!-- OAuth buttons here -->
   {% endif %}

   <!-- Keep existing email form -->
   <form action="/" method="post">
       ...
   </form>
   ```
3. No changes needed to backend code
4. Users can choose between OAuth login or traditional email

Both flows will coexist and work independently.
