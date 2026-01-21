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

Parallel Test Isolation Patterns
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When writing tests that run in parallel with ``pytest-xdist``, use these patterns to ensure isolation:

**1. xdist_group Marker** - Keep related tests on the same worker:

.. code-block:: python

   import pytest

   # Module-level marker: All tests in this module run on the same worker
   pytestmark = pytest.mark.xdist_group(name="my_group")

   # Or class-level marker:
   @pytest.mark.xdist_group(name="my_flow")
   class TestMyFlow:
       def test_step_1(self): ...
       def test_step_2(self): ...

Use xdist_group when:

- Tests share class-level state
- Tests use ``unittest.mock.patch()`` on the same module (patches can conflict across workers)
- Tests must run in a specific order

**2. Module Patching** - When multiple test modules patch the same import:

.. code-block:: python

   # test_module_a.py and test_module_b.py both patch actingweb.attribute.Attributes
   # They MUST use the same xdist_group name to run on the same worker

   # In test_module_a.py:
   pytestmark = pytest.mark.xdist_group(name="attribute_patching")

   # In test_module_b.py:
   pytestmark = pytest.mark.xdist_group(name="attribute_patching")

**3. Worker-Specific Prefixes** - For integration tests needing unique resources:

.. code-block:: python

   @pytest.fixture
   def unique_email(worker_info):
       """Generate a unique email per worker to avoid conflicts."""
       return f"test_{worker_info['worker_id']}_{uuid.uuid4().hex[:8]}@example.com"

**4. Distribution Mode** - The Makefile uses ``--dist loadgroup`` which respects xdist_group markers.

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Mode
     - Behavior
     - Use Case
   * - ``loadgroup``
     - Respects ``@pytest.mark.xdist_group``
     - Default (recommended)
   * - ``loadscope``
     - Groups by module/class scope only
     - Ignores xdist_group markers
   * - ``load``
     - Distributes tests evenly
     - Maximum parallelism, no grouping

See ``tests/integration/conftest.py`` for comprehensive isolation patterns used in integration tests.

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

Automated Testing with Playwright/Selenium
------------------------------------------

For end-to-end testing with browser automation tools like Playwright or Selenium, ActingWeb provides
a passphrase-to-SPA-token exchange endpoint that bypasses the OAuth2 flow.

.. warning::

   This endpoint is **only available when devtest mode is enabled** (``with_devtest(enable=True)``).
   It returns HTTP 403 when devtest is disabled, protecting production environments.

Obtaining SPA Tokens via Passphrase
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Exchange a creator passphrase for SPA tokens:

.. code-block:: python

   import requests

   # Create an actor (or use existing one)
   create_response = requests.post(
       "http://localhost:5000/",
       json={"creator": "test@example.com"}
   )
   actor = create_response.json()
   actor_id = actor["id"]
   passphrase = actor["passphrase"]

   # Exchange passphrase for SPA tokens
   token_response = requests.post(
       "http://localhost:5000/oauth/spa/token",
       json={
           "grant_type": "passphrase",
           "actor_id": actor_id,
           "passphrase": passphrase,
       }
   )
   tokens = token_response.json()
   access_token = tokens["access_token"]
   refresh_token = tokens["refresh_token"]

   # Use the token to access actor resources
   props_response = requests.get(
       f"http://localhost:5000/{actor_id}/properties",
       headers={"Authorization": f"Bearer {access_token}"}
   )

Token Delivery Modes
~~~~~~~~~~~~~~~~~~~~

The endpoint supports three token delivery modes:

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Mode
     - Behavior
     - Use Case
   * - ``json`` (default)
     - Both tokens in response body
     - API testing, programmatic access
   * - ``cookie``
     - Tokens set as HttpOnly cookies
     - Browser-based testing with cookie auth
   * - ``hybrid``
     - Access token in body, refresh in cookie
     - SPAs that store access token in memory

Example with cookie mode for Playwright:

.. code-block:: python

   # Get tokens as cookies
   token_response = requests.post(
       "http://localhost:5000/oauth/spa/token",
       json={
           "grant_type": "passphrase",
           "actor_id": actor_id,
           "passphrase": passphrase,
           "token_delivery": "cookie",
       }
   )

   # Extract cookies for Playwright
   cookies = token_response.cookies
   # Set these cookies in Playwright browser context

Playwright Integration Example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from playwright.sync_api import sync_playwright
   import requests

   def test_authenticated_page():
       # Setup: Create actor and get tokens
       actor = create_test_actor()
       token_response = requests.post(
           f"{BASE_URL}/oauth/spa/token",
           json={
               "grant_type": "passphrase",
               "actor_id": actor["id"],
               "passphrase": actor["passphrase"],
               "token_delivery": "cookie",
           }
       )

       with sync_playwright() as p:
           browser = p.chromium.launch()
           context = browser.new_context()

           # Set authentication cookies from token response
           for cookie in token_response.cookies:
               context.add_cookies([{
                   "name": cookie.name,
                   "value": cookie.value,
                   "domain": "localhost",
                   "path": "/",
               }])

           page = context.new_page()
           page.goto(f"{BASE_URL}/{actor['id']}/www")

           # Page is now authenticated - test your UI
           assert page.locator("h1").text_content() == "Dashboard"

           browser.close()

Response Format
~~~~~~~~~~~~~~~

Successful response (HTTP 200):

.. code-block:: json

   {
     "success": true,
     "actor_id": "<actor_id>",
     "access_token": "<token>",
     "refresh_token": "<token>",
     "token_type": "Bearer",
     "expires_in": 3600,
     "expires_at": 1705847200,
     "refresh_token_expires_in": 1209600
   }

Error responses:

- **400**: Missing required parameter (``actor_id`` or ``passphrase``)
- **401**: Invalid passphrase
- **403**: Devtest mode not enabled
- **404**: Actor not found

Mocking AWS/DynamoDB
--------------------

- Unit tests should not depend on live AWS. Prefer mocking the DB layer or running with DynamoDB Local.
- If using DynamoDB Local in CI, set `AWS_DB_HOST` and related env vars as shown in :doc:`local-dev-setup`.

Coverage
--------

Run tests with coverage (project default threshold is 80%):

.. code-block:: bash

   poetry run pytest


Testing Subscription Processing
-------------------------------

When testing applications using subscription processing (``.with_subscription_processing()``), use these patterns.

Enabling Subscription Processing in Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the test harness with ``enable_subscription_processing=True``:

.. code-block:: python

   from tests.integration.test_harness import create_test_app

   def test_subscription_callbacks():
       """Test with subscription processing enabled."""
       fastapi_app, aw_app = create_test_app(
           fqdn="localhost:5555",
           proto="http://",
           enable_subscription_processing=True,
           subscription_config={
               "auto_sequence": True,
               "auto_storage": True,
               "auto_cleanup": True,
               "gap_timeout_seconds": 1.0,  # Fast for tests
               "max_pending": 50,
           }
       )

       client = TestClient(fastapi_app)
       # ... test subscription flows

Simulating Callbacks with Devtest Endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In devtest mode, use the ``devtest`` endpoints to inspect subscription state:

.. code-block:: python

   def test_callback_state_inspection():
       """Inspect callback processing state via devtest."""
       fastapi_app, aw_app = create_test_app(
           enable_subscription_processing=True,
           enable_devtest=True,  # Required for devtest endpoints
       )
       client = TestClient(fastapi_app)

       # Create actor and subscription setup...

       # Inspect callback state (devtest only)
       response = client.get(
           f"/{actor_id}/devtest/callback_state/{peer_id}/{subscription_id}",
           auth=("creator", "passphrase")
       )
       assert response.status_code == 200
       state = response.json()
       assert "last_sequence" in state
       assert "pending_count" in state

Sending Test Callbacks
~~~~~~~~~~~~~~~~~~~~~~

Use the standard subscription callback endpoint:

.. code-block:: python

   def test_callback_processing():
       """Send a callback and verify processing."""
       # Setup publisher and subscriber actors...

       # Send callback in ActingWeb protocol format
       callback_data = {
           "id": publisher_id,
           "subscriptionid": subscription_id,
           "sequence": 1,
           "target": "properties",
           "data": {"status": "active"},
           "timestamp": "2026-01-20T12:00:00Z"
       }

       response = client.post(
           f"/{subscriber_id}/callbacks",
           json=callback_data,
           auth=(peer_token, "")  # Trust token from subscription
       )

       # 201 = processed, 200 = duplicate, 202 = pending, 429 = backpressure
       assert response.status_code in [200, 201, 202]

Testing Sequence Handling
~~~~~~~~~~~~~~~~~~~~~~~~~

Test out-of-order callbacks and gap detection:

.. code-block:: python

   @pytest.mark.xdist_group(name="subscription_flow")
   class TestCallbackSequencing:
       """Test callback sequencing behavior."""

       def test_out_of_order_triggers_pending(self, subscriber_client, callback_auth):
           """Callbacks arriving out of order should be queued."""
           # Send sequence 1
           response = send_callback(subscriber_client, callback_auth, sequence=1)
           assert response.status_code == 201  # Processed

           # Send sequence 3 (gap - missing 2)
           response = send_callback(subscriber_client, callback_auth, sequence=3)
           assert response.status_code == 202  # Pending

           # Send sequence 2 (fill gap)
           response = send_callback(subscriber_client, callback_auth, sequence=2)
           assert response.status_code == 201  # Processed (and 3 auto-processed)

       def test_duplicate_rejected(self, subscriber_client, callback_auth):
           """Duplicate sequence numbers should be rejected."""
           # Send sequence 1 twice
           response = send_callback(subscriber_client, callback_auth, sequence=1)
           assert response.status_code == 201

           response = send_callback(subscriber_client, callback_auth, sequence=1)
           assert response.status_code == 200  # Duplicate

Testing RemotePeerStore
~~~~~~~~~~~~~~~~~~~~~~~

Verify peer data storage:

.. code-block:: python

   from actingweb.remote_storage import RemotePeerStore

   def test_peer_data_storage():
       """Verify RemotePeerStore operations."""
       actor = ActorInterface.get_by_id(actor_id, config)
       store = RemotePeerStore(actor, peer_id)

       # Test scalar values
       store.set_value("status", {"active": True})
       assert store.get_value("status") == {"active": True}

       # Test lists
       store.set_list("items", [{"id": 1}, {"id": 2}])
       assert len(store.get_list("items")) == 2

       # Test list operations
       store.apply_list_operation("items", {
           "operation": "append",
           "items": [{"id": 3}]
       })
       assert len(store.get_list("items")) == 3

       # Test cleanup
       store.delete_all()
       assert store.get_value("status") is None

Testing Auto-Cleanup
~~~~~~~~~~~~~~~~~~~~

Verify peer data is cleaned up when trust is deleted:

.. code-block:: python

   def test_trust_deletion_cleans_peer_data():
       """Verify auto_cleanup removes peer data on trust deletion."""
       # Setup with auto_cleanup=True
       fastapi_app, aw_app = create_test_app(
           enable_subscription_processing=True,
           subscription_config={"auto_cleanup": True}
       )

       # Create trust and store peer data...
       store = RemotePeerStore(actor, peer_id)
       store.set_value("test", {"data": "value"})
       assert store.get_value("test") is not None

       # Delete trust
       actor.trust.delete_peer_trust(peer_id)

       # Verify cleanup
       assert store.get_value("test") is None

Test Isolation for Subscription Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subscription tests often need specific isolation due to shared state:

.. code-block:: python

   import pytest

   # Group subscription flow tests together
   pytestmark = pytest.mark.xdist_group(name="subscription_processing")

   class TestSubscriptionProcessingFlow:
       """Tests that must run on the same worker."""

       @pytest.fixture(autouse=True)
       def setup_flow(self, request):
           """Setup and teardown for each test."""
           # Setup
           self.actor = create_test_actor()
           self.peer = create_test_peer()
           establish_trust(self.actor, self.peer)

           yield

           # Teardown - clean up subscriptions and trust
           cleanup_test_data(self.actor, self.peer)

       def test_subscribe_and_receive_callback(self): ...
       def test_unsubscribe_stops_callbacks(self): ...
       def test_resync_after_gap(self): ...


See Also
--------

- :doc:`backend-testing` - Database backend testing strategy and coverage
- :doc:`../quickstart/local-dev-setup` - Local development setup
- :doc:`../reference/database-backends` - Database backend comparison

