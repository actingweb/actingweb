=============
Trust Manager
=============

Overview
--------

Manage peer relationships between actors and (optionally) customize permissions per relationship.

Basic Usage
-----------

.. code-block:: python

   # Create relationship
   rel = actor.trust.create_relationship(
       peer_url="https://peer.example.com/actor123",
       relationship="friend",
   )

   # Inspect relationships
   for rel in actor.trust.relationships:
       print(rel.peer_id, rel.relationship)

   # Approve
   actor.trust.approve_relationship(peer_id="peer123")

Permissions (Per Relationship)
-------------------------------

For apps using unified access control, you can set per‑relationship overrides. See :doc:`../unified-access-control-simple` for the simple guide.

Programmatic example:

.. code-block:: python

   from actingweb.trust_permissions import get_trust_permission_store, create_permission_override

   store = get_trust_permission_store(config)
   perms = create_permission_override(
       actor_id=actor.id,
       peer_id="peer123",
       trust_type="friend",
       permission_updates={
           "properties": {"patterns": ["public/*", "notes/*"], "operations": ["read", "write"]},
           "methods": {"allowed": ["get_*", "create_*"], "denied": ["delete_*"]},
       },
   )
   store.store_permissions(perms)

REST API
--------

- ``GET /{actor_id}/trust/{relationship}/{peer_id}?permissions=true``
- ``PUT /{actor_id}/trust/{relationship}/{peer_id}/permissions``
- ``GET /{actor_id}/trust/{relationship}/{peer_id}/permissions``
- ``DELETE /{actor_id}/trust/{relationship}/{peer_id}/permissions``

See also: :doc:`../unified-access-control` for the full system.
