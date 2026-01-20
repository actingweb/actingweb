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

import filelock
import pytest
import requests


def _prewarm_botocore():
    """
    Pre-warm botocore's service model cache.

    Botocore lazily loads AWS service model files on first use. When multiple
    pytest-xdist workers start simultaneously and all try to load these files
    at the same time, it can cause a deadlock in os.listdir().

    This function forces botocore to load the DynamoDB service model upfront,
    before parallel workers start their test apps.
    """
    try:
        import boto3

        # Create a dummy client to force service model loading
        # This populates botocore's internal caches
        boto3.client(
            "dynamodb",
            region_name="us-east-1",
            endpoint_url="http://localhost:8001",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    except Exception:
        # If this fails, tests will still work (just potentially slower)
        pass


@pytest.fixture(scope="session", autouse=True)
def prewarm_aws_client(tmp_path_factory):
    """
    Pre-warm botocore client before parallel workers start.

    Uses a file lock to ensure only one worker does the warming,
    while others wait. This prevents the race condition where multiple
    workers try to load botocore service models simultaneously.
    """
    # Get a shared lock file path that all workers can access
    root_tmp_dir = tmp_path_factory.getbasetemp().parent
    lock_file = root_tmp_dir / "botocore_prewarm.lock"
    warmup_done = root_tmp_dir / "botocore_warmup_done"

    with filelock.FileLock(str(lock_file)):
        if not warmup_done.exists():
            # First worker to acquire lock does the warming
            _prewarm_botocore()
            warmup_done.touch()

    yield


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
# Database backend selection
DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

# DynamoDB configuration
# Use AWS_DB_HOST from environment if set (for CI), otherwise use local default
TEST_DYNAMODB_HOST = os.environ.get("AWS_DB_HOST", "http://localhost:8001")

# PostgreSQL configuration
TEST_POSTGRES_HOST = os.environ.get("PG_DB_HOST", "localhost")
TEST_POSTGRES_PORT = os.environ.get("PG_DB_PORT", "5433")
TEST_POSTGRES_DB = os.environ.get("PG_DB_NAME", "actingweb_test")
TEST_POSTGRES_USER = os.environ.get("PG_DB_USER", "actingweb")
TEST_POSTGRES_PASSWORD = os.environ.get("PG_DB_PASSWORD", "testpassword")

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
    Start database services (DynamoDB or PostgreSQL) via Docker Compose.

    If services are already running (e.g., in CI), skips docker-compose setup.
    Yields after services are ready, cleans up on session end.

    Note: Services are shared across all workers for parallel execution.
    Worker isolation is achieved through database table prefixes (DynamoDB)
    or schema prefixes (PostgreSQL).
    """
    # Determine which services to start based on DATABASE_BACKEND
    services_to_start = []
    if DATABASE_BACKEND == "dynamodb":
        services_to_start.append("dynamodb-test")
    elif DATABASE_BACKEND == "postgresql":
        services_to_start.append("postgres-test")

    # Check if services are already running
    services_already_running = False

    if DATABASE_BACKEND == "dynamodb":
        try:
            response = requests.get(f"{TEST_DYNAMODB_HOST}/", timeout=2)
            if response.status_code in [200, 400]:  # DynamoDB responds with 400 to /
                print(f"DynamoDB already running at {TEST_DYNAMODB_HOST}")
                services_already_running = True
        except requests.exceptions.ConnectionError:
            pass
    elif DATABASE_BACKEND == "postgresql":
        try:
            import psycopg

            conninfo = f"host={TEST_POSTGRES_HOST} port={TEST_POSTGRES_PORT} dbname={TEST_POSTGRES_DB} user={TEST_POSTGRES_USER} password={TEST_POSTGRES_PASSWORD}"
            with psycopg.connect(conninfo) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    print(
                        f"PostgreSQL already running at {TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}"
                    )
                    services_already_running = True
        except Exception:
            pass

    started_docker_compose = False
    if not services_already_running:
        # Start Docker Compose with specific services
        service_args = " ".join(services_to_start)
        print(f"Starting {DATABASE_BACKEND} via docker-compose")
        subprocess.run(
            f"docker-compose -f docker-compose.test.yml up -d {service_args}",
            shell=True,
            check=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        started_docker_compose = True

        # Wait for service to be ready
        max_retries = 30
        if DATABASE_BACKEND == "dynamodb":
            for _ in range(max_retries):
                try:
                    response = requests.get(f"{TEST_DYNAMODB_HOST}/", timeout=2)
                    if response.status_code in [200, 400]:
                        break
                except requests.exceptions.ConnectionError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("DynamoDB failed to start within 30 seconds")
        elif DATABASE_BACKEND == "postgresql":
            for _ in range(max_retries):
                try:
                    import psycopg

                    conninfo = f"host={TEST_POSTGRES_HOST} port={TEST_POSTGRES_PORT} dbname={TEST_POSTGRES_DB} user={TEST_POSTGRES_USER} password={TEST_POSTGRES_PASSWORD}"
                    with psycopg.connect(conninfo) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT 1")
                            break
                except Exception:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("PostgreSQL failed to start within 30 seconds")

    yield

    # Cleanup: Stop Docker Compose only if we started it
    if started_docker_compose:
        print(f"Stopping docker-compose services: {services_to_start}")
        service_args = " ".join(services_to_start)
        subprocess.run(
            f"docker-compose -f docker-compose.test.yml down {service_args}",
            shell=True,
            check=False,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )


@pytest.fixture(scope="session", autouse=True)
def setup_database(docker_services, worker_info):
    """
    Set up database for testing based on DATABASE_BACKEND.

    For PostgreSQL: Runs migrations to create tables with worker-specific schema.
    For DynamoDB: No setup needed (tables auto-created).
    """
    if DATABASE_BACKEND == "postgresql":
        # Run Alembic migrations for PostgreSQL with worker-specific schema
        schema_name = f"{worker_info['db_prefix']}public"

        # Set environment for migration
        migration_env = os.environ.copy()
        migration_env["PG_DB_HOST"] = TEST_POSTGRES_HOST
        migration_env["PG_DB_PORT"] = TEST_POSTGRES_PORT
        migration_env["PG_DB_NAME"] = TEST_POSTGRES_DB
        migration_env["PG_DB_USER"] = TEST_POSTGRES_USER
        migration_env["PG_DB_PASSWORD"] = TEST_POSTGRES_PASSWORD
        migration_env["PG_DB_PREFIX"] = worker_info["db_prefix"]
        migration_env["PG_DB_SCHEMA"] = "public"

        # Run migrations
        migrations_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "actingweb",
            "db",
            "postgresql",
        )

        print(
            f"Running Alembic migrations for worker {worker_info['worker_id']} with schema {schema_name}"
        )
        subprocess.run(
            ["poetry", "run", "alembic", "upgrade", "head"],
            cwd=migrations_dir,
            env=migration_env,
            check=True,
            capture_output=True,
        )

    yield

    # Cleanup PostgreSQL schemas after tests
    if DATABASE_BACKEND == "postgresql":
        try:
            import psycopg
            from psycopg import sql

            conninfo = f"host={TEST_POSTGRES_HOST} port={TEST_POSTGRES_PORT} dbname={TEST_POSTGRES_DB} user={TEST_POSTGRES_USER} password={TEST_POSTGRES_PASSWORD}"
            schema_name = f"{worker_info['db_prefix']}public"

            with psycopg.connect(conninfo) as conn:
                with conn.cursor() as cur:
                    # Only drop non-public schemas (worker-specific schemas)
                    if schema_name != "public":
                        cur.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                sql.Identifier(schema_name)
                            )
                        )
                conn.commit()
                print(f"Dropped schema {schema_name}")
        except Exception as e:
            print(f"Error cleaning up schema {schema_name}: {e}")


@pytest.fixture(scope="session")
def test_app(docker_services, setup_database, worker_info):  # pylint: disable=unused-argument
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

    # Set environment based on database backend
    os.environ["DATABASE_BACKEND"] = DATABASE_BACKEND

    if DATABASE_BACKEND == "dynamodb":
        # Set environment for DynamoDB with worker-specific prefix
        os.environ["AWS_ACCESS_KEY_ID"] = "test"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
        os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]
    elif DATABASE_BACKEND == "postgresql":
        # Set environment for PostgreSQL with worker-specific schema prefix
        os.environ["PG_DB_HOST"] = TEST_POSTGRES_HOST
        os.environ["PG_DB_PORT"] = TEST_POSTGRES_PORT
        os.environ["PG_DB_NAME"] = TEST_POSTGRES_DB
        os.environ["PG_DB_USER"] = TEST_POSTGRES_USER
        os.environ["PG_DB_PASSWORD"] = TEST_POSTGRES_PASSWORD
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

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

    # Wait for app to be ready with improved reliability
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{test_app_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)  # Faster polling for quicker startup detection
    else:
        raise RuntimeError(
            f"Test app failed to start on port {test_app_port} within 30 seconds"
        )

    # Warmup: make a few requests to ensure the app is fully initialized
    # This helps prevent race conditions when the first real request hits
    for _ in range(3):
        try:
            requests.get(f"{test_app_url}/", timeout=2)
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.1)

    return test_app_url


@pytest.fixture(scope="session")
def www_test_app(docker_services, setup_database, worker_info):  # pylint: disable=unused-argument
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

    # Set environment based on database backend (uses same prefix as test_app for this worker)
    os.environ["DATABASE_BACKEND"] = DATABASE_BACKEND

    if DATABASE_BACKEND == "dynamodb":
        os.environ["AWS_ACCESS_KEY_ID"] = "test"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
        os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]
    elif DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = TEST_POSTGRES_HOST
        os.environ["PG_DB_PORT"] = TEST_POSTGRES_PORT
        os.environ["PG_DB_NAME"] = TEST_POSTGRES_DB
        os.environ["PG_DB_USER"] = TEST_POSTGRES_USER
        os.environ["PG_DB_PASSWORD"] = TEST_POSTGRES_PASSWORD
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

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

    # Wait for app to be ready with improved reliability
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{www_test_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)  # Faster polling for quicker startup detection
    else:
        raise RuntimeError(
            f"WWW test app failed to start on port {www_test_port} within 30 seconds"
        )

    # Warmup: make a few requests to ensure the app is fully initialized
    for _ in range(3):
        try:
            requests.get(f"{www_test_url}/", timeout=2)
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.1)

    return www_test_url


@pytest.fixture(scope="session")
def peer_app(docker_services, setup_database, worker_info):  # pylint: disable=unused-argument
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

    # Environment already set by test_app fixture (shares same database prefix for this worker)
    # Create peer app
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

    # Wait for app to be ready with improved reliability
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{peer_app_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)  # Faster polling for quicker startup detection
    else:
        raise RuntimeError(
            f"Peer app failed to start on port {peer_app_port} within 30 seconds"
        )

    # Warmup: make a few requests to ensure the app is fully initialized
    # This is especially important for peer_app which receives trust requests
    for _ in range(3):
        try:
            requests.get(f"{peer_app_url}/", timeout=2)
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.1)

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
            unique_creator = (
                f"{local}_{self.worker_id}_{self._counter}_{unique_id}@{domain}"
            )
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


# Base port for subscriber app
BASE_SUBSCRIBER_PORT = 5558


@pytest.fixture(scope="session")
def subscriber_app(docker_services, setup_database, worker_info):  # pylint: disable=unused-argument
    """
    Start a subscriber test app with subscription processing enabled.

    Uses a different port than test_app and peer_app.
    Returns the base URL for making requests.
    """
    from threading import Thread

    import uvicorn

    from .test_harness import create_test_app

    subscriber_port = BASE_SUBSCRIBER_PORT + worker_info["port_offset"]
    subscriber_url = f"http://{TEST_APP_HOST}:{subscriber_port}"

    # Environment already set by test_app fixture
    fastapi_app, _ = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{subscriber_port}",
        proto="http://",
        enable_oauth=True,
        enable_mcp=False,
        enable_devtest=True,
        enable_subscription_processing=True,
        subscription_config={
            "auto_sequence": True,
            "auto_storage": True,
            "auto_cleanup": True,
            "gap_timeout_seconds": 2.0,  # Shorter for testing
            "max_pending": 50,
        },
    )

    # Run in background thread with uvicorn
    def run_app():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=subscriber_port, log_level="error")

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{subscriber_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError(
            f"Subscriber app failed to start on port {subscriber_port} within 30 seconds"
        )

    # Warmup
    for _ in range(3):
        try:
            requests.get(f"{subscriber_url}/", timeout=2)
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.1)

    return subscriber_url


@pytest.fixture
def callback_sender():
    """
    Helper fixture for sending subscription callbacks.

    Handles callback wrapper format per protocol spec.
    """
    from datetime import datetime, timezone

    class CallbackSender:
        def send(
            self,
            to_actor: dict,
            from_actor_id: str,
            subscription_id: str,
            sequence: int,
            data: dict,
            trust_secret: str,
            callback_type: str = "diff",
        ) -> requests.Response:
            """Send a subscription callback."""
            callback_url = f"{to_actor['url']}/callbacks/subscriptions/{from_actor_id}/{subscription_id}"

            payload = {
                "id": from_actor_id,
                "target": "properties",
                "sequence": sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "granularity": "high",
                "subscriptionid": subscription_id,
                "data": data,
            }

            if callback_type == "resync":
                payload["type"] = "resync"

            return requests.post(
                callback_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {trust_secret}",
                    "Content-Type": "application/json",
                },
            )

        def send_out_of_order(
            self,
            to_actor: dict,
            from_actor_id: str,
            subscription_id: str,
            sequences: list[int],
            trust_secret: str,
        ) -> list[requests.Response]:
            """Send multiple callbacks with specified sequence order."""
            responses = []
            for seq in sequences:
                resp = self.send(
                    to_actor=to_actor,
                    from_actor_id=from_actor_id,
                    subscription_id=subscription_id,
                    sequence=seq,
                    data={"test_seq": seq},
                    trust_secret=trust_secret,
                )
                responses.append(resp)
            return responses

    return CallbackSender()


@pytest.fixture
def remote_store_verifier():
    """
    Helper fixture for verifying RemotePeerStore contents.
    """

    class RemoteStoreVerifier:
        def get_stored_data(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
        ) -> dict:
            """Get all data stored for a peer in the remote store."""
            # Access internal attributes via devtest endpoint
            bucket = f"remote:{peer_id}"
            response = requests.get(
                f"{actor_url}/devtest/attributes/{bucket}",
                auth=actor_auth,
            )
            if response.status_code == 200:
                return response.json()
            return {}

        def verify_data_exists(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
            key: str,
        ) -> bool:
            """Check if specific data exists in remote store."""
            data = self.get_stored_data(actor_url, actor_auth, peer_id)
            return key in data

        def verify_list_exists(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
            list_name: str,
        ) -> bool:
            """Check if a list exists in the remote store."""
            data = self.get_stored_data(actor_url, actor_auth, peer_id)
            return f"list:{list_name}:meta" in data

        def get_callback_state(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
            subscription_id: str,
        ) -> dict:
            """Get callback processor state for a subscription."""
            bucket = "_callback_state"
            key = f"state:{peer_id}:{subscription_id}"
            response = requests.get(
                f"{actor_url}/devtest/attributes/{bucket}/{key}",
                auth=actor_auth,
            )
            if response.status_code == 200:
                return response.json()
            return {}

        def get_all_callback_state(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
        ) -> dict:
            """Get all callback state for an actor."""
            bucket = "_callback_state"
            response = requests.get(
                f"{actor_url}/devtest/attributes/{bucket}",
                auth=actor_auth,
            )
            if response.status_code == 200:
                return response.json()
            return {}

    return RemoteStoreVerifier()
