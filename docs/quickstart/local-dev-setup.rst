=================
Local Dev Setup
=================

This page helps you run ActingWeb locally with DynamoDB Local and your preferred web framework.

Install
-------

.. code-block:: bash

   # Minimal
   pip install actingweb

   # Flask integration
   pip install 'actingweb[flask]'

   # FastAPI integration
   pip install 'actingweb[fastapi]'

   # MCP-enabled (FastAPI + MCP)
   pip install 'actingweb[fastapi,mcp]'

DynamoDB Local
--------------

Launch DynamoDB Local and configure environment:

.. code-block:: bash

   docker run -p 8000:8000 amazon/dynamodb-local

   export AWS_ACCESS_KEY_ID=local
   export AWS_SECRET_ACCESS_KEY=local
   export AWS_DEFAULT_REGION=us-east-1
   export AWS_DB_HOST=http://localhost:8000   # IMPORTANT for PynamoDB models

Notes:

- The library auto-creates tables on first access through its PynamoDB models.
- For production, configure IAM and real AWS hosts (do not set `AWS_DB_HOST`).

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

