Configuration Reference
=======================

This page summarizes configuration for building applications with the ActingWeb Python library. Use the fluent `ActingWebApp` API in applications; it produces a `Config` object (``actingweb.config.Config``) that drives behavior.

Quick Start
-----------

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="postgresql",  # or "dynamodb" (default)
        fqdn="myapp.example.com",
        proto="https://"
    ).with_oauth(client_id="...", client_secret="...") \
     .with_web_ui(enable=True) \
     .with_devtest(enable=False) \
     .add_actor_type("myself", relationship="friend")

    config = app.get_config()  # actingweb.config.Config

Core Identity
-------------

- ``aw_type``: ActingWeb type URI for your app (required).
- ``fqdn``: Hostname used for URLs (e.g., ``myapp.example.com``).
- ``proto``: URL scheme (``https://`` recommended).
- ``version``: Populated from library version; can be displayed to clients.

Runtime Switches
----------------

- ``ui``: Enable ``/<actor_id>/www`` web UI (``with_web_ui()``). Also affects browser redirects.
- ``devtest``: Enable development endpoints; MUST be ``False`` in production.
- ``www_auth``: ``basic`` or ``oauth``; set by ``with_oauth()``.
- ``unique_creator``: Enforce one actor per creator (``with_unique_creator()``).
- ``force_email_prop_as_creator``: Copy ``email`` property to ``creator``.
- ``mcp``: Include MCP capability; toggle via ``with_mcp()``.
- ``sync_subscription_callbacks``: Force synchronous subscription callbacks (``with_sync_callbacks()``). **Recommended for Lambda/serverless deployments** where async fire-and-forget callbacks may be lost when the function freezes.

Browser Redirect Behavior
-------------------------

The ``ui`` setting (``with_web_ui()``) controls where browsers are redirected:

.. list-table::
   :header-rows: 1
   :widths: 30 20 25 25

   * - Scenario
     - ``with_web_ui()``
     - Redirect
     - Use Case
   * - Unauthenticated browser → ``/<actor_id>``
     - Any
     - ``/login``
     - Consistent login experience
   * - Authenticated browser → ``/<actor_id>``
     - ``True``
     - ``/<actor_id>/www``
     - Server-rendered templates
   * - Authenticated browser → ``/<actor_id>``
     - ``False``
     - ``/<actor_id>/app``
     - Single Page Applications
   * - After OAuth login
     - ``True``
     - ``/<actor_id>/www``
     - Server-rendered templates
   * - After OAuth login
     - ``False``
     - ``/<actor_id>/app``
     - Single Page Applications

API clients (``Accept: application/json``) always receive JSON responses, not redirects.

For SPAs, you must provide ``/login`` and ``/<actor_id>/app`` routes. See :doc:`../guides/spa-authentication`.

OAuth2
------

Configured by ``with_oauth(...)``. Common fields:

- ``client_id``, ``client_secret``: Provider credentials.
- ``redirect_uri``: Defaults to ``{proto}{fqdn}/oauth``.
- ``auth_uri``, ``token_uri``: Authorization and token endpoints.
- ``scope``: Provider-specific scopes.

Actors Registry
---------------

``actors`` maps short names to known actor factories:

.. code-block:: python

    app.add_actor_type("myself", factory=f"{app.proto}{app.fqdn}/", relationship="friend")

Database Backend
----------------

ActingWeb supports two database backends:

- ``database="dynamodb"`` (default) - AWS DynamoDB with PynamoDB ORM
- ``database="postgresql"`` - PostgreSQL with psycopg3 and Alembic migrations

Backend selection is controlled by the ``database`` parameter in ``ActingWebApp()`` or via the ``DATABASE_BACKEND`` environment variable.

**Choosing a Backend:**

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Feature
     - DynamoDB
     - PostgreSQL
   * - Setup Complexity
     - Low (auto-creates tables)
     - Medium (requires migrations)
   * - Local Development
     - DynamoDB Local (Docker)
     - PostgreSQL (Docker/native)
   * - Scaling
     - Automatic, serverless
     - Manual (vertical/horizontal)
   * - Cost Model
     - Pay-per-request or provisioned
     - Instance-based
   * - Query Flexibility
     - Limited (key-based + GSI)
     - Full SQL with JOINs
   * - Latency (local)
     - Higher (network overhead)
     - Lower (direct connection)
   * - Production Management
     - Fully managed (AWS)
     - Self-managed or RDS
   * - Multi-region
     - Built-in global tables
     - Manual replication setup

See :doc:`../reference/database-backends` for detailed comparison and migration guide.

DynamoDB Setup
--------------

Installation
~~~~~~~~~~~~

.. code-block:: bash

    pip install 'actingweb[dynamodb]'

Local Development (DynamoDB Local)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    docker run -p 8000:8000 amazon/dynamodb-local
    export DATABASE_BACKEND=dynamodb  # Optional, default
    export AWS_ACCESS_KEY_ID=local
    export AWS_SECRET_ACCESS_KEY=local
    export AWS_DEFAULT_REGION=us-east-1
    export AWS_DB_HOST=http://localhost:8000  # PynamoDB host override for local

Point your app to DynamoDB Local via these environment variables (no code changes needed). The library uses its bundled PynamoDB models to create/access required tables at runtime.

Production (AWS DynamoDB)
~~~~~~~~~~~~~~~~~~~~~~~~~

- Configure IAM with least-privilege on the app's tables: ``dynamodb:GetItem``, ``PutItem``, ``UpdateItem``, ``DeleteItem``, ``Query``, ``Scan``.
- Ensure tables exist (actor, properties, attributes, subscriptions, trust, and related indexes) before first traffic; the library's DB modules are under ``actingweb.db.dynamodb``.
- Set region/credentials via standard AWS mechanisms (env vars, instance roles, profiles).

PostgreSQL Setup
----------------

Installation
~~~~~~~~~~~~

.. code-block:: bash

    # pip installation
    pip install 'actingweb[postgresql]'

    # poetry installation
    poetry add 'actingweb[postgresql]'

Local Development (Complete Setup)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Step 1: Start PostgreSQL**

.. code-block:: bash

    # Using Docker (recommended)
    docker run -d \
      --name actingweb-postgres \
      -e POSTGRES_USER=actingweb \
      -e POSTGRES_PASSWORD=devpassword \
      -e POSTGRES_DB=actingweb \
      -p 5432:5432 \
      postgres:16-alpine

**Step 2: Configure Environment**

Create a ``.env`` file in your project root:

.. code-block:: bash

    DATABASE_BACKEND=postgresql
    PG_DB_HOST=localhost
    PG_DB_PORT=5432
    PG_DB_NAME=actingweb
    PG_DB_USER=actingweb
    PG_DB_PASSWORD=devpassword

**Step 3: Setup Migration Helper (Recommended)**

.. code-block:: bash

    # Download migration helper script (one-time)
    mkdir -p scripts
    curl -o scripts/migrate_db.py https://raw.githubusercontent.com/actingweb/actingweb/main/scripts/migrate_db.py

The helper script automatically:

- Loads ``.env`` file
- Validates required environment variables
- Finds ``alembic.ini`` in installed actingweb package
- Provides simple migration commands

**Step 4: Run Migrations (REQUIRED)**

.. code-block:: bash

    # Apply all migrations
    python scripts/migrate_db.py upgrade head

    # Verify current version
    python scripts/migrate_db.py current

**Common Migration Commands:**

.. code-block:: bash

    python scripts/migrate_db.py upgrade head    # Apply all pending migrations
    python scripts/migrate_db.py current         # Show current version
    python scripts/migrate_db.py downgrade -1    # Rollback one migration
    python scripts/migrate_db.py history         # Show migration history

**Alternative: Direct Alembic (Advanced Users)**

If you prefer not to use the helper script:

.. code-block:: bash

    python -c "import actingweb; from pathlib import Path; print(Path(actingweb.__file__).parent / 'db' / 'postgresql')" | xargs -I{} alembic -c {}/alembic.ini upgrade head

Production (Managed PostgreSQL)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Environment Configuration:**

.. code-block:: bash

    export DATABASE_BACKEND=postgresql
    export PG_DB_HOST=postgres.example.com
    export PG_DB_PORT=5432
    export PG_DB_NAME=actingweb_prod
    export PG_DB_USER=actingweb
    export PG_DB_PASSWORD=<secure-password>

    # Optional: Connection pool tuning
    export PG_POOL_MIN_SIZE=2       # Minimum pool connections
    export PG_POOL_MAX_SIZE=20      # Maximum pool connections
    export PG_POOL_TIMEOUT=30       # Connection timeout (seconds)

**Migrations in Production:**

Use the same migration helper script or CI/CD-friendly one-liner:

.. code-block:: bash

    # Using helper script
    python scripts/migrate_db.py upgrade head

    # CI/CD one-liner (no .env file)
    python -c "import actingweb; from pathlib import Path; print(Path(actingweb.__file__).parent / 'db' / 'postgresql')" | xargs -I{} alembic -c {}/alembic.ini upgrade head

**Recommended Managed Services:**

- **AWS RDS PostgreSQL** - Fully managed, automatic backups, Multi-AZ
- **Google Cloud SQL** - Managed PostgreSQL with high availability
- **Azure Database for PostgreSQL** - Enterprise-grade managed service
- **DigitalOcean Managed PostgreSQL** - Simple, affordable managed database

**Docker Compose Example:**

.. code-block:: yaml

    services:
      app:
        environment:
          - DATABASE_BACKEND=postgresql
          - PG_DB_HOST=postgres
          - PG_DB_PORT=5432
          - PG_DB_NAME=actingweb
          - PG_DB_USER=actingweb
          - PG_DB_PASSWORD=devpassword
        depends_on:
          postgres:
            condition: service_healthy

      postgres:
        image: postgres:16-alpine
        environment:
          POSTGRES_USER: actingweb
          POSTGRES_PASSWORD: devpassword
          POSTGRES_DB: actingweb
        ports:
          - "5432:5432"
        volumes:
          - postgres_data:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U actingweb"]
          interval: 10s
          timeout: 5s
          retries: 5

    volumes:
      postgres_data:

**Common Issues and Solutions:**

**1. "Connection refused" error**

.. code-block:: bash

    # Check PostgreSQL is running
    docker ps | grep postgres
    # Or for native installations
    pg_isready -h localhost -p 5432

**2. "relation does not exist" error**

This means migrations haven't been run yet:

.. code-block:: bash

    python scripts/migrate_db.py upgrade head

**3. "permission denied" errors in queries**

Check your PostgreSQL user has proper permissions:

.. code-block:: sql

    psql -U postgres
    GRANT ALL PRIVILEGES ON DATABASE actingweb TO actingweb;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO actingweb;

**4. "password authentication failed"**

Verify your PG_DB_PASSWORD matches what you set when creating the database:

.. code-block:: bash

    # Reset password
    psql -U postgres -c "ALTER USER actingweb WITH PASSWORD 'newpassword';"
    # Update .env file with new password

Property Reverse Lookup
------------------------

ActingWeb supports efficient reverse lookups (find actor by property value) using a dedicated lookup table. This is particularly useful for OAuth authentication where you need to find an actor by their OAuth provider ID.

**Why Use Lookup Tables?**

By default, ActingWeb uses database indexes for reverse lookups:

- **DynamoDB**: Global Secondary Index (GSI) on the ``value`` field - limited to 2048 bytes
- **PostgreSQL**: Index on the ``value`` column - works but less efficient for large values

The lookup table approach removes size limits and improves query performance for configured properties.

Configuration
~~~~~~~~~~~~~

Enable lookup tables via API or environment variables:

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        fqdn="myapp.example.com"
    ).with_indexed_properties(["oauthId", "email", "externalUserId"])

    # Enable lookup table mode (disable legacy indexes)
    app.with_legacy_property_index(enable=False)  # Recommended for new deployments

**Environment Variables:**

.. code-block:: bash

    export USE_PROPERTY_LOOKUP_TABLE=true                           # Enable lookup table
    export INDEXED_PROPERTIES=oauthId,email,externalUserId         # Which properties to index

**Default Configuration:**

- ``USE_PROPERTY_LOOKUP_TABLE``: ``false`` (uses legacy GSI/index for backward compatibility)
- ``INDEXED_PROPERTIES``: ``["oauthId", "email", "externalUserId"]``

Usage Example
~~~~~~~~~~~~~

Finding an actor by OAuth ID:

.. code-block:: python

    from actingweb.db import get_db

    # Get property database interface
    db_property = get_db().DbProperty()

    # Reverse lookup: find actor by OAuth ID
    actor_id = db_property.get_actor_id_from_property(
        name="oauthId",
        value="github:12345"
    )

    if actor_id:
        print(f"Found actor: {actor_id}")

The lookup happens automatically when you set indexed properties:

.. code-block:: python

    # Setting an indexed property creates lookup entry automatically
    db_property.set(
        actor_id="actor-123",
        name="oauthId",
        value="github:12345"
    )

    # Lookup table entry is created behind the scenes
    # You can now find the actor by this OAuth ID

Migration Guide
~~~~~~~~~~~~~~~

**New Deployments:** Enable lookup tables from the start:

.. code-block:: python

    app.with_legacy_property_index(enable=False)

**Existing Deployments:** Use dual-mode for gradual migration:

1. **Phase 1 - Deploy with Lookup Table Support:**

   .. code-block:: python

       # Keep legacy mode enabled (default)
       app = ActingWebApp(...)  # use_lookup_table defaults to False

   Deploy this version. Both legacy and lookup table code paths are available.

2. **Phase 2 - Enable Lookup Tables:**

   .. code-block:: bash

       export USE_PROPERTY_LOOKUP_TABLE=true

   Restart the application. New writes will populate lookup tables. Legacy GSI/index still used for reads.

3. **Phase 3 - Backfill Existing Data (Optional):**

   Run a backfill script to populate lookup tables for existing actors (implementation depends on your deployment).

4. **Phase 4 - Disable Legacy Index:**

   Once backfill is complete and you've verified lookup tables work correctly, you can disable the legacy GSI/index at the database level.

**Rollback:** Set ``USE_PROPERTY_LOOKUP_TABLE=false`` to revert to legacy GSI/index mode.

Size Limits
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - Configuration
     - DynamoDB Limit
     - PostgreSQL Limit
   * - Legacy GSI/Index
     - 2048 bytes
     - 8191 bytes (btree index)
   * - Lookup Table
     - No limit (400KB item)
     - No limit (TEXT column)

**Recommendation:** Use lookup tables if you need to store OAuth tokens, long external IDs, or any property values exceeding 2KB.

**Practical Size Limits:**

While lookup tables remove hard limits, consider these guidelines for optimal performance:

- **DynamoDB**: Hard limit of 400KB per item (applies to entire property record)
- **PostgreSQL**: No hard limit (TEXT column), but very large values impact query performance
- **Recommended**: Keep indexed property values under 10KB for best query performance
- **Performance impact**: Property values over 100KB may cause slower writes and increased memory usage

For extremely large data (>100KB), consider:

1. Storing the data in external storage (S3, Cloud Storage) and keeping only a reference in the property
2. Using property lists for chunked storage of large datasets
3. Using non-indexed properties for large values that don't require reverse lookups

Best Practices
~~~~~~~~~~~~~~

1. **Choose Indexed Properties Carefully:** Only index properties you need for reverse lookups (e.g., ``oauthId``, ``email``). Each indexed property creates lookup table entries.

2. **Test Configuration Changes:** Property lookup configuration requires restart. Test in staging before production.

3. **Monitor Lookup Table Size:** For DynamoDB, monitor lookup table size and provision adequate capacity. For PostgreSQL, normal table monitoring applies.

4. **Cleanup:** Lookup entries are automatically deleted when properties or actors are deleted. No manual cleanup needed.

Peer Profile Caching
--------------------

ActingWeb can automatically cache profile attributes from peer actors with established trust relationships. This is useful for displaying peer information (display names, emails, etc.) without making repeated API calls.

Configuration
~~~~~~~~~~~~~

Enable peer profile caching via the fluent API:

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        fqdn="myapp.example.com"
    ).with_peer_profile(attributes=["displayname", "email", "description"])

**Parameters:**

- ``attributes``: List of property names to cache from peer actors.
  Default when enabled: ``["displayname", "email", "description"]``
  Pass an empty list to explicitly disable caching.

**Default Behavior:**

- Profile caching is **disabled by default**
- Must call ``with_peer_profile()`` to enable
- Profiles are stored in the ``peer_profiles`` attribute bucket

Automatic Profile Updates
~~~~~~~~~~~~~~~~~~~~~~~~~

When enabled, profiles are automatically updated:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Event
     - Action
   * - Trust fully approved (local)
     - Fetch and cache peer profile
   * - Trust fully approved (remote)
     - Fetch and cache peer profile
   * - ``sync_peer()`` completion
     - Refresh cached profile
   * - Trust deleted
     - Delete cached profile

Accessing Peer Profiles
~~~~~~~~~~~~~~~~~~~~~~~

Use the TrustManager to access cached profiles:

.. code-block:: python

    # Get cached profile
    profile = actor.trust.get_peer_profile(peer_id)
    if profile:
        print(f"Connected with {profile.displayname}")
        print(f"Email: {profile.email}")

    # Manual refresh (sync)
    profile = actor.trust.refresh_peer_profile(peer_id)

    # Manual refresh (async - for FastAPI)
    profile = await actor.trust.refresh_peer_profile_async(peer_id)

**PeerProfile Attributes:**

- ``actor_id``: The actor caching this profile
- ``peer_id``: The peer whose profile is cached
- ``displayname``: Human-readable name
- ``email``: Contact email
- ``description``: Actor description
- ``extra_attributes``: Dict of additional configured attributes
- ``fetched_at``: ISO timestamp when profile was fetched
- ``fetch_error``: Error message if fetch failed

Error Handling
~~~~~~~~~~~~~~

Profile fetch failures are handled gracefully:

- If the peer is unavailable, a profile with ``fetch_error`` is stored
- Missing properties are stored as ``None``
- Store failures are logged but don't crash the trust approval flow
- 403/404 responses cache an empty profile to avoid retries

Best Practices
~~~~~~~~~~~~~~

1. **Choose Attributes Carefully:** Only cache attributes you actually need. Each attribute requires a property lookup on the peer.

2. **Handle Missing Data:** Profiles may have ``None`` values for attributes the peer doesn't have. Always check before using:

   .. code-block:: python

       if profile and profile.displayname:
           display_text = profile.displayname
       else:
           display_text = f"Peer {peer_id[:8]}..."

3. **Check for Errors:** The ``fetch_error`` field indicates if the last fetch failed:

   .. code-block:: python

       if profile and profile.fetch_error:
           logger.warning(f"Profile fetch failed: {profile.fetch_error}")

4. **Refresh When Needed:** Use ``refresh_peer_profile()`` after significant peer changes or if cached data might be stale.

Peer Capabilities Caching
-------------------------

ActingWeb can automatically cache methods and actions that peer actors expose. This is useful for discovering what RPC methods and state-modifying actions are available on trusted peers without making repeated API calls.

Configuration
~~~~~~~~~~~~~

Enable peer capabilities caching via the fluent API:

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        fqdn="myapp.example.com"
    ).with_peer_capabilities(enable=True)

**Parameters:**

- ``enable``: Boolean to enable/disable capabilities caching. Default: ``True`` when called.

**Default Behavior:**

- Capabilities caching is **disabled by default**
- Must call ``with_peer_capabilities()`` to enable
- Capabilities are stored in the ``peer_capabilities`` attribute bucket

Automatic Capabilities Updates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When enabled, capabilities are automatically updated:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Event
     - Action
   * - Trust fully approved (local)
     - Fetch and cache peer methods/actions
   * - Trust fully approved (remote)
     - Fetch and cache peer methods/actions
   * - ``sync_peer()`` completion
     - Refresh cached capabilities
   * - Trust deleted
     - Delete cached capabilities

Accessing Peer Capabilities
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the TrustManager to access cached capabilities:

.. code-block:: python

    # Get all cached capabilities
    capabilities = actor.trust.get_peer_capabilities(peer_id)
    if capabilities:
        print(f"Methods: {capabilities.get_method_names()}")
        print(f"Actions: {capabilities.get_action_names()}")

        # Get specific method
        method = capabilities.get_method("get_data")
        if method:
            print(f"{method.name}: {method.description}")
            print(f"Input schema: {method.input_schema}")

    # Convenience methods for methods/actions only
    methods = actor.trust.get_peer_methods(peer_id)
    actions = actor.trust.get_peer_actions(peer_id)

    # Manual refresh (sync)
    capabilities = actor.trust.refresh_peer_capabilities(peer_id)

    # Manual refresh (async - for FastAPI)
    capabilities = await actor.trust.refresh_peer_capabilities_async(peer_id)

**CachedCapability Attributes:**

- ``name``: Method or action name
- ``description``: Human-readable description
- ``input_schema``: JSON Schema for parameters (optional)
- ``output_schema``: JSON Schema for return value (optional)
- ``capability_type``: ``"method"`` or ``"action"``

**CachedPeerCapabilities Attributes:**

- ``actor_id``: The actor caching this data
- ``peer_id``: The peer whose capabilities are cached
- ``methods``: List of CachedCapability objects for methods
- ``actions``: List of CachedCapability objects for actions
- ``fetched_at``: ISO timestamp when capabilities were fetched
- ``fetch_error``: Error message if fetch failed

Error Handling
~~~~~~~~~~~~~~

Capabilities fetch failures are handled gracefully:

- If the peer is unavailable, a capabilities object with ``fetch_error`` is stored
- 404 responses for ``/methods`` or ``/actions`` are normal (peer may not support them)
- Store failures are logged but don't crash the trust approval flow

Best Practices
~~~~~~~~~~~~~~

1. **Enable Only When Needed:** Capabilities caching adds network requests during trust establishment. Enable only if you need to discover peer methods/actions.

2. **Handle Missing Capabilities:** Check that methods/actions exist before using:

   .. code-block:: python

       method = capabilities.get_method("expected_method")
       if method:
           # Method is available, safe to call
           pass

3. **Check for Errors:** The ``fetch_error`` field indicates if the last fetch failed:

   .. code-block:: python

       if capabilities and capabilities.fetch_error:
           logger.warning(f"Capabilities fetch failed: {capabilities.fetch_error}")

4. **Refresh When Needed:** Use ``refresh_peer_capabilities()`` if cached data might be stale or after a peer upgrade.

Peer Permissions Caching
^^^^^^^^^^^^^^^^^^^^^^^^

When peer permissions caching is enabled, the library automatically caches what permissions
peer actors have granted to your actor. This enables efficient permission checking without
network requests.

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        fqdn="myapp.example.com"
    ).with_peer_permissions(
        enable=True,
        auto_delete_on_revocation=True,  # Delete cached data when permissions revoked
        notify_peer_on_change=True       # Auto-notify peers when their permissions change
    )

**Parameters:**

- ``enable``: Boolean to enable/disable permissions caching. Default: ``True`` when called.
- ``auto_delete_on_revocation``: When ``True``, automatically delete cached peer data
  from ``RemotePeerStore`` when the peer revokes property access. This ensures that
  when a peer revokes access to certain data (e.g., ``memory_*`` properties), the
  locally cached copies are deleted. Default: ``False``.
- ``notify_peer_on_change``: When ``True``, automatically notify peers when their
  permissions change by sending a callback to their ``/callbacks/permissions/{actor_id}``
  endpoint. This is fire-and-forget (failures are logged but don't block the store
  operation). Default: ``True``.

**Default Behavior:**

- Permissions caching is **disabled by default**
- Must call ``with_peer_permissions()`` to enable
- Permissions are stored in the ``_peer_permissions`` attribute bucket (note the ``_`` prefix for library-internal buckets)
- Auto-delete on revocation is **disabled by default**
- Notify peer on change is **enabled by default**

Automatic Permission Updates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When enabled, permissions are automatically updated:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Event
     - Action
   * - Trust fully approved
     - Fetch and cache peer's granted permissions
   * - ``sync_peer()`` completion
     - Refresh cached permissions
   * - Permission callback received
     - Update cached permissions (with change detection)
   * - Permission revoked (with ``auto_delete_on_revocation=True``)
     - Delete cached peer data matching revoked property patterns
   * - Permissions stored (with ``notify_peer_on_change=True``)
     - Send callback to peer's ``/callbacks/permissions/{actor_id}``
   * - Trust deleted
     - Delete cached permissions

Auto-Delete on Permission Revocation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``auto_delete_on_revocation=True`` is set and a peer revokes access to certain
properties, the library automatically deletes the corresponding cached data from
``RemotePeerStore``. This is useful when you're caching remote peer data via
subscription callbacks and want to ensure that revoked data is cleaned up.

**How it works:**

1. When a permission callback arrives, the library compares old and new permissions
2. Property patterns that were in the old permissions but not in the new are identified as "revoked"
3. All stored lists in ``RemotePeerStore`` matching the revoked patterns are deleted
4. The ``permission_changes`` dict is passed to the callback hook with details

**Example:** If the old permissions had patterns ``["memory_*", "profile_*"]`` and the
new permissions only have ``["memory_*"]``, then ``profile_*`` is considered revoked.
Any cached lists matching ``profile_*`` (like ``profile_info``) will be deleted.

**Callback Hook Data:**

When handling permission callbacks, the hook data includes a ``permission_changes`` dict:

.. code-block:: python

    @app.callback_hook("permissions")
    def on_permissions_callback(actor, name, data):
        changes = data.get("permission_changes", {})

        if changes.get("is_initial"):
            print("First permission callback from this peer")

        if changes.get("has_revocations"):
            print(f"Revoked patterns: {changes['revoked_patterns']}")

        if changes.get("granted_patterns"):
            print(f"Newly granted: {changes['granted_patterns']}")

        return True

Accessing Peer Permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the PeerPermissionStore to check cached permissions:

.. code-block:: python

    from actingweb.peer_permissions import get_peer_permission_store

    store = get_peer_permission_store(actor.config)

    # Get cached permissions
    perms = store.get_permissions(actor.id, peer_id)
    if perms:
        # Check property access
        if perms.has_property_access("memory_travel", "read"):
            print("Can read memory_travel from peer")

        # Check method access
        if perms.has_method_access("sync_data"):
            print("Can call sync_data on peer")

        # Check tool access (MCP)
        if perms.has_tool_access("search"):
            print("Can use search tool on peer")

**PeerPermissions Attributes:**

- ``actor_id``: The actor caching this data
- ``peer_id``: The peer who granted permissions
- ``properties``: Property permission patterns and operations
- ``methods``: Allowed/denied method patterns
- ``actions``: Allowed/denied action patterns
- ``tools``: Allowed/denied tool patterns (MCP)
- ``resources``: Allowed/denied resource patterns (MCP)
- ``prompts``: Allowed prompt patterns (MCP)
- ``fetched_at``: ISO timestamp when permissions were fetched
- ``fetch_error``: Error message if fetch failed

**Permission Check Methods:**

- ``has_property_access(name, operation)``: Check property permission (operation: read, write, subscribe, delete)
- ``has_method_access(name)``: Check method permission
- ``has_action_access(name)``: Check action permission
- ``has_tool_access(name)``: Check tool permission (MCP)
- ``has_resource_access(uri)``: Check resource permission (MCP)
- ``has_prompt_access(name)``: Check prompt permission (MCP)

Permission Callbacks
~~~~~~~~~~~~~~~~~~~~

When a peer modifies permissions granted to your actor, they can send a permission
callback to notify you immediately. This requires the ``permissioncallback`` option
to be advertised in the peer's ``/meta/actingweb/supported`` endpoint.

The callback is sent to::

    POST /{your_actor_id}/callbacks/permissions/{peer_actor_id}

The library automatically handles these callbacks and updates the local cache.

Best Practices
~~~~~~~~~~~~~~

1. **Enable for MCP Applications:** Permission caching is particularly useful for MCP applications that need to check tool/resource permissions frequently.

2. **Handle Missing Permissions:** Always check for permissions before operations:

   .. code-block:: python

       perms = store.get_permissions(actor.id, peer_id)
       if perms and perms.has_property_access("data", "read"):
           # Safe to read
           pass
       else:
           # No cached permissions or access denied
           pass

3. **Graceful Degradation:** If permissions aren't cached, fall back to synchronous fetch or deny access.

4. **Refresh When Needed:** Use manual fetch if cached permissions might be stale:

   .. code-block:: python

       from actingweb.peer_permissions import fetch_peer_permissions

       perms = fetch_peer_permissions(actor, peer_id)

Logging
-------

- ``logLevel``: ``DEBUG``, ``INFO``, or ``WARN``; defaults can be overridden with env var ``LOG_LEVEL``.

Environment Variables
---------------------

Convenience env vars read by the interface layer:

- ``APP_HOST_FQDN``: Default for ``fqdn`` if not provided.
- ``APP_HOST_PROTOCOL``: Default for ``proto`` if not provided.
- ``LOG_LEVEL``: Overrides logging level.
- ``APP_BOT_TOKEN``, ``APP_BOT_EMAIL``, ``APP_BOT_SECRET``, ``APP_BOT_ADMIN_ROOM``: Used by ``with_bot()``.

URLs and Base Paths
-------------------

- ``root``: Computed as ``{proto}{fqdn}/``. Templates receive ``actor_root`` and ``actor_www`` (see :doc:`../guides/web-ui`).
- Deployments under a base path are supported by integrations; avoid relative paths in templates.

MCP Capability
--------------

- Toggle with ``ActingWebApp.with_mcp(enable=True|False)``.
- When enabled, ``mcp`` appears in supported options returned by meta discovery.

Notes
-----

- Always use ``ActorInterface`` in applications; the internal ``Actor`` class is for framework use.
- Prefer property lists for large or growing collections; see :doc:`../sdk/developer-api` for guidance.
