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
        friends = actor.trust.get_peers_by_relationship("friend")

        # Access subscriptions
        subs = actor.subscriptions.all_subscriptions

        return {"results": [...]}

Properties
----------

The ``ActorInterface`` exposes several useful properties:

.. code-block:: python

    actor.id              # Actor ID string
    actor.creator         # Creator email/identifier
    actor.passphrase      # Actor passphrase
    actor.url             # Actor root URL
    actor.config          # ActingWeb configuration object
    actor.properties      # PropertyStore instance
    actor.property_lists  # ListPropertyStore instance (list-valued properties)
    actor.trust           # TrustManager instance
    actor.subscriptions   # SubscriptionManager instance
    actor.services        # ServiceRegistry (third-party OAuth2 services)

``actor.property_lists`` is only summarized here -- see
:doc:`../guides/property-lists` for the full API (``to_list()``,
``find()``, ``items_with_handles()``, the identity-addressed mutators, and
REST usage).

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

To suppress notification for a specific change, use
``set_without_notification()`` (``set()`` always notifies):

.. code-block:: python

    actor.properties.set_without_notification("internal_flag", True)

JSON Serialization
------------------

PropertyStore automatically handles JSON serialization for non-string values:

.. code-block:: python

    # These are automatically serialized to JSON strings
    actor.properties["config"] = {"theme": "dark", "lang": "en"}
    actor.properties["tags"] = ["python", "actingweb"]
    actor.properties["count"] = 42

    # Structured values (dict/list) round-trip as their original type
    config = actor.properties.get("config")  # Returns dict
    tags = actor.properties.get("tags")      # Returns list

    # NOTE: bare scalars are stored and returned as strings — a stored int comes
    # back as a str. Cast on read if you need the numeric type:
    count = int(actor.properties.get("count", 0))

TrustManager
============

The ``TrustManager`` handles trust relationships between actors, including permission evaluation and lifecycle hooks.

Getting Trust Relationships
----------------------------

.. code-block:: python

    # Get all trust relationships (property, not a method)
    all_trusts = actor.trust.relationships

    # Only active / only pending relationships
    active = actor.trust.active_relationships
    pending = actor.trust.pending_relationships

    # Get by peer ID (returns None if not found)
    trust = actor.trust.get_relationship("peer123")

    # Get by relationship type
    friends = actor.trust.get_peers_by_relationship("friend")
    colleagues = actor.trust.get_peers_by_relationship("colleague")

    # Membership checks
    if actor.trust.has_relationship_with("peer123"):
        ...

Creating Trust Relationships
-----------------------------

Use ``create_relationship()`` to initiate an outgoing trust with another actor.
It performs the reciprocal handshake with the peer (an HTTP call), so prefer the
``_async`` variant in async contexts (FastAPI):

.. code-block:: python

    # Create trust (initiates the reciprocal handshake with the peer)
    trust = actor.trust.create_relationship(
        peer_url="https://peer.example.com/peer123",
        relationship="friend",       # defaults to "friend"
        secret="",                    # auto-generated if omitted
        description="Alice's actor",
    )

    # Async variant (non-blocking; use in FastAPI handlers)
    trust = await actor.trust.create_relationship_async(
        peer_url="https://peer.example.com/peer123",
        relationship="friend",
    )

To *accept* an incoming trust request initiated by another actor (the peer POSTs
the trust details to you), use the synchronous ``create_verified_trust()``:

.. code-block:: python

    trust = actor.trust.create_verified_trust(
        baseuri="https://peer.example.com/peer123",
        peer_id="peer123",
        approved=True,
        secret="shared-secret",
        verification_token="token-from-peer",
        trust_type="friend",
        peer_approved=True,
        relationship="friend",
    )

Approving and Modifying Trust Relationships
--------------------------------------------

.. code-block:: python

    # Approve a pending incoming relationship
    actor.trust.approve_relationship("peer123")          # or approve_relationship_async

    # Change relationship attributes and notify the peer
    updated = actor.trust.modify_and_notify(
        peer_id="peer123",
        relationship="colleague",
    )

    # Local-only modification (no peer notification)
    actor.trust.modify_trust(peer_id="peer123", relationship="colleague")

Deleting Trust Relationships
-----------------------------

.. code-block:: python

    # Delete local trust only
    success = actor.trust.delete_relationship("peer123")

    # Delete and notify the peer (default notify_peer=True)
    success = actor.trust.delete_peer_trust("peer123")

    # Async local delete
    success = await actor.trust.delete_relationship_async("peer123")

Permission Checking
-------------------

Per-peer permissions are managed through the trust permission store rather than
on the ``TrustManager`` itself. For read/write access decisions in application
code, prefer the permission-enforcing :doc:`authenticated-views` (``as_peer`` /
``as_client``), which evaluate permissions for you. To inspect or update the
stored permissions directly:

.. code-block:: python

    from actingweb.trust_permissions import get_trust_permission_store

    store = get_trust_permission_store(actor.config)
    perms = store.get_permissions(actor.id, "peer123")

SubscriptionManager
===================

The ``SubscriptionManager`` handles event subscriptions to and from other actors.

Subscription Directions
-----------------------

Understanding subscription directions is important for proper subscription management:

**Outbound subscriptions** (callback=True):
  You are the **subscriber**. You subscribed TO another actor to receive their updates.
  Use ``unsubscribe()`` to terminate these.

**Inbound subscriptions** (callback=False):
  You are the **publisher**. Another actor subscribed TO YOU to receive your updates.
  Use ``revoke_peer_subscription()`` to terminate these.

Listing Subscriptions
---------------------

.. code-block:: python

    # Get all subscriptions (both directions)
    all_subs = actor.subscriptions.all_subscriptions

    # Get outbound subscriptions (we subscribed to them)
    outbound = actor.subscriptions.get_subscriptions_to_peer("peer123")

    # Get inbound subscriptions (they subscribed to us)
    inbound = actor.subscriptions.get_subscriptions_from_peer("peer123")

    # Get subscription with pending diffs
    sub_with_diffs = actor.subscriptions.get_subscription_with_diffs(
        peer_id="peer123",
        subscription_id="sub456"
    )
    diffs = sub_with_diffs.get_diffs()

Creating Subscriptions
-----------------------

.. code-block:: python

    # Subscribe to peer (synchronous - includes automatic baseline sync)
    subscription_url = actor.subscriptions.subscribe_to_peer(
        peer_id="peer123",
        target="properties",
        subtarget="",
        resource="",
        granularity="high"
    )

    # Subscribe to peer (async - includes automatic baseline sync)
    subscription_url = await actor.subscriptions.subscribe_to_peer_async(
        peer_id="peer123",
        target="properties",
        subtarget="",
        resource="",
        granularity="high"
    )

Deleting Subscriptions: unsubscribe() vs revoke_peer_subscription()
--------------------------------------------------------------------

There are two methods for deleting subscriptions, each for a different use case:

**unsubscribe()** - For terminating YOUR outbound subscriptions
    Use when you (the subscriber) want to stop receiving updates from a peer.
    This deletes your local outbound subscription and notifies the peer to delete
    their inbound record.

    .. code-block:: python

        # You subscribed to peer123's data and now want to stop receiving updates
        success = actor.subscriptions.unsubscribe(
            peer_id="peer123",
            subscription_id="sub456"
        )

        # Unsubscribe from all subscriptions to a peer
        success = actor.subscriptions.unsubscribe_from_peer("peer123")

**revoke_peer_subscription()** - For terminating a PEER'S inbound subscription
    Use when you (the publisher) want to stop sending updates to a peer.
    This deletes your local inbound subscription record and notifies the peer
    to delete their outbound subscription. The ``subscription_deleted`` lifecycle
    hook fires with ``initiated_by_peer=False``.

    .. code-block:: python

        # peer123 subscribed to your data and you want to revoke their access
        success = actor.subscriptions.revoke_peer_subscription(
            peer_id="peer123",
            subscription_id="sub456"
        )

**Quick Reference:**

+---------------------------+----------------+-----------------+---------------------------+
| Method                    | You are        | Subscription    | Use case                  |
+===========================+================+=================+===========================+
| ``unsubscribe()``         | Subscriber     | Outbound        | Stop receiving updates    |
+---------------------------+----------------+-----------------+---------------------------+
| ``revoke_peer_subscription()`` | Publisher | Inbound         | Stop sending updates      |
+---------------------------+----------------+-----------------+---------------------------+

**Example: Managing Bidirectional Subscriptions**

.. code-block:: python

    # Actor A and Actor B have mutual subscriptions
    # A subscribes to B (outbound for A, inbound for B)
    # B subscribes to A (outbound for B, inbound for A)

    # If A wants to stop receiving updates from B:
    actor_a.subscriptions.unsubscribe("actor_b_id", "sub_id_a_to_b")

    # If A wants to stop B from receiving A's updates:
    actor_a.subscriptions.revoke_peer_subscription("actor_b_id", "sub_id_b_to_a")

Subscription Lifecycle Hook
---------------------------

The ``subscription_deleted`` lifecycle hook fires when inbound subscriptions are deleted:

.. code-block:: python

    @app.lifecycle_hook("subscription_deleted")
    def on_subscription_deleted(actor, peer_id, subscription_id, subscription_data, initiated_by_peer):
        if initiated_by_peer:
            # Peer unsubscribed from us via unsubscribe()
            logger.info(f"{peer_id} unsubscribed from our data")
        else:
            # We revoked their subscription via revoke_peer_subscription()
            logger.info(f"Revoked {peer_id}'s subscription")

        # Common cleanup: revoke permissions, clear cached data, etc.
        from actingweb.trust_permissions import get_trust_permission_store
        store = get_trust_permission_store(actor.config)
        store.update_permissions(actor.id, peer_id, {"properties": []})

See :doc:`../reference/hooks-reference` for full hook documentation.

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
       trust = await actor.trust.create_relationship_async(peer_url=...)

       # Avoid in async contexts - sync, may block for seconds
       trust = actor.trust.create_relationship(peer_url=...)

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
       actor.properties.set_without_notification("_internal_flag", True)

5. **Check Trust Before Accessing**

   Always verify trust exists before assuming access:

   .. code-block:: python

       trust = actor.trust.get_relationship(peer_id)
       if not trust:
           return {"error": "No trust relationship"}

See Also
========

- :doc:`authenticated-views` - Permission-enforced access patterns
- :doc:`async-operations` - Async peer communication
- :doc:`handler-architecture` - How handlers use the developer API
- :doc:`../guides/hooks` - Implementing lifecycle hooks
