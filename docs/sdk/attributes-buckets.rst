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
- Returns ``False`` if value was modified by another request (no update performed)

**Use Cases:**

- OAuth refresh token rotation (prevents concurrent reuse)
- Distributed counters and rate limiting
- Session management with concurrent requests
- Any scenario requiring optimistic locking

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
     - Internal actor metadata (email, trustee_root, oauth tokens)
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
   - Trust permissions deleted
   - If OAuth2 client trust: triggers client cleanup (tokens revoked, indexes cleaned)
   - Trust record deleted

5. **Attribute Buckets** - ``attribute.Buckets(actor_id).delete()`` removes ALL buckets:

   - ``_internal``
   - ``mcp_clients``
   - ``mcp_tokens``
   - ``mcp_refresh_tokens``
   - ``mcp_auth_codes``
   - ``mcp_google_tokens``
   - Any custom buckets

6. **Actor Record** - Actor deleted from ``_actors`` table

MCP Client Deletion
~~~~~~~~~~~~~~~~~~~

When an MCP client is deleted via ``client_registry.delete_client()``:

1. **Token Revocation** - All access and refresh tokens for the client revoked
2. **Client Data** - Removed from actor's ``mcp_clients`` bucket
3. **Global Index** - Removed from system actor's ``client_index``
4. **Trust Relationship** - OAuth2 client trust deleted
5. **Google Token Data** - Associated Google tokens cleaned up

Token Expiration Handling
~~~~~~~~~~~~~~~~~~~~~~~~~

**Current Behavior: Lazy Deletion Only**

Expired tokens are deleted only when accessed and found to be expired:

.. code-block:: python

   # Example from token_manager.py
   def validate_access_token(self, token):
       token_data = self._get_access_token(token)
       if token_data and int(time.time()) > token_data["expires_at"]:
           self._remove_access_token(token)  # Lazy deletion
           return None
       return token_data

**Known Limitations:**

- No scheduled garbage collection
- No DynamoDB TTL configured
- Expired but never-accessed tokens accumulate
- Abandoned OAuth sessions may persist

Cleanup Methods Available
~~~~~~~~~~~~~~~~~~~~~~~~~

The following cleanup methods exist but are not automatically called:

.. code-block:: python

   from actingweb.oauth_session import OAuth2SessionManager

   session_mgr = OAuth2SessionManager(config)

   # Clear expired OAuth sessions (10 min TTL)
   cleared = session_mgr.clear_expired_sessions()

   # Clear expired SPA tokens
   cleared = session_mgr.cleanup_expired_tokens()

Known Issues and Gaps
---------------------

Data That May Accumulate
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table:: Potential Data Accumulation
   :widths: 25 15 60
   :header-rows: 1

   * - Data Type
     - Risk Level
     - Description
   * - Expired OAuth sessions
     - Medium
     - Sessions from abandoned OAuth flows (10 min TTL, lazy cleanup)
   * - Expired SPA refresh tokens
     - High
     - 2-week TTL, accumulates if users don't refresh
   * - Expired MCP refresh tokens
     - Critical
     - 30-day TTL, significant accumulation potential
   * - Expired auth codes
     - Medium
     - Codes from abandoned OAuth flows (10 min TTL)
   * - Orphaned Google token data
     - Medium
     - May remain if refresh token deleted before access token

Cleanup Not Implemented
~~~~~~~~~~~~~~~~~~~~~~~

1. **Reverse Token Lookups** - ``_revoke_refresh_tokens_for_access_token()`` logs warning but doesn't delete
2. **Scheduled Cleanup** - No cron/background task for expired data
3. **DynamoDB TTL** - Not configured on the attributes table

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
