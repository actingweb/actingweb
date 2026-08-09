===============
Property Lists
===============

Why
---

Use property lists for ordered collections that can grow beyond DynamoDB’s 400KB item limit. Items are stored individually with list metadata for scalable operations.

Basics
------

.. code-block:: python

   notes = actor.property_lists.notes
   notes.append("First note")
   notes.append({"title": "Meeting", "content": "Team sync"})
   first = notes[0]
   count = len(notes)
   for item in notes:
       print(item)
   all_items = notes.to_list()

Metadata
--------

.. code-block:: python

   notes.set_description("Personal notes")
   notes.set_explanation("User‑generated notes and reminders")
   desc = notes.get_description()
   expl = notes.get_explanation()

Common Operations
-----------------

- ``append(item)``
- ``insert(index, item)``
- ``pop(index=-1)``
- ``remove(value)``
- ``clear()``
- ``delete()`` (delete entire list)
- ``slice(start, end)`` (efficient range load)
- ``index(value, start=0, stop=None)``
- ``count(value)``

Use Cases
---------

.. code-block:: python

   # Blog posts
   blog_posts = actor.property_lists.blog_posts
   blog_posts.append({"title": "Getting Started", "tags": ["tutorial"]})

   # Webhooks
   webhooks = actor.property_lists.webhook_endpoints
   webhooks.append({"url": "https://api.example.com/webhook", "events": ["property_change"]})

   # Activity log
   activity = actor.property_lists.activity_log
   activity.append({"timestamp": "2024-01-15T14:30:00Z", "action": "property_updated"})

When to Use
-----------

- Regular properties: small key–value data, under ~50KB
- Property lists: growing collections, list ops, complex items, or large datasets

Namespace Collision Detection
------------------------------

Property names and list property names share the same namespace. Attempting to create a property when a list with the same name exists, or vice versa, will raise a ``ValueError``:

.. code-block:: python

   # This will raise ValueError if a list named 'notes' already exists
   actor.properties.notes = "some value"

   # This will raise ValueError if a property named 'tags' already exists
   tags = actor.property_lists.tags
   tags.append("python")

To resolve collisions:

- Delete the existing property/list first, or
- Use a different name for the new property/list

Migration Example
-----------------

.. code-block:: python

   # Old: large JSON array (risk hitting 400KB limit)
   actor.properties.user_notes = ["Note 1", "Note 2"]

   # New: scalable list
   notes = actor.property_lists.user_notes
   for n in ["Note 1", "Note 2"]:
       notes.append(n)

Storage Format (v1 / v2)
-------------------------

List properties have two internal storage formats. Both are fully
supported; which one a given list uses is invisible to everything above
the library (REST responses, ``to_list()``, item access) -- it only
affects repair internals.

- **v1** (dense integers): items stored as ``list:{name}-{index}``, with
  an authoritative ``length`` in metadata. Every list created before this
  format existed.
- **v2** (fractional rank keys): items stored as ``list:{name}-#{rank}``,
  where position is derived from sorting the rank keys -- there is no
  separate stored length to disagree with, so the corruption class
  ``verify()``/``compact()`` exist to repair (holes and orphans from an
  interrupted delete/insert) cannot occur. Every **new** list is created
  in this format.

New list names may not contain ``#`` (reserved for internal storage
keys); creating one raises ``ValueError`` immediately.

**Migrating existing v1 lists to v2**

Existing v1 lists keep working indefinitely -- migration is optional and
gradual, never required for a list to keep functioning:

- **Lazy**: a v1 list with 50 or fewer items migrates automatically the
  next time it's mutated (``append``, ``insert``, item assignment, or item
  deletion). A failed lazy migration is logged and the mutation still
  succeeds against the v1 storage -- migration never turns an ordinary
  write into a failure.
- **Bulk**: larger or idle lists are migrated with the operator script::

    poetry run python scripts/migrate_property_lists.py            # dry run
    poetry run python scripts/migrate_property_lists.py --migrate

  The script reports lists it refuses to migrate (names containing
  ``#`` -- rename first) and any duplicate-value residue it preserves
  as-is.
- **Programmatic**: ``actor.property_lists.<name>._list_prop.migrate_to_v2()``
  migrates one list directly. Idempotent -- safe to call again (a no-op
  once the list is already v2) and safe to re-run after an interruption.

.. warning::

   There is no supported forward path from v1 to v2 other than migration,
   and downgrading a v2 list back to v1 is an **emergency-only** operation
   (``scripts/migrate_property_lists.py --downgrade ACTOR_ID/list_name``),
   intended for rolling back to a release that predates v2 support. It
   takes no lock against concurrent writes and is not part of the normal
   operational flow -- do not script it into routine tooling.

REST API
--------

List properties integrate with the standard ``/properties`` endpoints:

**GET all items**::

  GET /{actor_id}/properties/{list_name}
  # Returns: [item1, item2, ...]

**GET all properties (default / format=short)**::

  GET /{actor_id}/properties
  # Returns: {"name": "Alice", "notes": {"_list": true, "count": 2}}

**GET all properties with full list data (format=full)**::

  GET /{actor_id}/properties?format=full
  # Returns: {"name": "Alice", "notes": {"_list": true, "count": 2, "description": "...", "items": [...]}}

**GET metadata only (metadata=true)**::

  GET /{actor_id}/properties?metadata=true
  # Returns: {"simple": {"properties": [...], "total_bytes": N}, "lists": {...}}

**GET/POST items** (an implementation extension, not part of the ActingWeb
spec -- the spec addresses items by path index,
``/properties/{list_name}/{index}``)::

  GET /{actor_id}/properties/{list_name}/items
  # Returns: {"items": [{"index": 0, "item": item0}, {"index": 1, "item": item1}, ...], "count": N}
  # "index" is the STORAGE index -- the same index accepted by the
  # update/delete actions below, so the two are always consistent.

  POST /{actor_id}/properties/{list_name}/items
  Content-Type: application/json
  {"action": "add", "item_value": {...}}          # append to end
  {"action": "update", "item_index": N, "item_value": {...}}
  {"action": "delete", "item_index": N}

**PUT item at index**::

  PUT /{actor_id}/properties/{list_name}?index=0
  Content-Type: application/json
  {...item data...}

  # index == current list length: creates (appends) the item.
  # index > current list length: 404 Not Found (no padding is created).

**DELETE entire list**::

  DELETE /{actor_id}/properties/{list_name}

**GET/PUT metadata**::

  GET /{actor_id}/properties/{list_name}/metadata
  PUT /{actor_id}/properties/{list_name}/metadata
  Content-Type: application/json
  {"description": "...", "explanation": "..."}

**Corrupted list (409 Conflict)**

Every list-serving path above (GET on the list, ``/items``, ``format=full``
and ``metadata=true`` on the properties root) returns structured 409 if it
finds an item missing from storage within the list's recorded length --
the residue an interrupted delete/insert can leave. This can only happen
on a v1 (dense-integer) list -- see `Storage Format (v1 / v2)`_ above;
a v2 list has no separate stored length for a row to disagree with, so
this failure mode is structurally impossible there::

  {"error": "list_corrupted", "list": "notes", "detail": "...", "remedy": "compact"}

There is no HTTP repair endpoint. Repair through the library API --
``actor.property_lists.notes.verify()`` to inspect, ``.compact()`` to fix
-- or the operator sweep script, ``scripts/verify_property_lists.py``.
``verify()``/``compact()`` also work on v2 lists, for a different purpose:
detecting and rebalancing rank keys that have grown long from repeated
inserts at the same position, before they approach the internal length
cap.

See the ActingWeb specification and Properties handler documentation for complete API details.

Web UI
------

The UI detects list properties and provides dedicated list pages with item and metadata editing. See :doc:`web-ui` for template customization.
