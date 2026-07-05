==========
Quickstart
==========

This 3–5 minute tour shows how to spin up a minimal app, create an actor, and browse the web UI.

Install
-------

.. code-block:: bash

    # Minimal
    pip install actingweb

    # Flask or FastAPI integration
    pip install 'actingweb[flask]'
    pip install 'actingweb[fastapi]'

    # Everything (incl. MCP)
    pip install 'actingweb[all]'

1) Start a database
===================

ActingWeb needs a database backend. For local development the quickest option is
**DynamoDB Local** in Docker:

.. code-block:: bash

    docker run -p 8000:8000 amazon/dynamodb-local

    # Point ActingWeb at it (dummy AWS creds are fine for the local emulator)
    export AWS_DB_HOST=http://localhost:8000
    export AWS_ACCESS_KEY_ID=local
    export AWS_SECRET_ACCESS_KEY=local
    export AWS_DEFAULT_REGION=us-east-1

Prefer PostgreSQL? Set ``database="postgresql"`` (or ``DATABASE_BACKEND=postgresql``)
and see :doc:`local-dev-setup` and :doc:`../reference/database-backends`. ActingWeb
creates the tables it needs on first use.

2) Minimal app (choose one)
===========================

Both apps enable the built-in web UI with ``with_web_ui(True)``. ActingWeb ships
default templates, so the sign-in/factory page, actor dashboard, properties, and
trust pages render **out of the box** — no templates required. To customise the
look, drop a same-named template into your app's ``templates/`` directory (Flask)
or the ``templates_dir`` you pass to ``integrate_fastapi`` (FastAPI); yours
overrides the library default.

Flask
-----

.. code-block:: python

    # app_flask.py
    from flask import Flask
    from actingweb.interface import ActingWebApp

    app = Flask(__name__)

    aw = ActingWebApp(
        aw_type="urn:actingweb:example.com:quickstart",
        database="dynamodb",
        fqdn="localhost:5000",
    ).with_web_ui(True)

    aw.integrate_flask(app)

    if __name__ == "__main__":
        app.run(host="0.0.0.0", port=5000, debug=True)

FastAPI
-------

.. code-block:: python

    # app_fastapi.py
    from fastapi import FastAPI
    from actingweb.interface import ActingWebApp

    api = FastAPI()

    aw = ActingWebApp(
        aw_type="urn:actingweb:example.com:quickstart",
        database="dynamodb",
        fqdn="localhost:5000",
    ).with_web_ui(True)

    aw.integrate_fastapi(api)  # add templates_dir="templates" to override defaults

    # Run with: uvicorn app_fastapi:api --reload --port 5000

3) Create an actor
==================

Open ``http://localhost:5000/`` in a browser and use the built-in sign-in/factory
page, or create one via the API:

.. code-block:: bash

    # Create new actor (no auth in dev)
    curl -X POST http://localhost:5000/ \
      -H 'Content-Type: application/json' \
      -d '{"creator": "you@example.com"}'

The response contains the new actor ID. The actor root is ``http://localhost:5000/<actor_id>``.

4) Explore
==========

- Web UI: ``/<actor_id>/www`` — dashboard, properties, and trust management
- API:

  .. code-block:: bash

      # Meta
      curl http://localhost:5000/<actor_id>/meta

      # Properties
      curl -X POST http://localhost:5000/<actor_id>/properties \
        -H 'Content-Type: application/json' \
        -d '{"status": "active"}'

Where to next
=============

- Local dev setup: install extras, DynamoDB Local → :doc:`local-dev-setup`
- Configuration reference: identity, auth (OAuth2), DB, base paths → :doc:`configuration`
- Routing overview: generated routes and structure → :doc:`../reference/routing-overview`
- Developer API: high‑level interfaces and hooks → :doc:`../sdk/developer-api`
- MCP apps: add AI‑client access when needed → :doc:`../guides/mcp-applications`
- MCP quickstart: minimal server with tools/prompts → :doc:`../guides/mcp-quickstart`