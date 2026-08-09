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
supported, and which one a given list uses does not change any REST
response or any value the API returns.

It is not entirely invisible in one respect: **reading items one at a time
by index costs more under v2**. ``lst[i]`` re-reads the list's key ordering
before resolving the position, because a cached ordering can be stale and
resolving against a stale one returns the wrong item. So a
``for i in range(len(lst)): lst[i]`` loop is two queries per item under v2,
where v1 was one. Use ``to_list()``, ``to_indexed_list()`` or plain
iteration instead -- each is a single query for the whole list regardless
of length, in both formats, and ``to_indexed_list()`` returns the
``(index, item)`` pairs such a loop is usually after.

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

.. note::

   A list created before this restriction existed may legitimately contain
   ``#`` in its name. Such a list keeps working as v1 forever (migration
   refuses it, see below), and the library keeps it isolated from any v2
   list whose name is a prefix of it: a list named ``foo-#bar`` stores rows
   that fall inside the byte range a v2 list named ``foo`` reads, so the
   range read additionally requires a well-formed rank key. Renaming such
   lists is still the cleaner long-term answer, and it is what unblocks
   migrating them.

**Migrating existing v1 lists to v2**

Existing v1 lists keep working indefinitely -- migration is optional and
gradual, never required for a list to keep functioning:

- **Lazy** (**off by default**): set
  ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH`` to a positive number and a v1 list
  with at most that many items migrates automatically the next time it's
  mutated (``append``, ``insert``, item assignment, or item deletion). 50 is
  a reasonable value. A failed lazy migration is logged and the mutation
  still succeeds against the v1 storage -- migration never turns an ordinary
  write into a failure.

  It defaults to off because it is a **rollback-safety** control: see the
  danger box below. Leaving it off means the upgrade changes no stored data
  at all, so rolling back stays a pure code rollback. Turn it on once the
  release has been live long enough that rollback is off the table -- or
  skip it and use the bulk script, which is the same operation on a rate
  limiter and at a time you choose.

  This does not make v2 opt-in: **every list created from now on is v2**
  regardless of this setting. Only the conversion of lists that already
  exist is deferred.

  Two further things lazy migration deliberately will **not** do, whenever
  it is enabled:

  - **It never migrates a damaged list.** If ``verify()`` reports the list
    unhealthy, migration is skipped with an operator-actionable warning.
    Migration closes holes in flight, which is correct when an operator
    runs the script and reads its report -- but silently, under an
    ordinary write, it would erase the evidence: the hole disappears, the
    lost item stays lost, duplicate residue becomes indistinguishable from
    real data, and ``verify()`` starts reporting the list healthy. Repair
    is an explicit decision. Run ``compact()`` (or
    ``verify_property_lists.py --repair``), then migrate.
  - **It runs inline, in the request.** One ``append()`` to a 40-item v1
    list performs the whole migration before the append itself -- dozens of
    sequential writes plus two full-partition reads. That is the second
    reason to leave it at ``0`` on Lambda or any latency-sensitive
    deployment, after the rollback hazard below.

  When enabled, the size threshold is checked **at the moment of the
  mutation**, which is not the same as "large lists stay v1 until I run the
  script". A
  ``clear()`` followed by ``extend()`` -- a whole-list rewrite, the shape a
  prune or a re-sync usually takes -- migrates a list of *any* original
  size, because the first ``append()`` inside ``extend()`` sees a list of
  length 0. If you are planning a controlled rollout, that is the case to
  know about; ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH=0`` -- the default -- is
  the only setting that makes "no list migrates without me" true.
- **Bulk**: larger or idle lists are migrated with the operator script::

    actingweb-migrate-property-lists              # dry run
    actingweb-migrate-property-lists --migrate

  The script reports lists it refuses to migrate -- names containing ``#``
  (rename first) and lists with holes or orphans (repair first) -- and any
  duplicate-value residue it preserves as-is. The dry run exits ``1`` if
  anything would be refused, so ``0`` means the migration has nothing to
  trip over; treat that as the gate rather than reading the log.
- **Programmatic**: ``actor.property_lists.<name>._list_prop.migrate_to_v2()``
  migrates one list directly. Idempotent -- safe to call again (a no-op
  once the list is already v2) and safe to re-run after an interruption.

.. warning::

   **Migration refuses a damaged list, and this is worth understanding
   rather than working around.** Migrating a list with a hole in it is not
   merely lossy -- it is *unreportably* lossy. The surviving rows are
   renumbered, so afterwards the hole is gone, the list verifies healthy,
   and nothing is left to say an item was ever destroyed. Repair first
   (``actingweb-verify-property-lists --repair``, or ``compact()``), which
   closes the hole while leaving the duplicate evidence intact, and the
   question does not arise.

   ``--migrate-damaged`` (or ``migrate_to_v2(allow_damaged=True)``) exists
   for the operator who has looked at the damage and decided to move on. It
   logs what it is giving up.

   Duplicate residue does **not** block migration, because it survives the
   conversion visibly -- a v2 list's ``verify()`` reports duplicates the
   same way a v1 list's does. Only holes and orphans gate.

.. danger::

   **No list may become v2 until every process that serves it can read v2 --
   and that includes the release you might roll back to.**

   An older process does not error on a v2 list. It reads it as **empty**,
   silently: the metadata row still exists (so the list "exists"), but a v2
   list stores no ``length`` field and a pre-v2 reader takes the absence as
   zero. Worse, a write from that process lands in v1 storage and the list
   **forks** -- two versions, two disjoint views of one list, neither
   reporting anything wrong. ``--downgrade`` cannot reconcile a forked list
   afterwards; it overwrites v1 storage with the v2 content, destroying
   whatever the older process wrote there.

   The dangerous direction is **rollback**, not deployment. A deploy leaves
   at most a brief mixed-version window. A rollback does not: deploy, let
   lazy migration convert lists for hours or days, then roll back for an
   unrelated reason, and *every list that migrated* now reads as empty in
   production. There is no timing to be lucky about, and recovery is
   ``--downgrade`` one list at a time, from a v2-capable checkout, against a
   database being served by the code you just rolled back to.

   Migration forward is automatic, fleet-wide and inline. Recovery back is
   manual and per-list. Size your caution to that asymmetry.

   **This is why ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH`` defaults to 0.**
   Out of the box, no existing list changes format, so an upgrade stays a
   pure code change with no data to reconcile if you roll back. Convert
   later, once the release has been live long enough that rollback is off
   the table, as a deliberate rate-limited step via
   ``scripts/migrate_property_lists.py --migrate`` -- or by setting the
   variable to a positive number and letting ordinary writes do it. Either
   way it is your decision and your timing, which is the point.

.. warning::

   There is no supported forward path from v1 to v2 other than migration,
   and downgrading a v2 list back to v1 is an **emergency-only** operation
   (``scripts/migrate_property_lists.py --downgrade ACTOR_ID/list_name``),
   intended for rolling back to a release that predates v2 support. It
   takes no lock against concurrent writes and is not part of the normal
   operational flow -- do not script it into routine tooling.

   **Order matters.** Where lazy migration has been enabled, a downgraded
   list at or under ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH`` is, by
   definition, a lazy-migration candidate again -- if the *current*
   application (the one with v2 support) is still running against it, its
   very next mutation (``append``/``insert``/item ``__setitem__``/
   ``__delitem__``) migrates it straight back to v2, silently undoing the
   downgrade. At the default of 0 that particular race is off, but the
   ordering rule is the same either way, because a v2-aware application
   still writes v2 to any list it creates or converts.
   Roll the application back to the pre-v2 release **first**,
   then run ``--downgrade`` against the database from a checkout that
   still has v2 support (the tool itself needs the v2 code to read the
   list it's converting) -- never the other way around.

REST API
--------

List properties integrate with the standard ``/properties`` endpoints:

**Create an empty list**::

  POST /{actor_id}/properties
  Content-Type: application/json
  {"notes": {"_type": "list"}}
  # Returns 201: {"notes": "[Empty list property created]"}

  # The list must exist before the /items endpoint below will accept
  # anything for it -- POST /items on an unknown list is a 404.

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

.. note::

   ``verify()`` has two duplicate checks and each is blind to what the other
   catches. ``adjacent_duplicates`` compares raw stored bytes of neighbouring
   rows -- exactly the residue an interrupted shift leaves, but it stops
   finding a duplicate once either copy is edited. Pass
   ``identity_key="id"`` (or whatever field identifies your items) to also
   get ``duplicate_identities``, which compares that field across the whole
   list: it survives later edits, and it does not assume the copies stayed
   neighbours. Duplicates from a different mechanism -- a failed read turning
   an upsert into an append, say -- are under no obligation to be adjacent.
   Both sweep tools take ``--identity-key``. Check
   ``identity_checked_count`` in the report before trusting an empty
   result: rows without the field are excluded from the comparison, so a
   mistyped key produces a report shaped exactly like a clean one having
   compared nothing.

   The tools ship with the library as ``actingweb-verify-property-lists``
   and ``actingweb-migrate-property-lists``, so they are available from an
   installed wheel; ``scripts/`` keeps thin wrappers for repo checkouts.

There is no HTTP repair endpoint. Repair through the library API --
``actor.property_lists.notes.verify()`` to inspect, ``.compact()`` to fix
-- or the operator sweep script, ``scripts/verify_property_lists.py``.
``verify()``/``compact()`` also work on v2 lists, for a different purpose:
detecting and rebalancing rank keys that have grown long from repeated
inserts at the same position, before they approach the internal length
cap.

.. warning::

   ``compact()`` is not crash-safe end to end, in **either** storage format.
   It writes every item to its new location before retiring any old row, so
   an interruption partway leaves a copy at both. Re-running ``compact()``
   does not undo that -- it treats every copy as a genuine item, and under
   v1 it explicitly declines to touch duplicate residue at all. Prefer
   running it when the actor is not taking writes, and re-run ``verify()``
   afterwards rather than assuming success.

   **v1** (dense integers): interrupting the rewrite of a 4-slot list with
   one hole leaves ``[a, c, c, d]`` or ``[a, c, d, d]`` with the length
   still reading 4 -- readable with no error, because nothing is
   structurally inconsistent. ``verify()`` catches it through the adjacent
   byte-identical heuristic, but repair will not remove it: duplicates are
   preserved by design, including the one repair itself created. Resolving
   it is manual.

   **v2** (rank keys): the same window, as a rank rebalance. The deliberate
   trade here is that the alternative -- retiring each old row as its
   replacement is written -- would leave interrupted states silently
   *reordered* instead, which nothing detects at all. Recovery is manual;
   the stale copies are the ones whose rank keys are not part of the evenly
   spaced sequence a fresh rebalance produces.

See the ActingWeb specification and Properties handler documentation for complete API details.

Web UI
------

The UI detects list properties and provides dedicated list pages with item and metadata editing. See :doc:`web-ui` for template customization.
