ActingWeb Authentication System
===============================

This document describes the comprehensive OAuth2 authentication system in ActingWeb, including support for multiple providers like Google and GitHub.

Overview
========

ActingWeb's authentication system provides a unified, provider-agnostic OAuth2 implementation that supports multiple authentication providers. The system uses the oauthlib library as the standard OAuth2 implementation and consolidates all OAuth2 functionality into core ActingWeb modules.

**Key Features:**

- **Multi-Provider Support**: Google OAuth2, GitHub OAuth2, and extensible to other providers
- **Multiple Authentication Methods**: Web sessions (cookies), Bearer tokens (API), and Basic auth (legacy)
- **Framework Agnostic**: Consistent behavior across FastAPI and Flask integrations
- **MCP Integration**: Full OAuth2 support for Model Context Protocol endpoints
- **Security**: CSRF protection, secure token storage, and privacy-respecting email handling

Architecture
============

Core Components
---------------

The authentication system is built around several key components:

**OAuth2Provider Base Class** (``actingweb/oauth2.py``)
    Base class for all OAuth2 provider implementations. Handles common OAuth2 configuration and validation.

**OAuth2Authenticator Class** (``actingweb/oauth2.py``)
    Main authenticator class that handles the complete OAuth2 flow using oauthlib. Supports:
    
    - Authorization URL generation
    - Authorization code exchange for tokens
    - Token validation and refresh
    - User information retrieval
    - Actor lookup/creation based on OAuth2 identity

**Provider-Specific Classes**
    - ``GoogleOAuth2Provider``: Google-specific OAuth2 configuration
    - ``GitHubOAuth2Provider``: GitHub-specific OAuth2 configuration and special handling

Authentication Methods
======================

Web Session Authentication
---------------------------

For interactive web users, ActingWeb uses session cookies:

1. User visits a protected endpoint (e.g., ``/``, ``/<actor_id>/www``, ``/mcp``)
2. If not authenticated, redirected to OAuth2 provider
3. After successful authentication, a secure session cookie is set
4. Subsequent requests use the cookie for authentication

**Cookie Configuration:**
    - Name: ``oauth_token``
    - Max Age: 2 weeks (1209600 seconds)
    - Secure: HTTPS only
    - Path: ``/`` (site-wide)

Bearer Token Authentication
---------------------------

For API clients and actor-to-actor communication:

.. code-block:: bash

    curl -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
         https://yourdomain.com/mcp

**Supported Endpoints:**
    - ``/mcp`` - Model Context Protocol
    - Actor-specific API endpoints
    - Any endpoint requiring authentication

Basic Authentication (Legacy)
------------------------------

Legacy Basic authentication is maintained for backward compatibility:

.. code-block:: bash

    curl -u username:password https://yourdomain.com/endpoint

Provider Implementations
========================

Google OAuth2 Provider
-----------------------

**Configuration:**

.. code-block:: python

    config.oauth = {
        "client_id": "your_google_client_id",
        "client_secret": "your_google_client_secret"
    }
    config.oauth2_provider = "google"  # Optional: default provider

**Endpoints:**
    - Auth URI: ``https://accounts.google.com/o/oauth2/v2/auth``
    - Token URI: ``https://oauth2.googleapis.com/token``
    - UserInfo URI: ``https://www.googleapis.com/oauth2/v2/userinfo``
    - Scope: ``openid email profile``

**Features:**
    - Refresh token support
    - Standard OpenID Connect flow
    - Public email addresses

GitHub OAuth2 Provider
-----------------------

**Configuration:**

.. code-block:: python

    config.oauth = {
        "client_id": "your_github_client_id",
        "client_secret": "your_github_client_secret"
    }
    config.oauth2_provider = "github"

**Endpoints:**
    - Auth URI: ``https://github.com/login/oauth/authorize``
    - Token URI: ``https://github.com/login/oauth/access_token``
    - UserInfo URI: ``https://api.github.com/user``
    - Scope: ``user:email``

**GitHub-Specific Features:**
    - **User-Agent Header**: Required for all GitHub API requests
    - **JSON Accept Header**: GitHub OAuth2 endpoints require ``Accept: application/json``
    - **No Refresh Tokens**: GitHub doesn't support OAuth2 refresh tokens
    - **Private Email Handling**: Special logic for users with private email addresses

**Email Handling:**
    GitHub users may have private email addresses. The system provides multiple strategies:

    1. Using public email if available (immediate login)
    2. Fetching verified emails via GitHub's emails API (dropdown selection)
    3. Manual email input with verification link (see Email Verification below)
    4. Provider ID mode: using stable GitHub user ID as identifier (no email required)

GitHub App Setup
----------------

1. Create a GitHub OAuth App at https://github.com/settings/applications/new
2. Set Authorization callback URL to: ``https://yourdomain.com/oauth/callback``
3. Copy the Client ID and Client Secret to your configuration
4. Ensure your app requests the ``user:email`` scope

Factory Functions
=================

The system provides several factory functions for creating authenticators:

**Provider-Specific Factories:**

.. code-block:: python

    from actingweb.oauth2 import create_google_authenticator, create_github_authenticator
    
    # Create Google OAuth2 authenticator
    google_auth = create_google_authenticator(config)
    
    # Create GitHub OAuth2 authenticator
    github_auth = create_github_authenticator(config)

**Generic Factory with Auto-Detection:**

.. code-block:: python

    from actingweb.oauth2 import create_oauth2_authenticator
    
    # Auto-detect provider from config.oauth2_provider
    auth = create_oauth2_authenticator(config)
    
    # Explicitly specify provider
    github_auth = create_oauth2_authenticator(config, provider_name="github")

**Custom Provider:**

.. code-block:: python

    from actingweb.oauth2 import create_generic_authenticator
    
    custom_config = {
        "client_id": "custom_client_id",
        "client_secret": "custom_secret",
        "auth_uri": "https://example.com/oauth/authorize",
        "token_uri": "https://example.com/oauth/token",
        "userinfo_uri": "https://example.com/userinfo",
        "scope": "read write",
        "redirect_uri": "https://yourdomain.com/oauth/callback"
    }
    
    custom_auth = create_generic_authenticator(config, custom_config)

OAuth2 Flow
===========

Authorization Request
---------------------

When a user needs authentication, they are redirected to the OAuth2 provider:

**GitHub Example:**

.. code-block:: text

    https://github.com/login/oauth/authorize?
      client_id=YOUR_CLIENT_ID&
      redirect_uri=https://yourdomain.com/oauth/callback&
      scope=user:email&
      state=CSRF_TOKEN&
      response_type=code

Authorization Code Exchange
---------------------------

The provider redirects back with an authorization code:

.. code-block:: text

    https://yourdomain.com/oauth/callback?code=AUTH_CODE&state=CSRF_TOKEN

Token Exchange
--------------

ActingWeb exchanges the code for an access token:

**GitHub Example:**

.. code-block:: text

    POST https://github.com/login/oauth/access_token
    Content-Type: application/x-www-form-urlencoded
    Accept: application/json
    User-Agent: ActingWeb-OAuth2-Client

    client_id=YOUR_CLIENT_ID&
    client_secret=YOUR_CLIENT_SECRET&
    code=AUTH_CODE&
    redirect_uri=https://yourdomain.com/oauth/callback

User Info Retrieval
-------------------

ActingWeb fetches user information:

**GitHub Example:**

.. code-block:: text

    GET https://api.github.com/user
    Authorization: Bearer ACCESS_TOKEN
    Accept: application/json
    User-Agent: ActingWeb-OAuth2-Client

Actor Lookup/Creation
---------------------

ActingWeb looks up or creates an actor based on the user's email address or unique identifier.

OAuth Login Flow with Postponed Actor Creation
-----------------------------------------------

ActingWeb supports an OAuth login flow where actor creation is postponed until after email is obtained from the OAuth provider. This enables applications to implement "Login with Google" or "Login with GitHub" buttons on the factory page.

**Key Features:**

- **Deferred Actor Creation**: Actors are created only after successful OAuth authentication and email retrieval
- **Email Fallback**: If the OAuth provider doesn't provide an email (e.g., GitHub private email), users are redirected to an email input form
- **Trust Type Detection**: Distinguishes between web UI login flows and MCP authorization flows

**Implementation:**

The library exposes OAuth authorization URLs through the factory handler's ``template_values``:

.. code-block:: python

    # Factory handler GET / provides:
    {
        'oauth_urls': {
            'google': 'https://accounts.google.com/o/oauth2/v2/auth?...',
            'github': 'https://github.com/login/oauth/authorize?...'
        },
        'oauth_providers': [
            {
                'name': 'google',
                'display_name': 'Google',
                'url': 'https://...'
            }
        ],
        'oauth_enabled': True
    }

Applications render "Login with Google/GitHub" buttons using these URLs:

.. code-block:: html

    {% if oauth_enabled %}
        {% for provider in oauth_providers %}
            <a href="{{ provider.url }}">
                Login with {{ provider.display_name }}
            </a>
        {% endfor %}
    {% endif %}

**Flow Diagram:**

1. User clicks "Login with Google" → OAuth2 redirect
2. Google returns to ``/oauth/callback`` with authorization code
3. Library exchanges code for access token and retrieves user info
4. If email is available: Create actor and redirect to ``/{actor_id}/www``
5. If email is missing: Redirect to ``/oauth/email`` for manual input
6. After email input: Create actor and complete login

**Email Fallback:**

When OAuth providers don't provide email addresses (e.g., GitHub with private email), the library:

1. Stores OAuth tokens temporarily in a session (10-minute TTL)
2. Redirects to ``/oauth/email`` with a session token
3. Presents email input form to the user
4. Completes actor creation after email is provided

Applications should provide an ``aw-oauth-email.html`` template for email input. If not provided, a basic fallback form is used.

**MCP Authorization Protection:**

The email fallback flow is disabled for MCP authorization requests (when ``trust_type`` parameter is present in OAuth state). MCP clients are programmatic and cannot interact with web forms, so these flows return an error if email cannot be extracted.

For detailed implementation guide, see :doc:`oauth-login-flow`.

MCP Integration
===============

The authentication system integrates seamlessly with ActingWeb's Model Context Protocol (MCP) implementation:

**Bearer Token Authentication:**

.. code-block:: bash

    curl -H "Authorization: Bearer YOUR_GITHUB_ACCESS_TOKEN" \
         -H "Content-Type: application/json" \
         -d '{"method": "tools/list", "id": 1}' \
         https://yourdomain.com/mcp

**Session Cookie Authentication:**
    Users authenticated via web session can access MCP endpoints directly.

**401 Responses:**
    Unauthenticated requests receive proper ``WWW-Authenticate`` headers with OAuth2 authorization URLs.

Custom Route Authentication
============================

For custom application routes that don't go through the standard ActingWeb handler system, use the ``check_and_verify_auth()`` function to provide proper authentication verification.

The ``check_and_verify_auth()`` Function
-----------------------------------------

**Location:** ``actingweb.auth.check_and_verify_auth()``

This function performs authentication checks and is designed for use in custom application routes. It supports:

- **Bearer Token Authentication**: OAuth2 tokens, ActingWeb trust secret tokens
- **Basic Authentication**: Username/password authentication
- **OAuth2 Cookie Sessions**: Web UI session authentication
- **OAuth2 Redirects**: Proper redirect handling for unauthenticated users

Function Signature
------------------

.. code-block:: python

    def check_and_verify_auth(appreq=None, actor_id=None, config=None):
        """Check and verify authentication for non-ActingWeb routes.
        
        Args:
            appreq: Request object (same format as used by ActingWeb handlers)
            actor_id: Actor ID to verify authentication against
            config: ActingWeb config object
            
        Returns:
            dict with:
            - 'authenticated': bool - True if authentication successful
            - 'actor': Actor object if authentication successful, None otherwise
            - 'auth': Auth object with authentication details
            - 'response': dict with response details {'code': int, 'text': str, 'headers': dict}
            - 'redirect': str - redirect URL if authentication requires redirect
        """

Usage Example
-------------

Here's how to use ``check_and_verify_auth()`` in a FastAPI custom route:

.. code-block:: python

    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import RedirectResponse
    from actingweb import auth
    from actingweb.aw_web_request import AWWebObj

    @fastapi_app.get("/{actor_id}/dashboard/memory")
    async def dashboard_memory(actor_id: str, request: Request):
        """Custom dashboard route with proper authentication."""
        
        # Convert FastAPI request to ActingWeb format
        req_data = await normalize_fastapi_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )
        
        # Use ActingWeb's proper authentication system
        auth_result = auth.check_and_verify_auth(
            appreq=webobj, 
            actor_id=actor_id, 
            config=app.get_config()
        )
        
        if not auth_result['authenticated']:
            # Handle different authentication failure scenarios
            response_code = auth_result['response']['code']
            
            if response_code == 404:
                raise HTTPException(status_code=404, detail="Actor not found")
            elif response_code == 302 and auth_result['redirect']:
                # OAuth redirect required
                raise HTTPException(
                    status_code=302,
                    detail="OAuth redirect required",
                    headers={"Location": auth_result['redirect']}
                )
            elif response_code == 401:
                # Authentication required
                headers = auth_result['response']['headers']
                raise HTTPException(
                    status_code=401, 
                    detail="Authentication required",
                    headers=headers
                )
            else:
                # Other authentication failures
                raise HTTPException(
                    status_code=response_code,
                    detail=auth_result['response']['text']
                )
        
        # Authentication successful - use the actor
        actor_interface = ActorInterface(auth_result['actor'])
        
        # Your custom route logic here...
        return {"message": f"Dashboard for actor {actor_interface.id}"}

Request Normalization Helper
----------------------------

For FastAPI applications, you'll need a helper function to convert FastAPI requests to ActingWeb format:

.. code-block:: python

    async def normalize_fastapi_request(request: Request) -> dict:
        """Convert FastAPI request to ActingWeb format."""
        # Read body asynchronously
        body = await request.body()

        # Parse cookies
        cookies = {}
        raw_cookies = request.headers.get("cookie")
        if raw_cookies:
            for cookie in raw_cookies.split("; "):
                if "=" in cookie:
                    name, value = cookie.split("=", 1)
                    cookies[name] = value

        # Convert headers (preserve case-sensitive header names)
        headers = {}
        for k, v in request.headers.items():
            if k.lower() == "authorization":
                headers["Authorization"] = v
            elif k.lower() == "content-type":
                headers["Content-Type"] = v
            else:
                headers[k] = v

        # If no Authorization header but we have an oauth_token cookie,
        # provide it as a Bearer token for web UI requests
        if "Authorization" not in headers and "oauth_token" in cookies:
            headers["Authorization"] = f"Bearer {cookies['oauth_token']}"

        # Get query parameters and form data
        params = {}
        for k, v in request.query_params.items():
            params[k] = v

        return {
            "method": request.method,
            "path": str(request.url.path),
            "data": body,
            "headers": headers,
            "cookies": cookies,
            "values": params,
            "url": str(request.url),
        }

Authentication Flow
-------------------

The ``check_and_verify_auth()`` function follows this authentication flow:

1. **Bearer Token Check**: Validates Authorization header for Bearer tokens (OAuth2 or ActingWeb trust tokens)
2. **Basic Authentication**: For API clients using username/password
3. **OAuth2 Cookie**: For web UI sessions with oauth_token cookie
4. **OAuth2 Redirect**: If all methods fail and OAuth2 is configured, creates redirect to OAuth2 provider

Response Codes
--------------

The function returns different response codes based on authentication results:

- **200**: Authentication successful
- **401**: Authentication required (with proper WWW-Authenticate headers)
- **302**: OAuth2 redirect required (with Location header)
- **403**: Forbidden (authentication failed)
- **404**: Actor not found

Security Considerations
-----------------------

When implementing custom routes with authentication:

- **Always validate actor_id**: Ensure users can only access their own actor data
- **Use HTTPS**: OAuth2 tokens and cookies should only be transmitted over secure connections
- **Handle errors gracefully**: Don't expose sensitive information in error messages
- **Log authentication attempts**: For security monitoring and debugging

Framework Integration
---------------------

The ``check_and_verify_auth()`` function works with any Python web framework:

**Flask Example:**

.. code-block:: python

    from flask import Flask, request
    from actingweb import auth
    from actingweb.aw_web_request import AWWebObj

    @app.route("/<actor_id>/dashboard/memory")
    def dashboard_memory(actor_id):
        webobj = AWWebObj(
            url=request.url,
            params=request.values,
            body=request.get_data(),
            headers=dict(request.headers),
            cookies=request.cookies,
        )
        
        auth_result = auth.check_and_verify_auth(
            appreq=webobj, 
            actor_id=actor_id, 
            config=app.get_config()
        )
        
        if not auth_result['authenticated']:
            # Handle authentication failure
            return handle_auth_failure(auth_result)
        
        # Use authenticated actor
        actor = ActorInterface(auth_result['actor'])
        return render_dashboard(actor)

**Django Example:**

.. code-block:: python

    from django.http import JsonResponse, HttpResponseRedirect
    from actingweb import auth
    from actingweb.aw_web_request import AWWebObj

    def dashboard_memory(request, actor_id):
        webobj = AWWebObj(
            url=request.build_absolute_uri(),
            params=request.GET.dict(),
            body=request.body,
            headers=dict(request.META),
            cookies=request.COOKIES,
        )
        
        auth_result = auth.check_and_verify_auth(
            appreq=webobj, 
            actor_id=actor_id, 
            config=get_actingweb_config()
        )
        
        if not auth_result['authenticated']:
            if auth_result['response']['code'] == 302:
                return HttpResponseRedirect(auth_result['redirect'])
            else:
                return JsonResponse(
                    {"error": auth_result['response']['text']}, 
                    status=auth_result['response']['code']
                )
        
        # Use authenticated actor
        actor = ActorInterface(auth_result['actor'])
        return render_dashboard(request, actor)

Implementation Files
====================

Core Files
----------

**actingweb/oauth2.py**
    Comprehensive OAuth2 module containing:
    - Base ``OAuth2Provider`` class
    - ``GoogleOAuth2Provider`` and ``GitHubOAuth2Provider`` implementations
    - ``OAuth2Authenticator`` class with full OAuth2 flow handling
    - Factory functions for creating authenticators
    - Utility functions for token and state handling

**actingweb/auth.py**
    Updated authentication module that integrates the new OAuth2 system with legacy authentication methods. Contains the ``check_and_verify_auth()`` function for custom route authentication.

**actingweb/handlers/oauth2_callback.py**
    Unified OAuth2 callback handler that processes callbacks from any OAuth2 provider.

Handler Updates
---------------

**actingweb/handlers/mcp.py**
    Updated to use provider-agnostic OAuth2 authentication with proper ``WWW-Authenticate`` headers.

Integration Updates
-------------------

**actingweb/interface/integrations/fastapi_integration.py**
    Updated FastAPI integration with:
    - OAuth2 authentication checks for protected endpoints
    - Session cookie validation
    - Bearer token validation
    - Consistent OAuth2 redirect handling

**actingweb/interface/integrations/flask_integration.py**
    Updated Flask integration with identical OAuth2 behavior to FastAPI.

Removed Legacy Files
--------------------

- ``actingweb/google_oauth.py`` - Replaced by consolidated ``oauth2.py``
- ``actingweb/handlers/google_oauth_callback.py`` - Replaced by ``oauth2_callback.py``

Security Considerations
=======================

CSRF Protection
---------------

- State parameter used for CSRF protection in OAuth2 flow
- State can encode redirect URL for post-authentication routing
- State validation prevents replay attacks

Token Security
--------------

- Access tokens stored securely in actor properties
- Session cookies are ``httpOnly`` and ``secure`` (HTTPS only)
- No sensitive information logged in debug output
- Token validation against provider APIs

Email Privacy
-------------

- Respects provider-specific email privacy settings
- Uses username-based fallback for private emails (GitHub)
- Optional enhanced email retrieval via provider APIs
- Unique identifier generation for users without public emails

Error Handling
==============

Common Provider-Specific Errors
-------------------------------

**GitHub:**
    - **403 Forbidden**: Check User-Agent header is set
    - **422 Unprocessable Entity**: Check Accept header is set to application/json
    - **Email Not Found**: User has private email - using username fallback

**Google:**
    - **Invalid Grant**: Authorization code expired or already used
    - **Invalid Client**: Check client_id and client_secret configuration
    - **Scope Error**: Requested scopes not available or not consented

Fallback Behavior
-----------------

- If provider email is private/unavailable, uses provider-specific unique identifiers
- If refresh token is requested but not supported, logs warning and continues
- If API calls fail, gracefully degrades to using available user information
- Authentication errors result in proper HTTP status codes and redirect to re-authentication

Testing
=======

The authentication system is designed to be testable:

**Unit Testing:**
    Each provider class can be instantiated with mock configurations for isolated testing.

**Integration Testing:**
    OAuth2 flows can be tested against real provider endpoints or mock servers.

**Provider Switching:**
    Easy configuration changes allow testing different providers in the same application.

**Mock Authentication:**
    Development and testing environments can use mock tokens and user information.

Backward Compatibility
======================

The implementation maintains full backward compatibility:

- Existing Google OAuth2 configurations continue to work unchanged
- Legacy Basic authentication still supported for older integrations
- API contracts unchanged - only internal implementation updated
- Existing actor data and properties remain intact
- No breaking changes to ActingWeb public APIs

Migration from Legacy
=====================

**From Legacy Google OAuth2:**

1. Update imports from ``google_oauth`` to ``oauth2``
2. Replace ``create_google_authenticator()`` calls with ``create_oauth2_authenticator()``
3. Update configuration if using custom OAuth2 settings
4. Test authentication flows to ensure proper functionality

**Configuration Changes:**

Old configuration:

.. code-block:: python

    # Legacy Google-specific config
    config.oauth = {
        "client_id": "google_client_id",
        "client_secret": "google_client_secret"
    }

New configuration (backward compatible):

.. code-block:: python

    # Provider-agnostic config (defaults to Google)
    config.oauth = {
        "client_id": "google_client_id", 
        "client_secret": "google_client_secret"
    }
    
    # Or explicitly specify provider
    config.oauth2_provider = "google"  # or "github"

Email Verification System
==========================

ActingWeb includes a comprehensive email verification system to prevent account hijacking when OAuth providers cannot verify email ownership.

Security Problem
----------------

When OAuth2 providers don't return a verified email address (e.g., GitHub users with private emails), the system needs to ensure the email entered by the user actually belongs to them. Without verification, an attacker could:

1. Authenticate with GitHub (private email)
2. Enter a victim's email address in the form
3. Gain access to the victim's actor

The email verification system prevents this by requiring proof of email ownership.

How It Works
------------

**Scenario 1: Provider Has Verified Emails**
    OAuth provider returns verified emails → User selects from dropdown → Actor created (email_verified=true)

**Scenario 2: No Verified Emails Available**
    No verified emails → User enters email → Verification email sent → User clicks link → Email marked verified

**Scenario 3: MCP Flows** (Cannot use web forms)
    No email from provider → Return error 502 → User must configure OAuth provider to make email public

Configuration
-------------

Email verification behavior is controlled by the ``force_email_prop_as_creator`` configuration:

.. code-block:: python

    app = (
        ActingWebApp(...)
        .with_email_as_creator(enable=True)  # Requires email addresses (default)
        .with_unique_creator(enable=True)
    )

When enabled (default):
    - Actor ``creator`` field must be a valid email address
    - System validates email ownership via OAuth provider OR verification link
    - Suitable for applications requiring email for notifications, billing, etc.

When disabled:
    - Actor ``creator`` field can be provider-specific ID
    - No email verification needed (see Provider ID Support below)
    - Suitable for privacy-focused applications

Verification Flow
-----------------

1. **Token Generation**: 32-byte URL-safe random token, 24-hour expiry
2. **Storage**: Token stored in ``actor.store.email_verification_token``
3. **Email Sent**: Lifecycle hook ``email_verification_required`` triggered
4. **User Clicks Link**: ``GET /<actor_id>/www/verify_email?token=abc123``
5. **Validation**: Token checked against stored value and expiry
6. **Mark Verified**: ``actor.store.email_verified`` set to ``"true"``
7. **Hook Triggered**: Lifecycle hook ``email_verified`` executed

Implementing Email Verification
--------------------------------

**Required: Implement the verification email hook:**

.. code-block:: python

    @app.lifecycle_hook("email_verification_required")
    def send_verification_email(
        actor: ActorInterface,
        email: str,
        verification_url: str,
        token: str
    ) -> None:
        """Send verification email when OAuth provider cannot verify."""
        import boto3  # or your email service

        ses = boto3.client('ses', region_name='us-east-1')

        ses.send_email(
            Source="noreply@yourdomain.com",
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": "Verify your email address"},
                "Body": {
                    "Html": {
                        "Data": f'''
                        <h2>Verify Your Email</h2>
                        <p>Click the link below to verify your email:</p>
                        <p><a href="{verification_url}">Verify Email</a></p>
                        <p>This link expires in 24 hours.</p>
                        '''
                    }
                }
            }
        )

**Optional: Handle successful verification:**

.. code-block:: python

    @app.lifecycle_hook("email_verified")
    def handle_email_verified(actor: ActorInterface, email: str) -> None:
        """Called after successful email verification."""
        logger.info(f"Email verified for actor {actor.id}: {email}")
        # Optional: Send welcome email, grant permissions, etc.

Verification Endpoints
----------------------

``GET /<actor_id>/www/verify_email?token=<token>``
    Validates the verification token and marks email as verified.

    **Responses:**
        - Success: Shows "Email Verified!" page
        - Invalid token: Shows error with explanation
        - Expired token: Shows error with "Resend" button

``POST /<actor_id>/www/verify_email``
    Resends the verification email with a new token.

    **Use case:** User didn't receive the original email or token expired

Verification State
------------------

The verification state is stored in actor properties:

.. code-block:: python

    # Check if email is verified
    if actor.store.email_verified == "true":
        # Email has been verified
        pass

    # Access verification metadata
    token = actor.store.email_verification_token  # Current token (if pending)
    created_at = actor.store.email_verification_created_at  # Token creation time
    verified_at = actor.store.email_verified_at  # When verification completed

Templates
---------

ActingWeb provides default templates for email verification:

**aw-verify-email.html**
    Verification result page (success, error, expired)

**aw-oauth-email.html**
    Email input form with dropdown support for verified emails

Applications can override these templates by placing them in their ``templates/`` directory.

Security Considerations
-----------------------

**Token Security:**
    - 32 bytes (256 bits) of cryptographically secure random data
    - URL-safe encoding (no special characters)
    - Single-use tokens (cleared after verification)
    - 24-hour expiration

**Email Validation:**
    - Verified emails from OAuth providers are validated via API
    - User input restricted to verified emails when available (dropdown)
    - Manual email input requires clicking verification link
    - No way to bypass verification requirement

**Attack Prevention:**
    - Token brute-forcing: 256-bit entropy makes this impractical
    - Token replay: Tokens are single-use and cleared after verification
    - Token expiry: Forces re-verification after 24 hours
    - Email spoofing: Verification link sent to claimed email address

MCP Authorization Security
===========================

ActingWeb includes critical security protections for MCP (Model Context Protocol) authorization flows to prevent unauthorized access.

Cross-Actor Authorization Prevention
-------------------------------------

**Security Threat:**
    An attacker could attempt to authorize MCP access to someone else's actor by manipulating the OAuth flow with a different user's ``actor_id``.

**Attack Scenario Without Protection:**

1. Alice has an actor with ``creator="alice@example.com"`` and ``actor_id="abc123"``
2. Bob starts MCP authorization with OAuth, providing ``actor_id="abc123"`` in the state parameter
3. Bob authenticates with his Google account (bob@example.com)
4. Without validation, the system would:

   - Load Alice's actor (abc123)
   - Store Bob's OAuth tokens in Alice's actor
   - Create trust relationship from Bob to Alice's actor
   - Bob gains unauthorized access to Alice's data!

**Protection Mechanism:**

The OAuth2 callback handler validates actor ownership before completing authorization:

.. code-block:: python

    # In oauth2_callback.py
    if actor_id and actor_instance:
        # Validate OAuth identifier matches actor creator
        if actor_instance.creator != identifier:
            # Reject authorization attempt
            return error_response(403, "You cannot authorize access to an actor that doesn't belong to you")

**How It Works:**

1. When ``actor_id`` is provided in OAuth state, the system loads the actor
2. Compares the OAuth-authenticated identifier with the actor's ``creator`` field
3. If they don't match, rejects the authorization with HTTP 403
4. Only allows authorization when the OAuth user owns the actor

**Error Messages:**

For MCP authorization attempts:
    *"You cannot authorize MCP access to an actor that doesn't belong to you. You authenticated as 'bob@example.com' but this actor belongs to 'alice@example.com'."*

For web login attempts:
    *"Authentication failed: You authenticated as 'bob@example.com' but attempted to access an actor belonging to 'alice@example.com'. Please log in with the correct account."*

Session Fixation Prevention
----------------------------

This security check also prevents session fixation attacks in web login flows:

**Attack Scenario:**
1. Attacker tricks victim into visiting OAuth URL with attacker's ``actor_id``
2. Victim authenticates with their own Google account
3. Without validation, victim's session would be bound to attacker's actor

**Protection:**
The same validation prevents this by rejecting authentication when the OAuth identifier doesn't match the actor creator.

Security Logging
-----------------

All authorization violations are logged with full context:

.. code-block:: text

    ERROR Security violation: OAuth identifier 'bob@example.com' does not match
    actor creator 'alice@example.com'. Flow type: MCP authorization

This enables security monitoring and incident response.

Legitimate Use Cases
---------------------

**Self-Authorization (Allowed):**
    - Alice authenticates with alice@example.com
    - Provides her own ``actor_id``
    - OAuth identifier matches actor creator → Authorized ✓

**New Actor Creation (Allowed):**
    - Bob authenticates with bob@example.com
    - No ``actor_id`` provided OR invalid ``actor_id``
    - System creates new actor with creator=bob@example.com → Authorized ✓

**Cross-Actor Authorization (Blocked):**
    - Bob authenticates with bob@example.com
    - Provides Alice's ``actor_id``
    - OAuth identifier doesn't match actor creator → Rejected ✗

Provider ID Support
===================

ActingWeb supports using stable provider-specific identifiers instead of email addresses as the actor creator. This provides enhanced privacy and works with users who don't want to share their email.

What Are Provider IDs?
-----------------------

Instead of using email addresses (which can change or be private), ActingWeb can use stable identifiers from OAuth providers:

**Google Provider IDs:**
    Format: ``google:<sub>``

    Example: ``google:105123456789012345678``

    The ``sub`` claim is a unique, stable identifier that never changes for a user.

**GitHub Provider IDs:**
    Format: ``github:<user_id>``

    Example: ``github:12345678``

    The GitHub user ID is stable even if the username changes. Falls back to ``github:<username>`` if user ID unavailable.

**Other Providers:**
    Format: ``{provider_name}:{unique_id}``

    Example: ``microsoft:550e8400-e29b-41d4-a716-446655440000``

Configuration
-------------

Enable provider ID mode by disabling email-as-creator:

.. code-block:: python

    app = (
        ActingWebApp(...)
        .with_email_as_creator(enable=False)  # Use provider IDs
        .with_unique_creator(enable=True)
    )

**Effect:**
    - Actor ``creator`` field contains provider ID (e.g., ``google:105...``)
    - Email address stored separately in ``actor.store.email`` (if provided by OAuth)
    - No email verification required
    - Works with private emails and email-less OAuth flows

Accessing Actor Information
----------------------------

.. code-block:: python

    # Get provider and ID from creator
    if actor.creator.startswith("google:"):
        google_sub = actor.creator.split(":", 1)[1]
        print(f"Google user: {google_sub}")
    elif actor.creator.startswith("github:"):
        github_id = actor.creator.split(":", 1)[1]
        print(f"GitHub user: {github_id}")

    # Get display email (may be None in provider ID mode)
    email = actor.store.email or "No email provided"

    # Get OAuth provider
    provider = actor.store.oauth_provider  # "google", "github", etc.

Benefits of Provider IDs
-------------------------

**Privacy:**
    Users can authenticate without sharing their email address

**Stability:**
    Provider IDs never change, even if the user changes their email or username

**Compatibility:**
    Works with OAuth providers that don't expose email addresses

**Security:**
    No user input - identifiers come directly from OAuth provider

**Simplicity:**
    No email verification flow needed

When to Use Provider IDs
-------------------------

**Use Provider IDs when:**
    - Privacy is a priority
    - Email addresses are not required for your application
    - You want stable, unchanging identifiers
    - Supporting users with private GitHub emails
    - Building MCP-only applications (no email notifications)

**Use Email Mode when:**
    - You need to send email notifications
    - Billing requires email addresses
    - Users expect email-based identification
    - Compatibility with existing email-based systems

Migration Between Modes
------------------------

**Switching from Email to Provider ID:**
    Existing email-based actors continue to work. New actors use provider IDs.

**Switching from Provider ID to Email:**
    Not recommended. Existing actors use provider IDs. Consider implementing email linking separately.

**Hybrid Approach:**
    Store provider ID as creator, link email separately:

    .. code-block:: python

        # In provider ID mode, email is stored separately
        actor.creator  # "google:105123456789012345678"
        actor.store.email  # "user@gmail.com" (if provided by OAuth)
        actor.store.email_verified  # "true" if verified by OAuth provider

Comparison: Email vs Provider ID Modes
---------------------------------------

+---------------------------+-------------------------+---------------------------+
| Feature                   | Email Mode              | Provider ID Mode          |
+===========================+=========================+===========================+
| Creator field             | Email address           | Provider-specific ID      |
+---------------------------+-------------------------+---------------------------+
| Email verification        | Required (if not from   | Not required              |
|                           | verified OAuth source)  |                           |
+---------------------------+-------------------------+---------------------------+
| Private GitHub emails     | Requires verification   | Works seamlessly          |
+---------------------------+-------------------------+---------------------------+
| Stable identifier         | No (email can change)   | Yes (ID never changes)    |
+---------------------------+-------------------------+---------------------------+
| Email notifications       | Yes                     | Optional (separate field) |
+---------------------------+-------------------------+---------------------------+
| User privacy              | Email exposed           | Email optional            |
+---------------------------+-------------------------+---------------------------+
| MCP flows                 | Email required          | Works without email       |
+---------------------------+-------------------------+---------------------------+
| Configuration             | ``with_email_as_creator | ``with_email_as_creator   |
|                           | (enable=True)``         | (enable=False)``          |
+---------------------------+-------------------------+---------------------------+

Future Enhancements
===================

The authentication system is designed for extensibility:

**Additional Providers:**
    - Microsoft Azure AD / Office 365
    - Auth0 and other identity providers
    - Custom enterprise OAuth2 providers
    - OpenID Connect providers

**Enhanced Features:**
    - Organization/team membership validation (GitHub, Google Workspace)
    - Customizable OAuth2 scopes per application
    - Advanced token refresh patterns
    - Webhook integration for account changes
    - Multi-factor authentication support

**Performance Improvements:**
    - Token caching and validation optimization
    - Async OAuth2 flows for better performance
    - Connection pooling for provider API calls

**Developer Experience:**
    - Configuration validation and helpful error messages
    - OAuth2 flow debugging tools
    - Provider-specific setup documentation
    - Integration testing utilities

This implementation provides a solid foundation for multi-provider OAuth2 support in ActingWeb while maintaining backward compatibility and enabling future authentication enhancements.
Roles
-----

ActingWeb commonly plays two roles with OAuth2:

- OAuth2 Client (login): Used for interactive login to the web UI (``/<actor_id>/www``) and app flows. The app redirects users to a provider (Google/GitHub) and receives a callback.
- OAuth2‑Protected Resource (MCP): The ``/mcp`` endpoint requires OAuth2 access. Unauthenticated requests receive 401 with a proper ``WWW-Authenticate`` header and discovery endpoints are exposed under ``/.well-known/``.

Discovery Endpoints (served by integrations):

- ``/.well-known/oauth-authorization-server``
- ``/.well-known/oauth-protected-resource``
- ``/.well-known/oauth-protected-resource/mcp``


Provider Differences (Cheat Sheet)
----------------------------------

- Google: refresh tokens supported (use ``access_type=offline`` + ``prompt=consent``), OpenID scopes (``openid email profile``).
- GitHub: set ``User-Agent`` and ``Accept: application/json`` headers, no refresh tokens (short‑lived tokens), email may be private.
