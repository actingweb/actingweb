============================
ActingWeb Authentication System
============================

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
    Updated authentication module that integrates the new OAuth2 system with legacy authentication methods.

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