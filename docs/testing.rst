=======
Testing
=======

This guide shows how to test ActingWeb applications efficiently without hitting external services.

Unit Testing Hooks
------------------

Hooks are regular functions; test them in isolation:

.. code-block:: python

   from actingweb.interface import ActingWebApp, ActorInterface

   def test_email_hook_lowercases():
       app = ActingWebApp(aw_type="urn:test", database="dynamodb")

       @app.property_hook("email")
       def handle_email(actor, operation, value, path):
           return value.lower() if operation == "put" else value

       actor = ActorInterface.create(creator="test@example.com", config=app.get_config())
       assert handle_email(actor, "put", "TEST@EXAMPLE.COM", []) == "test@example.com"

FastAPI Integration Tests
-------------------------

Use FastAPI's `TestClient` to test HTTP routes without a server:

.. code-block:: python

   from fastapi.testclient import TestClient
   from myapp import api  # Your FastAPI app with ActingWeb integrated

   def test_health_and_mcp():
       client = TestClient(api)
       assert client.get("/health").status_code == 200
       # Unauthenticated MCP gives 401 with WWW-Authenticate
       r = client.post("/mcp", json={"jsonrpc":"2.0","id":1,"method":"tools/list"})
       assert r.status_code in (200, 401)

Mocking AWS/DynamoDB
--------------------

- Unit tests should not depend on live AWS. Prefer mocking the DB layer or running with DynamoDB Local.
- If using DynamoDB Local in CI, set `AWS_DB_HOST` and related env vars as shown in :doc:`local-dev-setup`.

Coverage
--------

Run tests with coverage (project default threshold is 80%):

.. code-block:: bash

   poetry run pytest

