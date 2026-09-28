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

MCP client sees an empty tool list or ``-32003`` after upgrading
------------------------------------------------------------------

- **Symptom**: An MCP client that worked before an upgrade now sees an empty
  ``tools/list``/``resources/list``/``prompts/list``, or gets ``-32003``
  ("Access denied") on ``tools/call``/``prompts/get``/``resources/read``.
- **Cause**: As of ``v3.13.0rc3``, a valid MCP access token that cannot be
  resolved to a trust relationship is fail-closed (no access) instead of
  fail-open (full access) — see the ``SECURITY`` section of
  ``CHANGELOG.rst``. The server log has a ``WARNING`` naming the actor id
  and client id ("no trust found for MCP client ... requests will be
  denied") — but it is logged only when the trust *resolver* actually runs
  (a cache miss), not on every denied request. A negative result is cached
  for a short window (a few seconds), so if a client keeps retrying you'll
  see the WARNING recur roughly that often rather than on every single
  request — check the logs over a short window, not just the exact moment
  you reproduce the symptom.
- **Fix**: Work through the pre-upgrade checklist in
  ``docs/migration/v3.13.rst`` ("Security: MCP trust-cache authorization
  bypass") — it covers finding
  at-risk trust rows, auditing Flask resource URIs against your trust
  type's allowed patterns, and what happens to per-peer permission
  overrides when a client re-authorizes. In most cases the client simply
  needs to complete OAuth2 authorization again (not just retry the
  request) so its trust row is recreated with the ``oauth_client_id`` the
  new resolver requires.

MCP tool's structured data disappeared after upgrading
--------------------------------------------------------

- **Symptom**: After upgrading to ``v3.13.0rc4`` or newer, a tool that used to
  deliver structured fields to the model now delivers only its text, and
  ``structuredContent`` is absent from the ``tools/call`` response.
- **Cause**: ``structuredContent`` is now opt-in. Extra top-level keys returned
  alongside ``content`` used to be promoted into ``structuredContent``
  automatically; that promotion was removed because clients that discard text
  blocks when ``structuredContent`` is present were silently dropping the tool's
  entire prose payload. Dropped extras are **not** logged — they are a
  deliberate migration, not an error.
- **Fix**: Nest the data under an explicit ``structuredContent`` key, and keep
  the same object serialized in a text ``content`` block so clients that ignore
  ``structuredContent`` still receive it. See "MCP: ``structuredContent`` is
  now opt-in" in
  ``docs/migration/v3.13.rst``. If the tool's real payload is prose, returning
  prose alone is now the correct shape.
- **Note when verifying with ``curl``**: a request with no
  ``MCP-Protocol-Version`` header negotiates ``2025-03-26``, which suppresses
  ``structuredContent`` *even when set explicitly*. Send
  ``-H 'MCP-Protocol-Version: 2025-06-18'`` or you will misread a working hook
  as broken.

MCP client rejects a tool with "has an output schema but did not return structured content"
---------------------------------------------------------------------------------------------

- **Symptom**: A spec-conforming client (Claude Code, the reference Python
  client) errors on every call to one tool with ``Tool X has an output schema
  but did not return structured content``. The server log carries a matching
  ``WARNING`` naming the tool.
- **Cause**: The tool declares ``output_schema`` on ``@mcp_tool`` — so
  ``outputSchema`` is advertised in ``tools/list`` — but its hook returns no
  ``structuredContent``. Declaring a schema does **not** cause structured output
  to be emitted; the two are independent. Once a schema is advertised, clients
  treat structured output as mandatory on every non-error result.
- **Fix**: Either return an explicit ``structuredContent`` conforming to the
  declared schema, or remove ``output_schema`` from the decorator. The warning
  is logged once per tool per process, so check the log from around process
  start rather than only the moment you reproduce it.

MCP connector asks to log in again about an hour after connecting
------------------------------------------------------------------

- **Symptom**: From 3.15, an MCP client connects, works for about an hour,
  then its refresh fails with ``invalid_grant`` and the user must sign in
  again. The server logs a WARNING "Refresh token ... reused ... potential
  theft".
- **Cause**: MCP refresh tokens are single-use since 3.15. Every refresh
  returns a new ``refresh_token``. A client that keeps presenting its first
  one gets one refresh, and the replay an hour later is treated as token
  theft: the whole chain is revoked.
- **Fix**: The client must store the ``refresh_token`` from every token
  response. A replay within the grace period (60 seconds by default, set
  with ``with_refresh_token_grace()``) is tolerated (a retry or lost
  response), so the problem is a client that never persists the new token.
  See :doc:`../migration/v3.15`.

Native or mobile client asks to log in again after the device slept
-------------------------------------------------------------------

- **Symptom**: A desktop or mobile client (SPA endpoint or MCP) is signed
  out after the device wakes, at irregular intervals. The server logs a
  WARNING "Refresh token reuse detected ... potential token theft" (SPA) or
  "Refresh token ... reused ... potential theft" (MCP) minutes after the
  token was first used.
- **Cause**: The client sent a refresh, the device slept or the app was
  suspended before the response arrived, and after waking the client
  presented the consumed token again. Past the grace period that is read as
  theft and the rotation family is revoked. A client that received the new
  tokens, failed to store the new refresh token and fell back to the old
  one shows the same symptom.
- **Fix**: In the client: refresh only while the app is active and not from
  a timer, keep the process that owns the connection running while a
  refresh is in flight, give the request a short timeout and retry once at
  once while awake, and never fall back to a consumed refresh token when
  storing the new one fails. See :ref:`spa-refresh-reliably`. Raising the
  grace period is not the fix: it is capped at 60 seconds, well short of a
  sleep. The 3.15 change that reads an SPA refresh token past its own
  expiry as expired rather than theft is a separate fix; it does not
  address this symptom.

SPA client signed out during a database throttle
------------------------------------------------

- **Symptom**: Before 3.15, an SPA or native client was signed out when the
  token store was briefly unavailable (a DynamoDB throttle, a database
  failover); the refresh answered 401 "Invalid or expired refresh_token"
  and the server logged "Could not consume refresh token".
- **Cause**: The SPA refresh grant answered a store fault as if the token
  were unknown, and a client that treats a 401 as final signed out.
- **Fix**: From 3.15 the grant answers **503** with ``Retry-After`` and the
  body "Token store temporarily unavailable; retry", as the MCP grant does.
  The client keeps its token and retries after ``Retry-After`` seconds; see
  rule 7 in :ref:`spa-refresh-reliably`.

Public MCP client (such as Codex) fails every refresh with ``invalid_client``
-----------------------------------------------------------------------------

- **Cause**: The connector was registered before 3.15, when registration
  ignored ``token_endpoint_auth_method: none`` and stored every client as
  confidential. The client never sends the secret it was issued.
- **Fix**: Remove the connector and add it again; it registers as a public
  client. Signing in again is not enough when the client reuses its
  registration. Clients that send their issued secret (ChatGPT, claude.ai,
  Claude Code) are not affected.

ChatGPT asks the user to reconnect although its refresh token is valid
----------------------------------------------------------------------

- **Symptom**: After an access token was invalidated on the server (rows
  deleted from the token store, a store cleared, an application guard
  answering 401), ChatGPT shows "your connection has expired, reconnect"
  and the log has no ``refresh_token`` grant from it.
- **Cause**: ChatGPT refreshes only on its own expiry clock, from the
  ``expires_in`` it was given. A 401 from ``/mcp`` does not make it try its
  refresh token; it re-reads the server metadata, re-initialises, and on a
  second 401 asks the user to sign in again. Claude Code and claude.ai
  refresh in that case. Seen with the chatgpt.com connector on 3.15.0rc1.
- **Fix**: None on the server beyond not answering 401 to a token that is
  still meant to be valid. The reconnect reuses the connector's
  registration, so it is one sign-in, not a new connector. Refreshing on
  expiry works: ChatGPT stores each rotated refresh token.

``/mcp`` answers 503 with ``Retry-After``
-----------------------------------------

- **Cause**: The MCP token store could not be read (a DynamoDB throttle, a
  lost database connection). Since 3.15 this is not reported as an invalid
  token. Tokens already in the process cache keep working.
- **Fix**: Check the database; the client retries on its own.

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

  2. **Custom lifecycle hook overriding**: If you have a ``@app.lifecycle_hook("trust_deleted")``, ensure it doesn't prevent default cleanup.
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
