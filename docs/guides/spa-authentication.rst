========================
SPA Authentication Guide
========================

This guide covers OAuth2 authentication for Single Page Applications (SPAs) using ActingWeb. SPAs require special handling because they run entirely in the browser and cannot securely store client secrets.

.. contents::
   :local:
   :depth: 2

Understanding ActingWeb's Two OAuth2 Roles
------------------------------------------

ActingWeb operates in **two distinct OAuth2 roles** that use different endpoints:

**1. ActingWeb as OAuth2 Client (External Login)**

When users log in via Google, GitHub, or other external providers:

- ActingWeb acts as the OAuth2 **client**
- Google/GitHub are the OAuth2 **servers** (authorization servers)
- User authenticates WITH Google/GitHub, then ActingWeb creates/updates an actor

Endpoints:

- ``/oauth/spa/authorize`` - Initiate login with Google/GitHub
- ``/oauth/spa/token`` - Refresh tokens from external provider
- ``/oauth/callback`` - Receive authorization code from Google/GitHub

**2. ActingWeb as OAuth2 Server (MCP Authentication)**

When MCP clients (ChatGPT, Claude, Cursor) connect to ActingWeb:

- ActingWeb acts as the OAuth2 **server** (authorization server)
- MCP clients are the OAuth2 **clients**
- MCP client authenticates TO ActingWeb to access tools/resources

Endpoints:

- ``/oauth/authorize`` - MCP client requests authorization
- ``/oauth/token`` - MCP client exchanges code for token
- ``/oauth/register`` - MCP client dynamic registration

**Why This Matters**

The ``/oauth/authorize`` and ``/oauth/spa/authorize`` endpoints look similar but serve
completely different purposes:

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Aspect
     - ``/oauth/spa/authorize``
     - ``/oauth/authorize``
   * - ActingWeb Role
     - OAuth2 Client
     - OAuth2 Server
   * - Purpose
     - User logs in via Google/GitHub
     - MCP client authenticates to ActingWeb
   * - Who authenticates
     - User → Google/GitHub
     - MCP client → ActingWeb
   * - Result
     - Actor created/updated in ActingWeb
     - MCP client gets access token

Overview
--------

ActingWeb provides dedicated SPA OAuth2 endpoints that:

- Return pure JSON responses (no HTML templates)
- Support server-managed PKCE (Proof Key for Code Exchange)
- Offer multiple token delivery modes (JSON, cookies, hybrid)
- Implement refresh token rotation for security
- Include CORS headers for cross-origin requests

Token Architecture
------------------

**Important**: ActingWeb generates its own session tokens rather than passing through
OAuth provider tokens (Google/GitHub) directly. This provides several benefits:

1. **Performance**: No network calls to validate tokens on every API request
2. **Reliability**: No dependency on OAuth provider availability after initial auth
3. **Security**: OAuth provider tokens never exposed to frontend JavaScript
4. **Control**: Custom token expiry, permissions, and rotation policies

**How It Works:**

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────┐
   │                    OAuth Callback                           │
   │  1. Validate Google/GitHub token (once)                     │
   │  2. Generate ActingWeb access token                         │
   │  3. Store token in session manager                          │
   │  4. Return ActingWeb token (not Google token)               │
   └─────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┴────────────────────┐
         ▼                                         ▼
   ┌─────────────────────┐                 ┌─────────────────────┐
   │        SPA          │                 │       /www          │
   │  Token in memory    │                 │  Token in cookie    │
   │  Auth header        │                 │  HttpOnly cookie    │
   └─────────────────────┘                 └─────────────────────┘
         │                                         │
         └────────────────────┬────────────────────┘
                              ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                    Request Validation                       │
   │  - Session manager lookup (fast, no network)                │
   │  - Falls back to OAuth provider validation (legacy)         │
   └─────────────────────────────────────────────────────────────┘

**Token Lifecycle:**

- **Access tokens**: 1-hour TTL, stored in session manager
- **Refresh tokens**: 2-week TTL, supports rotation
- Both token types are validated against ActingWeb's session manager, not OAuth providers

This architecture applies to both SPAs (tokens in memory) and traditional /www apps
(tokens in HttpOnly cookies).

Key Endpoints
~~~~~~~~~~~~~

Most OAuth endpoints are unified at ``/oauth/*`` and work for both SPAs and traditional web apps.
Only ``/oauth/spa/authorize`` and ``/oauth/spa/token`` remain separate because they serve a different
OAuth role (ActingWeb as OAuth *client* to Google/GitHub) than the MCP OAuth2 endpoints
(ActingWeb as OAuth *server*).

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/oauth/config``
     - GET
     - Get OAuth configuration and available providers
   * - ``/oauth/spa/authorize``
     - POST
     - Initiate external OAuth flow (ActingWeb as OAuth client)
   * - ``/oauth/callback``
     - GET
     - Handle OAuth callback (auto-detects SPA mode via state param)
   * - ``/oauth/spa/token``
     - POST
     - Token refresh with rotation for external provider tokens
   * - ``/oauth/revoke``
     - POST
     - Revoke access and/or refresh tokens
   * - ``/oauth/session``
     - GET
     - Check current session status
   * - ``/oauth/logout``
     - POST/GET
     - Logout and clear all tokens (returns JSON when Accept: application/json)

Getting Started
---------------

1. Get OAuth Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

Before initiating login, fetch the available OAuth providers:

.. code-block:: javascript

   const response = await fetch('/oauth/config');
   const config = await response.json();

   // config structure:
   // {
   //   "oauth_enabled": true,
   //   "oauth_providers": [
   //     {
   //       "name": "google",
   //       "display_name": "Google",
   //       "authorization_endpoint": "..."
   //     }
   //   ],
   //   "pkce_supported": true,
   //   "token_delivery_modes": ["json", "cookie", "hybrid"],
   //   "endpoints": {...}
   // }
   //
   // Note: trust_types are NOT included here. Trust types are only
   // relevant for MCP client authorization (ActingWeb as OAuth server),
   // not for user login (ActingWeb as OAuth client).

2. Initiate OAuth Flow
~~~~~~~~~~~~~~~~~~~~~~

Start the OAuth flow with optional server-managed PKCE.

**For User Login** (no trust relationship):

.. code-block:: javascript

   const authResponse = await fetch('/oauth/spa/authorize', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({
           provider: 'google',
           // NO trust_type = simple user login
           redirect_uri: window.location.origin + '/callback',
           pkce: 'server',  // Let server manage PKCE
           token_delivery: 'json',  // Return tokens in JSON
           return_path: '/app'  // Where to redirect after auth (default: /app)
       })
   });

   const auth = await authResponse.json();

   // Redirect to OAuth provider
   window.location.href = auth.authorization_url;

The ``return_path`` parameter specifies where to redirect after successful authentication.
It will be prepended with the actor ID: ``/{actor_id}{return_path}``. You can also use
the ``{actor_id}`` placeholder for custom paths: ``return_path: '/{actor_id}/dashboard'``.

**For MCP Client Authorization** (creates trust relationship):

If your SPA is an MCP client that needs to establish a trust relationship
with a specific permission level, include the ``trust_type`` parameter:

.. code-block:: javascript

   const authResponse = await fetch('/oauth/spa/authorize', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({
           provider: 'google',
           trust_type: 'mcp_client',  // Creates trust relationship with this type
           redirect_uri: window.location.origin + '/callback',
           pkce: 'server',
           token_delivery: 'json'
       })
   });

.. note::

   **trust_type parameter:**

   - **Omitted or null**: Simple user login. Creates/looks up actor, no trust relationship.
   - **Specified (e.g., "mcp_client")**: MCP authorization. Creates actor AND trust relationship
     with the specified permission level.

3. Handle Callback
~~~~~~~~~~~~~~~~~~

The OAuth callback flow works in two stages for SPAs:

**Stage 1: Browser Redirect from OAuth Provider**

After the user authenticates with Google/GitHub, the OAuth provider redirects the browser
to ``/oauth/callback``. When the server detects SPA mode (via ``spa_mode: true`` in state),
it redirects the browser to your SPA's ``redirect_uri`` (e.g., ``/callback``) with the
authorization code and state preserved:

.. code-block:: text

   Google → /oauth/callback?code=xxx&state={"spa_mode":true,...}
                  ↓ (server detects SPA mode, redirects)
          /callback?code=xxx&state={"spa_mode":true,...}

**Stage 2: SPA Exchanges Code for Tokens**

Your SPA callback page then calls the server to exchange the code for tokens:

.. code-block:: javascript

   // On /callback page
   const params = new URLSearchParams(window.location.search);

   // Call /oauth/callback with Accept: application/json to get tokens
   const tokens = await fetch('/oauth/callback?' + params.toString(), {
       headers: { 'Accept': 'application/json' }  // Required for JSON response
   }).then(r => r.json());

   if (tokens.success) {
       // Store access token (in memory for security)
       setAccessToken(tokens.access_token);

       // Navigate to app - redirect_url contains the return_path
       window.location.href = tokens.redirect_url;  // e.g., /abc123/app
   }

.. note::

   The ``Accept: application/json`` header is required in Stage 2. Without it,
   the server will perform another redirect (Stage 1 behavior).

Token Delivery Modes
--------------------

ActingWeb supports three token delivery modes to accommodate different security requirements:

JSON Mode (Default)
~~~~~~~~~~~~~~~~~~~

Returns all tokens in the JSON response. Best for:

- SPAs that store tokens in memory
- Development and testing
- Maximum flexibility

.. code-block:: javascript

   {
       "success": true,
       "access_token": "eyJhbGciOiJIUzI1NiIs...",
       "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2g...",
       "token_type": "Bearer",
       "expires_in": 3600,
       "actor_id": "abc123"
   }

Cookie Mode
~~~~~~~~~~~

Stores all tokens in HttpOnly cookies. Best for:

- Maximum XSS protection
- Traditional session-based apps
- Backend-for-frontend (BFF) patterns

.. code-block:: javascript

   // Request with cookie mode
   const auth = await fetch('/oauth/spa/authorize', {
       method: 'POST',
       body: JSON.stringify({
           provider: 'google',
           token_delivery: 'cookie'
       })
   });

   // Response - no tokens in body, set via cookies
   // {
   //     "success": true,
   //     "actor_id": "abc123",
   //     "token_delivery": "cookie"
   // }

Hybrid Mode
~~~~~~~~~~~

Access token in JSON, refresh token in HttpOnly cookie. Best for:

- Balance of security and convenience
- SPAs that need immediate access to access tokens
- Protecting long-lived refresh tokens from XSS

.. code-block:: javascript

   // Request with hybrid mode
   const auth = await fetch('/oauth/spa/authorize', {
       method: 'POST',
       body: JSON.stringify({
           provider: 'google',
           token_delivery: 'hybrid'
       })
   });

   // Response - access token in body, refresh in cookie
   // {
   //     "success": true,
   //     "access_token": "eyJhbGciOiJIUzI1NiIs...",
   //     "token_type": "Bearer",
   //     "expires_in": 3600,
   //     "actor_id": "abc123",
   //     "token_delivery": "hybrid"
   // }

PKCE Support
------------

PKCE (Proof Key for Code Exchange) is essential for SPAs because they cannot securely store client secrets. ActingWeb supports two PKCE modes:

Server-Managed PKCE (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The server generates and manages the PKCE challenge/verifier pair:

.. code-block:: javascript

   const auth = await fetch('/oauth/spa/authorize', {
       method: 'POST',
       body: JSON.stringify({
           provider: 'google',
           pkce: 'server'  // Server generates PKCE
       })
   });

   // Response includes PKCE info
   // {
   //     "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
   //     "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
   //     "code_challenge_method": "S256",
   //     "pkce_managed_by": "server"
   // }

Client-Managed PKCE
~~~~~~~~~~~~~~~~~~~

Generate PKCE client-side for full control:

.. code-block:: javascript

   // Generate PKCE client-side
   function generateCodeVerifier() {
       const array = new Uint8Array(64);
       crypto.getRandomValues(array);
       return btoa(String.fromCharCode.apply(null, array))
           .replace(/\+/g, '-')
           .replace(/\//g, '_')
           .replace(/=/g, '');
   }

   async function generateCodeChallenge(verifier) {
       const encoder = new TextEncoder();
       const data = encoder.encode(verifier);
       const digest = await crypto.subtle.digest('SHA-256', data);
       return btoa(String.fromCharCode.apply(null, new Uint8Array(digest)))
           .replace(/\+/g, '-')
           .replace(/\//g, '_')
           .replace(/=/g, '');
   }

   // Store verifier in session
   const verifier = generateCodeVerifier();
   sessionStorage.setItem('pkce_verifier', verifier);

   const challenge = await generateCodeChallenge(verifier);

   // Send challenge to server
   const auth = await fetch('/oauth/spa/authorize', {
       method: 'POST',
       body: JSON.stringify({
           provider: 'google',
           pkce: 'client',
           code_challenge: challenge,
           code_challenge_method: 'S256'
       })
   });

Token Refresh with Rotation
---------------------------

ActingWeb implements refresh token rotation for enhanced security:

- Each refresh token can only be used once
- Token exchange returns both new access AND refresh tokens
- Reusing an old refresh token revokes all tokens (theft detection)

.. code-block:: javascript

   async function refreshTokens() {
       const response = await fetch('/oauth/spa/token', {
           method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify({
               grant_type: 'refresh_token',
               refresh_token: getStoredRefreshToken(),
               token_delivery: 'json'
           })
       });

       const data = await response.json();

       if (data.success) {
           // IMPORTANT: Store BOTH new tokens (rotation)
           setAccessToken(data.access_token);
           setRefreshToken(data.refresh_token);  // New refresh token!
       } else {
           // Refresh failed - user must re-authenticate
           redirectToLogin();
       }
   }

Session Management
------------------

Check Session Status
~~~~~~~~~~~~~~~~~~~~

.. code-block:: javascript

   async function checkSession() {
       const response = await fetch('/oauth/session', {
           headers: {
               'Authorization': `Bearer ${getAccessToken()}`
           }
       });

       const session = await response.json();

       if (session.authenticated) {
           console.log(`Logged in as actor ${session.actor_id}`);
           console.log(`Token expires in ${session.expires_in} seconds`);
       } else {
           // Not authenticated or token expired
           redirectToLogin();
       }
   }

Logout
~~~~~~

.. code-block:: javascript

   async function logout() {
       const response = await fetch('/oauth/logout', {
           method: 'POST',
           headers: {
               'Authorization': `Bearer ${getAccessToken()}`
           }
       });

       const result = await response.json();

       // Clear local token storage
       clearTokens();

       // Redirect to home
       window.location.href = result.redirect_url;
   }

Token Revocation
~~~~~~~~~~~~~~~~

Explicitly revoke tokens (e.g., when user logs out from another device):

.. code-block:: javascript

   async function revokeToken(token, tokenType = 'access_token') {
       await fetch('/oauth/revoke', {
           method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify({
               token: token,
               token_type_hint: tokenType
           })
       });
   }

Complete Example
----------------

Here's a complete SPA authentication flow:

.. code-block:: javascript

   // auth.js - SPA Authentication Module

   class AuthManager {
       constructor() {
           this.accessToken = null;
           this.refreshToken = null;
           this.expiresAt = null;
       }

       async getConfig() {
           const response = await fetch('/oauth/config');
           return response.json();
       }

       async login(provider = 'google') {
           // Store return URL
           sessionStorage.setItem('auth_return_url', window.location.pathname);

           // Initiate OAuth with server-managed PKCE
           const response = await fetch('/oauth/spa/authorize', {
               method: 'POST',
               headers: { 'Content-Type': 'application/json' },
               body: JSON.stringify({
                   provider: provider,
                   redirect_uri: window.location.origin + '/callback',
                   pkce: 'server',
                   token_delivery: 'hybrid'  // Best balance of security
               })
           });

           const auth = await response.json();

           // Redirect to OAuth provider
           window.location.href = auth.authorization_url;
       }

       async handleCallback() {
           const params = new URLSearchParams(window.location.search);

           if (params.get('error')) {
               throw new Error(params.get('error_description') || 'OAuth failed');
           }

           // OAuth provider redirects here; endpoint auto-detects SPA mode via state
           const response = await fetch('/oauth/callback?' + params.toString());
           const tokens = await response.json();

           if (!tokens.success) {
               throw new Error(tokens.message || 'Token exchange failed');
           }

           // Store access token in memory (hybrid mode)
           this.accessToken = tokens.access_token;
           this.expiresAt = tokens.expires_at;

           // Refresh token is in HttpOnly cookie (hybrid mode)

           // Return to original URL
           const returnUrl = sessionStorage.getItem('auth_return_url') || '/';
           sessionStorage.removeItem('auth_return_url');

           return { success: true, returnUrl };
       }

       async refreshTokens() {
           // With hybrid mode, refresh token is in cookie
           const response = await fetch('/oauth/spa/token', {
               method: 'POST',
               headers: { 'Content-Type': 'application/json' },
               credentials: 'include',  // Include cookies
               body: JSON.stringify({
                   grant_type: 'refresh_token',
                   token_delivery: 'hybrid'
               })
           });

           const data = await response.json();

           if (data.success) {
               this.accessToken = data.access_token;
               this.expiresAt = data.expires_at;
               return true;
           }

           return false;
       }

       async authenticatedFetch(url, options = {}) {
           // Check if token needs refresh (5 min buffer)
           if (this.expiresAt && Date.now() / 1000 > this.expiresAt - 300) {
               const refreshed = await this.refreshTokens();
               if (!refreshed) {
                   throw new Error('Session expired');
               }
           }

           return fetch(url, {
               ...options,
               headers: {
                   ...options.headers,
                   'Authorization': `Bearer ${this.accessToken}`
               }
           });
       }

       async logout() {
           await fetch('/oauth/spa/logout', {
               method: 'POST',
               headers: {
                   'Authorization': `Bearer ${this.accessToken}`
               },
               credentials: 'include'
           });

           this.accessToken = null;
           this.expiresAt = null;

           window.location.href = '/';
       }

       isAuthenticated() {
           return !!this.accessToken && (!this.expiresAt || Date.now() / 1000 < this.expiresAt);
       }
   }

   // Usage
   const auth = new AuthManager();

   // On login button click
   document.getElementById('login-btn').onclick = () => auth.login('google');

   // On callback page
   if (window.location.pathname === '/callback') {
       auth.handleCallback()
           .then(result => window.location.href = result.returnUrl)
           .catch(err => alert('Login failed: ' + err.message));
   }

Security Best Practices
-----------------------

Token Storage
~~~~~~~~~~~~~

**Recommended**: Store access tokens in memory (JavaScript closure or class property)

.. code-block:: javascript

   // GOOD: Token in memory
   class TokenManager {
       #accessToken = null;

       setToken(token) {
           this.#accessToken = token;
       }

       getToken() {
           return this.#accessToken;
       }
   }

   // AVOID: Token in localStorage (vulnerable to XSS)
   // localStorage.setItem('access_token', token);  // Don't do this!

CORS Configuration
~~~~~~~~~~~~~~~~~~

For production, configure specific allowed origins:

.. code-block:: python

   app = (
       ActingWebApp(...)
       .with_spa_cors_origins([
           'https://myapp.example.com',
           'https://staging.myapp.example.com'
       ])
   )

HTTPS Required
~~~~~~~~~~~~~~

Always use HTTPS in production. Cookie-based tokens require ``Secure`` flag:

.. code-block:: python

   app = ActingWebApp(
       ...
       proto='https://'  # Required for secure cookies
   )

Content Security Policy
~~~~~~~~~~~~~~~~~~~~~~~

Add CSP headers to prevent XSS:

.. code-block:: http

   Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'

Alternative: Factory JSON API
-----------------------------

For simpler integrations, the factory endpoint also supports JSON:

.. code-block:: javascript

   // Get OAuth config from factory
   const config = await fetch('/?format=json', {
       headers: { 'Accept': 'application/json' }
   }).then(r => r.json());

   // config includes all OAuth endpoints and providers

API Reference
-------------

GET /oauth/config
~~~~~~~~~~~~~~~~~

Returns OAuth configuration.

**Response:**

.. code-block:: json

   {
       "oauth_enabled": true,
       "oauth_providers": [
           {
               "name": "google",
               "display_name": "Google",
               "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"
           }
       ],
       "pkce_supported": true,
       "pkce_methods": ["S256"],
       "spa_mode_supported": true,
       "token_delivery_modes": ["json", "cookie", "hybrid"],
       "refresh_token_rotation": true,
       "endpoints": {...}
   }

.. note::

   Trust types are NOT included in this response. Trust types are only relevant
   for MCP client authorization (ActingWeb as OAuth server), not for user login
   (ActingWeb as OAuth client). For MCP authorization, use ``/oauth/authorize``.

POST /oauth/spa/authorize
~~~~~~~~~~~~~~~~~~~~~~~~~

Initiate OAuth flow for SPA.

**Request Body:**

.. code-block:: json

   {
       "provider": "google",
       "trust_type": "mcp_client",
       "redirect_uri": "https://myapp.example.com/callback",
       "return_path": "/app",
       "pkce": "server",
       "token_delivery": "json"
   }

**Parameters:**

- ``provider``: OAuth provider name (``google``, ``github``)
- ``trust_type``: (Optional) Trust type for MCP authorization. Omit for simple user login.
- ``redirect_uri``: Where OAuth provider should redirect (your SPA callback page)
- ``return_path``: (Optional) Final redirect path after auth. Default: ``/app``.
  Prepended with actor ID: ``/{actor_id}{return_path}``.
  Supports ``{actor_id}`` placeholder: ``/{actor_id}/dashboard``.
- ``pkce``: ``server`` (recommended) or ``client``
- ``token_delivery``: ``json``, ``cookie``, or ``hybrid``

**Response:**

.. code-block:: json

   {
       "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
       "state": "...",
       "code_challenge": "...",
       "code_challenge_method": "S256",
       "pkce_managed_by": "server"
   }

GET /oauth/callback
~~~~~~~~~~~~~~~~~~~

Handle OAuth callback. Auto-detects SPA mode via ``spa_mode: true`` in state parameter.

**Behavior:**

- **Browser navigation** (no ``Accept: application/json`` header):
  Redirects to the SPA's ``redirect_uri`` with code and state preserved.
- **Fetch with JSON** (``Accept: application/json`` header):
  Returns JSON response with tokens.

**Query Parameters:**

- ``code``: Authorization code from OAuth provider
- ``state``: State parameter for CSRF protection

**Response (JSON mode):**

.. code-block:: json

   {
       "success": true,
       "actor_id": "abc123",
       "email": "user@example.com",
       "access_token": "...",
       "refresh_token": "...",
       "token_type": "Bearer",
       "expires_in": 3600,
       "expires_at": 1699876543,
       "redirect_url": "/abc123/app"
   }

The ``redirect_url`` is constructed from the ``return_path`` parameter passed during
authorization (default: ``/app``), prepended with the actor ID.

POST /oauth/spa/token
~~~~~~~~~~~~~~~~~~~~~

Token exchange and refresh with rotation.

**Request Body (Refresh):**

.. code-block:: json

   {
       "grant_type": "refresh_token",
       "refresh_token": "...",
       "token_delivery": "json"
   }

**Response:**

.. code-block:: json

   {
       "success": true,
       "access_token": "new_access_token",
       "refresh_token": "new_refresh_token",
       "token_type": "Bearer",
       "expires_in": 3600,
       "refresh_token_expires_in": 1209600
   }

POST /oauth/revoke
~~~~~~~~~~~~~~~~~~~~~~

Revoke tokens.

**Request Body:**

.. code-block:: json

   {
       "token": "token_to_revoke",
       "token_type_hint": "access_token"
   }

**Response:**

.. code-block:: json

   {
       "success": true,
       "message": "Token revoked successfully"
   }

GET /oauth/session
~~~~~~~~~~~~~~~~~~~~~~

Check session status.

**Headers:**

- ``Authorization: Bearer <access_token>``

**Response (Authenticated):**

.. code-block:: json

   {
       "authenticated": true,
       "actor_id": "abc123",
       "identifier": "user@example.com",
       "expires_at": 1699876543,
       "expires_in": 3245
   }

**Response (Not Authenticated):**

.. code-block:: json

   {
       "authenticated": false,
       "message": "No active session"
   }

POST /oauth/logout
~~~~~~~~~~~~~~~~~~~~~~

Logout and clear session.

**Headers:**

- ``Authorization: Bearer <access_token>`` (optional)

**Response:**

.. code-block:: json

   {
       "success": true,
       "message": "Logged out successfully",
       "redirect_url": "/"
   }

Troubleshooting
---------------

"PKCE verification failed"
~~~~~~~~~~~~~~~~~~~~~~~~~~

If using client-managed PKCE, ensure the code verifier is stored and sent correctly:

.. code-block:: javascript

   // Store verifier BEFORE redirect
   sessionStorage.setItem('pkce_verifier', verifier);

   // Retrieve AFTER callback
   const verifier = sessionStorage.getItem('pkce_verifier');

"Refresh token already used"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This indicates refresh token reuse, which could mean:

1. Concurrent refresh requests - serialize refresh calls
2. Token theft - all tokens were revoked for security

.. code-block:: javascript

   // Serialize refresh requests
   let refreshPromise = null;

   async function safeRefresh() {
       if (refreshPromise) return refreshPromise;

       refreshPromise = refreshTokens();
       try {
           return await refreshPromise;
       } finally {
           refreshPromise = null;
       }
   }

"CORS error"
~~~~~~~~~~~~

Ensure your SPA origin is allowed and credentials are included:

.. code-block:: javascript

   fetch('/oauth/spa/token', {
       method: 'POST',
       credentials: 'include',  // Required for cookies
       headers: {
           'Content-Type': 'application/json'
       }
   });

Migration from Standard OAuth
-----------------------------

If migrating from standard OAuth to SPA endpoints:

1. Replace redirect-based callbacks with JSON responses
2. Add PKCE to authorization requests
3. Implement token refresh with rotation
4. Update token storage from cookies/localStorage to memory

.. code-block:: javascript

   // Before: Standard OAuth with redirect (returns HTML)
   window.location.href = '/oauth/callback?code=...';

   // After: SPA OAuth with JSON (same endpoint, auto-detects via state param)
   const tokens = await fetch('/oauth/callback?code=...&state={"spa_mode":true,...}')
       .then(r => r.json());
