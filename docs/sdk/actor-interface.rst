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

Next
----

- Hooks: :doc:`hooks`
- Large collections: :doc:`property-lists`
- Trust details: :doc:`trust-manager`
- Subscriptions: :doc:`subscriptions`
