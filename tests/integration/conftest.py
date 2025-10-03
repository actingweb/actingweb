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
import time
import pytest
import requests
import subprocess
from typing import Dict, List, Optional
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

# Test configuration
TEST_DYNAMODB_HOST = "http://localhost:8001"
TEST_APP_HOST = "localhost"
TEST_APP_PORT = 5555
TEST_APP_URL = f"http://{TEST_APP_HOST}:{TEST_APP_PORT}"


@pytest.fixture(scope="session")
def docker_services():
    """
    Start DynamoDB via Docker Compose for the test session.

    Yields after DynamoDB is ready, cleans up on session end.
    """
    # Start Docker Compose
    subprocess.run(
        ["docker-compose", "-f", "docker-compose.test.yml", "up", "-d"],
        check=True,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )

    # Wait for DynamoDB to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get(f"{TEST_DYNAMODB_HOST}/", timeout=2)
            if response.status_code in [200, 400]:  # DynamoDB responds with 400 to /
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("DynamoDB failed to start within 30 seconds")

    yield

    # Cleanup: Stop Docker Compose
    subprocess.run(
        ["docker-compose", "-f", "docker-compose.test.yml", "down", "-v"],
        check=False,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )


@pytest.fixture(scope="session")
def test_app(docker_services):
    """
    Start the test harness Flask application for the test session.

    Returns the base URL for making requests.
    """
    from .test_harness import create_test_app
    from threading import Thread

    # Set environment for DynamoDB
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = "test"

    # Create app
    flask_app, aw_app = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{TEST_APP_PORT}",
        proto="http://",
        enable_oauth=True,
        enable_mcp=True,
        enable_devtest=True,
    )

    # Run in background thread
    def run_app():
        flask_app.run(host="0.0.0.0", port=TEST_APP_PORT, use_reloader=False)

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for i in range(max_retries):
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
def www_test_app(docker_services):
    """
    Start a test harness Flask application WITHOUT OAuth for www template testing.

    This allows testing www templates with basic auth instead of OAuth redirects.
    Returns the base URL for making requests.
    """
    from .test_harness import create_test_app
    from threading import Thread

    # Use a different port for www testing
    WWW_TEST_PORT = 5557
    WWW_TEST_URL = f"http://{TEST_APP_HOST}:{WWW_TEST_PORT}"

    # Set environment for DynamoDB (same as test_app)
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = "test"

    # Create app WITHOUT OAuth
    flask_app, aw_app = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{WWW_TEST_PORT}",
        proto="http://",
        enable_oauth=False,  # Disable OAuth for www testing
        enable_mcp=False,
        enable_devtest=True,
    )

    # Run in background thread
    def run_app():
        flask_app.run(host="0.0.0.0", port=WWW_TEST_PORT, use_reloader=False)

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for i in range(max_retries):
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
def peer_app(docker_services):
    """
    Start a second test harness Flask application on a different port.

    This acts as a peer actor for testing trust relationships.
    Returns the base URL for making requests.
    """
    from .test_harness import create_test_app
    from threading import Thread

    PEER_APP_HOST = "localhost"
    PEER_APP_PORT = 5556
    PEER_APP_URL = f"http://{PEER_APP_HOST}:{PEER_APP_PORT}"

    # Create peer app (shares same DynamoDB as main app)
    flask_app, aw_app = create_test_app(
        fqdn=f"{PEER_APP_HOST}:{PEER_APP_PORT}",
        proto="http://",
        enable_oauth=True,
        enable_mcp=True,
        enable_devtest=True,
    )

    # Run in background thread
    def run_app():
        flask_app.run(host="0.0.0.0", port=PEER_APP_PORT, use_reloader=False)

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for i in range(max_retries):
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
        self.actors: List[Dict] = []

    def create(self, creator: str, passphrase: Optional[str] = None) -> Dict:
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
            from_actor: Dict,
            to_actor: Dict,
            relationship: str = "friend",
            approve: bool = True,
        ) -> Dict:
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
                raise RuntimeError(
                    f"Failed to initiate trust: {response.status_code}"
                )

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


