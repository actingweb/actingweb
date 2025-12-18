# Passphrase Login Feature Implementation Plan

**Date**: 2025-12-18
**Status**: Planning
**Author**: Claude Code

## Overview

Add an alternative login option to the ActingWeb login page that allows users to authenticate using their email (creator) and passphrase, without requiring OAuth2. This leverages the existing ActingWeb protocol's creator/passphrase authentication mechanism.

## Background

### Current Configuration
- `unique_creator=True` - Same email cannot create multiple actors
- `email_as_creator=True` - Email is used as the username (creator)

### Current Login Flow
1. User visits factory page (`GET /`)
2. User enters email in form
3. `POST /` with creator email
4. If actor exists → redirects to `/{actor_id}/www` (triggers OAuth2)
5. If new → creates actor, redirects to OAuth2

### Problem
There's no way to login using the ActingWeb native authentication (creator + passphrase) from the web UI. Users who have their passphrase cannot use it for browser-based access.

### Desired Flow
1. User visits factory page
2. User chooses "Login with Passphrase" option
3. User enters email + passphrase
4. System validates credentials
5. System creates session (SPA token)
6. User is redirected to `/www` with active session

## Implementation Phases

### Phase 1: Backend - Login Endpoint
**Goal**: Create endpoint to validate passphrase and issue session tokens

#### 1.1 Add Login Handler Method to Factory
**File**: `actingweb/handlers/factory.py`

Add a new method to handle passphrase-based login:

```python
def _handle_passphrase_login(self, creator: str, passphrase: str) -> bool:
    """Handle login with creator email and passphrase.

    Returns True if login successful (response set up for redirect),
    False if login failed (error response set).
    """
    from actingweb import actor
    from actingweb.oauth_session import get_oauth2_session_manager

    # Normalize email
    creator = creator.strip().lower()

    # Look up actor by creator
    existing_actor = actor.Actor(config=self.config)
    if not existing_actor.get_from_creator(creator):
        self.response.set_status(401, "Invalid credentials")
        return False

    # Validate passphrase (constant-time comparison)
    import hmac
    if not existing_actor.passphrase or not hmac.compare_digest(
        existing_actor.passphrase, passphrase
    ):
        self.response.set_status(401, "Invalid credentials")
        return False

    # Create SPA session tokens
    session_manager = get_oauth2_session_manager(self.config)
    tokens = session_manager.create_spa_tokens(
        actor_id=existing_actor.id,
        email=creator
    )

    # Set session cookie
    self._set_session_cookie(tokens["access_token"])

    # Redirect to /www
    self.response.set_redirect(f"/{existing_actor.id}/www")
    self.response.set_status(302, "Found")
    return True

def _set_session_cookie(self, token: str) -> None:
    """Set the OAuth session cookie."""
    cookie_settings = {
        "httponly": True,
        "secure": self.config.proto == "https://",
        "samesite": "Lax",
        "path": "/",
        "max_age": 3600  # 1 hour
    }
    self.response.set_cookie("oauth_token", token, **cookie_settings)
```

#### 1.2 Modify Factory POST Handler
**File**: `actingweb/handlers/factory.py`

Update `post()` method to detect and route passphrase login requests:

```python
def post(self):
    # ... existing body parsing code ...

    # Check if this is a passphrase login attempt
    login_mode = self.request.get("login_mode") or params.get("login_mode", "")

    if login_mode == "passphrase":
        passphrase = self.request.get("passphrase") or params.get("passphrase", "")
        if not creator or not passphrase:
            self.response.set_status(400, "Email and passphrase required")
            return
        self._handle_passphrase_login(creator, passphrase)
        return

    # ... rest of existing POST handling ...
```

#### 1.3 Update Flask Integration
**File**: `actingweb/interface/integrations/flask_integration.py`

Ensure the factory route can handle the new form fields (should work automatically with existing form handling).

- [ ] Task 1.1: Add `_handle_passphrase_login()` method
- [ ] Task 1.2: Add `_set_session_cookie()` helper method
- [ ] Task 1.3: Modify `post()` to detect `login_mode=passphrase`
- [ ] Task 1.4: Test basic login flow with curl/httpie

---

### Phase 2: Frontend - Login Page Template
**Goal**: Add passphrase login option to the factory page

#### 2.1 Update Factory Template
**File**: `tests/integration/templates/aw-root-factory.html`

Add a tabbed or toggle interface with two login options:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Login / Create Actor</title>
    <style>
        .login-container { max-width: 400px; margin: 40px auto; font-family: sans-serif; }
        .login-tabs { display: flex; margin-bottom: 20px; }
        .login-tab { flex: 1; padding: 10px; text-align: center; cursor: pointer;
                     border: 1px solid #ccc; background: #f5f5f5; }
        .login-tab.active { background: white; border-bottom: none; }
        .login-form { display: none; padding: 20px; border: 1px solid #ccc; border-top: none; }
        .login-form.active { display: block; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; }
        .form-group input { width: 100%; padding: 8px; box-sizing: border-box; }
        .btn { padding: 10px 20px; cursor: pointer; }
        .btn-primary { background: #007bff; color: white; border: none; }
        .oauth-buttons { margin-top: 15px; }
        .oauth-btn { display: block; padding: 10px; margin: 5px 0; text-align: center;
                     text-decoration: none; border-radius: 4px; }
        .oauth-google { background: #4285f4; color: white; }
        .oauth-github { background: #333; color: white; }
        .error { color: red; margin-bottom: 15px; }
        .divider { text-align: center; margin: 20px 0; color: #666; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>ActingWeb Login</h1>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <div class="login-tabs">
            <div class="login-tab active" onclick="showTab('oauth')">OAuth Login</div>
            <div class="login-tab" onclick="showTab('passphrase')">Passphrase Login</div>
        </div>

        <!-- OAuth Login Tab -->
        <div id="oauth-form" class="login-form active">
            {% if oauth_enabled %}
            <p>Sign in with your account:</p>
            <div class="oauth-buttons">
                {% for provider in oauth_providers %}
                <a href="{{ provider.url }}" class="oauth-btn oauth-{{ provider.name }}">
                    Login with {{ provider.display_name }}
                </a>
                {% endfor %}
            </div>
            <div class="divider">- or create new account -</div>
            {% endif %}

            <form action="/" method="post">
                <div class="form-group">
                    <label>Email:</label>
                    <input type="email" name="creator" required placeholder="your@email.com" />
                </div>
                <button type="submit" class="btn btn-primary">Create Account</button>
            </form>
        </div>

        <!-- Passphrase Login Tab -->
        <div id="passphrase-form" class="login-form">
            <p>Login with your email and passphrase:</p>
            <form action="/" method="post">
                <input type="hidden" name="login_mode" value="passphrase" />
                <div class="form-group">
                    <label>Email:</label>
                    <input type="email" name="creator" required placeholder="your@email.com" />
                </div>
                <div class="form-group">
                    <label>Passphrase:</label>
                    <input type="password" name="passphrase" required placeholder="Your passphrase" />
                </div>
                <button type="submit" class="btn btn-primary">Login</button>
            </form>
            <p style="margin-top: 15px; font-size: 0.9em; color: #666;">
                Your passphrase was shown when your account was created.
                If you've lost it, please contact support.
            </p>
        </div>
    </div>

    <script>
        function showTab(tab) {
            document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.login-form').forEach(f => f.classList.remove('active'));

            if (tab === 'oauth') {
                document.querySelector('.login-tab:first-child').classList.add('active');
                document.getElementById('oauth-form').classList.add('active');
            } else {
                document.querySelector('.login-tab:last-child').classList.add('active');
                document.getElementById('passphrase-form').classList.add('active');
            }
        }
    </script>
</body>
</html>
```

- [ ] Task 2.1: Update factory template with tabbed login interface
- [ ] Task 2.2: Style the forms appropriately
- [ ] Task 2.3: Add JavaScript for tab switching
- [ ] Task 2.4: Test UI renders correctly

---

### Phase 3: Actor Creation - Show Passphrase
**Goal**: Display passphrase to user when creating a new account

#### 3.1 Update/Create Success Template
**File**: `tests/integration/templates/aw-root-created.html`

Show the passphrase prominently so users can save it:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Account Created</title>
    <style>
        .container { max-width: 500px; margin: 40px auto; font-family: sans-serif; }
        .passphrase-box {
            background: #fff3cd; border: 1px solid #ffc107;
            padding: 20px; margin: 20px 0; border-radius: 4px;
        }
        .passphrase-value {
            font-family: monospace; font-size: 1.2em;
            background: white; padding: 10px; margin: 10px 0;
            border: 1px dashed #ccc; word-break: break-all;
        }
        .warning { color: #856404; font-weight: bold; }
        .btn { padding: 10px 20px; margin: 5px; cursor: pointer; }
        .btn-copy { background: #17a2b8; color: white; border: none; }
        .btn-continue { background: #28a745; color: white; border: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Account Created Successfully!</h1>

        <p>Your ActingWeb actor has been created.</p>

        <div class="passphrase-box">
            <p class="warning">IMPORTANT: Save your passphrase now!</p>
            <p>This is the only time your passphrase will be shown.
               You'll need it to log in without OAuth.</p>

            <div class="passphrase-value" id="passphrase">{{ passphrase }}</div>

            <button class="btn btn-copy" onclick="copyPassphrase()">Copy to Clipboard</button>
        </div>

        <p><strong>Email:</strong> {{ creator }}</p>
        <p><strong>Actor ID:</strong> {{ id }}</p>

        <a href="/{{ id }}/www" class="btn btn-continue">Continue to Dashboard</a>
    </div>

    <script>
        function copyPassphrase() {
            const text = document.getElementById('passphrase').innerText;
            navigator.clipboard.writeText(text).then(() => {
                alert('Passphrase copied to clipboard!');
            });
        }
    </script>
</body>
</html>
```

#### 3.2 Modify Factory to Show Passphrase Page
**File**: `actingweb/handlers/factory.py`

When creating a new actor via web form, show the passphrase:

```python
# In post() method, after successful actor creation for web forms:
if self.config.ui and not is_json:
    # For web UI, show the passphrase page
    self.response.template_values = {
        "id": myself.id,
        "creator": myself.creator,
        "passphrase": str(myself.passphrase),
    }
    # Template will be aw-root-created.html
    return
```

- [ ] Task 3.1: Update aw-root-created.html with passphrase display
- [ ] Task 3.2: Ensure factory shows created template (not redirect)
- [ ] Task 3.3: Add copy-to-clipboard functionality
- [ ] Task 3.4: Test new account creation flow

---

### Phase 4: Session Management Integration
**Goal**: Ensure passphrase login creates proper sessions compatible with existing auth

#### 4.1 Verify SPA Token Compatibility
**File**: `actingweb/oauth_session.py`

The `create_spa_tokens()` method should work for passphrase login. Verify:
- Token format is compatible with `/www` authentication
- Cookie name matches what `auth.py` expects
- Token TTL is appropriate

#### 4.2 Add Refresh Token Support (Optional)
For longer sessions, consider issuing refresh tokens:
- Store refresh token in separate cookie
- Add refresh endpoint or auto-refresh logic

- [ ] Task 4.1: Verify SPA token creation works for passphrase login
- [ ] Task 4.2: Test session persistence across page loads
- [ ] Task 4.3: Verify `/www` accepts the session token
- [ ] Task 4.4: (Optional) Add refresh token support

---

### Phase 5: Error Handling & Security
**Goal**: Robust error handling and security hardening

#### 5.1 Error Messages
Update templates to show login errors:
- Invalid credentials
- Account not found
- Rate limiting messages

#### 5.2 Rate Limiting (Recommended)
Add rate limiting to prevent brute force attacks:

```python
# Simple in-memory rate limiter (production should use Redis/similar)
from collections import defaultdict
from time import time

_login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes

def _check_rate_limit(self, identifier: str) -> bool:
    """Return True if rate limit exceeded."""
    now = time()
    attempts = _login_attempts[identifier]
    # Remove old attempts
    attempts[:] = [t for t in attempts if now - t < WINDOW_SECONDS]
    if len(attempts) >= MAX_ATTEMPTS:
        return True
    attempts.append(now)
    return False
```

#### 5.3 Security Considerations
- [x] Use constant-time comparison for passphrase (hmac.compare_digest)
- [ ] Add rate limiting
- [ ] Log failed login attempts
- [ ] Consider account lockout after N failures
- [ ] Ensure HTTPS in production (cookie secure flag)

- [ ] Task 5.1: Add rate limiting to login endpoint
- [ ] Task 5.2: Add error message display to templates
- [ ] Task 5.3: Add logging for security events
- [ ] Task 5.4: Test error scenarios

---

### Phase 6: Testing
**Goal**: Comprehensive test coverage

#### 6.1 Unit Tests
**File**: `tests/test_factory.py` (new or existing)

```python
def test_passphrase_login_success():
    """Test successful login with email and passphrase."""
    pass

def test_passphrase_login_wrong_password():
    """Test login with incorrect passphrase returns 401."""
    pass

def test_passphrase_login_nonexistent_user():
    """Test login with unknown email returns 401."""
    pass

def test_passphrase_login_missing_fields():
    """Test login with missing fields returns 400."""
    pass
```

#### 6.2 Integration Tests
**File**: `tests/integration/test_passphrase_login.py`

```python
def test_full_passphrase_login_flow(actor_factory, http_client):
    """Test complete flow: create actor, login with passphrase, access /www."""
    pass

def test_passphrase_login_creates_valid_session(actor_factory, http_client):
    """Test that passphrase login creates working session cookie."""
    pass

def test_login_page_shows_both_options(http_client):
    """Test that login page renders both OAuth and passphrase options."""
    pass
```

- [ ] Task 6.1: Write unit tests for login handler
- [ ] Task 6.2: Write integration tests for full flow
- [ ] Task 6.3: Test edge cases (empty fields, special characters, etc.)
- [ ] Task 6.4: Run full test suite, ensure no regressions

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `actingweb/handlers/factory.py` | Modify | Add passphrase login handling |
| `tests/integration/templates/aw-root-factory.html` | Modify | Add login UI with tabs |
| `tests/integration/templates/aw-root-created.html` | Modify | Show passphrase on creation |
| `tests/test_factory.py` | Create/Modify | Unit tests |
| `tests/integration/test_passphrase_login.py` | Create | Integration tests |

## Success Criteria

1. **Login Works**: Users can login with email + passphrase from web UI
2. **Session Created**: Login creates valid SPA session token
3. **WWW Access**: After login, user can access `/{actor_id}/www`
4. **New Users See Passphrase**: Account creation shows passphrase clearly
5. **OAuth Still Works**: Existing OAuth2 login flow unchanged
6. **Tests Pass**: All new and existing tests pass
7. **Security**: Rate limiting, constant-time comparison, secure cookies

## Dependencies

- Existing SPA token infrastructure in `oauth_session.py`
- Existing basic auth validation in `auth.py`
- Template rendering in Flask integration

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Passphrase brute force | Rate limiting, logging, optional lockout |
| User loses passphrase | Document recovery process, consider reset feature |
| Session token incompatibility | Reuse existing SPA token code from OAuth flow |
| Breaking OAuth flow | Comprehensive testing, feature flag if needed |

## Open Questions

1. **Passphrase Recovery**: Should we add a "forgot passphrase" flow? (Requires email verification)
2. **Remember Me**: Should we offer longer sessions with "remember me" checkbox?
3. **Feature Flag**: Should this be behind a config toggle initially?

## Next Steps

1. Review this plan
2. Implement Phase 1 (Backend)
3. Implement Phase 2 (Frontend)
4. Implement Phase 3 (Passphrase Display)
5. Test thoroughly
6. Document the feature
