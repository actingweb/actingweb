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

Trust and Subscriptions Lifecycle
---------------------------------

Trust relationships and subscriptions are tightly coupled. Understanding their lifecycle is essential for reliable peer communication.

**Subscription Requirements**

Subscriptions require an established trust relationship:

.. code-block:: python

   # 1. First establish trust
   rel = actor.trust.create_relationship(
       peer_url="https://peer.example.com/actor123",
       relationship="friend",
   )

   # 2. Approve the relationship (if needed)
   actor.trust.approve_relationship(peer_id="peer123")

   # 3. Now subscriptions work
   actor.subscriptions.subscribe_to_peer(
       peer_id="peer123", target="properties"
   )

**Trust States and Subscription Behavior**

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Trust State
     - Subscription Behavior
   * - Pending (not approved)
     - Subscriptions can be created but callbacks may be rejected
   * - Approved
     - Full subscription functionality, callbacks delivered
   * - Deleted
     - All subscriptions terminated, peer data cleaned up (if ``auto_cleanup=True``)

**Automatic Cleanup on Trust Deletion**

When ``auto_cleanup=True`` is enabled (default), deleting a trust relationship triggers automatic cleanup:

.. code-block:: python

   # Enable automatic cleanup
   app.with_subscription_processing(auto_cleanup=True)

   # When trust is deleted...
   actor.trust.delete_relationship(peer_id="peer123")

   # The following happens automatically:
   # 1. All subscriptions with this peer are terminated
   # 2. RemotePeerStore data for this peer is deleted
   # 3. Pending callbacks for this peer are discarded
   # 4. Callback state (sequence tracking) is cleared

**Manual Cleanup**

If you need manual control over cleanup, disable auto_cleanup and handle it in your trust hook:

.. code-block:: python

   app.with_subscription_processing(auto_cleanup=False)

   @app.trust_hook("delete")
   def on_trust_deleted(actor, peerid, relationship, trust_data):
       # Custom cleanup logic
       from actingweb.remote_storage import RemotePeerStore
       from actingweb.callback_processor import CallbackProcessor

       # Clean up peer data
       store = RemotePeerStore(actor, peerid)
       store.delete_all()

       # Clear callback state
       processor = CallbackProcessor(actor)
       # Note: subscription_id needed - iterate if multiple
       processor.clear_state(peerid, subscription_id)

       # Application-specific cleanup
       notify_user(f"Connection with {peerid} ended")

**Pending Callbacks When Trust Ends**

When trust is deleted, any pending (out-of-order) callbacks for that peer are discarded:

1. The CallbackProcessor checks trust status before processing
2. Pending callbacks from untrusted peers are rejected
3. No resync is triggered for deleted trust relationships

**Re-establishing Trust After Deletion**

When trust is re-established with a previously connected peer:

.. code-block:: python

   # Re-create trust
   actor.trust.create_relationship(
       peer_url="https://peer.example.com/actor123",
       relationship="friend",
   )
   actor.trust.approve_relationship(peer_id="peer123")

   # Re-subscribe (state starts fresh)
   actor.subscriptions.subscribe_to_peer(
       peer_id="peer123", target="properties"
   )
   # Peer sends initial resync with full current state

Important: Sequence numbers start fresh. The first callback after re-subscription triggers a full resync to establish baseline state.

**Trust Hooks and Subscription Events**

Use trust hooks to react to lifecycle events:

.. code-block:: python

   @app.trust_hook("create")
   def on_trust_created(actor, peerid, relationship, approved, trust_data):
       # Optionally auto-subscribe when trust is established
       if approved:
           actor.subscriptions.subscribe_to_peer(
               peer_id=peerid, target="properties"
           )

   @app.trust_hook("delete")
   def on_trust_deleted(actor, peerid, relationship, trust_data):
       # Application-specific cleanup (storage cleanup is automatic)
       notify_websocket_clients(f"Peer {peerid} disconnected")
       log_audit_event("trust_deleted", peer_id=peerid)
