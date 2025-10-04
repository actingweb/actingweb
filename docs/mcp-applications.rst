========================================
Building MCP Applications with ActingWeb
========================================

This guide shows how to build Model Context Protocol (MCP) server applications using ActingWeb, following the patterns demonstrated in the ``actingweb_mcp`` example application.

Overview
--------

An MCP server application with ActingWeb combines:

- **ActingWeb Framework**: Provides actor management, properties, trust relationships, and web interface
- **FastAPI Integration**: Modern ASGI web framework with automatic OpenAPI documentation
- **OAuth2 Authentication**: User authentication with Google, GitHub, or other providers
- **MCP Protocol Support**: Tools, prompts, and resources for AI language models
- **Per-User Data Isolation**: Each authenticated user gets their own actor with private data

Architecture Pattern
--------------------

MCP Application Structure
-------------------------

.. code-block:: text

    mcp-app/
    ├── application.py              # Main FastAPI application
    ├── shared_mcp/                 # Reusable MCP functionality
    │   ├── __init__.py
    │   ├── tools.py               # MCP tools (search, fetch, etc.)
    │   ├── prompts.py             # MCP prompts
    │   └── resources.py           # MCP resources
    ├── shared_hooks/              # ActingWeb hooks
    │   ├── __init__.py
    │   ├── property_hooks.py      # Property access control
    │   ├── callback_hooks.py      # Custom callbacks
    │   └── lifecycle_hooks.py     # Actor lifecycle events
    ├── templates/                 # Web UI templates
    │   ├── aw-actor-www-root.html
    │   ├── aw-actor-www-properties.html
    │   └── ...
    ├── static/                    # Static assets (CSS, JS, images)
    │   ├── style.css
    │   └── favicon.png
    ├── dynamodb/                  # Database configuration
    │   └── demo_table.json
    ├── serverless.yml             # AWS Lambda deployment config
    ├── Dockerfile-fastapi.lambda  # Container for Lambda
    └── pyproject.toml            # Dependencies and config

Key Components
--------------

1. **FastAPI Application**: Main ASGI app with automatic docs at ``/docs``
2. **MCP Server Endpoint**: Exposed at ``/mcp`` with OAuth2 authentication
3. **Shared MCP Logic**: Modularized tools, prompts, and resources
4. **Property Hooks**: Control access and validation for actor properties
5. **Web Interface**: User-friendly management of actor data
6. **Multi-Provider OAuth2**: Support for Google, GitHub, etc.

Quick Start
-----------

Basic MCP Application
---------------------

.. code-block:: python

    # application.py
    from fastapi import FastAPI
    from mangum import Mangum
    from actingweb.interface import ActingWebApp, ActorInterface
    from shared_mcp.tools import setup_mcp_tools
    from shared_mcp.prompts import setup_mcp_prompts
    from shared_hooks.property_hooks import register_property_hooks

    # Create FastAPI app
    fastapi_app = FastAPI(
        title="My MCP Server",
        description="MCP server with ActingWeb integration",
        version="1.0.0"
    )

    # Create ActingWeb app
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:example.com:mcp",
        database="dynamodb",
        fqdn=os.getenv("APP_HOST_FQDN", "localhost")
    ).with_oauth(
        client_id=os.getenv("OAUTH_CLIENT_ID"),
        client_secret=os.getenv("OAUTH_CLIENT_SECRET")
    ).with_web_ui()

    # Register hooks
    register_property_hooks(aw_app)

    # Initialize actors after creation
    @aw_app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs):
        # Set initial properties
        actor.properties.email = actor.creator
        actor.properties.created_at = datetime.now().isoformat()

    # Integrate with FastAPI
    aw_app.integrate_fastapi(fastapi_app)

    # Setup MCP functionality
    setup_mcp_tools(aw_app)
    setup_mcp_prompts(aw_app)

    # AWS Lambda handler
    lambda_handler = Mangum(fastapi_app, lifespan="off")

    # Local development
    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(fastapi_app, host="0.0.0.0", port=5000, reload=True)

MCP Tools Implementation
------------------------

Create reusable MCP tools in ``shared_mcp/tools.py`` using the correct decorators:

.. code-block:: python

    # shared_mcp/tools.py
    import logging
    from datetime import datetime
    from typing import Dict, Any
    from actingweb.interface import ActorInterface
    from actingweb.mcp import mcp_tool

    logger = logging.getLogger(__name__)

    def setup_mcp_tools(aw_app):
        """Register MCP tools with the ActingWeb app."""

        @aw_app.action_hook("search")
        @mcp_tool(description="Search through the actor's properties")
        def search(actor: ActorInterface, action_name: str, params: Dict[str, Any]):
            query = str(params.get("query", "")).lower()
            results = []
            for key, value in actor.properties.items():
                if query in key.lower() or query in str(value).lower():
                    results.append(f"Property {key}: {value}")
            return "\n".join(results) if results else f"No results for '{query}'"

        @aw_app.action_hook("create_note")
        @mcp_tool(description="Create a note for this actor")
        def create_note(actor: ActorInterface, action_name: str, params: Dict[str, Any]):
            title = params.get("title", "Untitled")
            content = params.get("content", "")
            key = f"note_{datetime.now().isoformat()}"
            actor.properties[key] = {"title": title, "content": content, "created": datetime.now().isoformat()}
            return {"status": "ok", "note": key}

        @aw_app.action_hook("fetch_url")
        @mcp_tool(description="Fetch URL content and store metadata")
        def fetch_url(actor: ActorInterface, action_name: str, params: Dict[str, Any]):
            import requests
            url = params.get("url")
            if not url:
                return {"error": "Missing url"}
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                actor.properties[f"fetch_{datetime.now().isoformat()}"] = {
                    "url": url,
                    "status_code": resp.status_code,
                }
                return resp.text[:5000]
            except Exception as e:
                return f"Error fetching URL: {e}"

MCP Prompts Implementation
--------------------------

Create prompts in ``shared_mcp/prompts.py`` using the correct decorators:

.. code-block:: python

    # shared_mcp/prompts.py
    from typing import Dict, Any
    from actingweb.interface import ActorInterface
    from actingweb.mcp import mcp_prompt

    def setup_mcp_prompts(aw_app):
        """Register MCP prompts for the ActingWeb application."""

        @aw_app.method_hook("analyze_notes")
        @mcp_prompt(description="Analyze notes for this actor")
        def analyze_notes(actor: ActorInterface, method_name: str, data: Dict[str, Any]):
            notes = [v for k, v in actor.properties.items() if k.startswith("note_") and isinstance(v, dict)]
            if not notes:
                return "No notes found."
            titles = ", ".join(n.get("title", "Untitled") for n in notes)
            return f"You have {len(notes)} notes. Titles: {titles}"

        @aw_app.method_hook("create_meeting_prep")
        @mcp_prompt(description="Create a meeting prep prompt")
        def create_meeting_prep(actor: ActorInterface, method_name: str, data: Dict[str, Any]):
            topic = str(data.get("topic", ""))
            relevant = [f"{k}: {v}" for k, v in actor.properties.items() if topic.lower() in str(v).lower()]
            context = "\n".join(relevant) if relevant else "No relevant data found."
            return f"Prepare for a meeting about: {topic}\n\nRelevant information:\n{context}"

MCP Resources Implementation
----------------------------

You can expose resources via MCP using the resource decorator on a method hook:

.. code-block:: python

    from typing import Dict, Any
    from actingweb.mcp import mcp_resource

    def setup_mcp_resources(aw_app):
        @aw_app.method_hook("config")
        @mcp_resource(uri_template="config://{path}", description="Read config values")
        def get_config(actor, method_name: str, data: Dict[str, Any]):
            path = data.get("path", "")
            return {"path": path, "value": actor.properties.get(path, None)}

Property Hooks for MCP Applications
-----------------------------------

Implement property access control in ``shared_hooks/property_hooks.py``:

.. code-block:: python

    # shared_hooks/property_hooks.py
    import json
    import logging
    from typing import Any, List, Optional
    from actingweb.interface.actor_interface import ActorInterface

    logger = logging.getLogger(__name__)

    # Properties that should be hidden from external access
    PROP_HIDE = ["email", "auth_token"]
    PROP_PROTECT = PROP_HIDE + ["created_at", "actor_type"]

    def register_property_hooks(app):
        """Register all property hooks with the ActingWeb application."""

        @app.property_hook("email")
        def handle_email_property(actor: ActorInterface, operation: str, value: Any, path: List[str]) -> Optional[Any]:
            """Handle email property with access control."""
            if operation in ["put", "post", "delete"]:
                # Protect email from all modifications
                return None
            return value

        @app.property_hook("*")
        def handle_all_properties(actor: ActorInterface, operation: str, value: Any, path: List[str]) -> Optional[Any]:
            """Handle all properties with general validation."""
            if not path:
                return value

            property_name = path[0] if path else ""

            # Hide sensitive properties from GET operations
            if (property_name in PROP_HIDE or property_name.startswith("_")) and operation == "get":
                return None

            # Protect certain properties from modification
            if operation in ["put", "post"]:
                if property_name in PROP_PROTECT:
                    return None
                    
                # Handle JSON string conversion
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        return value
                elif not isinstance(value, dict):
                    return value

            return value

OAuth2 Integration
------------------

Configure OAuth2 authentication for your MCP server:

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # OAuth2 Provider (google or github)
    OAUTH_PROVIDER="google"
    OAUTH_CLIENT_ID="your-google-client-id"
    OAUTH_CLIENT_SECRET="your-google-client-secret"

    # Application
    APP_HOST_FQDN="your-domain.com"
    APP_HOST_PROTOCOL="https://"
    LOG_LEVEL="INFO"

OAuth2 Flow
~~~~~~~~~~~

1. Client accesses protected ``/mcp`` endpoint
2. Returns 401 with ``WWW-Authenticate`` header containing OAuth2 provider auth URL  
3. User authenticates with Google/GitHub
4. OAuth2 callback creates/finds ActingWeb actor based on user email
5. Bearer token provided for subsequent API access

Authentication in Application Code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # The ActingWeb integration handles OAuth2 automatically
    # Authenticated users get access to their actor context in MCP tools

    from actingweb.mcp import mcp_tool

    @aw_app.action_hook("my_tool")
    @mcp_tool(description="Demo tool showing actor context")
    def my_tool(actor: ActorInterface, action_name: str, params: Dict[str, Any]) -> str:
        user_email = actor.creator
        actor.properties.last_tool_use = datetime.now().isoformat()
        return f"Tool executed for user {user_email}"

Deployment Patterns
===================

AWS Lambda with Serverless Framework
------------------------------------

.. code-block:: yaml

    # serverless.yml
    service: my-mcp-server

    provider:
      name: aws
      runtime: python3.11
      region: us-east-1
      environment:
        OAUTH_PROVIDER: ${env:OAUTH_PROVIDER}
        OAUTH_CLIENT_ID: ${env:OAUTH_CLIENT_ID}
        OAUTH_CLIENT_SECRET: ${env:OAUTH_CLIENT_SECRET}
        APP_HOST_FQDN: ${env:APP_HOST_FQDN}

    functions:
      app:
        handler: application.lambda_handler
        events:
          - http:
              path: /{proxy+}
              method: ANY
          - http:
              path: /
              method: ANY
        timeout: 29
        memorySize: 512

    plugins:
      - serverless-domain-manager

Container Deployment
---------------------

.. code-block:: dockerfile

    # Dockerfile
    FROM public.ecr.aws/lambda/python:3.11

    COPY requirements.txt .
    RUN pip install -r requirements.txt

    COPY . .

    CMD ["application.lambda_handler"]

Local Development
-----------------

.. code-block:: python

    # application.py
    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(fastapi_app, host="0.0.0.0", port=5000, reload=True)

Then run:

.. code-block:: bash

    poetry install
    poetry run python application.py

Web Interface Customization
---------------------------

Template Customization for MCP Apps
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Customize the web interface to show MCP-specific functionality:

.. code-block:: html

    <!-- templates/aw-actor-www-root.html -->
    <div class="mcp-stats">
        <h3>MCP Usage Statistics</h3>
        <div class="stats-grid">
            <div class="stat">
                <span class="value">{{ properties.get('tool_usage_count', 0) }}</span>
                <span class="label">Tools Used</span>
            </div>
            <div class="stat">
                <span class="value">{{ properties.keys()|select('startswith', 'note_')|list|length }}</span>
                <span class="label">Notes Created</span>
            </div>
        </div>
    </div>

MCP-Specific Property Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Show MCP-related properties in a dedicated section:

.. code-block:: html

    <!-- In templates/aw-actor-www-properties.html -->
    <div class="property-sections">
        <section class="mcp-data">
            <h3>MCP Data</h3>
            {% for name, value in properties.items() %}
                {% if name.startswith('note_') or name.startswith('fetch_') %}
                <div class="property-item">
                    <span class="name">{{ name }}</span>
                    <span class="value">{{ value }}</span>
                </div>
                {% endif %}
            {% endfor %}
        </section>

        <section class="system-properties">
            <h3>System Properties</h3>
            {% for name, value in properties.items() %}
                {% if name in ['email', 'created_at', 'actor_type'] %}
                <div class="property-item readonly">
                    <span class="name">{{ name }}</span>
                    <span class="value">{{ value }}</span>
                    {% if name in read_only_properties %}
                    <span class="badge">Read-only</span>
                    {% endif %}
                </div>
                {% endif %}
            {% endfor %}
        </section>
    </div>

Testing MCP Applications
------------------------

Unit Testing Tools and Prompts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # test_mcp_tools.py
    import unittest
    from shared_mcp.tools import setup_mcp_tools
    from actingweb.interface import ActingWebApp, ActorInterface

    class TestMCPTools(unittest.TestCase):
        def setUp(self):
            self.app = ActingWebApp(
                aw_type="urn:test:example.com:mcp",
                database="dynamodb"
            )
            setup_mcp_tools(self.app)
            
            self.actor = ActorInterface.create(
                creator="test@example.com", 
                config=self.app.get_config()
            )
            
        def test_search_tool(self):
            # Add test data
            self.actor.properties.test_note = "This is a test note about Python"

            # Execute the registered action hook (tool)
            result = self.app.hooks.execute_action_hooks(
                self.actor, "search", {"query": "Python"}
            )
            self.assertIn("test_note", result)
            self.assertIn("Python", result)
            
        def test_create_note_tool(self):
            result = self.app.hooks.execute_action_hooks(
                self.actor,
                "create_note",
                {"title": "Test Title", "content": "Test content"},
            )

            self.assertTrue("status" in result or "Created note" in str(result))

            # Check that note was stored
            notes = [k for k in self.actor.properties.keys() if k.startswith("note_")]
            self.assertTrue(len(notes) > 0)

Integration Testing with FastAPI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # test_integration.py
    from fastapi.testclient import TestClient
    from application import fastapi_app

    def test_mcp_endpoint():
        client = TestClient(fastapi_app)
        
        # Test that MCP endpoint requires authentication
        response = client.get("/mcp")
        assert response.status_code == 401
        
        # Test health endpoint
        response = client.get("/health")
        assert response.status_code == 200

Best Practices
--------------

Security
~~~~~~~~

1. **Always validate MCP tool parameters** before processing
2. **Use property hooks to control access** to sensitive data
3. **Sanitize user input** in MCP tools and prompts
4. **Implement rate limiting** for expensive operations
5. **Use environment variables** for sensitive configuration

Performance
~~~~~~~~~~~

1. **Cache expensive operations** using actor properties or attributes
2. **Limit response sizes** from MCP tools (especially fetch operations)
3. **Use background tasks** for long-running operations
4. **Implement pagination** for large data sets
5. **Monitor memory usage** in Lambda deployments
6. **Initialize permission system at startup** for optimal MCP performance (see Performance Optimization section)

MCP Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

ActingWeb v3.3+ includes intelligent caching for MCP endpoints that provides significant performance improvements:

**Automatic Performance Gains:**

- **50x faster authentication** for repeated requests (50ms → 1ms)
- **90%+ cache hit rates** for typical MCP usage patterns
- **Sub-millisecond response times** after cache warmup
- **Zero configuration required** - caching is automatic and transparent

**Permission Initialization (Automatic):**

The ActingWeb permission system is **automatically initialized** when you integrate with Flask or FastAPI - no manual setup required:

.. code-block:: python

    # Automatic initialization happens here - nothing else needed!
    integration = app.integrate_fastapi(fastapi_app, templates_dir=templates_dir)
    
    # Or for Flask:
    integration = app.integrate_flask(flask_app)

**Manual Initialization (Optional):**

If you need to initialize the permission system before integration (e.g., for testing), you can still call it manually:

.. code-block:: python

    # Optional - only needed for advanced use cases
    try:
        from actingweb.permission_initialization import initialize_permission_system
        initialize_permission_system(app.get_config())
        logger.info("ActingWeb permission system initialized manually")
    except Exception as e:
        logger.debug(f"Permission system initialization failed: {e}")
        # System will fall back to basic functionality

**Performance Monitoring:**

The MCP handler automatically logs cache statistics:

.. code-block:: text

    MCP cache stats - Token hits: 13, Actor hits: 13, Trust hits: 12

**Cache Behavior:**

- **First request**: Full authentication (~50ms) - populates cache
- **Subsequent requests**: Cached authentication (~1ms) - serves from memory
- **Cache TTL**: 5 minutes (automatically cleaned up)
- **Memory efficient**: Only active sessions cached

**What Gets Cached:**

1. **Token validation** - OAuth2 server lookups eliminated
2. **Actor loading** - DynamoDB actor retrieval cached
3. **Trust relationships** - Permission context cached per actor

This optimization is particularly beneficial for AI assistants making multiple consecutive requests, which is the typical MCP usage pattern.

Data Management
~~~~~~~~~~~~~~~

1. **Use consistent property naming** (e.g., ``note_*``, ``fetch_*``)
2. **Store timestamps** for all user-generated data
3. **Implement data cleanup** for temporary data
4. **Use attributes** for global/shared data
5. **Handle data migration** when updating schemas

Monitoring and Logging
~~~~~~~~~~~~~~~~~~~~~~

1. **Log MCP tool usage** with appropriate detail levels
2. **Track user activity** through property access
3. **Monitor authentication failures** and security events
4. **Use structured logging** for better analysis
5. **Implement health checks** for all dependencies

Example: Complete MCP Application
---------------------------------

Here's a complete example of a specialized MCP application for note-taking:

.. code-block:: python

    # notes_mcp_app.py
    import os
    from datetime import datetime
    from typing import Optional, Dict, Any
    from fastapi import FastAPI
    from mangum import Mangum
    from actingweb.interface import ActingWebApp, ActorInterface

    # Initialize FastAPI
    app = FastAPI(
        title="Notes MCP Server",
        description="Personal note-taking with MCP integration",
        version="1.0.0"
    )

    # Initialize ActingWeb
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:example.com:notes-mcp",
        database="dynamodb",
        fqdn=os.getenv("APP_HOST_FQDN", "localhost")
    ).with_oauth(
        client_id=os.getenv("OAUTH_CLIENT_ID"),
        client_secret=os.getenv("OAUTH_CLIENT_SECRET")
    ).with_web_ui()

    # Initialize actors after creation
    @aw_app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs):
        # Set initial properties
        actor.properties.email = actor.creator
        actor.properties.created_at = datetime.now().isoformat()
        actor.properties.note_count = 0

    # Property hooks
    @aw_app.property_hook("email")
    def protect_email(actor, operation, value, path):
        return None if operation in ["put", "post", "delete"] else value

    @aw_app.property_hook("note_count")
    def protect_note_count(actor, operation, value, path):
        return None if operation in ["put", "post", "delete"] else value

    # MCP Tools
    from actingweb.mcp import mcp_tool

    @aw_app.action_hook("create_note")
    @mcp_tool(description="Create a new note with title, content, and tags")
    def create_note(actor: ActorInterface, action_name: str, params: Dict[str, Any]) -> str:
        """Create a new note with title, content, and optional tags."""
        title = params.get("title", "Untitled")
        content = params.get("content", "")
        tags = params.get("tags", "")
        note_id = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        note_data = {
            "id": note_id,
            "title": title,
            "content": content,
            "tags": tags.split(",") if tags else [],
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat()
        }
        
        actor.properties[note_id] = note_data
        
        # Update note count
        current_count = actor.properties.get("note_count", 0)
        actor.properties.note_count = current_count + 1
        
        return f"Created note '{title}' with ID {note_id}"

    @aw_app.action_hook("search_notes")
    @mcp_tool(description="Search notes by content, title, or tags")
    def search_notes(actor: ActorInterface, action_name: str, params: Dict[str, Any]) -> str:
        """Search notes by content, title, or tags."""
        query = str(params.get("query", ""))
        tag = str(params.get("tag", ""))
        results = []
        
        for key, value in actor.properties.items():
            if key.startswith("note_") and isinstance(value, dict):
                note = value
                
                # Search in title and content
                if query.lower() in note.get("title", "").lower() or \\
                   query.lower() in note.get("content", "").lower():
                    
                    # Filter by tag if specified
                    if not tag or tag.lower() in [t.lower() for t in note.get("tags", [])]:
                        results.append(
                            f"**{note.get('title')}** ({note.get('id')})\\n"
                            f"{note.get('content')[:100]}...\\n"
                            f"Tags: {', '.join(note.get('tags', []))}\\n"
                        )
        
        if not results:
            return f"No notes found for query '{query}'"
        
        return "\\n---\\n".join(results)

    @aw_app.action_hook("list_tags")
    @mcp_tool(description="List all tags used in notes")
    def list_tags(actor: ActorInterface, action_name: str, params: Dict[str, Any]) -> str:
        """List all tags used in notes."""
        all_tags = set()
        
        for key, value in actor.properties.items():
            if key.startswith("note_") and isinstance(value, dict):
                note_tags = value.get("tags", [])
                all_tags.update(note_tags)
        
        if not all_tags:
            return "No tags found"
        
        return "Available tags: " + ", ".join(sorted(all_tags))

    # MCP Prompts
    from actingweb.mcp import mcp_prompt

    @aw_app.method_hook("summarize_notes")
    @mcp_prompt(description="Summarize notes, optionally filtered by topic")
    def summarize_notes(actor: ActorInterface, method_name: str, params: Dict[str, Any]) -> str:
        """Generate a summary of notes, optionally filtered by topic."""
        topic = str(params.get("topic", ""))
        notes = []
        
        for key, value in actor.properties.items():
            if key.startswith("note_") and isinstance(value, dict):
                if not topic or topic.lower() in value.get("title", "").lower() or \\
                   topic.lower() in value.get("content", "").lower():
                    notes.append(value)
        
        if not notes:
            return f"No notes found{' for topic: ' + topic if topic else ''}"
        
        notes_text = "\\n".join([
            f"**{note.get('title')}**\\n{note.get('content')}\\n"
            for note in notes
        ])
        
        return f"""Please summarize the following notes{' about ' + topic if topic else ''}:

    {notes_text}

    Provide:
    1. Key themes and topics
    2. Important insights or conclusions
    3. Action items or next steps mentioned
    4. Connections between different notes
    """

    # Integrate with FastAPI
    aw_app.integrate_fastapi(app)

    # AWS Lambda handler
    lambda_handler = Mangum(app, lifespan="off")

    # Local development
    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=5000, reload=True)

This example demonstrates all the key concepts for building production-ready MCP applications with ActingWeb.

OAuth2 Client Management
------------------------

MCP applications with ActingWeb support dynamic OAuth2 client registration for AI assistants. This allows users to generate API credentials that AI assistants can use to authenticate and access their personal data.

Client Registration API
~~~~~~~~~~~~~~~~~~~~~~~

The application provides an OAuth2 client generation endpoint:

.. code-block:: python

    @fastapi_app.post("/{actor_id}/api/generate-oauth-client")
    async def generate_oauth_client(actor_id: str, request: Request):
        """Generate OAuth2 client credentials for AI assistants."""
        from actingweb.oauth2_server.client_registry import MCPClientRegistry
        
        # Parse request body
        body = await request.json()
        client_name = body.get("client_name", "AI Assistant Connector")
        trust_type = body.get("trust_type", "mcp_client")
        
        # Dynamic client registration data (RFC 7591)
        registration_data = {
            "client_name": client_name,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp",
            "trust_type": trust_type,
        }
        
        # Register client
        client_registry = MCPClientRegistry(app.get_config())
        client_data = client_registry.register_client(actor_id, registration_data)
        
        return JSONResponse(content={
            "client_id": client_data["client_id"],
            "client_secret": client_data["client_secret"],
            "client_name": client_name,
            "trust_type": trust_type,
            "created_at": client_data.get("created_at")
        })

Client Deletion API
~~~~~~~~~~~~~~~~~~~

Users can delete OAuth2 clients they no longer need:

.. code-block:: python

    @fastapi_app.delete("/{actor_id}/api/oauth-client/{client_id}")
    async def delete_oauth_client(actor_id: str, client_id: str):
        """Delete an OAuth2 client."""
        from actingweb.oauth2_server.client_registry import MCPClientRegistry
        
        client_registry = MCPClientRegistry(app.get_config())
        
        # Verify client belongs to actor
        client_data = client_registry._load_client(client_id)
        if client_data.get("actor_id") != actor_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Delete the client
        success = client_registry.delete_client(client_id)
        
        return JSONResponse(content={
            "success": success, 
            "message": "OAuth client deleted successfully"
        })

Web Interface Integration
--------------------------

Display OAuth2 clients in the web interface by enhancing the WWW handler:

.. code-block:: python

    # In actingweb/handlers/www.py
    def _get_oauth_clients_for_actor(self, actor_id: str):
        """Get registered OAuth2 clients for an actor."""
        from ..oauth2_server.client_registry import MCPClientRegistry
        import datetime
        
        client_registry = MCPClientRegistry(self.config)
        clients = client_registry.list_clients_for_actor(actor_id)
        
        # Process client data for template display
        processed_clients = []
        for client in clients:
            processed_client = {
                "client_id": client.get("client_id", ""),
                "client_name": client.get("client_name", "Unknown Client"),
                "trust_type": client.get("trust_type", "mcp_client"),
                "created_at": datetime.datetime.fromtimestamp(
                    client.get("created_at", 0)
                ).strftime("%Y-%m-%d %H:%M"),
                "status": "active",
            }
            processed_clients.append(processed_client)
        
        return processed_clients

Then include OAuth2 clients in the trust page template variables:

.. code-block:: python

    # In the trust page handler
    oauth_clients = self._get_oauth_clients_for_actor(actor_id)
    
    self.response.template_values = {
        "id": myself.id,
        "trusts": relationships,
        "oauth_clients": oauth_clients,  # Add this line
        "url": f"{urls['actor_root']}/",
        "actor_root": urls["actor_root"],
        "actor_www": urls["actor_www"],
    }

Template Integration
---------------------

Display OAuth2 clients in templates with delete functionality:

.. code-block:: html

    <!-- OAuth2 Clients Section -->
    <div class="connections-card">
        <h3>🔑 API Clients</h3>
        
        {% if oauth_clients %}
        <table>
            <thead>
                <tr>
                    <th>Client</th>
                    <th>Type</th>
                    <th>Created</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for client in oauth_clients %}
                <tr>
                    <td>{{ client.client_name }}</td>
                    <td>{{ client.trust_type }}</td>
                    <td>{{ client.created_at }}</td>
                    <td>{{ client.status }}</td>
                    <td>
                        <button onclick="deleteOAuthClient('{{ client.client_id }}', '{{ client.client_name }}')">
                            Delete
                        </button>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p>No API clients registered. Generate credentials to connect AI assistants.</p>
        {% endif %}
    </div>

    <script>
        async function deleteOAuthClient(clientId, clientName) {
            if (!confirm(`Delete OAuth2 client "${clientName}"?`)) return;
            
            const response = await fetch(`{{ actor_root }}/api/oauth-client/${clientId}`, {
                method: 'DELETE',
                credentials: 'include'
            });
            
            if (response.ok) {
                alert('Client deleted successfully!');
                window.location.reload();
            } else {
                alert('Error deleting client');
            }
        }
    </script>

Client Registry Features
~~~~~~~~~~~~~~~~~~~~~~~~

The ``MCPClientRegistry`` class provides comprehensive client management:

* **Dynamic Registration**: RFC 7591 compliant client registration
* **Per-Actor Storage**: Clients are stored in actor-specific attribute buckets
* **Global Index**: Fast client lookup using global index system
* **Secure Deletion**: Removes client from both actor storage and global index
* **Trust Type Integration**: Clients inherit permissions from trust type system

Usage in AI Assistants
~~~~~~~~~~~~~~~~~~~~~~

Generated OAuth2 credentials can be used with AI assistants:

1. **Client Registration**: User generates credentials via web interface
2. **OAuth2 Flow**: AI assistant uses authorization code flow
3. **Token Exchange**: Client credentials exchanged for access tokens
4. **MCP Access**: Authenticated access to user's MCP tools and data

The OAuth2 system integrates seamlessly with ActingWeb's trust and permission system, ensuring secure access control for AI assistant connections.

OAuth2ClientManager Interface
------------------------------

For developer-friendly OAuth2 client management, ActingWeb provides the ``OAuth2ClientManager`` interface that follows the same patterns as other ActingWeb interfaces like ``TrustManager`` and ``PropertyStore``.

.. code-block:: python

    from actingweb.interface.oauth_client_manager import OAuth2ClientManager

    # Initialize manager for specific actor
    client_manager = OAuth2ClientManager(actor_id, config)

    # Create new OAuth2 client
    client = client_manager.create_client("My AI Assistant")
    print(f"Client ID: {client['client_id']}")
    print(f"Client Secret: {client['client_secret']}")

    # List all clients for actor
    clients = client_manager.list_clients()
    for client in clients:
        print(f"{client['client_name']} - {client['created_at_formatted']}")

    # Get specific client details
    client_data = client_manager.get_client("mcp_abc123...")
    if client_data:
        print(f"Client: {client_data['client_name']}")

    # Delete client
    success = client_manager.delete_client("mcp_abc123...")
    if success:
        print("Client deleted successfully")

    # Get client statistics
    stats = client_manager.get_client_stats()
    print(f"Total clients: {stats['total_clients']}")
    print(f"Trust types: {stats['trust_types']}")

    # Convenience properties and methods
    print(f"Client count: {client_manager.client_count}")
    print(f"Has clients: {bool(client_manager)}")
    
    # Iteration support
    for client in client_manager:
        print(f"Client: {client['client_name']}")

Interface Features
------------------

The ``OAuth2ClientManager`` provides these developer-friendly features:

* **Formatted Timestamps**: Automatic conversion of Unix timestamps to readable format
* **Status Information**: Enhanced client metadata with activity status
* **Validation**: Built-in client ownership validation before operations
* **Statistics**: Convenient methods for client analytics and reporting
* **Pythonic Interface**: Support for ``len()``, ``bool()``, and iteration
* **Error Handling**: Comprehensive logging and error management
* **Trust Type Integration**: Seamless integration with ActingWeb's trust system

This interface abstracts away the complexity of the underlying ``MCPClientRegistry`` while providing a clean, consistent API that follows ActingWeb's established interface patterns.
