=======
Testing
=======

This guide covers testing strategies for ActingWeb library development and application testing.

Test Execution Modes
--------------------

ActingWeb has 900+ tests with two execution modes offering different tradeoffs:

Sequential Testing (Recommended for CI)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   make test-integration        # ~5 min - Most reliable, best for CI
   make test-integration-fast   # ~3 min - Skip slow tests

**Pros**: Better test isolation, more reliable
**Cons**: Slower execution time

Parallel Testing (Recommended for Development)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   make test-parallel           # ~2 min - Fast iteration during development
   make test-parallel-fast      # ~1 min - Quick feedback loop
   make test-all-parallel       # ~4 min - ALL tests (unit + integration)

**Pros**: 2-3x faster execution
**Cons**: May have occasional test isolation issues in parallel runs

Before Committing
~~~~~~~~~~~~~~~~~

**ALWAYS run the full test suite before committing:**

.. code-block:: bash

   make test-all-parallel       # Run ALL tests (unit + integration)

This ensures:

- All 900+ tests pass
- No regressions introduced
- Both unit and integration tests validated

Test Isolation Notes
~~~~~~~~~~~~~~~~~~~~

**Known Issues with Parallel Execution**:

- Some MCP OAuth2 tests may fail with "Token exchange failed: server_error" when run in parallel
- OAuth2 client token tests may show intermittent failures in parallel mode
- These tests pass reliably when run individually or sequentially

**If parallel tests fail**:

1. Re-run with sequential mode: ``make test-integration``
2. If sequential passes → test isolation issue (not a bug)
3. If sequential also fails → investigate the actual failure

Test Organization
~~~~~~~~~~~~~~~~~

.. code-block:: text

   tests/
   ├── integration/        # Integration tests (require DynamoDB)
   │   ├── test_*.py      # Test files organized by feature
   │   └── conftest.py    # Shared fixtures
   └── test_*.py          # Unit tests (no external dependencies)

Running Specific Tests
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Run single test file
   poetry run pytest tests/integration/test_oauth2_security.py -v

   # Run single test class
   poetry run pytest tests/integration/test_oauth2_security.py::TestCrossActorAuthorizationPrevention -v

   # Run single test method
   poetry run pytest tests/integration/test_oauth2_security.py::TestCrossActorAuthorizationPrevention::test_self_authorization_succeeds -v

   # Run tests matching pattern
   poetry run pytest tests/ -k "oauth" -v

Performance Benchmarks
~~~~~~~~~~~~~~~~~~~~~~

Performance benchmark tests are marked with ``@pytest.mark.benchmark`` and are **excluded from parallel test runs** in CI/CD because benchmarks require sequential execution for accurate measurements.

.. code-block:: bash

   # Run benchmark tests (must be run WITHOUT -n flag)
   DATABASE_BACKEND=postgresql poetry run pytest -m benchmark -v

   # Run benchmarks and save results to JSON for comparison
   DATABASE_BACKEND=postgresql poetry run pytest -m benchmark --benchmark-json=pg_results.json
   DATABASE_BACKEND=dynamodb poetry run pytest -m benchmark --benchmark-json=db_results.json

**Note**: Benchmarks are automatically disabled when using ``pytest-xdist`` parallel execution (``-n`` flag). Always run benchmarks sequentially.

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



See Also
--------

- :doc:`backend-testing` - Database backend testing strategy and coverage
- :doc:`../quickstart/local-dev-setup` - Local development setup
- :doc:`../reference/database-backends` - Database backend comparison

