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

REST API
--------

List properties integrate with the standard ``/properties`` endpoints:

**GET all items**::

  GET /{actor_id}/properties/{list_name}
  # Returns: [item1, item2, ...]

**GET with metadata**::

  GET /{actor_id}/properties?metadata=true
  # Returns list metadata: {"_list": true, "count": N, "description": "...", ...}

**POST new item** (append to end)::

  POST /{actor_id}/properties/{list_name}/items
  Content-Type: application/json
  {"action": "add", "item_value": {...}}

**PUT item at index**::

  PUT /{actor_id}/properties/{list_name}?index=0
  Content-Type: application/json
  {...item data...}

**DELETE entire list**::

  DELETE /{actor_id}/properties/{list_name}

**GET/PUT metadata**::

  GET /{actor_id}/properties/{list_name}/metadata
  PUT /{actor_id}/properties/{list_name}/metadata
  Content-Type: application/json
  {"description": "...", "explanation": "..."}

See the ActingWeb specification and Properties handler documentation for complete API details.

Web UI
------

The UI detects list properties and provides dedicated list pages with item and metadata editing. See :doc:`web-ui` for template customization.
