"""
Shared pytest fixtures for ActingWeb REST integration tests.

These fixtures provide:
- Docker services (DynamoDB)
- Test harness application
- HTTP client with base URL
- Actor factory with automatic cleanup
- Trust relationship helpers
- Mock for trust verification (to avoid 408 timeouts)
- Worker-specific isolation for parallel test execution
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


def get_worker_id(request) -> str:
    """
    Get the xdist worker ID for this test process.

    Returns:
        Worker ID string (e.g., 'gw0', 'gw1', 'master')
    """
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["workerid"]
    return "master"


def get_worker_number(worker_id: str) -> int:
    """
    Extract numeric worker number from worker ID.

    Args:
        worker_id: Worker ID string (e.g., 'gw0', 'gw1', 'master')

    Returns:
        Worker number (0 for master, 1-N for workers)
    """
    if worker_id == "master":
        return 0
    if worker_id.startswith("gw"):
        try:
            return int(worker_id[2:]) + 1
        except ValueError:
            return 0
    return 0


# Test configuration
# Use AWS_DB_HOST from environment if set (for CI), otherwise use local default
TEST_DYNAMODB_HOST = os.environ.get("AWS_DB_HOST", "http://localhost:8001")
TEST_APP_HOST = "localhost"
# Base ports - will be offset by worker number for parallel execution
BASE_APP_PORT = 5555
BASE_PEER_PORT = 5556
BASE_WWW_PORT = 5557


@pytest.fixture(scope="session")
def worker_info(request) -> dict:
    """
    Provide worker-specific configuration for parallel test execution.

    Returns:
        Dict with 'worker_id', 'worker_num', 'db_prefix', 'port_offset'
    """
    worker_id = get_worker_id(request)
    worker_num = get_worker_number(worker_id)

    return {
        "worker_id": worker_id,
        "worker_num": worker_num,
        "db_prefix": f"test_w{worker_num}_",
        "port_offset": worker_num * 10,  # Each worker gets 10 ports
    }


@pytest.fixture(scope="session")
def docker_services():
    """
    Start DynamoDB via Docker Compose for the test session.

    If DynamoDB is already running (e.g., in CI), skips docker-compose setup.
    Yields after DynamoDB is ready, cleans up on session end.

    Note: DynamoDB is shared across all workers for parallel execution.
    Worker isolation is achieved through database table prefixes.
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
def test_app(docker_services, worker_info):  # pylint: disable=unused-argument
    """
    Start the test harness FastAPI application for the test session.

    Uses worker-specific port and database prefix for parallel execution.
    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    # Worker-specific configuration
    test_app_port = BASE_APP_PORT + worker_info["port_offset"]
    test_app_url = f"http://{TEST_APP_HOST}:{test_app_port}"

    # Set environment for DynamoDB with worker-specific prefix
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

    # Create app
    fastapi_app, _ = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{test_app_port}",
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
            port=test_app_port,
            log_level="error",  # Suppress logs during tests
        )

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{test_app_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError(f"Test app failed to start on port {test_app_port} within 30 seconds")

    return test_app_url


@pytest.fixture(scope="session")
def www_test_app(docker_services, worker_info):  # pylint: disable=unused-argument
    """
    Start a test harness FastAPI application WITHOUT OAuth for www template testing.

    Uses worker-specific port for parallel execution.
    This allows testing www templates with basic auth instead of OAuth redirects.
    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    # Worker-specific port for www testing
    www_test_port = BASE_WWW_PORT + worker_info["port_offset"]
    www_test_url = f"http://{TEST_APP_HOST}:{www_test_port}"

    # Set environment for DynamoDB (uses same prefix as test_app for this worker)
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

    # Create app WITHOUT OAuth
    fastapi_app, _ = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{www_test_port}",
        proto="http://",
        enable_oauth=False,  # Disable OAuth for www testing
        enable_mcp=False,
        enable_devtest=True,
    )

    # Run in background thread with uvicorn
    def run_app():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=www_test_port, log_level="error")

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{www_test_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError(f"WWW test app failed to start on port {www_test_port} within 30 seconds")

    return www_test_url


@pytest.fixture(scope="session")
def peer_app(docker_services, worker_info):  # pylint: disable=unused-argument
    """
    Start a second test harness FastAPI application on a different port.

    Uses worker-specific port for parallel execution.
    This acts as a peer actor for testing trust relationships.
    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    # Worker-specific port for peer app
    peer_app_port = BASE_PEER_PORT + worker_info["port_offset"]
    peer_app_url = f"http://{TEST_APP_HOST}:{peer_app_port}"

    # Create peer app (shares same DynamoDB prefix as main app for this worker)
    fastapi_app, _ = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{peer_app_port}",
        proto="http://",
        enable_oauth=True,
        enable_mcp=True,
        enable_devtest=True,
    )

    # Run in background thread with uvicorn
    def run_app():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=peer_app_port, log_level="error")

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{peer_app_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError(f"Peer app failed to start on port {peer_app_port} within 30 seconds")

    return peer_app_url


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

    def __init__(self, base_url: str, worker_id: str = "master"):
        self.base_url = base_url
        self.worker_id = worker_id
        self.actors: list[dict] = []
        self._counter = 0

    def create(self, creator: str, passphrase: str | None = None) -> dict:
        """
        Create a test actor with unique email for parallel execution.

        If creator doesn't contain a UUID, adds a unique suffix based on worker ID
        and counter to ensure uniqueness across parallel workers.

        Returns:
            Dict with 'id', 'url', 'creator', 'passphrase'
        """
        import uuid

        # Make email unique by adding worker ID and counter if not already unique
        if "@" in creator and "_" not in creator.split("@")[0]:
            # Extract email parts
            local, domain = creator.split("@", 1)
            # Add worker ID and counter for uniqueness
            unique_id = uuid.uuid4().hex[:8]
            self._counter += 1
            unique_creator = f"{local}_{self.worker_id}_{self._counter}_{unique_id}@{domain}"
        else:
            # Already has unique identifier or not an email
            unique_creator = creator

        body = {"creator": unique_creator}
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
def actor_factory(test_app: str, worker_info: dict):
    """
    Factory fixture for creating test actors with automatic cleanup.

    Generates unique actor emails per worker for parallel test execution.

    Usage:
        def test_something(actor_factory):
            actor = actor_factory.create("test@example.com")
            # actor["id"], actor["url"], actor["passphrase"] available
            # Email will be automatically made unique with worker ID
    """
    manager = ActorManager(test_app, worker_info["worker_id"])
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
                        f"Failed to approve trust from to_actor: {response.status_code}"
                    )

                # Also approve from from_actor's side to establish mutual trust
                peer_id = trust["peerid"]
                from_actor_approval_url = (
                    f"{from_actor['url']}/trust/{relationship}/{peer_id}"
                )
                response = requests.put(
                    from_actor_approval_url,
                    json={"approved": True},
                    auth=(from_actor["creator"], from_actor["passphrase"]),
                )

                if response.status_code not in [200, 204]:
                    raise RuntimeError(
                        f"Failed to approve trust from from_actor: {response.status_code}"
                    )

            return trust

    return TrustHelper()
