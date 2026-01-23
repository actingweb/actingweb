=================
ActorInterface
=================

Overview
--------

ActingWeb provides two actor classes:

- ``actingweb.actor.Actor``: low‑level, internal implementation (not for apps)
- ``actingweb.interface.ActorInterface``: high‑level, public API for apps

Always use ``ActorInterface`` in applications for a stable, developer‑friendly API with error handling and type hints.

Quick Start
-----------

.. code-block:: python

   from actingweb.interface import ActingWebApp, ActorInterface

   app = (
       ActingWebApp(
           aw_type="urn:actingweb:example.com:myapp",
           database="dynamodb",
           fqdn="myapp.example.com"
       ).with_web_ui().with_devtest()
   )

   @app.lifecycle_hook("actor_created")
   def on_actor_created(actor: ActorInterface, **kwargs):
       actor.properties.email = actor.creator

   # app.run(port=5000)  # or integrate with Flask/FastAPI

Creating and Loading Actors
---------------------------

.. code-block:: python

   # Create
   actor = ActorInterface.create(creator="user@example.com", config=app.get_config())

   # Load by id
   actor2 = ActorInterface.get_by_id(actor.id, config=app.get_config())

   # Load by creator
   actor3 = ActorInterface.get_by_creator("user@example.com", config=app.get_config())

Properties (Key–Value)
----------------------

``actor.properties`` behaves like a dict with convenience accessors:

.. code-block:: python

   # Set
   actor.properties.email = "user@example.com"
   actor.properties["settings"] = {"theme": "dark"}

   # Get
   email = actor.properties.email
   theme = actor.properties.get("settings", {}).get("theme")

   # Exists / iterate
   if "email" in actor.properties:
       for k, v in actor.properties.items():
           print(k, v)

PropertyStore Methods
~~~~~~~~~~~~~~~~~~~~~

- ``get(key, default=None)``: Fetch with default
- ``set(key, value)``: Set value
- ``delete(key)``: Remove property
- ``update(mapping)``: Bulk update
- ``to_dict()``: Convert to plain dict

Trust and Subscriptions
-----------------------

Trust relationships and subscriptions are available via:

.. code-block:: python

   # Trust
   actor.trust.create_relationship(peer_url="https://peer/actor123", relationship="friend")
   for rel in actor.trust.relationships:
       print(rel.peer_id, rel.relationship)

   # Subscriptions
   actor.subscriptions.subscribe_to_peer(peer_id="peer123", target="properties")
   actor.subscriptions.notify_subscribers(target="properties", data={"status": "active"})

Peer Profile Caching
~~~~~~~~~~~~~~~~~~~~

When peer profile caching is enabled (via ``app.with_peer_profile()``), you can access cached profile attributes:

.. code-block:: python

   # Get cached profile
   profile = actor.trust.get_peer_profile(peer_id)
   if profile:
       print(f"Connected with {profile.displayname}")
       print(f"Email: {profile.email}")

   # Manual refresh
   profile = actor.trust.refresh_peer_profile(peer_id)

   # Async refresh (FastAPI)
   profile = await actor.trust.refresh_peer_profile_async(peer_id)

See :doc:`../guides/trust-relationships` for details on enabling and configuring profile caching.

Peer Capabilities Caching
~~~~~~~~~~~~~~~~~~~~~~~~~

When peer capabilities caching is enabled (via ``app.with_peer_capabilities()``), you can discover what methods and actions trusted peers expose:

.. code-block:: python

   # Get cached capabilities (methods + actions)
   capabilities = actor.trust.get_peer_capabilities(peer_id)
   if capabilities:
       print(f"Methods: {capabilities.get_method_names()}")
       print(f"Actions: {capabilities.get_action_names()}")

       # Get specific method
       method = capabilities.get_method("get_data")
       if method:
           print(f"{method.name}: {method.description}")

   # Convenience methods
   methods = actor.trust.get_peer_methods(peer_id)  # Just methods
   actions = actor.trust.get_peer_actions(peer_id)  # Just actions

   # Manual refresh
   capabilities = actor.trust.refresh_peer_capabilities(peer_id)

   # Async refresh (FastAPI)
   capabilities = await actor.trust.refresh_peer_capabilities_async(peer_id)

See :doc:`../guides/trust-relationships` for details on enabling and configuring capabilities caching.

Peer Permissions Caching
~~~~~~~~~~~~~~~~~~~~~~~~

When peer permissions caching is enabled (via ``app.with_peer_permissions()``), you can check what permissions peers have granted to your actor:

.. code-block:: python

   from actingweb.peer_permissions import get_peer_permission_store

   store = get_peer_permission_store(actor.config)

   # Get cached permissions
   perms = store.get_permissions(actor.id, peer_id)
   if perms:
       # Check property access
       if perms.has_property_access("memory_travel", "read"):
           # Can read this property from peer
           pass

       # Check method access
       if perms.has_method_access("sync_data"):
           # Can call this method on peer
           pass

       # Check MCP tool access
       if perms.has_tool_access("search"):
           # Can use this tool on peer
           pass

   # Manual refresh
   from actingweb.peer_permissions import fetch_peer_permissions
   perms = fetch_peer_permissions(actor, peer_id)

   # Async refresh (FastAPI)
   from actingweb.peer_permissions import fetch_peer_permissions_async
   perms = await fetch_peer_permissions_async(actor, peer_id)

**PeerPermissions Access Methods:**

- ``has_property_access(name, operation)`` - Check property permission (operation: read, write, subscribe, delete)
- ``has_method_access(name)`` - Check method permission
- ``has_action_access(name)`` - Check action permission
- ``has_tool_access(name)`` - Check MCP tool permission
- ``has_resource_access(uri)`` - Check MCP resource permission
- ``has_prompt_access(name)`` - Check MCP prompt permission

See :doc:`../guides/trust-relationships` for details on enabling and configuring permissions caching.

Next
----

- Hooks: :doc:`../guides/hooks`
- Large collections: :doc:`../guides/property-lists`
- Trust details: :doc:`../guides/trust-relationships`
- Subscriptions: :doc:`../guides/subscriptions`
