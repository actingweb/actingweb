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
