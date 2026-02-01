=================
Async Operations
=================

**Audience**: SDK developers working with async frameworks or peer-to-peer communication.

ActingWeb provides async variants of methods that communicate with remote peers. This enables non-blocking peer operations in async frameworks like FastAPI.

Overview
========

Peer communication involves HTTP requests to other actors. In synchronous code, these block the thread. Async variants allow concurrent execution without blocking.

Async Methods
=============

Actor Class Async Methods
-------------------------

The core ``Actor`` class provides these async methods:

.. code-block:: python

    class Actor:
        # Peer information
        async def get_peer_info_async(self, peer_id: str) -> Optional[Dict]

        # Trust operations
        async def modify_trust_and_notify_async(
            self, peer_id: str, relationship: str, ...
        ) -> bool

        async def create_reciprocal_trust_async(
            self, peer_id: str, relationship: str, baseuri: str, ...
        ) -> Optional[Dict]

        async def create_verified_trust_async(
            self, peer_id: str, relationship: str, baseuri: str, verify_token: str, ...
        ) -> Optional[Dict]

        async def delete_reciprocal_trust_async(
            self, peer_id: str, ...
        ) -> bool

        # Subscription operations
        async def create_remote_subscription_async(
            self, peer_id: str, baseuri: str, callback_path: str, ...
        ) -> Optional[Dict]

        async def delete_remote_subscription_async(
            self, peer_id: str, ...
        ) -> bool

        async def callback_subscription_async(
            self, peer_id: str, diff_data: Dict, ...
        ) -> bool

TrustManager Async Methods
--------------------------

The ``TrustManager`` wraps these for easier use:

.. code-block:: python

    class TrustManager:
        async def create_reciprocal_trust_async(
            self, peer_id: str, relationship: str, baseuri: str
        ) -> Optional[TrustRelationship]

        async def create_verified_trust_async(
            self, peer_id: str, relationship: str, baseuri: str, verify_token: str
        ) -> Optional[TrustRelationship]

        async def modify_and_notify_async(
            self, peer_id: str, relationship: str
        ) -> bool

        async def delete_peer_trust_async(
            self, peer_id: str
        ) -> bool

SubscriptionManager Async Methods
---------------------------------

.. code-block:: python

    class SubscriptionManager:
        async def subscribe_to_peer_async(
            self,
            peer_id: str,
            target: str,
            subtarget: str = "",
            resource: str = "",
            granularity: str = "high"
        ) -> Optional[str]  # Returns subscription URL

        async def unsubscribe(
            self, peer_id: str, subscription_id: str
        ) -> bool

AwProxy Async Methods
---------------------

For direct HTTP communication with peers:

.. code-block:: python

    class AwProxy:
        async def get_resource_async(
            self, path: str, params: Dict = None
        ) -> Optional[Dict]

        async def create_resource_async(
            self, path: str, data: Dict
        ) -> Optional[Dict]

        async def change_resource_async(
            self, path: str, data: Dict
        ) -> Optional[Dict]

        async def delete_resource_async(
            self, path: str
        ) -> bool

Usage Examples
==============

FastAPI Route with Async Trust Creation
---------------------------------------

.. code-block:: python

    from fastapi import FastAPI, HTTPException
    from actingweb.interface import ActorInterface

    app = FastAPI()

    @app.post("/{actor_id}/connect")
    async def connect_to_peer(actor_id: str, peer_baseuri: str):
        actor = get_actor(actor_id)
        actor_interface = ActorInterface(actor)

        # Non-blocking peer communication
        trust = await actor_interface.trust.create_verified_trust_async(
            peer_id="new_peer",
            relationship="friend",
            baseuri=peer_baseuri,
            verify_token=generate_token()
        )

        if not trust:
            raise HTTPException(status_code=400, detail="Failed to establish trust")

        return {"trust_id": trust.peer_id, "status": "connected"}

Concurrent Peer Operations
--------------------------

.. code-block:: python

    import asyncio

    async def notify_all_peers(actor: ActorInterface, message: Dict):
        """Notify all trusted peers concurrently."""

        peers = actor.trust.get_all_relationships()

        async def notify_peer(peer):
            proxy = AwProxy(
                peer_target={"id": actor.id, "peerid": peer["peerid"]},
                config=actor.config
            )
            return await proxy.create_resource_async(
                path="callbacks/notification",
                data=message
            )

        # Execute all notifications concurrently
        results = await asyncio.gather(
            *[notify_peer(p) for p in peers],
            return_exceptions=True
        )

        return results

Async Subscription with Callback
--------------------------------

.. code-block:: python

    async def subscribe_to_service(actor: ActorInterface, service_uri: str):
        """Subscribe to a remote service."""

        # Create trust first
        trust = await actor.trust.create_reciprocal_trust_async(
            peer_id="service",
            relationship="service",
            baseuri=service_uri
        )

        if not trust:
            raise RuntimeError("Failed to establish trust")

        # Then subscribe (includes automatic baseline sync)
        subscription_url = await actor.subscriptions.subscribe_to_peer_async(
            peer_id="service",
            target="properties",
            granularity="high"
        )

        return subscription_url

Implementation Details
======================

Async via httpx
---------------

Async methods use ``httpx`` for non-blocking HTTP:

.. code-block:: python

    async def get_resource_async(self, path: str) -> Optional[Dict]:
        import httpx

        url = f"{self.peer_baseuri}/{path}"
        headers = self._build_auth_headers()

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)

        if response.status_code == 200:
            return response.json()
        return None

Async via asyncio.to_thread
---------------------------

Some methods wrap synchronous code with ``asyncio.to_thread``:

.. code-block:: python

    async def create_verified_trust_async(self, ...):
        # Runs sync method in thread pool
        return await asyncio.to_thread(
            self.create_verified_trust,
            peer_id, relationship, baseuri, verify_token, ...
        )

Timeout Handling
----------------

Async operations include configurable timeouts:

.. code-block:: python

    async def get_peer_info_async(self, peer_id: str, timeout: float = 30.0):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers)
                return response.json()
        except httpx.TimeoutException:
            logger.warning(f"Timeout getting info for peer {peer_id}")
            return None

Best Practices
==============

1. **Use Async for External Communication**

   .. code-block:: python

       # Good - non-blocking
       trust = await actor.trust.create_reciprocal_trust_async(...)

       # Avoid in async context - blocks event loop
       trust = actor.trust.create_reciprocal_trust(...)

2. **Use asyncio.gather for Concurrent Operations**

   .. code-block:: python

       # Notify multiple peers concurrently
       results = await asyncio.gather(
           notify_peer(peer1),
           notify_peer(peer2),
           notify_peer(peer3),
           return_exceptions=True
       )

3. **Handle Timeouts Gracefully**

   .. code-block:: python

       try:
           result = await asyncio.wait_for(
               actor.trust.create_verified_trust_async(...),
               timeout=60.0
           )
       except asyncio.TimeoutError:
           logger.error("Trust creation timed out")
           return None

4. **Don't Mix Sync and Async Carelessly**

   .. code-block:: python

       # In async function - use async variant
       async def handler():
           trust = await actor.trust.create_reciprocal_trust_async(...)

       # In sync function - use sync variant
       def handler():
           trust = actor.trust.create_reciprocal_trust(...)

5. **Consider Connection Pooling**

   .. code-block:: python

       # Reuse client for multiple requests
       async with httpx.AsyncClient() as client:
           result1 = await client.get(url1)
           result2 = await client.get(url2)

Performance Considerations
==========================

Sync vs Async Comparison
------------------------

+----------------------+-------------------+-------------------+
| Operation            | Sync (blocking)   | Async (concurrent)|
+======================+===================+===================+
| Single peer request  | ~100ms            | ~100ms            |
+----------------------+-------------------+-------------------+
| 10 peer requests     | ~1000ms (serial)  | ~100ms (parallel) |
+----------------------+-------------------+-------------------+
| Mixed local + remote | Blocks on remote  | Overlapped        |
+----------------------+-------------------+-------------------+

When to Use Async
-----------------

- FastAPI/Starlette routes
- Multiple peer operations
- Long-running peer communication
- High-concurrency scenarios

When Sync is OK
---------------

- Flask routes (WSGI is sync anyway)
- Single peer operation
- Background tasks with dedicated threads
- Simple scripts and CLI tools

See Also
========

- :doc:`developer-api` - Developer API reference
- :doc:`handler-architecture` - Handler internals
- :doc:`custom-framework` - Framework integration
