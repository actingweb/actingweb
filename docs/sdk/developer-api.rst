==============
Developer API
==============

**Audience**: SDK developers and advanced users who want to work with ActingWeb's high-level developer interfaces.

The ActingWeb Developer API provides a clean, modern interface for working with actors, properties, trust relationships, and subscriptions. This API abstracts away the low-level details and provides a pythonic way to interact with your actor system.

Overview
========

The Developer API consists of four main components:

1. **ActorInterface** - High-level wrapper around the core Actor class
2. **PropertyStore** - Dictionary-like interface for actor properties
3. **TrustManager** - Manages trust relationships between actors
4. **SubscriptionManager** - Handles event subscriptions

All of these are accessed through the ``ActorInterface`` which you get in your hook functions.

ActorInterface
==============

The ``ActorInterface`` is the primary way to interact with actors in your application code. It provides access to all actor functionality through clean, typed interfaces.

Basic Usage
-----------

In hook functions, you receive an ``ActorInterface`` instance:

.. code-block:: python

    from actingweb.interface import ActorInterface
    from typing import Dict, Any

    @app.action_hook("search")
    def handle_search(actor: ActorInterface, action_name: str, data: Dict[str, Any]):
        # Access actor ID
        actor_id = actor.id

        # Access properties
        status = actor.properties.get("status")

        # Work with trust relationships
        friends = actor.trust.get_relationships_by_type("friend")

        # Access subscriptions
        subs = actor.subscriptions.list_subscriptions()

        return {"results": [...]}

Properties
----------

The ``ActorInterface`` exposes several useful properties:

.. code-block:: python

    actor.id              # Actor ID string
    actor.type            # Actor type (urn:...)
    actor.creator         # Creator email/identifier
    actor.passphrase      # Actor passphrase
    actor.properties      # PropertyStore instance
    actor.trust           # TrustManager instance
    actor.subscriptions   # SubscriptionManager instance

PropertyStore
=============

The ``PropertyStore`` provides a dictionary-like interface for managing actor properties with automatic JSON serialization and change notifications.

Basic Operations
----------------

.. code-block:: python

    # Get a property
    status = actor.properties.get("status")
    config = actor.properties.get("config", default={})

    # Set a property
    actor.properties["status"] = "active"
    actor.properties.set("config", {"theme": "dark"})

    # Delete a property
    del actor.properties["status"]
    actor.properties.delete("config")

    # Check existence
    if "status" in actor.properties:
        print("Status exists")

    # Update multiple properties
    actor.properties.update({
        "status": "active",
        "last_seen": "2025-12-14"
    })

    # Get all properties
    all_props = actor.properties.to_dict()

    # Clear all properties
    actor.properties.clear()

Automatic Diff Generation
--------------------------

When properties change, ActingWeb automatically:

1. Generates diffs describing the change
2. Notifies subscribed peers
3. Triggers property hooks if registered

.. code-block:: python

    # This automatically generates a diff and notifies subscribers
    actor.properties["status"] = "active"

To suppress notification for a specific change:

.. code-block:: python

    actor.properties.set("internal_flag", True, notify=False)

JSON Serialization
------------------

PropertyStore automatically handles JSON serialization for non-string values:

.. code-block:: python

    # These are automatically serialized to JSON strings
    actor.properties["config"] = {"theme": "dark", "lang": "en"}
    actor.properties["tags"] = ["python", "actingweb"]
    actor.properties["count"] = 42

    # Retrieved as original types
    config = actor.properties.get("config")  # Returns dict
    tags = actor.properties.get("tags")      # Returns list
    count = actor.properties.get("count")    # Returns int

TrustManager
============

The ``TrustManager`` handles trust relationships between actors, including permission evaluation and lifecycle hooks.

Getting Trust Relationships
----------------------------

.. code-block:: python

    # Get all trust relationships
    all_trusts = actor.trust.get_all_relationships()

    # Get by peer ID
    trust = actor.trust.get_relationship_by_peerid("peer123")

    # Get by relationship type
    friends = actor.trust.get_relationships_by_type("friend")
    colleagues = actor.trust.get_relationships_by_type("colleague")

Creating Trust Relationships
-----------------------------

.. code-block:: python

    # Create simple trust (local only)
    trust = actor.trust.create_relationship(
        peer_id="peer123",
        relationship_type="friend",
        baseuri="https://peer.example.com/peer123",
        desc="Alice's actor"
    )

    # Create with peer notification
    trust = await actor.trust.create_reciprocal_trust_async(
        peer_id="peer123",
        relationship_type="friend",
        baseuri="https://peer.example.com/peer123"
    )

    # Create verified trust (handshake protocol)
    trust = await actor.trust.create_verified_trust_async(
        peer_id="peer123",
        relationship_type="friend",
        baseuri="https://peer.example.com/peer123",
        verify_token="secret-token-from-peer"
    )

Modifying Trust Relationships
------------------------------

.. code-block:: python

    # Update relationship type
    updated = actor.trust.modify_relationship(
        peer_id="peer123",
        relationship_type="colleague"  # Changed from "friend"
    )

    # Modify with peer notification
    updated = await actor.trust.modify_and_notify_async(
        peer_id="peer123",
        relationship_type="colleague"
    )

Deleting Trust Relationships
-----------------------------

.. code-block:: python

    # Delete local trust only
    success = actor.trust.delete_relationship("peer123")

    # Delete with peer notification
    success = await actor.trust.delete_peer_trust_async("peer123")

Permission Checking
-------------------

Trust relationships include permission checking based on relationship type:

.. code-block:: python

    # Check if peer can access a property
    trust = actor.trust.get_relationship_by_peerid("peer123")
    if trust:
        can_read = actor.trust.check_property_permission(
            trust,
            "user_profile",
            "read"
        )

SubscriptionManager
===================

The ``SubscriptionManager`` handles event subscriptions to and from other actors.

Listing Subscriptions
---------------------

.. code-block:: python

    # Get all subscriptions
    all_subs = actor.subscriptions.list_subscriptions()

    # Get specific subscription by peer
    sub = actor.subscriptions.get_subscription("peer123")

    # Get subscription with pending diffs
    sub_with_diffs = actor.subscriptions.get_subscription_with_diffs("peer123")
    if sub_with_diffs.has_diffs():
        diffs = sub_with_diffs.get_diffs()

Creating Subscriptions
-----------------------

.. code-block:: python

    # Create local subscription (we subscribe to them)
    sub = actor.subscriptions.create_local_subscription(
        peer_id="peer123",
        resource_uri="https://peer.example.com/peer123",
        granularity="",  # All properties
        target_uri=f"https://myapp.com/{actor.id}/callbacks/updates"
    )

    # Create with peer notification
    sub = await actor.subscriptions.subscribe_to_peer_async(
        peer_id="peer123",
        baseuri="https://peer.example.com/peer123",
        callback_path="callbacks/updates"
    )

Deleting Subscriptions
-----------------------

.. code-block:: python

    # Delete local subscription
    success = actor.subscriptions.delete_subscription("peer123")

    # Delete with peer notification
    success = await actor.subscriptions.unsubscribe_async("peer123")

Callback Subscriptions
-----------------------

For callback-specific operations:

.. code-block:: python

    # Get callback subscription (they subscribed to us)
    callback_sub = actor.subscriptions.get_callback_subscription("peer123")

    # Delete callback subscription
    success = actor.subscriptions.delete_callback_subscription("peer123")

Authenticated Views
===================

See :doc:`authenticated-views` for details on permission-enforced access modes (Owner, Peer, Client).

Async Operations
================

See :doc:`async-operations` for details on async variants and peer communication patterns.

Best Practices
==============

1. **Use ActorInterface in Hooks**

   Always use the ``ActorInterface`` provided to hook functions. Don't create your own instances.

2. **Prefer Async for Peer Communication**

   Use async variants when communicating with remote peers to avoid blocking:

   .. code-block:: python

       # Good - async, non-blocking
       trust = await actor.trust.create_verified_trust_async(...)

       # Avoid - sync, may block for seconds
       trust = actor.trust.create_verified_trust(...)

3. **Let PropertyStore Handle Serialization**

   Don't manually JSON encode/decode - PropertyStore handles it:

   .. code-block:: python

       # Good
       actor.properties["config"] = {"theme": "dark"}

       # Don't do this
       import json
       actor.properties["config"] = json.dumps({"theme": "dark"})

4. **Use Diffs for Notifications**

   Property changes automatically generate diffs. Don't suppress unless needed:

   .. code-block:: python

       # Subscribers will be notified
       actor.properties["status"] = "active"

       # Only suppress for internal state
       actor.properties.set("_internal_flag", True, notify=False)

5. **Check Trust Before Accessing**

   Always verify trust exists before assuming access:

   .. code-block:: python

       trust = actor.trust.get_relationship_by_peerid(peer_id)
       if not trust:
           return {"error": "No trust relationship"}

See Also
========

- :doc:`authenticated-views` - Permission-enforced access patterns
- :doc:`async-operations` - Async peer communication
- :doc:`handler-architecture` - How handlers use the developer API
- :doc:`../guides/hooks` - Implementing lifecycle hooks
