==========
Quickstart
==========

This 3–5 minute tour shows how to spin up a minimal app, create an actor, and browse the web UI.

1) Minimal app (choose one)
===========================

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

    aw.integrate_fastapi(api, templates_dir="templates")

    # Run with: uvicorn app_fastapi:api --reload --port 5000

2) Create an actor
==================

Use the root factory page in the browser and follow the form, or create via API:

.. code-block:: bash

    # Create new actor (no auth in dev)
    curl -X POST http://localhost:5000/

The response contains the new actor ID. The actor root is ``http://localhost:5000/<actor_id>``.

3) Explore
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

- Configuration reference: identity, auth (OAuth2), DB, base paths → :doc:`configuration`
- Routing overview: generated routes and structure → :doc:`routing-overview`
- Developer API: high‑level interfaces and hooks → :doc:`developers`
- MCP apps: add AI‑client access when needed → :doc:`mcp-applications`
