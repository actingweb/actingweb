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

Available events: ``actor_created``, ``actor_deleted``, ``oauth_success``, ``trust_approved``, ``trust_deleted``.

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

Permissions
-----------

Permission checks are integrated transparently with hooks. See :doc:`../unified-access-control-simple` for the simple guide and :doc:`../unified-access-control` for full details.
