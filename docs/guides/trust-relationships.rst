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

For apps using unified access control, you can set per‑relationship overrides. See :doc:`access-control-simple` for the simple guide.

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

See also: :doc:`access-control` for the full system.

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

Peer Profile Caching
--------------------

ActingWeb can automatically cache profile attributes from trusted peers, making it easy to display peer information without repeated API calls.

**Enable Profile Caching**

.. code-block:: python

   app = ActingWebApp(
       aw_type="urn:actingweb:example.com:myapp",
       fqdn="myapp.example.com"
   ).with_peer_profile(attributes=["displayname", "email", "description"])

When enabled, profiles are:

- Automatically fetched when trust is fully approved (both sides)
- Refreshed during ``sync_peer()`` operations
- Cleaned up when trust is deleted

**Accessing Cached Profiles**

.. code-block:: python

   # Get cached profile
   profile = actor.trust.get_peer_profile(peer_id)
   if profile:
       print(f"Connected with {profile.displayname}")
       print(f"Email: {profile.email}")
       # Access additional attributes
       avatar = profile.get_attribute("avatar_url")

   # Check for fetch errors
   if profile and profile.fetch_error:
       print(f"Warning: {profile.fetch_error}")

**Manual Profile Refresh**

.. code-block:: python

   # Sync version
   profile = actor.trust.refresh_peer_profile(peer_id)

   # Async version (for FastAPI)
   profile = await actor.trust.refresh_peer_profile_async(peer_id)

**Custom Attributes**

Cache any property the peer exposes:

.. code-block:: python

   app.with_peer_profile(attributes=[
       "displayname",
       "email",
       "avatar_url",
       "timezone",
       "organization",
   ])

See :doc:`../quickstart/configuration` for detailed configuration options.

Peer Capabilities Caching
-------------------------

ActingWeb can automatically cache the methods and actions that trusted peers expose, making it easy to discover what functionality is available without repeated API calls.

**Enable Capabilities Caching**

.. code-block:: python

   app = ActingWebApp(
       aw_type="urn:actingweb:example.com:myapp",
       fqdn="myapp.example.com"
   ).with_peer_capabilities(enable=True, max_age_seconds=3600)

**Parameters:**

- ``enable``: Enable/disable capabilities caching. Default: ``True`` when called.
- ``max_age_seconds``: Maximum cache age in seconds before capabilities are refetched during ``sync_peer()``. Default: ``3600`` (1 hour). Set to ``0`` to always refetch.

When enabled, capabilities are:

- Automatically fetched when trust is fully approved (both sides)
- Refreshed during ``sync_peer()`` operations (only if cache is older than ``max_age_seconds``)
- Always refreshed when ``sync_peer(force_refresh=True)`` is called
- Cleaned up when trust is deleted

**Accessing Cached Capabilities**

.. code-block:: python

   # Get all cached capabilities
   capabilities = actor.trust.get_peer_capabilities(peer_id)
   if capabilities:
       # List available methods and actions
       print(f"Methods: {capabilities.get_method_names()}")
       print(f"Actions: {capabilities.get_action_names()}")

       # Get specific method details
       method = capabilities.get_method("get_data")
       if method:
           print(f"{method.name}: {method.description}")
           if method.input_schema:
               print(f"Expects: {method.input_schema}")

   # Convenience methods for just methods or actions
   methods = actor.trust.get_peer_methods(peer_id)
   actions = actor.trust.get_peer_actions(peer_id)

   # Check for fetch errors
   if capabilities and capabilities.fetch_error:
       print(f"Warning: {capabilities.fetch_error}")

**Manual Capabilities Refresh**

.. code-block:: python

   # Sync version
   capabilities = actor.trust.refresh_peer_capabilities(peer_id)

   # Async version (for FastAPI)
   capabilities = await actor.trust.refresh_peer_capabilities_async(peer_id)

**Use Case: Method Discovery**

Peer capabilities caching is especially useful for MCP (Model Context Protocol) integration, where you need to discover what tools/methods a peer exposes:

.. code-block:: python

   # Check if peer supports a specific method before calling
   capabilities = actor.trust.get_peer_capabilities(peer_id)
   if capabilities:
       if capabilities.get_method("summarize"):
           # Safe to call the summarize method
           result = actor.trust.call_peer_method(peer_id, "summarize", data)
       else:
           # Use fallback behavior
           result = default_summarize(data)

See :doc:`../quickstart/configuration` for detailed configuration options.

Peer Permissions Caching
------------------------

ActingWeb can automatically cache what permissions peer actors have granted to your actor.
This enables efficient permission checking without network requests.

**Enable Permissions Caching**

.. code-block:: python

   app = ActingWebApp(
       aw_type="urn:actingweb:example.com:myapp",
       fqdn="myapp.example.com"
   ).with_peer_permissions(
       enable=True,
       auto_delete_on_revocation=True,   # Delete cached data when revoked
       notify_peer_on_change=True        # Auto-notify peers (default)
   )

**Configuration Options:**

- ``enable``: Enable peer permissions caching. Default: ``True`` when called.
- ``auto_delete_on_revocation``: Delete cached peer data when permissions revoked. Default: ``False``.
- ``notify_peer_on_change``: Auto-notify peers when their permissions change. Default: ``True``.

When enabled, permissions are:

- Fetched when trust relationships are fully approved
- Updated when permission callbacks are received from peers
- Sent to peers automatically when you change their permissions (if ``notify_peer_on_change=True``)
- Refreshed during ``sync_peer()`` operations
- Deleted when trust relationships are removed

**Accessing Cached Permissions**

.. code-block:: python

   from actingweb.peer_permissions import get_peer_permission_store

   store = get_peer_permission_store(actor.config)

   # Get cached permissions
   perms = store.get_permissions(actor.id, peer_id)
   if perms:
       # Check property access
       if perms.has_property_access("memory_travel", "read"):
           data = actor.trust.get_peer_property(peer_id, "memory_travel")

       # Check method access
       if perms.has_method_access("sync_data"):
           result = actor.trust.call_peer_method(peer_id, "sync_data", params)

       # Check tool access (MCP)
       if perms.has_tool_access("search"):
           # Safe to use the search tool
           pass

   # Check for fetch errors
   if perms and perms.fetch_error:
       print(f"Warning: {perms.fetch_error}")

**Manual Permissions Refresh**

.. code-block:: python

   from actingweb.peer_permissions import fetch_peer_permissions

   # Synchronous refresh
   perms = fetch_peer_permissions(actor, peer_id)

   # Async refresh (for FastAPI)
   perms = await fetch_peer_permissions_async(actor, peer_id)

**Permission Callbacks**

When a peer modifies permissions granted to your actor, they can send a permission callback
to notify you immediately. The callback is sent to::

   POST /{your_actor_id}/callbacks/permissions/{peer_actor_id}

The library automatically handles these callbacks and updates the local cache. Permission
callbacks contain the full *effective* permissions (base trust-type defaults merged with
per-trust overrides), enabling accurate change detection. When new property patterns are
granted, an incremental sync automatically fetches only the newly granted properties.
Peers supporting this feature advertise ``permissioncallback`` in their
``/meta/actingweb/supported`` endpoint.

**Use Cases for MCP**

Peer permissions caching is especially useful for MCP (Model Context Protocol) integration,
where you need to check if you have access to a peer's tools or resources:

.. code-block:: python

   from actingweb.peer_permissions import get_peer_permission_store

   store = get_peer_permission_store(actor.config)
   perms = store.get_permissions(actor.id, peer_id)

   if perms:
       # Check tool access before calling
       if perms.has_tool_access("search"):
           result = await actor.trust.call_peer_tool(peer_id, "search", query)
       else:
           # Access denied - use alternative approach
           result = local_search(query)

       # Check resource access
       if perms.has_resource_access("data://shared/*"):
           # Can access shared data resources
           pass

See :doc:`../quickstart/configuration` for detailed configuration options.
