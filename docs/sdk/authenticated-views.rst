===================
Authenticated Views
===================

**Audience**: SDK developers implementing permission-enforced access patterns.

ActingWeb provides a unified access control system through **Authenticated Views**. This system ensures that all access to actor resources respects the permissions defined by trust relationships.

Overview
========

Three access modes are supported:

1. **Owner Mode** - Direct ``ActorInterface`` access with full permissions
2. **Peer Mode** - Actor-to-actor access with trust-based permissions
3. **Client Mode** - OAuth2/MCP client access with trust-based permissions

Access Modes
============

Owner Mode
----------

When you have direct access to an actor (e.g., the actor's own code), you use Owner Mode. This provides full access without permission checks.

.. code-block:: python

    from actingweb.interface import ActorInterface

    # Direct access - full permissions, no checks
    actor = ActorInterface(core_actor)
    actor.properties["any_property"] = value  # Always works
    all_data = actor.properties.to_dict()     # Gets everything

Peer Mode
---------

When one actor accesses another actor's resources, Peer Mode enforces the permissions defined by their trust relationship.

.. code-block:: python

    # Access as a peer - permissions enforced
    peer_view = actor.as_peer(
        peer_id="peer123",
        trust_relationship=trust_data
    )

    # This will check if "friend" relationship allows writing "shared_data"
    peer_view.properties["shared_data"] = value

    # This will only return properties the peer is allowed to read
    accessible_props = peer_view.properties.to_dict()

Client Mode
-----------

For OAuth2 clients and MCP applications, Client Mode enforces permissions based on the client's trust relationship with the actor.

.. code-block:: python

    # Access as an OAuth2/MCP client - permissions enforced
    client_view = actor.as_client(
        client_id="mcp_chatgpt",
        trust_relationship=trust_data
    )

    # Permission checks applied
    client_view.properties["user_data"] = value

AuthenticatedActorView
======================

The ``AuthenticatedActorView`` class wraps an ``ActorInterface`` and enforces permissions on all operations.

Creating Views
--------------

.. code-block:: python

    from actingweb.interface.authenticated_views import AuthenticatedActorView

    # Create peer view
    peer_view = AuthenticatedActorView(
        actor_interface=actor,
        accessor_id="peer123",
        trust_relationship=trust_record,
        is_peer=True,
        is_client=False
    )

    # Create client view
    client_view = AuthenticatedActorView(
        actor_interface=actor,
        accessor_id="mcp_client_123",
        trust_relationship=trust_record,
        is_peer=False,
        is_client=True
    )

Properties Access
-----------------

The ``AuthenticatedPropertyStore`` wraps property access with permission checks:

.. code-block:: python

    # Reading - checks read permission
    value = peer_view.properties.get("user_profile")

    # Writing - checks write permission
    peer_view.properties["status"] = "active"

    # Iteration - filters to accessible properties only
    for key, value in peer_view.properties.items():
        print(f"{key}: {value}")  # Only shows permitted properties

    # to_dict - returns only accessible properties
    visible_props = peer_view.properties.to_dict()

Permission Errors
-----------------

When access is denied, a ``PermissionError`` is raised:

.. code-block:: python

    try:
        peer_view.properties["restricted_data"] = "value"
    except PermissionError as e:
        print(f"Access denied: {e}")
        # Handle permission denial

Handler Integration
===================

In HTTP handlers, use the ``_get_authenticated_view()`` helper method:

.. code-block:: python

    class MyHandler(BaseHandler):
        def get(self, actor_id, path):
            # Get the actor
            actor = self._get_actor(actor_id)
            if not actor:
                return self._not_found()

            # Get authentication result
            auth_result = self._authenticate()

            # Get authenticated view (or None for owner)
            auth_view = self._get_authenticated_view(actor, auth_result)

            if auth_view:
                # Peer or client access - permissions enforced
                data = auth_view.properties.get("config")
            else:
                # Owner access - full permissions
                data = actor.properties.get("config")

            return self._json_response(data)

Trust Relationships and Permissions
===================================

Permissions are derived from the trust relationship type:

.. code-block:: python

    # Trust record contains relationship type
    trust_record = {
        "peerid": "peer123",
        "relationship": "friend",  # Determines permissions
        "approved": True,
        "peer_approved": True
    }

    # "friend" relationship might allow:
    # - Read: user_profile, status, public_*
    # - Write: messages, shared_data

Built-in Relationship Types
---------------------------

ActingWeb includes several built-in relationship types:

- **friend** - Trusted peer with moderate access
- **colleague** - Work relationship with specific access patterns
- **service** - Service-to-service integration
- **admin** - Administrative access
- **readonly** - Read-only access to public properties

Custom Relationship Types
-------------------------

Define custom relationship types with specific permissions:

.. code-block:: python

    app = ActingWebApp(...)

    # Add custom trust type
    app.add_trust_type(
        name="family",
        permissions={
            "properties": {
                "read": ["*"],  # Read all
                "write": ["shared_*", "family_*"]  # Write shared/family props
            },
            "subscriptions": {
                "create": True,
                "delete": True
            }
        }
    )

Context Properties
==================

The ``AuthenticatedActorView`` provides context about the accessor:

.. code-block:: python

    # Get accessor information
    accessor_id = auth_view.accessor_id  # "peer123" or "mcp_client_123"

    # Check access type
    if auth_view.is_peer:
        # Actor-to-actor access
        pass
    elif auth_view.is_client:
        # OAuth2/MCP client access
        pass

    # Access underlying actor interface
    core_actor = auth_view.actor_interface

Best Practices
==============

1. **Always Use Authenticated Views for External Access**

   .. code-block:: python

       # In handlers - get authenticated view
       auth_view = self._get_authenticated_view(actor, auth_result)
       if auth_view:
           # Use auth_view for all operations
           data = auth_view.properties.get(key)

2. **Handle Permission Errors Gracefully**

   .. code-block:: python

       try:
           auth_view.properties[key] = value
       except PermissionError:
           return self._forbidden("Not authorized to write this property")

3. **Use Owner Mode Only for Internal Operations**

   .. code-block:: python

       # Internal processing - owner mode OK
       actor.properties["_internal_state"] = state

       # External API - use authenticated view
       auth_view.properties["user_data"] = data

4. **Check Trust Before Creating Views**

   .. code-block:: python

       trust = actor.trust.get_relationship_by_peerid(peer_id)
       if not trust or not trust.get("approved"):
           return self._unauthorized("No trust relationship")

       auth_view = actor.as_peer(peer_id, trust)

See Also
========

- :doc:`developer-api` - Core developer interfaces
- :doc:`../guides/access-control` - Detailed access control guide
- :doc:`../guides/trust-relationships` - Trust relationship management
