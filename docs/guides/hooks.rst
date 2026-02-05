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

Method hooks implement RPC-style functions. You can add metadata for API discovery:

.. code-block:: python

   # Simple method hook
   @app.method_hook("get_profile")
   def get_profile(actor, method_name, data):
       return {"email": actor.properties.get("email")}

   # Method hook with metadata for API discovery
   @app.method_hook(
       "calculate",
       description="Perform a mathematical calculation",
       input_schema={
           "type": "object",
           "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
           "required": ["x", "y"]
       },
       annotations={"readOnlyHint": True}
   )
   def calculate(actor, method_name, data):
       return {"result": data["x"] + data["y"]}

   # Method hook with auto-generated schemas from TypedDict
   from typing import TypedDict

   class ProfileInput(TypedDict):
       include_email: bool

   class ProfileOutput(TypedDict):
       name: str
       email: str | None

   @app.method_hook("get_profile_detailed", description="Get user profile")
   def get_profile_detailed(actor, method_name, data: ProfileInput) -> ProfileOutput:
       return {
           "name": actor.properties.get("name"),
           "email": actor.properties.get("email") if data.get("include_email") else None
       }

Action Hooks
------------

Action hooks implement side-effecting operations. You can add metadata for API discovery:

.. code-block:: python

   # Simple action hook
   @app.action_hook("send_notification")
   def send_notification(actor, action_name, data):
       # send side‑effecting notification
       return {"status": "sent"}

   # Action hook with metadata for API discovery
   @app.action_hook(
       "delete_item",
       description="Permanently delete an item",
       input_schema={"type": "object", "properties": {"item_id": {"type": "string"}}},
       annotations={"destructiveHint": True}
   )
   def delete_item(actor, action_name, data):
       delete_from_database(data["item_id"])
       return {"status": "deleted"}

   # Action hook with auto-generated schemas from TypedDict
   from typing import TypedDict

   class CreateNoteInput(TypedDict):
       title: str
       content: str

   class CreateNoteOutput(TypedDict):
       note_id: str
       created_at: str

   @app.action_hook("create_note", description="Create a new note")
   def create_note(actor, action_name, data: CreateNoteInput) -> CreateNoteOutput:
       note_id = save_note(data["title"], data["content"])
       return {"note_id": note_id, "created_at": datetime.now().isoformat()}

Discovering Methods and Actions
-------------------------------

Clients can discover available methods and actions via GET requests:

.. code-block:: bash

   # Discover available methods
   curl https://myapp.example.com/<actor_id>/methods

   # Discover available actions
   curl https://myapp.example.com/<actor_id>/actions

The response includes metadata for each hook:

.. code-block:: text

   {
     "methods": [
       {
         "name": "calculate",
         "description": "Perform a mathematical calculation",
         "input_schema": {"type": "object", "properties": {...}},
         "output_schema": null,
         "annotations": {"readOnlyHint": true}
       }
     ]
   }

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

   @app.lifecycle_hook("subscription_deleted")
   def on_subscription_deleted(actor, peer_id, subscription_id, subscription_data, **kwargs):
       # Called when a subscription is deleted (by us or by peer)
       initiated_by_peer = kwargs.get("initiated_by_peer", False)
       if initiated_by_peer:
           # Peer unsubscribed from us - revoke their permissions
           revoke_permissions(actor, peer_id)
           notify_user(actor, f"{peer_id} unsubscribed from your data")

Available events: ``actor_created``, ``actor_deleted``, ``oauth_success``, ``trust_initiated``, ``trust_request_received``, ``trust_fully_approved_local``, ``trust_fully_approved_remote``, ``trust_deleted``, ``subscription_deleted``.

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

Permission checks are integrated transparently with hooks. See :doc:`access-control-simple` for the simple guide and :doc:`access-control` for full details.
