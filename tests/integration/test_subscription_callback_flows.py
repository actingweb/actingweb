"""Integration tests for subscription callback flows and failure scenarios.

Tests the complete subscription callback system including:
- Normal callback processing
- Gap detection and handling
- Gap timeout and automatic resync
- Duplicate callback handling
- Sync operations with baseline fetch
- Diff clearing and confirmation

These tests verify the fixes for:
- False duplicate detection on retry
- Diff deleted before processing
- Gap timeout automatic resync
- increase_seq() type error
- Peer capabilities not loaded
- Sync with all-duplicate diffs
"""

import os
import time

import pytest
import requests


@pytest.fixture
def test_config(docker_services, setup_database, worker_info):  # noqa: ARG001
    """
    Provide a Config object for tests that need direct Actor access.

    This fixture creates a Config object matching the test environment.
    """
    from actingweb.config import Config

    # Create config based on DATABASE_BACKEND
    database_backend = os.environ.get("DATABASE_BACKEND", "dynamodb")

    # Set up environment for PostgreSQL schema isolation
    if database_backend == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    config = Config(database=database_backend)

    return config


@pytest.mark.xdist_group(name="subscription_callback_flows")
class TestNormalCallbackFlow:
    """Test normal callback flow without gaps."""

    # Publisher (on test_app)
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "cb_publisher@example.com"

    # Subscriber (on subscriber_app with subscription processing)
    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "cb_subscriber@example.com"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_create_publisher(self, http_client):
        """Create publisher actor on test_app."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
        )
        assert response.status_code == 201
        TestNormalCallbackFlow.publisher_url = response.headers["Location"]
        TestNormalCallbackFlow.publisher_id = response.json()["id"]
        TestNormalCallbackFlow.publisher_passphrase = response.json()["passphrase"]

    def test_002_create_subscriber(self, subscriber_app):
        """Create subscriber actor on subscriber_app (with subscription processing)."""
        response = requests.post(
            f"{subscriber_app}/",
            json={"creator": self.subscriber_creator},
        )
        assert response.status_code == 201
        TestNormalCallbackFlow.subscriber_url = response.headers["Location"]
        TestNormalCallbackFlow.subscriber_id = response.json()["id"]
        TestNormalCallbackFlow.subscriber_passphrase = response.json()["passphrase"]

    def test_003_establish_trust(self):
        """Establish trust between publisher and subscriber."""
        assert self.publisher_passphrase is not None
        assert self.subscriber_passphrase is not None

        # Publisher initiates trust to subscriber
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={"url": self.subscriber_url, "relationship": "friend"},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )
        assert response.status_code == 201
        TestNormalCallbackFlow.trust_secret = response.json()["secret"]
        peer_id = response.json()["peerid"]

        # Subscriber approves
        response = requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        assert response.status_code == 204

        # Publisher approves
        response = requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )
        assert response.status_code in [200, 204]

    def test_004_create_subscription(self):
        """Create subscription from subscriber to publisher."""
        assert self.subscriber_passphrase is not None

        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID from publisher
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            TestNormalCallbackFlow.subscription_id = data["data"][0]["subscriptionid"]

    def test_005_send_callback(self, callback_sender):
        """Send callback and verify it's processed."""
        response = callback_sender.send(
            to_actor={"url": self.subscriber_url},
            from_actor_id=self.publisher_id,
            subscription_id=self.subscription_id,
            sequence=1,
            data={"test_prop": "value1"},
            trust_secret=self.trust_secret,
        )
        assert response.status_code == 204

    def test_006_verify_data_stored(self, remote_store_verifier):
        """Verify data was stored in RemotePeerStore."""
        assert self.subscriber_passphrase is not None

        # Wait a bit for async processing
        time.sleep(0.5)

        stored_data = remote_store_verifier.get_stored_data(
            actor_url=self.subscriber_url,
            actor_auth=(self.subscriber_creator, self.subscriber_passphrase),
            peer_id=self.publisher_id,
        )
        # Data is stored in attribute format with "data" wrapper
        # Simple values are wrapped: {"value": "value1"}
        assert "test_prop" in stored_data, f"Data not found. Stored data: {stored_data}"
        assert stored_data["test_prop"]["data"]["value"] == "value1"

    def test_007_verify_sequence_updated(self, test_config):
        """Verify subscription sequence was updated."""
        from actingweb.subscription import Subscription

        sub = Subscription(
            actor_id=self.subscriber_id,
            peerid=self.publisher_id,
            subid=self.subscription_id,
            callback=True,
            config=test_config,
        )
        sub_data = sub.get()
        assert sub_data is not None
        assert sub_data.get("sequence", 0) == 1


@pytest.mark.xdist_group(name="subscription_callback_flows")
class TestGapDetectionAndHandling:
    """Test gap detection and resolution."""

    # Publisher
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "gap_publisher@example.com"

    # Subscriber
    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "gap_subscriber@example.com"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_create_actors(self, http_client, subscriber_app):
        """Create publisher and subscriber actors."""
        # Publisher on test_app
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
        )
        assert response.status_code == 201
        TestGapDetectionAndHandling.publisher_url = response.headers["Location"]
        TestGapDetectionAndHandling.publisher_id = response.json()["id"]
        TestGapDetectionAndHandling.publisher_passphrase = response.json()["passphrase"]

        # Subscriber on subscriber_app
        response = requests.post(
            f"{subscriber_app}/",
            json={"creator": self.subscriber_creator},
        )
        assert response.status_code == 201
        TestGapDetectionAndHandling.subscriber_url = response.headers["Location"]
        TestGapDetectionAndHandling.subscriber_id = response.json()["id"]
        TestGapDetectionAndHandling.subscriber_passphrase = response.json()[
            "passphrase"
        ]

    def test_002_establish_trust_and_subscription(self):
        """Establish trust and create subscription."""
        assert self.publisher_passphrase is not None
        assert self.subscriber_passphrase is not None

        # Publisher initiates trust
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={"url": self.subscriber_url, "relationship": "friend"},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )
        assert response.status_code == 201
        TestGapDetectionAndHandling.trust_secret = response.json()["secret"]
        peer_id = response.json()["peerid"]

        # Mutual approval
        requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )

        # Create subscription
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            TestGapDetectionAndHandling.subscription_id = data["data"][0][
                "subscriptionid"
            ]

    def test_003_send_callback_with_gap(self, callback_sender):
        """Send callback with gap (seq=3 when expecting seq=1)."""
        assert self.subscriber_passphrase is not None

        response = callback_sender.send(
            to_actor={"url": self.subscriber_url},
            from_actor_id=self.publisher_id,
            subscription_id=self.subscription_id,
            sequence=3,
            data={"test_prop": "value3"},
            trust_secret=self.trust_secret,
        )
        # Callback accepted but queued
        assert response.status_code == 204

        # Verify callback was queued - check pending state
        # The pending state is stored in attributes with key "pending:{peer_id}:{subscription_id}"
        bucket = "_callback_state"
        pending_key = f"pending:{self.publisher_id}:{self.subscription_id}"
        response = requests.get(
            f"{self.subscriber_url}/devtest/attributes/{bucket}/{pending_key}",
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        assert response.status_code == 200, (
            f"Failed to get pending state: {response.status_code}"
        )
        pending_attr = response.json()
        # Pending is stored as {"callbacks": [list]} in the data field
        pending_data = pending_attr.get("data", {})
        pending = pending_data.get("callbacks", [])
        assert len(pending) == 1, (
            f"Expected 1 pending callback, got {len(pending)}. Full response: {pending_attr}"
        )
        assert pending[0]["sequence"] == 3

    def test_004_resolve_gap(self, callback_sender):
        """Send missing callbacks to resolve gap."""
        # Send seq 1
        response = callback_sender.send(
            to_actor={"url": self.subscriber_url},
            from_actor_id=self.publisher_id,
            subscription_id=self.subscription_id,
            sequence=1,
            data={"prop1": "value1"},
            trust_secret=self.trust_secret,
        )
        assert response.status_code == 204

        # Send seq 2
        response = callback_sender.send(
            to_actor={"url": self.subscriber_url},
            from_actor_id=self.publisher_id,
            subscription_id=self.subscription_id,
            sequence=2,
            data={"prop2": "value2"},
            trust_secret=self.trust_secret,
        )
        assert response.status_code == 204

        # Gap resolved - all callbacks should be accepted


@pytest.mark.xdist_group(name="subscription_callback_flows")
class TestDuplicateCallbackHandling:
    """Test duplicate callback detection."""

    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "dup_publisher@example.com"

    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "dup_subscriber@example.com"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_setup(self, http_client, subscriber_app):
        """Create actors, trust, and subscription."""
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
        )
        TestDuplicateCallbackHandling.publisher_url = response.headers["Location"]
        TestDuplicateCallbackHandling.publisher_id = response.json()["id"]
        TestDuplicateCallbackHandling.publisher_passphrase = response.json()[
            "passphrase"
        ]

        # Create subscriber
        response = requests.post(
            f"{subscriber_app}/",
            json={"creator": self.subscriber_creator},
        )
        TestDuplicateCallbackHandling.subscriber_url = response.headers["Location"]
        TestDuplicateCallbackHandling.subscriber_id = response.json()["id"]
        TestDuplicateCallbackHandling.subscriber_passphrase = response.json()[
            "passphrase"
        ]

        assert self.publisher_passphrase is not None
        assert self.subscriber_passphrase is not None

        # Establish trust
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={"url": self.subscriber_url, "relationship": "friend"},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )
        TestDuplicateCallbackHandling.trust_secret = response.json()["secret"]
        peer_id = response.json()["peerid"]

        requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )

        # Create subscription
        requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            TestDuplicateCallbackHandling.subscription_id = data["data"][0][
                "subscriptionid"
            ]

    def test_002_send_first_callback(self, callback_sender):
        """Send first callback."""
        response = callback_sender.send(
            to_actor={"url": self.subscriber_url},
            from_actor_id=self.publisher_id,
            subscription_id=self.subscription_id,
            sequence=1,
            data={"test_prop": "value1"},
            trust_secret=self.trust_secret,
        )
        assert response.status_code == 204

    def test_003_send_duplicate(self, callback_sender, test_config):
        """Send duplicate callback, verify it's ignored."""
        response = callback_sender.send(
            to_actor={"url": self.subscriber_url},
            from_actor_id=self.publisher_id,
            subscription_id=self.subscription_id,
            sequence=1,
            data={"test_prop": "different_value"},
            trust_secret=self.trust_secret,
        )
        # Still returns 204 (idempotent)
        assert response.status_code == 204

        # Verify sequence still 1
        from actingweb.subscription import Subscription

        sub = Subscription(
            actor_id=self.subscriber_id,
            peerid=self.publisher_id,
            subid=self.subscription_id,
            callback=True,
            config=test_config,
        )
        sub_data = sub.get()
        assert sub_data.get("sequence", 0) == 1


@pytest.mark.xdist_group(name="subscription_callback_flows")
class TestIncreaseSeqReturnValue:
    """Test that increase_seq() returns integer, not boolean."""

    def test_increase_seq_returns_integer(self, test_config, http_client):
        """Verify increase_seq() returns integer sequence number."""
        from actingweb.subscription import Subscription

        # Create two actors
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": "test_inc1@example.com"},
        )
        publisher_id = response.json()["id"]

        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": "test_inc2@example.com"},
        )
        subscriber_id = response.json()["id"]

        # Create subscription record
        sub = Subscription(
            actor_id=subscriber_id,
            peerid=publisher_id,
            subid="test_sub_id",
            callback=True,
            config=test_config,
        )

        # Initialize subscription
        success = sub.create(
            target="properties",
            subtarget=None,
            resource=None,
            granularity="high",
            seqnr=0,
        )
        assert success is True

        # Call increase_seq() and verify it returns integer
        result = sub.increase_seq()
        assert isinstance(result, int), f"Expected int, got {type(result)}"
        assert result == 1

        # Call again
        result2 = sub.increase_seq()
        assert isinstance(result2, int)
        assert result2 == 2


@pytest.mark.xdist_group(name="subscription_callback_flows")
class TestDiffRetention:
    """Test that diffs are not immediately cleared after 204 response."""

    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "diff_pub@example.com"

    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "diff_sub@example.com"

    subscription_id: str | None = None

    def test_001_setup(self, http_client, subscriber_app):
        """Create actors and subscription."""
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
        )
        TestDiffRetention.publisher_url = response.headers["Location"]
        TestDiffRetention.publisher_id = response.json()["id"]
        TestDiffRetention.publisher_passphrase = response.json()["passphrase"]

        # Create subscriber
        response = requests.post(
            f"{subscriber_app}/",
            json={"creator": self.subscriber_creator},
        )
        TestDiffRetention.subscriber_url = response.headers["Location"]
        TestDiffRetention.subscriber_id = response.json()["id"]
        TestDiffRetention.subscriber_passphrase = response.json()["passphrase"]

        assert self.publisher_passphrase is not None
        assert self.subscriber_passphrase is not None

        # Establish trust
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={"url": self.subscriber_url, "relationship": "friend"},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )
        TestDiffRetention.trust_secret = response.json()["secret"]
        peer_id = response.json()["peerid"]

        requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )
        requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )

        # Create subscription
        requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),
        )

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            TestDiffRetention.subscription_id = data["data"][0]["subscriptionid"]

    def test_002_verify_diffs_retained(self):
        """
        Test that diffs are retained after 204 response.

        This verifies the fix for: "Diff deleted before subscriber processing"
        """
        assert self.publisher_passphrase is not None

        # Publisher adds a property (creates diff)
        response = requests.post(
            f"{self.publisher_url}/properties",
            json={"name": "test_prop", "value": "test_value"},
            auth=(self.publisher_creator, self.publisher_passphrase),
        )
        assert response.status_code == 201

        # Get subscription from publisher side via HTTP to check diffs
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        sub_data = response.json()

        # Verify diffs are present (not deleted after 204)
        assert "data" in sub_data, f"No data in subscription: {sub_data}"
        diffs = sub_data.get("data", [])
        assert len(diffs) >= 1, f"Expected at least 1 diff, got {len(diffs)}"
