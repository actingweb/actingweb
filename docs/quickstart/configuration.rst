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

    pip install 'actingweb[postgresql]'

Local Development
~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Start PostgreSQL
    docker run -d \
      --name actingweb-postgres \
      -e POSTGRES_USER=actingweb \
      -e POSTGRES_PASSWORD=devpassword \
      -e POSTGRES_DB=actingweb \
      -p 5432:5432 \
      postgres:16-alpine

    # Configure environment
    export DATABASE_BACKEND=postgresql
    export PG_DB_HOST=localhost
    export PG_DB_PORT=5432
    export PG_DB_NAME=actingweb
    export PG_DB_USER=actingweb
    export PG_DB_PASSWORD=devpassword

    # Run migrations (REQUIRED before first use)
    cd actingweb/db/postgresql/
    alembic upgrade head

Production (Managed PostgreSQL)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure environment variables for your PostgreSQL instance:

.. code-block:: bash

    export DATABASE_BACKEND=postgresql
    export PG_DB_HOST=postgres.example.com
    export PG_DB_PORT=5432
    export PG_DB_NAME=actingweb_prod
    export PG_DB_USER=actingweb
    export PG_DB_PASSWORD=<secure-password>

    # Optional connection pool tuning
    export PG_POOL_MIN_SIZE=2
    export PG_POOL_MAX_SIZE=20
    export PG_POOL_TIMEOUT=30

**Migration Management:**

- Run ``alembic upgrade head`` to apply migrations
- Migrations are located in ``actingweb/db/postgresql/migrations/``
- Check current version: ``alembic current``
- See migration guide: :doc:`../guides/postgresql-migration`

**Recommended Services:**

- AWS RDS PostgreSQL
- Google Cloud SQL for PostgreSQL
- Azure Database for PostgreSQL
- DigitalOcean Managed PostgreSQL

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

- ``root``: Computed as ``{proto}{fqdn}/``. Templates receive ``actor_root`` and ``actor_www`` (see :doc:`www-handler-templates`).
- Deployments under a base path are supported by integrations; avoid relative paths in templates.

MCP Capability
--------------

- Toggle with ``ActingWebApp.with_mcp(enable=True|False)``.
- When enabled, ``mcp`` appears in supported options returned by meta discovery.

Notes
-----

- Always use ``ActorInterface`` in applications; the internal ``Actor`` class is for framework use.
- Prefer property lists for large or growing collections; see :doc:`developers` for guidance.
