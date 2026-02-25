=========
CHANGELOG
=========

Unreleased
----------

ADDED
~~~~~

- **Multi-Provider OAuth Support**: Multiple OAuth providers (e.g., Google and GitHub) can now be configured simultaneously using ``.with_oauth(provider="google", ...).with_oauth(provider="github", ...)``. The factory login page renders buttons for all configured providers, OAuth state parameter carries the provider name for correct callback routing, and ``/oauth/config`` (SPA endpoint) returns all configured providers. Fully backward compatible — existing single-provider configurations work without modification.

- **SPA Email Form Fallback for GitHub**: When GitHub returns no verified emails and ``require_email=True``, the SPA OAuth callback now redirects to ``/oauth/email`` (email collection form) instead of returning a hard error. This matches the existing Web UI behavior and provides a recovery path for GitHub users with private/unverified emails.

- **Provider Display Name Helper**: New ``get_provider_display_name()`` public function in ``oauth2`` module for consistent provider name formatting (e.g., "GitHub" instead of "Github").

CHANGED
~~~~~~~

- **Loosen dependency version constraints**: Runtime dependencies now use more permissive version ranges (e.g., ``boto3 >=1.26``, ``requests >=2.20``, ``cryptography >=43.0``) to reduce version conflicts for downstream consumers. Optional framework dependencies (Flask, FastAPI, uvicorn) also loosened.

- **Update dev dependencies**: Bump ``ruff`` to 0.15.x, ``responses`` to 0.26.x, ``pytest-rerunfailures`` to 16.x. Remove ``black`` (redundant with ``ruff format``).

- **Rename ``google_token_data`` parameter**: ``TokenManager.create_authorization_code()`` parameter renamed from ``google_token_data`` to ``provider_token_data`` to reflect multi-provider support.

- **Make ``get_github_verified_emails()`` public**: Renamed from ``_get_github_verified_emails()`` on ``OAuth2Authenticator`` to remove the private prefix, as it is called across class boundaries.

FIXED
~~~~~

- **PostgreSQL Properties Value Index Removed**: Dropped the ``idx_properties_value`` B-tree index on the ``properties.value`` column. This index blocked storage of large values (embeddings, JSON blobs) that exceed the B-tree page size limit (~2700 bytes). The ``property_lookup`` table already provides targeted reverse-index lookups for properties that need value-based search. Includes Alembic migration ``c3d4e5f6a7b8`` to drop the index on existing databases.

- **GitHub Email Verification Security**: ``_get_github_primary_email()`` now requires both ``primary`` and ``verified`` flags when selecting the email for actor linking. Previously, an unverified primary email was accepted, which could allow account-linking attacks via the GitHub ``/user/emails`` API. If no verified primary email is available, falls back to the first verified non-primary email.

- **MCP Flow Verified Email Requirement**: The MCP OAuth flow now returns a clear ``invalid_grant`` error message when no verified email is available from the provider, explaining that a verified email is required and suggesting the user add one to their provider account.

- **Token revocation uses correct provider**: Logout and token revocation endpoints now look up the OAuth provider from the session cookie instead of always using the default provider. Ensures tokens are sent to the correct revocation endpoint in multi-provider deployments.

IMPROVED
~~~~~~~~

- **Logging in register_diffs()**: Replaced string concatenation logging with parameterized ``%s`` formatting in ``Actor.register_diffs()``. Diff blob contents are no longer logged verbatim; instead only the byte length is logged (e.g. ``diff(1234 bytes)``), reducing log noise and avoiding accidental exposure of large payloads.
- **Flattened out the thoughts dir**: Moved all the sub-dirs under thoughts/ to simplify where AI docs live

v3.10.0b3: Feb 6, 2026
-----------------------

FIXED
~~~~~

- **Async MCP Resource Lookup**: Fixed three critical bugs in ``AsyncMCPHandler._handle_resource_read_async()`` that prevented MCP resources from being discovered and executed. (1) Handler checked ``metadata.get("uri")`` but resources are registered with ``"uri_template"`` field - added fallback chain checking ``uri_template`` first, then ``uri``, then generating default. (2) URI template matching called with reversed parameters ``_match_uri_template(uri, uri_template)`` instead of correct order ``(uri_template, uri)``. (3) Match result checked with ``if match_result:`` which treated empty dict ``{}`` (valid match with no variables) as falsy - changed to ``if match_result is not None:``. Resources now work correctly in async MCP handler.

v3.10.0b2: Feb 5, 2026
-----------------------

ADDED
~~~~~

- **Revoke Peer Subscription Method**: New ``SubscriptionManager.revoke_peer_subscription(peer_id, subscription_id)`` method provides semantically clear way to delete inbound subscriptions (peer's subscription to our data). This method notifies the peer to delete their outbound subscription and deletes our local inbound record. Improves API clarity compared to the generic ``unsubscribe()`` method which works for both directions but has misleading naming for inbound subscriptions.

- **Subscription Deleted Lifecycle Hook**: New ``subscription_deleted`` lifecycle event triggered when a subscription is deleted, particularly useful for cleanup when peers unsubscribe. The hook receives ``actor``, ``peer_id``, ``subscription_id``, ``subscription_data``, and ``initiated_by_peer`` flag. Applications can use this to revoke permissions, clean up cached data, or send notifications when peers unsubscribe. Only triggered for inbound subscriptions (where peer subscribes to us) to prevent duplicate cleanup.

- **Revoked Trust Detection**: Automatic detection and cleanup when a peer has revoked a trust relationship. During subscription sync, if all subscriptions return 404, the system verifies the trust relationship with the peer and either cleans up dead subscriptions (if trust still exists) or removes the local trust entirely, triggering the ``trust_deleted`` lifecycle hook.

- **Baseline Sync on Subscription Creation**: ``subscribe_to_peer()`` and new ``subscribe_to_peer_async()`` now perform an immediate baseline data fetch after creating the subscription. This ensures consistent initial state regardless of whether the peer has existing data or pending diffs.

- **Peer Metadata Refresh on Subscribe**: Initial subscription creation now automatically refreshes cached peer profile, capabilities, and permissions metadata when configured, eliminating the need for a separate sync cycle.

- **RemotePeerStore Enumeration**: Added ``list_all_scalars()`` and ``get_all_properties()`` methods to ``RemotePeerStore`` for enumerating stored peer data. ``get_all_properties()`` returns a combined view of all lists and scalars with type metadata (type, value, item_count).

FIXED
~~~~~

- **RemotePeerStore Cleanup with Multiple Subscriptions**: Fixed a bug where deleting one outbound subscription would incorrectly clean up the RemotePeerStore even when other active outbound subscriptions to the same peer still existed. Moved cleanup logic from low-level ``Subscription.delete()`` to ``Actor.delete_subscription()`` where it can properly check for remaining subscriptions using the Actor interface (``get_subscriptions()``), ensuring cached peer data is preserved when still needed by other subscriptions.

- **Missing Callback Parameter in Unsubscribe**: Fixed a critical bug in ``SubscriptionManager.unsubscribe()`` where the ``callback=True`` parameter wasn't passed to ``delete_subscription()`` when deleting the local outbound subscription. This caused RemotePeerStore cleanup to be skipped entirely, leaving cached peer data orphaned after unsubscribing. The method now correctly passes ``callback=True`` to trigger proper cleanup of outbound subscriptions.

- **Stale Subscription Cache Preventing Cleanup**: Fixed a bug in ``Actor.delete_subscription()`` where the subscription list cache (``self.subs_list``) was not cleared before checking for remaining subscriptions, causing the check to use stale data including already-deleted or currently-deleting subscriptions. This prevented RemotePeerStore cleanup from running even when deleting the last subscription to a peer. The method now clears the cache before checking and after deletion to ensure fresh data.

- **Wrong Field Name in Subscription Filtering**: Fixed a critical bug in ``Actor.delete_subscription()`` where the filter checked ``s.get("subid")`` instead of ``s.get("subscriptionid")``, causing the filter to never match any subscriptions. This meant every subscription deletion would find "other subscriptions still active" (the one being deleted) and skip RemotePeerStore cleanup entirely, leaving orphaned peer data. The filter now uses the correct field name ``subscriptionid``.

- **Subscription Deletion Cleanup**: Fixed a bug in the subscription handler where the actual ``callback`` value from the subscription record wasn't passed to ``delete_subscription()``, causing incorrect RemotePeerStore cleanup. The handler now fetches the subscription first to determine whether it's inbound (``callback=False``) or outbound (``callback=True``), then passes the correct value to ensure proper cleanup: outbound subscriptions clean up cached peer data, while inbound subscriptions don't.

- **Subscription Listing by Peer**: Fixed a bug in the subscription handler where ``GET /subscriptions?peerid=X`` only returned outbound subscriptions (where we subscribed to peer) instead of all subscriptions involving that peer. The endpoint now returns both outbound and inbound subscriptions (where peer subscribed to us), matching the expected API behavior.

- **Permission Diff Asymmetry**: Fixed a bug where permission callbacks sent only override fields instead of the full effective permissions (base trust-type defaults merged with overrides). This caused ``detect_permission_changes()`` to incorrectly report base permissions as revoked when only new permissions were granted, leading to potential data loss via ``_delete_revoked_peer_data()``. The ``GET /permissions/{peer_id}`` endpoint now also returns merged effective permissions for consistency.

- **Non-Destructive Resync**: ``RemotePeerStore.apply_resync_data()`` now replaces only the specific properties included in the resync data instead of deleting all peer data first. This prevents data loss when multiple subscriptions exist to the same peer (e.g., subscription A syncs ``memory_*`` properties, subscription B resyncs ``status`` - previously, B's resync would delete all of A's data).

- **Permission Format Normalization**: Both shorthand list format (``["pattern1", "pattern2"]``) and spec-compliant dict format (``{"patterns": [...], "operations": [...]}``) are now accepted and normalized consistently across all permission APIs. Shorthand format defaults to read-only operations. This applies to ``TrustPermissions`` storage, ``PeerPermissions`` callbacks, and ``AccessControlConfig.add_trust_type()``.

IMPROVED
~~~~~~~~

- **Incremental Sync on Permission Grant**: Permission grant auto-sync now fetches only the newly granted properties instead of doing a full ``sync_peer()`` which refetched the entire baseline, capabilities, and permissions. Reduces HTTP requests from ~7 to 1-2 per permission grant.

- **Capability Cache Staleness Check**: ``sync_peer()`` now checks if cached peer capabilities (methods/actions) are fresh before refetching. Capabilities are only refetched when the cache is older than ``peer_capabilities_max_age_seconds`` (default: 1 hour, configurable via ``with_peer_capabilities(max_age_seconds=...)``). A new ``force_refresh`` parameter on ``sync_peer()`` and ``sync_peer_async()`` bypasses staleness checks for manual/developer-triggered syncs.

- **Structured Proxy Error Responses**: All ``aw_proxy`` resource methods (GET, POST, PUT, DELETE, sync and async) now return structured error dicts (with ``code`` and ``message``) for all error responses, including when the peer returns JSON with a string-typed ``error`` field (e.g., ``{"error": "Not found"}``). Previously, the actual HTTP status code (e.g., 404) was lost and replaced with a hardcoded 500 in downstream error handling.

- **Robust Error Format Handling**: ``peer_permissions`` now handles both dict and string error formats in peer responses, preventing ``AttributeError`` on unexpected error shapes.

- **Privacy in List Attribute Logging**: ``ListAttribute.append()`` no longer logs actual user data values; only metadata (type and size) is logged.

- **Consolidated Baseline Fetch Logic**: Resync callbacks and subscription creation now share the same baseline fetch and transformation helpers (``_fetch_and_transform_baseline``), ensuring consistent handling of ``?metadata=true`` expansion and property list transformations.

- **Parallel Test Isolation**: Significantly improved pytest-xdist parallel test execution reliability, reducing flakiness from ~5% to <1%:

  - Worker-namespaced OAuth2 client registration prevents token exchange conflicts between parallel workers
  - Pre/post cleanup for both DynamoDB and PostgreSQL ensures clean database state between runs
  - Enhanced botocore pre-warming with timeout handling prevents initialization hangs
  - Added pytest-rerunfailures with retry logic for transient failures (temporary safety net)

- **Test Infrastructure Documentation**: Created comprehensive xdist group documentation (``tests/integration/XDIST_GROUPS.md``) covering all 42 test groups with categorization and rationale.

- **CI/CD Reliability**: Enhanced GitHub Actions workflow with automated group verification, flakiness reporting, and retry logic for improved stability across both DynamoDB and PostgreSQL matrix jobs.

CHANGED
~~~~~~~

- **SDK Documentation**: Updated ``developer-api.rst`` and ``async-operations.rst`` to reflect new ``subscribe_to_peer()`` and ``subscribe_to_peer_async()`` signatures and baseline sync behavior.

- **Subscription Management Documentation**: Enhanced ``developer-api.rst`` with comprehensive guide for subscription directions (inbound vs outbound), ``unsubscribe()`` vs ``revoke_peer_subscription()`` usage, and subscription lifecycle hook integration.

ADDED (Test Infrastructure)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Test Group Verification**: New ``tests/integration/verify_groups.py`` script ensures all xdist groups are documented, integrated into CI pipeline to prevent undocumented groups.

- **Subscription Lifecycle Integration Tests**: New ``test_subscription_lifecycle_hooks.py`` with 29 tests covering ``subscription_deleted`` hook execution, ``revoke_peer_subscription()`` method, and bidirectional subscription management (unsubscribe vs revoke).

v3.10.0b1: Jan 30, 2026
-----------------------

ActingWeb 3.10 introduces **automatic subscription processing**, comprehensive **request correlation and logging**, and major improvements to subscription reliability. This beta includes all features from alpha releases plus critical bug fixes for subscription handling.

**Highlights:**

- **Automatic Subscription Processing**: CallbackProcessor, RemotePeerStore, and FanOutManager reduce callback handling from ~500 lines to ~30 lines
- **Request Correlation**: Full distributed tracing with request IDs, actor IDs, and peer IDs in every log line
- **Subscription Reliability**: Fixed critical bugs in callback sequencing, diff handling, and resync operations
- **Security**: Comprehensive logging hardening and remote peer data sanitization
- **Performance**: Bulk permission evaluation, configurable thread pools, and optimized property filtering

ADDED
~~~~~

- **Inbound Subscription Query Method**: New ``SubscriptionManager.get_subscriptions_from_peer(peer_id)`` method for querying inbound subscriptions where a peer has subscribed to our data. Complements existing ``get_subscriptions_to_peer()`` for symmetric subscription discovery.

- **Lambda Environment Detection**: Automatic detection of AWS Lambda deployments with warnings when asynchronous subscription callbacks are enabled. Helps prevent callback loss when Lambda functions freeze by recommending ``with_sync_callbacks()``.

- **Configurable FastAPI Thread Pool**: New ``ActingWebApp.with_thread_pool_workers(workers)`` method for tuning thread pool size (1-100 workers, default 10). Includes documentation with tuning guidelines for Lambda, container, and CPU-bound scenarios.

- **Request Correlation in Logging**: Comprehensive logging framework with automatic context injection. Every log line includes ``[request_id:actor_id:peer_id]`` for distributed request tracing across actor-to-actor communication.

  - New modules: ``actingweb.request_context`` (thread-safe context storage), ``actingweb.log_filter`` (context injection)
  - New functions: ``enable_request_context_filter()``, ``configure_production_logging()``, ``configure_development_logging()``
  - Request IDs extracted from ``X-Request-ID`` header or auto-generated
  - Response headers include ``X-Request-ID`` for client correlation
  - Context automatically managed by Flask and FastAPI integrations
  - Minimal overhead: <1% performance impact

- **Inter-Actor Request Correlation**: Request correlation headers (``X-Request-ID``, ``X-Parent-Request-ID``) automatically added to all peer-to-peer communication, enabling complete request chain tracing across actor networks.

- **Request Context API**: Public API for custom integrations: ``set_request_context()``, ``get_request_id()``, ``get_actor_id()``, ``get_peer_id()``, ``clear_request_context()``. Thread-safe and async-safe using Python's ``contextvars``.

CHANGED
~~~~~~~

- **Authentication Sets Peer Context**: Authentication layer now automatically sets peer ID in request context after successful authentication for logging correlation.

- **Flask/FastAPI Integration Context Management**: Both integrations now automatically manage request context lifecycle with hooks/middleware for extracting request IDs, actor IDs, and adding correlation headers to responses.

IMPROVED
~~~~~~~~

- **Bulk Property Permission Evaluation**: Optimized property permission checks to use bulk evaluation, reducing DEBUG log volume by 10-50x for multi-property operations. Single log line for batch operations with summary: "N properties: X allowed, Y denied, Z not found".

- **Action and Method List Filtering**: Actions and methods list endpoints now filter results based on peer permissions, preventing information disclosure of restricted capabilities.

- **FastAPI Context Propagation**: Fixed context propagation to thread pool workers, ensuring log statements from synchronous handlers preserve request ID, actor ID, and peer ID context.

- **Logging Configuration**: Enhanced ``actingweb.logging_config`` with per-component log levels (``db_level``, ``auth_level``, ``handlers_level``, ``proxy_level``) and convenience functions for common scenarios.

SECURITY
~~~~~~~~

- **Remote Peer Data Sanitization**: Comprehensive sanitization of all data from remote peers to prevent JSON encoding failures from malformed Unicode. Removes invalid UTF-16 surrogate pairs and replaces invalid UTF-8 sequences. Applied to all RemotePeerStore operations and database writes.

- **Logging Security Hardening**: Comprehensive audit of all log statements to prevent sensitive information leakage:
  - Token masking (shows only first 8 characters)
  - Removed full access/refresh tokens from logs (18 statements)
  - Removed OAuth2 request bodies containing client secrets
  - Removed HTTP headers containing Authorization headers
  - Removed property values from property handler logs
  - Removed HTTP response content from debug logs
  - Changed verbose INFO logs to DEBUG for high-frequency operations

FIXED
~~~~~

- **Property Deletion via Subscription Callbacks**: ``RemotePeerStore.apply_callback_data()`` now correctly handles property deletion. Per the ActingWeb spec, an empty string value in a diff callback means the property was deleted. Previously, deleted properties were stored as ``{"value": ""}`` instead of being removed from the store.

- **List Property Format Parameter**: Added ``format`` query parameter to list property GET requests. Use ``?format=short`` to retrieve metadata only (count, description, explanation) without fetching all items.

DOCUMENTATION
~~~~~~~~~~~~~

- Added FastAPI performance tuning section with thread pool configuration, Lambda deployment best practices, and automatic Lambda detection documentation
- Added comprehensive logging and correlation guide (``docs/guides/logging-and-correlation.rst``) with grepping examples and request chain tracing patterns
- Documented request context API for custom integrations
- Updated configuration quickstart with logging configuration section

For complete details on features introduced in alpha releases (automatic subscription processing, peer profile/capabilities/permissions caching, subscription suspension, attribute list storage, etc.), see the v3.10.0a5 and earlier entries below.

Unreleased
----------

v3.10.0a5: Jan 26, 2026
-----------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- **Library Bucket Naming Convention**: All library-internal buckets now use ``_`` prefix to avoid namespace collisions with user-defined buckets. Application code can create arbitrary buckets via ``Attributes(actor_id=..., bucket="mydata")``. Without a reserved prefix, a user's ``bucket="peer_permissions"`` would collide with the library's.

  **Renamed buckets** (old -> new):

  - ``trust_types`` -> ``_trust_types``
  - ``trust_permissions`` -> ``_trust_permissions``
  - ``peer_profiles`` -> ``_peer_profiles``
  - ``peer_capabilities`` -> ``_peer_capabilities``
  - ``auth_code_index`` -> ``_auth_code_index``
  - ``access_token_index`` -> ``_access_token_index``
  - ``refresh_token_index`` -> ``_refresh_token_index``
  - ``client_index`` -> ``_client_index``
  - ``oauth_sessions`` -> ``_oauth_sessions``

  **Migration**: Existing data in old bucket names will need to be migrated. For most deployments, the data is transient (OAuth sessions, token indexes) and will naturally be recreated. Trust types and permissions may need explicit migration if you have existing trust relationships.


ADDED
~~~~~

- **AsyncMCPHandler for FastAPI**: Added ``AsyncMCPHandler`` class for optimal async performance with FastAPI integration. MCP tools and prompts with async hooks now execute natively in the FastAPI event loop without thread pool overhead, enabling true concurrent execution and significantly better performance for I/O-bound operations.

  - New handler: ``actingweb.handlers.async_mcp.AsyncMCPHandler``
  - FastAPI integration automatically uses ``AsyncMCPHandler`` for MCP endpoints
  - Async MCP tools (action hooks) and prompts (method hooks) execute without thread pool bouncing
  - Backward compatible: sync MCP hooks continue to work
  - Performance improvement: 30-50% reduction in response time for async I/O operations
  - Flask integration continues using sync ``MCPHandler`` (appropriate for WSGI)
  - See ``docs/guides/async-hooks-migration.rst`` for detailed async MCP usage patterns

- **Database Accessor Pattern**: Added factory functions in ``actingweb.db`` module for creating database instances with configuration automatically injected. This ensures all DB objects respect application settings like ``indexed_properties`` and ``use_lookup_table``.

  - New accessor functions: ``get_property()``, ``get_property_list()``, ``get_actor()``, ``get_actor_list()``, ``get_trust()``, ``get_trust_list()``, ``get_peer_trustee()``, ``get_peer_trustee_list()``, ``get_subscription()``, ``get_subscription_list()``, ``get_subscription_diff()``, ``get_subscription_diff_list()``, ``get_subscription_suspension()``, ``get_attribute()``, ``get_attribute_bucket_list()``
  - New utility function: ``get_db_accessors()`` returns dictionary of all accessor functions
  - New protocol definitions in ``actingweb.db.protocols`` for all database interfaces
  - Improved type safety: Full IDE autocomplete and type checking support
  - Simplified usage pattern: ``db = get_property(config)`` instead of ``db = config.DbProperty.DbProperty()``

- **Auto-Delete Cached Peer Data on Permission Revocation**: Added optional automatic deletion of cached peer data when permissions are revoked.

  - New parameter: ``ActingWebApp.with_peer_permissions(auto_delete_on_revocation=True)``
  - New helper functions in ``actingweb.peer_permissions``: ``detect_revoked_property_patterns()``, ``detect_permission_changes()``
  - Permission callback hooks now receive ``permission_changes`` dict with revocation details
  - When enabled, cached data in ``RemotePeerStore`` matching revoked property patterns is automatically deleted
  - Disabled by default for backwards compatibility

- **Peer Profile Caching**: Added first-class support for caching profile attributes from peer actors with trust relationships. This enables applications to access peer information (displayname, email, etc.) without making repeated API calls.

  - New module: ``actingweb.peer_profile`` - ``PeerProfile`` dataclass and ``PeerProfileStore`` for storage
  - New configuration method: ``ActingWebApp.with_peer_profile(attributes=["displayname", "email", "description"])``
  - New TrustManager methods: ``get_peer_profile()``, ``refresh_peer_profile()``, ``refresh_peer_profile_async()``
  - Automatic profile fetch on trust approval via lifecycle hooks (``trust_fully_approved_local``, ``trust_fully_approved_remote``)
  - Automatic profile cleanup on trust deletion via ``trust_deleted`` hook
  - Profile refresh during ``sync_peer()`` and ``sync_peer_async()`` operations
  - Both sync and async fetch functions for flexible usage patterns

- **Peer Capabilities Caching (Methods & Actions)**: Added first-class support for caching methods and actions that peer actors expose. This enables applications to discover and access peer RPC methods and state-modifying actions without making repeated API calls.

  - Extended ``actingweb.peer_capabilities`` module with ``CachedCapability``, ``CachedPeerCapabilities``, and ``CachedCapabilitiesStore``
  - New configuration method: ``ActingWebApp.with_peer_capabilities(enable=True)``
  - New TrustManager methods: ``get_peer_capabilities()``, ``get_peer_methods()``, ``get_peer_actions()``, ``refresh_peer_capabilities()``, ``refresh_peer_capabilities_async()``
  - Automatic capabilities fetch on trust approval via lifecycle hooks (``trust_fully_approved_local``, ``trust_fully_approved_remote``)
  - Automatic capabilities cleanup on trust deletion via ``trust_deleted`` hook
  - Capabilities refresh during ``sync_peer()`` and ``sync_peer_async()`` operations
  - Both sync and async fetch functions: ``fetch_peer_methods_and_actions()``, ``fetch_peer_methods_and_actions_async()``
  - New constant: ``PEER_CAPABILITIES_BUCKET`` for attribute storage

- **Peer Permissions Caching**: Added first-class support for caching permissions that peer actors have granted us. This is distinct from TrustPermissions which stores what WE grant to peers; PeerPermissions stores what PEERS grant to us.

  - New module: ``actingweb.peer_permissions`` - ``PeerPermissions`` dataclass and ``PeerPermissionStore`` for storage
  - New configuration method: ``ActingWebApp.with_peer_permissions(enable=True)``
  - Automatic permissions fetch on trust approval via lifecycle hooks
  - Automatic permissions cleanup on trust deletion via ``trust_deleted`` hook
  - Permissions refresh during ``sync_peer()`` and ``sync_peer_async()`` operations
  - Both sync and async fetch functions: ``fetch_peer_permissions()``, ``fetch_peer_permissions_async()``
  - Permission access checking methods: ``has_property_access()``, ``has_method_access()``, ``has_tool_access()``
  - New constant: ``PEER_PERMISSIONS_BUCKET`` for attribute storage

- **Permission Callback Type**: Added support for permission callbacks in the subscription callback system. Permission callbacks notify peers when their granted permissions change, enabling reactive permission synchronization without polling.

  - New ``CallbackType.PERMISSION`` enum value in ``callback_processor.py``
  - Permission callbacks use URL pattern ``/callbacks/permissions/{granting_actor_id}``
  - Permission callbacks are idempotent and use full replacement (not diffs)
  - Automatic storage in ``PeerPermissionStore`` when callbacks are received
  - App-specific handling via ``@app.callback_hook("permissions")`` decorator
  - New ``RemotePeerStore.apply_permission_data()`` method for programmatic permission updates

- **Automatic Peer Notification on Permission Change**: Added automatic notification of peers when their permissions are changed via ``TrustPermissionStore.store_permissions()``.

  - New configuration option: ``ActingWebApp.with_peer_permissions(notify_peer_on_change=True)`` (default: ``True``)
  - New ``TrustPermissionStore`` methods: ``store_permissions_async()``, ``_notify_peer()``, ``_notify_peer_async()``
  - Notifications are fire-and-forget (failures logged but don't block storage)
  - Sends POST to peer's ``/callbacks/permissions/{actor_id}`` endpoint
  - Can be disabled per-call via ``store_permissions(permissions, notify_peer=False)``

- **Automatic Subscription Handling**: Comprehensive subscription callback processing with automatic gap detection, resync handling, and back-pressure support. Peer capabilities are now exchanged during trust establishment to negotiate optimal callback behavior.

  - New module: ``actingweb.callback_processor`` - Processes incoming subscription callbacks with sequence validation
  - New module: ``actingweb.remote_storage`` - Manages storing remote subscription data locally
  - New module: ``actingweb.peer_capabilities`` - Peer capability negotiation during trust establishment
  - New module: ``actingweb.subscription_config`` - Configuration for subscription behavior (gap thresholds, resync policies)
  - New module: ``actingweb.fanout`` - Fan-out delivery for subscription callbacks
  - Enhanced ``Trust`` model with ``peer_capabilities`` field for storing negotiated capabilities
  - Automatic resync request when sequence gaps exceed configured thresholds
  - Subscription suspension support for temporary delivery failures
  - Circuit breaker pattern for handling unresponsive subscribers

- **Pull-Based Subscription Sync API**: Added ``sync_subscription()`` and ``sync_peer()`` methods to ``SubscriptionManager`` for explicitly fetching and processing pending diffs from peers.

  - New method: ``sync_subscription(peer_id, subscription_id, config?)`` - Sync a single subscription
  - New method: ``sync_peer(peer_id, config?)`` - Sync all outbound subscriptions to a peer
  - Async variants: ``sync_subscription_async()`` and ``sync_peer_async()``
  - New dataclass: ``SubscriptionSyncResult`` - Result of syncing a single subscription
  - New dataclass: ``PeerSyncResult`` - Aggregate result of syncing all subscriptions to a peer
  - Supports configurable processing via ``SubscriptionProcessingConfig``
  - Complements push-based callbacks for manual "Sync All" workflows

- **Subscription Suspension**: Added suspension/resume support for subscription delivery failures.

  - New database table: ``SubscriptionSuspension`` for tracking suspended subscriptions
  - DynamoDB and PostgreSQL backends with migration support
  - Automatic suspension on repeated delivery failures
  - Resync triggered on subscription resume
  - Scoped suspensions by subtarget for granular control

- **Passphrase-to-SPA-Token Exchange**: Added ``grant_type="passphrase"`` to the ``POST /oauth/spa/token`` endpoint for exchanging a valid creator passphrase for SPA tokens. This enables automated testing tools like Playwright to obtain authenticated access without going through the full OAuth2 flow.

  - Devtest-mode only (returns 403 if ``config.devtest=False``) for security
  - Returns ``access_token`` and ``refresh_token`` with standard OAuth2 response format
  - Supports all token delivery modes: ``json``, ``cookie``, ``hybrid``
  - Tokens can be used immediately to access actor resources via Bearer authentication

- **Attribute List Storage**: Added ``ListAttribute`` and ``AttributeListStore`` for storing distributed lists in internal attributes (not exposed via REST API). This provides the same API as ``ListProperty``/``PropertyListStore`` but stores data in attribute buckets instead of properties, bypassing the 400KB property size limit while maintaining list semantics.

  - New class: ``ListAttribute`` - Distributed list implementation using attributes
  - New class: ``AttributeListStore`` - Per-actor-per-bucket list management
  - Supports all standard list operations: append, extend, insert, pop, remove, index, count, clear, delete
  - Metadata support with ``get_description()``, ``set_description()``, ``get_explanation()``, ``set_explanation()``, and ``get_metadata()`` for accessing list metadata (created_at, updated_at, version, etc.)
  - Discovery methods: ``exists()``, ``list_all()``
  - Bucket isolation: Same list name can exist independently in different buckets
  - Lazy loading with ``ListAttributeIterator`` for efficient iteration
  - Attribute naming pattern: ``list:{name}:{index}`` for items, ``list:{name}:meta`` for metadata
  - Comprehensive test coverage: 12 unit tests for ListAttribute, 21 unit tests for AttributeListStore, 18 integration tests

- **List Metadata Access**: Added ``get_metadata()`` method to both ``ListProperty`` and ``ListAttribute`` to expose internal metadata (created_at, updated_at, version, item_type, chunk_size, length). Previously, users needed to access private ``_load_metadata()`` method to get timestamps and other readonly metadata fields.

- **Property/List Name Collision Detection**: Added automatic collision detection to enforce namespace exclusivity between properties and lists. Creating a property or list with a name that already exists as the other type raises a ``ValueError`` to prevent ambiguity and data loss.

  - List creation error: Attempting to create a list when a property with the same name exists raises ``ValueError``
  - Property creation error: Attempting to set a property when a list with the same name exists raises ``ValueError``
  - Clear error messages: Exception messages indicate the conflict and suggest deleting the existing item or using a different name
  - Clean namespace: Property names and list names are strictly mutually exclusive
  - Internal ``list:`` prefix remains an implementation detail, never exposed in public APIs
  - List operations: PUT requests with ``?index=N`` parameter correctly route to list item operations instead of triggering collision detection
  - Comprehensive test coverage: 4 unit tests in ``tests/test_property_list.py``, 4 integration tests in ``tests/integration/test_property_list_collision.py``

- **Comprehensive Integration Tests for Subscriptions**: Added extensive test coverage for subscription handling flows.

  - ``test_subscription_processing_flow.py``: Callback sequencing, gap detection, resync handling
  - ``test_fanout_flow.py``: Fan-out delivery, large payloads, concurrent changes, circuit breaker
  - ``test_subscription_suspension_flow.py``: Suspension/resume, subtarget scoping, multiple subscribers
  - New test fixtures: ``callback_sender``, ``trust_helper`` for subscription testing

- **CI/CD Documentation Build**: Added documentation build job to GitHub Actions workflow.

- **Configurable AwProxy Timeout**: Added ``timeout`` parameter to ``AwProxy`` constructor for configurable HTTP request timeouts. Accepts either a single value (used for both connect and read) or a tuple ``(connect_timeout, read_timeout)``. Default changed from hardcoded ``(5, 10)`` to ``(5, 20)`` seconds for better handling of slow peer responses.

- **Permission Query Endpoint**: Added ``GET /{actor_id}/permissions/{peer_id}`` endpoint allowing peers to query what permissions they've been granted. This supports proactive permission discovery, complementing the reactive callback-based push mechanism.

  - New handler: ``actingweb.handlers.permissions.PermissionsHandler``
  - Returns custom permission overrides or trust type defaults
  - Includes metadata: ``source`` (custom_override or trust_type_default), ``trust_type``, ``created_by``, ``updated_at``, ``notes``
  - Authentication required: peer must authenticate as the ``peer_id`` in the URL
  - Authorization: peer can only query their own granted permissions
  - Error responses: 404 (no trust relationship), 403 (not authorized), 500 (retrieval failed)
  - Both Flask and FastAPI integrations supported
  - Comprehensive test coverage in ``tests/test_permissions_handler.py``

- **Permission Protocol Option Tags**: Added automatic advertisement of permission-related capabilities via ActingWeb protocol option tags in ``/meta/actingweb/supported`` endpoint.

  - New option tag: ``permissioncallback`` - indicates support for receiving permission change notifications
  - New option tag: ``permissionquery`` - indicates support for ``GET /{actor_id}/permissions/{peer_id}`` endpoint
  - Tags automatically added when ``ActingWebApp.with_peer_permissions(enable=True)`` is called
  - New method: ``Config.update_supported_options()`` - dynamically updates option tags based on enabled features
  - Complies with ActingWeb Protocol Specification v1.4 requirements (spec lines 2064-2065, 2830)

- **Peer Profile Extraction from Subscriptions**: Added automatic extraction of peer profile attributes from synced subscription data in ``sync_peer()`` and ``sync_peer_async()``. When peer permissions caching is enabled and a subscription exists for profile properties, the profile is extracted from the cached subscription data before falling back to a direct HTTP fetch. This reduces unnecessary API calls and improves performance.

  - Profile attributes extracted from ``RemotePeerStore`` when available
  - Handles wrapped property values (``{"value": ...}``) correctly
  - Type conversion to strings for standard profile fields (displayname, email, description)
  - Extra attributes stored with original types preserved
  - Graceful fallback to HTTP fetch if extraction fails

SECURITY
~~~~~~~~

- **Logging Security Hardening**: Comprehensive audit and remediation of all log statements to prevent sensitive information leakage in production logs.

  - **Token masking**: Added ``_mask_token()`` helper in ``token_manager.py`` that shows only first 8 characters of tokens. Fixed 18 log statements that were previously logging full access/refresh tokens.
  - **Request body removal**: Removed logging of OAuth2 token request body in ``oauth2_endpoints.py`` which could contain client_secret, authorization codes, and refresh tokens.
  - **Headers removal**: Removed logging of HTTP request headers in ``trust.py`` which could expose Authorization headers.
  - **State data protection**: Changed ``state_manager.py`` to only log flow_type instead of full OAuth2 state data.
  - **Trust object protection**: Fixed ``auth.py`` to only log peer_id instead of full trust objects which could contain secrets.
  - **Property value protection**: Removed property values from log messages in ``handlers/properties.py``, ``db/dynamodb/property.py``, ``db/postgresql/property.py``, and ``db/postgresql/property_lookup.py``.
  - **Response content removal**: Removed HTTP response content from debug logs in ``aw_proxy.py`` (7 occurrences) - now only logs status codes.
  - **Peer creation data removal**: Removed data payload from peer actor creation logs in ``actor.py``.

CHANGED
~~~~~~~

- **Log level adjustments for production**: Changed verbose INFO-level logs to DEBUG for high-frequency operations:

  - ``aw_proxy.py``: "Fetching peer resource" logs changed from INFO to DEBUG
  - ``actor.py``: "Fetching peer info" logs changed from INFO to DEBUG

- **Debug logging cleanup**: Removed 7 commented-out debug statements in ``handlers/properties.py`` that were logging JSON data and paths.

- **List properties in non-metadata responses**: The ``GET /properties`` endpoint now includes list properties even without ``?metadata=true``. List properties are represented with a minimal marker format ``{"_list": true, "count": N}`` to allow clients to detect them without requesting full metadata. With ``?metadata=true``, the full format ``{"_list": true, "count": N, "description": "...", "explanation": "..."}`` is returned. The ``_list`` key is used consistently in both minimal and full metadata formats.

FIXED
~~~~~

- **Baseline data fetch for new subscriptions**: Fixed ``sync_subscription()`` and ``sync_subscription_async()`` to fetch baseline data from the target resource when no diffs exist. Previously, syncing a fresh subscription with 0 diffs would do nothing, leaving the remote storage empty. Now it properly establishes baseline data via ``RemotePeerStore.apply_resync_data()``, enabling features like Remote Memory to work immediately after subscription creation. The baseline fetch respects subscription scope by including subtarget and resource in the fetch path (e.g., ``/properties/myProp`` for scoped subscriptions, ``/properties?metadata=true`` for collection-level subscriptions).

- **Subscription authorization path patterns**: Changed authorization path pattern from ``<id>/<id>`` to ``<id>/<subid>`` in ``handlers/subscription.py`` for clarity and consistency with other handlers.

- **List property subscription diff callbacks**: Fixed ``list:`` prefix leakage in subscription diff callbacks. Previously, list property changes registered diffs with ``subtarget="list:myList"`` which exposed the internal ``list:`` prefix in callbacks sent to subscribers. Now uses clean subtarget (``subtarget="myList"``) - the diff blob already contains ``"list": "myList"`` to identify list operations. Subscribers no longer need to strip the prefix when processing list property callbacks.

- **Profile attribute type conversion in sync**: Fixed type conversion when extracting peer profile attributes from synced subscription data. Profile attributes retrieved from ``RemotePeerStore`` are now properly unwrapped from ``{"value": ...}`` format and converted to strings for standard profile fields (displayname, email, description). This fixes type errors where dict values were being assigned to string-typed profile fields.

- Fixed ``DbSubscriptionSuspension`` initialization: ``get_subscription_suspension()`` now requires ``actor_id`` parameter to properly initialize the suspension instance
- Fixed type annotations across database layer to eliminate pyright errors
- Fixed ``DbTrustProtocol.modify()`` signature to include missing parameters: ``aw_supported``, ``aw_version``, ``capabilities_fetched_at``
- Fixed ``DbAttributeBucketListProtocol`` to include ``fetch_timestamps()`` method
- Fixed return type handling for ``PeerTrustee.get()`` to properly handle ``bool | dict | None`` returns

- **Subscription Baseline Sync for List Properties**: Fixed a bug where subscription baseline sync (when no diffs are available) did not properly fetch and store list property items. The baseline fetch now correctly detects list metadata from the remote peer and fetches the actual list items via ActingWeb protocol, transforming them to the format expected by ``RemotePeerStore``.

  - Added ``SubscriptionManager._transform_baseline_list_properties()`` method to fetch list items from remote peer
  - Updated ``RemotePeerStore.apply_resync_data()`` to support flag-based list format (``{"_list": true, "items": [...]}``)
  - Maintains backward compatibility with legacy ``"list:"`` prefix format
  - Permission filtering happens automatically via remote peer's property hooks
  - Graceful error handling: skips lists on fetch errors without crashing sync

v3.9.2: Jan 16, 2026
--------------------

ADDED
~~~~~

- **Synchronous Subscription Callbacks**: Added ``with_sync_callbacks()`` builder method and ``sync_subscription_callbacks`` config option for Lambda/serverless environments. When enabled, subscription callbacks use blocking HTTP requests instead of async fire-and-forget, ensuring callbacks complete before the request handler returns. This prevents callbacks from being lost when Lambda functions freeze after returning a response.

  - New builder method: ``ActingWebApp.with_sync_callbacks(enable=True)``
  - New config attribute: ``Config.sync_subscription_callbacks`` (default: ``False``)
  - Refactored ``Actor.callback_subscription()`` to use shared sync helper function
  - Improved logging with sequence numbers and peer IDs for callback debugging

- **Subscription Sequence in GET Response**: Added ``sequence`` field to GET subscription response (``/subscriptions/<peerid>/<subid>``). The subscription's current sequence number is now included at the top level of the response, allowing peers to detect gaps in received diffs without examining individual diff sequence numbers. Updated ActingWeb Specification to version 1.4.

FIXED
~~~~~

- **Network Exception Handling in Trust Creation**: Fixed ``get_peer_info()`` to catch network-related exceptions (``ConnectionError``, ``Timeout``, etc.) that were previously uncaught. This prevents HTTP 500 errors during trust relationship creation when the peer is temporarily unavailable or slow to respond. The function now returns a proper 500 status code instead of crashing.

IMPROVED
~~~~~~~~

- **Retry Logic for Peer Communication**: Added automatic retry with exponential backoff to ``get_peer_info()``. Network requests now retry up to 3 times with delays of 0.5s, 1s, and 2s on transient network failures. This significantly improves reliability when peers are briefly unavailable or slow to respond.

- **Test Fixture Reliability**: Improved test server startup detection with faster polling (0.5s vs 1s) and added warmup requests after servers are detected as ready. This helps prevent race conditions in parallel test execution where the first real request might hit before internal initialization is complete.

v3.9.1: Jan 15, 2026
--------------------

FIXED
~~~~~

- **Async Hooks in Sync Execution Methods**: Fixed ``execute_lifecycle_hooks()``, ``execute_callback_hooks()``, ``execute_property_hooks()``, ``execute_subscription_hooks()``, and ``execute_app_callback_hooks()`` to properly execute async hooks when called from synchronous contexts. Previously, async hooks registered for these hook types would return unawaited coroutines instead of executing. Now all sync execution methods use ``_execute_hook_in_sync_context()`` to correctly handle both sync and async hooks via ``asyncio.run()`` fallback.

v3.9.0: Jan 15, 2026
--------------------

ADDED
~~~~~

- **Property Lookup Tables**: Added dedicated lookup tables for property reverse lookups (``get_actor_id_from_property()``), removing DynamoDB GSI 2048-byte size limit. Supports unlimited property value sizes for indexed properties in both DynamoDB and PostgreSQL backends.

  - Configurable indexed properties via ``with_indexed_properties()`` (default: ``oauthId``, ``email``, ``externalUserId``)
  - Dual-mode operation: new lookup table or legacy GSI/index
  - Backward compatible: defaults to legacy mode (``use_lookup_table=false``)
  - Environment variables: ``USE_PROPERTY_LOOKUP_TABLE``, ``INDEXED_PROPERTIES``
  - Automatic cleanup: lookup entries deleted with properties/actors
  - PostgreSQL foreign key CASCADE for automatic orphan cleanup

- ``actingweb.db.dynamodb.property_lookup`` module with ``PropertyLookup`` model and ``DbPropertyLookup`` class
- ``actingweb.db.postgresql.property_lookup`` module with ``DbPropertyLookup`` class
- ``actingweb.interface.ActingWebApp.with_indexed_properties()`` builder method for configuration
- ``actingweb.interface.ActingWebApp.with_legacy_property_index()`` builder method to control mode
- PostgreSQL migration ``70d60420526_add_property_lookup_table.py`` for lookup table schema
- Comprehensive test suite (``tests/test_property_lookup.py``) with 26 tests for both backends
- Documentation in ``docs/quickstart/configuration.rst`` with migration guide and best practices

- **Native Async/Await Hook Support**: ActingWeb hooks now support both synchronous and asynchronous (async/await) function definitions with automatic detection

  - New async execution methods: ``execute_method_hooks_async()``, ``execute_action_hooks_async()``, ``execute_property_hooks_async()``, ``execute_callback_hooks_async()``, ``execute_app_callback_hooks_async()``, ``execute_subscription_hooks_async()``, and ``execute_lifecycle_hooks_async()``
  - Async handler variants: ``AsyncMethodsHandler`` and ``AsyncActionsHandler`` with ``*_async()`` method variants (``get_async()``, ``post_async()``, ``put_async()``, ``delete_async()``)
  - FastAPI integration automatically detects and uses async handlers for optimal performance without thread pool overhead
  - Backward compatible: Existing synchronous hooks continue to work without changes
  - Mixed support: Applications can use both sync and async hooks in the same application
  - Sync context support: Async hooks are executed via ``asyncio.run()`` when called from synchronous contexts (Flask)
  - Use ``async def`` for hooks that need to call async services (AWS Bedrock, async HTTP clients, async database operations, AwProxy async methods)

CHANGED
~~~~~~~

- ``DbProperty.get_actor_id_from_property()`` now uses lookup table when configured, falling back to legacy GSI/index
- ``DbProperty.set()`` now syncs lookup entries for indexed properties
- ``DbProperty.delete()`` now removes lookup entries for indexed properties
- ``DbPropertyList.delete()`` now cleans up all lookup entries when deleting actor properties
- FastAPI integration now preferentially uses async handler variants (``AsyncMethodsHandler``, ``AsyncActionsHandler``) for methods and actions endpoints
- Synchronous hook execution methods (``execute_*_hooks()``) now support async hooks via ``asyncio.run()`` fallback
- Handler factory (``get_handler_class()``) now supports creating async handler variants based on framework preference

v3.8.3: Jan 12, 2026
--------------------

FIXED
~~~~~

- Fixed Flask integration ``TypeError`` in cookie handling by extracting cookie name as positional argument instead of kwarg
- Fixed missing subscription callbacks when deleting properties via WWW handler with ``?_method=DELETE``
- Fixed trust relationship timestamps to always include timezone info in ISO format strings (both DynamoDB and PostgreSQL)
- Fixed property list metadata to avoid auto-saving default metadata on first access

ADDED
~~~~~

- **Rich Metadata for Methods/Actions**: ``GET /<actor_id>/methods`` and ``GET /<actor_id>/actions`` now return metadata (description, input/output schemas, annotations) with auto-generation from TypedDict type hints

CHANGED
~~~~~~~

- Enhanced OAuth2 refresh token reuse handling with three-tier grace period (0-10s: full rotation, 10-60s: access token only, >60s: revoke all)

v3.8.2: Jan 3, 2026
--------------------

FIXED
~~~~~

- **Trust Deletion Error Handling**: Enhanced DELETE handler to return 404 when the remote actor doesn't exist (not just when relationship doesn't exist), enabling complete cleanup of orphaned trust relationships during ``delete_reciprocal_trust()`` flow when the remote actor has been deleted
- **OAuth Refresh Token Race Condition**: Fixed race condition in refresh token rotation that could cause false token theft detection and forced re-login when concurrent requests use the same refresh token. The check-and-mark-as-used operation is now atomic using database-level compare-and-swap, preventing multiple requests from successfully using the same token

ADDED
~~~~~

- **Atomic Attribute Updates**: Added ``conditional_update_attr()`` method to both DynamoDB and PostgreSQL backends for atomic compare-and-swap operations, enabling race-free token rotation and other concurrent update scenarios
- **Atomic Token Marking**: Added ``try_mark_refresh_token_used()`` method in ``OAuth2SessionManager`` that atomically checks and marks refresh tokens as used in a single database operation

v3.8.1: Jan 2, 2026
--------------------

FIXED
~~~~~

- **Subscription Cache Invalidation**: Fixed subscription handler to invalidate ``subs_list`` cache after creating new subscription, ensuring ``register_diffs()`` immediately sees newly created subscriptions for callback delivery
- **Trust Deletion Error Handling**: Fixed DELETE handler for trust relationships to return 404 (instead of 403) when relationship doesn't exist, enabling proper cleanup of orphaned trust relationships during ``delete_reciprocal_trust()`` flow
- **PostgreSQL Backend**: Fixed SQL queries to quote ``desc`` column as reserved keyword (PostgreSQL compatibility)
- **PostgreSQL Backend**: Fixed ``Attributes`` class to handle None values from PostgreSQL for non-existent attribute buckets
- **Database Backend Abstraction**: Removed hardcoded DynamoDB imports in ``TrustManager`` and ``PermissionEvaluator`` to use configured database backend dynamically
- **Test Fixtures**: Fixed ``test_trust_manager_oauth`` mock to properly structure ``DbTrust`` module for compatibility with backend abstraction

ADDED
~~~~~

- **Migration Helper**: Added ``scripts/migrate_db.py`` helper script for simplified PostgreSQL migrations with automatic .env loading and environment validation

CHANGED
~~~~~~~

- **Documentation**: Enhanced PostgreSQL setup documentation in quickstart guides with migration helper script usage, troubleshooting guide, and step-by-step setup instructions
- **TODO**: Added task for implementing ``TrustManager.create_relationship_async()`` method to avoid blocking event loop in async contexts


v3.8.0: Dec 31, 2025
--------------------

CHANGED
~~~~~~~

- **Database Package Structure**: Refactored ``actingweb.db_dynamodb`` to hierarchical package structure ``actingweb.db.dynamodb`` for better organization
- **Installation Extras**: Added optional dependency groups - ``pip install 'actingweb[postgresql]'`` or ``'actingweb[dynamodb]'`` for backend-specific installations
- **Database Backend Selection**: Environment variable ``DATABASE_BACKEND`` (or ``database`` parameter in ``ActingWebApp()``) now supports ``"dynamodb"`` (default) or ``"postgresql"``
- **Documentation Overhaul**: Comprehensive updates across all user-facing documentation:
  - Updated quickstart guides to include PostgreSQL setup instructions
  - Enhanced configuration reference with backend comparison tables
  - Expanded database maintenance guide to cover both DynamoDB TTL and PostgreSQL pg_cron cleanup
  - Added backend selection guidance throughout documentation
- **Logging Architecture**: Implemented hierarchical logging with named loggers throughout codebase using ``__name__`` pattern
- **Logging Configuration**: Added centralized logging configuration with ``configure_actingweb_logging()`` helper functions
- **Log Levels**: Rebalanced log levels - significant operations (actor creation, trust deletion, etc.) now use INFO instead of DEBUG

ADDED
~~~~~

- **PostgreSQL Database Backend**: Full PostgreSQL support as an alternative to DynamoDB
- ``actingweb.db.postgresql`` package with all 7 database tables (Actor, Property, Trust, PeerTrustee, Subscription, SubscriptionDiff, Attribute)
- PostgreSQL connection pooling via psycopg3 with configurable pool sizes
- Alembic migrations for PostgreSQL schema management (``actingweb/db/postgresql/migrations/``)
- Database backend protocols (``actingweb.db.protocols``) for interface consistency across backends
- Protocol compliance tests to ensure both backends implement the same interface
- ``scripts/migrate_dynamodb_to_postgresql.py`` - Data migration tool with export, import, and validate operations
- Performance benchmarks (``tests/performance/``) for comparing backend performance
- Comprehensive PostgreSQL documentation:
  - ``docs/guides/postgresql-migration.md`` - Complete migration guide from DynamoDB to PostgreSQL
  - ``docs/reference/database-backends.rst`` - Detailed backend comparison, cost analysis, and recommendations
- GitHub Actions matrix testing for both DynamoDB and PostgreSQL backends
- Backend-specific pytest markers (``@pytest.mark.dynamodb``, ``@pytest.mark.postgresql``)
- ``actingweb.logging_config`` module with production/development/testing configuration helpers
- Performance-critical logger identification for production optimization
- Lazy log evaluation in hot paths for improved performance
- **ActorInterface.config property**: Direct access to ActingWeb configuration object from ``ActorInterface`` instances
- **Trust Lifecycle Hooks**: Added ``trust_initiated`` hook - fires when actor initiates trust request to peer (outgoing)
- **Trust Lifecycle Hooks**: Added ``trust_request_received`` hook - fires when actor receives trust request from peer (incoming)
- **Trust Lifecycle Hooks**: Added ``trust_fully_approved_local`` hook - fires when THIS actor approves, completing mutual trust
- **Trust Lifecycle Hooks**: Added ``trust_fully_approved_remote`` hook - fires when PEER actor approves, completing mutual trust

FIXED
~~~~~

- Database module import paths corrected from relative to absolute imports

v3.7.6: Dec 30, 2025
--------------------

FIXED
~~~~~

- **Subscription Filtering**: Fixed ``get_subscriptions()`` callback parameter to properly filter by callback flag - ``callback=None`` now returns all subscriptions, ``callback=False`` returns inbound subscriptions, ``callback=True`` returns outbound subscriptions
- **Trust Deletion Hook**: Enhanced ``trust_deleted`` lifecycle hook to include ``relationship`` and ``trust_data`` parameters for consistency with ``trust_approved`` hook

CHANGED
~~~~~~~

- Added documentation to ``get_subscriptions()`` method explaining parameter filtering behavior

v3.7.5: Dec 27, 2025
--------------------

ADDED
~~~~~

- **Actor Root Content Negotiation**: ``GET /<actor_id>`` now supports content negotiation - API clients receive JSON, browsers are redirected based on authentication status and ``with_web_ui()`` configuration.
- **Browser Redirect to /login**: Unauthenticated browser requests to ``/<actor_id>`` now redirect to ``/login`` for a consistent login experience instead of triggering OAuth directly.
- **SPA Redirect Support**: When ``with_web_ui(False)``, authenticated browsers and OAuth callbacks redirect to ``/<actor_id>/app`` instead of ``/<actor_id>/www``.
- Integration tests for actor root endpoint content negotiation and redirect behavior.

CHANGED
~~~~~~~

- OAuth2 callback handler now respects ``config.ui`` setting - redirects to ``/<actor_id>/app`` when web UI is disabled (SPA mode).
- FastAPI and Flask integrations updated to redirect unauthenticated browser requests to ``/login``.
- Documentation extensively updated: routing-overview, web-ui guide, spa-authentication guide, and configuration reference now document browser redirect behavior.

v3.7.4: Dec 26, 2025
--------------------

ADDED
~~~~~

- DynamoDB TTL support for automatic cleanup of expired tokens, sessions, and auth codes.

v3.7.3: Dec 19, 2025
--------------------

FIXED
~~~~~

- **WWW Callback Hook Template Rendering**: The ``www`` callback hook can now render custom templates by returning ``{"template": "template-name.html", "data": {...}}``. This allows applications to add custom web UI pages without modifying the core library.
- **Callbacks Handler Response Data**: GET, POST, and DELETE callback handlers now return the hook's response data as JSON (200 OK) instead of just boolean success/failure, enabling richer callback interactions.
- **Methods/Actions ACL Rules**: Added default ACL rules for ``/methods`` and ``/actions`` endpoints for creator, friend, partner, and admin trust types.
- Added ``template_name`` attribute to ``AWResponse`` for custom template rendering support.
- Fixed methods and actions handlers to use dual-context authentication (``_authenticate_dual_context``) supporting both web UI (OAuth cookie) and API (basic auth) access.

ADDED
~~~~~

- Added integration tests for custom www template rendering via callback hooks.
- Added integration tests for OAuth2 logout SPA CORS behavior (origin echoing and credentials).

CHANGED
~~~~~~~

- **OAuth2 Logout Consolidation**: ``/oauth/spa/logout`` now delegates to the main ``/oauth/logout`` handler for consistent behavior. The logout endpoint uses SPA CORS (echoed origin + credentials) to ensure cross-origin SPAs can clear session cookies. Both Flask and FastAPI integrations now properly propagate cookies from handler responses.
- Callbacks handler now returns actual hook results as JSON response body instead of just HTTP status codes.
- Documentation updated with template rendering examples for www callback hooks.

v3.7.2: Dec 19, 2025
--------------------

FIXED
~~~~~

- Fixed Flask integration cookie handling: added ``path`` and ``samesite`` parameters for proper session cookie behavior across browser security policies
- Simplified Flask OAuth session validation to use session manager directly instead of OAuth2 authenticator, fixing token validation issues
- Improved Flask template rendering error logging for easier debugging

CHANGED
~~~~~~~

- Added thoughts/shared/plans/2025-12-18-passphrase-login-feature.md as a way to support www login without a 3rd party auth provider

v3.7.1: Dec 18, 2025
--------------------

FIXED
~~~~~

- **SECURITY**: Permission override merging now uses union semantics for both ``patterns`` AND ``excluded_patterns`` arrays by default - base security exclusions (private/*, security/*, oauth_*) can no longer be accidentally cleared by individual trust relationship overrides
- Cleaned up integration/unit tests to have all dynamodb-dependent tests in integration dir

v3.7.0: Dec 16, 2025
--------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- **Developer API Extended**: SubscriptionManager and TrustManager have new methods with cleaner APIs and automatic lifecycle hooks
- See ``docs/migration/v3.7.rst`` for comprehensive migration guide
- **HTTP API remains 100% backward compatible** - no changes required for applications using REST endpoints only

FIXED
~~~~~

- **SECURITY**: Permission evaluator now returns DENIED (not NOT_FOUND) when explicit patterns are defined but target doesn't match - fixes permission bypass via legacy ACL fallback
- **SECURITY**: Properties ``listall`` endpoint now filters properties and list properties based on peer permissions - prevents unauthorized data exposure
- Properties ``listall`` now includes list properties even when all regular properties are filtered by permissions
- Subscription callbacks now fire asynchronously in async contexts to avoid blocking the caller
- Fixed permission filtering for property lists to strip 'list:' prefix before permission checks
- Property list diff notifications now include item data (item, index, items) for subscribers
- Add trigger of oauth_success hook in SPA oauth2 login
- Fixed unused variable and import warnings identified by ruff linting
- Fixed ``hasattr(x, '__call__')`` pattern replaced with ``callable(x)`` for better type safety

ADDED
~~~~~

- **Permission Merge Control**: Added ``merge_base`` parameter to ``merge_permissions()`` function - defaults to ``True`` for fail-safe union merging of patterns/excluded_patterns; set to ``False`` for explicit full override capability
- **Developer API Extensions**: Added methods to SubscriptionManager: ``create_local_subscription()``, ``get_subscription_with_diffs()``, ``get_callback_subscription()``, ``delete_callback_subscription()``
- **Developer API Extensions**: Added methods to TrustManager: ``create_verified_trust()``, ``modify_and_notify()``, ``delete_peer_trust()``, ``trustee_root`` property
- **Wrapper Classes**: Added ``SubscriptionWithDiffs`` wrapper providing clean access to subscription data and diffs
- **Async Authentication**: Added async versions of authentication methods (``check_token_auth_async()``, ``check_and_verify_auth_async()``) to avoid blocking event loop during OAuth2 validation
- **OAuth2 Token Heuristic**: Added ``Auth._looks_like_oauth2_token()`` method to avoid unnecessary network calls for non-OAuth tokens
- **List Property Subscriptions**: List property operations now trigger subscription notifications with structured diff payloads
- **Parallel Test Execution**: Added pytest-xdist support with worker isolation (unique DB prefixes, ports, emails) for 3-4x faster test runs
- Added Makefile targets: ``make test-parallel``, ``make test-parallel-fast``, ``make test-all-parallel``
- Added ``pytest-xdist`` dependency for parallel test execution
- GitHub Actions CI now runs tests in parallel with 4 workers
- oauth_success hook now receives full OAuth user info

CHANGED
~~~~~~~

- **Permission Merge Documentation**: Added "Permission Override Merging" section to ``docs/guides/access-control.rst`` and updated ``docs/reference/security.rst`` cheatsheet
- **Architecture**: Handlers refactored to four-tier architecture (Handler → Developer API → Core Actor → Database) for clean separation of concerns
- **Handler Simplification**: Handlers are now thin HTTP adapters delegating business logic to developer API
- OAuth2 token validation now includes quick heuristic check before network requests for better performance
- Integration tests now support parallel execution with automatic worker isolation
- GitHub Actions workflow uses parallel testing (4 workers for public repos, 2 for private)
- Added timeout-minutes to GitHub Actions jobs (20 min tests, 10 min type-check)
- Documentation consolidated into CONTRIBUTING.rst and CLAUDE.md

v3.6.0: Dec 11, 2025
--------------------

FIXED
~~~~~~~

- Trust ``trust_approved`` lifecycle hook now triggers when receiving POST approval notification from peer (moved from PUT handler to POST handler)
- Fixed race condition in trust approval flow where trust relationship must be saved to database before notifying the peer.
- Fixed missing deletion of permissions for trust relationship when deleting it.
- Fixed missing ``trust_deleted`` lifecycle hook trigger in trust DELETE handler.

ADDED
~~~~~

- **ACL Rules for Custom Trust Types**: ``add_trust_type()`` now accepts an ``acl_rules`` parameter to specify HTTP endpoint access permissions. This enables custom trust types (like ``subscriber``) to access ActingWeb REST endpoints like ``/subscriptions/<id>`` for creating subscriptions. Each rule is a tuple of ``(path, methods, access)``.
- **SECURITY**: Subscription callbacks now respect property permissions - only properties the peer has ``read`` permission on are included in callbacks (fail-closed design)
- **NEW ENDPOINT**: Added ``/trust/{relationship}/{peerid}/shared_properties`` endpoint for discovering properties available for subscription
- **BREAKING**: Subscription permission filtering is fail-closed - if permission evaluation fails, no data is sent to subscribers

**Note on Subscription Access Control**: Subscription creation is controlled by ACL rules (e.g., ``("subscriptions/<id>", "POST", "a")``), NOT by property permission patterns. Any peer with the subscription ACL can create subscriptions to any target. Property permissions only affect what data is included in subscription callbacks.
- **Async HTTP Methods**: Added async versions of ``AwProxy`` methods using ``httpx`` for non-blocking operations in async frameworks like FastAPI:

  - ``AwProxy.get_resource_async()`` - Async peer resource retrieval
  - ``AwProxy.create_resource_async()`` - Async peer resource creation
  - ``AwProxy.change_resource_async()`` - Async peer resource update
  - ``AwProxy.delete_resource_async()`` - Async peer resource deletion

- **Dependencies**: Added ``httpx`` as a new dependency for async HTTP client operations

CHANGED
~~~~~~~

- Subscription handlers now use unified permission evaluator (``evaluate_property_access``) instead of legacy ``check_authorisation``
- Permission changes made after subscription creation now affect subsequent callbacks (dynamic permission enforcement)
- Actor ``callback_subscription`` method now filters property subscription data based on peer permissions before sending

v3.5.6: Dec 4, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Fixed token revocation searching wrong actor bucket during trust deletion - tokens were stored in user's actor but revocation looked in system actor (``_actingweb_oauth2``), leaving tokens valid after trust deletion

v3.5.5: Dec 3, 2025
-------------------

FIXED
~~~~~

- Fixed Flask and FastAPI integrations not propagating handler headers (e.g., WWW-Authenticate) to OAuth2 endpoint responses

v3.5.4: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Trust relationship deletion now properly deletes the associated OAuth2 client and revokes all tokens - prevents deleted MCP clients from being reused after trust relationship is removed

v3.5.3: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: MCP client deletion now immediately revokes all access and refresh tokens - prevents deleted clients from continuing to access resources using cached tokens

v3.5.2: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Fixed missing WWW-Authenticate header for 401 responses in OAuth2 token endpoint - RFC 6749 Section 5.2 requires WWW-Authenticate header for invalid_client errors

v3.5.1: Dec 1, 2025
-------------------

FIXED
~~~~~

- **CRITICAL**: Fixed OAuth2 actor creation not triggering lifecycle hooks - ``config._hooks`` was never set, causing ``actor_created`` and other lifecycle hooks to be silently ignored during OAuth-based actor creation
- Added comprehensive regression tests for OAuth2 lifecycle hook integration

CHANGED
~~~~~~~

- ActingWebApp now automatically attaches HookRegistry to Config object's ``_hooks`` attribute in ``get_config()``

v3.5: Nov 30, 2025
------------------

**ActingWeb Specification version 1.2**

This release implements ActingWeb Specification version 1.2 with SPA-friendly API behavior.

FIXED
~~~~~

- **SECURITY**: Fixed SPA PKCE code challenge not being sent to OAuth providers - PKCE parameters are now properly forwarded to authorization URLs
- **SECURITY**: Fixed trust-based permissions bypass - handlers were using ``getattr()`` on dict instead of ``.get()`` for peer ID lookup, causing permission evaluator to be bypassed
- Fixed FastAPI cookie setting using ``key`` parameter instead of ``name`` (FastAPI/Starlette API difference)
- Fixed SPA refresh token cookie not being stored by browser (changed ``path="/"`` and ``samesite="Lax"``)
- Fixed refresh token reuse false positives on rapid page refresh with 2-second grace period
- Fixed ``oauth_state.decode_state()`` to handle JSON null values for optional trust_type field
- Removed sensitive token values from debug log messages (security improvement)
- Fixed pytest marker registration for integration tests (added ``integration`` marker)

CHANGED
~~~~~~~

- SPA OAuth2 authorize endpoint only includes ``trust_type`` in state when provided (distinguishes user login from MCP client auth)

BREAKING CHANGES
~~~~~~~~~~~~~~~~

**Empty Collection Response Behavior (Spec v1.2)**

The following endpoints now return ``200 OK`` with empty arrays/objects instead of ``404 Not Found``
when collections are empty. This is a **breaking change** for clients that rely on ``404`` to detect
empty collections:

- ``GET /trust`` - Returns ``200 OK`` with ``[]`` when no trust relationships exist (was ``404``)
- ``GET /trust?relationship=<type>`` - Returns ``200 OK`` with ``[]`` when no matches (was ``404``)
- ``GET /properties`` - Returns ``200 OK`` with ``{}`` when no properties exist (was ``404``)
- ``GET /subscriptions`` - Returns ``200 OK`` with ``{"id": ..., "data": []}`` when no subscriptions (was ``404``)

**Migration Guide:**

Before (v1.1):

.. code-block:: python

    response = requests.get(f"{actor_url}/trust", auth=auth)
    if response.status_code == 404:
        trusts = []  # No trusts
    else:
        trusts = response.json()

After (v1.2):

.. code-block:: python

    response = requests.get(f"{actor_url}/trust", auth=auth)
    trusts = response.json()  # Always returns array (may be empty)

**Note:** Individual resource lookups still return ``404 Not Found`` when the specific resource
does not exist (e.g., ``GET /properties/nonexistent``, ``GET /trust/friend/nonexistent-peer``).

DOCS
~~~~

- **Spec v1.2**: Added "Response Conventions" section documenting SPA-friendly empty collection behavior
- **Spec v1.2**: Updated ``/properties``, ``/trust``, and list properties sections with new 200 OK behavior
- Added ``listproperties`` option tag to ActingWeb specification for list property support
- Added comprehensive List Properties section to ``docs/actingweb-spec.rst`` documenting ordered collections
- Documented list property CRUD operations (GET/POST/PUT/DELETE) for items and full lists
- Documented list property metadata endpoint (GET/PUT ``/properties/{name}/metadata``)
- Updated GET ``/properties?metadata=true`` documentation to reference listproperties option tag

ADDED
~~~~~

- SPA mode support in OAuth2 callback handler (``spa_mode=true`` in state parameter returns JSON instead of redirect)
- JSON API responses in email verification handler (based on ``Accept: application/json`` header)
- ``GET /{actor_id}/meta/trusttypes`` endpoint for trust type enumeration
- ``GET/PUT /{actor_id}/properties/{name}/metadata`` endpoint for list property metadata
- Factory JSON API: ``GET /?format=json`` or ``Accept: application/json`` returns OAuth configuration for SPAs
- New test suites for SPA API endpoints (``tests/test_spa_api_endpoints.py``, ``tests/integration/test_spa_api.py``)

CHANGED
~~~~~~~

**Trust Type Configuration Clarification**

Trust types are now correctly scoped to MCP client authorization flows only:

- Trust types are **no longer** exposed in user login endpoints (``GET /?format=json``, ``/oauth/spa/*``)
- Library no longer hardcodes default trust types (e.g., ``mcp_client``)
- Applications must configure trust types for MCP OAuth2 flows via ``AccessControlConfig.configure_oauth2_trust_types()``
- ``/oauth/authorize`` (MCP authorization) shows trust types from registry; ``/oauth/spa/authorize`` (user login) does not

This change clarifies the distinction between:

1. **User Login** (ActingWeb as OAuth client to Google/GitHub): No trust relationship created, no trust_type needed
2. **MCP Authorization** (ActingWeb as OAuth server for MCP clients): Trust relationship created with specified trust_type

**Security Enhancement**

- Added explicit validation in OAuth2 callback to prevent actor spoofing (validates OAuth email matches actor creator)
- MCP OAuth2 flows derive actor_id from authenticated email, not user input

FIXED
~~~~~

- Fixed unit test configuration to use correct DynamoDB port (8001) matching docker-compose.test.yml
- Fixed Trust class attribute initialization to prevent AttributeError on early returns

v3.4.3: Nov 23, 2025
--------------------

FIXED
~~~~~

- Fixed MCP authentication to include error="invalid_token" in WWW-Authenticate header per RFC 6750 to force OAuth2 clients to invalidate cached tokens
- Fixed Flask and FastAPI integrations to properly propagate HTTP 401 status codes and WWW-Authenticate headers from MCP handler
- Reduced excessive debug logging in MCP trust relationship lookup
- Added conditional update check to prevent unnecessary trust relationship updates when client info hasn't changed

v3.4.2: Nov 22, 2025
--------------------

ADDED
~~~~~

- Github action to push new package to pypi on merging PRs to master branch

FIXED
~~~~~

- Fixed wrong URL in OAUTH2 discovery URL that prevented detection of dynamic client registration

CHANGED
~~~~~~~

- Reduced unnecessary error logging for access and authentication
- Ruff linting and formatting and pyright type fixes

v3.4.1: Nov 8, 2025
-------------------

FIXED
~~~~~

**MCP Tool Annotations**

- Fixed tool annotations not being serialized in ``tools/list`` responses in MCP handler
- Tool annotations (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``, ``openWorldHint``) are now properly included when decorators define them
- This fix enables ChatGPT and other MCP clients to properly evaluate tool safety before execution
- Aligns FastAPI/HTTP integration path with SDK server behavior

**OAuth2 Trust Type Selection**

- Fixed OAuth2 authorization form ignoring user-selected trust type during Google/GitHub authentication
- OAuth provider buttons now submit form to ``/oauth/authorize`` POST with selected trust_type before redirecting to provider
- Trust type is properly embedded in encrypted OAuth state and applied during callback
- Fixes regression introduced when OAuth provider integration was added (previously worked with email form submission)

v3.4: Oct 26, 2025
-------------------

ADDED
~~~~~

**OAuth2 Security Enhancements**

- Added email verification system for OAuth2 actors when provider cannot verify email ownership
- Added cross-actor authorization prevention in MCP OAuth2 flows (blocks attackers from authorizing access to other users' actors)
- Added session fixation prevention in web OAuth2 login flows
- Added comprehensive security documentation in ``docs/authentication-system.rst``
- Added security tests in ``tests/integration/test_oauth2_security.py``
- Added lifecycle hooks: ``email_verification_required`` and ``email_verified``
- Added email verification endpoint: ``/<actor_id>/www/verify_email``
- Added verified emails dropdown for GitHub OAuth2 (fetches verified emails via GitHub API)
- Added provider ID support (stable identifiers like ``google:sub`` or ``github:user_id``) as alternative to email addresses
- Added 32-byte cryptographic verification tokens with 24-hour expiry
- Added security logging for all authorization violations

**Trust Relationship Enhancements**

- Added ``last_accessed`` and ``last_connected_via`` fields to trust relationships for tracking connection activity
- Handler now updates trust relationship timestamps on each connection with client metadata refresh
- Trust relationship sorting by most recent connection in web UI (``/www/trust``)

FIXED
~~~~~

**Security Fixes**

- **CRITICAL**: Fixed OAuth2 callback to validate actor ownership before completing authorization (prevents cross-actor authorization attacks in MCP flows)
- Fixed potential account hijacking vulnerability when OAuth2 providers don't return verified email addresses
- Fixed session fixation vulnerability where attackers could trick users into logging into attacker's actor

**OAuth2 and Integration Fixes**

- Fixed OAuth2 CORS preflight (OPTIONS) requests not being routed correctly in FastAPI integration, causing 404 errors on ``/oauth/register`` and ``/oauth/token`` endpoints

CHANGED
~~~~~~~

**Code Quality & Type Safety**

- **Type Checking**: Achieved zero pyright errors and warnings across entire codebase (down from 430+ issues)
- **Linting**: Achieved zero ruff errors (fixed all 15 remaining linting issues)
- **Configuration**: Added pyright to dev dependencies and created ``pyrightconfig.json`` for consistent type checking
- **VSCode Integration**: Updated ``.vscode/settings.json`` for optimal pylance and ruff integration
- **Test Improvements**: Fixed pytest fixture names causing test failures, all 474 tests now passing
- **Type Annotations**: Added comprehensive type ignore comments for test files (228+ annotations)
- **Import Management**: Fixed unused imports, variables, and function warnings throughout codebase
- **Module Declarations**: Fixed lazy-loaded module ``__all__`` declarations with proper pyright ignores (34 modules)

- **Dependencies**: Updated Poetry to 2.2.1 and major package upgrades including ``cryptography`` 45.0.6 → 46.0.3, ``fastapi`` 0.116.1 → 0.120.0, ``mcp`` 1.12.4 → 1.19.0, ``pydantic`` 2.11.7 → 2.12.3, ``pytest-cov`` 6.2.1 → 7.0.0, ``ruff`` 0.12.8 → 0.14.2, and 30+ other dependency updates


v3.3: Oct 4, 2025
-----------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

**Legacy OAuth System Removed**

- Removed legacy ``OAuth`` class and related third-party service authentication
- Removed ``/<actor_id>/oauth`` endpoints that used legacy OAuth
- Removed legacy OAuth methods from ``Auth`` class (``oauth_get``, ``oauth_post``, etc.)
- Legacy OAuth auth type no longer supported in ``select_auth_type()``

**Migration Path**: Use the new unified third-party service integration system instead:

- Replace ``oauth.OAuth()`` with ``actor.services.get("service_name")``
- Replace manual OAuth configuration with ``app.add_dropbox()``, ``app.add_gmail()``, etc.
- Use clean service API: ``service.get()``, ``service.post()``, etc.

FIXED
~~~~~

- MCP tools/list response now applies client-specific formatting for better compatibility
- Trust relationship descriptions now show friendly client names instead of raw identifiers when available
- OAuth2 client trust relationships maintain proper client metadata across updates
- Trust manager now keeps peer identifier in sync for OAuth2/MCP clients
- Fixed FastAPI extra inadvertently importing Flask, forcing Flask as a dependency
- Fixed trust handler to return empty list instead of 404 for graceful handling
- Reduced logging noise by moving non-essential INFO logs to DEBUG
- Made ``actor.get_config()`` use the dynamic global ``actingweb.__version__``
- Fixed error in ``DbPropertyList`` when properties table was missing in DynamoDB
- Fixed ``trustee_root`` JSON to return stored value instead of input parameter
- Fixed missing ``trustee_root`` in actor creation via REST API
- Fixed handling of ``POST`` to ``/<actor_id>/www/properties`` (including ``_method=DELETE``)
- Fixed base path handling for ``/<actor_id>/www`` (supports non-root base paths consistently)
- Fixed ``www/`` hook not triggered
- Devtest proxy: added Basic-auth fallback (``trustee:<peer passphrase>``) when Bearer trust requests to peer ``/properties`` endpoints receive 302/401/403, avoiding OAuth2 redirects during testing
- Fixed MCP OAuth2 trust relationship creation where MCP clients completed authentication but no trust relationships were created
- Fixed hook permission operation mapping where "get" operations were incorrectly passed as "read"
- Fixed OAuth2 callback ``established_via`` to properly distinguish between MCP and regular OAuth2 flows
- Fixed singleton initialization dependency order causing Permission Evaluator to fail when Trust Permission Store was not yet initialized
- Fixed OAuth2 trust-type filtering logic that was incorrectly placed inside exception handlers, causing 0 available trust types during OAuth2 flows
- Fixed severe OAuth2 performance issue where lazy singleton loading during requests caused 4+ minute hangs during OAuth2 callbacks
- Fixed ``established_via`` field being lost between database save and retrieval in trust relationship management
- Added explicit singleton initialization at application startup to prevent performance degradation during OAuth2 flows
- Replaced all urlfetch HTTP calls with requests library for improved reliability, better timeout handling, and elimination of 30+ second timeout issues

CHANGED
~~~~~~~

- If ``unique_creator=False``, ensure deterministic retrieval of the first actor available when doing OAuth2 auth and log in from root
- Refactored OAuth2 server implementation to use Attributes system instead of underscore-prefixed properties for storing sensitive data (tokens, authorization codes, Google OAuth2 tokens)
- Removed unused default resources in the MCP server (now only existing resources and hooks are presented)
- Removed notes and usage as static resource in the library, leave this to the implementing application
- Cleaned up the actor creation interfaces, ActorInterface.create() is now the only factory to be used.
- Standardized global Attribute buckets for cross-actor data.
- Enhanced ``/trust/{relationship}/{peerid}`` API endpoints to support permission management alongside traditional trust relationship operations
- Modified ``/meta/actingweb/supported`` to dynamically include feature tags based on available system capabilities
- Properties, methods, and actions handlers now integrate with unified permission system while maintaining backward compatibility
- Hook execution system now includes transparent permission checking with authentication context passing
- **Dependencies**: Replaced ``urlfetch ^2.0.1`` with ``requests ^2.31.0`` for more reliable HTTP operations

ADDED
~~~~~

**Integration Test Suite**

- Added comprehensive REST API integration test suite with 117 tests covering all mandatory ActingWeb protocol endpoints
- Added ``tests/integration/`` directory with test harness, fixtures, and test files
- Added Docker Compose configuration for local DynamoDB testing (``docker-compose.test.yml``)
- Added GitHub Actions CI/CD workflow (``.github/workflows/integration-tests.yml``) for automated testing on PRs
- Added ``make test-integration`` target for running integration tests locally
- Added comprehensive testing documentation (``docs/TESTING.md``)
- Test coverage: actor lifecycle, properties (nested/complex), meta, trust relationships, subscriptions with diffs

**MCP Client Management Enhancements**

- Support for ``allowed_clients`` parameter in ``@mcp_tool`` decorator to restrict tool access by client type
- Support for ``client_descriptions`` parameter in ``@mcp_tool`` decorator for client-specific tool descriptions
- Client-specific tool filtering for MCP endpoints based on client type detection (ChatGPT, Claude, Cursor, etc.)
- Enhanced OAuth2 client trust relationship display with friendly client names in web UI
- Automatic enrichment of OAuth2 trust relationships with missing client metadata

**Unified Third-Party Service Integration**

- Added modern service integration system replacing legacy OAuth class
- Added fluent API methods: ``app.add_dropbox()``, ``app.add_gmail()``, ``app.add_github()``, ``app.add_box()``
- Added ``ServiceConfig``, ``ServiceClient``, and ``ServiceRegistry`` classes
- Added automatic token management and refresh for third-party services
- Added ``actor.services.get()`` interface for accessing authenticated service clients
- Added service OAuth2 callback endpoints: ``/{actor_id}/services/{service_name}/callback``
- Added service revocation endpoints: ``DELETE /{actor_id}/services/{service_name}``
- Added comprehensive documentation in ``docs/service-integration.rst``
- Integrated service system with both Flask and FastAPI frameworks

**Bot Handler Improvements**

- Fixed broken bot handler that tried to use removed legacy OAuth system
- Simplified bot authentication to use direct bot token validation from config
- Removed dependency on Auth class for bot endpoints - bots now use simpler token-based validation
- Bot token now passed to hooks for service calls if needed

**Simplified Authentication Interface**

- Added ``require_authenticated_actor()`` method to BaseHandler for one-line auth + authorization
- Added ``authenticate_actor()`` method returning ``AuthResult`` for more granular control
- New interface reduces boilerplate from 6-8 lines to 2-3 lines per handler method
- Maintains full compatibility with existing ``init_actingweb()`` usage
- Automatic HTTP response handling for common authentication and authorization failures

**Unified Access Control System**

- Complete unified access control system with trust types, permissions, and pattern matching
- Trust Type Registry with 6 built-in trust types (associate, viewer, friend, partner, admin, mcp_client) and support for custom types
- Permission Evaluator with glob pattern matching, precedence rules, and fallback to legacy authorization
- Per-relationship permission storage system allowing individual trust relationships to override trust type defaults
- Permission Integration module providing transparent permission checking for all ActingWeb operations
- Enhanced Trust API with permission management endpoints:

  - ``GET /trust/{relationship}/{peerid}?permissions=true`` - Include permission overrides in trust response
  - ``PUT /trust/{relationship}/{peerid}`` - Update permissions alongside trust relationship properties
  - ``GET /trust/{relationship}/{peerid}/permissions`` - Dedicated permission management endpoint
  - ``PUT /trust/{relationship}/{peerid}/permissions`` - Create/update permission overrides
  - ``DELETE /trust/{relationship}/{peerid}/permissions`` - Remove permission overrides

- ``trustpermissions`` feature tag automatically included in ``/meta/actingweb/supported`` when permission system is available
- Transparent hook permission checking - existing hooks automatically get permission filtering without code changes
- Enhanced MCP OAuth2 trust relationship creation with automatic trust type detection
- Zero-migration design - existing applications work immediately while gaining new capabilities
- Comprehensive permission structure supporting properties, methods, actions, tools, resources, and prompts
- Pattern-based permissions with support for glob wildcards (``*``, ``?``) and URI schemes
- Backward compatibility with legacy authorization system as fallback

**Other Additions**

- Added execution of property_hooks in the handler of www/*
- Added support for list of hidden properties as variable to www/properties* templates
- Added support for dynamic generation of resources in MCP based on hooks
- Support for CORS in oauth2 flows
- PKCE support in oauth2 flows
- Support for OPTIONS method on OAUTH2 discovery endpoints
- New explicit interface for managing list properties with `actor.property_lists.listname` syntax
- Distributed list storage bypassing DynamoDB 400KB item limits by storing individual list items as separate properties
- Added `property_lists` attribute to Actor class for list-specific operations
- Lazy-loading iterator for efficient list traversal without loading entire lists into memory
- Added singleton warmup module (``actingweb.singleton_warmup``) for explicit initialization of performance-critical singletons at application startup
- Comprehensive documentation for singleton initialization requirements in both CLAUDE.md and unified-access-control.rst
- Intelligent caching system for MCP endpoint authentication providing 50x performance improvement (50ms → 1ms) for repeated requests with 90%+ cache hit rates
- MCP authentication caching includes token validation, actor loading, and trust relationship lookup with automatic TTL-based cleanup and performance monitoring

**OAuth2 Client Management**

- High-level ``OAuth2ClientManager`` interface for creating, listing, validating, deleting clients, and regenerating client secrets
- Client secret regeneration with verification, audit timestamp (``secret_regenerated_at``), and formatted display values
- Generate access tokens via client-credentials flow directly from ``OAuth2ClientManager.generate_access_token()``

**OAuth2 Authorization Server**

- Added support for ``client_credentials`` grant type with token issuance and discovery updated (``grant_types_supported``)
- Added ``trust_type`` and ``actor_id`` to client registration/discovery responses; improved secret validation diagnostics
- Added client deletion capability to MCP client registry

**MCP Integration**

- Captures and caches MCP ``clientInfo`` during initialize; persists to trust relationship after OAuth2 callback
- Populates trust context on authenticated MCP sessions for permission evaluation
- Added Google OAuth2 token validation via Google TokenInfo API
- Enhanced MCP client information capture and persistent storage across session establishment
- Improved MCP authentication with proper HTTP 401 handling and WWW-Authenticate headers for FastAPI integration
- Added global client info caching during session establishment with automatic cleanup
- Each MCP client now gets unique trust relationship per user email, preventing clients from overwriting each other's identities
- OAuth2 client registration now automatically creates trust relationships, ensuring proper permission evaluation
- All OAuth2 clients must pass permission evaluation before accessing MCP endpoints

**Runtime Context System**

- New ``actingweb.runtime_context`` module providing structured request context for hook functions
- ``RuntimeContext`` class with type-safe context classes: ``MCPContext``, ``OAuth2Context``, ``WebContext``
- ``get_client_info_from_context()`` helper function for unified client detection across all context types
- Support for custom context types via ``set_custom_context()`` and ``get_custom_context()`` methods
- Request-scoped context lifecycle with automatic cleanup support
- Comprehensive documentation and examples for using runtime context in hook functions

**Web UI Enhancements**

- Consistent template URL variables across pages: ``actor_root``, ``actor_www``, and ``url``
- Trust page displays registered OAuth2 clients (name, trust type, created time, status)
- Trust creation form supports selecting trust type; consistent ``form_action`` and redirects
- Property pages: create/delete list properties, edit list metadata (description/explanation), and improved redirects after operations

**Auth Utilities**

- Added ``check_and_verify_auth()`` helper to verify authentication for custom (non-ActingWeb) routes with redirect-aware responses

v3.2.1: Aug 9, 2025
-------------------

**OAuth2 Authentication System and Enhanced Integrations**

ADDED
~~~~~

- **OAuth2 Implementation**:
  - New oauth2.py module with comprehensive OAuth2 authentication using oauthlib WebApplicationClient
  - Support for Google and GitHub OAuth2 providers with automatic provider detection
  - OAuth2CallbackHandler for secure callback processing with state parameter validation
  - Email validation system to prevent identity confusion attacks
  - Login hint parameter support for Google OAuth2 to improve user experience
  - State parameter encryption with CSRF protection and email validation

- **MCP OAuth2 Authorization Server**:
  - Complete RFC 7591/RFC 8414 compliant OAuth2 authorization server for MCP (Model Context Protocol) clients
  - Dynamic Client Registration (DCR) endpoint for MCP client registration
  - OAuth2 authorization and token endpoints with proper scope handling
  - Separate token management system for ActingWeb tokens vs Google tokens
  - Per-actor MCP client credential storage using ActingWeb attribute bucket pattern
  - State parameter encryption with MCP context preservation for OAuth2 flows
  - Global index buckets for efficient MCP client lookup across actors
  - Integration with existing Google OAuth2 for user authentication proxying

- **Enhanced Authentication Flow**:
  - Modified factory endpoint behavior: GET shows email form, POST triggers OAuth2 with email hint
  - Email validation step to ensure authenticated email matches form input
  - User-friendly error templates for authentication failures
  - Security enhancement preventing form email != OAuth2 email mismatch attacks
  - Dual OAuth2 callback handling supporting both ActingWeb and MCP flows

- **FastAPI Integration Enhancements**:
  - Improved FastAPI integration with better async/await handling
  - Enhanced template and static file support for FastAPI applications
  - Better separation of GET/POST handling in factory routes
  - Improved error handling and response formatting for FastAPI

- **Integration Improvements**:
  - Enhanced both Flask and FastAPI integrations with OAuth2 callback handling
  - Improved factory route handling with separate GET/POST methods
  - Better template variable population for authentication forms
  - Enhanced error handling across both integrations

CHANGED
~~~~~~~

- **Authentication System**:
  - Factory routes now handle GET and POST separately for better UX
  - Enhanced OAuth callback processing with comprehensive validation
  - Improved state parameter handling with encryption and validation
  - Better error messaging and user guidance for authentication failures

- **Integration Layer**:
  - Updated both Flask and FastAPI integrations to support new OAuth2 flow
  - Enhanced template rendering with better context and error handling
  - Improved factory handler logic with cleaner separation of concerns
  - Better support for custom authentication flows in integrations

- **Dependency Management**:
  - Updated all dependencies to latest stable versions
  - Major version updates: Flask ^2.0.0 → ^3.1.1, Werkzeug ^2.0.0 → ^3.1.3
  - FastAPI ^0.100.0 → ^0.116.1, uvicorn ^0.23.1 → ^0.35.0
  - Core dependencies: boto3 ^1.26.0 → ^1.40.6, urlfetch ^1.0.2 → ^2.0.1, cryptography ^41.0.0 → ^45.0.6
  - Development tools: pytest ^7.0.0 → ^8.4.1, black ^22.0.0 → ^25.1.0, ruff ^0.1.0 → ^0.12.8
  - Documentation: sphinx ^5.0.0 → ^8.2.3, sphinx-rtd-theme ^1.0.0 → ^3.0.2
  - Restructured optional dependencies into independent extras: flask, fastapi, mcp, and all

FIXED
~~~~~

- **Type Safety**:
  - Fixed all pylance/mypy type annotation errors in OAuth2 implementation
  - Enhanced type safety for OAuth2 classes and methods
  - Better null safety checks in authentication flows
  - Improved Union type handling for request bodies

- **Authentication Issues**:
  - Fixed OAuth callback handling edge cases
  - Resolved state parameter validation issues
  - Fixed email validation logic for OAuth2 providers
  - Enhanced error handling in authentication flows

- **Handler Integration Issues**:
  - Fixed critical auth.py bug where handler objects were incorrectly treated as response objects
  - Resolved AttributeError: 'SubscriptionRootHandler' object has no attribute 'write'
  - Resolved AttributeError: 'SubscriptionRootHandler' object has no attribute 'headers'
  - Updated auth.init_actingweb() to properly access appreq.response.write() and appreq.response.headers
  - Added defensive checks for response object availability in authentication flows

- **DynamoDB Storage Issues**:
  - Fixed DynamoDB ValidationException for authorization codes exceeding 2KB index key size limit
  - Fixed DynamoDB ValidationException for access tokens exceeding size limits
  - Implemented individual property storage pattern for large data structures
  - Separated Google token data storage from index keys to prevent size limit violations
  - Added reference key pattern for efficient lookup of separated token data

SECURITY
~~~~~~~~

- **OAuth2 Security Enhancements**:
  - Implemented comprehensive email validation to prevent identity attacks
  - Added state parameter encryption for CSRF protection
  - Enhanced callback validation with multiple security checks
  - Improved error handling to prevent information leakage

- **MCP Authorization Server Security**:
  - RFC 7591 compliant Dynamic Client Registration with proper client credential generation
  - Per-actor client isolation using ActingWeb security boundary model
  - State parameter encryption with MCP context preservation prevents CSRF attacks
  - Secure token separation between ActingWeb internal tokens and Google OAuth2 tokens
  - Proper scope validation and authorization code flow implementation
  - Client credential storage encrypted at rest using ActingWeb property system

v3.1: Jul 28, 2025
--------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- Removed legacy OnAWBase interface completely
- Removed `actingweb.on_aw` module and `OnAWBase` class  
- Removed `ActingWebBridge` compatibility layer from interface module
- Handler constructors now accept `hooks: HookRegistry` instead of `on_aw: OnAWBase`
- Applications must now use the modern `ActingWebApp` interface exclusively

ADDED
~~~~~

- FastAPI integration with `app.integrate_fastapi()` method
- FastAPI integration automatically generates OpenAPI/Swagger documentation
- Synchronous ActingWeb handlers run in thread pools to prevent event loop blocking
- Pydantic models for all ActingWeb endpoints with automatic validation
- Support for modern `@app.actor_factory` decorator in FastAPI integration

CHANGED
~~~~~~~

- All handlers now use HookRegistry directly instead of OnAWBase bridge pattern
- Flask integration now uses HookRegistry directly
- Fixed hook method call signatures in properties.py, resources.py, and www.py
- Fixed path handling in property hooks to prevent index out of bounds errors
- Standardized hook parameter order across all handlers
- Fixed missing arguments in execute_property_hooks calls
- Resolved callback hook return type issues with any() function usage

v3.0.1: (Jul 17, 2025)
------------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~
- Minimum Python version is now 3.11+
- Removed deprecated Google App Engine (GAE) database implementation
- Removed migrate_2_5_0 migration flag and related migration code
- Database backend now only supports DynamoDB
- Removed Google App Engine urlfetch abstraction layer
- Environment types updated to remove APPENGINE, added AWS
- Separated application-level callbacks (@app.app_callback_hook) from actor-level callbacks (@app.callback_hook)

ADDED
~~~~~
- Comprehensive type hints using Python 3.11+ union syntax (str | None)
- Custom exception hierarchy: ActorError, ActorNotFoundError, InvalidActorDataError, PeerCommunicationError, TrustRelationshipError
- Constants module with AuthType, HttpMethod, TrustRelationship, ResponseCode enums
- Modern build system with pyproject.toml and Poetry for dependency management
- Modern developer interface with ActingWebApp class and fluent API
- Decorator-based hook system for property, callback, subscription, and lifecycle events
- ActorInterface, PropertyStore, TrustManager, and SubscriptionManager wrappers
- Flask integration with automatic route generation
- /methods endpoint support with JSON-RPC 2.0 protocol compatibility
- /actions endpoint support for trigger-based functionality
- Method hooks (@app.method_hook) and action hooks (@app.action_hook)
- Development tooling (black, ruff, mypy) and comprehensive test suite with pytest
- Type checking support with py.typed marker
- __version__ attribute to actingweb module

CHANGED
~~~~~~~
- Modernized string formatting with f-strings
- Simplified HTTP client code to use urlfetch library directly
- Removed config.env == "appengine" environment checks
- Updated default actor type from gae-demo to demo
- Enhanced type safety with comprehensive None-checking patterns
- Applied systematic None validation patterns to prevent runtime errors
- Improved IDE support with better type inference and error detection
- Complete documentation overhaul with modern interface examples

FIXED
~~~~~
- Eliminated potential bugs from dual interface inconsistencies
- Removed unnecessary abstraction layers improving request handling speed
- Single code path reduces potential for interface synchronization issues
- Better type checking with direct HookRegistry usage instead of generic OnAWBase
- Zero Pylance diagnostics errors across entire codebase
- Comprehensive None safety checks across all core modules
- Fixed handler method signatures for proper positional argument passing
- Enhanced HTTP request safety with proper urlfetch module validation
- Fixed OAuth configuration access with proper None checks
- Applied systematic None safety patterns across all HTTP methods
- Refactored actor creation to reduce coupling between factory handler and bridge implementation
- Fixed template variables not being populated for web form POST to /

QUALITY
~~~~~~~
- Legacy OnAWBase interface completely removed for better maintainability
- Applications using OnAWBase must migrate to ActingWebApp interface
- 95%+ reduction in complexity for handler logic
- Clean separation of concerns with direct hook execution
- Much simpler debugging without bridge layer abstraction
- All tests continue to pass with new interface (30/30)
- 90% reduction in boilerplate code for new applications
- Proper circular import handling with TYPE_CHECKING
- Enhanced developer experience with self-documenting type hints

MIGRATION GUIDE
~~~~~~~~~~~~~~~
**For existing applications using OnAWBase:**

**Before (Legacy - NO LONGER SUPPORTED)**::

    class MyApp(OnAWBase):
        def get_properties(self, path, data):
            return data

        def post_callbacks(self, name):
            return True

**After (Modern Interface - REQUIRED)**::

    app = ActingWebApp("my-app", "dynamodb", "myapp.com")

    @app.property_hook("*")
    def handle_properties(actor, operation, value, path):
        if operation == "get":
            return value
        return value

    @app.callback_hook("*")
    def handle_callbacks(actor, name, data):
        return {"status": "handled"}

**Handler instantiation changes:**
- **Before:** `Handler(webobj, config, on_aw=my_onaw_instance)`  
- **After:** `Handler(webobj, config, hooks=app.hooks)`

**Key Benefits of Migration:**
- 95% less boilerplate code
- Better type safety and IDE support  
- Easier testing and debugging
- Single source of truth for application logic
- No more dual interface maintenance

v2.6.5: Apr 22, 2021
--------------------
- Fix bug in subscription_diff handling by replacing query with scan as query requires hash key

v2.6.4: Apr 11, 2021
--------------------
- Messed up release versioning, bump up to avoid confusion

v2.6.3: Apr 11, 2021
--------------------
- Fix bug in peertrustee handling by replacing dynamodb count() with scan() as count requires a hash key

v2.6.2: Oct 20, 2020
--------------------
- Security fix on oauth refresh

v2.6.1: Aug 30, 2020
--------------------
- Fix token refresh to also use Basic authorisation

v2.6.0: Aug 23, 2020
--------------------
- Add support for optional Basic authorisation in token request (e.g. Fitbit is requiring this)

v2.5.1: Jan 29, 2019
--------------------
- Move some annoying info messages to debug in auth/oauth
- Fix bug in set_attr for store where struct is not initialised (attribute.py:70)
- Enforce lower case on creator if @ (i.e. email) in value

v2.5.0: Nov 17, 2018
--------------------
- BREAKING: /www/properties template_values now return a dict with { 'key': value} instead of list of { 'name': 'key',
  'value': value}
- Add support for scope GET parameter in callback from OAUTH2 provider (useful for e.g. Google)
- Add support for oauth_extras dict in oauth config to set additional oauth paramters forwarded to OAUTH2 provider
  (Google uses this)
- Add support for dynamic:creator in oauth_extras to preset login hint etc when forwarding to OAuth2 auth endpoints
  (if creator==email, this allows you to send Google hint on which account to use with 'login_hint': 'dynamic:creator'
  in oauth_extras in config
- Add support for actor get_from_creator() to initialise an actor from a creator (only usable together with config
  variable unique_creator)
- Add support for get_properties(), delete_properties(), put_properties(), and post_properties in the on_aw() class.
  These allows on_aw overriding functions to process any old and new properties and return the resulting properties
  to be stored, deleted, or returned
- Move all internal (oauth_token, oauth_token_expiry, oauth_refresh_token, oauth_token_refresh_token_expiry,
  cookie_redirect, and trustee_root) data from properties (where they are exposed on GET /<actor_id>/properties) to internal
  variable store (attributes). Introduce config variable migrate_2_5_0 (default True) that will look for properties
  with oauth variable names if not found in internal store and move them over to internal store (should be turned
  off when all actors have migrated their oauth properties over to store)
- Add new interface InternalStore() (attribute.py) for storing and retrieving internal variables on an actor (i.e.
  attributes). All actors now have .store that can be used either as a dict or dot-notation. actor.store.var = 'this'
  or actor.store['var'] = 'this'. Set the variable to None to delete it. All variables are immediately stored to the
  database. Note that variable values must be json serializable
- Add new interface PropertyStore() (property.py) for storing and retrieving properties. Used just like InternalStore()
  and access through actor.property.my_var or actor.property['my_var']
- InternalStore(actor_id=None, config=None, bucket=None) can be used independently and the optional bucket parameter
  allows you to create an internal store that stores a set of variables in a specific bucket. A bucket is retrieved
  all at once and variables are written to database immediately
- Fix issue where downstream (trusts) server processing errors resulted in 405 instead of 500 error code
- Fix bug in oauth.put_request() where post was used instead of put
- Fix issue where 200 had Forbidden text

v2.4.3: Sep 27, 2018
--------------------
- Don't do relative import with import_module, AWS Lambda gets a hiccup

v2.4.2: Sep 27, 2018
--------------------
- Get rid of future requirement, just a pain

v2.4.1: Sep 26, 2018
--------------------
- Fix bad relative imports
- Use extras_require for future (python2 support)

v2.4.0: Sep 22 2018
--------------------
- Support python3

v2.3.0: Dec 27, 2017
--------------------
- Entire API for handlers and Actor() as well as other objects changed to be PEP8 compliant
- Add support for head_request(() in oauth and oauth_head() in auth
- Change all uses of now() to utcnow()
- db_gae for Google AppEngine is not kept updated, so folder deprecated and just kept for later reference
- Full linting/PEP8 review
- Add support for actor_id (set id) on Actor.create()

v2.2.2: Dec 3, 2017
-------------------
- Fix bug in region for properties and attributes resulting in using us-east-1 for these (and not us-west-1 as default)

v2.2.1: Dec 3, 2017
-------------------
- Add support for environment variable AWS_DB_PREFIX to support multiple actingweb tables in same DynamoDB region

v2.2.0: Nov 25, 2017
--------------------
- Add support for attribute.Attributes() and attribute.Buckets() (to be used for internal properties not exposed)
- Various bug fixes to make the oauth flows work

v2.1.2: Nov 12, 2017
--------------------
- Split out actingweb module as a separate pypi library and repository
- Python2 support, not python3
- Support AWS DynamoDB and Google Datastore in sub-modules
- Refactor out a set of handlers to allow easy integration into any web framework
- actingwebdemo as a full-functioning demo app to show how the library is used

Jul 9, 2017
--------------------
- Fix bug with unique actor setting and actor already exists
- Improve handling of enforce use of email property as creator
- Fix auth bug for callbacks (401 when no auth is expected)
- Add support for "lazy refresh" of oauth token, i.e. refresh if expired or refresh token has <24h to expiry
- Add support for Actors() class in actor.py to get a list of all actors with id and creator (ONLY for admin usage)
- Fix various bugs when subscriptions don't exist
- Improve logging when actor cannot be created

Apr 2, 2017
--------------------
- Changed license to BSD after approval from Cisco Systems
- Fix bug in deletion of trust relationship that would not delete subscription
- Add support for GET param ?refresh=true for web-based sessions to ignore set cookie and do oauth
- Fix bug in oauth.oauth_delete() returning success when >299 is returned from upstream

Mar 11, 2017
--------------------
- Fix bug in aw_actor_callbacks.py on does exist test after db refactoring
- Fix bug in handling of www/init form to set properties
- Add support to enforce that creator (in actor) is unique (Config.unique_creator bool)
- Add support to enforce that a creator field set to "creator" is overwritten if property "email" is set 
  (Config.force_email_prop_as_creator bool, default True). Note that username for basic login then changes from
  creator to the value of email property. 
  This functionality can be useful if actor is created by trustee and email is set later
- Add new DbActor.py function get_by_creator() to allow retrieving an actor based on the creator value


Feb 25, 2016
--------------------
- Major refactoring of all database code
- All db entities are now accessible only from the actingweb/* libraries
- Each entity can be accessed one by one (e.g. trust.py exposes trust class) and as a list (e.g. trust.py exposes trusts class)
- actor_id and any parameters that identify the entity must be set when the class is instantiated
- get() must be called on the object to retrieve it from the database and the object
  is returned as a dictionary
- Subsequent calls to get() will return the dictionary without database access, but
  any changes will be synced to database immediately
- The actingweb/* libraries do not contain any database-specific code, but imports
  a db library that exposes the barebone db operations per object
- The google datastore code can be found in actingweb/db_gae
- Each database entity has its own .py file exposing get(), modify(), create(), delete()
  and some additional search/utility functions where needed
- These db classes do not do anything at init, and get() and create() must include all parameters
- The database handles are kept in the object, so modify() and delete() require a get() or create()
  before they can be called
- Currently, Google Datastore is the only supported db backend, but the db_* code can now fairly
  easily be adapted to new databases

Nov 19, 2016
--------------------
- Create a better README in rst
- Add readthedocs.org support with conf.py and index.rst files
- Add the actingweb spec as an rst file
- Add a getting-started rst file
- Correct diff timestamps to UTC standard with T and Z notation
- Fix json issue where diff sub-structures are escaped
- Add 20 sec timeout on all urlfethc (inter-actor) communication
- Support using creator passphrase as bearer token IF creator username == trustee
  and passphrase has bitstrength > 80
- Added id, peerid, and subscriptionid in subscriptions to align with spec
- Add modiify() for actor to allow change of creator username
- Add support for /trust/trustee operations to align with spec
- Add /devtest path and config.devtest bool to allow test scripts
- Add /devtest testing of all aw_proxy functionality

Nov 17, 2016
--------------------
- Renaming of getPeer() and deletePeer() to get_peer_trustee() and delete_peer_trustee() to avoid confusion
- Support for oauth_put() (and corresponding put_request()) and fix to accept 404 without refreshing token
- aw_proxy support for get_resource(), change_resource((), and delete_resource(()
- Support PUT on /resources

Nov 5, 2016
--------------------
- Add support for getResources in aw_proxy.py
- Renamed peer to peerTrustee in peer.py to better reflect that it is created by actor as trustee

Nov 1, 2016
--------------
- Add support for change_resource(() and delete_resource(() in aw_proxy.py
- Add support for PUT to /resources and on_put_resources() in on_aw_resources.py

Oct 28, 2016
--------------
- Add support for establishment and tear-down of peer actors as trustee, actor.getPeer() and actor.deletePeer()

  - Add new db storage for peers created as trustee
  - Add new config.actor section in config.py to define known possible peers
- Add new actor support function: getTrustRelationshipByType()
- Add new AwProxy() class with helper functions to do RPCish peer operations on trust relationships

  - Either use trust_target or peer_target to send commands to a specific trust or to the trust associated with a peer (i.e. peer created by this app as a trustee)
  - Support for create_resource() (POST on remote actor path like /resources or /properties)
- Fix bug where clean up of actor did not delete remote subscription (actor.delete())

  - Add remoteSubscription deletion in aw-actor-subscription.py
  - Fix auth issue in aw-actor-callbacks.py revealed by ths bug

Oct 26, 2016
--------------
- Add support for trustee by adding trustee_root to actor factory
- Add debug logging in auth process
- Fix bug where actors created within the same second got the same id

Oct 15, 2016
--------------
- Added support for requests to /bot and a bot (permanent) token in config.py to do API requests
  without going through the /<actorid>/ paths. Used to support scenarios where users can communicate with a bot to
  initiate creation of an actor (or to do commands that don't need personal oauth authorization.

Oct 12, 2016
--------------
- Support for actor.get_from_property(property-name, value) to initialse an actor from db by looking up a property value
  (it must be unique)

Oct 9, 2016
--------------
- Added support for GET, PUT, and DELETE for any sub-level of /properties, 
  also below resource, i.e. /properties/<subtarget>/<resource>/something/andmore/...
- Fixed bug where blob='', i.e. deletion, would not be registered

Oct 7, 2016
--------------
- Added support for resource (in addition to target and subtarget) in subscriptions, thus allowing subscriptions to
  e.g. /resources/files/<fileid> (where <fileid> is the resource to subscribe to. /properties/subtarget/resource
  subscriptions are also allowed.

Oct 6, 2016
--------------
- Added support for /resources with on_aw_resources.py in on_aw/ to hook into GET, DELETE, and POST requests to /resources
- Added fixes for box.com specific OAUTH implementation
- Added new function oauth_get(), oauth_post(), and oauth_delete() to Auth() class. These will refresh a token if necessary and
  can be used insted of oauth.get_request(), post_request(), and delete_request(()
- Minor refactoring of inner workings of auth.py and oauth.py wrt return values and error codes

Sep 25, 2016
--------------
- Added use_cache=False to all db operations to avoid cache issue when there are multiple instances of same app in gae

Sep 4, 2016
--------------
- Refactoring of creation of trust:
  - ensure that secret is generated by initiating peer
  - ensure that a peer cannot have more than one relationship
  - ensure that a secret can only be used for one relationship

Aug 28, 2016
--------------
- Major refactoring of auth.py. Only affects how init_actingweb() is used, see function docs

Aug 21, 2016: New features
--------------------------
- Removed the possibility of setting a secret when initiating a new relationship, as well as ability to change secret. This is to avoid the possibility of detecting existing secrets (from other peers) by testing secrets

Aug 15, 2016: Bug fixes
------------------------
- Added new acl["approved"] flag to auth.py indicating whether an authenticated peer has been approved
- Added new parameter to the authorise() function to turn off the requirement that peer has been approved to allow access
- Changed default relationship to the lowest level (associate) and turned off default approval of the default relationship
- Added a new authorisation check to subscriptions to make sure that only peers with access to a path are allowed to subscribe to those paths
- Added a new approval in trust to allow non-approved peers to delete their relationship (in case they want to "withdraw" their relationship request)
- Fixed uncaught json exception in create_remote_subscription()
- Fixed possibility of subpath being None instead of '' in auth.py
- Fixed handling of both bool json type and string bool value for approved parameter for trust relationships


Aug 6, 2016: New features
----------------------------
- Support for deleting remote subscription (i.e. callback and subscription, dependent on direction) when an actor is
  deleted

  - New delete_remote_subscription() in actor.py
  - Added deletion to actor.delete()
  - New handler for DELETE of /callbacks in aw-actor-callbacks.py
  - New on_delete_callbacks() in on_aw_callbacks.py

Aug 6, 2016: Bug fixes
----------------------------
- Fixed bug where /meta/nonexistent resulted in 500

Aug 3, 2016: New features
----------------------------
- Support for doing callbacks when registering diffs

  - New function in actor.py: callback_subscription()
  - Added defer of callbacks to avoid stalling responses when adding diffs
  - Added new function get_trust_relationship() to get one specific relationship based on peerid (instead of searching using get_trust_relationships())
- Improved diff registration

  - Totally rewrote register_diffs() to register diffs for subscriptions that are not exact matches (i.e. broader/higher-level and more specific)
  - Added debug logging to trace how diffs are registered
- Owner-based access only to /callbacks/subscriptions
- Support for handling callbacks for subscriptions

  - New function in on_aw_callbacks.py: on_post_subscriptions() for handling callbacks on subscriptions
  - Changed aw-actor-callbacks.py to handle POSTs to /callbacks/subscriptions and forward those to on_post_subscriptions()

Aug 3, 2016: Bug fixes
----------------------------
- Added no cache to the rest of subscriptionDiffs DB operations to make sure that deferred subscription callbacks don't mess up sequencing
- Changed meta/raml to meta/specification to allow any type of specification language

Aug 1, 2016: New features
----------------------------
- Added support for GET on subscriptions as peer, generic register diffs function, as well as adding diffs when changing /properties. Also added support for creator initiating creation of a subscription by distingushing on POST to /subscriptions (as creator to inititate a subscription with another peer) and to /subscriptions/<peerid> (as peer to create subscription)
- Subscription is also created when initiating a remote subscription (using callback bool to set flag to identify a subscription where callback is expected). Still missing support for sending callbacks (high/low/none), as well as processing callbacks
- Added support for sequence number in subscription, so that missing diffs can be detected. Specific diffs can be retrieved by doing GET as peer on /subscriptions/<peerid>/<subid>/<seqnr> (and the diff will be cleared)

Jul 27, 2016: New features
----------------------------
- Started adding log statements to classes and methods
- Added this file to track changes
- Added support for requesting creation of subscriptions, GETing (with search) all subscriptions as creator (not peer), as well as deletion of subscriptions when an actor is deleted (still remaining GET all relationship as peer, GET on relationship to get diffs, DELETE subscription as peer, as well as mechanism to store diffs)

Jul 27, 2016: Bug fixes
----------------------------
- Changed all ndb.fetch() calls to not include a max item number
- Cleaned up actor delete() to go directly on database to delete all relevant items
- Fixed a bug where the requested peer would not store the requesting actor's mini-app type in db (in trust)
- Added use_cache=False in all trust.py ndb calls to get rid of the cache issues experienced when two different threads communicate to set up a trust
- Added a new check and return message when secret is not included in an "establish trust" request (requestor must always include secret)

July 12, 2016: New features
----------------------------
- config.py cleaned up a bit

July 12, 2016: Bug fixes
----------------------------
- Fix in on_aw_oauth_success where token can optionally supplied (first time oauth was done the token has not been flushed to db)
- Fix in on_aw_oauth_success where login attempt with wrong Spark user did not clear the cookie_redirect variable
- Fixed issue with wrong Content-Type header for GET and DELETE messages without json body
