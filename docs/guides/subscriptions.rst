====================
Subscription Manager
====================

Overview
--------

A peer may subscribe only to what it may read (3.16, as the protocol
requires): creating a subscription to a ``properties``, ``resources``,
``methods`` or ``actions`` path its grant does not let it read answers 403
(``{"error": "forbidden"}``). A subscription to a whole target needs a rule
that reads at least one name (or, when the grant does not mention the
category, the access table's GET on it). What each diff carries is filtered
again at delivery for ``properties``. For ``resources``, ``methods`` and
``actions`` the same creation check is asked again at delivery, push and
pull: a subscription the grant no longer admits delivers nothing. An
application's own target (any other name) needs only an approved trust at
delivery: the grant has no category
for it, and a subscription the application made itself never passed the
route's creation row. So changing a peer's relationship to one whose access
table would not let it create the subscription does not stop one it already
has; withdraw approval, or delete the subscription, to stop it. Their
content is delivered as registered, so filter it in the application if it
carries data some subscribers may not read. A peer whose
trust this actor has not approved may not list its subscriptions.

The ActingWeb subscription system enables real-time data synchronization between actors. Actors can:

- **Subscribe** to updates from peer actors
- **Notify** their subscribers when data changes
- **Process** incoming callbacks with automatic sequencing and deduplication

.. seealso::

   :doc:`p2p-quickstart` walks through establishing trust and subscribing to
   a peer end-to-end in one runnable example.

Usage
-----

.. code-block:: python

   # Outbound subscription
   actor.subscriptions.subscribe_to_peer(
       peer_id="peer123", target="properties", granularity="high"
   )

   # Notify subscribers
   actor.subscriptions.notify_subscribers(
       target="properties", data={"status": "active"}
   )

   # A change inside one property: write it first, then notify. A
   # subscriber above the resource is sent the property's whole stored
   # value (3.16), one at resource level the resource's value.
   actor.subscriptions.notify_subscribers(
       target="properties", data={"unit": "C"},
       subtarget="settings", resource="display",
   )

   # Introspection
   for sub in actor.subscriptions.all_subscriptions:
       print(sub.peer_id, sub.target)

   # Unsubscribe
   actor.subscriptions.unsubscribe(peer_id="peer123", subscription_id="sub123")

Properties
----------

- ``all_subscriptions``: all inbound/outbound
- ``outbound_subscriptions``: to other actors
- ``inbound_subscriptions``: from other actors
- ``get_subscriptions_by_peer()`` (3.16): every subscription grouped by peer
  id, as ``PeerSubscriptions`` (``peer_id``, ``outbound``, ``inbound``); a
  peer with none has no key. Through a peer view only that peer's key;
  through a client view its trust's peer id and its client id (a client's
  subscriptions filed before 3.16 are under the client id).

An actor reads its subscription list once per instance, an empty list too
(3.16): these listings, and every diff the instance registers, use that
read. The instance reads again after its own creates and deletes, a resume,
and every call of the trust methods that can send a request to the peer. An instance kept across
requests does not see subscriptions created elsewhere; the actors the
library hands to hooks and handlers are built per request.

Callback Delivery
-----------------

Since 3.16 one sender delivers every subscriber's callback for a write
(``actingweb.callback_sender``):

- **Concurrently, with a bound per write.** Subscribers on other hosts are
  sent at most ``max_concurrent_callbacks`` at a time (default 4). Each
  subscription's own sequence orders its diffs, so overlapping sends are safe.
- **Subscribers on the publisher's own host one at a time**
  (``serialize_own_host_callbacks``, default on): such a subscriber needs a
  handler of the same process to answer, and a low-granularity one a second
  for its fetch back. The two groups run alongside each other, so a write
  waits for the longer of them, not the sum. A subscriber is on the own host
  when its trust's base URI has the publisher's origin (scheme, host, port).
- **Ordered callbacks to one subscriber** arrive in order, and stop at the
  first that was not delivered.
- **Timeouts:** 5 s to connect and 10 s to read for a diff, 30 s to read for
  a resync.

Where the write waits:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Where the write runs
     - What the sender does
   * - Off the event loop (Flask, FastAPI's sync handlers, the SDK in a
       thread), or ``with_sync_callbacks()``
     - The write returns when every send has answered or timed out (or the
       delivery budget ran out). A resync that was not delivered (refused,
       timed out, a 503 from a subscriber that could not fetch its baseline)
       is recorded and sent again on the next resume.
   * - On a running event loop without ``with_sync_callbacks()``
     - The sends are tasks the library keeps a reference to until done, not
       awaited; the write returns at once. On a function platform the
       instance may freeze before they finish, which is why that shape sets
       ``with_sync_callbacks()``.

``with_sync_callbacks()`` on a running loop blocks the loop while the sends
run: it is for handlers that run off the loop.

**The delivery budget** (``callback_delivery_budget_seconds``, off by
default) gives one request a total time for delivering its callbacks (every
write in it shares the deadline): each
send's timeouts are clipped to what is left, and a send that would start with
nothing left is not made. Every diff was stored and numbered before any send,
so a subscriber that was skipped sees the gap at its next callback, or polls.
Set it under a gateway's response limit, not as a tuning knob. See
:doc:`../quickstart/deployment` for the two deployment shapes.

Callback sends no longer set ``Actor.last_response_code`` (3.16); trust and
peer calls still do.

========================
Subscription Processing
========================

Overview
--------

The subscription processing system provides automatic handling of incoming subscription callbacks, including:

- **Sequencing**: Process callbacks in order, even if they arrive out-of-order
- **Deduplication**: Skip duplicate or outdated callbacks
- **Resync handling**: Automatically trigger full resync when gaps are detected
- **Storage**: Store received data in actor attributes
- **Cleanup**: Remove peer data when trust relationships end

This reduces ~500+ lines of manual callback handling code to ~30 lines of application logic.

Quick Start
-----------

Enable subscription processing with minimal configuration:

.. code-block:: python

   from actingweb.interface import ActingWebApp

   app = (
       ActingWebApp(
           aw_type="urn:actingweb:example.com:myapp",
           database="dynamodb",
           fqdn="myapp.example.com",
           proto="https://"
       )
       .with_subscription_processing(
           auto_sequence=True,   # Handle out-of-order callbacks
           auto_storage=True,    # Store peer data automatically
           auto_cleanup=True,    # Clean up on trust deletion
       )
   )

   @app.subscription_data_hook("properties")
   def on_property_change(
       actor,
       peer_id: str,
       target: str,
       data: dict,
       sequence: int,
       callback_type: str,  # "diff" or "resync"
   ):
       """Called with already-sequenced, deduplicated, stored data."""
       print(f"Received {callback_type} from {peer_id}: {data}")

Configuration Options
---------------------

The ``with_subscription_processing()`` method accepts these parameters:

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Parameter
     - Default
     - Description
   * - ``auto_sequence``
     - ``True``
     - Enable CallbackProcessor for sequencing/deduplication
   * - ``auto_storage``
     - ``True``
     - Enable RemotePeerStore for storing peer data
   * - ``auto_cleanup``
     - ``True``
     - Clean up peer data when trust is deleted
   * - ``gap_timeout_seconds``
     - ``5.0``
     - Seconds before a sequence gap triggers resync
   * - ``max_pending``
     - ``100``
     - Maximum pending callbacks before a callback is refused
   * - ``max_concurrent_callbacks``
     - ``4``
     - Callbacks of one write sent at once to subscribers on other hosts
       (read since 3.16; it was 10 and read by nothing)
   * - ``callback_delivery_budget_seconds``
     - ``None``
     - Total time one request may spend delivering its callbacks; off unless
       set (see "Callback Delivery")
   * - ``serialize_own_host_callbacks``
     - ``True``
     - Send subscribers on the publisher's own host one at a time; turn off
       only for one request per function instance

``max_payload_for_high_granularity``, ``circuit_breaker_threshold`` and
``circuit_breaker_cooldown`` were removed in 3.16 (they configured
``FanOutManager``, which was never on the publish path): passing one raises
``RuntimeError`` naming :doc:`../migration/v3.16`.

Subscription Data Hooks
-----------------------

Register handlers for specific targets using the ``@subscription_data_hook`` decorator:

.. code-block:: python

   @app.subscription_data_hook("properties")
   def on_properties(actor, peer_id, target, data, sequence, callback_type):
       """Handle property changes from peers."""
       for key, value in data.items():
           print(f"Property {key} = {value}")

   @app.subscription_data_hook("resources")
   def on_resources(actor, peer_id, target, data, sequence, callback_type):
       """Handle resource changes from peers."""
       pass

   # Wildcard handler for all targets
   @app.subscription_data_hook("*")
   def on_any_target(actor, peer_id, target, data, sequence, callback_type):
       """Handle any callback not matched by specific handlers."""
       print(f"Unhandled target: {target}")

Hook Parameters
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Parameter
     - Description
   * - ``actor``
     - The ActorInterface receiving the callback
   * - ``peer_id``
     - ID of the peer actor sending the callback
   * - ``target``
     - Target resource (e.g., "properties", "resources")
   * - ``data``
     - The callback payload (already processed and stored)
   * - ``sequence``
     - Sequence number of the callback
   * - ``callback_type``
     - Either "diff" (incremental) or "resync" (full state)

Callback Types
--------------

**Diff Callbacks** (``callback_type="diff"``):

Regular incremental updates containing only changed data:

.. code-block:: json

   {
     "id": "actor123",
     "subscriptionid": "sub456",
     "sequence": 42,
     "target": "properties",
     "data": {"status": "active"},
     "timestamp": "2026-01-20T12:00:00.000000Z"
   }

**Resync Callbacks** (``callback_type="resync"``):

Full state replacement, triggered when:

- A sequence gap exceeds the timeout
- The publisher calls ``resume_subscriptions()``
- Initial sync after subscription creation

An OAuth2 client's subscription (one an ``as_client`` view created) is sent
no callback: the client reads its diffs. On ``resume_subscriptions()`` its
next diff is a resync marker: ``GET /subscriptions/<peerid>/<subid>`` (and
``/<seq>``) serves it with ``"type": "resync"``, the ``url`` to re-read and
empty ``data``. The client discards its cached state for what the ``url``
names (one property when the publisher resumed one subtarget, which can be
narrower than the subscription) and GETs the URL, under its own grant, as
on a resync callback. The re-read already holds what the diffs after the
marker in the same answer change under that URL, so the client skips those
changes, applies the others as usual, and acknowledges up to the answer's
highest sequence.

Resync callbacks include a ``type`` field and a ``url`` to fetch the full state:

.. code-block:: json

   {
     "id": "actor123",
     "subscriptionid": "sub456",
     "sequence": 43,
     "target": "properties",
     "type": "resync",
     "url": "https://example.com/actor123/properties",
     "timestamp": "2026-01-20T12:00:00.000000Z"
   }

A resume sends this callback to every subscriber with a callback endpoint,
whatever option tags it advertises (3.16; a peer cached without
``subscriptionresync`` was sent the full state as ordinary diffs before). A
subscriber that does not know the type re-reads on its own schedule.

What a Subscriber Is Told
~~~~~~~~~~~~~~~~~~~~~~~~~

Since 3.16 (specification 1.5) every writer, the REST handlers, the web UI
and ``actor.properties``, registers the same diffs:

- **A delete is ``""``** at the level that was deleted, and ``{name: ""}``
  above it. A subscription to the deleted name itself receives ``""`` with a
  sequence number (a REST delete reached it with nothing before). A
  subscription to a resource (``name/key``) receives ``""`` when its key went
  with its parent: the parent was deleted, or overwritten by a value without
  the key. It receives nothing when the key never existed. A data hook reads
  ``""`` as "absent"; a stored empty string cannot be told from a delete.
- **A nested write sends the parent's whole stored value** to a subscription
  above the resource (``{name: whole}`` at target level): a receiver applies
  a target- or subtarget-level value whole, so the partial ``{name: {key:
  value}}`` sent before 3.16 dropped the parent's other keys from replicas.
  A resource subscription still receives its resource.
- **A diff carries the value stored after the property hooks**, not the
  request body.
- **A clear** (``DELETE /properties``, ``actor.properties.clear()``) is one
  diff naming every deleted property (``{"a": "", "b": ""}``), one sequence
  number and one callback per subscriber. Lists are not cleared and are not
  in it.
- **The timestamp** of every callback, resync callback and poll is ISO 8601
  in UTC with ``Z`` and microseconds (``2026-01-20T12:00:00.000000Z``);
  callbacks sent ``str()`` of the stored time and resync callbacks an offset.
- **A ``none`` subscription** is sent no resync callback on resume: the
  resync waits in its queue as a diff of ``"type": "resync"``, and the
  library's poll (``sync_subscription``) acts on it as a resync: it rebuilds
  the replica from the URL and clears the queue through it. A failed fetch
  leaves the marker queued and the rebuild owed.
- **The poll runs the data hooks** for each change it applies, as a pushed
  callback does, when it is given the application's configuration; the
  library's gap resync is. The triggering callback of a gap resync is
  applied when the poll did not bring its sequence.

What the receiver answers and does:

- **A resync is fetched at the stored subscription's level**, whatever the
  callback body names, and afterwards the replica no longer holds what the
  baseline lacks (whole target: every name it does not carry; a subtarget:
  that name). The sweep lists the replica, so it runs at most once a minute
  per subscription; a resync inside that minute is applied without it and
  leaves the rebuild owed, which the next callback or sync runs once the
  minute has passed. The data hook gets the baseline; it is not told name by
  name what the sweep removed.
- **A resync whose fetch fails answers 503** with ``Retry-After``, records no
  sequence and marks the rebuild owed. The next callback runs the owed
  rebuild once it is due, whatever its sequence; a publisher on 3.16 sends
  the resync again on its next resume. A gone resource (404) is an empty
  value, not a failure.
- **A callback with ``data`` and no integer ``sequence`` answers 400**, as a
  low-granularity one without a sequence does (it was taken as a duplicate).
- **``PUT /subscriptions/<peer>/<id>`` with ``{"sequence": 0}``** answers 204
  and clears nothing; ``{"sequence": n}`` clears through ``n``.
- **A granularity other than ``high``, ``low`` or ``none``** answers 400 at
  the publisher, and ``create_remote_subscription`` refuses it before
  sending anything.

Peer Capability Discovery
-------------------------

Check what features a peer supports before using optional protocol features:

.. code-block:: python

   from actingweb.peer_capabilities import PeerCapabilities

   caps = PeerCapabilities(actor, peer_id)

   # Check specific capabilities
   if caps.supports_resync_callbacks():
       # Peer can handle type="resync" callbacks
       pass

   if caps.supports_compression():
       # Peer accepts compressed payloads
       pass

   if caps.supports("permissionquery"):
       # Peer answers GET /{actor_id}/permissions/{peer_id}
       pass

   # Get all supported options
   all_options = caps.get_all_supported()
   print(f"Peer supports: {all_options}")

   # Get protocol version
   version = caps.get_version()
   print(f"Peer version: {version}")

Remote Peer Storage
-------------------

Store and retrieve data synchronized from peers:

.. code-block:: python

   from actingweb.remote_storage import RemotePeerStore

   # Create store for a specific peer
   store = RemotePeerStore(actor, peer_id)

   # Scalar values
   store.set_value("status", {"active": True, "updated": "2026-01-20"})
   status = store.get_value("status")
   store.delete_value("status")

   # Lists (a baseline replaces the list)
   store.set_list("items", [{"id": 1}, {"id": 2}])
   items = store.get_list("items")

   # Apply a callback's data, as the library does for a whole-target
   # subscription: a list diff keyed by its own list name
   result = store.apply_callback_data({
       "items": {"list": "items", "operation": "append", "length": 3,
                 "index": 2, "item": {"id": 3}},
   })
   if result.out_of_step:
       # The replica could not apply a list diff; rebuild it from a baseline
       actor.subscriptions.rebuild_subscription(peer_id, subscription_id)

   # Enumerate stored data
   scalar_names = store.list_all_scalars()   # ["status", "config"]
   list_names = store.list_all_lists()       # ["items", "history"]
   all_props = store.get_all_properties()    # Combined view with type metadata

   # Storage stats
   stats = store.get_storage_stats()
   print(f"Stored {stats['scalar_count']} scalars, {stats['list_count']} lists")

   # Cleanup
   store.delete_all()  # Remove all data for this peer

List Operations
~~~~~~~~~~~~~~~

Every change to a property list registers a *list diff* on the list's own
subtarget (3.16: the SDK, REST and web-UI edits alike). A diff always
carries ``list`` (the list's name), ``operation`` and ``length`` (the
publisher's list length after the change, advisory), plus the fields its
operation needs. ``actingweb.property_list.build_list_diff()`` builds the
same diffs for application code; its operations are
``LIST_DIFF_OPERATIONS``. The subscription processing system applies them
to the replica:

.. list-table::
   :header-rows: 1
   :widths: 14 30 56

   * - Operation
     - Fields besides ``list``, ``operation``, ``length``
     - What the replica does
   * - ``append``
     - ``item``, ``index`` (advisory)
     - Appends ``item``; ``index`` is never used as an address
   * - ``extend``
     - ``items``
     - Appends every item. An empty ``items`` for a list the replica does
       not hold creates the empty list (a new list created over REST or in
       the web UI)
   * - ``insert``
     - ``item``, ``index``
     - Inserts at ``index``
   * - ``update``
     - ``item``, and ``index``, ``old_item`` or both
     - With ``old_item``: replaces the one row holding that value, or, when
       several do, the one at ``index``. No row holding it with ``item``
       already there is a no-op (applied before); any other miss (no row,
       or several none of which is at ``index``) is out of step. Without
       ``old_item``, replaces the row at ``index``
   * - ``delete``
     - ``index``, and ``old_item`` when the item was read
     - With ``old_item``: removes the one row holding that value, or, when
       several do, the one at ``index`` (none at ``index`` is out of step);
       no row holding it is a no-op (applied before). ``length`` is not
       consulted (advisory in the specification). Without ``old_item``:
       removes the row at ``index``. REST, bulk and web-UI deletes send this
   * - ``pop``
     - ``index`` (default ``-1``, negative counts from the end)
     - Removes the row at ``index``
   * - ``remove``
     - ``item``
     - Removes the first row equal to ``item``; an absent item is a no-op
   * - ``clear``
     - none
     - Empties the list and keeps it
   * - ``delete_all``
     - none (``length`` is ``0``)
     - Deletes the list
   * - ``metadata``
     - none
     - Nothing: the description and explanation are not replicated; the
       diff tells a hook that they changed

An index out of range, a damaged or conflicting list in the replica, a
reference (below), or a scalar arriving for a list's name means the replica
no longer holds what the publisher's list held: it is *out of step* and is
rebuilt (see `How a replica is stored`_). A bulk ``POST /properties`` with
``items`` sends up to 25 changes in order, a run of appends as one
``extend``; more than 25 send no per-item diff and one resync of the list
after the batch (``Actor.request_resync``).

``delete_by_handle()``, ``update_by_handle()``, ``remove_where()``, and
``update_where()`` (added in 3.14) do not add new operations to this table
-- the diff vocabulary above is closed, so a peer running an older
ActingWeb version keeps understanding every diff it receives, except a
3.16 *reference* (below). Instead:

- ``delete_by_handle()`` and a multi-match ``remove_where()`` each emit
  one ``remove`` diff per item actually removed, carrying that item's
  full value.
- ``update_by_handle()`` and ``update_where()`` each emit one ``update``
  diff per item actually updated, carrying the new ``item`` value and an
  OPTIONAL ``old_item`` field -- the pre-update value. Neither emits
  ``index``: a value-addressed update does not have a reliable position
  to send, since diff delivery between peers isn't guaranteed reliable
  or ordered and a peer's list may already have drifted from the
  sender's by the time the diff arrives. A peer receiving ``old_item``
  locates the row by matching its current value against it, but only
  when that match is unique -- if two or more rows currently hold that
  value, which one the sender meant is ambiguous, and the update is not
  applied rather than risking the wrong row. A peer that predates
  ``old_item`` simply ignores the field; without ``index`` present
  either, it has nothing to match the diff against. (A REST
  ``PUT ?index=N`` update carries both, so an ambiguous match falls back
  to the index.)

**References (3.16).** A list diff whose encoded blob would exceed the
publisher's span threshold (``list_item_span_threshold``; 390,000 bytes on
DynamoDB by default, off on PostgreSQL) is sent as a *reference*: the
value-carrying fields (``item``, ``old_item``, ``value``, ``items``) are
removed and top-level ``"spanned": true`` and ``"bytes": n`` (the values'
total encoded size) are added, for example::

    {"list": "docs", "operation": "append", "length": 4,
     "index": 3, "spanned": true, "bytes": 1048590}

That covers a spanned item, an ``update`` whose old and new values together
are too large, and an ``extend`` of many items. The library's receiver does
not apply a reference and does not fetch the values: the replica is out of
step, a WARNING names the list and the operation, and the replica is
rebuilt from a baseline (see `How a replica is stored`_). A reference is the one diff a pre-3.16 peer does not understand:
with the value fields absent it answers ``unknown operation`` and stores
nothing.

One positional field became advisory in 3.14: the ``index`` an
``append`` diff carries (and the ``length`` field every list diff
carries) derives from the list's advisory count rather than a fresh
count of the rows, so under concurrent mutation it can be momentarily
off by the documented drift bound (see "Storage Format" in the
property-lists guide). Apply an append by appending ``item``; treat
``index`` and ``length`` as ordering hints, never as addresses. The
library's own receiver has always done exactly this.

Because ``remove_where()``/``update_where()`` can match many items in one
call, they can also emit many diffs in one call -- see the fan-out note
below for what that means for delivery time.

How a replica is stored
~~~~~~~~~~~~~~~~~~~~~~~

A subscriber keeps each peer's data in the attribute bucket
``remote:<peer_id>``, which is never served over HTTP. A scalar is one
attribute; a list is stored in the property list layout
(``list:<name>-meta`` and one ``list:<name>-#<rank>`` row per item, an item
over the span threshold in the side bucket ``remote:<peer_id>$aux``; see
:doc:`property-lists`). A replica list written before 3.16 is read in place
and converted on its first change.

Where a callback's data lands depends on the subscription's level, which is
why ``apply_callback_data()`` and ``apply_resync_data()`` take it as the
keyword-only ``subtarget`` and ``resource``:

- **Whole target** (``properties``): a set of top-level keys. A value is a
  list diff only when its ``list`` equals the key it arrived under;
  anything else is that key's scalar value, so a property value shaped like
  a list diff never edits another list.
- **Subtarget** (``properties/notes``): stored under the subtarget's name. A
  diff whose ``list`` is the subtarget is one list operation, an object keyed
  by the subtarget's own name is its full state, and anything else is the
  one scalar's value. A baseline is stored the same way, never spread into
  top-level keys.
- **Resource** (``properties/settings/theme``): merged at the resource's
  path inside the stored property; an empty value deletes that path.

.. code-block:: python

   from actingweb.remote_storage import RemotePeerStore

   store = RemotePeerStore(actor, peer_id)
   result = store.apply_callback_data(
       {"list": "notes", "operation": "delete", "index": 1, "old_item": "old", "length": 2},
       subtarget="notes",          # the subscription's subtarget, or None
       resource=None,              # the subscription's resource, or None
   )
   result.out_of_step   # None, or {"list", "operation", "why"}
   result.failed        # names whose entry could not be stored

The result is a ``ReplicaApplyResult``: a dict of per-key results whose
``out_of_step`` and ``failed`` are attributes, never keys (a key is a name
the peer chose). A name is a scalar or a list in a replica, never both: a
list arriving where a scalar is stored replaces it, ``""`` arriving for a
list's name deletes the list, and any other scalar arriving for a list's
name is out of step. A list a diff would create whose name has a control
character, ``#`` or ``$``, starts with ``_`` or is too long for a key is
refused (logged); a stored list of any name can still be changed and
deleted. A scalar key starting ``list:`` is refused, and so is a key
another bucket holds (``AttributeKeyCollision``, logged).

**Rebuilds.** A list diff the replica cannot apply marks it out of step.
The callback is still acknowledged, and the subscriber rebuilds the replica
from a baseline: it reads the subscription's sequence from the publisher,
fetches the baseline (again if the sequence moved meanwhile), replaces the
replica, deletes what the baseline no longer carries (at target level every
name it does not carry, at subtarget level the subtarget, and each list
recorded as out of step), records the sequence and clears the publisher's
diffs up to it. There is at most one attempt a minute per subscription,
successful or not; a rebuild owed inside that interval runs on the next
callback or ``sync_subscription()`` after it. A failure leaves it owed and
logs a WARNING (``Rebuild of <peer>:<subscription> ... stays owed``).
``actor.subscriptions.rebuild_subscription(peer_id, subscription_id,
force=True)`` (or ``rebuild_subscription_async``) runs one now; ``force``
skips the interval, never a rebuild already running. A direct call tells no
hook: its result's ``baseline`` is what it applied. A rebuild that a
callback or ``sync_subscription()`` runs is told to the data hooks once, as
``"resync"``.

A diff in the middle of a list (``insert``, ``update``, ``delete``,
``pop``, ``remove``) reads the replica's list, which costs O(n); appends do
not. When a peer is subscribed to both on its whole ``properties`` target
and on a subtarget, only the whole-target subscription writes the replica
(``ReplicaApplyResult.skipped`` for the other); the subtarget
subscription's hooks still run. A whole-target subscription that is only
polled (granularity ``none``) covers too, so the subtarget's values then
reach the replica when that subscription is polled (``sync_peer()``), not
when the subtarget's callbacks arrive.

**What a hook receives.** A subscription data hook (and a
``callback_hook("subscription")``, in ``data["data"]``) receives the
callback's data as sent. For
a whole-target subscription a list edit arrives keyed by its list name,
``{"notes": {"list": "notes", "operation": "append", "length": 3, "index":
2, "item": "x"}}``; for a subscription to the list's subtarget it is the
diff itself. A reference carries ``"spanned": true`` and ``"bytes"`` instead
of ``item``, ``old_item`` or ``items``. Test for a list diff with
``value.get("list") == key`` (whole target) or ``data.get("list") ==
subtarget``, not with ``"list" in value``.

Subscription Suspension
-----------------------

Publishers can temporarily suspend diff callbacks during bulk operations:

.. code-block:: python

   # Suspend callbacks for a target
   actor.subscriptions.suspend(target="properties")

   # Perform bulk operations without triggering callbacks
   for item in bulk_items:
       actor.properties.set(item["key"], item["value"])

   # Resume and send resync to all subscribers
   count = actor.subscriptions.resume(target="properties")
   print(f"Sent resync to {count} subscribers")

**Performance Note:**

The ``resume()`` operation uses **cached peer capabilities** to determine whether to send full resync callbacks or low-granularity callbacks. This avoids blocking on network requests to check peer capabilities:

- If capabilities are cached and fresh (< 24 hours): Uses cached value
- If cache is expired or missing: Assumes peer supports resync (optimistic approach)
- Background refresh updates the cache for next time (async mode only)

This ensures ``resume()`` returns immediately without blocking, even when suspending/resuming many subscriptions.

**Fan-out arithmetic for ``remove_where()``/``update_where()``:** a single
call that matches *k* items registers *k* diffs, and a synchronous HTTP
handler delivering those diffs to subscribers is still bound by the
platform's request timeout (for example API Gateway's ~29 second ceiling
on Lambda deployments). If *k* is large and the list has callback
subscribers, that per-request delivery cost is *k* callback deliveries,
not one -- the same shape as calling ``remove()``/``update_by_handle()``
in a loop, just issued from a single call. For a bulk change against a
list with subscribers, prefer suspending the ``properties`` target first
(``suspend()`` above), performing the ``_where`` call, then ``resume()``
-- one resync callback instead of *k* individual diff deliveries.

Advanced: Component-Level Usage
-------------------------------

For fine-grained control, use components directly:

.. code-block:: python

   from actingweb.callback_processor import (
       CallbackProcessor, CallbackType, ProcessedCallback, ProcessResult
   )
   from actingweb.remote_storage import RemotePeerStore

   # Create processor
   processor = CallbackProcessor(
       actor=actor,
       gap_timeout_seconds=10.0,
       max_pending=200,
   )

   # Process a callback manually. The handler runs for each callback taken
   # in order (a queued one included) and records a list diff the replica
   # could not apply, which makes the processor answer REBUILD.
   async def handle_callback(peer_id, sub_id, subscription, data, sequence):
       async def apply(cb: ProcessedCallback) -> None:
           store = RemotePeerStore(actor, cb.peer_id)
           level = {
               "subtarget": subscription.get("subtarget") or None,
               "resource": subscription.get("resource") or None,
           }
           if cb.callback_type == CallbackType.RESYNC:
               store.apply_resync_data(cb.data, **level)
           else:
               cb.out_of_step = store.apply_callback_data(cb.data, **level).out_of_step

       result = await processor.process_callback(
           peer_id=peer_id,
           subscription_id=sub_id,
           sequence=sequence,
           data=data,
           handler=apply,
       )

       if result == ProcessResult.PROCESSED:
           pass  # applied by the handler
       elif result == ProcessResult.DUPLICATE:
           # Skip - already processed
           pass
       elif result == ProcessResult.PENDING:
           # Gap detected, waiting for missing callbacks
           pass
       elif result == ProcessResult.RESYNC_TRIGGERED:
           # Gap timeout exceeded: sync from the publisher
           await actor.subscriptions.sync_subscription_async(peer_id, sub_id)
       elif result == ProcessResult.REBUILD:
           # The replica is out of step: replace it from a baseline
           await actor.subscriptions.rebuild_subscription_async(peer_id, sub_id)

   # Get state info
   info = processor.get_state_info(peer_id, sub_id)
   print(f"Last seq: {info['last_seq']}, Pending: {info['pending_count']}")

   # Clear state (e.g., on unsubscribe)
   processor.clear_state(peer_id, sub_id)

Migration from Raw Hooks
------------------------

If you're using raw ``@callback_hook("subscription")``, migrate to subscription processing:

**Before (manual handling):**

.. code-block:: python

   @app.callback_hook("subscription")
   def handle_subscription(actor, name, req_data):
       peer_id = req_data.get("id")
       sequence = req_data.get("sequence", 0)
       data = req_data.get("data", {})

       # Manual sequencing
       last_seq = get_last_sequence(peer_id)
       if sequence <= last_seq:
           return {"status": "duplicate"}
       if sequence > last_seq + 1:
           store_pending(peer_id, sequence, data)
           return {"status": "pending"}

       # Manual storage
       save_peer_data(peer_id, data)
       update_sequence(peer_id, sequence)

       # Process pending
       process_pending(peer_id)

       return {"status": "ok"}

**After (automatic handling):**

.. code-block:: python

   app = app.with_subscription_processing()

   @app.subscription_data_hook("properties")
   def on_properties(actor, peer_id, target, data, sequence, callback_type):
       # Just handle your business logic!
       # Sequencing, storage, and cleanup are automatic
       notify_user(f"Properties updated from {peer_id}")

Compatibility
-------------

Subscription processing is **fully backward compatible**:

- Existing apps using ``@callback_hook("subscription")`` or
  ``@app.subscription_hook`` continue to work unchanged on the legacy
  fallback path (both fire; either returning truthy marks the callback
  processed)
- New apps can opt-in with ``.with_subscription_processing()`` and
  ``@app.subscription_data_hook``
- All approaches can coexist

Error Handling Reference
------------------------

HTTP Status Codes
~~~~~~~~~~~~~~~~~

When processing subscription callbacks, the library returns these HTTP status codes:

.. list-table::
   :header-rows: 1
   :widths: 15 25 60

   * - Code
     - Status
     - Description
   * - 204
     - No Content
     - Processed, a duplicate of a sequence already applied, or held behind
       a gap (pending)
   * - 503
     - Service Unavailable
     - With ``Retry-After``: another delivery of the sequence is in progress,
       a resync's baseline could not be fetched, or the store faulted. Send
       again later
   * - 400
     - Bad Request
     - Malformed (data without an integer ``sequence``, an unknown type), or
       refused (the pending queue is full, ``max_pending``)
   * - 401
     - Unauthorized
     - No credentials
   * - 403
     - Forbidden
     - Credentials of another peer, or a trust not approved

ProcessResult Enum
~~~~~~~~~~~~~~~~~~

When using ``CallbackProcessor`` directly, ``process_callback()`` (async) and ``process_callback_sync()`` return a ``ProcessResult``:

.. code-block:: python

   from actingweb.callback_processor import ProcessResult

   # The sync form takes a plain (non-async) handler function
   result = processor.process_callback_sync(
       peer_id, sub_id, sequence, data, handler=apply_sync
   )

   if result == ProcessResult.PROCESSED:
       # Normal processing - callback was in sequence
       # Your data hook will be called
       pass

   elif result == ProcessResult.DUPLICATE:
       # Already processed this sequence number
       # Safe to ignore, no action needed
       pass

   elif result == ProcessResult.PENDING:
       # Gap detected - sequence is higher than expected
       # Callback queued, waiting for missing sequences. The delivery
       # that fills the gap processes it, also when that delivery was
       # already running when this one arrived
       pass

   elif result == ProcessResult.RESYNC_TRIGGERED:
       # Gap timeout exceeded (gap_timeout_seconds)
       # The library's handler then syncs from the publisher
       pass

   elif result == ProcessResult.REBUILD:
       # A list diff could not be applied (the handler set out_of_step)
       # and a rebuild is due: call rebuild_subscription()
       pass

   elif result == ProcessResult.IN_PROGRESS:
       # Another delivery of this sequence is still running its handler
       # Do not acknowledge it; the library answers 503 with Retry-After
       pass

   elif result == ProcessResult.REJECTED:
       # max_pending limit reached (back-pressure)
       # Publisher should slow down or retry later
       pass

A handler passed to either method can be called for more than the callback
it was called with: the delivery that is next in line also processes the
callbacks queued behind it, in order and one at a time (always the first;
then at most 20, and none once 5 seconds have passed; the next delivery
takes the rest). A
``REBUILD`` result can therefore come from a queued callback.

Performance Tuning
------------------

Tuning gap_timeout_seconds
~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``gap_timeout_seconds`` parameter controls when a sequence gap triggers a resync:

**Guidelines:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Scenario
     - Value
     - Reasoning
   * - Low-latency networks
     - 2-3s
     - Callbacks arrive quickly; gaps likely indicate lost messages
   * - Standard deployments
     - 5s
     - Default; balances responsiveness and tolerance
   * - High-latency/unreliable
     - 10-15s
     - Allow more time for delayed callbacks to arrive
   * - Batch processing
     - 30-60s
     - Large batches may have temporary gaps during processing

**Trade-offs:**

- **Too short**: Unnecessary resyncs when callbacks are just delayed
- **Too long**: Slow recovery when callbacks are actually lost

Tuning max_pending
~~~~~~~~~~~~~~~~~~

The ``max_pending`` parameter limits how many out-of-order callbacks are queued:

**Guidelines:**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Environment
     - Value
     - Reasoning
   * - Memory-constrained (Lambda)
     - 20-50
     - Limited memory per function invocation
   * - Standard deployments
     - 100
     - Default; handles typical burst scenarios
   * - High-throughput systems
     - 200-500
     - More tolerance for temporary out-of-order delivery

**Memory usage**: Each pending callback uses approximately 1-5KB depending on payload size.

Callback Delivery Tuning
~~~~~~~~~~~~~~~~~~~~~~~~

For publishers with many subscribers:

.. code-block:: python

   app.with_callback_delivery(
       max_concurrent_callbacks=4,             # per write, other hosts
       serialize_own_host_callbacks=True,      # own host one at a time
       callback_delivery_budget_seconds=None,  # set under a gateway's limit
   )

``with_callback_delivery()`` sets these without turning on the processing of
incoming callbacks; ``with_subscription_processing()`` accepts them too.

**Guidelines:**

- ``max_concurrent_callbacks``: a write holds one handler thread and, when
  its subscribers call back into the same deployment through another origin,
  up to this many more. On FastAPI size ``with_thread_pool_workers`` to at
  least the simultaneous writes you expect times one plus the bound.
- Twenty subscribers that all hang cost a write 75 s at the default bound
  (five rounds of the 15 s timeout) where the serial sender took 300 s; the
  budget caps it.

Back-Pressure Handling
----------------------

When the pending queue is full (``max_pending`` exceeded), the library refuses
the callback with 400; a callback whose sequence another delivery is
handling, or whose resync baseline could not be fetched, answers 503 with
``Retry-After``.

Publisher Handling
~~~~~~~~~~~~~~~~~~

The library's sender does not retry a refused or failed callback: the diff is
stored and numbered, so the subscriber recovers by the gap at its next
callback or by polling, and an undelivered resync is sent again on the next
resume. Back-off, a per-peer breaker and payload limits are not implemented
(the specification makes them optional).

Subscriber Mitigation
~~~~~~~~~~~~~~~~~~~~~

If your application frequently hits back-pressure:

1. **Increase max_pending**: Allow more callbacks to queue

   .. code-block:: python

      app.with_subscription_processing(max_pending=200)

2. **Speed up processing**: Keep ``@subscription_data_hook`` handlers fast

   .. code-block:: python

      @app.subscription_data_hook("properties")
      def on_property_change(actor, peer_id, target, data, sequence, callback_type):
          # Do minimal work here
          # Offload heavy processing to background task
          background_queue.enqueue(process_data, peer_id, data)

3. **Request suspension**: Ask publishers to suspend during high-load periods

Database Support
----------------

Subscription processing works with both database backends:

- **DynamoDB**: Subscription state stored in attributes (no migration needed)
- **PostgreSQL**: Subscription state stored in attributes (no migration needed)

Both backends support optimistic locking for concurrent callback handling.

See Also
--------

- :doc:`../protocol/actingweb-spec` - The ActingWeb specification (version
  1.5), the normative rules for subscriptions, diffs and callbacks
- :doc:`trust-relationships` - Trust lifecycle and subscription cleanup
- :doc:`troubleshooting` - Subscription troubleshooting guide
- :doc:`../migration/v3.10` - Migration guide for subscription processing
- :doc:`../contributing/testing` - Testing subscription handlers
