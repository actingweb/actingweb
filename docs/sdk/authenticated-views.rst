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

Prefer the ``actor.as_peer()`` / ``actor.as_client()`` factory methods shown
above. They build the view for you and are the supported API. If you need to
construct a view directly, pass an ``AuthContext`` (the accessor is a ``peer_id``
**or** a ``client_id``, never both):

.. code-block:: python

    from actingweb.interface.authenticated_views import (
        AuthContext,
        AuthenticatedActorView,
    )

    # Peer view
    peer_view = AuthenticatedActorView(
        actor,
        AuthContext(peer_id="peer123", trust_relationship=trust_record),
    )

    # Client view (OAuth2 / MCP)
    client_view = AuthenticatedActorView(
        actor,
        AuthContext(client_id="mcp_client_123", trust_relationship=trust_record),
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

Property List Access
---------------------

The ``AuthenticatedPropertyListStore`` wraps ``actor.property_lists`` with
per-operation permission checks, mirroring ``AuthenticatedPropertyStore``:

.. code-block:: python

    # Reading a list - checks "read" on the list name
    notes = peer_view.property_lists.notes
    items = notes.to_list()

    # Mutating - each call re-checks "write" (or "delete" for
    # __delitem__/clear()/delete()) before delegating, even though the
    # object above was already obtained under a "read" check
    notes.append("a new note")        # requires "write"
    del notes[0]                      # requires "delete"
    notes.clear()                     # requires "delete"

    # Deleting an entire named list
    peer_view.property_lists.delete("notes")   # requires "delete"

    # Existence check - requires "read"; returns False rather than raising
    # when denied
    peer_view.property_lists.exists("notes")

There is no ``create()``: lists are created lazily on first write, so a
separate creation step has no meaning. (An earlier ``create()`` existed but
had never worked -- it resolved through ``PropertyListStore.__getattr__`` to
a ``NotifyingListProperty`` named ``"create"`` and then called it, raising
``TypeError``.)

The 3.14 identity/handle mutators are gated the same way, and one of them
is easy to guess wrong from its name:

.. code-block:: python

    notes.delete_by_handle(handle)         # requires "write", not "delete"
    notes.update_by_handle(handle, item)   # requires "write"
    notes.update_where("status", "open", item)   # requires "write"
    notes.remove_where("status", "archived")     # requires "delete"

``delete_by_handle()`` requires ``write`` rather than ``delete`` because
it targets exactly one item you already have a reference to, the same
kind of operation as ``update_by_handle()``. ``remove_where()`` requires
``delete`` because it can remove every matching item in the list in one
call -- closer in effect to ``clear()`` than to a single-item change.

The same single-item logic applies to the two positional removers that
predate 3.14: ``pop()`` and ``remove(value)`` require ``write``, not
``delete`` -- each takes out exactly one item. The ``delete`` permission
gates the operations whose blast radius is a position you did not
inspect (``__delitem__``), many items at once (``remove_where()``), or
the whole list (``clear()``, ``delete()``).

Every method ``actor.property_lists.<name>`` exposes -- ``to_list()``,
``append()``, ``pop()``, ``slice()``, ``compact()``, ``migrate_to_v2()``, and
so on -- is reachable through the authenticated view with the matching
permission check applied per call, not once when the list was obtained.

Bulk reads
~~~~~~~~~~

The three bulk readers are defined on the view itself and filter by
permission in **one** bulk evaluation, not one check per list:

.. code-block:: python

    names = peer_view.property_lists.list_all()
    names, rows = peer_view.property_lists.list_all_with_rows()
    names, rows = peer_view.property_lists.list_prefix_with_rows("memory_")

    for name in names:                       # only lists this peer may read
        items = getattr(peer_view.property_lists, name).to_list_from_rows(rows)

A denied list is removed from **both** halves of the result -- its name from
``names`` and every one of its rows from ``rows`` -- using the library's own
row-attribution logic, so a permitted sibling such as ``foo-old`` keeps all
its rows when ``foo`` is denied. A denied list is simply absent: nothing
raises, and no denied name appears in any message or in this module's log
records. If the permission system itself fails, the result is empty
(``[]`` / ``([], {})``) rather than partial, following the REST
``/properties`` handler's "exclude all list properties on error". As with
``exists()``, an empty result is therefore indistinguishable from "this
actor has no such lists". Everything else about the three methods --
``prefix`` semantics, the cost contrast with the whole-partition read, and
that ``list_prefix_with_rows()`` raises ``ValueError`` on an empty prefix
and ``DbError`` on a backend fault -- is exactly as documented for the
unauthenticated store in :doc:`/guides/property-lists`.

Before 3.14.3 these calls fell through ``__getattr__`` and raised
``TypeError``, the same way the removed ``create()`` did. The repair has one
consequence worth knowing: a list whose name **collides with a store method**
-- ``exists``, ``list_all``, ``list_all_with_rows``,
``list_prefix_with_rows`` -- now raises ``AttributeError`` through the
authenticated view rather than resolving either way. That is deliberate:
resolving such a name to the underlying store's method would hand a
permission-scoped accessor an unfiltered whole-partition read. Such a list
is still reachable through the unauthenticated ``actor.property_lists``.

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

    # Identity of the accessor and the actor being viewed
    accessor = auth_view.accessor_id     # peer_id or client_id
    actor_id = auth_view.id
    ctx = auth_view.auth_context

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

       trust = actor.trust.get_relationship(peer_id)
       if not trust or not trust.approved:
           return self._unauthorized("No trust relationship")

       auth_view = actor.as_peer(peer_id, trust.to_dict())

See Also
========

- :doc:`developer-api` - Core developer interfaces
- :doc:`../guides/access-control` - Detailed access control guide
- :doc:`../guides/trust-relationships` - Trust relationship management
