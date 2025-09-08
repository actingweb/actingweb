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
    GitHub users may have private email addresses. The system handles this by:
    
    1. Using public email if available
    2. Attempting to fetch primary email via GitHub's emails API
    3. Falling back to ``{username}@github.local`` as unique identifier

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

This function performs the same authentication checks as ``init_actingweb()`` but is designed for use in custom application routes. It supports:

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
