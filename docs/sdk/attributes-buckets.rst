===============================
Attributes and Buckets (Global)
===============================

Overview
--------

The attribute/bucket system provides flexible JSON storage for application-level or cross-actor data.
It supports configurations, registries, indexes, and any data that doesn't fit the property model.

**Key Characteristics:**

- JSON-serializable data stored per actor per bucket
- Each attribute has a name, data payload, and optional timestamp
- Global storage via system actors (``_actingweb_system``, ``_actingweb_oauth2``)
- Efficient querying by bucket with composite range keys

Basic Usage
-----------

.. code-block:: python

   from actingweb import attribute

   # Per-actor bucket
   prefs = attribute.Attributes(actor_id=actor.id, bucket="user_preferences", config=config)
   prefs.set_attr(name="theme", data="dark")
   theme_attr = prefs.get_attr(name="theme")
   # Returns: {"data": "dark", "timestamp": <datetime>}

   # Delete single attribute
   prefs.delete_attr(name="theme")

   # Delete entire bucket
   prefs.delete_bucket()

Global Storage
--------------

.. code-block:: python

   # Global settings using system actor
   from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR

   global_config = attribute.Attributes(
       actor_id=ACTINGWEB_SYSTEM_ACTOR,
       bucket="app_settings",
       config=config
   )
   global_config.set_attr(name="maintenance_mode", data=False)

``actor.store`` and a failed read
---------------------------------

``Attributes.get_bucket()`` and ``get_attr()`` raise ``DbError`` when the
backend cannot answer. ``actor.store`` (the actor's ``_internal`` bucket) is
the one wrapper that does not: ``actor.store.<name>`` reads ``None`` for a
name that is not set *and* for a bucket that could not be read, and
``actor.store.loaded`` is ``False`` in the second case. Check ``loaded``
before acting on an absent value; the hooks reference shows the pattern under
``actor_deleted``.

Atomic Operations (v3.8.2+)
---------------------------

For concurrent access scenarios, use ``conditional_update_attr()`` to perform atomic
compare-and-swap operations. This is essential for race-free updates when multiple
requests might modify the same attribute simultaneously.

.. code-block:: python

   from actingweb import attribute

   # Example: Atomic token rotation
   tokens = attribute.Attributes(
       actor_id=OAUTH2_SYSTEM_ACTOR,
       bucket="spa_refresh_tokens",
       config=config
   )

   # Get current token data
   token_attr = tokens.get_attr(name=refresh_token)
   if not token_attr:
       return False

   old_data = token_attr["data"]

   # Only update if token hasn't been marked as used
   if old_data.get("used"):
       return False  # Already used by another request

   # Prepare new data with used flag
   new_data = old_data.copy()
   new_data["used"] = True
   new_data["used_at"] = int(time.time())

   # Atomic update - only succeeds if current data still matches old_data
   success = tokens.conditional_update_attr(
       name=refresh_token,
       old_data=old_data,
       new_data=new_data
   )

   if success:
       # This request won the race - token is now marked as used
       return True
   else:
       # Another request modified the token first
       return False

**How It Works:**

- **PostgreSQL**: Uses ``UPDATE ... WHERE data = old_data`` for atomic compare-and-swap
- **DynamoDB**: Uses conditional update expressions with ``condition=(Attribute.data == old_data)``
- Returns ``True`` only if the current database value exactly matches ``old_data``
- Returns ``False`` if value was modified by another request (no update performed).
- **By default it also returns** ``False`` **if the backend faulted.** Pass
  ``strict=True`` (v4.0+) to have a fault raise ``DbError`` instead, chained to the
  backend's exception (so a fault a retry cannot fix classifies as permanent). A
  value JSON cannot order or encode raises ``TypeError`` or ``ValueError`` before
  the store is touched.
  ``False`` then means the condition did not hold: the row holds something other
  than ``old_data``, or there is no row. Unlike the reads, whose ``strict`` defaults
  to ``True``, the default here is ``False``: an existing caller keeps the answer it
  had. (``create_attr_if_absent`` below always raises ``DbError`` on a fault.)
- **Neither a** ``DbError`` **nor a** ``False`` **proves the write did not land.** A
  write whose answer was lost can be retried by the database client, and the retry
  then meets its own ``new_data`` and fails the condition. A caller that must know
  puts a value unique to the call in ``new_data`` (a nonce) and reads the row with
  ``get_attr_strict`` before it writes again:

.. code-block:: python

   import secrets

   from actingweb.db.exceptions import DbError

   claim = {"owner": worker_id, "claim_id": secrets.token_hex(8)}
   try:
       won = jobs.conditional_update_attr(
           name=job_id, old_data=unclaimed, new_data=claim, strict=True
       )
   except DbError:
       raise  # an outage: the integration answers 503
   if not won:
       row = jobs.dbprop.get_attr_strict(
           actor_id=jobs.actor_id, bucket=jobs.bucket, name=job_id
       )
       won = bool(row) and row["data"].get("claim_id") == claim["claim_id"]

**Use Cases:**

- OAuth refresh token rotation (prevents concurrent reuse)
- Distributed counters and rate limiting
- Session management with concurrent requests
- Any scenario requiring optimistic locking

Create if absent (v4.0+)
-------------------------

``create_attr_if_absent()`` creates an attribute only if no live row holds its name,
in one conditional write. It is the primitive for a once-only claim (an unlock request,
an idempotency key) where a read-then-write would let two requests both win.

.. code-block:: python

   import uuid
   from actingweb import attribute

   asks = attribute.Attributes(actor_id=actor_id, bucket="unlock_asks", config=config)

   # A per-call nonce makes exactly one caller the winner (see below).
   request_id = uuid.uuid4().hex
   if asks.create_attr_if_absent(
       name=f"unlock:{user_id}",
       data={"request_id": request_id},
       ttl_seconds=600,
   ):
       send_the_unlock_mail(user_id)      # this request owns the ask
   else:
       pass                               # a live ask exists; read it with get_attr

**The rules:**

- ``True`` means this call created the row or replaced an **expired** one (a row whose
  stored ``ttl_timestamp`` is in the past, the rule ``get_attr_strict`` applies; use
  ``get_attr_strict`` to read the row back under the same rule, because ``get_attr``
  returns expired rows).
- ``False`` means a live row holds the name, or another bucket owns the key. The row is
  untouched, and a later ``get_attr(name)`` on the same ``Attributes`` reads the
  winner's row through.
- A lost condition whose stored row is **JSON-equal** to the data this call wrote is
  ``True``: a create that landed, then was retried by the SDK, must not read as lost.
  The consequence: two callers writing identical ``data`` both get ``True``. A caller
  that needs exactly one winner puts a per-call nonce in ``data``, as above.
- **When a name frees up.** The stored ``ttl_timestamp`` is ``ttl_seconds`` plus
  ``TTL_CLOCK_SKEW_BUFFER`` (one hour) from the write, as for every attribute with a
  TTL, so the purge never removes a row early. A row written with ``ttl_seconds=600``
  therefore holds its name for 70 minutes, and ``get_attr_strict`` reports it live for
  that span. When the application's own expiry is shorter, keep the deadline in
  ``data`` (``{"request_id": ..., "expires_at": ...}``). Once it has passed, take the
  name over with ``conditional_update_attr(name, old_data=<the data you read>,
  new_data=<the new ask>, ttl_seconds=...)``: a compare-and-swap, so only one caller
  replaces a given stale ask.
- A fault raises ``DbError`` (the integrations answer 503). A missing ``name`` raises
  ``ValueError``.
- Do not use it on names an untrusted party chooses, in a bucket where an expired row
  still carries meaning (a consumed marker kept for ``consumed_ttl``): it replaces an
  expired row.

Writes are bound to their bucket (v4.0+)
-----------------------------------------

Both backends key an attribute as ``<bucket>:<name>``, so bucket ``a`` with name
``b:c`` and bucket ``a:b`` with name ``c`` share one key (a peer id in
``remote:<peer_id>`` may contain ``:``). Every attribute write, ``set_attr``
included, is conditioned on its bucket: a write to a key another bucket holds
raises ``AttributeKeyCollision`` (``actingweb.db.exceptions``, a ``DbError``) and
never replaces the other bucket's row. It is not an availability fault: a retry meets
the same row. The subscription replica refuses such a key and logs it (``another
bucket holds the key``).

Attribute lists (v4.0+)
------------------------

``actor.attribute_lists(bucket)`` returns an ``AttributeListStore`` for one bucket.
Its lists (``.get(name)`` or attribute access) are ``ListAttribute`` instances with
the ``ListProperty`` interface: private to the actor, never served or diffed. See
:doc:`../guides/property-lists` ("Attribute Lists") for the interface and when to use
one.

.. code-block:: python

   queue = actor.attribute_lists("jobs").get("pending")
   queue.append({"job": "reindex"})
   first = queue.pop(0)

**Layout.** A list is ``list:<name>-meta`` plus one ``list:<name>-#<rank>`` row per
item in its bucket, the property list format (``actingweb.list_core.ListCore`` over a
``ListStorage``). A side bucket, ``<bucket>$aux`` under the same actor, holds the body
rows of items over the span threshold and the key rows of ``append_once()``. Code
that enumerates an actor's buckets sees these ``$aux`` buckets; leave them alone, the
list owns them (``clear()`` and ``delete()`` remove them with the list).

**The old layout.** Before 4.0 an attribute list was ``list:<name>:meta`` and
``list:<name>:<i>``. Such a list is read in place and converted on its first change,
its metadata included; reads never convert. ``ListAttributeIterator`` is removed:
iterate the list itself. ``get_metadata()["length"]`` is advisory and ``updated_at``
best effort. A pre-4.0 process reads a converted list as empty, and a write it makes
lands in the old layout beside the new one: the list then raises
``ListLayoutConflictError`` on every access. Finish a rolling deploy before lists
convert, and check with ``actingweb-verify-property-lists --attributes --bucket
<bucket>`` (:doc:`../guides/property-lists`).

**Custom backends.** Attribute lists need nine more ``DbAttribute`` methods
(``ATTRIBUTE_LIST_PRIMITIVES`` in ``actingweb.db.protocols``); see
:doc:`../migration/v4.0`, "Custom database backends". On PostgreSQL they need
revision ``a7b8c9d0e1f2`` (``check_ready()`` raises ``AttributeSchemaNotReady``
until it is applied).

Complete Bucket Reference
-------------------------

The following table documents all buckets used by ActingWeb:

System-Level Buckets (Global)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table:: System-Level Buckets
   :widths: 20 15 45 20
   :header-rows: 1

   * - Bucket Name
     - System Actor
     - Purpose
     - TTL
   * - ``trust_types``
     - ``_actingweb_system``
     - Global registry of trust relationship type definitions
     - Permanent
   * - ``oauth_sessions``
     - ``_actingweb_oauth2``
     - Temporary OAuth2 sessions for postponed actor creation
     - 10 minutes
   * - ``spa_access_tokens``
     - ``_actingweb_oauth2``
     - SPA (Single Page App) access token storage
     - 1 hour
   * - ``spa_refresh_tokens``
     - ``_actingweb_oauth2``
     - SPA refresh token storage
     - 2 weeks
   * - ``auth_code_index``
     - ``_actingweb_oauth2``
     - Global index mapping auth codes to actor IDs
     - 10 minutes (tied to auth code)
   * - ``access_token_index``
     - ``_actingweb_oauth2``
     - Global index mapping access tokens to actor IDs
     - Tied to token lifetime
   * - ``refresh_token_index``
     - ``_actingweb_oauth2``
     - Global index mapping refresh tokens to actor IDs
     - Tied to token lifetime
   * - ``client_index``
     - ``_actingweb_oauth2``
     - Global index mapping MCP client IDs to actor IDs
     - Permanent (until client deleted)

Per-Actor Buckets
~~~~~~~~~~~~~~~~~

.. list-table:: Per-Actor Buckets
   :widths: 20 45 15 20
   :header-rows: 1

   * - Bucket Name
     - Purpose
     - TTL
     - Cleanup Trigger
   * - ``_internal``
     - Internal actor metadata (email, trustee_root, oauth tokens, ``auth_method`` and, after an adoption, ``auth_method_adopted_from``, ``auth_method_adopted_at``, ``auth_method_replaced_actor_id``)
     - Permanent
     - Actor deletion
   * - ``trust_permissions``
     - Per-trust permission overrides for peer relationships
     - Permanent
     - Trust deletion
   * - ``mcp_clients``
     - MCP client credentials and registration data
     - Permanent
     - Client deletion
   * - ``mcp_tokens``
     - MCP access tokens issued to clients
     - 1 hour
     - Token revocation or expiry
   * - ``mcp_refresh_tokens``
     - MCP refresh tokens for token renewal
     - 30 days
     - Token revocation or expiry
   * - ``mcp_auth_codes``
     - Temporary authorization codes during OAuth2 flow
     - 10 minutes
     - Code exchange or expiry
   * - ``mcp_google_tokens``
     - Stored Google OAuth2 tokens for MCP authentication
     - Tied to access token
     - Access token deletion
   * - ``oauth_tokens:{peer_id}``
     - OAuth2 tokens per trust relationship
     - Permanent
     - Trust deletion
   * - ``remote:{peer_id}``
     - Replica of a peer's subscribed data (scalars, and lists in the attribute list
       layout); see :doc:`../guides/subscriptions`
     - Permanent
     - Trust deletion (``auto_cleanup``)
   * - ``{bucket}$aux``
     - Side bucket of the attribute lists in ``{bucket}``: spanned items' body rows,
       ``append_once()`` key rows
     - Permanent
     - The list's ``clear()``/``delete()``; actor deletion

Data Type Details
-----------------

MCP Client Data (``mcp_clients``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   {
       "client_id": "mcp_abc123",
       "client_secret": "hashed_secret",
       "client_name": "My MCP Client",
       "redirect_uris": ["https://example.com/callback"],
       "grant_types": ["authorization_code", "refresh_token"],
       "response_types": ["code"],
       "trust_type": "mcp_client",
       "created_at": 1703001234,
       "actor_id": "actor123"
   }

MCP Access Token (``mcp_tokens``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   {
       "token_id": "unique_token_id",
       "token": "aw_access_token_value",
       "actor_id": "actor123",
       "client_id": "mcp_abc123",
       "created_at": 1703001234,
       "expires_at": 1703004834,  # created_at + 3600
       "expires_in": 3600,
       "google_token_key": "google_token_access_xyz"  # Reference to stored Google token
   }

OAuth Session (``oauth_sessions``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   {
       "token_data": {"access_token": "...", "refresh_token": "..."},
       "user_info": {"email": "user@example.com", "name": "User"},
       "provider": "google",
       "created_at": 1703001234,
       "verified_emails": ["user@example.com"],
       "pkce_verifier": "base64_verifier_string"
   }

Trust Permission Override (``trust_permissions``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   {
       "actor_id": "actor123",
       "peer_id": "peer456",
       "properties": {
           "config/settings": "rw",
           "config/*": "r"
       },
       "updated_at": "2024-01-15T10:30:00Z"
   }

Data Lifecycle and Cleanup
--------------------------

Actor Deletion
~~~~~~~~~~~~~~

When ``actor.delete()`` is called, the following cleanup occurs:

1. **Peer Trustees** - All peer trustee relationships deleted
2. **Properties** - All actor properties deleted
3. **Subscriptions** - All subscriptions deleted
4. **Trust Relationships** - For each trust:

   - Subscriptions for that peer deleted
   - If OAuth2 client trust: the actor's tokens for that client revoked
     first; after the record, a client registered under this actor is
     deleted (see below), while a client registered elsewhere keeps its
     registration and only this actor's other rows of it go
   - Trust record deleted, then its trust permissions and any provider
     tokens stored for it (``oauth_tokens:<peer_id>`` in ``_internal``)

5. **Attribute Buckets** - ``attribute.Buckets(actor_id).delete()`` removes ALL buckets:

   - ``_internal``
   - ``mcp_clients``
   - ``mcp_tokens``
   - ``mcp_refresh_tokens``
   - ``mcp_auth_codes``
   - ``mcp_google_tokens``
   - ``remote:{peer_id}`` replicas and every attribute list's ``{bucket}$aux`` side
     bucket
   - Any custom buckets

6. **Actor Record** - Actor deleted from ``_actors`` table

MCP Client Deletion
~~~~~~~~~~~~~~~~~~~

When an MCP client is deleted via ``client_registry.delete_client()``,
which only the actor the client is registered under may do (another
caller is refused, since the index row is global):

1. **Token Revocation** - All access and refresh tokens for the client revoked,
   each token chain marked revoked first so a refresh in flight cannot
   outlive it
2. **Client Data** - Removed from actor's ``mcp_clients`` bucket
3. **Global Index** - Removed from system actor's ``client_index``
4. **Trust Relationships** - every trust row of the client on that actor deleted
5. **Google Token Data** - Associated Google tokens cleaned up

Deleting one actor's trust row of a client registered under another actor
(a dynamically registered client lives under the system actor) ends only
that connection: ``client_registry.delete_client_connection(actor_id,
client_id)`` revokes that actor's tokens and deletes that actor's rows of
the client. The registration and every other actor's connection stay.

Token Expiration Handling
~~~~~~~~~~~~~~~~~~~~~~~~~

A token past its expiry is refused when it is read, and removed then. The
rest is removed in bulk without anything on the serving path doing a scan:

- **DynamoDB**: the rows carry a TTL attribute; enable DynamoDB's native
  TTL on the attributes table and it removes every kind of expired token
  and session.
- **PostgreSQL**: ``/oauth/spa/token`` and ``/oauth/token`` each purge
  their expired tokens at most once an hour per process; OAuth sign-in
  sessions, orphaned index entries and consumed refresh tokens past the
  reuse window need the scheduled ``cleanup_expired_tokens()``.

:doc:`../guides/database-maintenance` has the setup for both backends and
what each cleanup removes.

Maintenance Recommendations
---------------------------

.. note::

   ActingWeb typically runs in **AWS Lambda** with hundreds of concurrent containers.
   Fast cold start time is critical. **Never add cleanup logic to the serving path.**

.. seealso::

   For detailed deployment instructions including DynamoDB TTL configuration
   and cleanup Lambda setup, see :doc:`../guides/database-maintenance`.

Recommended Approach (Lambda-Optimized)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Enable DynamoDB TTL** (Primary Solution - Zero Runtime Overhead):

   .. code-block:: python

      # Add ttl_timestamp field to Attribute model
      class Attribute(Model):
          # ... existing fields ...
          ttl_timestamp = NumberAttribute(null=True)

   .. code-block:: bash

      # Enable TTL on the table
      aws dynamodb update-time-to-live \
        --table-name {prefix}_attributes \
        --time-to-live-specification "Enabled=true, AttributeName=ttl_timestamp"

2. **Scheduled Cleanup Lambda** (For Index Cleanup):

   .. code-block:: python

      # cleanup_lambda.py - SEPARATE Lambda, NOT in serving path
      def handler(event, context):
          """Triggered daily by EventBridge."""
          session_mgr = OAuth2SessionManager(config)
          session_mgr.clear_expired_sessions()
          session_mgr.cleanup_expired_tokens()

3. **Keep Lazy Cleanup** (Current Behavior):

   The existing lazy cleanup during token validation is appropriate - it adds
   no extra overhead since validation happens anyway.

Anti-Patterns for Lambda
~~~~~~~~~~~~~~~~~~~~~~~~

.. warning::

   **Do NOT do these in Lambda environments:**

   - Startup cleanup (adds cold start latency, thundering herd)
   - Request-based periodic cleanup (unpredictable latency spikes)
   - Any synchronous cleanup in the serving path

Monitoring Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. CloudWatch metric for ``_actingweb_oauth2`` bucket item count
2. Alert if item count exceeds threshold (indicates TTL not working)
3. Monitor DynamoDB TTL deletion metrics
4. Track cleanup Lambda execution results

Client Registry Example
-----------------------

.. code-block:: python

   class ClientRegistry:
       def __init__(self, config):
           self.config = config

       def register_client(self, actor_id: str, client_data: dict) -> None:
           bucket = attribute.Attributes(actor_id=actor_id, bucket="clients", config=self.config)
           bucket.set_attr(name=client_data["client_id"], data=client_data)
           index = attribute.Attributes(actor_id="_global_registry", bucket="client_index", config=self.config)
           index.set_attr(name=client_data["client_id"], data=actor_id)

       def find_client(self, client_id: str) -> dict | None:
           index = attribute.Attributes(actor_id="_global_registry", bucket="client_index", config=self.config)
           actor_id_attr = index.get_attr(name=client_id)
           if not actor_id_attr or "data" not in actor_id_attr:
               return None
           actor_id = actor_id_attr["data"]
           bucket = attribute.Attributes(actor_id=actor_id, bucket="clients", config=self.config)
           client_attr = bucket.get_attr(name=client_id)
           return client_attr.get("data") if client_attr else None

       def delete_client(self, actor_id: str, client_id: str) -> bool:
           """Delete client and clean up index - ALWAYS do both!"""
           # Delete from actor bucket
           bucket = attribute.Attributes(actor_id=actor_id, bucket="clients", config=self.config)
           bucket.delete_attr(name=client_id)
           # Delete from global index
           index = attribute.Attributes(actor_id="_global_registry", bucket="client_index", config=self.config)
           index.delete_attr(name=client_id)
           return True

Best Practices
--------------

1. **JSON-serializable data only** - All data must be JSON serializable
2. **Use attributes for sensitive data** - Better than properties for secrets
3. **Keep bucket names stable** - Treat keys as logical IDs
4. **Always clean up indexes** - When deleting data with global indexes, delete both
5. **Set appropriate TTLs** - Plan for data lifecycle from the start
6. **Monitor bucket growth** - Especially for system actor buckets
7. **Implement lazy + scheduled cleanup** - Both patterns together work best

See Also
--------

- :doc:`../reference/actingweb-db` - Database implementation details
- :doc:`../guides/mcp-applications` - MCP application guide
- :doc:`../guides/trust-relationships` - Trust and permission management
