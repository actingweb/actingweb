========================================
Building MCP Applications with ActingWeb
========================================

This guide shows how to build Model Context Protocol (MCP) server applications using ActingWeb, following the patterns demonstrated in the ``actingweb_mcp`` example application.

Overview
========

An MCP server application with ActingWeb combines:

- **ActingWeb Framework**: Provides actor management, properties, trust relationships, and web interface
- **FastAPI Integration**: Modern ASGI web framework with automatic OpenAPI documentation
- **OAuth2 Authentication**: User authentication with Google, GitHub, or other providers
- **MCP Protocol Support**: Tools, prompts, and resources for AI language models
- **Per-User Data Isolation**: Each authenticated user gets their own actor with private data

Architecture Pattern
===================

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
===========

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
=======================

Create reusable MCP tools in ``shared_mcp/tools.py``:

.. code-block:: python

    # shared_mcp/tools.py
    import logging
    from typing import Optional, Dict, Any
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    logger = logging.getLogger(__name__)

    def setup_mcp_tools(aw_app):
        """Setup MCP tools for the ActingWeb application."""
        
        @aw_app.mcp_tool
        def search(query: str, actor_context: Optional[Dict[str, Any]] = None) -> str:
            """Search through the actor's data and properties."""
            if not actor_context:
                return "No actor context available"
            
            actor = actor_context.get("actor")
            if not actor:
                return "No actor available"
            
            results = []
            
            # Search through properties
            for key, value in actor.properties.items():
                if query.lower() in key.lower() or query.lower() in str(value).lower():
                    results.append(f"Property {key}: {value}")
            
            if not results:
                return f"No results found for '{query}'"
            
            return "\\n".join(results)

        @aw_app.mcp_tool
        def create_note(title: str, content: str, actor_context: Optional[Dict[str, Any]] = None) -> str:
            """Create a new note for the actor."""
            if not actor_context:
                return "No actor context available"
            
            actor = actor_context.get("actor")
            if not actor:
                return "No actor available"
            
            # Store note in properties
            note_key = f"note_{datetime.now().isoformat()}"
            note_data = {
                "title": title,
                "content": content,
                "created": datetime.now().isoformat()
            }
            
            actor.properties[note_key] = note_data
            
            return f"Created note '{title}' successfully"

        @aw_app.mcp_tool
        def fetch_url(url: str, actor_context: Optional[Dict[str, Any]] = None) -> str:
            """Fetch content from a URL."""
            try:
                import requests
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                # Store fetch history in actor properties
                if actor_context and actor_context.get("actor"):
                    actor = actor_context["actor"]
                    history_key = f"fetch_history_{datetime.now().isoformat()}"
                    actor.properties[history_key] = {
                        "url": url,
                        "timestamp": datetime.now().isoformat(),
                        "status_code": response.status_code
                    }
                
                return response.text[:5000]  # Limit response size
                
            except Exception as e:
                return f"Error fetching URL: {str(e)}"

MCP Prompts Implementation
=========================

Create prompt templates in ``shared_mcp/prompts.py``:

.. code-block:: python

    # shared_mcp/prompts.py
    from typing import Optional, Dict, Any

    def setup_mcp_prompts(aw_app):
        """Setup MCP prompts for the ActingWeb application."""
        
        @aw_app.mcp_prompt
        def analyze_notes(actor_context: Optional[Dict[str, Any]] = None) -> str:
            """Analyze all notes created by this actor."""
            if not actor_context:
                return "No actor context available"
            
            actor = actor_context.get("actor")
            if not actor:
                return "No actor available"
            
            # Collect all notes
            notes = []
            for key, value in actor.properties.items():
                if key.startswith("note_") and isinstance(value, dict):
                    notes.append(value)
            
            if not notes:
                return "You are analyzing notes for a user, but no notes were found."
            
            notes_text = "\\n".join([
                f"Title: {note.get('title', 'Untitled')}\\n"
                f"Content: {note.get('content', '')}\\n"
                f"Created: {note.get('created', 'Unknown')}\\n---"
                for note in notes
            ])
            
            return f"""You are analyzing the following notes for a user:

    {notes_text}

    Please provide insights about:
    1. Common themes or topics
    2. Sentiment analysis
    3. Suggestions for organization
    4. Action items or follow-ups identified
    """

        @aw_app.mcp_prompt  
        def create_meeting_prep(topic: str, actor_context: Optional[Dict[str, Any]] = None) -> str:
            """Create a meeting preparation prompt based on actor's data."""
            if not actor_context:
                return "No actor context available"
            
            actor = actor_context.get("actor")
            if not actor:
                return "No actor available"
            
            # Find relevant notes and data
            relevant_data = []
            for key, value in actor.properties.items():
                if topic.lower() in str(value).lower():
                    relevant_data.append(f"{key}: {value}")
            
            context = "\\n".join(relevant_data) if relevant_data else "No relevant data found."
            
            return f"""Prepare for a meeting about: {topic}

    Relevant information from your data:
    {context}

    Please help prepare for this meeting by:
    1. Summarizing key points from the relevant data
    2. Identifying potential questions to ask
    3. Suggesting discussion topics
    4. Recommending action items to propose
    """

Property Hooks for MCP Applications
==================================

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
==================

Configure OAuth2 authentication for your MCP server:

Environment Variables
--------------------

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
----------

1. Client accesses protected ``/mcp`` endpoint
2. Returns 401 with ``WWW-Authenticate`` header containing OAuth2 provider auth URL  
3. User authenticates with Google/GitHub
4. OAuth2 callback creates/finds ActingWeb actor based on user email
5. Bearer token provided for subsequent API access

Authentication in Application Code
---------------------------------

.. code-block:: python

    # The ActingWeb integration handles OAuth2 automatically
    # Authenticated users get access to their actor context in MCP tools

    @aw_app.mcp_tool
    def my_tool(param: str, actor_context: Optional[Dict[str, Any]] = None) -> str:
        if not actor_context:
            return "Authentication required"
        
        actor = actor_context.get("actor")
        user_email = actor.creator  # The authenticated user's email
        
        # Use actor.properties for per-user data storage
        actor.properties.last_tool_use = datetime.now().isoformat()
        
        return f"Tool executed for user {user_email}"

Deployment Patterns
==================

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
-------------------

.. code-block:: dockerfile

    # Dockerfile
    FROM public.ecr.aws/lambda/python:3.11

    COPY requirements.txt .
    RUN pip install -r requirements.txt

    COPY . .

    CMD ["application.lambda_handler"]

Local Development
----------------

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
===========================

Template Customization for MCP Apps
-----------------------------------

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
-------------------------------

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
=======================

Unit Testing Tools and Prompts
------------------------------

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
            
            # Test search
            result = search("Python", actor_context={"actor": self.actor})
            self.assertIn("test_note", result)
            self.assertIn("Python", result)
            
        def test_create_note_tool(self):
            result = create_note(
                "Test Title", 
                "Test content",
                actor_context={"actor": self.actor}
            )
            
            self.assertIn("Created note", result)
            
            # Check that note was stored
            notes = [k for k in self.actor.properties.keys() if k.startswith("note_")]
            self.assertTrue(len(notes) > 0)

Integration Testing with FastAPI
-------------------------------

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
==============

Security
--------

1. **Always validate MCP tool parameters** before processing
2. **Use property hooks to control access** to sensitive data
3. **Sanitize user input** in MCP tools and prompts
4. **Implement rate limiting** for expensive operations
5. **Use environment variables** for sensitive configuration

Performance
-----------

1. **Cache expensive operations** using actor properties or attributes
2. **Limit response sizes** from MCP tools (especially fetch operations)
3. **Use background tasks** for long-running operations
4. **Implement pagination** for large data sets
5. **Monitor memory usage** in Lambda deployments

Data Management
--------------

1. **Use consistent property naming** (e.g., ``note_*``, ``fetch_*``)
2. **Store timestamps** for all user-generated data
3. **Implement data cleanup** for temporary data
4. **Use attributes** for global/shared data
5. **Handle data migration** when updating schemas

Monitoring and Logging
---------------------

1. **Log MCP tool usage** with appropriate detail levels
2. **Track user activity** through property access
3. **Monitor authentication failures** and security events
4. **Use structured logging** for better analysis
5. **Implement health checks** for all dependencies

Example: Complete MCP Application
=================================

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
    @aw_app.mcp_tool
    def create_note(title: str, content: str, tags: str = "", 
                   actor_context: Optional[Dict[str, Any]] = None) -> str:
        """Create a new note with title, content, and optional tags."""
        if not actor_context:
            return "Authentication required"
        
        actor = actor_context["actor"]
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

    @aw_app.mcp_tool
    def search_notes(query: str, tag: str = "", 
                    actor_context: Optional[Dict[str, Any]] = None) -> str:
        """Search notes by content, title, or tags."""
        if not actor_context:
            return "Authentication required"
        
        actor = actor_context["actor"]
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

    @aw_app.mcp_tool
    def list_tags(actor_context: Optional[Dict[str, Any]] = None) -> str:
        """List all tags used in notes."""
        if not actor_context:
            return "Authentication required"
        
        actor = actor_context["actor"]
        all_tags = set()
        
        for key, value in actor.properties.items():
            if key.startswith("note_") and isinstance(value, dict):
                note_tags = value.get("tags", [])
                all_tags.update(note_tags)
        
        if not all_tags:
            return "No tags found"
        
        return "Available tags: " + ", ".join(sorted(all_tags))

    # MCP Prompts  
    @aw_app.mcp_prompt
    def summarize_notes(topic: str = "", actor_context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a summary of notes, optionally filtered by topic."""
        if not actor_context:
            return "Authentication required"
        
        actor = actor_context["actor"]
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