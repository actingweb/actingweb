====================
Subscription Manager
====================

Overview
--------

The ActingWeb subscription system enables real-time data synchronization between actors. Actors can:

- **Subscribe** to updates from peer actors
- **Notify** their subscribers when data changes
- **Process** incoming callbacks with automatic sequencing and deduplication

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

Callback Modes
--------------

By default, subscription callbacks are sent asynchronously (fire-and-forget) to avoid blocking the caller. This works well for traditional server deployments but can cause issues in serverless environments.

**Synchronous Callbacks (Lambda/Serverless)**

In Lambda/serverless environments, async tasks may be lost when the function freezes after returning a response. Enable synchronous callbacks to ensure delivery:

.. code-block:: python

   from actingweb.interface import ActingWebApp

   app = ActingWebApp(...).with_sync_callbacks(enable=True)

This makes **all subscription callbacks** (both diff and resync) use blocking HTTP requests, guaranteeing delivery at the cost of slightly longer response times.

**Why Lambda Requires Sync Callbacks:**

- Lambda freezes execution after returning a response
- Async fire-and-forget callbacks are terminated before completion
- Sync callbacks block until delivery is confirmed
- Both diff callbacks and resync callbacks respect this configuration

**Local Development Warning:**

Do **NOT** use ``with_sync_callbacks()`` in local/container deployments:

- Default async behavior prevents blocking and self-deadlock
- Async mode allows both actors on the same server to communicate without blocking
- Sync mode can cause 30+ second blocking when both actors are on the same server
- Callbacks complete in the background after the response is returned

**When to Use Each Mode:**

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Environment
     - Callback Mode
     - Reason
   * - Traditional Server (Flask/FastAPI)
     - Async (default)
     - Background tasks persist after response
   * - AWS Lambda
     - Sync (``with_sync_callbacks()``)
     - Function freezes after response
   * - Google Cloud Functions
     - Sync (``with_sync_callbacks()``)
     - Function freezes after response
   * - Azure Functions
     - Sync (``with_sync_callbacks()``)
     - Function freezes after response
   * - Kubernetes/Docker
     - Async (default)
     - Background tasks persist after response
   * - Local Development
     - Async (default)
     - Prevents blocking and self-deadlock

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
     - Maximum pending callbacks before back-pressure

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
     "timestamp": "2026-01-20T12:00:00Z"
   }

**Resync Callbacks** (``callback_type="resync"``):

Full state replacement, triggered when:

- A sequence gap exceeds the timeout
- The publisher calls ``resume_subscriptions()``
- Initial sync after subscription creation

Resync callbacks include a ``type`` field and a ``url`` to fetch the full state:

.. code-block:: json

   {
     "id": "actor123",
     "subscriptionid": "sub456",
     "sequence": 43,
     "target": "properties",
     "type": "resync",
     "url": "https://example.com/actor123/properties",
     "timestamp": "2026-01-20T12:00:00Z"
   }

**Low-Granularity Fallback:**

When a peer doesn't support the ``subscriptionresync`` option (per ActingWeb protocol v1.4), the publisher automatically falls back to a low-granularity callback:

.. code-block:: json

   {
     "id": "actor123",
     "subscriptionid": "sub456",
     "sequence": 43,
     "target": "properties",
     "granularity": "low",
     "url": "https://example.com/actor123/subscriptions/sub456/43",
     "timestamp": "2026-01-20T12:00:00Z"
   }

Note: No ``type`` field, and ``url`` points to the subscription diff endpoint. The receiver fetches the data from the URL automatically.

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

   if caps.supports_batch_subscriptions():
       # Peer supports batch subscription creation
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

   # Lists with automatic operations
   store.set_list("items", [{"id": 1}, {"id": 2}])
   items = store.get_list("items")

   # Apply list operations from callbacks
   store.apply_list_operation("items", {
       "operation": "append",
       "items": [{"id": 3}]
   })

   # Storage stats
   stats = store.get_storage_stats()
   print(f"Stored {stats['scalar_count']} scalars, {stats['list_count']} lists")

   # Cleanup
   store.delete_all()  # Remove all data for this peer

List Operations
~~~~~~~~~~~~~~~

The subscription processing system automatically applies list operations from callbacks:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Operation
     - Description
   * - ``append``
     - Add items to end of list
   * - ``extend``
     - Add multiple items to end of list
   * - ``insert``
     - Insert item at specific index
   * - ``update``
     - Update item at specific index
   * - ``delete``
     - Remove item at specific index
   * - ``pop``
     - Remove and return item at index (or last)
   * - ``clear``
     - Remove all items from list
   * - ``remove``
     - Remove first occurrence of item

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

Fan-Out Manager
---------------

For advanced use cases, control callback delivery with circuit breakers:

.. code-block:: python

   from actingweb.fanout import FanOutManager, FanOutResult

   manager = FanOutManager(
       actor=actor,
       max_concurrent=5,      # Parallel deliveries
       default_timeout=30.0,  # Request timeout
   )

   # Deliver to all subscribers
   result: FanOutResult = await manager.deliver(
       target="properties",
       data={"status": "changed"},
   )

   print(f"Delivered to {result.success_count}/{result.total_count}")
   for failure in result.failures:
       print(f"Failed: {failure.peer_id} - {failure.error}")

   # Check circuit breaker status
   status = manager.get_circuit_breaker_status("peer123")
   if status == "OPEN":
       print("Peer is unavailable, requests will be skipped")

   # Reset circuit breaker
   manager.reset_circuit_breaker("peer123")

Advanced: Component-Level Usage
-------------------------------

For fine-grained control, use components directly:

.. code-block:: python

   from actingweb.callback_processor import (
       CallbackProcessor, ProcessResult, CallbackType
   )
   from actingweb.remote_storage import RemotePeerStore
   from actingweb.peer_capabilities import PeerCapabilities

   # Create processor
   processor = CallbackProcessor(
       actor=actor,
       gap_timeout_seconds=10.0,
       max_pending=200,
   )

   # Process a callback manually
   async def handle_callback(peer_id, data, sequence):
       result = await processor.process_callback(
           peer_id=peer_id,
           subscription_id=sub_id,
           sequence=sequence,
           data=data,
       )

       if result == ProcessResult.PROCESSED:
           # Normal processing
           store = RemotePeerStore(actor, peer_id)
           store.apply_callback_data(target="properties", data=data)
       elif result == ProcessResult.DUPLICATE:
           # Skip - already processed
           pass
       elif result == ProcessResult.PENDING:
           # Gap detected, waiting for missing callbacks
           pass
       elif result == ProcessResult.RESYNC_REQUIRED:
           # Gap timeout exceeded, fetch full state
           pass

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
   def handle_subscription(actor, req):
       peer_id = req.json.get("id")
       sequence = req.json.get("sequence", 0)
       data = req.json.get("data", {})

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

- Existing apps using ``@callback_hook("subscription")`` continue to work unchanged
- New apps can opt-in with ``.with_subscription_processing()``
- Both approaches can coexist (raw hook takes precedence if registered)

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
   * - 201
     - Created
     - Callback processed successfully
   * - 200
     - OK
     - Duplicate callback (already processed this sequence)
   * - 202
     - Accepted
     - Callback queued as pending (gap detected, waiting for missing sequences)
   * - 429
     - Too Many Requests
     - Back-pressure: pending queue full (``max_pending`` exceeded)
   * - 401
     - Unauthorized
     - Invalid or missing trust token
   * - 403
     - Forbidden
     - Trust relationship not approved or deleted
   * - 400
     - Bad Request
     - Malformed callback payload

ProcessResult Enum
~~~~~~~~~~~~~~~~~~

When using ``CallbackProcessor`` directly, the ``process_callback()`` method returns a ``ProcessResult``:

.. code-block:: python

   from actingweb.callback_processor import ProcessResult

   result = processor.process_callback(peer_id, sub_id, sequence, data)

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
       # Callback queued, waiting for missing sequences
       # Will auto-process when gap is filled
       pass

   elif result == ProcessResult.RESYNC_REQUIRED:
       # Gap timeout exceeded (gap_timeout_seconds)
       # Library will request full resync from peer
       pass

   elif result == ProcessResult.BACK_PRESSURE:
       # max_pending limit reached
       # Publisher should slow down or retry later
       pass

Circuit Breaker States
~~~~~~~~~~~~~~~~~~~~~~

The ``FanOutManager`` uses circuit breakers to protect against failing peers:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - State
     - Behavior
   * - ``CLOSED``
     - Normal operation - requests are sent to the peer
   * - ``OPEN``
     - Peer is unavailable - requests are skipped (fast-fail)
   * - ``HALF_OPEN``
     - Testing recovery - one request allowed to check peer status

**Circuit breaker triggers:**

- Opens after consecutive failures (default: 5)
- Stays open for a cooldown period (default: 60 seconds)
- Transitions to HALF_OPEN after cooldown
- Closes again on successful delivery

.. code-block:: python

   from actingweb.fanout import FanOutManager

   manager = FanOutManager(actor)

   # Check status
   status = manager.get_circuit_breaker_status(peer_id)
   print(f"Circuit breaker for {peer_id}: {status}")

   # Manual reset (e.g., after fixing connectivity)
   if status == "OPEN":
       manager.reset_circuit_breaker(peer_id)

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

FanOutManager Tuning
~~~~~~~~~~~~~~~~~~~~

For publishers with many subscribers:

.. code-block:: python

   from actingweb.fanout import FanOutManager

   manager = FanOutManager(
       actor=actor,
       max_concurrent=10,     # Parallel deliveries (default: 5)
       default_timeout=45.0,  # Per-request timeout (default: 30s)
       failure_threshold=3,   # Opens circuit after N failures (default: 5)
       recovery_timeout=30.0, # Cooldown before testing (default: 60s)
   )

**Guidelines:**

- ``max_concurrent``: Increase for many subscribers, decrease if overloading infrastructure
- ``default_timeout``: Increase for slow peers, decrease for fast-fail behavior
- ``failure_threshold``: Lower for quick circuit breaker activation
- ``recovery_timeout``: Lower for faster retry attempts

Back-Pressure Handling
----------------------

When the pending queue is full (``max_pending`` exceeded), the library returns HTTP 429.

Publisher Handling
~~~~~~~~~~~~~~~~~~

Publishers should implement retry logic when receiving 429:

.. code-block:: python

   import time
   import httpx

   def send_callback_with_retry(url, data, auth, max_retries=3):
       """Send callback with exponential backoff on 429."""
       for attempt in range(max_retries):
           response = httpx.post(url, json=data, auth=auth)

           if response.status_code == 429:
               # Back-pressure - subscriber is overloaded
               wait_time = (2 ** attempt) + random.uniform(0, 1)
               print(f"Back-pressure from subscriber, waiting {wait_time:.1f}s")
               time.sleep(wait_time)
               continue

           return response

       raise Exception("Max retries exceeded due to back-pressure")

FanOutManager Automatic Handling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``FanOutManager`` handles 429 responses automatically:

1. Marks the delivery as failed (not retried immediately)
2. Increments the circuit breaker failure count
3. Includes the peer in ``result.failures``

.. code-block:: python

   result = await manager.deliver(target="properties", data={"status": "active"})

   for failure in result.failures:
       if failure.status_code == 429:
           print(f"Peer {failure.peer_id} is overloaded")
           # Consider: reduce publishing rate or alert

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

- :doc:`trust-relationships` - Trust lifecycle and subscription cleanup
- :doc:`troubleshooting` - Subscription troubleshooting guide
- :doc:`../migration/v3.10` - Migration guide for subscription processing
- :doc:`../contributing/testing` - Testing subscription handlers
