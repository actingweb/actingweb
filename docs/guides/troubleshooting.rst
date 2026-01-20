===============
Troubleshooting
===============

Common issues and fixes when developing with ActingWeb.

401 at /mcp
-----------

- Cause: No authentication configured or provided. MCP is OAuth2-protected in production.
- Fix: Configure OAuth2 (Google/GitHub) with `.with_oauth(...)`. Unauthenticated requests should return 401 with `WWW-Authenticate` header. For local, temporarily allow open access or sign in via `/www`.

DynamoDB Local connection errors
--------------------------------

- Symptom: Timeouts or table not found.
- Fix: Ensure DynamoDB Local is running and set env vars:

  .. code-block:: bash

     export AWS_ACCESS_KEY_ID=local
     export AWS_SECRET_ACCESS_KEY=local
     export AWS_DEFAULT_REGION=us-east-1
     export AWS_DB_HOST=http://localhost:8000

Slow first request after startup
--------------------------------

- Explanation: The permission system compiles/caches trust types on first use.
- Fix: This is initialized automatically during framework integration. If you still see warmups during requests, check logs for initialization errors.

Tools/prompts don’t appear in tools/list or prompts/list
--------------------------------------------------------

- Check that you decorated hooks correctly:
  - Tools: `@app.action_hook("name")` + `@mcp_tool(...)`
  - Prompts: `@app.method_hook("name")` + `@mcp_prompt(...)`
- Verify unified access control isn’t filtering them out for the current peer.

Property changes not visible in Web UI
--------------------------------------

- Hook returns `None` for GET hides the property completely.
- Hook returns `None` for PUT/POST marks the property read-only.

Subscription Callbacks Not Delivered
------------------------------------

- **Symptom**: Property changes on the publisher are not reaching subscribers.
- **Causes and fixes**:

  1. **Circuit breaker is open**: Check the circuit breaker status for the peer:

     .. code-block:: python

        from actingweb.fanout import FanOutManager
        manager = FanOutManager(actor)
        status = manager.get_circuit_breaker_status(peer_id)
        if status == "OPEN":
            # Peer is unavailable, reset if issue resolved
            manager.reset_circuit_breaker(peer_id)

  2. **Peer URL unreachable**: Verify the peer's callback URL is accessible and responding.
  3. **Trust not approved**: Ensure the trust relationship is approved on both sides.
  4. **Subscription target mismatch**: Verify the subscription target matches what you're publishing.

Unexpected Resync Callbacks
---------------------------

- **Symptom**: Full resync callbacks triggered frequently instead of incremental diffs.
- **Causes and fixes**:

  1. **Network latency**: If callbacks arrive out-of-order often, increase the gap timeout:

     .. code-block:: python

        app.with_subscription_processing(gap_timeout_seconds=10.0)  # Default is 5.0

  2. **Burst updates**: Rapid property changes can cause sequence gaps. Consider using suspension:

     .. code-block:: python

        actor.subscriptions.suspend(target="properties")
        # ... perform bulk updates ...
        actor.subscriptions.resume(target="properties")  # Sends single resync

  3. **Publisher restart**: After a publisher restarts, sequence numbers reset. Subscribers should handle resync gracefully.

Duplicate Callbacks Being Processed
-----------------------------------

- **Symptom**: Same data processed multiple times in your ``@subscription_data_hook``.
- **Causes and fixes**:

  1. **auto_sequence disabled**: Ensure subscription processing is enabled:

     .. code-block:: python

        app.with_subscription_processing(auto_sequence=True)  # Default

  2. **Using raw callback_hook**: The raw ``@callback_hook("subscription")`` doesn't deduplicate. Migrate to ``@subscription_data_hook``.
  3. **Multiple hook registrations**: Check you haven't registered the same hook twice.

Peer Data Not Cleaned Up After Trust Deletion
---------------------------------------------

- **Symptom**: RemotePeerStore data persists after trust relationship is deleted.
- **Causes and fixes**:

  1. **auto_cleanup disabled**: Enable automatic cleanup:

     .. code-block:: python

        app.with_subscription_processing(auto_cleanup=True)  # Default

  2. **Custom trust hook overriding**: If you have a ``@trust_hook("delete")``, ensure it doesn't prevent default cleanup.
  3. **Manual cleanup needed**: For legacy data, manually clean up:

     .. code-block:: python

        from actingweb.remote_storage import RemotePeerStore
        store = RemotePeerStore(actor, peer_id)
        store.delete_all()

Subscriber Returning 429 (Too Many Requests)
--------------------------------------------

- **Symptom**: Publisher receives 429 responses when sending callbacks.
- **Causes and fixes**:

  1. **Pending queue full**: The subscriber's ``max_pending`` limit was exceeded:

     .. code-block:: python

        # On subscriber, increase if needed:
        app.with_subscription_processing(max_pending=200)  # Default is 100

  2. **Processing too slow**: The subscriber's hook is blocking. Keep hooks fast or offload work.
  3. **Publisher retry strategy**: Implement exponential backoff when receiving 429:

     .. code-block:: python

        # FanOutManager handles retries automatically
        # For custom implementations, wait before retrying

Sequence Gaps Not Resolving
---------------------------

- **Symptom**: Callbacks stuck in pending queue, never processed.
- **Causes and fixes**:

  1. **Gap timeout too long**: Reduce the timeout to trigger resync sooner:

     .. code-block:: python

        app.with_subscription_processing(gap_timeout_seconds=3.0)

  2. **Missing callbacks**: The publisher may have lost callbacks. Manually trigger resync:

     .. code-block:: python

        # On publisher side:
        actor.subscriptions.resume(target="properties")

  3. **Check pending state**: Use devtest endpoints to inspect pending queue (devtest mode only):

     .. code-block:: bash

        GET /{actor_id}/devtest/callback_state/{peer_id}/{subscription_id}
