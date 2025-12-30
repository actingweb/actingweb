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

Option 2: PostgreSQL
~~~~~~~~~~~~~~~~~~~~

Launch PostgreSQL and run migrations:

.. code-block:: bash

   # Start PostgreSQL (Docker)
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

   # Run database migrations
   cd actingweb/db/postgresql/
   alembic upgrade head

Notes:

- PostgreSQL requires running Alembic migrations before first use (unlike DynamoDB which auto-creates tables).
- For native PostgreSQL installation: ``brew install postgresql`` (macOS) or ``apt install postgresql`` (Ubuntu).
- Connection pooling is built-in (psycopg3 pool with configurable min/max connections).

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

