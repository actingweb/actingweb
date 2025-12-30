======
Hooks
======

Overview
--------

Use decorators on your ``ActingWebApp`` instance to customize behavior without subclassing:

- ``@app.property_hook(name)``: control access/validation for properties
- ``@app.method_hook(name)``: implement read‑only method endpoints
- ``@app.action_hook(name)``: implement side‑effecting actions
- ``@app.lifecycle_hook(event)``: react to lifecycle events
- ``@app.subscription_hook``: handle subscription callbacks

Property Hooks
--------------

.. code-block:: python

   @app.property_hook("email")
   def handle_email(actor, operation, value, path):
       if operation == "get":
           return value if actor.is_owner() else None  # hide from others
       if operation in ("put", "post"):
           return value.lower() if "@" in value else None
       return value

Method Hooks
------------

.. code-block:: python

   @app.method_hook("get_profile")
   def get_profile(actor, method_name, data):
       return {"email": actor.properties.get("email")}

Action Hooks
------------

.. code-block:: python

   @app.action_hook("send_notification")
   def send_notification(actor, action_name, data):
       # send side‑effecting notification
       return {"status": "sent"}

Lifecycle Hooks
---------------

.. code-block:: python

   @app.lifecycle_hook("actor_created")
   def on_actor_created(actor, **kwargs):
       actor.properties.created_at = datetime.now().isoformat()

   @app.lifecycle_hook("trust_initiated")
   def on_trust_initiated(actor, peer_id, relationship, trust_data, **kwargs):
       # Called when this actor initiates a trust request to a peer
       print(f"Trust initiated to {peer_id}")

   @app.lifecycle_hook("trust_request_received")
   def on_trust_request_received(actor, peer_id, relationship, trust_data, **kwargs):
       # Called when this actor receives a trust request from a peer
       notify_user(actor, f"New trust request from {peer_id}")

   @app.lifecycle_hook("trust_fully_approved_local")
   def on_trust_fully_approved_local(actor, peer_id, relationship, trust_data, **kwargs):
       # Called when this actor approves, completing mutual approval
       notify_user(actor, f"You approved! Relationship with {peer_id} established")

   @app.lifecycle_hook("trust_fully_approved_remote")
   def on_trust_fully_approved_remote(actor, peer_id, relationship, trust_data, **kwargs):
       # Called when peer approves, completing mutual approval
       notify_user(actor, f"{peer_id} approved your request! Relationship established")

Available events: ``actor_created``, ``actor_deleted``, ``oauth_success``, ``trust_initiated``, ``trust_request_received``, ``trust_fully_approved_local``, ``trust_fully_approved_remote``, ``trust_deleted``.

Subscription Hook
-----------------

.. code-block:: python

   @app.subscription_hook
   def on_subscription(actor, subscription, peer_id, data):
       if subscription.get("target") == "properties" and "status" in data:
           actor.properties[f"peer_{peer_id}_status"] = data["status"]
       return True

MCP Decorators
--------------

Expose hooks via MCP:

- Tools: decorate an action hook with ``@mcp_tool``
- Prompts: decorate a method hook with ``@mcp_prompt``
- Resources: decorate a method hook with ``@mcp_resource``

.. code-block:: python

   from actingweb.mcp import mcp_tool, mcp_prompt, mcp_resource

   @app.action_hook("create_note")
   @mcp_tool(description="Create a note")
   def create_note(actor, action_name, params):
       ...

   @app.method_hook("analyze_notes")
   @mcp_prompt(description="Analyze notes")
   def analyze_notes(actor, method_name, params):
       ...

   @app.method_hook("config")
   @mcp_resource(uri_template="config://{path}")
   def config_resource(actor, method_name, params):
       ...

Client-Specific Tool Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``@mcp_tool`` decorator supports client-specific filtering and descriptions:

.. code-block:: python

   @app.action_hook("sensitive_action")
   @mcp_tool(
       description="Perform a sensitive action",
       allowed_clients=["claude", "cursor"],  # Only allow Claude and Cursor
       client_descriptions={
           "claude": "Safely perform action with Claude's oversight",
           "cursor": "Execute action within Cursor IDE context"
       }
   )
   def sensitive_action(actor, action_name, params):
       return {"status": "executed safely"}

**Parameters:**

- ``allowed_clients``: List of client types that can access this tool. If None, tool is available to all clients. Supported types: ``"chatgpt"``, ``"claude"``, ``"cursor"``, ``"mcp_inspector"``, ``"universal"``
- ``client_descriptions``: Dict mapping client types to specific descriptions for safety and clarity

Runtime Context
---------------

Hooks receive fixed parameters (``actor``, ``name``, ``data``), but often need context about the current request (which client is calling, session info, etc.). ActingWeb provides a runtime context system to solve this:

.. code-block:: python

   from actingweb.runtime_context import RuntimeContext, get_client_info_from_context

   @app.action_hook("search")
   def handle_search(actor, action_name, data):
       # Get client information for customization
       client_info = get_client_info_from_context(actor)
       if client_info:
           client_type = client_info["type"]  # "mcp", "oauth2", "web"
           client_name = client_info["name"]  # "Claude", "ChatGPT", etc.

           # Customize response based on client
           if client_type == "mcp" and "claude" in client_name.lower():
               # Use Claude-optimized formatting
               return format_for_claude(results)

Context Types
~~~~~~~~~~~~~

- **MCP Context**: Set during MCP client authentication, contains trust relationship with client metadata
- **OAuth2 Context**: Set during OAuth2 authentication, contains client ID, user email, scopes
- **Web Context**: Set during web requests, contains session ID, user agent, IP address

.. code-block:: python

   @app.action_hook("custom_action")
   def custom_action(actor, action_name, data):
       runtime_context = RuntimeContext(actor)

       if runtime_context.get_request_type() == "mcp":
           mcp_context = runtime_context.get_mcp_context()
           trust_relationship = mcp_context.trust_relationship
           # Access client_name, client_version, etc.

       elif runtime_context.get_request_type() == "oauth2":
           oauth2_context = runtime_context.get_oauth2_context()
           # Access client_id, user_email, scopes

       elif runtime_context.get_request_type() == "web":
           web_context = runtime_context.get_web_context()
           # Access session_id, user_agent, ip_address

The runtime context is request-scoped and automatically managed by the framework.

Permissions
-----------

Permission checks are integrated transparently with hooks. See :doc:`../unified-access-control-simple` for the simple guide and :doc:`../unified-access-control` for full details.
