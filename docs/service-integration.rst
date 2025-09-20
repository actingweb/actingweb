====================
Service Integration
====================

ActingWeb provides a unified, modern interface for integrating with third-party OAuth2-protected services like Dropbox, Gmail, GitHub, and Box. This system replaces the legacy OAuth class with a clean, developer-friendly API built on top of the new OAuth2 foundation.

Overview
========

The service integration system provides:

- **Unified Configuration**: Register services using fluent API methods or templates
- **Automatic Token Management**: Handles access token refresh and storage transparently
- **Clean Developer Interface**: Similar to other ActingWeb functionality
- **Per-Actor Authentication**: Each actor can authenticate to services independently
- **Trust Relationship Storage**: Service authentication details stored in trust relationships

Quick Start
===========

1. **Configure Services** in your ActingWeb app:

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = (
        ActingWebApp(
            aw_type="urn:actingweb:example.com:myapp",
            database="dynamodb",
            fqdn="myapp.example.com"
        )
        .with_oauth(...)  # Configure user authentication
        .add_dropbox("dropbox_client_id", "dropbox_client_secret")
        .add_gmail("gmail_client_id", "gmail_client_secret", readonly=True)
        .add_github("github_client_id", "github_client_secret")
    )

2. **Use Services** in your application code:

.. code-block:: python

    @app.action_hook("sync_files")
    def sync_files(actor: ActorInterface, action_name: str, data: Dict[str, Any]) -> Any:
        # Get authenticated Dropbox client
        dropbox = actor.services.get("dropbox")

        if not dropbox.is_authenticated():
            # Return authorization URL for user to authenticate
            return {
                "error": "Dropbox authentication required",
                "auth_url": dropbox.get_authorization_url()
            }

        # Make API calls to Dropbox
        files = dropbox.get("/2/files/list_folder", {"path": "/Documents"})
        return {"files": files}

Configuration
=============

Service Registration
-------------------

Use fluent API methods to register services:

**Pre-configured Templates**:

.. code-block:: python

    app.add_dropbox(client_id, client_secret)
    app.add_gmail(client_id, client_secret, readonly=True)  # readonly=False for write access
    app.add_github(client_id, client_secret)
    app.add_box(client_id, client_secret)

**Custom Services**:

.. code-block:: python

    app.add_service(
        name="custom_service",
        client_id="your_client_id",
        client_secret="your_client_secret",
        scopes=["read", "write"],
        auth_uri="https://service.com/oauth/authorize",
        token_uri="https://service.com/oauth/token",
        userinfo_uri="https://service.com/oauth/userinfo",  # optional
        revocation_uri="https://service.com/oauth/revoke",  # optional
        base_api_url="https://api.service.com/v1",
        access_type="offline",  # extra OAuth parameters
        prompt="consent"
    )

**Advanced Configuration**:

.. code-block:: python

    # Get service registry for advanced configuration
    registry = app.get_service_registry()

    # Register custom service configuration
    from actingweb.interface.services import ServiceConfig

    custom_config = ServiceConfig(
        name="advanced_service",
        client_id="client_id",
        client_secret="client_secret",
        scopes=["custom.read", "custom.write"],
        auth_uri="https://auth.service.com/oauth2/auth",
        token_uri="https://auth.service.com/oauth2/token",
        base_api_url="https://api.service.com/v2",
        extra_params={"access_type": "offline", "approval_prompt": "force"}
    )

    registry.register_service(custom_config)

Usage
=====

Accessing Services
------------------

Each actor has a `services` property that provides access to authenticated service clients:

.. code-block:: python

    # Get service client
    service_client = actor.services.get("dropbox")

    # Check authentication status
    if service_client.is_authenticated():
        # Make API calls
        pass
    else:
        # Redirect user to authenticate
        auth_url = service_client.get_authorization_url()

Authentication Flow
-------------------

**1. Check Authentication**:

.. code-block:: python

    dropbox = actor.services.get("dropbox")
    if not dropbox.is_authenticated():
        return {"auth_url": dropbox.get_authorization_url()}

**2. User Authorization**:

The user visits the authorization URL and grants permissions. The service redirects back to:
``https://yourdomain.com/{actor_id}/services/{service_name}/callback``

**3. Automatic Token Exchange**:

ActingWeb automatically handles the OAuth2 callback, exchanges the authorization code for tokens, and stores them securely.

Making API Calls
-----------------

Service clients provide convenient HTTP methods:

.. code-block:: python

    # GET request
    files = dropbox.get("/2/files/list_folder", {"path": "/Documents"})

    # POST request
    result = dropbox.post("/2/files/create_folder_v2", {
        "path": "/NewFolder",
        "autorename": False
    })

    # PUT request
    updated = service.put("/api/resource/123", {"name": "Updated Name"})

    # DELETE request
    deleted = service.delete("/api/resource/123")

**Automatic Token Refresh**:

Service clients automatically refresh expired access tokens using refresh tokens when available.

**Error Handling**:

.. code-block:: python

    result = dropbox.get("/2/files/list_folder", {"path": "/Documents"})
    if result is None:
        # API call failed - check logs for details
        return {"error": "Failed to access Dropbox"}

Service Management
==================

List Available Services
-----------------------

.. code-block:: python

    # Get all services and their authentication status
    services_status = actor.services.list_available_services()
    # Returns: {"dropbox": True, "gmail": False, "github": True}

Revoke Service Authentication
-----------------------------

.. code-block:: python

    # Revoke specific service
    success = actor.services.revoke_service("dropbox")

    # Revoke all services
    results = actor.services.revoke_all_services()
    # Returns: {"dropbox": True, "gmail": True, "github": False}

REST API Endpoints
==================

The service integration system automatically creates REST endpoints:

**Service OAuth2 Callback**:
``GET /{actor_id}/services/{service_name}/callback?code=...&state=...``

**Revoke Service Authentication**:
``DELETE /{actor_id}/services/{service_name}``

These endpoints are automatically configured in both Flask and FastAPI integrations.

Service Templates
=================

Pre-configured service templates are available for popular services:

Dropbox
-------

.. code-block:: python

    app.add_dropbox("client_id", "client_secret")

**Scopes**: ``files.content.read``, ``files.metadata.read``
**API Base URL**: ``https://api.dropboxapi.com``

Gmail
-----

.. code-block:: python

    app.add_gmail("client_id", "client_secret", readonly=True)

**Read-only Scopes**: ``https://www.googleapis.com/auth/gmail.readonly``
**Write Scopes**: ``https://www.googleapis.com/auth/gmail.modify``
**API Base URL**: ``https://www.googleapis.com/gmail/v1``

GitHub
------

.. code-block:: python

    app.add_github("client_id", "client_secret")

**Scopes**: ``repo``, ``user``
**API Base URL**: ``https://api.github.com``

Box
---

.. code-block:: python

    app.add_box("client_id", "client_secret")

**Scopes**: ``root_readwrite``
**API Base URL**: ``https://api.box.com/2.0``

Architecture
============

The service integration system consists of several components:

**ServiceConfig**: Type-safe configuration for OAuth2 services
**ServiceClient**: Handles authentication and API calls for a specific service
**ServiceRegistry**: Manages registered service configurations
**ActorServices**: Per-actor interface for accessing authenticated service clients
**ServicesHandler**: HTTP handler for OAuth2 callbacks and service management

**Token Storage**: Service authentication tokens are stored securely in ActingWeb's trust relationship system, providing per-actor isolation and proper security.

**Integration**: The system integrates seamlessly with both Flask and FastAPI, automatically registering the necessary routes for OAuth2 callbacks.


Security
========

**Token Storage**: Service tokens are stored in ActingWeb's trust relationship system, providing:

- Per-actor isolation
- Encrypted storage
- Secure token refresh
- Automatic cleanup on actor deletion

**OAuth2 Security**: Built on the same OAuth2 foundation as user authentication:

- State parameter validation
- CSRF protection
- Secure redirect URI validation
- Token revocation support

**Permissions**: Service access is tied to actor permissions and trust relationships, ensuring proper authorization controls.

Troubleshooting
===============

**Service Not Registered**:

.. code-block:: python

    service = actor.services.get("unknown_service")
    # Returns None if service not registered

**Authentication Failed**:

Check the service configuration and ensure redirect URIs match:

.. code-block:: python

    # Verify service is registered
    registry = app.get_service_registry()
    config = registry.get_service_config("dropbox")
    if not config or not config.is_enabled():
        # Service not properly configured

**Token Refresh Failed**:

Service clients automatically attempt token refresh. Check logs for refresh errors and ensure the service supports refresh tokens.

**API Call Failed**:

.. code-block:: python

    result = service.get("/api/endpoint")
    if result is None:
        # Check logs for HTTP errors, authentication issues, etc.

**Debugging**:

Enable debug logging to see detailed OAuth2 flows and API calls:

.. code-block:: python

    import logging
    logging.getLogger('actingweb').setLevel(logging.DEBUG)

This will log OAuth2 token exchanges, API requests, and error details for troubleshooting.