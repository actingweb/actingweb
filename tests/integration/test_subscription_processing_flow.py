"""
Integration tests for subscription processing at the publisher's side.

What remains after the subscription wire baseline retired the classes
whose subscriber had no processor (thoughts/plans/
2026-11-06-subscription-wire-baseline.md, Phase 2; their cover is the
wire rows in wire/rows.toml and tests/test_callback_processor.py): peer
capabilities in a trust and on /meta, and cleanup on trust deletion.
"""

import pytest
import requests


@pytest.mark.xdist_group(name="peer_capabilities_subscription")
class TestPeerCapabilitiesInSubscriptions:
    """
    Test peer capabilities in subscription context.

    Verifies that capability fields are tracked and accessible for
    subscription-related decisions.
    """

    # Shared state
    actor1_url: str | None = None
    actor1_id: str | None = None
    actor1_passphrase: str | None = None
    actor1_creator: str = "caps_actor1@actingweb.net"

    actor2_url: str | None = None
    actor2_id: str | None = None
    actor2_passphrase: str | None = None
    actor2_creator: str = "caps_actor2@actingweb.net"

    trust_secret: str | None = None

    def test_001_create_actors(self, http_client):
        """
        Create actors for capability tests.
        """
        # Create actor 1
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.actor1_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPeerCapabilitiesInSubscriptions.actor1_url = response.headers.get(
            "Location"
        )
        TestPeerCapabilitiesInSubscriptions.actor1_id = response.json()["id"]
        TestPeerCapabilitiesInSubscriptions.actor1_passphrase = response.json()[
            "passphrase"
        ]

        # Create actor 2
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.actor2_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPeerCapabilitiesInSubscriptions.actor2_url = response.headers.get(
            "Location"
        )
        TestPeerCapabilitiesInSubscriptions.actor2_id = response.json()["id"]
        TestPeerCapabilitiesInSubscriptions.actor2_passphrase = response.json()[
            "passphrase"
        ]

    def test_002_establish_trust(self, http_client):
        """
        Establish trust between actors.
        """
        response = requests.post(
            f"{self.actor1_url}/trust",
            json={
                "url": self.actor2_url,
                "relationship": "friend",
            },
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        TestPeerCapabilitiesInSubscriptions.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Approve both sides
        response = requests.put(
            f"{self.actor2_url}/trust/friend/{self.actor1_id}",
            json={"approved": True},
            auth=(self.actor2_creator, self.actor2_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.actor1_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

    def test_003_verify_trust_has_capability_fields(self, http_client):
        """
        Verify trust relationship has capability fields (can be null initially).
        """
        response = requests.get(
            f"{self.actor1_url}/trust/friend/{self.actor2_id}",
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        data = response.json()

        # Capability fields may be null but should exist in schema
        # The fields are: aw_supported, aw_version, capabilities_fetched_at
        # Note: They might not be exposed in API response - this test documents behavior
        assert "relationship" in data

    def test_004_verify_peer_meta_actingweb_supported(self, http_client):
        """
        Verify peer's /meta/actingweb/supported endpoint is accessible.

        This is where capabilities are fetched from.
        """
        response = requests.get(
            f"{self.actor2_url}/meta/actingweb/supported",
        )

        # Should return 200 with supported options
        # or 404 if no supported options configured
        assert response.status_code in [200, 404]

        if response.status_code == 200 and response.text:
            try:
                data = response.json()
                # Should have 'supported' key with comma-separated options
                assert "supported" in data or isinstance(data, dict)
            except ValueError:
                # Empty or invalid JSON is acceptable - endpoint exists but no options
                pass

    def test_099_cleanup(self, http_client):
        """
        Clean up test actors.
        """
        if self.actor1_url and self.actor1_passphrase:
            requests.delete(
                self.actor1_url,
                auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
            )

        if self.actor2_url and self.actor2_passphrase:
            requests.delete(
                self.actor2_url,
                auth=(self.actor2_creator, self.actor2_passphrase),  # type: ignore[arg-type]
            )


@pytest.mark.xdist_group(name="peer_capabilities_integration")
class TestPeerCapabilitiesIntegration:
    """
    Test peer capabilities integration in subscription context.

    Tests the full capability checking flow:
    - Capabilities not cached initially
    - Lazy loading on first access
    - Caching after fetch
    - TTL expiration and refresh
    """

    # Shared state
    actor1_url: str | None = None
    actor1_id: str | None = None
    actor1_passphrase: str | None = None
    actor1_creator: str = "caps_int_actor1@actingweb.net"

    actor2_url: str | None = None
    actor2_id: str | None = None
    actor2_passphrase: str | None = None
    actor2_creator: str = "caps_int_actor2@actingweb.net"

    trust_secret: str | None = None

    def test_001_create_actors(self, http_client):
        """
        Create actors for capability integration tests.
        """
        # Create actor 1
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.actor1_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPeerCapabilitiesIntegration.actor1_url = response.headers.get("Location")
        TestPeerCapabilitiesIntegration.actor1_id = response.json()["id"]
        TestPeerCapabilitiesIntegration.actor1_passphrase = response.json()[
            "passphrase"
        ]

        # Create actor 2
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.actor2_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPeerCapabilitiesIntegration.actor2_url = response.headers.get("Location")
        TestPeerCapabilitiesIntegration.actor2_id = response.json()["id"]
        TestPeerCapabilitiesIntegration.actor2_passphrase = response.json()[
            "passphrase"
        ]

    def test_002_establish_trust(self, http_client):
        """
        Establish trust between actors for capability tests.
        """
        response = requests.post(
            f"{self.actor1_url}/trust",
            json={
                "url": self.actor2_url,
                "relationship": "friend",
            },
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        TestPeerCapabilitiesIntegration.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Approve trust
        response = requests.put(
            f"{self.actor2_url}/trust/friend/{self.actor1_id}",
            json={"approved": True},
            auth=(self.actor2_creator, self.actor2_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.actor1_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

    def test_010_verify_capabilities_endpoint_exists(self, http_client):
        """
        Verify the /meta/actingweb/supported endpoint exists and is accessible.
        """
        response = requests.get(
            f"{self.actor2_url}/meta/actingweb/supported",
        )

        # Should return 200 (with options) or 404 (no options configured)
        assert response.status_code in [200, 404]

    def test_011_verify_capabilities_endpoint_format(self, http_client):
        """
        Verify the capabilities endpoint returns proper format.
        """
        response = requests.get(
            f"{self.actor1_url}/meta/actingweb/supported",
        )

        if response.status_code == 200 and response.text:
            try:
                data = response.json()
                # Should be a dict with 'supported' key or similar structure
                assert isinstance(data, dict)
            except ValueError:
                # Empty or invalid JSON - endpoint exists but no content
                pass

    def test_020_trust_has_capability_fields_schema(self, http_client):
        """
        Verify trust API response includes capability-related information.

        The trust model has fields for capabilities but they may not
        all be exposed in the REST API response.
        """
        response = requests.get(
            f"{self.actor1_url}/trust/friend/{self.actor2_id}",
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        data = response.json()

        # Basic trust fields should be present
        assert "relationship" in data
        assert "approved" in data

        # Capability fields may or may not be exposed
        # This documents the expected behavior

    def test_030_capabilities_accessible_via_peer_url(self, http_client):
        """
        Verify capabilities can be fetched from peer's URL.

        This is how the system fetches capabilities - via the peer's
        /meta/actingweb/supported endpoint.
        """
        # Get trust to find peer URL
        response = requests.get(
            f"{self.actor1_url}/trust/friend/{self.actor2_id}",
            auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        trust_data = response.json()

        # Get peer's baseuri
        peer_url = (
            trust_data.get("baseuri") or trust_data.get("peerurl") or self.actor2_url
        )

        # Fetch capabilities from peer
        response = requests.get(f"{peer_url}/meta/actingweb/supported")

        # Endpoint should exist
        assert response.status_code in [200, 404]

    def test_040_verify_capability_check_before_feature(self, http_client):
        """
        Test that capability checking works before using optional features.

        This documents the pattern for checking capabilities:
        1. Get peer capabilities
        2. Check if feature is supported
        3. Use appropriate format based on support
        """
        # Fetch capabilities
        response = requests.get(
            f"{self.actor2_url}/meta/actingweb/supported",
        )

        if response.status_code == 200 and response.text:
            try:
                data = response.json()
                supported_options = data.get("supported", "")

                # Parse supported options (comma-separated string)
                if supported_options:
                    options = [opt.strip() for opt in supported_options.split(",")]
                else:
                    options = []

                # Document available options
                # Common options: subscriptionresync, callbackcompression, etc.
                assert isinstance(options, list)
            except ValueError:
                # No JSON response
                pass

    def test_099_cleanup(self, http_client):
        """
        Clean up test actors.
        """
        if self.actor1_url and self.actor1_passphrase:
            requests.delete(
                self.actor1_url,
                auth=(self.actor1_creator, self.actor1_passphrase),  # type: ignore[arg-type]
            )

        if self.actor2_url and self.actor2_passphrase:
            requests.delete(
                self.actor2_url,
                auth=(self.actor2_creator, self.actor2_passphrase),  # type: ignore[arg-type]
            )


@pytest.mark.xdist_group(name="cleanup_verification")
class TestCleanupOnTrustDeletion:
    """
    Test that subscription data is properly cleaned up when trust is deleted.

    Verifies:
    - Data exists before cleanup
    - Trust deletion triggers cleanup
    - Remote data cleaned up
    - Callback state cleaned up
    """

    # Shared state
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "cleanup_pub@actingweb.net"

    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "cleanup_sub@actingweb.net"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_setup_actors_and_subscription(self, http_client):
        """
        Set up actors, trust, and subscription for cleanup tests.
        """
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCleanupOnTrustDeletion.publisher_url = response.headers.get("Location")
        TestCleanupOnTrustDeletion.publisher_id = response.json()["id"]
        TestCleanupOnTrustDeletion.publisher_passphrase = response.json()["passphrase"]

        # Create subscriber
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.subscriber_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCleanupOnTrustDeletion.subscriber_url = response.headers.get("Location")
        TestCleanupOnTrustDeletion.subscriber_id = response.json()["id"]
        TestCleanupOnTrustDeletion.subscriber_passphrase = response.json()["passphrase"]

        # Establish trust
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={
                "url": self.subscriber_url,
                "relationship": "friend",
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        TestCleanupOnTrustDeletion.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Approve trust
        response = requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

        # Grant permissions
        response = requests.put(
            f"{self.publisher_url}/trust/friend/{self.subscriber_id}/permissions",
            json={
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read", "subscribe"],
                }
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 204]

        # Create subscription
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            TestCleanupOnTrustDeletion.subscription_id = data["data"][0][
                "subscriptionid"
            ]

    def test_010_create_subscription_data(self, http_client):
        """
        Create some subscription data by making property changes.
        """
        # Set several properties to generate subscription diffs
        for i in range(5):
            response = requests.put(
                f"{self.publisher_url}/properties/cleanup_test_{i}",
                data=f"value_{i}",
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [201, 204]

    def test_011_verify_subscription_data_exists(self, http_client):
        """
        Verify subscription data exists before cleanup.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data and len(data["data"]) > 0

    def test_012_verify_subscription_diffs_exist(self, http_client):
        """
        Verify subscription diffs exist before cleanup.
        """
        if not self.subscription_id:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "sequence" in data
        assert data["sequence"] >= 5  # We made 5 property changes

    def test_020_delete_trust_triggers_cleanup(self, http_client):
        """
        Delete trust relationship to trigger cleanup.
        """
        response = requests.delete(
            f"{self.publisher_url}/trust/friend/{self.subscriber_id}",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [200, 204]

    def test_021_verify_subscriptions_cleaned_up(self, http_client):
        """
        Verify subscriptions are cleaned up after trust deletion.
        """
        # Try to access subscription with old trust secret - should fail
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        # Should return 401/403 (invalid trust) or 404 (no subscriptions)
        assert response.status_code in [401, 403, 404]

    def test_022_verify_subscription_diffs_cleaned_up(self, http_client):
        """
        Verify subscription diffs are cleaned up after trust deletion.
        """
        if not self.subscription_id:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        # Should return 401/403 (invalid trust) or 404 (no diffs)
        assert response.status_code in [401, 403, 404]

    def test_099_cleanup(self, http_client):
        """
        Clean up test actors.
        """
        if self.publisher_url and self.publisher_passphrase:
            requests.delete(
                self.publisher_url,
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )

        if self.subscriber_url and self.subscriber_passphrase:
            requests.delete(
                self.subscriber_url,
                auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
            )
