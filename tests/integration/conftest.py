"""
Shared pytest fixtures for ActingWeb REST integration tests.

These fixtures provide:
- Docker services (DynamoDB)
- Test harness application
- HTTP client with base URL
- Actor factory with automatic cleanup
- Trust relationship helpers
- Mock for trust verification (to avoid 408 timeouts)
"""

import os
import subprocess
import time

import pytest
import requests


def pytest_collection_modifyitems(items):
    """Auto-mark all tests in this directory with 'integration' marker."""
    for item in items:
        # Check if test is in the integration directory
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

# Test configuration
# Use AWS_DB_HOST from environment if set (for CI), otherwise use local default
TEST_DYNAMODB_HOST = os.environ.get("AWS_DB_HOST", "http://localhost:8001")
TEST_APP_HOST = "localhost"
TEST_APP_PORT = 5555
TEST_APP_URL = f"http://{TEST_APP_HOST}:{TEST_APP_PORT}"


@pytest.fixture(scope="session")
def docker_services():
    """
    Start DynamoDB via Docker Compose for the test session.

    If DynamoDB is already running (e.g., in CI), skips docker-compose setup.
    Yields after DynamoDB is ready, cleans up on session end.
    """
    # Check if DynamoDB is already running
    dynamodb_already_running = False
    try:
        response = requests.get(f"{TEST_DYNAMODB_HOST}/", timeout=2)
        if response.status_code in [200, 400]:  # DynamoDB responds with 400 to /
            print(f"DynamoDB already running at {TEST_DYNAMODB_HOST}")
            dynamodb_already_running = True
    except requests.exceptions.ConnectionError:
        pass

    started_docker_compose = False
    if not dynamodb_already_running:
        # Start Docker Compose
        print(f"Starting DynamoDB via docker-compose at {TEST_DYNAMODB_HOST}")
        subprocess.run(
            ["docker-compose", "-f", "docker-compose.test.yml", "up", "-d"],
            check=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        started_docker_compose = True

        # Wait for DynamoDB to be ready
        max_retries = 30
        for _ in range(max_retries):
            try:
                response = requests.get(f"{TEST_DYNAMODB_HOST}/", timeout=2)
                if response.status_code in [
                    200,
                    400,
                ]:  # DynamoDB responds with 400 to /
                    break
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("DynamoDB failed to start within 30 seconds")

    yield

    # Cleanup: Stop Docker Compose only if we started it
    if started_docker_compose:
        print("Stopping docker-compose services")
        subprocess.run(
            ["docker-compose", "-f", "docker-compose.test.yml", "down", "-v"],
            check=False,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )


@pytest.fixture(scope="session")
def test_app(docker_services):  # pylint: disable=unused-argument
    """
    Start the test harness FastAPI application for the test session.

    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    # Set environment for DynamoDB
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = "test"

    # Create app
    fastapi_app, _ = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{TEST_APP_PORT}",
        proto="http://",
        enable_oauth=True,
        enable_mcp=True,
        enable_devtest=True,
    )

    # Run in background thread with uvicorn
    def run_app():
        uvicorn.run(
            fastapi_app,
            host="0.0.0.0",
            port=TEST_APP_PORT,
            log_level="error",  # Suppress logs during tests
        )

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{TEST_APP_URL}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Test app failed to start within 30 seconds")

    return TEST_APP_URL


@pytest.fixture(scope="session")
def www_test_app(docker_services):  # pylint: disable=unused-argument
    """
    Start a test harness FastAPI application WITHOUT OAuth for www template testing.

    This allows testing www templates with basic auth instead of OAuth redirects.
    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    # Use a different port for www testing
    WWW_TEST_PORT = 5557
    WWW_TEST_URL = f"http://{TEST_APP_HOST}:{WWW_TEST_PORT}"

    # Set environment for DynamoDB (same as test_app)
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = "test"

    # Create app WITHOUT OAuth
    fastapi_app, _ = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{WWW_TEST_PORT}",
        proto="http://",
        enable_oauth=False,  # Disable OAuth for www testing
        enable_mcp=False,
        enable_devtest=True,
    )

    # Run in background thread with uvicorn
    def run_app():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=WWW_TEST_PORT, log_level="error")

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{WWW_TEST_URL}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("WWW test app failed to start within 30 seconds")

    return WWW_TEST_URL


@pytest.fixture(scope="session")
def peer_app(docker_services):  # pylint: disable=unused-argument
    """
    Start a second test harness FastAPI application on a different port.

    This acts as a peer actor for testing trust relationships.
    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    PEER_APP_HOST = "localhost"
    PEER_APP_PORT = 5556
    PEER_APP_URL = f"http://{PEER_APP_HOST}:{PEER_APP_PORT}"

    # Create peer app (shares same DynamoDB as main app)
    fastapi_app, _ = create_test_app(
        fqdn=f"{PEER_APP_HOST}:{PEER_APP_PORT}",
        proto="http://",
        enable_oauth=True,
        enable_mcp=True,
        enable_devtest=True,
    )

    # Run in background thread with uvicorn
    def run_app():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=PEER_APP_PORT, log_level="error")

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{PEER_APP_URL}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Peer app failed to start within 30 seconds")

    return PEER_APP_URL


@pytest.fixture
def http_client(test_app: str, peer_app: str) -> requests.Session:
    """
    HTTP client for making requests to the test app.

    Returns a requests.Session with base_url and peer_url set.
    """
    session = requests.Session()
    session.base_url = test_app  # type: ignore  # Custom attribute for convenience
    session.peer_url = peer_app  # type: ignore  # Custom attribute for peer server
    return session


class ActorManager:
    """Helper class for managing test actors with automatic cleanup."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.actors: list[dict] = []

    def create(self, creator: str, passphrase: str | None = None) -> dict:
        """
        Create a test actor.

        Returns:
            Dict with 'id', 'url', 'creator', 'passphrase'
        """
        body = {"creator": creator}
        if passphrase:
            body["passphrase"] = passphrase

        response = requests.post(
            f"{self.base_url}/",
            json=body,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 201:
            raise RuntimeError(
                f"Failed to create actor: {response.status_code} {response.text}"
            )

        actor = {
            "id": response.json()["id"],
            "url": response.headers["Location"],
            "creator": response.json()["creator"],
            "passphrase": response.json()["passphrase"],
        }

        self.actors.append(actor)
        return actor

    def cleanup(self):
        """Delete all created actors."""
        for actor in self.actors:
            try:
                requests.delete(
                    actor["url"],
                    auth=(actor["creator"], actor["passphrase"]),
                )
            except Exception:
                pass  # Best effort cleanup


@pytest.fixture
def actor_factory(test_app: str):
    """
    Factory fixture for creating test actors with automatic cleanup.

    Usage:
        def test_something(actor_factory):
            actor = actor_factory.create("test@example.com")
            # actor["id"], actor["url"], actor["passphrase"] available
    """
    manager = ActorManager(test_app)
    yield manager
    manager.cleanup()


@pytest.fixture
def oauth2_client(test_app):
    """
    Create an authenticated OAuth2 client for testing OAuth2-protected endpoints.

    This fixture provides a fully authenticated client that can access /mcp, /www,
    and other OAuth2-protected endpoints.

    Returns:
        OAuth2TestHelper instance with valid access token
    """
    from .utils.oauth2_helper import create_authenticated_client

    return create_authenticated_client(test_app, client_name="Test Fixture Client")


@pytest.fixture
def trust_helper():
    """
    Helper fixture for establishing trust relationships between actors.

    Usage:
        def test_trust(actor_factory, trust_helper):
            actor1 = actor_factory.create("user1@example.com")
            actor2 = actor_factory.create("user2@example.com")
            trust = trust_helper.establish(actor1, actor2, "friend")
    """

    class TrustHelper:
        def establish(
            self,
            from_actor: dict,
            to_actor: dict,
            relationship: str = "friend",
            approve: bool = True,
        ) -> dict:
            """
            Establish trust from from_actor to to_actor.

            Returns:
                Trust relationship dict with 'secret', 'url', etc.
            """
            # Initiate trust from from_actor
            response = requests.post(
                f"{from_actor['url']}/trust",
                json={
                    "url": to_actor["url"],
                    "relationship": relationship,
                },
                auth=(from_actor["creator"], from_actor["passphrase"]),
            )

            if response.status_code != 201:
                raise RuntimeError(f"Failed to initiate trust: {response.status_code}")

            trust = response.json()
            trust["url"] = response.headers["Location"]

            # Approve trust at to_actor if requested
            if approve:
                reciprocal_url = (
                    f"{to_actor['url']}/trust/{relationship}/{from_actor['id']}"
                )
                response = requests.put(
                    reciprocal_url,
                    json={"approved": True},
                    auth=(to_actor["creator"], to_actor["passphrase"]),
                )

                if response.status_code != 204:
                    raise RuntimeError(
                        f"Failed to approve trust: {response.status_code}"
                    )

            return trust

    return TrustHelper()
