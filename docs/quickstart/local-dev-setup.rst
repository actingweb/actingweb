=================
Local Dev Setup
=================

This page helps you run ActingWeb locally with your choice of database backend (DynamoDB or PostgreSQL) and web framework.

Install
-------

.. code-block:: bash

   # Minimal (no database backend)
   pip install actingweb

   # Flask integration + DynamoDB
   pip install 'actingweb[flask,dynamodb]'

   # Flask integration + PostgreSQL
   pip install 'actingweb[flask,postgresql]'

   # FastAPI integration + DynamoDB
   pip install 'actingweb[fastapi,dynamodb]'

   # FastAPI integration + PostgreSQL
   pip install 'actingweb[fastapi,postgresql]'

   # MCP-enabled (FastAPI + MCP + database)
   pip install 'actingweb[fastapi,mcp,postgresql]'  # or dynamodb

   # All extras (both backends, all integrations)
   pip install 'actingweb[all]'

Database Backend Setup
----------------------

ActingWeb supports two database backends: **DynamoDB** and **PostgreSQL**. Choose one for local development.

Option 1: DynamoDB Local
~~~~~~~~~~~~~~~~~~~~~~~~~

Launch DynamoDB Local and configure environment:

.. code-block:: bash

   docker run -p 8000:8000 amazon/dynamodb-local

   export DATABASE_BACKEND=dynamodb  # Optional, dynamodb is default
   export AWS_ACCESS_KEY_ID=local
   export AWS_SECRET_ACCESS_KEY=local
   export AWS_DEFAULT_REGION=us-east-1
   export AWS_DB_HOST=http://localhost:8000   # IMPORTANT for PynamoDB models

Notes:

- The library auto-creates tables on first access through its PynamoDB models.
- For production, configure IAM and real AWS hosts (do not set ``AWS_DB_HOST``).

Option 2: PostgreSQL (Recommended for New Projects)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Quick Start (Complete Setup)**

.. code-block:: bash

   # 1. Start PostgreSQL (Docker)
   docker run -d \
     --name actingweb-postgres \
     -e POSTGRES_USER=actingweb \
     -e POSTGRES_PASSWORD=devpassword \
     -e POSTGRES_DB=actingweb \
     -p 5432:5432 \
     postgres:16-alpine

   # 2. Create .env file in your project root
   cat > .env << 'EOF'
   DATABASE_BACKEND=postgresql
   PG_DB_HOST=localhost
   PG_DB_PORT=5432
   PG_DB_NAME=actingweb
   PG_DB_USER=actingweb
   PG_DB_PASSWORD=devpassword
   EOF

   # 3. Download migration helper script (one-time setup)
   mkdir -p scripts
   curl -o scripts/migrate_db.py https://raw.githubusercontent.com/actingweb/actingweb/main/scripts/migrate_db.py

   # 4. Run migrations (REQUIRED before first use)
   python scripts/migrate_db.py upgrade head

   # 5. Verify setup
   python scripts/migrate_db.py current

**Why PostgreSQL?**

- Lower latency (no network overhead for local development)
- Full SQL support with JOINs and complex queries
- Built-in ACID transactions
- Mature ecosystem (pg_dump, psql, GUI tools)
- Lower cost for read-heavy workloads

**Migration Helper Script Benefits:**

The ``scripts/migrate_db.py`` helper script:

- Automatically loads your ``.env`` file
- Validates all required environment variables
- Finds ``alembic.ini`` in your installed actingweb package
- Provides simple commands: ``upgrade``, ``downgrade``, ``current``, ``history``
- Works with both pip and poetry installations

**Common Migration Commands:**

.. code-block:: bash

   python scripts/migrate_db.py upgrade head    # Apply all pending migrations
   python scripts/migrate_db.py current         # Show current version
   python scripts/migrate_db.py downgrade -1    # Rollback one migration
   python scripts/migrate_db.py history         # Show migration history

**Alternative: Manual Migration (Not Recommended)**

If you prefer to run alembic directly without the helper script:

.. code-block:: bash

   python -c "import actingweb; from pathlib import Path; print(Path(actingweb.__file__).parent / 'db' / 'postgresql')" | xargs -I{} alembic -c {}/alembic.ini upgrade head

**Notes:**

- PostgreSQL requires running Alembic migrations before first use (unlike DynamoDB which auto-creates tables)
- For native PostgreSQL: ``brew install postgresql`` (macOS) or ``apt install postgresql`` (Ubuntu)
- Connection pooling is automatic (psycopg3 with configurable min/max connections)
- Use Docker Compose for multi-service setups (see :doc:`../guides/postgresql-migration`)

Choosing a Framework
--------------------

- Flask: smallest dependency footprint; great for simple apps
- FastAPI: async support and automatic OpenAPI docs at `/docs`

Web UI and Dev Endpoints
------------------------

- Enable the web UI with `.with_web_ui(True)` (available at `/<actor_id>/www`)
- Enable dev/test helpers with `.with_devtest(True)` (disable in production)

Running Locally
---------------

- Flask: call `aw.integrate_flask(flask_app)` and run `flask_app.run()`
- FastAPI: call `aw.integrate_fastapi(api)` and run `uvicorn app:api --reload --port 5000`

