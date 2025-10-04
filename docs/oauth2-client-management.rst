===============================
OAuth2 Client Management System
===============================

This document describes the OAuth2 client management functionality in ActingWeb, which enables applications to create and manage OAuth2 clients for programmatic access using the client credentials grant flow.

Overview
========

The OAuth2 client management system extends ActingWeb's authentication capabilities by providing a complete OAuth2 server implementation that supports the client credentials grant flow (RFC 6749 Section 4.4). This allows applications to create OAuth2 clients that can obtain access tokens for API access without user interaction.

**Key Features:**

- **Client Registration**: Dynamic OAuth2 client creation following RFC 7591
- **Client Credentials Flow**: Full support for OAuth2 client credentials grant
- **Access Token Generation**: On-demand access token creation with configurable expiration
- **High-Level Interface**: Developer-friendly OAuth2ClientManager API
- **Security**: Actor-scoped client isolation and validation
- **Trust Integration**: Seamless integration with ActingWeb's trust system

Architecture
============

Core Components
---------------

The OAuth2 client management system consists of several layers:

**OAuth2ClientManager** (``actingweb/interface/oauth_client_manager.py``)
    High-level, developer-friendly interface for OAuth2 client operations. This is the primary public API that applications should use.

**MCPClientRegistry** (``actingweb/oauth2_server/client_registry.py``) 
    Handles OAuth2 client registration, storage, and validation using ActingWeb's property system.

**OAuth2Server** (``actingweb/oauth2_server/oauth2_server.py``)
    Core OAuth2 server implementation supporting authorization code and client credentials grant flows.

**ActingWebTokenManager** (``actingweb/oauth2_server/token_manager.py``)
    Manages OAuth2 access token lifecycle, storage, and validation using JWT-like tokens.

Usage Guide
===========

Creating OAuth2 Clients
------------------------

Applications use the ``OAuth2ClientManager`` to create and manage OAuth2 clients:

.. code-block:: python

    from actingweb.interface.oauth_client_manager import OAuth2ClientManager

    # Initialize client manager for an actor
    client_manager = OAuth2ClientManager(actor_id, config)
    
    # Create a new OAuth2 client
    client_data = client_manager.create_client(
        client_name="My API Client",
        trust_type="mcp_client"
    )
    
    print(f"Client ID: {client_data['client_id']}")
    print(f"Client Secret: {client_data['client_secret']}")

The created client includes:

- **client_id**: Unique identifier starting with ``mcp_``
- **client_secret**: Secure secret for authentication  
- **created_at**: Creation timestamp
- **trust_type**: Integration with ActingWeb's trust system
- **grant_types**: Supported OAuth2 grant types
- **scope**: Authorized scopes (default: ``mcp``)

Generating Access Tokens
-------------------------

Applications can generate access tokens using the client credentials flow:

.. code-block:: python

    # Generate access token for a client
    token_response = client_manager.generate_access_token(
        client_id=client_data['client_id'],
        scope="mcp"
    )
    
    if token_response:
        access_token = token_response['access_token']
        expires_in = token_response['expires_in']  # seconds
        token_type = token_response['token_type']  # "Bearer"
        
        print(f"Access Token: {access_token}")
        print(f"Expires in: {expires_in} seconds")

Access tokens are:

- **Bearer tokens**: Used in Authorization header
- **Time-limited**: Default 3600 seconds (1 hour) expiration
- **Scoped**: Limited to specified OAuth2 scopes
- **Actor-bound**: Associated with the creating actor's permissions

Client Management Operations
----------------------------

The ``OAuth2ClientManager`` provides comprehensive client management:

.. code-block:: python

    # List all clients for an actor
    clients = client_manager.list_clients()
    for client in clients:
        print(f"Client: {client['client_name']} ({client['client_id']})")
        print(f"Created: {client['created_at_formatted']}")
        print(f"Status: {client['status']}")

    # Get specific client details
    client = client_manager.get_client(client_id)
    if client:
        print(f"Trust type: {client['trust_type']}")
        print(f"Grant types: {client['grant_types']}")

    # Validate client credentials
    is_valid = client_manager.validate_client(client_id, client_secret)
    
    # Delete a client
    success = client_manager.delete_client(client_id)
    
    # Get statistics
    stats = client_manager.get_client_stats()
    print(f"Total clients: {stats['total_clients']}")
    print(f"Trust types: {stats['trust_types']}")

Security Model
==============

Actor Isolation
----------------

OAuth2 clients are strictly isolated by actor:

- Each client belongs to exactly one actor
- Clients can only be managed by their owning actor
- Access tokens inherit the actor's permissions and trust relationships
- Cross-actor access is prevented at all levels

Client Types
------------

The system distinguishes between client types:

**Custom Clients** (``mcp_*``)
    - Created dynamically by applications
    - Support access token generation
    - Can be deleted by the owner
    - Full management capabilities

**System Clients** (non-``mcp_*``)
    - Reserved for ActingWeb framework use
    - Limited management operations
    - Cannot generate access tokens via client manager

Trust Integration
-----------------

OAuth2 clients integrate with ActingWeb's trust system:

- **trust_type**: Links clients to trust relationship types
- **Permission Inheritance**: Clients inherit actor's trust-based permissions
- **Scope Validation**: Token scopes validated against trust relationships

Implementation Details
======================

Token Format
-------------

Access tokens follow a structured format:

.. code-block:: text

    aw_<base64url-encoded-payload>
    
    # Example:
    aw_abc123def456ghi789jkl012mno345pqr678stu901

Tokens contain:

- **Prefix**: ``aw_`` identifies ActingWeb tokens
- **Payload**: URL-safe base64 encoded random data
- **Length**: 32+ characters for security

Storage Schema
--------------

OAuth2 clients and tokens are stored in ActingWeb's property system:

**Client Storage** (``oauth2:client:<client_id>``)
    - Client metadata and credentials
    - Trust type and grant permissions
    - Creation and modification timestamps

**Token Storage** (``oauth2:token:<token>``)  
    - Token metadata and expiration
    - Actor and client associations
    - Scope and permission information

**Client Indexes** (``oauth2:actor_clients:<actor_id>``)
    - Efficient actor-to-clients mapping
    - Supports client listing operations

Error Handling
--------------

The system provides comprehensive error handling:

.. code-block:: python

    try:
        client = client_manager.create_client("My Client")
    except ValueError as e:
        # Handle client creation errors
        print(f"Client creation failed: {e}")
    except Exception as e:
        # Handle unexpected errors
        print(f"Unexpected error: {e}")

Common error scenarios:

- **Invalid client_id**: Client not found or not accessible
- **Permission denied**: Client doesn't belong to current actor
- **Token generation failure**: Client credentials invalid
- **Storage errors**: Database connectivity issues

Best Practices
==============

Client Lifecycle
-----------------

1. **Creation**: Create clients with descriptive names
2. **Token Management**: Generate tokens on-demand, don't store long-term
3. **Cleanup**: Delete unused clients to reduce attack surface
4. **Monitoring**: Track client usage via statistics

.. code-block:: python

    # Good: Create client with descriptive name
    client = client_manager.create_client("Production API Client v2.1")
    
    # Good: Generate token when needed
    token = client_manager.generate_access_token(client['client_id'])
    
    # Good: Clean up unused clients
    if not client_in_use(client_id):
        client_manager.delete_client(client_id)

Security Considerations
-----------------------

1. **Client Secrets**: Treat as sensitive data, never log or expose
2. **Access Tokens**: Short-lived, use HTTPS for transmission
3. **Actor Validation**: Always validate actor ownership before operations
4. **Scope Limiting**: Use minimal required scopes

.. code-block:: python

    # Good: Minimal scope
    token = client_manager.generate_access_token(client_id, scope="read")
    
    # Good: Validate ownership
    client = client_manager.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

Integration Examples
====================

FastAPI Integration
-------------------

.. code-block:: python

    from fastapi import FastAPI, HTTPException, Depends
    from actingweb.interface.oauth_client_manager import OAuth2ClientManager

    app = FastAPI()

    def get_client_manager(actor_id: str) -> OAuth2ClientManager:
        return OAuth2ClientManager(actor_id, app.config)

    @app.post("/{actor_id}/oauth-clients")
    async def create_oauth_client(
        actor_id: str,
        client_name: str,
        client_manager: OAuth2ClientManager = Depends(get_client_manager)
    ):
        try:
            client = client_manager.create_client(client_name)
            return {"client_id": client["client_id"], "client_secret": client["client_secret"]}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/{actor_id}/oauth-clients/{client_id}/tokens")
    async def generate_access_token(
        actor_id: str,
        client_id: str,
        client_manager: OAuth2ClientManager = Depends(get_client_manager)
    ):
        token_response = client_manager.generate_access_token(client_id)
        if not token_response:
            raise HTTPException(status_code=400, detail="Token generation failed")
        return token_response

MCP Server Integration
----------------------

For MCP (Model Context Protocol) applications:

.. code-block:: python

    from actingweb.interface.actor_interface import ActorInterface

    class MCPServer:
        def __init__(self, actor: ActorInterface):
            self.actor = actor
            self.client_manager = OAuth2ClientManager(actor.id, actor.config)
        
        async def setup_oauth_client(self, client_name: str):
            """Setup OAuth2 client for MCP access"""
            client = self.client_manager.create_client(
                client_name=client_name,
                trust_type="mcp_client"
            )
            
            # Generate initial access token
            token = self.client_manager.generate_access_token(client['client_id'])
            
            return {
                "client_credentials": {
                    "client_id": client['client_id'],
                    "client_secret": client['client_secret']
                },
                "access_token": token['access_token'],
                "expires_in": token['expires_in']
            }

Troubleshooting
===============

Common Issues
-------------

**"Client not found" errors**
    - Verify client_id is correct and belongs to the current actor
    - Check client wasn't deleted by another process

**"Token generation failed" errors**  
    - Ensure client_id starts with ``mcp_`` (custom client)
    - Verify client credentials are valid
    - Check ActingWeb configuration is correct

**Performance issues**
    - Monitor client and token counts per actor
    - Clean up expired tokens and unused clients regularly
    - Consider token caching for high-frequency operations

Debug Logging
-------------

Enable debug logging to troubleshoot issues:

.. code-block:: python

    import logging
    
    # Enable OAuth2 debug logging
    logging.getLogger('actingweb.interface.oauth_client_manager').setLevel(logging.DEBUG)
    logging.getLogger('actingweb.oauth2_server').setLevel(logging.DEBUG)

This will provide detailed information about:

- Client creation and validation
- Token generation processes
- Storage operations
- Error conditions

Related Documentation
=====================

- :doc:`authentication-system` - Core OAuth2 authentication
- :doc:`unified-access-control` - Trust and permission system  
- :doc:`mcp-applications` - MCP server implementation
- :doc:`developers` - General development guide